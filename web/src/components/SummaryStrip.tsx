import { useStore } from '../store'

const KEYS = ['当前趋势', '当前市场周期', '下一个市场周期', '支撑区', '阻力区'] as const

export default function SummaryStrip() {
  const decision = useStore((s) => s.decision)
  const metrics = decision?.summary_metrics ?? {}
  return (
    <div className="summary-strip">
      {KEYS.map((key) => (
        <div className="metric-card" key={key}>
          <div className="metric-label">{key}</div>
          <div className="metric-value">{metrics[key] ?? '—'}</div>
        </div>
      ))}
    </div>
  )
}
