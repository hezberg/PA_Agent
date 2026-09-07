import { useStore } from '../../store'

const OUTCOME_ZH: Record<string, string> = {
  trade: '交易',
  wait: '等待',
  watch: '观望',
  reject: '否决',
}

export default function TreeTab() {
  const trace = useStore((s) => s.decision?.tree_trace)
  if (!trace || trace.path.length === 0) {
    return <div className="muted" style={{ padding: 12 }}>等待分析结果…</div>
  }

  const banner = trace.banner
  let bannerCls = ''
  let bannerText = '无终点信息'
  if (banner) {
    const outcomeZh = OUTCOME_ZH[banner.outcome] ?? banner.outcome
    bannerText = banner.node_id
      ? `终点 · §${banner.node_id} · ${outcomeZh}\n${banner.label}`
      : `阶段一闸门：${outcomeZh}（${banner.outcome}）\n未调用阶段二模型。`
    bannerCls =
      banner.outcome === 'trade'
        ? 'terminal-banner'
        : banner.outcome === 'reject'
          ? 'terminal-banner'
          : 'terminal-banner'
  }

  return (
    <div>
      <div className={bannerCls} style={{ whiteSpace: 'pre-wrap' }}>{bannerText}</div>
      {trace.gate_shortcircuited && (
        <div className="muted" style={{ marginBottom: 8 }}>
          阶段一闸门未通过（wait/unknown）：已跳过阶段二 API 调用；「不下单」为程序根据闸门结论自动生成。
        </div>
      )}
      {!trace.gate_shortcircuited && trace.gate_result && (
        <div className="muted" style={{ marginBottom: 8 }}>阶段一 gate_result：{trace.gate_result}</div>
      )}

      <div className="panel-title">路径回放（阶段一闸门 → 阶段二策略）</div>
      <table className="data-table">
        <thead>
          <tr>
            <th>步</th><th>阶段</th><th>节点</th><th>回答</th><th>K线依据</th><th>理由</th>
          </tr>
        </thead>
        <tbody>
          {trace.path.map((row) => (
            <tr key={row.step}>
              <td>{row.step}</td>
              <td>{row.phase === 'gate' ? '闸门' : '决策'}</td>
              <td title={row.question}>§{row.node_id}</td>
              <td>{row.answer || '—'}</td>
              <td>{row.bar_basis || '—'}</td>
              <td>{row.reasoning}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
