import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { useStore } from '../store'
import type { Meta } from '../api/types'

export default function ControlBar() {
  const meta = useStore((s) => s.meta)
  const price = useStore((s) => s.price)
  const ui = useStore((s) => s.ui)
  const decision = useStore((s) => s.decision)
  const fetchProgress = useStore((s) => s.fetchProgress)
  const pushToast = useStore((s) => s.pushToast)

  const [symbol, setSymbol] = useState('')
  const [timeframe, setTimeframe] = useState('15m')
  const [kind, setKind] = useState('mt5')
  const [exchange, setExchange] = useState('')
  const [waitClose, setWaitClose] = useState(false)
  const [keepAnalysis, setKeepAnalysis] = useState(false)
  const [busy, setBusy] = useState(false)
  const [candidates, setCandidates] = useState<Array<{ code: string; name: string; kind: string }> | null>(null)
  const searchSeq = useRef(0)
  const searchTimer = useRef<number | null>(null)
  const symbolDirtyRef = useRef(false) // 用户正在编辑品种时，meta 轮询不得覆盖输入框

  // Sync editable fields when meta arrives / changes.
  useEffect(() => {
    if (!meta) return
    if (!symbolDirtyRef.current) setSymbol(meta.symbol)
    setTimeframe(meta.timeframe)
    setKind(meta.active_kind)
    setExchange(meta.exchange)
  }, [meta])

  const submitBlocked = ui?.submit_block_reason ?? null
  const incremental = ui?.incremental_available ?? false
  const inProgress = ui?.analysis_in_progress ?? false
  const demoMode = ui?.demo_mode ?? false

  async function refetchMeta() {
    const m = await api.get('/api/meta')
    useStore.getState().setMeta(m as Meta)
  }

  // 输入即搜（easytdx 名称反查）：350ms 防抖，读本地缓存的名称表。
  function scheduleSearch(value: string) {
    if (searchTimer.current !== null) window.clearTimeout(searchTimer.current)
    const q = value.trim()
    if (kind !== 'easytdx' || q.length === 0) {
      setCandidates(null)
      return
    }
    searchTimer.current = window.setTimeout(async () => {
      const seq = ++searchSeq.current
      try {
        const r = await api.get(`/api/symbol/search?q=${encodeURIComponent(q)}&limit=12`)
        if (seq !== searchSeq.current) return // 丢弃过期响应
        const list = Array.isArray(r.candidates) ? r.candidates : []
        setCandidates(list.length > 0 ? list : null)
      } catch {
        /* 搜索失败不打扰输入 */
      }
    }, 350)
  }

  useEffect(() => {
    setCandidates(null)
  }, [kind])

  async function onFetchData(symOverride?: string) {
    const sym = symOverride ?? symbol
    setBusy(true)
    try {
      if (sym !== meta?.symbol || timeframe !== meta?.timeframe) {
        const r = await api.post('/api/subscribe', { symbol: sym, timeframe })
        if (!r.ok) {
          if (Array.isArray(r.candidates) && r.candidates.length > 0) {
            setCandidates(r.candidates)
          } else {
            setCandidates(null)
            pushToast({ level: 'error', title: '切换失败', message: r.error ?? '' })
          }
          return // 保留输入内容与 dirty 状态，供用户修改后重试
        }
      }
      symbolDirtyRef.current = false // 已订阅成功，服务端品种与输入一致
      setCandidates(null)
      const r = await api.post('/api/fetch')
      if (!r.ok) pushToast({ level: 'error', title: '获取数据失败', message: r.error ?? '' })
    } finally {
      setBusy(false)
      refetchMeta()
    }
  }

  function onPickCandidate(code: string) {
    setSymbol(code)
    setCandidates(null)
    onFetchData(code)
  }

  async function onKindChange(next: string) {
    setKind(next)
    setBusy(true)
    try {
      const r = await api.post('/api/data-source', { kind: next })
      if (!r.ok) {
        pushToast({ level: 'error', title: '切换数据来源失败', message: r.error ?? '' })
        if (meta) setKind(meta.active_kind)
      }
    } finally {
      setBusy(false)
      refetchMeta()
    }
  }

  async function onExchangeChange(next: string) {
    setExchange(next)
    const r = await api.post('/api/exchange', { exchange: next })
    if (!r.ok) pushToast({ level: 'error', title: '交易所切换失败', message: r.error ?? '' })
  }

  async function onSubmit() {
    if (inProgress) {
      await api.post('/api/analysis/cancel')
      return
    }
    const r = await api.post('/api/analysis', {
      force_incremental: incremental ? true : null,
      wait_close: waitClose,
    })
    if (!r.ok) {
      pushToast({ level: 'warning', title: '无法提交分析', message: r.error ?? '' })
    }
  }

  async function onKeepAnalysis(enabled: boolean) {
    setKeepAnalysis(enabled)
    const r = await api.post('/api/keep-analysis', { enabled })
    if (!r.ok) pushToast({ level: 'error', title: '持续跟踪分析', message: r.error ?? '' })
  }

  const symbolAlert = meta?.symbol_alert ?? null
  const isTv = kind === 'tradingview'
  const isFutures = kind === 'eastmoney_futures'
  const fetching =
    fetchProgress !== null &&
    ['probing', 'fetching', 'retrying'].includes(fetchProgress.stage)

  return (
    <div className="control-bar">
      <span className="muted">数据来源:</span>
      <select
        value={kind}
        disabled={demoMode || busy}
        onChange={(e) => onKindChange(e.target.value)}
        style={{ minWidth: 120 }}
      >
        {(meta?.data_sources ?? []).map((d) => (
          <option key={d.kind} value={d.kind}>
            {d.label}
          </option>
        ))}
      </select>

      {isTv && (
        <>
          <span className="muted">交易所:</span>
          <select value={exchange} onChange={(e) => onExchangeChange(e.target.value)} style={{ minWidth: 130 }}>
            <option value="">（自动）</option>
            {(meta?.tv_exchanges ?? []).map((ex) => (
              <option key={ex} value={ex}>
                {ex}
              </option>
            ))}
          </select>
        </>
      )}

      {isFutures && (
        <>
          <span className="muted">品种:</span>
          <select onChange={(e) => setSymbol(e.target.value)}>
            {(meta?.futures_varieties ?? []).map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        </>
      )}

      <span className="muted">{isFutures ? '合约:' : '品种:'}</span>
      <span className="symbol-box">
        <input
          type="text"
          list={kind !== 'easytdx' ? 'symbol-suggestions' : undefined}
          value={symbol}
          placeholder={meta?.symbol_placeholder ?? ''}
          onChange={(e) => {
            symbolDirtyRef.current = true
            setSymbol(e.target.value)
            scheduleSearch(e.target.value)
          }}
          onBlur={() => {
            if (searchTimer.current !== null) window.clearTimeout(searchTimer.current)
            setCandidates(null)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setCandidates(null)
          }}
          style={{ width: 200 }}
        />
        {candidates && candidates.length > 0 && (
          <div className="symbol-candidates" onMouseDown={(e) => e.preventDefault()}>
            {candidates.map((c) => (
              <button key={c.kind + c.code} type="button" onClick={() => onPickCandidate(c.code)}>
                <span className="cand-name">{c.name}</span>
                <span className="cand-meta">
                  {c.code} · {c.kind}
                </span>
              </button>
            ))}
          </div>
        )}
      </span>
      {kind !== 'easytdx' && (
        <datalist id="symbol-suggestions">
          {(meta?.symbols ?? []).map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      )}

      <span className="muted">周期:</span>
      <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)} style={{ width: 66 }}>
        {(meta?.timeframes?.length ? meta.timeframes : ['1m', '5m', '15m', '1h', '4h', '1d']).map((tf) => (
          <option key={tf} value={tf}>
            {tf}
          </option>
        ))}
      </select>

      {price && (
        <span className="price-label" style={{ color: price.color }}>
          {price.price}
        </span>
      )}

      <span style={{ flex: 1 }} />

      <button className="primary" disabled={demoMode || busy} onClick={() => onFetchData()}>
        {fetching ? '获取中…' : '获取数据'}
      </button>
      {fetchProgress && (
        <span className={`fetch-progress ${fetchProgress.stage}`}>{fetchProgress.text}</span>
      )}

      <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <input
          type="checkbox"
          checked={waitClose}
          onChange={(e) => setWaitClose(e.target.checked)}
        />
        <span className="muted">等待最新K线收盘后再提交分析</span>
      </label>

      <button
        className="primary"
        disabled={!!submitBlocked && !inProgress}
        title={submitBlocked ?? ''}
        onClick={onSubmit}
        style={{ minWidth: 100 }}
      >
        {inProgress ? '取消分析' : incremental ? '增量分析' : '提交分析'}
      </button>

      <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <input
          type="checkbox"
          checked={keepAnalysis}
          onChange={(e) => onKeepAnalysis(e.target.checked)}
        />
        <span className="muted">持续跟踪分析</span>
      </label>

      <button
        disabled={!ui?.chart_refresh_paused}
        onClick={() => api.post('/api/chart/resume')}
        title="恢复 K 线实时刷新"
      >
        图表实时更新
      </button>

      {decision && (
        <span className="pill blue">决策: {decision.order_type}</span>
      )}
      {meta?.ai_mode_label && <span className="muted">{meta.ai_mode_label}</span>}

      {symbolAlert && <span className="symbol-alert">{symbolAlert}</span>}
    </div>
  )
}
