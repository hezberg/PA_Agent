"""Unit tests for the slimmed OpenAI-compatible DeepSeekClient (2026-09 精简版).

Standard protocol only: reasoning_effort top-level param, standard usage fields,
streaming with per-chunk cancellation. The OpenAI SDK is mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pa_agent.ai.deepseek_client import (
    AIReply,
    AIUsage,
    CancelledError,
    DeepSeekClient,
    _extract_cached_prompt_tokens,
    supports_kv_prefix_chain,
)
from pa_agent.config.settings import AIProviderSettings
from pa_agent.util.threading import CancelToken


def _make_settings(**overrides) -> AIProviderSettings:
    s = AIProviderSettings()
    s.api_key = "sk-test-1234abcd"
    s.base_url = "https://relay.example.com/v1"
    s.model = "gpt-test"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _fake_usage(prompt=100, completion=50, total=150, cached=20):
    usage = MagicMock()
    usage.prompt_tokens = prompt
    usage.completion_tokens = completion
    usage.total_tokens = total
    usage.prompt_tokens_details = MagicMock()
    usage.prompt_tokens_details.cached_tokens = cached
    return usage


class FakeStreamChunk:
    def __init__(self, *, delta=None, usage=None, chunk_id="req-1", model="m"):
        self.choices = [MagicMock(delta=delta)] if delta is not None else []
        self.usage = usage
        self.id = chunk_id
        self.model = model


class FakeDelta:
    def __init__(self, reasoning=None, content=None):
        self.reasoning_content = reasoning
        self.content = content


def _make_client(settings=None) -> tuple[DeepSeekClient, MagicMock]:
    """Return (client, mock OpenAI constructor) with a scripted stream."""
    client = DeepSeekClient(settings or _make_settings())

    chunks = [
        FakeStreamChunk(delta=FakeDelta(reasoning="思考"), chunk_id="req-1", model="gpt-test"),
        FakeStreamChunk(delta=FakeDelta(content="你好")),
        FakeStreamChunk(usage=_fake_usage()),
    ]
    fake_openai = MagicMock()
    fake_openai.return_value.chat.completions.create.return_value = iter(chunks)
    return client, fake_openai


# ── Contract: streaming + callbacks + usage ───────────────────────────────────

def test_stream_chat_returns_ai_reply_with_standard_usage() -> None:
    client, fake_openai = _make_client()
    with patch("pa_agent.ai.deepseek_client._OpenAI", fake_openai):
        reply = client.stream_chat([{"role": "user", "content": "hi"}])

    assert isinstance(reply, AIReply)
    assert reply.content == "你好"
    assert reply.reasoning_content == "思考"
    assert reply.usage.prompt_tokens == 100
    assert reply.usage.cached_prompt_tokens == 20
    assert reply.usage.completion_tokens == 50
    assert reply.usage.total_tokens == 150
    assert reply.usage.cache_hit_rate == pytest.approx(0.2)
    assert reply.request_id == "req-1"


def test_stream_chat_drives_both_callbacks() -> None:
    client, fake_openai = _make_client()
    reasoning: list[str] = []
    content: list[str] = []
    with patch("pa_agent.ai.deepseek_client._OpenAI", fake_openai):
        client.stream_chat(
            [{"role": "user", "content": "hi"}],
            on_reasoning_token=reasoning.append,
            on_content_token=content.append,
        )
    assert reasoning == ["思考"]
    assert content == ["你好"]


# ── Thinking / reasoning_effort semantics ─────────────────────────────────────

def test_thinking_on_sends_standard_reasoning_effort_param() -> None:
    settings = _make_settings(thinking=True, reasoning_effort="high")
    client, fake_openai = _make_client(settings)
    with patch("pa_agent.ai.deepseek_client._OpenAI", fake_openai):
        client.stream_chat([{"role": "user", "content": "hi"}])

    kwargs = fake_openai.return_value.chat.completions.create.call_args.kwargs
    assert kwargs["reasoning_effort"] == "high"
    assert "temperature" not in kwargs
    assert "extra_body" not in kwargs          # 无厂商 extra_body
    assert kwargs["max_tokens"] == 384_000     # 全局唯一上限，无 per-vendor 分支


def test_thinking_off_omits_reasoning_and_sets_temperature_zero() -> None:
    settings = _make_settings(thinking=False)
    client, fake_openai = _make_client(settings)
    with patch("pa_agent.ai.deepseek_client._OpenAI", fake_openai):
        client.stream_chat([{"role": "user", "content": "hi"}])

    kwargs = fake_openai.return_value.chat.completions.create.call_args.kwargs
    assert "reasoning_effort" not in kwargs
    assert kwargs["temperature"] == 0


def test_call_level_overrides_settings() -> None:
    settings = _make_settings(thinking=True, reasoning_effort="high")
    client, fake_openai = _make_client(settings)
    with patch("pa_agent.ai.deepseek_client._OpenAI", fake_openai):
        client.stream_chat(
            [{"role": "user", "content": "hi"}],
            thinking=False,
        )
    kwargs = fake_openai.return_value.chat.completions.create.call_args.kwargs
    assert "reasoning_effort" not in kwargs
    assert kwargs["temperature"] == 0


# ── Cancellation ──────────────────────────────────────────────────────────────

def test_cancelled_before_call_raises() -> None:
    client, _ = _make_client()
    token = CancelToken()
    token.set()
    with pytest.raises(CancelledError):
        client.stream_chat([{"role": "user", "content": "hi"}], cancel_token=token)


def test_cancelled_mid_stream_raises() -> None:
    client, fake_openai = _make_client()
    token = CancelToken()

    chunks = [
        FakeStreamChunk(delta=FakeDelta(content="a")),
        FakeStreamChunk(delta=FakeDelta(content="b")),
    ]

    def _stream_that_allows_cancel(**kwargs):
        token.set()  # 第二个 chunk 前置取消
        return iter(chunks)

    fake_openai.return_value.chat.completions.create.side_effect = _stream_that_allows_cancel
    with patch("pa_agent.ai.deepseek_client._OpenAI", fake_openai):
        with pytest.raises(CancelledError):
            client.stream_chat([{"role": "user", "content": "hi"}], cancel_token=token)


# ── stream_options fallback ───────────────────────────────────────────────────

def test_retries_without_stream_options_when_rejected() -> None:
    client, fake_openai = _make_client()
    calls: list[dict] = []

    def _create(**kwargs):
        calls.append(kwargs)
        if "stream_options" in kwargs:
            raise RuntimeError("stream_options unsupported")
        return iter([FakeStreamChunk(delta=FakeDelta(content="ok"), usage=_fake_usage())])

    fake_openai.return_value.chat.completions.create.side_effect = _create
    with patch("pa_agent.ai.deepseek_client._OpenAI", fake_openai):
        reply = client.stream_chat([{"role": "user", "content": "hi"}])

    assert reply.content == "ok"
    assert len(calls) == 2
    assert "stream_options" not in calls[1]


# ── Usage parsing / misc ──────────────────────────────────────────────────────

def test_extract_cached_tokens_standard_field_only() -> None:
    usage = MagicMock()
    usage.prompt_tokens_details = MagicMock()
    usage.prompt_tokens_details.cached_tokens = 77
    assert _extract_cached_prompt_tokens(usage) == 77
    assert _extract_cached_prompt_tokens(None) == 0
    empty = MagicMock()
    empty.prompt_tokens_details = MagicMock()
    empty.prompt_tokens_details.cached_tokens = 0
    assert _extract_cached_prompt_tokens(empty) == 0


def test_aiusage_cache_helpers() -> None:
    u = AIUsage(prompt_tokens=200, cached_prompt_tokens=50, completion_tokens=10, total_tokens=210)
    assert u.cache_hit_rate == pytest.approx(0.25)
    assert u.cache_miss_tokens == 150
    assert AIUsage().cache_hit_rate == 0.0


def test_kv_prefix_chain_always_supported() -> None:
    assert supports_kv_prefix_chain(None) is True
    assert supports_kv_prefix_chain(_make_settings()) is True


def test_empty_content_still_returns_reply() -> None:
    client, fake_openai = _make_client()
    chunks = [FakeStreamChunk(delta=FakeDelta(content="")), FakeStreamChunk(usage=_fake_usage())]
    fake_openai.return_value.chat.completions.create.return_value = iter(chunks)
    with patch("pa_agent.ai.deepseek_client._OpenAI", fake_openai):
        reply = client.stream_chat([{"role": "user", "content": "hi"}])
    assert reply.content == ""
    assert reply.usage.prompt_tokens == 100
