// 决策票：AI 决策结果的一览卡（方向 / 信心 / 价位 / 盈亏比条），常驻侧栏顶部。
import { useState } from 'react'
import { useStore } from '../store'
import { useSymbolName } from '../symbolName'
import { ChevronDownIcon } from '../icons'

const SUMMARY_KEYS = ['当前趋势', '当前市场周期', '下一个市场周期', '支撑区', '阻力区'] as const

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isNaN(n) ? null : n
}

function str(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  return String(v)
}

function directionClass(text: string): 'up' | 'down' | '' {
  if (/多|涨|long|bull/i.test(text)) return 'up'
  if (/空|跌|short|bear/i.test(text)) return 'down'
  return ''
}

export default function DecisionTicket() {
  const decision = useStore((s) => s.decision)
  const metaSymbol = useStore((s) => s.meta?.symbol ?? '')
  const symbolName = useSymbolName(metaSymbol)
  const [folded, setFolded] = useState(false)
  if (!decision || !decision.decision_inner || Object.keys(decision.decision_inner).length === 0) {
    return null
  }

  const d = decision.decision_inner as Record<string, unknown>
  const orderType = str(d.order_type)
  const direction = str(d.order_direction)
  const dirCls = directionClass(`${direction} ${orderType}`)
  const isNoOrder = orderType.includes('不下单') || orderType.includes('观望')

  const entry = num(d.entry_price)
  const stop = num(d.stop_loss_price)
  const tp1 = num(d.take_profit_price)
  const risk = entry !== null && stop !== null ? entry - stop : null
  const reward = entry !== null && tp1 !== null ? tp1 - entry : null
  const showBar =
    risk !== null && reward !== null && risk > 0 && reward > 0
      ? { riskPct: (risk / (risk + reward)) * 100, risk, reward }
      : null

  const confidence = num(d.trade_confidence)
  const threshold = decision.confidence_threshold ?? 0
  const metrics = decision.summary_metrics ?? {}

  return (
    <>
      <div className={`ticket${folded ? ' folded' : ''}`}>
        <div className="ticket-head">
          {metaSymbol && (
            <span className="ticket-symbol">
              {symbolName ? `${symbolName} ` : ''}
              <span className="mono">{metaSymbol}</span>
            </span>
          )}
          <span className={`ticket-dir ${isNoOrder ? '' : dirCls}`} style={isNoOrder ? { color: 'var(--warning)' } : undefined}>
            {isNoOrder ? '观望' : direction !== '—' ? direction : orderType}
          </span>
          <span className="ticket-sub">
            {orderType}
            {decision.decision_stance ? ` · 倾向 ${decision.decision_stance}` : ''}
          </span>
          <div className="ticket-meta">
            {confidence !== null && (
              <span className="chip info">
                信心 {confidence}%{threshold > 0 ? ` ≥ 阈值 ${threshold}%` : ''}
              </span>
            )}
            {d.risk_reward_ratio ? <span className="chip amber mono">盈亏比 {str(d.risk_reward_ratio)}</span> : null}
            <button className="ticket-fold" aria-label={folded ? '展开决策票' : '折叠决策票'} onClick={() => setFolded((v) => !v)}>
              <ChevronDownIcon />
            </button>
          </div>
        </div>
        <div className="ticket-body">
          {isNoOrder ? (
            <div className="stage-content">{str(d.reasoning)}</div>
          ) : (
            <>
              <div className="prices">
                <div className="pc"><div className="k">入场</div><div className="v">{str(d.entry_price)}</div></div>
                <div className="pc"><div className="k">止损</div><div className="v down">{str(d.stop_loss_price)}</div></div>
                <div className="pc"><div className="k">止盈 TP1</div><div className="v up">{str(d.take_profit_price)}</div></div>
                <div className="pc"><div className="k">止盈 TP2</div><div className="v up">{str(d.take_profit_price_2)}</div></div>
              </div>
              {showBar && (
                <div className="rr-bar-wrap">
                  <div className="rr-bar">
                    <div className="risk" style={{ width: `${showBar.riskPct}%` }} />
                    <div className="reward" style={{ width: `${100 - showBar.riskPct}%` }} />
                  </div>
                  <div className="rr-legend">
                    <span><i style={{ background: 'var(--chart-down)' }} />风险 {showBar.risk.toFixed(2)}（绿跌）</span>
                    <span><i style={{ background: 'var(--chart-up)' }} />收益 {showBar.reward.toFixed(2)}（红涨）</span>
                    <span style={{ marginLeft: 'auto' }}>以入场价为原点 · 按 TP1 计</span>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
      <div className="chips-row">
        {SUMMARY_KEYS.map((key) => (
          <span className="schip" key={key}>
            {key} <b>{metrics[key] || '—'}</b>
          </span>
        ))}
      </div>
    </>
  )
}
