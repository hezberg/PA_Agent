import { useStore } from '../../store'
import type { StructureLevel } from '../../api/types'

function pick(obj: Record<string, unknown>, key: string): string {
  const v = obj?.[key]
  if (v === null || v === undefined || v === '') return '—'
  return String(v)
}

export default function DecisionTab() {
  const decision = useStore((s) => s.decision)
  if (!decision || !decision.decision_inner || Object.keys(decision.decision_inner).length === 0) {
    return <div className="muted" style={{ padding: 12 }}>等待分析结果…</div>
  }

  const d = decision.decision_inner as Record<string, unknown>
  const diag = (decision.diagnosis_summary ?? {}) as Record<string, unknown>
  const orderType = String(d.order_type ?? '—')
  const stance = decision.decision_stance ?? '—'

  return (
    <div>
      <div className="panel-section">
        <div className="panel-title">交易决策 · {orderType}</div>
        <Pill text={orderType} />
        <div className="kv-row"><span className="kv-key">方向</span><span className="kv-value">{pick(d, 'order_direction')}</span></div>
        <div className="kv-row"><span className="kv-key">入场价</span><span className="kv-value">{pick(d, 'entry_price')}</span></div>
        <div className="kv-row"><span className="kv-key">止损价</span><span className="kv-value">{pick(d, 'stop_loss_price')}</span></div>
        <div className="kv-row"><span className="kv-key">止盈 TP1</span><span className="kv-value">{pick(d, 'take_profit_price')}</span></div>
        <div className="kv-row"><span className="kv-key">止盈 TP2</span><span className="kv-value">{pick(d, 'take_profit_price_2')}</span></div>
        <div className="kv-row"><span className="kv-key">交易信心</span><span className="kv-value">{tradeConfidence(d, decision.confidence_threshold)}</span></div>
        <div className="kv-row"><span className="kv-key">预期盈亏比</span><span className="kv-value">{pick(d, 'risk_reward_ratio')}</span></div>
        <div className="kv-row"><span className="kv-key">倾向</span><span className="kv-value">{String(stance)}</span></div>
      </div>

      <div className="panel-section">
        <div className="panel-title">市场诊断</div>
        <div className="kv-row"><span className="kv-key">当前周期</span><span className="kv-value">{pick(diag, 'cycle_position')}</span></div>
        <div className="kv-row"><span className="kv-key">方向</span><span className="kv-value">{pick(diag, 'direction')}</span></div>
        <div className="kv-row"><span className="kv-key">阶段判断</span><span className="kv-value">{pick(diag, 'phase')}</span></div>
        <Levels title="支撑位" levels={(decision.stage1_diagnosis?.support_levels as string[]) ?? []} />
        <Levels title="阻力位" levels={(decision.stage1_diagnosis?.resistance_levels as string[]) ?? []} />
      </div>

      <div className="panel-section">
        <div className="panel-title">交易者方程</div>
        <div className="kv-row"><span className="kv-key">突破概率</span><span className="kv-value">{pick(d, 'breakout_probability')}</span></div>
        <div className="kv-row"><span className="kv-key">其余</span><span className="kv-value">
          {`目标 ${pick(d, 'target_price')} · 承担 ${pick(d, 'risk_price')}`}
        </span></div>
        <div className="kv-row"><span className="kv-key">理由</span><span className="kv-value">{pick(d, 'reasoning')}</span></div>
      </div>

      <div className="panel-section">
        <div className="panel-title">失效条件</div>
        <div className="kv-value" style={{ whiteSpace: 'pre-wrap' }}>{pick(d, 'invalidation_condition')}</div>
      </div>
    </div>
  )
}

function tradeConfidence(d: Record<string, unknown>, threshold: number): string {
  const raw = d.trade_confidence
  if (raw === null || raw === undefined || raw === '') return '—'
  let val: number | null = null
  try {
    val = Math.max(0, Math.min(100, Number(raw)))
  } catch {
    return String(raw)
  }
  if (Number.isNaN(val)) return String(raw)
  const pass = threshold > 0 && val >= threshold
  return `${val}% ${pass ? '（≥阈值，通过）' : threshold > 0 ? `（阈值 ${threshold}%）` : ''}`
}

function Pill({ text }: { text: string }) {
  const cls = text.includes('限价') || text.includes('市价') || text.includes('突破')
    ? 'pill green'
    : text === '不下单'
      ? 'pill amber'
      : 'pill blue'
  return <span className={cls} style={{ marginBottom: 6 }}>{text}</span>
}

function Levels({ title, levels }: { title: string; levels: (string | StructureLevel)[] }) {
  if (!levels.length) return null
  return (
    <div className="kv-row">
      <span className="kv-key">{title}</span>
      <span className="kv-value">{levels.map((l) => (typeof l === 'string' ? l : l.label)).join('、')}</span>
    </div>
  )
}
