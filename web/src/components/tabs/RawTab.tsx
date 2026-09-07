import { useEffect, useState } from 'react'
import { useStore } from '../../store'
import type { DebugTurn } from '../../api/types'

export default function RawTab() {
  const decision = useStore((s) => s.decision)
  const livePrompts = useStore((s) => s.livePrompts)
  const [selected, setSelected] = useState(0)

  // Merge live stage prompts (streaming) with finished debug turns.
  const liveTurns: DebugTurn[] = livePrompts.map((p, i) => ({
    label: `Stage${p.stage === 'stage1' ? '1' : '2'} 发送（实时 #${i + 1}）`,
    system_prompt: p.system,
    user_prompt: p.user,
    raw_response: {},
    validation_info: '',
  }))
  const turns = [...liveTurns, ...(decision?.debug_turns ?? [])]

  useEffect(() => {
    setSelected(Math.max(0, turns.length - 1))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [decision])

  if (turns.length === 0) {
    return <div className="muted" style={{ padding: 12 }}>暂无数据。分析开始后这里会显示每轮发送的完整 Prompt 与模型原始响应。</div>
  }

  const turn = turns[Math.min(selected, turns.length - 1)]

  async function copyAll() {
    const text = [
      `--- ${turn.label} ---`,
      '--- System Prompt ---',
      turn.system_prompt,
      '--- User Prompt ---',
      turn.user_prompt,
      '--- Raw Response ---',
      JSON.stringify(turn.raw_response ?? {}, null, 2),
      '--- Validation ---',
      turn.validation_info,
    ].join('\n')
    await navigator.clipboard.writeText(text)
    useStore.getState().pushToast({ level: 'success', title: '已复制', message: '调试信息已复制到剪贴板' })
  }

  return (
    <div className="raw-layout">
      <div className="raw-list">
        {turns.map((t, i) => (
          <button key={i} className={i === selected ? 'active' : ''} onClick={() => setSelected(i)}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="raw-detail">
        <button className="copy-btn" onClick={copyAll}>
          复制调试信息
        </button>
        <h4 style={{ margin: '0 0 6px', fontSize: 12 }}>System Prompt</h4>
        <pre>{turn.system_prompt || '（空）'}</pre>
        <h4 style={{ margin: '10px 0 6px', fontSize: 12 }}>User Prompt</h4>
        <pre>{turn.user_prompt || '（空）'}</pre>
        {Boolean(turn.raw_response) && Object.keys(turn.raw_response as object).length > 0 && (
          <>
            <h4 style={{ margin: '10px 0 6px', fontSize: 12 }}>Raw Response</h4>
            <pre>{JSON.stringify(turn.raw_response, null, 2)}</pre>
          </>
        )}
        {turn.validation_info && (
          <>
            <h4 style={{ margin: '10px 0 6px', fontSize: 12 }}>Validation / Exception</h4>
            <pre>{turn.validation_info}</pre>
          </>
        )}
      </div>
    </div>
  )
}
