// 底部状态栏：运行状态 / 刷新计时 / 倒计时 / 品种信息 / 模型 / 免责声明，单行承载。
import { useEffect, useState } from 'react'
import { useStore } from '../store'
import { tfZh, useSymbolName } from '../symbolName'

export default function StatusBar() {
  const statusText = useStore((s) => s.statusText)
  const demoName = useStore((s) => s.demoName)
  const meta = useStore((s) => s.meta)
  const lastRefreshTs = useStore((s) => s.lastRefreshTs)
  const paused = useStore((s) => s.ui?.chart_refresh_paused)
  const waitClose = useStore((s) => s.ui?.wait_close)
  const name = useSymbolName(meta?.symbol)
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  let elapsedLabel = ''
  let elapsedCls = ''
  if (paused) {
    elapsedLabel = '图表刷新已暂停'
    elapsedCls = 'paused'
  } else if (lastRefreshTs > 0) {
    const elapsed = Math.max(0, Math.floor((now - lastRefreshTs) / 1000))
    const m = Math.floor(elapsed / 60)
    const s = elapsed % 60
    elapsedLabel = elapsed < 60 ? `${elapsed}s 前刷新` : `${m}m${String(s).padStart(2, '0')}s 前刷新`
    if (elapsed > 10) elapsedCls = 'stale'
  }

  return (
    <footer className="statusbar">
      <span className={paused ? 'dot-warn' : 'dot-ok'} />
      {demoName && <span className="demo-chip">演示模式 · {demoName}</span>}
      <span className="ellipsis">{statusText || '就绪'}</span>
      {elapsedLabel && <span className={elapsedCls}>{elapsedLabel}</span>}
      {waitClose?.armed && waitClose.seconds_remaining !== null && waitClose.seconds_remaining !== undefined && (
        <span>还剩 {waitClose.seconds_remaining} 秒</span>
      )}
      <span style={{ flex: 1 }} />
      {meta && (
        <span className="ellipsis" title={meta.ai_mode_label}>
          {name && <>{name} </>}
          {meta.symbol} · {tfZh(meta.timeframe)} · {meta.active_label}
          {meta.source_connected ? '' : '（未连接）'}
        </span>
      )}
      {meta?.ai_mode_label && <span className="ellipsis">{meta.ai_mode_label}</span>}
      <span>分析仅供参考，不构成投资建议</span>
    </footer>
  )
}
