"""对比两个回放轮的决策输出，按 ADR-001 口径生成报告。

  uv run python scripts/compare_llm_round.py --baseline data/llm_round/baseline --opt data/llm_round/llm-opt
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# 字段 → 位置（runner 输出结构）
TOP_EXACT = ["gate_result", "cycle_position"]  # 顶层，完全一致
DEC_EXACT = ["order_direction", "order_type"]  # decision 内，完全一致
PRICE_FIELDS = ["entry_price", "stop_loss_price", "take_profit_price", "take_profit_price_2"]
TOL = 0.005  # ±0.5%


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="data/llm_round/baseline")
    ap.add_argument("--opt", default="data/llm_round/llm-opt")
    args = ap.parse_args()

    base = {p.stem: json.loads(p.read_text()) for p in Path(args.baseline).glob("*.json")}
    opt = {p.stem: json.loads(p.read_text()) for p in Path(args.opt).glob("*.json")}
    common = sorted(set(base) & set(opt))
    print(f"基线 {len(base)} | 优化 {len(opt)} | 共同 {len(common)}\n")

    rows, mismatch = [], []
    for sym in common:
        b, o = base[sym], opt[sym]
        bd, od = b.get("decision") or {}, o.get("decision") or {}
        row = {"symbol": sym, "fields": []}
        ok = True

        def cmp(label, bv, ov, tol=False):
            nonlocal ok
            if bv is None and ov is None:
                row[label] = "—"
                return
            if bv is None or ov is None:
                row[label] = f"✗ 缺({bv}→{ov})"
                ok = False
                return
            if tol:
                diff = abs(float(ov) - float(bv)) / max(abs(float(bv)), 1e-9)
                good = diff <= TOL
                row[label] = f"{'✓' if good else '✗'} {bv:.4g}→{ov:.4g}"
            else:
                good = bv == ov
                row[label] = "✓" if good else f"✗ {bv}→{ov}"
            if not good:
                ok = False

        for f in TOP_EXACT:
            cmp(f, b.get(f), o.get(f))
        for f in DEC_EXACT:
            cmp(f, bd.get(f), od.get(f))
        for f in PRICE_FIELDS:
            short = {"entry_price": "入", "stop_loss_price": "止",
                     "take_profit_price": "TP1", "take_profit_price_2": "TP2"}[f]
            cmp(short, num(bd.get(f)), num(od.get(f)), tol=True)

        row["OK"] = ok
        row["_fields"] = dict(row)
        rows.append(row)
        if not ok:
            mismatch.append(sym)

    tb = sum((b.get("usage") or {}).get("total_tokens") or 0 for b in base.values())
    to = sum((o.get("usage") or {}).get("total_tokens") or 0 for o in opt.values())
    tb_s = sum(b.get("elapsed_s") or 0 for b in base.values())
    to_s = sum(o.get("elapsed_s") or 0 for o in opt.values())

    n = len(rows)
    ok_n = sum(1 for r in rows if r["OK"])
    rate = ok_n / n * 100 if n else 0
    print(f"决策级等价: {ok_n}/{n} = {rate:.0f}%  （通过线 95%）")
    print(f"tokens: 基线 {tb / 1e6:.2f}M vs 优化 {to / 1e6:.2f}M ({(to - tb) / max(tb, 1) * 100:+.0f}%)")
    print(f"耗时:   基线 {tb_s:.0f}s vs 优化 {to_s:.0f}s ({(to_s - tb_s) / max(tb_s, 1) * 100:+.0f}%)\n")
    for r in rows:
        f = r.pop("_fields")
        flag = "✓" if r["OK"] else "✗"
        detail = " ".join(f"{k}:{v}" for k, v in f.items() if k not in ("symbol", "OK"))
        print(f"  {flag} {r['symbol']:<8} {detail}")
    if mismatch:
        print(f"\n不一致个案（需归因复核）: {mismatch}")
    print(f"\n结论: {'✅ 通过' if n and rate >= 95 else '❌ 未通过'}")
    return 0 if n and rate >= 95 else 1


if __name__ == "__main__":
    raise SystemExit(main())
