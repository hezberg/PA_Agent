// Brooks 价格行为术语中文映射 + hover 含义提示。
// 枚举取值与 pa_agent/ai/cycle_enums.py、prompt_engineering/_reference/pattern_enum.md 对齐；
// 未收录的值原样返回（AI 偶发新词不阻断显示）。

export type Term = { zh: string; hint?: string }

/** 周期频谱八态（按趋势强度从最陡到最平） */
export const CYCLE_TERMS: Record<string, Term> = {
  spike: {
    zh: '尖峰',
    hint: '爆发式突破：连续2根以上大实体趋势棒、棒间重叠<30%。最强趋势状态，仅顺向操作、禁止追第三根',
  },
  micro_channel: {
    zh: '微型通道',
    hint: '几乎无回调的单边急行，K线一根接一根基本不重叠。追高风险大，等回调或旗形再入',
  },
  tight_channel: {
    zh: '窄通道',
    hint: '通道态，波段回撤<30%，趋势很强。顺势突破/回调入场，禁止逆势单',
  },
  normal_channel: {
    zh: '正常通道',
    hint: '通道态，波段回撤30%~50%，趋势健康。标准通道策略：回调至均线/前波段末端顺向入场',
  },
  broad_channel: {
    zh: '宽通道',
    hint: '通道态，波段回撤50%~78.6%，常是倾斜的交易区间。需要更多确认、减小仓位',
  },
  trending_tr: {
    zh: '趋势型交易区间',
    hint: '有方向偏好但仅2组波段、画不出稳定通道线（宽通道的退化形态）。波段操作，警惕方向反转',
  },
  trading_range: {
    zh: '交易区间',
    hint: '横盘震荡：上下边界清晰、EMA走平。低买高卖，区间中部不入场',
  },
  extreme_tr: {
    zh: '极端交易区间',
    hint: '方向完全丧失、EMA纠缠，任意入场期望为负。最难操作的状态，最好观望',
  },
  unknown: { zh: '未知', hint: '状态无法判定' },
}

/** 方向 */
export const DIRECTION_TERMS: Record<string, Term> = {
  bullish: { zh: '看涨（多头）', hint: '价格预期向上' },
  bearish: { zh: '看跌（空头）', hint: '价格预期向下' },
  neutral: { zh: '中性（无方向）', hint: '多空力量均衡，无明确预期' },
  up: { zh: '向上' },
  down: { zh: '向下' },
  long: { zh: '做多' },
  short: { zh: '做空' },
}

/** 诊断字段枚举 */
export const DIAG_TERMS: Record<string, Term> = {
  // spike_stage 尖峰阶段
  active: { zh: '进行中' },
  ending: { zh: '减弱中' },
  transitioning: { zh: '转换中', hint: '原状态已结束，正在转向通道/区间' },
  stable: { zh: '稳定持续' },
  // climax_risk 高潮风险
  none: { zh: '无' },
  warning: { zh: '警告', hint: '连续强趋势棒过多但未衰竭，禁止继续追单' },
  triggered: { zh: '已触发', hint: '出现长尾/小实体/反向棒等衰竭信号，禁止追多/追空' },
  // transition_risk 误判风险
  low: { zh: '低' },
  medium: { zh: '中' },
  high: { zh: '高' },
  // gate_result 阶段一闸门
  proceed: { zh: '通过', hint: '诊断完成，允许进入阶段二决策' },
  stop: { zh: '拦截', hint: '不满足进入决策的条件（如数据不足）' },
  // trend_context.relationship 大小周期关系
  conflict: { zh: '冲突', hint: '大周期与交易周期方向相反，胜率打折' },
  aligned: { zh: '一致', hint: '大周期与交易周期同向' },
}

