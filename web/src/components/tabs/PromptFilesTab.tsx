import { useStore } from '../../store'

export default function PromptFilesTab() {
  const files = useStore((s) => s.decision?.prompt_files)
  const stage2Files = useStore((s) => s.stage2Files)

  const stage1 = files?.stage1 ?? []
  const stage2 = files?.stage2 ?? (stage2Files.length ? stage2Files : [])

  return (
    <div>
      <div className="panel-section">
        <div className="panel-title">Stage 1 · 诊断提示词文件</div>
        {stage1.length === 0 ? (
          <span className="muted">等待分析…</span>
        ) : (
          stage1.map((f) => <div key={f} className="kv-row"><span className="pill cyan">{f}</span></div>)
        )}
      </div>

      <div className="panel-section">
        <div className="panel-title">Stage 2 · 策略提示词文件</div>
        {stage2.length === 0 ? (
          <span className="muted">等待阶段二…</span>
        ) : (
          stage2.map((f) => <div key={f} className="kv-row"><span className="pill blue">{f}</span></div>)
        )}
      </div>

      {files && (
        <div className="muted">本轮加载经验案例：{files.experience_count} 条</div>
      )}
    </div>
  )
}
