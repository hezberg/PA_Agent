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
import type { StructureLevel } from '../api/types'

export default function ChartPanel() {
  const wrapRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const emaRef = useRef<ISeriesApi<'Line'> | null>(null)
  const priceLines = useRef<ReturnType<ISeriesApi<'Candlestick'>['createPriceLine']>[]>([])
  const fitOnNext = useRef(true)

  const frame = useStore((s) => s.frame)
  const decision = useStore((s) => s.decision)

  useEffect(() => {
    if (!wrapRef.current || chartRef.current) return
    const chart = createChart(wrapRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#0a0e14' },
        textColor: '#8b949e',
        fontFamily: 'var(--font-ui)',
      },
      grid: {
        vertLines: { color: '#1c2128' },
        horzLines: { color: '#1c2128' },
      },
      timeScale: { borderColor: '#30363d', timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: '#30363d' },
      autoSize: true,
    })
    // A 股惯例：红涨绿跌
    const candles = chart.addCandlestickSeries({
      upColor: '#ef4444',
      downColor: '#22c55e',
      borderUpColor: '#ef4444',
      borderDownColor: '#22c55e',
      wickUpColor: '#ef4444',
      wickDownColor: '#22c55e',
    })
    const ema = chart.addLineSeries({
      color: '#fbbf24',
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
      color: b.closed ? undefined : 'rgba(230,237,243,0.45)',
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
    push('entry_price', '#38bdf8', '入场')
    push('take_profit_price', '#22c55e', 'TP1')
    push('take_profit_price_2', '#22c55e', 'TP2')
    push('stop_loss_price', '#ef4444', '止损')

    for (const level of (decision?.support_resistance ?? []) as StructureLevel[]) {
      lines.push({
        price: level.price,
        color: level.kind === 'support' ? 'rgba(34,197,94,0.55)' : 'rgba(239,68,68,0.55)',
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

  return <div ref={wrapRef} className="chart-area" />
}
