import { useStore } from '../../store'
import { zhTerm, termHint } from '../../zhTerms'
import TermTip from '../TermTip'
import type { StructureLevel } from '../../api/types'

function pick(obj: Record<string, unknown>, key: string): string {
  const v = obj?.[key]
  if (v === null || v === undefined || v === '') return '—'
  return String(v)
}

// 枚举值 → 中文展示；悬停/点按显示术语含义（TermTip）
function TermValue({ value }: { value: string | null | undefined }) {
  return <TermTip className="kv-value" text={zhTerm(value)} hint={termHint(value)} />
}

// 详情 tab：决策票之外的完整决策明细（诊断 / 交易者方程 / 失效条件 / 阶段 JSON）。
export default function DecisionTab() {
  const decision = useStore((s) => s.decision)
  if (!decision || !decision.decision_inner || Object.keys(decision.decision_inner).length === 0) {
    return <div className="muted" style={{ padding: 12 }}>等待分析结果…</div>
  }

  const d = decision.decision_inner as Record<string, unknown>
  const diag = (decision.diagnosis_summary ?? {}) as Record<string, unknown>

  return (
    <div>
      <div className="panel-section">
        <div className="panel-title">市场诊断</div>
        <div className="kv-row"><span className="kv-key">当前周期</span><TermValue value={pick(diag, 'cycle_position')} /></div>
        {pick(diag, 'alternative_cycle_position') !== '—' && (
          <div className="kv-row"><span className="kv-key">备选周期</span><TermValue value={pick(diag, 'alternative_cycle_position')} /></div>
        )}
        <div className="kv-row"><span className="kv-key">方向</span><TermValue value={pick(diag, 'direction')} /></div>
        {pick(diag, 'market_phase') !== '—' && (
          <div className="kv-row"><span className="kv-key">状态阶段</span><TermValue value={pick(diag, 'market_phase')} /></div>
        )}
        {pick(diag, 'climax_risk') !== '—' && pick(diag, 'climax_risk') !== 'none' && (
          <div className="kv-row"><span className="kv-key">高潮风险</span><TermValue value={pick(diag, 'climax_risk')} /></div>
        )}
        {pick(diag, 'transition_risk') !== '—' && (
          <div className="kv-row"><span className="kv-key">转换误判风险</span><TermValue value={pick(diag, 'transition_risk')} /></div>
        )}
        {Array.isArray(diag.detected_patterns) && (diag.detected_patterns as string[]).length > 0 && (
          <div className="kv-row">
            <span className="kv-key">检测形态</span>
            <span className="kv-value">
              {(diag.detected_patterns as string[]).map((p, i) => (
              <span key={p + i}>
                {i > 0 && '、'}
                <TermTip text={zhTerm(p)} hint={termHint(p)} />
              </span>
              ))}
            </span>
          </div>
        )}
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

      {decision.stage_results.length > 0 && (
        <div className="panel-section">
          <div className="panel-title">阶段完整输出</div>
          {decision.stage_results.map((sr) => (
            <details key={sr.stage} style={{ marginBottom: 4 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--accent)' }}>
                {sr.title}
              </summary>
              <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '6px 0 0' }}>
                {sr.content}
              </pre>
            </details>
          ))}
        </div>
      )}
    </div>
  )
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
