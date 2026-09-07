import { useStore } from '../store'

const LABELS = ['数据', '快照', '诊断', '决策', '追问']
const GLYPHS = ['⌁', '▤', '☰', '⚖', '↩']

export default function FlowBar() {
  const steps = useStore((s) => s.flowSteps)
  return (
    <div className="flow-bar">
      {LABELS.map((label, i) => {
        const step = steps[i] ?? { status: 'idle' as const, caption: label }
        return (
          <div key={label} style={{ display: 'contents' }}>
            <div className={`flow-step ${step.status}`}>
              <div className="flow-dot">{GLYPHS[i]}</div>
              <div className="flow-caption">{step.caption}</div>
            </div>
            {i < LABELS.length - 1 && <div className="flow-link" />}
          </div>
        )
      })}
    </div>
  )
}
