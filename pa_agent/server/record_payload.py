"""Build the frontend panel payload from a finished AnalysisRecord.

Ports the panel-update logic of ``_on_record_ready_impl`` /
``_on_analysis_finished`` to one JSON-safe dict: decision panel, future-trend
panel, decision tree + flow-viz traces, chart overlays, summary strip,
prompt files, debug turns and token display.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pa_agent.ai.response_extract import reasoning_from_response

logger = logging.getLogger(__name__)


def build_record_payload(state: Any, record: Any) -> dict[str, Any]:
    settings = state.settings()
    stage1_diag = getattr(record, "stage1_diagnosis", None)
    stage1_diag = stage1_diag if isinstance(stage1_diag, dict) else {}
    s2_full = getattr(record, "stage2_decision", None)
    s2_full = s2_full if isinstance(s2_full, dict) else {}
    exc_info = getattr(record, "exception", None)

    skip_next_bar = False
    if settings is not None:
        skip_next_bar = not bool(
            getattr(settings.general, "enable_next_bar_prediction", False)
        )

    from pa_agent.services.stage2_payload import prepare_stage2_for_ui

    inner = prepare_stage2_for_ui(
        s2_full, stage1_json=stage1_diag or None, skip_next_bar=skip_next_bar
    )

    cooldown = 3
    if settings is not None:
        cooldown = int(
            getattr(settings.general, "structure_flip_cooldown_bars", 3) or 3
        )
    from pa_agent.services.chart_decision_overlay import (
        enrich_decision_for_chart_overlay,
    )

    chart_decision = enrich_decision_for_chart_overlay(
        inner,
        stage2_full=s2_full or None,
        frame=getattr(state, "last_analysis_frame", None),
        stage1_json=stage1_diag or None,
        previous_record=getattr(state, "analysis_previous_record", None),
        cooldown_bars=cooldown,
    )

    stance = None
    meta = getattr(record, "meta", None)
    if meta is not None:
        stance = getattr(meta, "decision_stance", None)
    elif settings is not None:
        stance = getattr(settings.general, "decision_stance", None)

    return {
        "decision_inner": inner,
        "diagnosis_summary": s2_full.get("diagnosis_summary"),
        "stage1_diagnosis": stage1_diag or None,
        "decision_stance": stance,
        "confidence_threshold": _confidence_threshold(settings),
        "chart_decision": chart_decision,
        "support_resistance": _chart_levels(stage1_diag),
        "summary_metrics": _summary_metrics(s2_full, stage1_diag),
        "tree_trace": _tree_trace(s2_full, stage1_diag),
        "debug_turns": _debug_turns(record, exc_info),
        "stage_results": _stage_results(record),
        "prompt_files": _prompt_files(record),
        "token_display": _token_display(record, settings),
        "exception": exc_info,
        "stage2_full": s2_full,
        "order_type": inner.get("order_type", "—") if inner else "—",
    }


def _confidence_threshold(settings: Any) -> int:
    if settings is None:
        return 0
    return int(getattr(settings.general, "decision_confidence_threshold", 0))


def _chart_levels(stage1_diag: dict) -> list[dict[str, Any]]:
    try:
        from pa_agent.services.support_resistance import (
            chart_levels_from_stage1_diagnosis,
        )

        return [
            {
                "kind": lv.kind,
                "low": lv.low,
                "high": lv.high,
                "label": lv.label,
                "price": lv.price,
            }
            for lv in chart_levels_from_stage1_diagnosis(stage1_diag)
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("chart levels failed: %s", exc)
        return []


def _summary_metrics(stage2_full: dict, stage1_diag: dict) -> dict[str, str]:
    from pa_agent.ai.cycle_enums import (
        format_cycle_with_direction,
        format_trend_label,
    )
    from pa_agent.services.analysis_flow import best_probability_key
    from pa_agent.services.support_resistance import (
        nearest_support_resistance_labels,
    )

    diag = stage2_full.get("diagnosis_summary") or {}
    cur_cycle = diag.get("cycle_position") or ""
    cur_cycle_zh = format_cycle_with_direction(cur_cycle, diag.get("direction"))

    next_cycle_zh = "—"
    ncp = stage2_full.get("next_cycle_prediction") or {}
    probs = ncp.get("probabilities") or {}
    if probs:
        best_key = best_probability_key(probs)
        if best_key:
            next_cycle_zh = format_cycle_with_direction(best_key, ncp.get("direction"))
    else:
        cycle_key = ncp.get("cycle")
        if cycle_key:
            next_cycle_zh = format_cycle_with_direction(cycle_key, ncp.get("direction"))

    cur_trend_zh = format_trend_label(diag.get("direction"), cur_cycle)
    sup_label, res_label = nearest_support_resistance_labels(stage1_diag)
    return {
        "当前趋势": cur_trend_zh,
        "当前市场周期": cur_cycle_zh,
        "下一个市场周期": next_cycle_zh,
        "支撑区": sup_label,
        "阻力区": res_label,
    }


def _tree_trace(stage2_full: dict, stage1_diag: dict) -> dict[str, Any]:
    from pa_agent.ai.decision_tree import (
        format_trace_answer,
        merge_traces,
        normalize_bar_range,
    )

    merged = merge_traces(
        stage1_diag.get("gate_trace"), stage2_full.get("decision_trace")
    )
    path: list[dict[str, Any]] = []
    for i, item in enumerate(merged, start=1):
        if not isinstance(item, dict) or not item.get("node_id"):
            continue
        path.append(
            {
                "step": i,
                "phase": item.get("phase", ""),
                "node_id": str(item.get("node_id", "")),
                "question": str(item.get("question", "") or ""),
                "answer": format_trace_answer(item),
                "bar_basis": normalize_bar_range(item),
                "reasoning": str(item.get("reasoning", "") or ""),
                "skipped": bool(item.get("skipped")),
            }
        )

    terminal = stage2_full.get("terminal")
    banner: dict[str, Any] | None = None
    if isinstance(terminal, dict) and terminal.get("node_id"):
        outcome = str(terminal.get("outcome", ""))
        banner = {
            "node_id": str(terminal.get("node_id", "")),
            "outcome": outcome,
            "label": str(terminal.get("label", "") or ""),
        }
    gate_result = stage1_diag.get("gate_result")
    if banner is None and gate_result in ("wait", "unknown"):
        banner = {"node_id": "", "outcome": str(gate_result), "label": ""}

    return {
        "path": path,
        "terminal": terminal if isinstance(terminal, dict) else None,
        "banner": banner,
        "gate_result": gate_result,
        "gate_shortcircuited": bool(stage2_full.get("gate_shortcircuited")),
    }


def _debug_turns(record: Any, exc_info: dict | None) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    exc_json = json.dumps(exc_info, ensure_ascii=False, indent=2) if exc_info else ""

    s1_msgs = getattr(record, "stage1_messages", []) or []
    s1_system = next((m.get("content", "") for m in s1_msgs if m.get("role") == "system"), "")
    s1_user = next((m.get("content", "") for m in s1_msgs if m.get("role") == "user"), "")
    s1_raw = getattr(record, "stage1_response", {}) or {}
    s1_diag = getattr(record, "stage1_diagnosis", None)
    if exc_info and exc_info.get("stage") == "stage1":
        s1_validation = exc_json
    elif s1_diag:
        s1_validation = json.dumps(s1_diag, ensure_ascii=False, indent=2)
    else:
        s1_validation = "（验证失败或无数据）"
    turns.append(
        {
            "label": "Stage1 诊断",
            "system_prompt": s1_system,
            "user_prompt": s1_user,
            "raw_response": s1_raw,
            "validation_info": s1_validation,
        }
    )

    s2_msgs = getattr(record, "stage2_messages", []) or []
    s2_system = next((m.get("content", "") for m in s2_msgs if m.get("role") == "system"), "")
    s2_user = next(
        (m.get("content", "") for m in reversed(s2_msgs) if m.get("role") == "user"), ""
    )
    s2_raw = getattr(record, "stage2_response", {}) or {}
    s2_decision = getattr(record, "stage2_decision", None)
    if exc_info and exc_info.get("stage") == "stage2":
        s2_validation = exc_json
    elif s2_decision:
        s2_validation = json.dumps(s2_decision, ensure_ascii=False, indent=2)
    else:
        s2_validation = "（验证失败或无数据）"
    turns.append(
        {
            "label": "Stage2 决策",
            "system_prompt": s2_system,
            "user_prompt": s2_user,
            "raw_response": s2_raw,
            "validation_info": s2_validation,
        }
    )

    if exc_info:
        turns.append(
            {
                "label": "⚠ 异常",
                "system_prompt": "",
                "user_prompt": "",
                "raw_response": {},
                "validation_info": exc_json,
            }
        )
    return turns


def _stage_results(record: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    s1_diag = getattr(record, "stage1_diagnosis", None)
    s1_raw = getattr(record, "stage1_response", {}) or {}
    if s1_diag:
        out.append(
            {
                "stage": "stage1",
                "title": "阶段一：市场诊断",
                "content": json.dumps(s1_diag, ensure_ascii=False, indent=2),
                "reasoning": reasoning_from_response(s1_raw if isinstance(s1_raw, dict) else None),
                "cache_hit_pct": (s1_raw.get("usage") or {}).get("cache_hit_rate_pct")
                if isinstance(s1_raw, dict)
                else None,
            }
        )
    s2_decision = getattr(record, "stage2_decision", None)
    s2_raw = getattr(record, "stage2_response", {}) or {}
    if s2_decision:
        out.append(
            {
                "stage": "stage2",
                "title": "阶段二：交易决策",
                "content": json.dumps(s2_decision, ensure_ascii=False, indent=2),
                "reasoning": reasoning_from_response(s2_raw if isinstance(s2_raw, dict) else None),
                "cache_hit_pct": (s2_raw.get("usage") or {}).get("cache_hit_rate_pct")
                if isinstance(s2_raw, dict)
                else None,
            }
        )
    return out


def _prompt_files(record: Any) -> dict[str, Any]:
    from pa_agent.ai.prompt_assembler import (
        stage1_prompt_txt_files,
        stage2_prompt_txt_files,
    )

    strategy = getattr(record, "strategy_files_used", None) or []
    experience = getattr(record, "experience_loaded", None) or []
    return {
        "stage1": stage1_prompt_txt_files(),
        "stage2": stage2_prompt_txt_files(strategy),
        "experience_count": len(experience),
    }


def _token_display(record: Any, settings: Any) -> dict[str, int] | None:
    usage_total = getattr(record, "usage_total", {}) or {}
    if not usage_total:
        return None
    context_window = 1_000_000
    if settings is not None:
        context_window = (
            getattr(settings.provider, "context_window", 1_000_000) or 1_000_000
        )
    prompt_tokens = usage_total.get("prompt_tokens", 0)
    cached_tokens = usage_total.get("cached_prompt_tokens", 0)
    completion_tokens = usage_total.get("completion_tokens", 0)
    total_tokens = usage_total.get("total_tokens", 0) or (
        prompt_tokens + completion_tokens
    )
    return {
        "context_used": total_tokens,
        "context_window": context_window,
        "total_input": prompt_tokens,
        "total_cached_input": cached_tokens,
        "total_output": completion_tokens,
    }
