// 共享切票链路：自选清单 / 顶栏候选共用。
// 非通达信源先自动切换数据来源（含「正在切换中」重试），再订阅 + 拉数据；可选拉起 K 线面板。
import { api } from './api/client'
import { useStore } from './store'
import type { Meta } from './api/types'

async function refetchMeta() {
  const m = await api.get('/api/meta')
  if (m.ok) useStore.getState().setMeta(m as Meta)
}

/**
 * 切换到指定品种（subCode 为可直接订阅通达信源的代码，如 600519 / 00700）。
 * 失败以 toast 呈现并返回 false。
 */
export async function switchToSymbol(
  subCode: string,
  opts?: { timeframe?: string; expandChart?: boolean; armAutoIncremental?: false },
): Promise<boolean> {
  const s = useStore.getState()
  const meta = s.meta
  const timeframe = opts?.timeframe ?? meta?.timeframe ?? '1d'
  const pushToast = s.pushToast
  const code = subCode.trim()
  if (!code) return false

  const sameSub = meta?.active_kind === 'easytdx' && meta?.symbol === code && meta?.timeframe === timeframe

  // 视图与选中状态先行：点自选/候选 = 用户明确要看这只票（跳转不依赖后续网络结果）
  if (opts?.expandChart) {
    useStore.getState().setChartOpen(true)
    useStore.getState().setMView('chart') // 移动端：点击自选/候选 → 跳图表视图
  }
  useStore.getState().chooseSymbol()

  if (!sameSub && meta?.active_kind !== 'easytdx') {
    // A 股/港股代码只有通达信源可订阅：先切换数据来源；上次切换可能仍在进行，稍候重试。
    let r = await api.post('/api/data-source', { kind: 'easytdx', symbol: code, timeframe })
    for (let i = 0; !r.ok && /正在切换中/.test(r.error ?? '') && i < 3; i++) {
      await new Promise((res) => setTimeout(res, 1500))
      r = await api.post('/api/data-source', { kind: 'easytdx', symbol: code, timeframe })
    }
    if (!r.ok) {
      pushToast({ level: 'error', title: '切换数据来源失败', message: r.error ?? '' })
      await refetchMeta()
      return false
    }
    // data-source 路由内部已重启刷新循环，无需再调 /api/fetch
  } else if (!sameSub) {
    const r = await api.post('/api/subscribe', {
      symbol: code,
      timeframe,
      arm_auto_incremental: opts?.armAutoIncremental ?? false,
    })
    if (!r.ok) {
      pushToast({ level: 'error', title: '切换失败', message: r.error ?? '订阅失败' })
      await refetchMeta()
      return false
    }
    // subscribe 路由内部已重启刷新循环
  } else {
    // 同品种同周期：显式强制重新拉取一轮
    const r = await api.post('/api/fetch')
    if (!r.ok) pushToast({ level: 'error', title: '刷新失败', message: r.error ?? '' })
    await refetchMeta()
    return true
  }

  await refetchMeta()
  return true
}
