import { useEffect, useRef, useState } from 'react'
import { api, openStream } from '../../api/client'
import { useStore } from '../../store'
import type { ChatMsg } from '../../api/types'

export default function StreamTab() {
  const panes = useStore((s) => s.panes)
  const streaming = useStore((s) => s.streaming)
  const decision = useStore((s) => s.decision)
  const retries = useStore((s) => s.retries)
  const chatEnabled = useStore((s) => s.chatEnabled)
  const chatHistory = useStore((s) => s.chatHistory)
  const chatStreaming = useStore((s) => s.chatStreaming)
  const chatDraft = useStore((s) => s.chatDraft)

  const [input, setInput] = useState('')
  const chatCloser = useRef<null | (() => void)>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [panes, chatHistory, chatDraft])

  async function send() {
    const text = input.trim()
    if (!text || chatStreaming) return
    const s = useStore.getState()
    setInput('')
    s.appendChat({ role: 'user', content: text })
    s.setChatStreaming(true)
    s.setChatDraft({ reasoning: '', content: '' })

    const r = await api.post('/api/chat', { text })
    if (!r.ok) {
      s.pushToast({ level: 'error', title: '追问失败', message: r.error ?? '' })
      s.setChatStreaming(false)
      s.setChatDraft(null)
      return
    }
    const channel: string = r.channel ?? ''
    chatCloser.current?.()
    chatCloser.current = openStream(
      `/api/chat/stream/${channel.split(':').pop() ?? ''}`,
      (type, data) => {
        const st = useStore.getState()
        if (type === 'reasoning_token') {
          const draft = { ...(st.chatDraft ?? { reasoning: '', content: '' }) }
          draft.reasoning += String(data.chunk ?? '')
          st.setChatDraft(draft)
        } else if (type === 'content_token') {
          const draft = { ...(st.chatDraft ?? { reasoning: '', content: '' }) }
          draft.content += String(data.chunk ?? '')
          st.setChatDraft(draft)
        } else if (type === 'finished') {
          const draft = st.chatDraft
          if (draft?.content) {
            st.appendChat({
              role: 'assistant',
              content: draft.content,
              reasoning_content: draft.reasoning || undefined,
            })
          }
          st.setChatDraft(null)
          st.setChatStreaming(false)
          chatCloser.current?.()
          chatCloser.current = null
        } else if (type === 'error') {
          st.pushToast({ level: 'error', title: '追问出错', message: String(data.message ?? '') })
        }
      },
    )
  }

  const ledger = decision?.token_display
  const pct =
    ledger && ledger.context_window > 0
      ? Math.min(100, (ledger.context_used / ledger.context_window) * 100)
      : 0

  return (
    <div>
      {panes.length === 0 && (
        <div className="muted" style={{ padding: 12 }}>
          等待分析… 点击「提交分析」开始两阶段 AI 分析。
        </div>
      )}

      {panes.map((pane) => (
        <div key={pane.stage}>
          <div className="stream-stage">
            {pane.title}
            {pane.active && streaming && <span className="cursor" style={{ marginLeft: 6 }} />}
          </div>
          {pane.reasoning && (
            <div style={{ marginBottom: 6 }}>
              <div className="muted" style={{ marginBottom: 2 }}>
                思考过程{retries.includes(pane.stage) ? '（已重试）' : ''}
              </div>
              <div className="reasoning-box">{pane.reasoning}</div>
            </div>
          )}
          {pane.content && <div className="content-box">{pane.content}</div>}
        </div>
      ))}
      <div ref={bottomRef} />

      {decision && (
        <div className="panel-section" style={{ marginTop: 12 }}>
          {decision.stage_results.map((sr) => (
            <details key={sr.stage} style={{ marginBottom: 4 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--accent-3)' }}>
                {sr.title}（点击展开完整 JSON）
              </summary>
              <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {sr.content}
              </pre>
            </details>
          ))}
        </div>
      )}

      {ledger && (
        <div className="token-progress">
          <div className="token-bar">
            <div style={{ width: `${pct}%` }} />
          </div>
          <div className="token-stats">
            <span>上下文 {fmt(ledger.context_used)} / {fmt(ledger.context_window)}（{pct.toFixed(1)}%）</span>
            <span>输入 {fmt(ledger.total_input)}</span>
            <span>缓存 {fmt(ledger.total_cached_input)}</span>
            <span>输出 {fmt(ledger.total_output)}</span>
          </div>
        </div>
      )}

      <div className="chat-input-row">
        <input
          type="text"
          placeholder={
            chatEnabled
              ? '追问（基于本轮分析，K线已刷新冻结）…'
              : '完成一次分析后可在此追问'
          }
          disabled={!chatEnabled || chatStreaming}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') send()
          }}
        />
        <button className="primary" disabled={!chatEnabled || chatStreaming} onClick={send}>
          发送
        </button>
        {chatStreaming && (
          <button
            onClick={async () => {
              await api.post('/api/chat/cancel')
            }}
          >
            停止
          </button>
        )}
      </div>
      {chatDraft && (
        <div style={{ marginTop: 6 }}>
          {chatDraft.reasoning && <div className="reasoning-box">{chatDraft.reasoning}</div>}
          <div className="content-box">{chatDraft.content || '…'}</div>
        </div>
      )}
      {chatHistory.length > 0 && <HistoryList history={chatHistory} />}
    </div>
  )
}

function HistoryList({ history }: { history: ChatMsg[] }) {
  return (
    <div style={{ marginTop: 10 }}>
      <div className="muted" style={{ marginBottom: 4 }}>
        追问历史（{history.filter((m) => m.role === 'user').length} 轮）
      </div>
      {history
        .filter((m) => m.role === 'user')
        .map((m, i) => (
          <div key={i} className="kv-row">
            <span className="kv-key">第{i + 1}问</span>
            <span className="kv-value">{m.content}</span>
          </div>
        ))}
    </div>
  )
}

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return String(n)
}
