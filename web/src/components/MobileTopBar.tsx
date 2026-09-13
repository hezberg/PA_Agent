// 移动端顶栏：两行制。上行=品种+大号现价+「开始分析」；下行=周期+获取+⚙。
// 品种中文名搜索保留；数据源切换/自选登录/持续跟踪等收进 ⚙ 菜单。
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { useStore } from '../store'
import { useSymbolName, tfZh } from '../symbolName'
import { switchToSymbol } from '../switchSymbol'

type Candidate = { code: string; name: string; kind: string }

export default function MobileTopBar() {
  const meta = useStore((s) => s.meta)
  const price = useStore((s) => s.price)
  const ui = useStore((s) => s.ui)
  const fetchProgress = useStore((s) => s.fetchProgress)
  const openModal = useStore((s) => s.openModal)
  const pushToast = useStore((s) => s.pushToast)

  const [symbol, setSymbol] = useState('')
  const [timeframe, setTimeframe] = useState('1d')
  const [kind, setKind] = useState('easytdx')
  const [busy, setBusy] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [candidates, setCandidates] = useState<Candidate[] | null>(null)
  const [searching, setSearching] = useState(false)
  const searchSeq = useRef(0)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!meta) return
    setSymbol(meta.symbol)
    setTimeframe(meta.timeframe)
    setKind(meta.active_kind)
  }, [meta])

  useEffect(() => {
    if (!menuOpen) return
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('click', onDoc)
    return () => document.removeEventListener('click', onDoc)
  }, [menuOpen])

  const submitBlocked = ui?.submit_block_reason ?? null
  const inProgress = Boolean(ui?.analysis_in_progress)
  const fetching = fetchProgress !== null && ['probing', 'fetching', 'retrying'].includes(fetchProgress.stage)
  const name = useSymbolName(meta?.symbol)
  const activeName = name ?? ''

  // 数据就绪判断：图表的K线与当前订阅一致才能分析
  const frame = useStore((s) => s.frame)
  const dataReady = Boolean(frame && frame.symbol === (meta?.symbol ?? '') && (frame.bars?.length ?? 0) > 0)
  // 分析按钮禁用原因（数据未就绪时给出明确提示而非可点但失败）
  const analyzeBlock: string | null = inProgress
    ? null
    : submitBlocked ?? (!dataReady ? '正在获取K线数据，就绪后即可分析' : null)

  function onSearchInput(value: string) {
    setSymbol(value)
    const q = value.trim()
    if (!q) return setCandidates(null)
    setSearching(true)
    const seq = ++searchSeq.current
    const t = window.setTimeout(async () => {
      try {
        const r = await api.get(`/api/symbol/search?q=${encodeURIComponent(q)}&limit=8`)
        if (seq !== searchSeq.current) return
        const list = Array.isArray(r.candidates) ? r.candidates : []
        setCandidates(list.length ? list : null)
      } catch {
        /* 静默 */
      } finally {
        if (seq === searchSeq.current) setSearching(false)
      }
    }, 350)
    return () => window.clearTimeout(t)
  }

  async function onFetch() {
    setBusy(true)
    try {
      await switchToSymbol(symbol, { timeframe })
    } finally {
      setBusy(false)
    }
  }

  async function onSubmit() {
    if (inProgress) {
      await api.post('/api/analysis/cancel')
      return
    }
    const r = await api.post('/api/analysis', { force_incremental: null, wait_close: false })
    if (!r.ok) pushToast({ level: 'warning', title: '无法提交分析', message: r.error ?? '' })
  }

  async function onKindChange(next: string) {
    setKind(next)
    setMenuOpen(false)
    const r = await api.post('/api/data-source', { kind: next })
    if (!r.ok) {
      pushToast({ level: 'error', title: '切换数据来源失败', message: r.error ?? '' })
      if (meta) setKind(meta.active_kind)
      return
    }
    const m = await api.get('/api/meta')
    if (m.ok) useStore.getState().setMeta(m)
  }

  async function onToggleKeep(enabled: boolean) {
    const r = await api.post('/api/analysis/keep-analysis', { enabled })
    if (!r.ok) pushToast({ level: 'error', title: '持续跟踪分析', message: r.error ?? '' })
  }

  const keepOn = ui?.keep_analysis ?? false

  return (
    <header className="m-topbar">
      <div className="m-row1">
        <span className="m-sym">
          <span className="m-sym-name">{activeName || meta?.symbol}</span>
          {price && (
            <span className="m-price" style={{ color: price.color }}>
              {price.price}
            </span>
          )}
        </span>
        <button
          className={inProgress ? 'cancel' : 'primary'}
          disabled={!!analyzeBlock}
          title={analyzeBlock ?? undefined}
          onClick={onSubmit}
        >
          {inProgress ? '取消' : '分析'}
        </button>
      </div>
      <div className="m-row2">
        <span className="symbol-box m-symbox">
          <input
            type="text"
            value={symbol}
            placeholder="代码 / 中文名"
            aria-label="品种"
            onChange={(e) => onSearchInput(e.target.value)}
          />
          {candidates && (
            <div className="symbol-candidates" onMouseDown={(e) => e.preventDefault()}>
              {candidates.map((c) => (
                <button
                  key={c.kind + c.code}
                  onClick={() => {
                    setCandidates(null)
                    setSymbol(c.code)
                    switchToSymbol(c.code, { timeframe })
                  }}
                >
                  <span className="cand-name">{c.name}</span>
                  <span className="cand-meta">{c.code}</span>
                </button>
              ))}
            </div>
          )}
        </span>
        <select aria-label="周期" value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
          {(meta?.timeframes ?? ['1d']).map((tf) => (
            <option key={tf} value={tf}>
              {tfZh(tf)}
            </option>
          ))}
        </select>
        <button className="primary m-fetch" disabled={busy || fetching} onClick={onFetch}>
          {fetching ? '获取中…' : '获取'}
        </button>
        <div className="menu-wrap m-menu" ref={menuRef}>
          <button className="iconbtn" aria-label="菜单" onClick={() => setMenuOpen((v) => !v)}>
            ⚙
          </button>
          {menuOpen && (
            <div className="menu">
              <div className="menu-sec">数据来源</div>
              {(meta?.data_sources ?? []).map((d) => (
                <button key={d.kind} className={`menu-item${kind === d.kind ? ' on' : ''}`} onClick={() => onKindChange(d.kind)}>
                  {d.label}
                </button>
              ))}
              <div className="menu-sec">设置</div>
              <button className="menu-item" onClick={() => { setMenuOpen(false); openModal('ai') }}>AI 模型设置</button>
              <button className="menu-item" onClick={() => { setMenuOpen(false); openModal('ths') }}>自选股登录</button>
              <div className="menu-sec">分析</div>
              <button className={`menu-item${keepOn ? ' on' : ''}`} onClick={() => onToggleKeep(!keepOn)}>
                <span className="cb" />持续跟踪分析
              </button>
            </div>
          )}
        </div>
      </div>
      {analyzeBlock && !inProgress && !/API Key/.test(analyzeBlock) && (
        <div className={`m-blocked${/等待/.test(analyzeBlock) ? ' wl-stale' : ''}`}>{analyzeBlock}</div>
      )}
    </header>
  )
}
