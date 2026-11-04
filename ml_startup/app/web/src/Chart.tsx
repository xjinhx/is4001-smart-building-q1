import { useEffect, useRef, useState } from 'react'
import type { Result } from './types'
import { clock, fmt } from './types'

const BILLING_START = 540       // 09:00, TOU on-peak

// Main chart. Signature detail: the 15-minute ruler, because that interval is what gets billed.
export default function Chart({ r, minute, onSeek, from, to }: {
  r: Result; minute?: number; onSeek?: (m: number) => void; from?: number; to?: number
}) {
  const box = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 800, h: 200 })
  const [hover, setHover] = useState<number | null>(null)
  useEffect(() => {
    if (!box.current) return
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(box.current)
    return () => ro.disconnect()
  }, [])
  const { w, h } = size
  const keep = r.bins.map((b, i) => [b, i]).filter(([b]) => b >= (from ?? 0) && b < (to ?? 1e4))
  const bins = keep.map(([b]) => b)
  const today = keep.map(([, i]) => r.curve_today[i])
  const sched = keep.map(([, i]) => r.curve_schedule[i])
  const L = 44, R = w < 700 ? 116 : 148, T = 20, B = 32
  const t0 = bins[0], t1 = bins[bins.length - 1] + 15
  const yMax = Math.ceil(Math.max(...today, ...sched) / 100 + 0.2) * 100
  const X = (m: number) => L + ((m - t0) / (t1 - t0)) * (w - L - R)
  const Y = (v: number) => T + (1 - v / yMax) * (h - T - B)
  // A bin's value covers its whole interval, so each is plotted at the interval's middle
  const line = (c: number[]) => c.map((v, i) => `${i ? 'L' : 'M'}${X(bins[i] + 7.5).toFixed(1)} ${Y(v).toFixed(1)}`).join(' ')
  const pi = bins.indexOf(r.peak_bin_schedule)
  const yT = Array.from({ length: Math.floor(yMax / 200) + 1 }, (_, i) => i * 200)
  const hi = hover !== null ? bins.findIndex((b) => hover >= b && hover < b + 15) : -1
  const fromEvent = (e: React.MouseEvent) => {
    const rect = box.current!.getBoundingClientRect()
    return Math.round(t0 + ((e.clientX - rect.left - L) / (w - L - R)) * (t1 - t0))
  }
  const showBilling = BILLING_START > t0 && BILLING_START < t1
  const labelEvery = t1 - t0 > 360 ? 120 : 60
  const mi = bins.indexOf(r.morning_peak_bin)
  return (
    <div
      ref={box} className={`chart${onSeek ? ' seek' : ''}`}
      onMouseMove={(e) => { const m = fromEvent(e); setHover(m >= t0 && m < t1 ? m : null) }}
      onMouseLeave={() => setHover(null)}
      onClick={(e) => { const m = fromEvent(e); if (onSeek && m >= t0 && m < t1) onSeek(m) }}
    >
      <svg width={w} height={h} role="img" aria-label={`Building load: billed peak ${fmt(r.peak_today)} kW today, ${fmt(r.peak_schedule)} kW with this schedule`}>
        {pi >= 0 && <rect x={X(r.peak_bin_schedule)} y={T} width={X(r.peak_bin_schedule + 15) - X(r.peak_bin_schedule)} height={h - T - B} fill="var(--heat)" opacity={0.25} />}
        {yT.map((v) => (
          <g key={v}>
            <line x1={L} x2={w - R} y1={Y(v)} y2={Y(v)} stroke="var(--line)" />
            <text x={L - 8} y={Y(v) + 4} textAnchor="end" className="tick">{fmt(v)}</text>
          </g>
        ))}
        {showBilling && (
          <g>
            <line x1={X(BILLING_START)} x2={X(BILLING_START)} y1={T - 12} y2={h - B} stroke="var(--line-2)" strokeDasharray="3 3" />
            <text x={X(BILLING_START) + 6} y={T - 4} className="tick">Billing starts 9:00</text>
            {mi >= 0 && <text x={X(BILLING_START) - 6} y={T - 4} textAnchor="end" className="tick">Morning start {fmt(r.morning_peak)} kW, not billed</text>}
          </g>
        )}
        {bins.map((b) => <line key={b} x1={X(b)} x2={X(b)} y1={h - B} y2={h - B + (b % 60 === 0 ? 8 : 4)} stroke="var(--line-2)" />)}
        {bins.filter((b) => b % labelEvery === 0).map((b) => <text key={b} x={X(b)} y={h - B + 22} textAnchor="middle" className="tick">{clock(b)}</text>)}
        <path d={line(today)} fill="none" stroke="var(--text-3)" strokeWidth={1.5} />
        <path d={line(sched)} fill="none" stroke="var(--accent)" strokeWidth={2} />
        {minute !== undefined && minute >= t0 && minute < t1 && <line x1={X(minute)} x2={X(minute)} y1={T} y2={h - B} stroke="var(--text)" />}
        {pi >= 0 && <circle cx={X(bins[pi] + 7.5)} cy={Y(sched[pi])} r={4} fill="var(--accent)" />}
        <text x={w - R + 12} y={T + 10} className="end-label muted">Today's peak</text>
        <text x={w - R + 12} y={T + 28} className="end-value muted">{fmt(r.peak_today)} kW</text>
        <text x={w - R + 12} y={T + 54} className="end-label">With schedule</text>
        <text x={w - R + 12} y={T + 72} className="end-value">{fmt(r.peak_schedule)} kW</text>
        {hi >= 0 && <line x1={X(bins[hi] + 7.5)} x2={X(bins[hi] + 7.5)} y1={T} y2={h - B} stroke="var(--line-2)" />}
      </svg>
      {hi >= 0 && (
        <div className="tooltip" style={{ left: Math.min(X(bins[hi] + 7.5) + 12, w - R - 170), top: T }}>
          <div className="mono">{clock(bins[hi])} to {clock(bins[hi] + 15)}</div>
          <div>Today <b>{fmt(today[hi])} kW</b></div>
          <div>With schedule <b>{fmt(sched[hi])} kW</b></div>
        </div>
      )}
    </div>
  )
}
