import { useEffect, useRef, useState } from 'react'
import { api, openStream } from './api/client'
import { useStore } from './store'
import ControlBar from './components/ControlBar'
import FlowBar from './components/FlowBar'
import SummaryStrip from './components/SummaryStrip'
import ChartPanel from './components/ChartPanel'
import Sidebar from './components/Sidebar'
import StatusBar from './components/StatusBar'
import Toasts from './components/Toasts'
import SettingsModals from './components/SettingsModals'
import type { DecisionPanelPayload, FramePayload, Meta, UiState } from './api/types'

/** Beep via WebAudio (order-opportunity alert; replaces Qt QApplication.beep). */
function beep() {
  try {
    const ctx = new AudioContext()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.frequency.value = 880
    gain.gain.setValueAtTime(0.2, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6)
    osc.start()
    osc.stop(ctx.currentTime + 0.6)
  } catch {
    /* audio unavailable */
  }
}

export default function App() {
  const store = useStore()
  const analysisCloser = useRef<null | (() => void)>(null)
  const demoCloser = useRef<null | (() => void)>(null)

  useEffect(() => {
    // ── Bootstrap static + dynamic meta ────────────────────────────────────
    api.get('/api/meta').then((m: Meta) => {
      useStore.getState().setMeta(m)
      // Chart bootstrap: fetch a snapshot when a source is already connected
      // (covers joining mid-session, e.g. after the refresh loop is running).
      if (m.source_connected) {
        api.get('/api/klines').then((r) => {
          if (r.ok && r.frame) useStore.getState().applyFrame(r.frame as FramePayload)
        })
      }
    })
    api
      .get('/api/analysis/state')
      .then((u: UiState) => useStore.getState().applyUiState(u))

    // ── Main UI stream (frames + broadcast events) ─────────────────────────
    const closeMain = openStream('/api/stream/frames', (type, data) => {
      const s = useStore.getState()
      switch (type) {
        case 'bars':
          break // bars payload is superseded by composed frame for the chart
        case 'frame':
          s.applyFrame(data as unknown as FramePayload)
          break
        case 'price':
          s.setPrice(data as unknown as { price: string; color: string })
          break
        case 'status':
          s.setStatus(String(data.text ?? ''))
          break
        case 'fetch_progress':
          s.applyFetchProgress({
            stage: String(data.stage ?? ''),
            text: String(data.text ?? ''),
          })
          break
        case 'state':
          s.applyUiState(data as Partial<UiState>)
          break
        case 'flow_reset':
          s.resetFlow()
          break
        case 'flow_step':
          s.applyFlowStep(data as never)
          break
        case 'analysis_started': {
          const channel = String(data.channel ?? '')
          if (channel) {
            analysisCloser.current?.()
            analysisCloser.current = attachAnalysisStream(channel)
          }
          break
        }
        case 'record_payload':
          s.applyDecision(data as unknown as DecisionPanelPayload)
          s.applyFlowStep({ index: 4, status: 'active', caption: '可追问' })
          break
        case 'order_opportunity':
          beep()
          s.pushToast({ level: 'warning', title: '下单机会', message: String(data.message ?? '') })
          break
        case 'alert':
          s.pushToast({
            level: (data.level as 'info' | 'warning') ?? 'info',
            title: String(data.title ?? '提示'),
            message: String(data.message ?? ''),
          })
          break
        case 'tv_blocked':
          s.pushToast({
            level: 'warning',
            title: 'TradingView 连接受限',
            message: String(data.detail ?? '') +
              '\n可切换数据源为 MT5，或检查网络后重试。',
          })
          break
        case 'token_update':
          break
        case 'settings_updated':
          api.get('/api/meta').then((m: Meta) => useStore.getState().setMeta(m))
          s.pushToast({ level: 'success', title: '设置已保存', message: '' })
          break
      }
    })

    // ── Demo stream (always attached; events only fire in demo mode) ───────
    demoCloser.current = openStream('/api/demo/stream', (type, data) => {
      const s = useStore.getState()
      switch (type) {
        case 'demo_started':
          s.setDemoName(String(data.name ?? ''))
          s.startStream('阶段一：市场诊断')
          s.applyUiState({ demo_mode: true, analysis_in_progress: true })
          if (data.frame) s.applyFrame(data.frame as FramePayload)
          break
        case 'status':
          s.setStatus(String(data.text ?? ''))
          break
        case 'stage_prompt':
          s.addLivePrompt(String(data.stage ?? ''), String(data.system ?? ''), String(data.user ?? ''))
          break
        case 'reasoning_token':
          s.appendReasoning(String(data.stage ?? ''), String(data.chunk ?? ''))
          break
        case 'content_token':
          s.appendContent(String(data.stage ?? ''), String(data.chunk ?? ''))
          break
        case 'stage2_files':
          s.setStage2Files((data.files as string[]) ?? [])
          break
        case 'record':
          break
        case 'finished':
          s.finishStream()
          break
        case 'state':
          s.applyUiState(data as Partial<UiState>)
          break
      }
    })

    return () => {
      closeMain()
      analysisCloser.current?.()
      demoCloser.current?.()
    }
  }, [])

  // Refresh meta + state every 15 s (cheap; covers out-of-band changes).
  useEffect(() => {
    const t = setInterval(() => {
      api.get('/api/meta').then((m: Meta) => useStore.getState().setMeta(m))
      api.get('/api/analysis/state').then((u: UiState) => useStore.getState().applyUiState(u))
    }, 15000)
    return () => clearInterval(t)
  }, [])

  return (
    <div className="app">
      <MenuBar />
      <ControlBar />
      <div className="api-alert" style={{ display: store.meta?.api_key_configured ? 'none' : undefined }}>
        未配置 API Key：请点击上方「AI 模型设置」，在设置中填写 API Key 后才能进行 AI 分析。
      </div>
      <div className="disclaimer">分析仅供参考，不构成投资建议</div>
      <StatusRow />
      <FlowBar />
      <SummaryStrip />
      <div className="workbench">
        <ChartPanel />
        <Sidebar />
      </div>
      <StatusBar />
      <Toasts />
      <SettingsModals />
    </div>
  )
}

