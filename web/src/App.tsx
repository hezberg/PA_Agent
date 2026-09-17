import { useEffect, useRef } from 'react'
import { api, openStream } from './api/client'
import { useStore } from './store'
import { useIsMobile } from './useIsMobile'
import MobileShell from './components/MobileShell'
import TopBar from './components/TopBar'
import FlowBar from './components/FlowBar'
import ChartPanel from './components/ChartPanel'
import WatchlistPanel from './components/WatchlistPanel'
import Sidebar from './components/Sidebar'
import StatusBar from './components/StatusBar'
import Toasts from './components/Toasts'
import SettingsModals from './components/SettingsModals'
import { CandleIcon } from './icons'
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
  const analysisCloser = useRef<null | (() => void)>(null)
  const demoCloser = useRef<null | (() => void)>(null)
  const chartOpen = useStore((s) => s.chartOpen)
  const toggleChart = useStore((s) => s.toggleChart)
  const isMobile = useIsMobile()

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

  if (isMobile) return <MobileShell />

  return (
    <div className="app">
      <TopBar />
      <FlowBar />
      <div className={`workbench ${chartOpen ? "chart-open" : "chart-closed"}`}>
        <WatchlistPanel />
        {!chartOpen && (
          <button className="rail" title="展开 K 线图" onClick={toggleChart}>
            <CandleIcon />
            <span className="rail-txt">K 线</span>
          </button>
        )}
        <ChartPanel open={chartOpen} onCollapse={toggleChart} />
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
