// 同花顺自选清单：最左侧固定宽度面板（可收起成竖轨）。
// 分组小标签横排换行（「我的自选」第一）；条目=中文名+代码；点击=切票+自动展开K线。
import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { useStore } from '../store'
import { switchToSymbol } from '../switchSymbol'
import type { ThsGroup } from '../api/types'

const OPEN_KEY = 'pa.watchlist.open'
const REFRESH_MS = 30 * 60 * 1000

export default function WatchlistPanel() {
  const thsEnabled = useStore((s) => s.meta?.ths_enabled ?? false)
  const openModal = useStore((s) => s.openModal)
  const pushToast = useStore((s) => s.pushToast)
  const metaSymbol = useStore((s) => s.meta?.symbol ?? '')

  const [open, setOpen] = useState(() => localStorage.getItem(OPEN_KEY) !== '0')
  const [groups, setGroups] = useState<ThsGroup[]>([])
  const [activeId, setActiveId] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [stale, setStale] = useState(false)

  const load = useCallback(
    async (force = false) => {
      setLoading(true)
      setError('')
      try {
        const r = await api.get(`/api/ths/watchlist${force ? '?force=true' : ''}`)
        if (r.ok) {
          const list = (r.groups ?? []) as ThsGroup[]
          // 「我的自选」(group_id=__selfstock__) 排第一
          list.sort((a, b) => (a.id === '__selfstock__' ? -1 : b.id === '__selfstock__' ? 1 : 0))
          setGroups(list)
          setStale(Boolean(r.stale))
          setActiveId((cur) => (cur && list.some((g) => g.id === cur) ? cur : (list[0]?.id ?? '')))
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

  // 登录成功后（modal 关闭→meta 更新）自动拉取
  useEffect(() => {
    if (thsEnabled && groups.length === 0 && !loading) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [thsEnabled])

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

  const active = groups.find((g) => g.id === activeId) ?? groups[0]

  return (
    <section className="watchlist" aria-label="自选清单">
      <div className="wl-head">
        <span className="wl-title">自选</span>
        <span style={{ flex: 1 }} />
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
            {groups.map((g) => (
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
            {(active?.items ?? []).map((it) => (
              <button
                key={active.id + it.market + it.code}
                className={`wl-item${it.sub_code === metaSymbol ? ' cur' : ''}`}
                onClick={() =>
                  switchToSymbol(it.sub_code, { expandChart: true }).then((ok) => {
                    if (!ok) pushToast({ level: 'error', title: '切换失败', message: it.name || it.code })
                  })
                }
              >
                <span className="wl-name" title={it.name || it.code}>
                  {it.name || it.code}
                </span>
                <span className="wl-code">{it.sub_code}</span>
              </button>
            ))}
            {active && active.items.length === 0 && <div className="wl-empty">该分组暂无股票</div>}
          </div>
        </>
      )}
    </section>
  )
}
