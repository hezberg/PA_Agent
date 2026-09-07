"""OpenAI-compatible LLM client (the only AI route after the 2026-09 slim-down).

Standard protocol only — no per-vendor special-casing:
- thinking on  → top-level ``reasoning_effort`` parameter (o-series convention)
- thinking off → no reasoning parameter, ``temperature=0`` for JSON fidelity
- usage        → standard ``prompt_tokens_details.cached_tokens``
- reasoning    → standard ``delta.reasoning_content`` streaming field

Contract consumed by the orchestrators (do not change casually):
``stream_chat(messages, on_reasoning_token=, on_content_token=, cancel_token=,
reasoning_effort=) -> AIReply`` and the ``AIUsage`` / ``AIReply`` /
``CancelledError`` types.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from pa_agent.util.threading import CancelToken

from pa_agent.config.settings import AIProviderSettings

try:
    from openai import OpenAI as _OpenAI  # type: ignore[import]
except ImportError as _exc:  # pragma: no cover - openai is a hard dependency
    _OpenAI = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# Completion budget sent with every request. Generous on purpose: analysis JSON
# plus thinking must fit. Gateways with lower caps may 400 — the error surfaces
# verbatim in the 原始 debug tab.
_MAX_OUTPUT_TOKENS = 384_000

# Minimal reasoning length below which we warn (caught misconfigurations).
_SHORT_REASONING_CHARS = 80


@dataclass
class AIUsage:
    """Token usage from a single API call (standard OpenAI fields)."""

    prompt_tokens: int = 0
    cached_prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of prompt tokens served from provider KV cache (0.0–1.0)."""
        if self.prompt_tokens <= 0:
            return 0.0
        return self.cached_prompt_tokens / self.prompt_tokens

    @property
    def cache_miss_tokens(self) -> int:
        """Prompt tokens that were NOT served from cache (billed at full rate)."""
        return max(0, self.prompt_tokens - self.cached_prompt_tokens)


@dataclass
class AIReply:
    """Structured response from a single AI API call."""

    content: str
    reasoning_content: str
    raw: dict[str, Any]          # full raw response dict for the 原始 debug tab
    usage: AIUsage
    request_id: str
    latency_ms: float


class CancelledError(Exception):
    """Raised when a cancel_token is set before or during an API call."""


def _extract_cached_prompt_tokens(usage: Any) -> int:
    """Read cached prompt tokens from the standard OpenAI usage field."""
    if usage is None:
        return 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", 0)
        if cached:
            return int(cached)
    return 0


def _resolve_effort(
    settings: AIProviderSettings,
    thinking: bool | None,
    reasoning_effort: str | None,
) -> str | None:
    """Effective reasoning_effort for this call; None when thinking is off."""
    _thinking = settings.thinking if thinking is None else thinking
    if not _thinking:
        return None
    effort = settings.reasoning_effort if reasoning_effort is None else reasoning_effort
    return effort or "high"


