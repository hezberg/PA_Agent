// 移动端「分析」视图：决策票 + 标签页（实时/详情/未来预期/更多）。
import { useEffect, useState } from 'react'
import { useStore } from '../store'
import DecisionTicket from './DecisionTicket'
import StreamTab from './tabs/StreamTab'
import DecisionTab from './tabs/DecisionTab'
import FutureTrendTab from './tabs/FutureTrendTab'
import RawTab from './tabs/RawTab'

type TabKey = 'stream' | 'detail' | 'future' | 'raw'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'detail', label: '详情' },
  { key: 'stream', label: '实时' },
  { key: 'future', label: '未来' },
  { key: 'raw', label: '原始' },
]

export default function AnalysisView() {
  const [tab, setTab] = useState<TabKey>('detail')
  const decision = useStore((s) => s.decision)
  const panes = useStore((s) => s.panes)
  const streaming = useStore((s) => s.streaming)

  // 新结果到达时停在「详情」；无结果时引导看「实时」
  const isEmpty = !decision && panes.length === 0 && !streaming
  useEffect(() => {
    if (decision) setTab('detail')
  }, [decision])

  return (
    <section className="m-analysis">
      <DecisionTicket />
      <nav className="tabs m-tabs">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? 'active' : ''} onClick={() => setTab(t.key)}>
            {t.label}
            {t.key === 'stream' && streaming && <span className="badge" />}
          </button>
        ))}
      </nav>
      <div className="tab-body m-tab-body">
        {isEmpty ? (
          <div className="muted" style={{ padding: 16 }}>还没有分析结果——点上方「分析」开始第一轮。</div>
        ) : tab === 'stream' ? (
          <StreamTab />
        ) : tab === 'detail' ? (
          <DecisionTab />
        ) : tab === 'future' ? (
          <FutureTrendTab />
        ) : (
          <RawTab />
        )}
      </div>
    </section>
  )
}
