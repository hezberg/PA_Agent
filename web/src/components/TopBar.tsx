// 单行顶栏：品种/周期/数据源 + 现价 + 主操作（获取数据 / 开始分析）+ ⚙ 设置菜单。
// 吸收原 ControlBar、MenuBar、API Key 横幅与刷新状态行。
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { useStore } from '../store'
import { useSymbolName, tfZh } from '../symbolName'
import { GearIcon } from '../icons'
import type { Meta } from '../api/types'

type Candidate = { code: string; name: string; kind: string }

export default function TopBar() {
  const meta = useStore((s) => s.meta)
  const price = useStore((s) => s.price)
  const ui = useStore((s) => s.ui)
  const fetchProgress = useStore((s) => s.fetchProgress)
  const pushToast = useStore((s) => s.pushToast)
  const openModal = useStore((s) => s.openModal)

  const [symbol, setSymbol] = useState('')
  const [timeframe, setTimeframe] = useState('1d')
  const [kind, setKind] = useState('mt5')
  const [exchange, setExchange] = useState('')
  const [waitClose, setWaitClose] = useState(false)
  const [keepAnalysis, setKeepAnalysis] = useState(false)
  const [busy, setBusy] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [candidates, setCandidates] = useState<Candidate[] | null>(null)
  const searchSeq = useRef(0)
  const searchTimer = useRef<number | null>(null)
  const symbolDirtyRef = useRef(false) // 用户正在编辑品种时，meta 轮询不得覆盖输入框
  const menuRef = useRef<HTMLDivElement>(null)

  // Sync editable fields when meta arrives / changes.
  useEffect(() => {
    if (!meta) return
    if (!symbolDirtyRef.current) setSymbol(meta.symbol)
    setTimeframe(meta.timeframe)
    setKind(meta.active_kind)
    setExchange(meta.exchange)
  }, [meta])

  // 服务端持续跟踪状态为准（含演示模式恢复等场景）。
  useEffect(() => {
    if (ui?.keep_analysis !== undefined) setKeepAnalysis(ui.keep_analysis)
  }, [ui?.keep_analysis])

  useEffect(() => {
    if (!menuOpen) return
    const onDocClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('click', onDocClick)
    return () => document.removeEventListener('click', onDocClick)
  }, [menuOpen])

  const submitBlocked = ui?.submit_block_reason ?? null
  const incremental = ui?.incremental_available ?? false
  const inProgress = ui?.analysis_in_progress ?? false
  const demoMode = ui?.demo_mode ?? false
  const paused = ui?.chart_refresh_paused ?? false

  async function refetchMeta() {
    const m = await api.get('/api/meta')
    useStore.getState().setMeta(m as Meta)
  }

  // 输入即搜（A股/港股/指数名称反查）：350ms 防抖。
  function scheduleSearch(value: string) {
    if (searchTimer.current !== null) window.clearTimeout(searchTimer.current)
    const q = value.trim()
    if (q.length === 0) {
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
      symbolDirtyRef.current = false
      setCandidates(null)
      const r = await api.post('/api/fetch')
      if (!r.ok) pushToast({ level: 'error', title: '获取数据失败', message: r.error ?? '' })
    } finally {
      setBusy(false)
      refetchMeta()
    }
  }

  async function onPickCandidate(code: string) {
    setSymbol(code)
    setCandidates(null)
    if (kind !== 'easytdx') {
      // A股/港股代码只有通达信源可订阅：选中候选时自动切换数据来源。
      setBusy(true)
      try {
        let r = await api.post('/api/data-source', { kind: 'easytdx', symbol: code, timeframe })
        for (let i = 0; !r.ok && /正在切换中/.test(r.error ?? '') && i < 3; i++) {
          await new Promise((res) => setTimeout(res, 1500))
          r = await api.post('/api/data-source', { kind: 'easytdx', symbol: code, timeframe })
        }
        if (!r.ok) {
          pushToast({ level: 'error', title: '切换数据来源失败', message: r.error ?? '' })
          return
        }
        setKind('easytdx')
      } finally {
        setBusy(false)
        refetchMeta()
      }
      return
    }
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

  async function onToggleDemo() {
    setMenuOpen(false)
    if (demoMode) {
      await api.post('/api/demo/stop')
    } else {
      const r = await api.post('/api/demo/start', { mode: 'auto' })
      if (!r.ok) useStore.getState().pushToast({ level: 'error', title: '演示模式', message: r.error ?? '' })
    }
  }

  async function onToggleKeep(enabled: boolean) {
    setKeepAnalysis(enabled)
    // 注意挂在 analysis 路由下：/api/analysis/keep-analysis
    const r = await api.post('/api/analysis/keep-analysis', { enabled })
    if (!r.ok) {
      pushToast({ level: 'error', title: '持续跟踪分析', message: r.error ?? '' })
      setKeepAnalysis(!enabled)
    }
  }

  const symbolAlert = meta?.symbol_alert ?? null
  const isTv = kind === 'tradingview'
  const isFutures = kind === 'eastmoney_futures'
  const fetching = fetchProgress !== null && ['probing', 'fetching', 'retrying'].includes(fetchProgress.stage)
  const activeName = useSymbolName(meta?.symbol)

  // ── 按钮状态推导：任何禁用都必须给出紧跟按钮的可见原因 ──
  const fetchingNow = busy || fetching
  const sourceDown = !(meta?.source_connected ?? false)
  const fetchDisabledReason = demoMode
    ? '演示模式中不可操作'
    : sourceDown
      ? '数据源未连接'
      : null
  const fetchDisabled = demoMode || busy || sourceDown
  // 分析中按钮变为可按的「取消分析」；其余禁用原因由服务端给出
  const analyzeDisabledReason: string | null = inProgress ? null : submitBlocked

  return (
    <header className="topbar">
      <div className="brand"><span className="mark">◆</span>PA 分析</div>

      <div className="grp">
        <select value={kind} disabled={demoMode || busy} aria-label="数据来源" onChange={(e) => onKindChange(e.target.value)}>
          {(meta?.data_sources ?? []).map((d) => (
            <option key={d.kind} value={d.kind}>
              {d.label}
            </option>
          ))}
        </select>

        {isTv && (
          <select value={exchange} aria-label="交易所" onChange={(e) => onExchangeChange(e.target.value)}>
            <option value="">（自动）</option>
            {(meta?.tv_exchanges ?? []).map((ex) => (
              <option key={ex} value={ex}>
                {ex}
              </option>
            ))}
          </select>
        )}

        {isFutures && (
          <select aria-label="品种" onChange={(e) => setSymbol(e.target.value)}>
            {(meta?.futures_varieties ?? []).map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
        )}

        <span className="symbol-box">
          <input
            className="symbol-input"
            type="text"
            list={kind !== 'easytdx' ? 'symbol-suggestions' : undefined}
            value={symbol}
            placeholder={meta?.symbol_placeholder ?? ''}
            aria-label="品种"
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

        <select value={timeframe} aria-label="周期" onChange={(e) => setTimeframe(e.target.value)}>
          {(meta?.timeframes?.length ? meta.timeframes : ['1m', '5m', '15m', '1h', '4h', '1d']).map((tf) => (
            <option key={tf} value={tf}>
              {tfZh(tf)}
            </option>
          ))}
        </select>

        {activeName && <span className="sym-name">{activeName}</span>}

        {symbolAlert && <span className="chip warn" title={symbolAlert}>品种告警</span>}
      </div>

      {price && (
        <span className="price-big" style={{ color: price.color }}>
          {price.price}
        </span>
      )}

      <span style={{ flex: 1 }} />

      {!meta?.api_key_configured && (
        <span className="chip warn" role="button" tabIndex={0} onClick={() => openModal('ai')} onKeyDown={(e) => e.key === 'Enter' && openModal('ai')}>
          未配置 API Key → 去设置
        </span>
      )}

      <button
        className="primary"
        disabled={fetchDisabled}
        title={fetchDisabledReason ?? undefined}
        onClick={() => onFetchData()}
      >
        {fetchingNow ? '获取中…' : '获取数据'}
      </button>
      {fetchDisabledReason && !fetchingNow && <span className="btn-hint">{fetchDisabledReason}</span>}
      {fetchProgress && <span className={`fetch-progress ${fetchProgress.stage}`}>{fetchProgress.text}</span>}

      <button
        className={inProgress ? 'cancel' : 'primary'}
        disabled={!!analyzeDisabledReason}
        title={analyzeDisabledReason ?? undefined}
        onClick={onSubmit}
        style={{ minWidth: 96 }}
      >
        {inProgress ? '取消分析' : '开始分析'}
      </button>
      {analyzeDisabledReason && !/API Key/.test(analyzeDisabledReason) && (
        <span className={`btn-hint${/等待|切换/.test(analyzeDisabledReason) ? ' warn' : ''}`}>
          {analyzeDisabledReason}
        </span>
      )}
      {incremental && !inProgress && <span className="chip amber">增量 · 复用上次结论</span>}
      {keepAnalysis && !inProgress && <span className="chip info">跟踪中 · 收盘自动重分析</span>}

      <div className="menu-wrap" ref={menuRef}>
        <button className="iconbtn" title="设置与更多" aria-label="设置与更多" aria-expanded={menuOpen} onClick={() => setMenuOpen((v) => !v)}>
          <GearIcon />
          <span>设置</span>
        </button>
        {menuOpen && (
          <div className="menu">
            <div className="menu-sec">设 置</div>
            <button className="menu-item" onClick={() => { setMenuOpen(false); openModal('ai') }}>
              AI 模型设置<span className="menu-hint">Base URL / Key / 模型</span>
            </button>
            <button className="menu-item" onClick={() => { setMenuOpen(false); openModal('general') }}>
              其他通用设置
            </button>
            <button className="menu-item" onClick={() => { setMenuOpen(false); openModal('feishu') }}>
              飞书通知设置<span className="menu-hint">Webhook 推送</span>
            </button>
            <div className="menu-sec">分 析</div>
            <button className={`menu-item${waitClose ? ' on' : ''}`} onClick={() => setWaitClose((v) => !v)}>
              <span className="cb" />等待最新K线收盘后再提交
            </button>
            <button className={`menu-item${keepAnalysis ? ' on' : ''}`} onClick={() => onToggleKeep(!keepAnalysis)}>
              <span className="cb" />持续跟踪分析<span className="menu-hint">收盘自动重分析</span>
            </button>
            <button className="menu-item" disabled={!paused} onClick={() => { setMenuOpen(false); api.post('/api/chart/resume') }}>
              恢复图表实时刷新<span className="menu-hint">{paused ? '刷新已暂停' : '刷新进行中'}</span>
            </button>
            <div className="menu-sec">其 他</div>
            <button className="menu-item" onClick={onToggleDemo}>
              {demoMode ? '退出演示模式' : '演示模式'}
            </button>
          </div>
        )}
      </div>
    </header>
  )
}
