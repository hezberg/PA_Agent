// Simplified animated decision-flow visualisation (SVG path walk with play control).
// Replaces the 1200-line QGraphicsScene sci-fi version: nodes appear step by
// step, edges light up, with a play/replay control and auto-fit layout.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useStore } from '../../store'
import type { TreePathRow } from '../../api/types'

const NODE_W = 148
const NODE_H = 46
const GAP_X = 52
const PAD = 24

interface LaidRow {
  row: TreePathRow
  x: number
  y: number
}

function layoutRows(rows: TreePathRow[], width: number): { laid: LaidRow[]; edges: [number, number][]; height: number } {
  const perRow = Math.max(2, Math.floor((width - PAD * 2) / (NODE_W + GAP_X)))
  const laid: LaidRow[] = rows.map((row, i) => {
    const line = Math.floor(i / perRow)
    const col = i % perRow
    const lineCount = Math.min(perRow, rows.length - line * perRow)
    const rowWidth = lineCount * (NODE_W + GAP_X) - GAP_X
    const x = (width - rowWidth) / 2 - NODE_W / 2 + col * (NODE_W + GAP_X) + NODE_W / 2
    const y = PAD + line * (NODE_H + 44)
    return { row, x, y }
  })
  const edges: [number, number][] = []
  for (let i = 0; i < laid.length - 1; i++) edges.push([i, i + 1])
  const height = PAD * 2 + Math.ceil(rows.length / perRow) * (NODE_H + 44)
  return { laid, edges, height: Math.max(height, 160) }
}

export default function FlowVizTab() {
  const trace = useStore((s) => s.decision?.tree_trace)
  const [playing, setPlaying] = useState(false)
  const [visible, setVisible] = useState(0)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(560)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setWidth(el.clientWidth))
    ro.observe(el)
    setWidth(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  const rows = trace?.path ?? []
  const { laid, edges, height } = layoutRows(rows, width)

  const play = useCallback(() => {
    if (rows.length === 0) return
    setVisible(0)
    setPlaying(true)
  }, [rows.length])

  useEffect(() => {
    if (!playing) return
    timer.current = setInterval(() => {
      setVisible((v) => {
        if (v >= rows.length) {
          setPlaying(false)
          return v
        }
        return v + 1
      })
    }, 450)
    return () => {
      if (timer.current) clearInterval(timer.current)
    }
  }, [playing, rows.length])

  // Auto-play once a new trace arrives (mirrors should_auto_play_after_load).
  useEffect(() => {
    if (rows.length > 0) play()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trace])

  const terminal = trace?.terminal

  return (
    <div ref={wrapRef}>
      <div className="flowviz-controls">
        <button className="primary" onClick={play} disabled={rows.length === 0}>
          {playing ? '播放中…' : '▶ 播放路径'}
        </button>
        <button onClick={() => setVisible(rows.length)} disabled={rows.length === 0}>
          全部显示
        </button>
        <span className="muted">
          {visible}/{rows.length} 节点
        </span>
      </div>

      {rows.length === 0 ? (
        <div className="muted" style={{ padding: 12 }}>
          等待分析结果… 决策路径将以动画方式逐步展示。
        </div>
      ) : (
        <svg className="flowviz-canvas" width={width} height={height + 60}>
          {/* phase bands */}
          <text className="fv-phase-label" x={PAD} y={14}>STAGE 1 · GATE</text>
          <text className="fv-phase-label" x={PAD} y={height + 34}>STAGE 2 · DECISION</text>

          {edges.map(([a, b]) => {
            if (a >= visible - 1 && !(a < visible - 1)) return null
            const from = laid[a]
            const to = laid[b]
            const done = b < visible
            const mx = (from.x + to.x) / 2
            const path =
              Math.abs(from.y - to.y) < 1
                ? `M ${from.x + NODE_W / 2} ${from.y + NODE_H / 2} L ${to.x - NODE_W / 2} ${to.y + NODE_H / 2}`
                : `M ${from.x + NODE_W / 2} ${from.y + NODE_H / 2} C ${mx} ${from.y + NODE_H / 2}, ${mx} ${to.y - 14}, ${to.x} ${to.y}`
            return (
              <path
                key={`${a}-${b}`}
                className={`fv-edge ${done ? 'done' : ''}`}
                d={path}
              />
            )
          })}

          {laid.map(({ row, x, y }, i) => {
            const shown = i < visible
            const cls = [
              'fv-node',
              row.phase === 'gate' ? 'gate' : '',
              shown ? (i === visible - 1 ? 'active' : 'done') : '',
            ].join(' ')
            return (
              <g key={row.step} className={cls} transform={`translate(${x - NODE_W / 2}, ${y})`} opacity={shown ? 1 : 0.18}>
                <rect width={NODE_W} height={NODE_H} />
                <text x={10} y={19}>§{row.node_id}</text>
                <text className="fv-answer" x={10} y={35}>
                  {(row.answer || '—').slice(0, 14)}
                </text>
                <title>{`${row.question}\n${row.reasoning}`}</title>
              </g>
            )
          })}

          {terminal && (
            <g transform={`translate(${width / 2 - 70}, ${height + 44})`}>
              <rect
                width={140}
                height={40}
                rx={8}
                className={`fv-terminal ${terminal.outcome}`}
                strokeOpacity={visible >= rows.length ? 1 : 0.2}
              />
              <text x={70} y={25} textAnchor="middle" style={{ fill: 'var(--fg)', fontSize: 12, fontWeight: 700 }}>
                终点 · {terminal.node_id} · {terminal.outcome}
              </text>
            </g>
          )}
        </svg>
      )}
    </div>
  )
}
