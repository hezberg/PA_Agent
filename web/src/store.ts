// Global UI store — fed by the SSE event streams and REST bootstrap.
import { create } from 'zustand'
import type {
  ChatMsg,
  DecisionPanelPayload,
  FlowStep,
  FramePayload,
  Meta,
  UiState,
} from './api/types'

export type StreamPane = {
  stage: string
  title: string
  reasoning: string
  content: string
  active: boolean
}

const FLOW_STEPS = ['数据', '快照', '诊断', '决策', '追问']

export interface ToastItem {
  id: number
  level: 'info' | 'warning' | 'error' | 'success'
  title: string
  message: string
}

interface Store {
  // market
  meta: Meta | null
  frame: FramePayload | null
  price: { price: string; color: string } | null
  lastRefreshTs: number
  stale: boolean

  // submission state
  ui: UiState | null
  statusText: string
  fetchProgress: { stage: string; text: string } | null
  flowSteps: FlowStep[]
  countdown: number | null

  // streaming analysis
  panes: StreamPane[]
  streaming: boolean
  livePrompts: { stage: string; system: string; user: string }[]
  stage2Files: string[]
  retries: string[]
  decision: DecisionPanelPayload | null

  // chat
  chatHistory: ChatMsg[]
  chatStreaming: boolean
  chatDraft: { reasoning: string; content: string } | null
  chatEnabled: boolean

  // demo
  demoName: string | null

  // toasts / modals
  toasts: ToastItem[]
  modal: 'ai' | 'general' | 'feishu' | 'ths' | 'validation' | null
  validationBody: { title: string; summary: string; body: string } | null

  // K 线展开状态（自选清单点击切票时需要跨组件展开）
  chartOpen: boolean
  /** 本次会话中用户是否主动选过票（未选前移动端图表视图显示引导而非默认 K 线） */
  symbolChosen: boolean
  /** 移动端当前主视图 */
  mView: 'watchlist' | 'chart' | 'analysis'

  // actions
  setMeta: (m: Meta) => void
  applyUiState: (u: Partial<UiState>) => void
  setStatus: (text: string) => void
  applyFetchProgress: (p: { stage: string; text: string }) => void
  applyFrame: (f: FramePayload) => void
  setPrice: (p: { price: string; color: string } | null) => void
  resetFlow: () => void
  clearStaleAnalysis: () => void
  applyFlowStep: (s: { index?: number; status?: FlowStep['status']; caption?: string; reset?: boolean }) => void
  startStream: (title: string) => void
  appendReasoning: (stage: string, chunk: string) => void
  appendContent: (stage: string, chunk: string) => void
  addLivePrompt: (stage: string, system: string, user: string) => void
  setStage2Files: (files: string[]) => void
  markRetry: (stage: string) => void
  applyDecision: (payload: DecisionPanelPayload) => void
  finishStream: () => void
  setChatStreaming: (v: boolean) => void
  setChatDraft: (d: { reasoning: string; content: string } | null) => void
  appendChat: (msg: ChatMsg) => void
  setChatHistory: (h: ChatMsg[]) => void
  setChatEnabled: (v: boolean) => void
  setDemoName: (name: string | null) => void
  pushToast: (t: Omit<ToastItem, 'id'>) => void
  dismissToast: (id: number) => void
  openModal: (m: Store['modal']) => void
  showValidation: (v: { title: string; summary: string; body: string }) => void
  toggleChart: () => void
  chooseSymbol: () => void
  setMView: (v: 'watchlist' | 'chart' | 'analysis') => void
  setChartOpen: (v: boolean) => void
}

let toastSeq = 1

function makeSteps(): FlowStep[] {
  return FLOW_STEPS.map((label, index) => ({
    index,
    status: 'idle' as const,
    caption: label,
  }))
}

