"""LLM 优化等价轮/质量轮回放 runner（ADR-001）。

在冻结样本上离线运行两阶段分析，产出记录到指定目录：
  uv run python scripts/run_llm_equiv_round.py --label llm-opt --profile opt1opt2
  uv run python scripts/run_llm_equiv_round.py --label baseline --profile baseline

profile 决定 llm_opt 开关（内存覆盖，不改 settings.json）：
  baseline : kline_summary=False, prompt_reorder=False（等价于 main 行为）
  opt1opt2 : ①② 开
  tier     : ③ 开（+①②）
  dual     : ④ 开（+①②）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "fixtures" / "llm_opt"

PROFILES: dict[str, dict[str, bool]] = {
    "baseline": {"kline_summary": False, "prompt_reorder": False},
    "opt1opt2": {"kline_summary": True, "prompt_reorder": True},
    "tier": {"kline_summary": True, "prompt_reorder": True, "reasoning_tier": True},
    "dual": {"kline_summary": True, "prompt_reorder": True, "dual_model": True},
}


def build_frame(payload: dict):
    from pa_agent.data.base import KlineBar
    from pa_agent.data.snapshot import build_display_frame

    bars = [
        KlineBar(
            seq=i + 1,
            ts_open=b["ts_open"],
            open=b["open"],
            high=b["high"],
            low=b["low"],
            close=b["close"],
            volume=b["volume"],
            closed=True,
        )
        for i, b in enumerate(payload["bars"])  # fixture 最新优先
    ]
    return build_display_frame(bars, 100, payload["symbol"], payload["timeframe"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="输出子目录名（如 baseline / llm-opt）")
    ap.add_argument("--profile", default="opt1opt2", choices=sorted(PROFILES))
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个样本（调试用）")
    args = ap.parse_args()

    from pa_agent.ai.client_factory import create_ai_client
    from pa_agent.ai.prompt_assembler import PromptAssembler
    from pa_agent.ai.router import route_strategy_files
    from pa_agent.ai.json_validator import JsonValidator
    from pa_agent.config.paths import EXPERIENCE_DIR, PROMPT_DIR, SETTINGS_JSON_PATH
    from pa_agent.config.settings import load_settings, save_settings
    from pa_agent.orchestrator.two_stage import TwoStageOrchestrator
    from pa_agent.records.pending_writer import PendingWriter
    from pa_agent.util.threading import CancelToken

    settings = load_settings(SETTINGS_JSON_PATH)
    overrides = PROFILES[args.profile]
    for k, v in overrides.items():
        setattr(settings.llm_opt, k, v)

    out_dir = ROOT / "data" / "llm_round" / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "profile.json").write_text(
        json.dumps({"profile": args.profile, **overrides}, ensure_ascii=False), encoding="utf-8"
    )

    client = create_ai_client(settings.provider)
    assembler = PromptAssembler(
        prompt_dir=PROMPT_DIR, llm_opt_settings=settings.llm_opt
    )
    validator = JsonValidator(settings.validation)

    fixtures = sorted(FIXTURES.glob("*.json"))
    if args.limit:
        fixtures = fixtures[: args.limit]
    print(f"profile={args.profile} | 样本 {len(fixtures)} 个 → {out_dir}")

    done = 0
    for fp in fixtures:
        payload = json.loads(fp.read_text(encoding="utf-8"))
        out_file = out_dir / f"{payload['symbol']}.json"
        if out_file.exists():
            print(f"  跳过（已存在）: {payload['symbol']}")
            done += 1
            continue
        frame = build_frame(payload)
        if frame is None:
            print(f"  {payload['symbol']}: frame 构建失败")
            continue

        pending_dir = out_dir / "_pending"
        pending_dir.mkdir(exist_ok=True)
        from pa_agent.records.pending_writer import PendingWriter as PW

        pending = PW(str(pending_dir))
        exp_reader = None
        from pa_agent.records.experience_reader import ExperienceReader

        exp_reader = ExperienceReader(experience_dir=ROOT / "experience")

        orchestrator = TwoStageOrchestrator(
            client=client,
            assembler=assembler,
            router=route_strategy_files,
            validator=validator,
            pending_writer=pending,
            exp_reader=exp_reader,
            settings=settings,
            llm_opt=settings.llm_opt,
        )
        t0 = time.perf_counter()
        try:
            record = orchestrator.submit(
                frame=frame,
                cancel_token=type("T", (), {"is_set": lambda self: False, "set": lambda self: None})(),
                on_event=lambda e: None,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  {payload['symbol']}: 异常 {str(exc)[:100]}")
            continue
        dt = time.perf_counter() - t0

        usage = getattr(record, "usage_total", None)
        dec = (record.stage2_decision or {}).get("decision", {})
        out = {
            "symbol": payload["symbol"],
            "elapsed_s": round(dt, 1),
            "usage": usage and usage.model_dump() or None,
            "gate_result": (record.stage1_diagnosis or {}).get("gate_result"),
            "cycle_position": (record.stage1_diagnosis or {}).get("cycle_position"),
            "decision": {
                k: dec.get(k)
                for k in ("order_type", "order_direction", "entry_price", "stop_loss_price",
                          "take_profit_price", "take_profit_price_2", "trade_confidence")
            },
        }
        out_file.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        done += 1
        print(f"  {payload['symbol']}: {dt:.0f}s tokens={getattr(usage, 'total_tokens', '?')}")
        time.sleep(1.0)  # 请求间礼貌间隔
    print(f"完成 {done}/{len(fixtures)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
