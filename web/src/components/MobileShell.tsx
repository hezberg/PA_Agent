// 移动端骨架：顶栏两行制 + 三主视图（自选/图表/分析）+ 底部 Tab 导航。
// 当前票全局共享：点自选里的票自动跳「图表」。安全区适配刘海屏与浏览器工具栏。
import { useEffect, useRef, useState } from 'react'
import { useStore } from '../store'
import { useIsMobile } from '../useIsMobile'
import MobileTopBar from './MobileTopBar'
import StatusBar from './StatusBar'
import Toasts from './Toasts'
import SettingsModals from './SettingsModals'
import ChartPanel from './ChartPanel'
import WatchlistPanel from './WatchlistPanel'
import AnalysisView from './AnalysisView'

/** 图表数据状态：切票后「获取中→已就绪」全程可见，回答“什么时候能分析”。 */
function ChartDataStatus() {
  const fetchProgress = useStore((s) => s.fetchProgress)
  const frame = useStore((s) => s.frame)
  const metaSymbol = useStore((s) => s.meta?.symbol ?? '')
  const ready = Boolean(frame && frame.symbol === metaSymbol && (frame.bars?.length ?? 0) > 0)
  const text = fetchProgress?.text ?? (ready ? '数据已就绪，可以开始分析' : '等待数据…')
  const stage = fetchProgress?.stage ?? (ready ? 'done' : 'fetching')
  return <div className={`m-fetch-status ${stage}`}>{text}</div>
}

type View = 'watchlist' | 'chart' | 'analysis'

export default function MobileShell() {
  const isMobile = useIsMobile()
  const [view, setView] = useState<View>('watchlist')
  const metaSymbol = useStore((s) => s.meta?.symbol ?? '')
  const lastSymbol = useRef('')

  // 品种变化（点了自选/顶栏搜索）→ 自动跳图表；首帧到达不算
  useEffect(() => {
    if (metaSymbol && lastSymbol.current && metaSymbol !== lastSymbol.current) {
      setView('chart')
    }
    lastSymbol.current = metaSymbol
  }, [metaSymbol])

  if (!isMobile) return null

  const tabs: { key: View; label: string; icon: string }[] = [
    { key: 'watchlist', label: '自选', icon: '☰' },
    { key: 'chart', label: '图表', icon: '📈' },
    { key: 'analysis', label: '分析', icon: '🧠' },
  ]

  return (
    <div className="app m-app">
      <MobileTopBar />
      <main className="m-main">
        {view === 'watchlist' && (
          <>
            <ChartDataStatus />
            <WatchlistPanel />
          </>
        )}
        {view === 'chart' && (
          <section className="m-chartwrap">
            <ChartDataStatus />
            <ChartPanel open onCollapse={() => setView('analysis')} />
          </section>
        )}
        {view === 'analysis' && <AnalysisView />}
      </main>
      <nav className="m-tabbar">
        {tabs.map((t) => (
          <button
            key={t.key}
            className={view === t.key ? 'on' : ''}
            onClick={() => setView(t.key)}
          >
            <span className="m-tab-ico">{t.icon}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </nav>
      <StatusBar mobile />
      <Toasts />
      <SettingsModals />
    </div>
  )
}
