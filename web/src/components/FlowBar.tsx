// 会话条：仅分析进行时渲染。五步 stepper + 上下文用量，替代原常驻 FlowBar。
import { useStore, FLOW_STEPS } from '../store'

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return String(n)
}

export default function FlowBar() {
  const steps = useStore((s) => s.flowSteps)
  const ui = useStore((s) => s.ui)
  const streaming = useStore((s) => s.streaming)
  const decision = useStore((s) => s.decision)

  if (!(ui?.analysis_in_progress || streaming)) return null

  const ledger = decision?.token_display ?? null
  const pct = ledger && ledger.context_window > 0 ? Math.min(100, (ledger.context_used / ledger.context_window) * 100) : 0

  return (
    <div className="session-strip">
      <div className="stepper">
        {FLOW_STEPS.map((label, i) => {
          const step = steps[i] ?? { status: 'idle' as const, caption: label }
          return (
            <div key={label} style={{ display: 'contents' }}>
              <div className={`st ${step.status}`}>
                <div className="dot">{step.status === 'done' ? '✓' : i + 1}</div>
                <span className="cap">{step.caption || label}</span>
              </div>
              {i < FLOW_STEPS.length - 1 && <div className={`st-link${step.status === 'done' ? ' done' : ''}`} />}
            </div>
          )
        })}
      </div>
      {ledger && (
        <div className="token-meter">
          <div className="bar">
            <div style={{ width: `${pct}%` }} />
          </div>
          <span className="nums mono">
            上下文 {fmt(ledger.context_used)} / {fmt(ledger.context_window)} · {pct.toFixed(0)}%
          </span>
        </div>
      )}
    </div>
  )
}
