import { useState } from 'react'
import { useStore } from '../store'
import StreamTab from './tabs/StreamTab'
import DecisionTab from './tabs/DecisionTab'
import TreeTab from './tabs/TreeTab'
import FlowVizTab from './tabs/FlowVizTab'
import FutureTrendTab from './tabs/FutureTrendTab'
import RawTab from './tabs/RawTab'
import PromptFilesTab from './tabs/PromptFilesTab'

const TABS = [
  { key: 'stream', label: '实时' },
  { key: 'decision', label: '决策' },
  { key: 'tree', label: '决策树' },
  { key: 'flowviz', label: '决策树可视化' },
  { key: 'future', label: '未来走势预期' },
  { key: 'raw', label: '原始' },
  { key: 'prompts', label: '调试' },
] as const

type TabKey = (typeof TABS)[number]['key']

export default function Sidebar() {
  const [tab, setTab] = useState<TabKey>('stream')
  const streaming = useStore((s) => s.streaming)

  return (
    <div className="sidebar">
      <div className="tab-buttons">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={tab === t.key ? 'active' : ''}
            onClick={() => setTab(t.key)}
          >
            {t.label}
            {t.key === 'stream' && streaming ? ' ●' : ''}
          </button>
        ))}
      </div>
      <div className="tab-body">
        {tab === 'stream' && <StreamTab />}
        {tab === 'decision' && <DecisionTab />}
        {tab === 'tree' && <TreeTab />}
        {tab === 'flowviz' && <FlowVizTab />}
        {tab === 'future' && <FutureTrendTab />}
        {tab === 'raw' && <RawTab />}
        {tab === 'prompts' && <PromptFilesTab />}
      </div>
    </div>
  )
}
