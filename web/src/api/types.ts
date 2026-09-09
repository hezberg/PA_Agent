// Shared types mirroring pa_agent/server payloads.

export interface Bar {
  seq: number
  ts_open: number
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number
  pct_chg: number | null
  closed: boolean
}

export interface FramePayload {
  symbol: string
  timeframe: string
  snapshot_ts_local_ms: number
  bars: Bar[]            // oldest → newest
  ema20: (number | null)[]
  atr14: (number | null)[]
}

export interface Meta {
  data_sources: { kind: string; label: string }[]
  active_kind: string
  active_label: string
  symbol: string
  timeframe: string
  exchange: string
  tv_exchanges: string[]
  default_symbol: string
  symbol_placeholder: string
  symbol_alert: string | null
  symbols: string[]
  timeframes: string[]
  futures_varieties: string[]
  source_connected: boolean
  refresh_running: boolean
  analysis_bar_count: number
  ai_mode_label: string
  api_key_configured: boolean
  ths_enabled?: boolean
}

export interface WaitCloseState {
  armed: boolean
  seconds_remaining: number | null
  force_incremental: boolean
}

export interface UiState {
  analysis_in_progress: boolean
  demo_mode: boolean
  submit_block_reason: string | null
  incremental_available: boolean
  chart_refresh_paused: boolean
  wait_close: WaitCloseState
  keep_analysis: boolean
  last_refresh_ts: number
}

export interface FlowStep {
  index: number
  status: 'idle' | 'active' | 'done' | 'error'
  caption: string
}

export interface TreePathRow {
  step: number
  phase: string
  node_id: string
  question: string
  answer: string
  bar_basis: string
  reasoning: string
  skipped: boolean
}

export interface TreeTrace {
  path: TreePathRow[]
  terminal: { node_id: string; outcome: string; label?: string } | null
  banner: { node_id: string; outcome: string; label: string } | null
  gate_result: string | null
  gate_shortcircuited: boolean
}

export interface DebugTurn {
  label: string
  system_prompt: string
  user_prompt: string
  raw_response: unknown
  validation_info: string
}

export interface StageResult {
  stage: string
  title: string
  content: string
  reasoning: string
  cache_hit_pct: number | null
}

export interface PromptFiles {
  stage1: string[]
  stage2: string[]
  experience_count: number
}

export interface TokenDisplay {
  context_used: number
  context_window: number
  total_input: number
  total_cached_input: number
  total_output: number
}

export interface StructureLevel {
  kind: string
  low: number
  high: number
  label: string
  price: number
}

export interface DecisionPanelPayload {
  decision_inner: Record<string, unknown>
  diagnosis_summary: Record<string, unknown> | null
  stage1_diagnosis: Record<string, unknown> | null
  decision_stance: string | null
  confidence_threshold: number
  chart_decision: Record<string, unknown>
  support_resistance: StructureLevel[]
  summary_metrics: Record<string, string>
  tree_trace: TreeTrace
  debug_turns: DebugTurn[]
  stage_results: StageResult[]
  prompt_files: PromptFiles
  token_display: TokenDisplay | null
  exception: Record<string, unknown> | null
  stage2_full: Record<string, unknown>
  order_type: string
}

export interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
  reasoning_content?: string
}

export interface SettingsPayload {
  provider: Record<string, unknown>
  general: Record<string, unknown>
  prompt: Record<string, unknown>
  validation: Record<string, unknown>
  feishu: Record<string, unknown>
  pushplus: Record<string, unknown>
  tushare: Record<string, unknown>
  ths: Record<string, unknown>
}

export interface ThsGroup {
  id: string
  name: string
  readonly?: boolean
  items: { code: string; market: string; sub_code: string; name: string }[]
}

