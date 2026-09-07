import { useStore } from '../store'

export default function StatusBar() {
  const statusText = useStore((s) => s.statusText)
  const demoName = useStore((s) => s.demoName)
  const meta = useStore((s) => s.meta)
  return (
    <div className="status-bar">
      {demoName && <span className="demo-label">当前为演示模式 · {demoName}</span>}
      <span>{statusText || '就绪'}</span>
      <span style={{ flex: 1 }} />
      {meta && (
        <span>
          {meta.active_label} · {meta.symbol} {meta.timeframe}
          {meta.source_connected ? '' : '（未连接）'}
        </span>
      )}
    </div>
  )
}