class DeepSeekClient:
    """Thin streaming client for any OpenAI-compatible endpoint."""

    def __init__(
        self, settings: AIProviderSettings, logger_: logging.Logger | None = None
    ) -> None:
        self._settings = settings
        self._log = logger_ or logging.getLogger(__name__)

    def update_provider(self, settings: AIProviderSettings) -> None:
        self._settings = settings

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        on_reasoning_token: Callable[[str], None] | None = None,
        on_content_token: Callable[[str], None] | None = None,
        thinking: bool | None = None,
        reasoning_effort: str | None = None,
        cancel_token: "CancelToken | None" = None,
        timeout_s: float = 600.0,
    ) -> AIReply:
        """Stream *messages* and return an :class:`AIReply` when complete.

        - ``reasoning_content`` deltas arrive first (thinking), then content.
        - Raises :class:`CancelledError` when *cancel_token* is set before or
          during the call.
        - Never sends temperature/top_p/presence_penalty while thinking is on.
        """
        if cancel_token is not None and cancel_token.is_set():
            raise CancelledError("Request cancelled before API call")
        if _OpenAI is None:  # pragma: no cover - openai is a hard dependency
            raise RuntimeError("openai package is not installed")

        effort = _resolve_effort(self._settings, thinking, reasoning_effort)
        thinking_on = effort is not None

        self._log.info(
            "stream_chat: model=%s base_url=%s thinking=%s effort=%s msgs=%d",
            self._settings.model,
            self._settings.base_url,
            thinking_on,
            effort,
            len(messages),
        )

        client = _OpenAI(
            base_url=self._settings.base_url,
            api_key=self._settings.api_key,
        )

        create_kwargs: dict[str, Any] = {
            "model": self._settings.model,
            "messages": messages,
            "timeout": timeout_s,
            "max_tokens": _MAX_OUTPUT_TOKENS,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if effort is not None:
            create_kwargs["reasoning_effort"] = effort
        else:
            # Thinking off: temperature=0 for maximum JSON instruction fidelity.
            create_kwargs["temperature"] = 0

        t0 = time.monotonic()
        reasoning_content = ""
        content = ""
        request_id = ""
        model_name = ""
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        cached_tokens = 0

        try:
            try:
                stream = client.chat.completions.create(**create_kwargs)
            except Exception:
                # Some providers reject stream_options — retry without it.
                self._log.debug("stream_options rejected; retrying without it")
                create_kwargs.pop("stream_options", None)
                stream = client.chat.completions.create(**create_kwargs)

            for chunk in stream:
                if cancel_token is not None and cancel_token.is_set():
                    raise CancelledError("Request cancelled during streaming")

                if getattr(chunk, "usage", None) is not None:
                    u = chunk.usage
                    prompt_tokens = getattr(u, "prompt_tokens", 0) or prompt_tokens
                    completion_tokens = (
                        getattr(u, "completion_tokens", 0) or completion_tokens
                    )
                    total_tokens = getattr(u, "total_tokens", 0) or total_tokens
                    cached_tokens = (
                        _extract_cached_prompt_tokens(u) or cached_tokens
                    )

                if not getattr(chunk, "choices", None):
                    continue
                request_id = request_id or (getattr(chunk, "id", "") or "")
                model_name = model_name or (getattr(chunk, "model", "") or "")

                delta = getattr(chunk.choices[0], "delta", None)
                if delta is None:
                    continue

                r = getattr(delta, "reasoning_content", None)
                if r:
                    reasoning_content += r
                    if on_reasoning_token is not None:
                        on_reasoning_token(r)
                elif delta.content:
                    content += delta.content
                    if on_content_token is not None:
                        on_content_token(delta.content)

        except CancelledError:
            raise
        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            self._log.error("stream error after %.0f ms: %s", latency_ms, exc)
            raise

        latency_ms = (time.monotonic() - t0) * 1000
        usage = AIUsage(
            prompt_tokens=prompt_tokens,
            cached_prompt_tokens=cached_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        raw: dict[str, Any] = {
            "id": request_id,
            "model": model_name,
            "content": content,
            "reasoning_content": reasoning_content,
            "usage": {
                "prompt_tokens": usage.prompt_tokens,
                "cached_prompt_tokens": usage.cached_prompt_tokens,
                "cache_miss_tokens": usage.cache_miss_tokens,
                "cache_hit_rate_pct": round(usage.cache_hit_rate * 100, 1),
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            },
            "latency_ms": latency_ms,
        }

        self._log.info(
            "stream_chat done: latency=%.0f ms reasoning_chars=%d content_chars=%d",
            latency_ms,
            len(reasoning_content),
            len(content),
        )
        if not content.strip():
            self._log.warning(
                "API returned empty content (model=%s base_url=%s) — "
                "check the 原始 tab Raw Response.",
                self._settings.model,
                self._settings.base_url,
            )
        if thinking_on and len(reasoning_content) < _SHORT_REASONING_CHARS:
            self._log.warning(
                "Thinking enabled but reasoning_content is short (%d chars) — "
                "check the endpoint honours reasoning_effort=%s.",
                len(reasoning_content),
                effort,
            )

        return AIReply(
            content=content,
            reasoning_content=reasoning_content,
            raw=raw,
            usage=usage,
            request_id=request_id,
            latency_ms=latency_ms,
        )


def supports_kv_prefix_chain(settings: AIProviderSettings | None) -> bool:
    """Stage 2 may chain after Stage 1 messages (KV prefix cache friendly).

    Always True on the standard protocol — chaining is just a longer message
    list and every OpenAI-compatible endpoint accepts it.
    """
    return True
