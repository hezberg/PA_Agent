// 同花顺自选清单：最左侧固定宽度面板（可收起成竖轨）。
// 分组小标签横排换行（「全部」聚合 + 「我的自选」优先）；条目=中文名+代码+现价涨跌；
// 点击=切票+自动展开K线；行情为交易时段内按设置间隔刷新的快照（非轮询式逐票请求）。
// 移动端：顶部下拉（列表置顶时）→ 释放整页刷新，替代被应用式布局挡住的 Chrome 原生下拉刷新。
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { useStore } from '../store'
import { switchToSymbol } from '../switchSymbol'
import type { ThsGroup } from '../api/types'

const OPEN_KEY = 'pa.watchlist.open'
const REFRESH_MS = 30 * 60 * 1000
const QUOTES_MS = 2000
const ALL_ID = '__all__'

type Quote = { price: number; change_pct: number; name?: string }

function chgColor(v: number | undefined): string | undefined {
  if (v === undefined || v === 0) return undefined
  return v > 0 ? 'var(--chart-up)' : 'var(--chart-down)' // A 股惯例：红涨绿跌
}

export default function WatchlistPanel() {
  const thsEnabled = useStore((s) => s.meta?.ths_enabled ?? false)
  const openModal = useStore((s) => s.openModal)
  const pushToast = useStore((s) => s.pushToast)
  const metaSymbol = useStore((s) => s.meta?.symbol ?? '')

  const [open, setOpen] = useState(() => localStorage.getItem(OPEN_KEY) !== '0')
  const [groups, setGroups] = useState<ThsGroup[]>([])
  const [activeId, setActiveId] = useState<string>(ALL_ID)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [stale, setStale] = useState(false)
  const [quotes, setQuotes] = useState<Record<string, Quote>>({})
  const [sortMode, setSortMode] = useState<'none' | 'desc' | 'asc'>('desc')

  const load = useCallback(
    async (force = false) => {
      setLoading(true)
      setError('')
      try {
        const r = await api.get(`/api/ths/watchlist${force ? '?force=true' : ''}`)
        if (r.ok) {
          const list = (r.groups ?? []) as ThsGroup[]
          list.sort((a, b) => (a.id === '__selfstock__' ? -1 : b.id === '__selfstock__' ? 1 : 0))
          setGroups(list)
          setStale(Boolean(r.stale))
          setActiveId((cur) => (cur && list.some((g) => g.id === cur) ? cur : ALL_ID))
        } else {
          setError(r.error ?? '拉取失败')
        }
      } catch {
        setError('网络错误')
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    if (!thsEnabled) return
    load()
    const t = setInterval(() => load(), REFRESH_MS)
    return () => clearInterval(t)
  }, [thsEnabled, load])

  // 行情快照轮询：交易时段内后端按设置间隔拉取，这里 2s 取一次现成快照（本地调用，零成本）
  useEffect(() => {
    if (!thsEnabled || !open) return
    let alive = true
    const tick = async () => {
      try {
        const r = await api.get('/api/ths/quotes')
        if (alive && r.ok) setQuotes(r.quotes ?? {})
      } catch {
        /* 忽略单次失败 */
      }
    }
    tick()
    const t = setInterval(tick, QUOTES_MS)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [thsEnabled, open])

  // 「全部」聚合分组（按代码去重，保持组顺序）
  const allGroup: ThsGroup = useMemo(() => {
    const seen = new Set<string>()
    const items: ThsGroup['items'] = []
    for (const g of groups)
      for (const it of g.items) {
        if (seen.has(it.sub_code)) continue
        seen.add(it.sub_code)
        items.push(it)
      }
    return { id: ALL_ID, name: '全部', items }
  }, [groups])

  const active = groups.find((g) => g.id === activeId) ?? (activeId === ALL_ID ? allGroup : groups[0])
  if (!active && !error && thsEnabled && groups.length > 0) {
    // groups 尚未就绪时的兜底
  }

  const sortedItems = useMemo(() => {
    const items = [...(active?.items ?? [])]
    if (sortMode !== 'none') {
      items.sort((a, b) => {
        const qa = quotes[a.sub_code]?.change_pct
        const qb = quotes[b.sub_code]?.change_pct
        const va = qa ?? -999
        const vb = qb ?? -999
        return sortMode === 'desc' ? vb - va : va - vb
      })
    }
    return items
  }, [active, quotes, sortMode])

  function toggleSort() {
    setSortMode((m) => (m === 'none' ? 'desc' : m === 'desc' ? 'asc' : 'none'))
  }
  const sortLabel = sortMode === 'desc' ? '涨跌↓' : sortMode === 'asc' ? '涨跌↑' : '排序'

  if (!open) {
    return (
      <button
        className="rail watchlist-rail"
        title="展开自选清单"
        onClick={() => {
          localStorage.setItem(OPEN_KEY, '1')
          setOpen(true)
        }}
      >
        <span className="rail-txt">自选</span>
      </button>
    )
  }

  return (
    <section className="watchlist" aria-label="自选清单">
      <div className="wl-head">
        <span className="wl-title">自选</span>
        <span style={{ flex: 1 }} />
        <button
          className="wl-act"
          title="排序：按当日涨跌幅"
          disabled={!thsEnabled || groups.length === 0}
          onClick={toggleSort}
        >
          {sortLabel}
        </button>
        <button
          className="wl-act"
          title="刷新自选（从同花顺重新拉取）"
          disabled={!thsEnabled || loading}
          onClick={() => load(true)}
        >
          {loading ? '…' : '⟳'}
        </button>
        {thsEnabled && (
          <button className="wl-act" title="自选股登录设置" onClick={() => openModal('ths')}>
            ⚙
          </button>
        )}
        <button
          className="wl-act"
          title="收起自选清单"
          onClick={() => {
            localStorage.setItem(OPEN_KEY, '0')
            setOpen(false)
          }}
        >
          ⟨
        </button>
      </div>

      {!thsEnabled ? (
        <div className="wl-guide">
          <div>登录同花顺账号后，这里会显示你的自选分组。</div>
          <button className="primary" onClick={() => openModal('ths')}>
            去登录
          </button>
        </div>
      ) : error && groups.length === 0 ? (
        <div className="wl-guide">
          <div>{error}</div>
          <button onClick={() => load(true)}>重试</button>
        </div>
      ) : (
        <>
          <div className="wl-tabs">
            {[allGroup, ...groups].map((g) => (
              <button
                key={g.id}
                className={`wl-tab${g.id === active?.id ? ' on' : ''}`}
                onClick={() => setActiveId(g.id)}
                title={`${g.name}（${g.items.length} 只）`}
              >
                {g.name}
              </button>
            ))}
          </div>
          {stale && <div className="wl-stale">拉取失败，显示上次缓存</div>}
          <div className="wl-items">
            {sortedItems.map((it) => {
              const q = quotes[it.sub_code]
              const name = it.name || q?.name || it.sub_code
              return (
                <button
                  key={active.id + it.market + it.code}
                  className={`wl-item${it.sub_code === metaSymbol ? ' cur' : ''}`}
                  onClick={() =>
                    switchToSymbol(it.sub_code, { expandChart: true }).then((ok) => {
                      if (!ok) pushToast({ level: 'error', title: '切换失败', message: it.name || it.code })
                    })
                  }
                >
                  <span className="wl-row">
                    <span className="wl-name" title={name}>
                      {name}
                    </span>
                    <span className="wl-quote" style={{ color: chgColor(q?.change_pct) }}>
                      {q ? (
                        <>
                          {q.price.toFixed(2)}
                          <span className="wl-chg">
                            {q.change_pct > 0 ? '+' : ''}
                            {q.change_pct.toFixed(2)}%
                          </span>
                        </>
                      ) : (
                        <span className="wl-code">{it.sub_code}</span>
                      )}
                    </span>
                  </span>
                </button>
              )
            })}
            {active && active.items.length === 0 && <div className="wl-empty">该分组暂无股票</div>}
          </div>
        </>
      )}
    </section>
  )
}
