import { useEffect, useRef } from 'react'
import {
  createChart,
  IChartApi,
  ISeriesApi,
  LineData,
  ColorType,
  CandlestickData,
  Time,
} from 'lightweight-charts'
import { useStore } from '../store'
import { tfZh, useSymbolName } from '../symbolName'
import { ChevronLeftIcon } from '../icons'
import type { StructureLevel } from '../api/types'

// Rosé Pine 图表配色（红涨绿跌，低对比）
const CHART_BG = '#191724'
const CHART_GRID = '#26233a'
const CHART_TEXT = '#908caa'
const CHART_BORDER = '#322f4d'
const UP = '#eb6f92'
const DOWN = '#79a290'
const EMA = '#f6c177'

export default function ChartPanel({ open, onCollapse }: { open: boolean; onCollapse: () => void }) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const emaRef = useRef<ISeriesApi<'Line'> | null>(null)
  const priceLines = useRef<ReturnType<ISeriesApi<'Candlestick'>['createPriceLine']>[]>([])
  const fitOnNext = useRef(true)

  const frame = useStore((s) => s.frame)
  const decision = useStore((s) => s.decision)
  const name = useSymbolName(frame?.symbol)

  useEffect(() => {
    if (!wrapRef.current || chartRef.current) return
    const chart = createChart(wrapRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: CHART_BG },
        textColor: CHART_TEXT,
        fontFamily: "var(--font-ui)",
      },
      grid: {
        vertLines: { color: CHART_GRID },
        horzLines: { color: CHART_GRID },
      },
      timeScale: { borderColor: CHART_BORDER, timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: CHART_BORDER },
      autoSize: true,
    })
    // A 股惯例：红涨绿跌
    const candles = chart.addCandlestickSeries({
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
    })
    const ema = chart.addLineSeries({
      color: EMA,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    })
    chartRef.current = chart
    candleRef.current = candles
    emaRef.current = ema
    return () => {
      chart.remove()
      chartRef.current = null
      candleRef.current = null
      emaRef.current = null
      priceLines.current = []
    }
  }, [])

  // Feed frame data (oldest → newest) into the chart.
  useEffect(() => {
    const candles = candleRef.current
    const ema = emaRef.current
    if (!candles || !ema || !frame || frame.bars.length === 0) return

    const candleData: CandlestickData<Time>[] = frame.bars.map((b) => ({
      time: (b.ts_open / 1000) as Time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
      color: b.closed ? undefined : 'rgba(224,222,244,0.45)',
    }))
    candles.setData(candleData)

    const emaData: LineData<Time>[] = []
    frame.ema20.forEach((v, i) => {
      if (v !== null && v !== undefined && frame.bars[i]) {
        emaData.push({ time: (frame.bars[i].ts_open / 1000) as Time, value: v })
      }
    })
    ema.setData(emaData)

    if (fitOnNext.current) {
      chartRef.current?.timeScale().fitContent()
      fitOnNext.current = false
    } else {
      chartRef.current?.timeScale().scrollToRealTime()
    }
  }, [frame])

  // Decision overlay: entry / TP / SL + support & resistance price lines.
  useEffect(() => {
    const candles = candleRef.current
    if (!candles) return
    for (const line of priceLines.current) {
      candles.removePriceLine(line)
    }
    priceLines.current = []

    const overlay = decision?.chart_decision ?? {}
    const lines: { price: number; color: string; title: string }[] = []
    const push = (key: string, color: string, title: string) => {
      const raw = overlay[key]
      const v = raw === null || raw === undefined || raw === '' ? NaN : Number(raw)
      if (!Number.isNaN(v) && v > 0) lines.push({ price: v, color, title })
    }
    push('entry_price', '#9ccfd8', '入场')
    push('take_profit_price', '#eb6f92', 'TP1')
    push('take_profit_price_2', '#eb6f92', 'TP2')
    push('stop_loss_price', '#79a290', '止损')

    for (const level of (decision?.support_resistance ?? []) as StructureLevel[]) {
      lines.push({
        price: level.price,
        color: level.kind === 'support' ? 'rgba(121,162,144,0.55)' : 'rgba(235,111,146,0.55)',
        title: level.label,
      })
    }

    for (const line of lines) {
      priceLines.current.push(
        candles.createPriceLine({
          price: line.price,
          color: line.color,
          lineWidth: 1,
          lineStyle: 0,
          axisLabelVisible: true,
          title: line.title,
        }),
      )
    }
  }, [decision])

  // Refit when the user asks (button) — listen for frame resets (new symbol).
  useEffect(() => {
    fitOnNext.current = true
  }, [frame?.symbol, frame?.timeframe])

  // The chart container changes size when toggled; refit once it is visible again.
  useEffect(() => {
    if (!open) return
    const id = requestAnimationFrame(() => chartRef.current?.timeScale().fitContent())
    return () => cancelAnimationFrame(id)
  }, [open])

  return (
    <section className={`chart-area${open ? '' : ' collapsed'}`} aria-label="K线图">
      <div ref={wrapRef} className="chart-canvas" />
      {frame && (
        <span className="chart-badge">
          {name && <>{name} </>}
          {frame.symbol} · {tfZh(frame.timeframe)}
        </span>
      )}
      {open && (
        <button className="chart-collapse" title="收起 K 线图" onClick={onCollapse}>
          <ChevronLeftIcon /> 收起
        </button>
      )}
    </section>
  )
}
