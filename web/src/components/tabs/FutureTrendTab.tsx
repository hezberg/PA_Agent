import { useStore } from '../../store'

type Pred = {
  direction?: string
  probabilities?: Record<string, unknown>
  cycle?: string
  reasoning?: string
}

function pct(v: unknown): string {
  if (v === null || v === undefined || v === '') return '?'
  return `${v}%`
}

function dominant(probs: Record<string, unknown>): 'bullish' | 'bearish' | 'neutral' | null {
  const entries: [string, number][] = []
  for (const key of ['bullish', 'bearish', 'neutral']) {
    const raw = probs[key]
    if (raw === null || raw === undefined || raw === '') continue
    const n = Number(raw)
    if (!Number.isNaN(n)) entries.push([key, n])
  }
  if (!entries.length) return null
  return entries.sort((a, b) => b[1] - a[1])[0][0] as 'bullish' | 'bearish' | 'neutral'
}

// 红涨绿跌（A 股惯例）：看涨=红、看跌=绿
const COLOR: Record<string, string> = {
  bullish: 'var(--chart-up)',
  bearish: 'var(--chart-down)',
  neutral: 'var(--warning)',
}

export default function FutureTrendTab() {
  const decision = useStore((s) => s.decision)
  const inner = (decision?.decision_inner ?? {}) as Record<string, unknown>
  const nextBar = inner.next_bar_prediction as Pred | null | undefined
  const nextCycle = inner.next_cycle_prediction as Pred | null | undefined

  if (!decision || (!nextBar && !nextCycle)) {
    return (
      <div className="muted" style={{ padding: 12 }}>
        等待分析结果…（可在「其他通用设置」中开启「下一根K线预测」）
      </div>
    )
  }

  return (
    <div>
      {nextBar && (
        <div className="panel-section">
          <div className="panel-title">下一根K线预测</div>
          {nextBar.direction ? (
            <>
              <div className="kv-row">
                <span className="kv-key">主方向</span>
                <span
                  className="kv-value"
                  style={{ color: COLOR[dominant(nextBar.probabilities ?? {}) ?? ''] ?? undefined, fontWeight: 700 }}
                >
                  {dirZh(nextBar.direction)}
                </span>
              </div>
              <div className="kv-row">
                <span className="kv-key">概率</span>
                <span className="kv-value">{probsLine(nextBar.probabilities ?? {})}</span>
              </div>
            </>
          ) : (
            <div className="muted">不可预测（无有效预测输出）</div>
          )}
          {nextBar.reasoning && (
            <div className="kv-row"><span className="kv-key">理由</span><span className="kv-value">{nextBar.reasoning}</span></div>
          )}
        </div>
      )}

      {nextCycle && (
        <div className="panel-section">
          <div className="panel-title">下一个市场周期预测</div>
          <div className="kv-row">
            <span className="kv-key">周期</span>
            <span className="kv-value">
              {cycleZh(nextCycle.cycle)} {nextCycle.direction ? `(${dirZh(nextCycle.direction)})` : ''}
            </span>
          </div>
          {nextCycle.probabilities && (
            <div className="kv-row">
              <span className="kv-key">概率分布</span>
              <span className="kv-value">{probsDetail(nextCycle.probabilities)}</span>
            </div>
          )}
          {nextCycle.reasoning && (
            <div className="kv-row"><span className="kv-key">理由</span><span className="kv-value">{nextCycle.reasoning}</span></div>
          )}
        </div>
      )}
    </div>
  )
}

function dirZh(direction: string): string {
  const map: Record<string, string> = { bullish: '看涨（阳线）', bearish: '看跌（阴线）', neutral: '中性', up: '向上', down: '向下' }
  return map[direction] ?? direction
}

function cycleZh(cycle: string | undefined): string {
  return cycle ?? '—'
}

function probsLine(probs: Record<string, unknown>): string {
  return `阳 ${pct(probs.bullish)} · 阴 ${pct(probs.bearish)} · 中性 ${pct(probs.neutral)}`
}

function probsDetail(probs: Record<string, unknown>): string {
  return Object.entries(probs)
    .map(([k, v]) => `${cycleZh(k)} ${pct(v)}`)
    .join('，')
}
