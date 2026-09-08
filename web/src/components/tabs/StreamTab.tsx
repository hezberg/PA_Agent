// 实时流：两阶段阶段卡（思考过程可折叠）+ 追问气泡 + 置底输入框。
import { useEffect, useRef, useState } from 'react'
import { api, openStream } from '../../api/client'
import { useStore } from '../../store'
import type { ChatMsg } from '../../api/types'

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return String(n)
}

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

  // 智能滚动：仅当视口已接近底部时才自动跟随，向上翻阅历史时不打扰。
  useEffect(() => {
    const el = bottomRef.current?.closest('.tab-body') as HTMLElement | null
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 140
    if (nearBottom) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [panes, chatHistory, chatDraft])

  useEffect(() => () => chatCloser.current?.(), [])

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

  return (
    <>
      <div style={{ flexShrink: 0 }}>
        {panes.length === 0 && (
          <div className="muted" style={{ padding: 4 }}>
            等待分析… 点「开始分析」后，两阶段 AI 的思考与结论会实时显示在这里。
          </div>
        )}

        {panes.map((pane) => {
          const retried = retries.includes(pane.stage)
          const live = pane.active && streaming
          return (
            <div className="stage-card" key={pane.stage}>
              <div className="sc-head">
                <span className="sc-title">{pane.title}</span>
                <span className={`sc-state ${live ? 'live' : 'done'}`}>{live ? '推理中' : '已完成'}</span>
                {retried && <span className="sc-state retried">已重试</span>}
              </div>
              {pane.reasoning && (
                <details className="reasoning">
                  <summary>思考过程 ▸{retried ? '（已重试）' : ''}</summary>
                  <div className="r-body">{pane.reasoning}</div>
                </details>
              )}
              <div className="stage-content">
                {pane.content}
                {live && <span className="cursor" />}
              </div>
            </div>
          )
        })}
        <div ref={bottomRef} style={{ flexShrink: 0 }} />
      </div>

      {decision && decision.stage_results.length > 0 && (
        <div className="panel-section" style={{ marginTop: 10, flexShrink: 0 }}>
          {decision.stage_results.map((sr) => (
            <details key={sr.stage} style={{ marginBottom: 4 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--accent)' }}>
                {sr.title}（展开完整 JSON）
              </summary>
              <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: '6px 0 0' }}>
                {sr.content}
              </pre>
            </details>
          ))}
        </div>
      )}

      {decision?.token_display && (
        <div className="token-foot mono" style={{ flexShrink: 0 }}>
          上下文 {fmt(decision.token_display.context_used)} / {fmt(decision.token_display.context_window)}
          （{((decision.token_display.context_used / decision.token_display.context_window) * 100).toFixed(1)}%）
          · 输入 {fmt(decision.token_display.total_input)} · 缓存 {fmt(decision.token_display.total_cached_input)}
          · 输出 {fmt(decision.token_display.total_output)}
        </div>
      )}

      <ChatArea
        input={input}
        setInput={setInput}
        send={send}
        chatEnabled={chatEnabled}
        chatStreaming={chatStreaming}
        chatDraft={chatDraft}
        chatHistory={chatHistory}
      />
    </>
  )
}

function ChatArea({
  input,
  setInput,
  send,
  chatEnabled,
  chatStreaming,
  chatDraft,
  chatHistory,
}: {
  input: string
  setInput: (v: string) => void
  send: () => void
  chatEnabled: boolean
  chatStreaming: boolean
  chatDraft: { reasoning: string; content: string } | null
  chatHistory: ChatMsg[]
}) {
  return (
    <div className="chat-input-wrap" style={{ marginTop: 'auto' }}>
      {chatHistory.filter((m) => m.role === 'user').length > 0 && (
        <div style={{ paddingTop: 10 }}>
          {chatHistory.map((m, i) => (
            <div key={i} className={`bubble ${m.role === 'user' ? 'user' : 'ai'}`}>
              <div className="b-in">
                <div className="b-role">{m.role === 'user' ? '你' : 'AI'}</div>
                {m.content}
              </div>
            </div>
          ))}
        </div>
      )}
      {chatDraft && (
        <div style={{ paddingTop: 10 }}>
          {chatDraft.reasoning && (
            <details className="reasoning" open>
              <summary>AI 思考过程 ▸</summary>
              <div className="r-body">{chatDraft.reasoning}</div>
            </details>
          )}
          <div className={`bubble ai`}>
            <div className="b-in">
              <div className="b-role">AI</div>
              {chatDraft.content || '…'}
              <span className="cursor" />
            </div>
          </div>
        </div>
      )}
      <div className="chat-input">
        <input
          type="text"
          placeholder={chatEnabled ? '追问（基于本轮分析，K线已刷新冻结）…' : '完成一次分析后可在此追问'}
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
          <button onClick={async () => { await api.post('/api/chat/cancel') }}>停止</button>
        )}
      </div>
    </div>
  )
}