export const useStore = create<Store>((set) => ({
  meta: null,
  frame: null,
  price: null,
  lastRefreshTs: 0,
  stale: false,
  ui: null,
  statusText: '就绪',
  fetchProgress: null,
  flowSteps: makeSteps(),
  countdown: null,
  panes: [],
  streaming: false,
  livePrompts: [],
  stage2Files: [],
  retries: [],
  decision: null,
  chatHistory: [],
  chatStreaming: false,
  chatDraft: null,
  chatEnabled: false,
  demoName: null,
  toasts: [],
  modal: null,
  validationBody: null,
  chartOpen:
    typeof window !== 'undefined' &&
    (window.location.hash === '#chart' || localStorage.getItem('pa.chart.open') === '1'),
  symbolChosen: false,
  mView: 'watchlist',

  // 品种变化：上一只票的分析结论/实时流立即清理，避免误读为新票的结果
  setMeta: (m) =>
    set((s) => {
      const switched = Boolean(s.meta && s.meta.symbol && m.symbol && s.meta.symbol !== m.symbol)
      return {
        meta: m,
        ...(switched ? { decision: null, panes: [], streaming: false } : {}),
      }
    }),
  applyUiState: (u) =>
    set((s) => ({
      ui: { ...(s.ui ?? ({} as UiState)), ...u },
      countdown: u.wait_close ? (u.wait_close.seconds_remaining ?? null) : s.countdown,
      chatEnabled: u.analysis_in_progress === false ? s.chatEnabled : s.chatEnabled,
    })),
  setStatus: (text) => set({ statusText: text || '' }),
  applyFetchProgress: (p) => set({ fetchProgress: p }),
  applyFrame: (f) => set({ frame: f, lastRefreshTs: Date.now(), stale: false }),
  setPrice: (p) => set({ price: p }),

  resetFlow: () => {
    const steps = makeSteps()
    steps[0] = { index: 0, status: 'done', caption: '已就绪' }
    set({ flowSteps: steps })
  },

  applyFlowStep: (s) =>
    set((state) => {
      if (s.reset) return { flowSteps: makeSteps() }
      const steps = state.flowSteps.map((x) => ({ ...x }))
      if (s.index !== undefined) {
        const target = steps[s.index]
        if (target) {
          if (s.status) target.status = s.status
          if (s.caption) target.caption = s.caption
        }
      }
      return { flowSteps: steps }
    }),

  startStream: (title) =>
    set({
      panes: [
        { stage: 'stage1', title, reasoning: '', content: '', active: true },
      ],
      streaming: true,
      livePrompts: [],
      stage2Files: [],
      retries: [],
    }),

  appendReasoning: (stage, chunk) =>
    set((s) => {
      const panes = [...s.panes]
      let pane = panes.find((p) => p.stage === stage)
      if (!pane) {
        pane = {
          stage,
          title: stage === 'stage2' ? '阶段二：交易决策' : '阶段一：市场诊断',
          reasoning: '',
          content: '',
          active: true,
        }
        panes.push(pane)
      }
      pane.reasoning += chunk
      pane.active = true
      return { panes }
    }),

  appendContent: (stage, chunk) =>
    set((s) => {
      const panes = [...s.panes]
      let pane = panes.find((p) => p.stage === stage)
      if (!pane) {
        pane = {
          stage,
          title: stage === 'stage2' ? '阶段二：交易决策' : '阶段一：市场诊断',
          reasoning: '',
          content: '',
          active: true,
        }
        panes.push(pane)
      }
      pane.content += chunk
      return { panes }
    }),

  addLivePrompt: (stage, system, user) =>
    set((s) => ({
      livePrompts: [
        ...s.livePrompts,
        { stage, system, user },
      ],
    })),

  setStage2Files: (files) => set({ stage2Files: files }),
  markRetry: (stage) =>
    set((s) => ({ retries: [...s.retries.slice(-9), stage] })),

  applyDecision: (payload) =>
    set({
      decision: payload,
      streaming: false,
      chatEnabled: true,
    }),

  finishStream: () => set({ streaming: false }),

  setChatStreaming: (v) => set({ chatStreaming: v }),
  setChatDraft: (d) => set({ chatDraft: d }),
  appendChat: (msg) => set((s) => ({ chatHistory: [...s.chatHistory, msg] })),
  setChatHistory: (h) => set({ chatHistory: h }),
  setChatEnabled: (v) => set({ chatEnabled: v }),

  setDemoName: (name) => set({ demoName: name }),

  pushToast: (t) =>
    set((s) => ({ toasts: [...s.toasts.slice(-5), { ...t, id: toastSeq++ }] })),
  dismissToast: (id) =>
    set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),
  openModal: (m) => set({ modal: m }),
  toggleChart: () =>
    set((s) => {
      const v = !s.chartOpen
      localStorage.setItem('pa.chart.open', v ? '1' : '0')
      return { chartOpen: v }
    }),
  setChartOpen: (v) => {
    localStorage.setItem('pa.chart.open', v ? '1' : '0')
    set({ chartOpen: v })
  },
  chooseSymbol: () => set({ symbolChosen: true }),
  clearStaleAnalysis: () => set({ decision: null, panes: [], streaming: false }),
  setMView: (v) => set({ mView: v }),
  showValidation: (v) => set({ validationBody: v, modal: 'validation' }),
}))

export { FLOW_STEPS }

// 调试钩子：控制台可用 __pa_store.getState() 检查/注入状态（亦用于自动化验收）。
declare global {
  interface Window {
    __pa_store?: typeof useStore
  }
}
if (typeof window !== 'undefined') window.__pa_store = useStore