/** Brooks 形态标签（pattern_enum.md） */
export const PATTERN_TERMS: Record<string, Term> = {
  wedge: { zh: '楔形/三推', hint: '三推结构，常孕育反转' },
  reversal_attempt: { zh: '反转尝试', hint: '未必满足完整反转条件' },
  mtr: { zh: '主要趋势反转', hint: '趋势线突破+前极点测试失败' },
  final_flag: { zh: '最终旗形', hint: '趋势末端旗形，禁止顺势追' },
  h1: { zh: '高1', hint: '多头第一次回调计数入场点' },
  h2: { zh: '高2', hint: '多头第二次回调计数入场点（经典入场）' },
  l1: { zh: '低1', hint: '空头第一次反弹计数入场点' },
  l2: { zh: '低2', hint: '空头第二次反弹计数入场点（经典入场）' },
  breakout_failure: { zh: '突破失败', hint: '突破后快速跌回原结构内' },
  failed_breakout: { zh: '突破失败', hint: '同 breakout_failure' },
  breakout_test: { zh: '突破回测', hint: '突破后回踩突破位' },
  breakout_pullback: { zh: '突破回踩', hint: '失败的突破失败，顺向信号' },
  barbwire: { zh: '铁丝网', hint: '极紧凑交易区间，避开' },
  wire: { zh: '铁丝网', hint: '同 barbwire' },
  overlap: { zh: '高度重叠', hint: 'K线重叠、方向不明' },
  middle_range: { zh: '区间中部', hint: '处于区间中间，交易价值低' },
  always_in: { zh: '总在场状态', hint: 'Always In：若现在空仓应持有的方向' },
  ail: { zh: '总在场做多', hint: 'Always In Long：方向偏多' },
  ais: { zh: '总在场做空', hint: 'Always In Short：方向偏空' },
  '20gb': { zh: '20根未触均线', hint: '连续约20根K线未回到EMA，趋势过热' },
  gap_bar: { zh: '均线缺口棒', hint: 'K线与均线间的缺口，非开盘跳空' },
  opening_gap: { zh: '开盘跳空', hint: '开盘价跳空缺口' },
  spike_candidate: { zh: '尖峰候选', hint: '单根超大突破棒，尚不构成尖峰' },
  spike_active: { zh: '尖峰进行中' },
  spike_ending: { zh: '尖峰减弱' },
  spike_transitioning: { zh: '尖峰转换中' },
  double_top_bottom: { zh: '双顶/双底', hint: '含微型双顶双底' },
  climax_warning: { zh: '高潮警告' },
  climax_triggered: { zh: '高潮已触发' },
  shrinking_stairs: { zh: '收缩台阶', hint: '推进幅度递减，动能衰竭' },
  failed_signal: { zh: '信号失败', hint: '失败信号的入场/止损价成为磁力位' },
  magnet: { zh: '磁力位', hint: '价格被吸引的价位' },
  trapped_traders: { zh: '被套交易者', hint: '套牢盘结构，常引发二次推动' },
  ascending_triangle: { zh: '上升三角形' },
  descending_triangle: { zh: '下降三角形' },
  symmetrical_triangle: { zh: '对称三角形' },
  expanding_triangle: { zh: '扩张三角形' },
  trend_bull: { zh: '趋势阳线' },
  trend_bear: { zh: '趋势阴线' },
  doji: { zh: '十字星' },
  inside: { zh: '内包线', hint: '高低点都在前一根范围内' },
  outside_bull: { zh: '外包阳线', hint: '吞没前一根的阳线' },
  outside_bear: { zh: '外包阴线', hint: '吞没前一根的阴线' },
  flat: { zh: '平盘' },
  other: { zh: '其他' },
}

/** 任意枚举值 → 中文；hover 提示由 termHint 单独取 */
export function zhTerm(value: string | null | undefined): string {
  const v = String(value ?? '').trim()
  if (!v) return v ?? ''
  return (
    CYCLE_TERMS[v]?.zh ?? DIRECTION_TERMS[v]?.zh ?? DIAG_TERMS[v]?.zh ?? PATTERN_TERMS[v]?.zh ?? v
  )
}

/** 任意枚举值 → hover 提示（无解释时返回 undefined） */
export function termHint(value: string | null | undefined): string | undefined {
  const v = String(value ?? '').trim()
  if (!v) return undefined
  return (
    CYCLE_TERMS[v]?.hint ??
    DIRECTION_TERMS[v]?.hint ??
    DIAG_TERMS[v]?.hint ??
    PATTERN_TERMS[v]?.hint
  )
}