function attachAnalysisStream(channel: string): () => void {
  return openStream(`/api/analysis/stream/${channel.split(':').pop() ?? ''}`, (type, data) => {
    const s = useStore.getState()
    switch (type) {
      case 'stage_prompt':
        s.addLivePrompt(String(data.stage ?? ''), String(data.system ?? ''), String(data.user ?? ''))
        break
      case 'reasoning_token':
        s.appendReasoning(String(data.stage ?? ''), String(data.chunk ?? ''))
        break
      case 'content_token':
        s.appendContent(String(data.stage ?? ''), String(data.chunk ?? ''))
        break
      case 'stage2_files':
        s.setStage2Files((data.files as string[]) ?? [])
        s.applyFlowStep({ index: 3, status: 'active', caption: '决策中…' })
        break
      case 'retry_occurred':
        s.markRetry(String(data.stage ?? ''))
        break
      case 'flow_step':
        s.applyFlowStep(data as never)
        break
      case 'finished':
        s.finishStream()
        break
    }
  })
}

function MenuBar() {
  const openModal = useStore((s) => s.openModal)
  const demo = useStore((s) => s.ui?.demo_mode)
  return (
    <div className="menu-bar">
      <button onClick={() => openModal('ai')}>AI 模型设置</button>
      <button onClick={() => openModal('feishu')}>飞书发送通知设置</button>
      <button onClick={() => openModal('general')}>其他通用设置</button>
      <div className="spacer" />
      <button
        onClick={async () => {
          if (demo) {
            await api.post('/api/demo/stop')
          } else {
            const r = await api.post('/api/demo/start', { mode: 'auto' })
            if (!r.ok) useStore.getState().pushToast({ level: 'error', title: '演示模式', message: r.error ?? '' })
          }
        }}
      >
        {demo ? '退出演示模式' : '演示模式'}
      </button>
    </div>
  )
}

function StatusRow() {
  const lastRefreshTs = useStore((s) => s.lastRefreshTs)
  const paused = useStore((s) => s.ui?.chart_refresh_paused)
  const [now] = useStateWithInterval()

  let elapsedLabel = '距上次刷新: —'
  let cls = ''
  if (paused) {
    elapsedLabel = '图表刷新已暂停'
    cls = 'paused'
  } else if (lastRefreshTs > 0) {
    const elapsed = Math.max(0, Math.floor((now - lastRefreshTs) / 1000))
    const m = Math.floor(elapsed / 60)
    const s = elapsed % 60
    elapsedLabel = elapsed < 60 ? `距上次刷新: ${elapsed}s` : `距上次刷新: ${m}m${String(s).padStart(2, '0')}s`
    if (elapsed > 10) cls = 'stale'
  }
  return (
    <div className="status-row">
      {countdownLabel()}
      <span className={cls}>{elapsedLabel}</span>
    </div>
  )
}

function countdownLabel(): string | null {
  const ui = useStore((s) => s.ui)
  if (!ui?.wait_close?.armed) return null
  const secs = ui.wait_close.seconds_remaining
  return secs !== null && secs !== undefined ? `还剩 ${secs} 秒` : null
}

function useStateWithInterval(): [number, () => void] {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  return [now, () => setNow(Date.now())]
}
