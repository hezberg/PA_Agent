// 代码 → 名称反查与周期中文映射。
// /api/meta 不含品种名称，这里用现成的 /api/symbol/search 反查一次并缓存；
// 查不到（部分期货/外盘合约）则回退为仅显示代码。
import { useEffect, useState } from 'react'
import { api } from './api/client'

const nameCache = new Map<string, string>() // '' = 已查询但无结果
const listeners = new Set<() => void>()

export function cachedSymbolName(symbol?: string | null): string {
  if (!symbol) return ''
  return nameCache.get(symbol) ?? ''
}

/** 异步解析品种名称；结果更新后通知订阅者重渲染。 */
export function resolveSymbolName(symbol?: string | null): void {
  if (!symbol || nameCache.has(symbol)) return
  nameCache.set(symbol, '') // 占位，防止重复请求
  api
    .get(`/api/symbol/search?q=${encodeURIComponent(symbol)}&limit=8`)
    .then((r) => {
      const list = Array.isArray(r.candidates) ? r.candidates : []
      const hit = list.find((c: { code: string }) => c.code === symbol)
      nameCache.set(symbol, hit?.name ?? '')
      listeners.forEach((l) => l())
    })
    .catch(() => {
      nameCache.delete(symbol) // 失败允许后续重试
    })
}

/** 订阅指定品种的名称；名称在后台解析完成后触发重渲染。 */
export function useSymbolName(symbol?: string | null): string {
  const [name, setName] = useState(() => cachedSymbolName(symbol))
  useEffect(() => {
    setName(cachedSymbolName(symbol))
    resolveSymbolName(symbol)
    const listener = () => setName(cachedSymbolName(symbol))
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  }, [symbol])
  return name
}

const TF_ZH: Record<string, string> = {
  '1m': '1分钟', '2m': '2分钟', '3m': '3分钟', '5m': '5分钟', '10m': '10分钟', '15m': '15分钟', '20m': '20分钟', '30m': '30分钟',
  '1h': '1小时', '2h': '2小时', '3h': '3小时', '4h': '4小时', '6h': '6小时', '8h': '8小时', '12h': '12小时',
  '1d': '日线', '1w': '周线', '1M': '月线',
}

/** 周期显示为中文；未知周期原样返回。 */
export function tfZh(tf?: string | null): string {
  if (!tf) return ''
  return TF_ZH[tf] ?? tf
}
