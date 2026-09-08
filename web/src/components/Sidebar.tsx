// 侧栏：决策票（常驻）+ tabs（实时/详情/未来预期/更多）+ 空态引导。
// 分析完成时自动切到「详情」；用户正停留在实时流则不打断。
import { useEffect, useState } from 'react'
import { useStore } from '../store'
import DecisionTicket from './DecisionTicket'
import StreamTab from './tabs/StreamTab'
import DecisionTab from './tabs/DecisionTab'
import TreeTab from './tabs/TreeTab'
import FlowVizTab from './tabs/FlowVizTab'
import FutureTrendTab from './tabs/FutureTrendTab'
import RawTab from './tabs/RawTab'
import PromptFilesTab from './tabs/PromptFilesTab'

const TABS = [
  { key: 'stream', label: '实时' },
  { key: 'detail', label: '详情' },
  { key: 'future', label: '未来预期' },
  { key: 'more', label: '更多 ▾' },
] as const

type TabKey = (typeof TABS)[number]['key']
type MoreView = 'tree' | 'flowviz' | 'raw' | 'prompts'

const MORE_ITEMS: { key: MoreView; label: string; desc: string }[] = [
  { key: 'tree', label: '决策树', desc: '闸门与策略路径文本图' },
  { key: 'flowviz', label: '决策树可视化', desc: '可交互流程图 + 播放动画' },
  { key: 'raw', label: '原始', desc: 'Prompt / 原始响应 JSON' },
  { key: 'prompts', label: '调试', desc: '落盘文件与经验案例' },
]

function EmptyGuide() {
  return (
    <div className="empty-guide">
      <div className="eg-title">三步开始第一轮分析</div>
      <div className="eg-step">
        <div className="eg-num">1</div>
        <div>
          <div className="t">获取数据</div>
          <div className="d">选择数据来源，输入品种代码或名称，点「获取数据」。</div>
        </div>
      </div>
      <div className="eg-step">
        <div className="eg-num">2</div>
        <div>
          <div className="t">开始分析</div>
          <div className="d">点「开始分析」，AI 分两阶段给出市场诊断与交易决策。</div>
        </div>
      </div>
      <div className="eg-step">
        <div className="eg-num">3</div>
        <div>
          <div className="t">自由追问</div>
          <div className="d">分析完成后，在「实时」页底部继续追问任意细节。</div>
        </div>
      </div>
    </div>
  )
}

function MoreMenu({ onView }: { onView: (v: MoreView) => void }) {
  return (
    <div>
      <div className="muted" style={{ marginBottom: 8 }}>
        低频工具已收进二级菜单。
      </div>
      {MORE_ITEMS.map((it) => (
        <button key={it.key} className="menu-item" style={{ width: 'auto' }} onClick={() => onView(it.key)}>
          {it.label}
          <span className="menu-hint">{it.desc}</span>
        </button>
      ))}
    </div>
  )
}

export default function Sidebar() {
  const [tab, setTab] = useState<TabKey>('stream')
  const [moreView, setMoreView] = useState<MoreView | null>(null)
  const streaming = useStore((s) => s.streaming)
  const decision = useStore((s) => s.decision)
  const panes = useStore((s) => s.panes)

  // 新结果到达时切到「详情」；用户正停留在实时流则不打断。
  useEffect(() => {
    if (decision) setTab((t) => (t === 'stream' ? t : 'detail'))
  }, [decision])

  const isEmpty = !decision && panes.length === 0 && !streaming

  function renderBody() {
    if (isEmpty) return <EmptyGuide />
    switch (tab) {
      case 'stream':
        return <StreamTab />
      case 'detail':
        return <DecisionTab />
      case 'future':
        return <FutureTrendTab />
      case 'more':
        if (moreView === null) return <MoreMenu onView={setMoreView} />
        if (moreView === 'tree') return <TreeTab />
        if (moreView === 'flowviz') return <FlowVizTab />
        if (moreView === 'raw') return <RawTab />
        return <PromptFilesTab />
    }
  }

  return (
    <div className="sidebar">
      <DecisionTicket />
      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={tab === t.key ? 'active' : ''}
            onClick={() => {
              setTab(t.key)
              if (t.key === 'more') setMoreView(null) // 每次进「更多」先回到菜单
            }}
          >
            {t.label}
            {t.key === 'stream' && streaming && <span className="badge" />}
          </button>
        ))}
      </nav>
      <div className={`tab-body${tab === 'stream' && !isEmpty ? ' tab-stream' : ''}`}>{renderBody()}</div>
    </div>
  )
}
