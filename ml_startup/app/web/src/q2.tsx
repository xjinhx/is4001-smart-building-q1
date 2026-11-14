// Q2 AC alerts: the Alerts, Alert list and Alert workload pages. Real 2019 readings for Floors 3 to 7,
// with the Q2 team's frozen alert method (see ml_startup/q2_alerts/build_alerts.py). Nothing here is simulated.
import { Component, lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { BellRing, ChevronLeft, ChevronRight, Download, ExternalLink, Pause, Play, SkipForward, X } from 'lucide-react'
import type { Init } from './types'
import { clock, fmt } from './types'
import { LABEL_AT, LIFT_CORE, ZONE_SHAPES, type Pt } from './plan'

const Building = lazy(() => import('./Building'))

export type Policy = 'immediate' | 'continuous20' | '20of30'
export const POLICIES: Policy[] = ['immediate', 'continuous20', '20of30']
export const POLICY_LABEL: Record<Policy, string> = { immediate: 'Immediate', continuous20: 'Continuous20', '20of30': '20of30' }
const POLICY_NOTE: Record<Policy, string> = {
  immediate: 'First abnormal minute',
  continuous20: '20 consecutive abnormal minutes',
  '20of30': 'At least 20 of the last 30 minutes abnormal (main policy)',
}
// review_group names are the Q2 team's own. Each is defined by which policies alert, so the text below only
// restates that rule in words. GROUP_SHORT is the brief form used in the workload note.
const GROUP_TEXT: Record<string, string> = {
  immediate_only: 'Only Immediate alerts. The readings were abnormal, but never for 20 of any 30 minutes, so Continuous20 and 20of30 stay quiet.',
  interruption_tolerance_adds_case: "20of30 alerts but Continuous20 doesn't. The readings were abnormal for at least 20 of 30 minutes, but with breaks, so never 20 minutes in a row.",
  shorter_duration_adds_case: 'Continuous20 and 20of30 alert. The readings were abnormal for at least 20 minutes in a row, but not 30.',
  shared_sustained_case: 'Every policy alerts. The readings were abnormal for at least 30 minutes in a row.',
}
const GROUP_SHORT: Record<string, string> = {
  immediate_only: 'only Immediate alerts',
  interruption_tolerance_adds_case: '20 of 30 minutes abnormal, with breaks',
  shorter_duration_adds_case: '20 to 29 minutes abnormal in a row',
  shared_sustained_case: '30 or more minutes abnormal in a row',
}
// Thai national public holidays, May to December 2019, from the API (q2_alerts/build_alerts.py keeps the list).
// A case that starts on one is held back as a suspected false alarm instead of being flagged.
export let HOLIDAYS: Record<string, string> = {}
const PERIOD_LABEL: Record<string, string> = {
  all: 'May to December', development: 'May to June (development)', validation: 'July to September (validation)',
  evaluation: 'October to December (evaluation)',
}

export type Q2Case = {
  id: number; floor: number; zone: number; unit: string; direction: 'high' | 'low'; period: string
  start: string; end: string; span: number; abnormal: number; longest_run: number; mean_observed: number; mean_expected: number
  review_group: string; review: { review_id: string; rating: string; reason: string } | null
  held: { reason: string; holiday: string; note: string } | null
  alerts: Record<Policy, string | null>; delay: Record<Policy, number | null>
}
type WorkloadRow = {
  floor: number | 'all'; period: string; policy: Policy | 'continuous30'; label: string; cases: number; unit_weeks: number
  calendar_weeks: number; held: number; cases_per_monitored_week: number | null; alerts_per_week: number; missed: number
  missed_per_monitored_week: number | null; missed_pct: number | null; average_delay: number | null
  total_delay_per_monitored_week: number | null; missed_by_group: Record<string, number>
  estimated_missed_worth_investigating: number; estimated_per_week: number
}
export type Q2Init = {
  year: number; start: string; end: string; periods: { id: string; start: string; end: string }[]
  units: { id: number; floor: number; zone: number; unit: string }[]
  settings: { window_days: number; sigma: number; min_deviation_kw: number; gap_minutes: number }; note: string
  days: { date: string; label: string; weekend: boolean; counts: Record<Policy, number>; held: Record<Policy, number> }[]
  holidays: Record<string, string>
  workload: WorkloadRow[]
  shares: Record<string, { plots: number; investigate: number; share: number | null }>
  reviewer: { policy: Policy; label: string; plots: number; investigate: number; monitor: number; investigate_pct: number | null }[]
}
type Row = {
  time: string; in_case: boolean; observed: number | null; expected: number | null; threshold: number | null
  abnormal: boolean; abnormal_in_last_30: number; consecutive_abnormal: number; alerts: string[]
}
type Detail = { case: Q2Case; rows: Row[]; pad: number }
export type Focus = { date: string; minute: number; caseId?: number }

// Timestamps arrive as 'YYYY-MM-DD HH:MM:SS'. Minutes are counted from midnight of the date passed in.
const dayOf = (ts: string) => ts.slice(0, 10)
const minOfDay = (ts: string) => +ts.slice(11, 13) * 60 + +ts.slice(14, 16)
const dayDiff = (a: string, b: string) => Math.round((Date.parse(`${a}T00:00:00Z`) - Date.parse(`${b}T00:00:00Z`)) / 86400000)
const minFrom = (ts: string, date: string) => dayDiff(dayOf(ts), date) * 1440 + minOfDay(ts)
const longDate = (d: string) => new Date(`${d}T00:00:00Z`).toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' })
const shortStamp = (ts: string) => `${new Date(`${dayOf(ts)}T00:00:00Z`).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', timeZone: 'UTC' })} ${ts.slice(11, 16)}`
const where = (c: Q2Case) => `F${c.floor} ${c.unit}`
const csvCell = (v: unknown) => { const s = v === null || v === undefined ? '' : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s }

// Loaded once and shared by the three pages
let store: Promise<{ init: Q2Init; cases: Q2Case[] }> | null = null
function loadQ2() {
  if (!store) {
    store = Promise.all([fetch('/api/q2/init'), fetch('/api/q2/cases')]).then(async ([a, b]) => {
      if (!a.ok || !b.ok) throw new Error(`The backend returned ${a.ok ? b.status : a.status}`)
      const init: Q2Init = await a.json()
      HOLIDAYS = init.holidays
      return { init, cases: await b.json() }
    })
    store.catch(() => { store = null })
  }
  return store
}
function useQ2() {
  const [state, setState] = useState<{ init: Q2Init; cases: Q2Case[] } | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { loadQ2().then(setState).catch((e) => setError(e.message)) }, [])
  return { q: state, error }
}

class Fallback extends Component<{ onFail: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch() { this.props.onFail() }
  render() { return this.state.failed ? null : this.props.children }
}

function PolicySeg({ policy, onChange, small }: { policy: Policy; onChange: (p: Policy) => void; small?: boolean }) {
  return (
    <div className={`seg${small ? ' small' : ''}`} role="group" aria-label="Alert policy">
      {POLICIES.map((p) => <button key={p} className={policy === p ? 'on' : ''} onClick={() => onChange(p)} title={POLICY_NOTE[p]}>{POLICY_LABEL[p]}</button>)}
    </div>
  )
}

// ---------- Alert detail: the minute-by-minute view for the facilities manager ----------

function CaseChart({ d }: { d: Detail }) {
  const rows = d.rows
  const W = 600, H = 200, L = 40, R = 12, T = 12, B = 26
  const vals = rows.flatMap((r) => [r.observed, r.expected !== null && r.threshold !== null ? r.expected + r.threshold : null]).filter((v): v is number => v !== null)
  const yMax = Math.max(1, Math.ceil(Math.max(...vals, 1) * 1.1))
  const X = (i: number) => L + (i / Math.max(1, rows.length - 1)) * (W - L - R)
  const Y = (v: number) => T + (1 - v / yMax) * (H - T - B)
  const path = (get: (r: Row) => number | null) => {
    let out = '', pen = false
    rows.forEach((r, i) => { const v = get(r); if (v === null) { pen = false; return } out += `${pen ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`; pen = true })
    return out
  }
  const band = rows.map((r, i) => (r.expected !== null && r.threshold !== null ? [i, Math.min(yMax, r.expected + r.threshold), Math.max(0, r.expected - r.threshold)] : null)).filter((x): x is number[] => x !== null)
  const bandPath = band.length ? `M${band.map(([i, hi]) => `${X(i).toFixed(1)} ${Y(hi).toFixed(1)}`).join(' L')} L${[...band].reverse().map(([i, , lo]) => `${X(i).toFixed(1)} ${Y(lo).toFixed(1)}`).join(' L')} Z` : ''
  const first = rows.findIndex((r) => r.in_case), last = rows.length - 1 - [...rows].reverse().findIndex((r) => r.in_case)
  const ticks = rows.map((r, i) => [r, i] as const).filter(([r]) => minOfDay(r.time) % 30 === 0)
  return (
    <svg className="q2-case-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Observed against expected power for this case">
      {first >= 0 && <rect x={X(first)} y={T} width={Math.max(1, X(last) - X(first))} height={H - T - B} fill="rgba(229,72,77,.08)" />}
      {[0, yMax / 2, yMax].map((v) => (
        <g key={v}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} stroke="rgba(237,237,237,.08)" /><text x={L - 6} y={Y(v) + 4} textAnchor="end" className="tick">{fmt(v)}</text></g>
      ))}
      <path d={bandPath} fill="rgba(161,161,166,.18)" />
      <path d={path((r) => r.expected)} fill="none" stroke="#85858b" strokeWidth={1.2} strokeDasharray="4 3" />
      <path d={path((r) => r.observed)} fill="none" stroke="#f2ad45" strokeWidth={1.6} />
      {rows.map((r, i) => r.abnormal && r.observed !== null ? <circle key={i} cx={X(i)} cy={Y(r.observed)} r={1.6} fill="#e5484d" /> : null)}
      {rows.map((r, i) => [r, i] as const).filter(([r]) => r.alerts.length).map(([r, i], k) => (
        <g key={`a${i}`}><line x1={X(i)} x2={X(i)} y1={T} y2={H - B} stroke="#e5484d" /><text x={X(i) + 4} y={T + 10 + 14 * k} className="tick q2-alert-tick">{r.alerts.join(', ')}</text></g>
      ))}
      {ticks.map(([r, i]) => <text key={r.time} x={X(i)} y={H - 8} textAnchor="middle" className="tick">{r.time.slice(11, 16)}</text>)}
    </svg>
  )
}

export function AlertDetail({ id, onClose, onReplay }: { id: number; onClose: () => void; onReplay?: (f: Focus) => void }) {
  const [d, setD] = useState<Detail | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    setD(null)
    fetch(`/api/q2/case/${id}`).then((r) => { if (!r.ok) throw new Error(`The backend returned ${r.status}`); return r.json() }).then(setD).catch((e) => setError(e.message))
  }, [id])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [onClose])
  const c = d?.case
  return (
    <div className="q2-scrim" onClick={onClose}>
      <aside className="q2-drawer" role="dialog" aria-label="Alert details" onClick={(e) => e.stopPropagation()}>
        <header className="q2-drawer-head">
          <div>
            <h3>{c ? `${where(c)}, ${c.direction === 'high' ? 'above' : 'below'} expected${c.held ? ' (held back)' : ''}` : 'Alert details'}</h3>
            {c && <div className="muted">Floor {c.floor}, zone {c.zone}, {longDate(dayOf(c.start))}</div>}
          </div>
          <button aria-label="Close alert details" onClick={onClose}><X size={16} strokeWidth={1.5} /></button>
        </header>
        {error && <p className="warn q2-pad">{error}</p>}
        {!c && !error && <p className="muted q2-pad">Loading the minutes for this alert</p>}
        {c && d && (
          <div className="q2-drawer-body">
            {c.held && <p className="q2-held-note"><b>Not flagged: suspected false alarm.</b> {c.held.note}. The policy times below are when it would have alerted.</p>}
            <dl className="q2-facts">
              <div><dt>Case</dt><dd className="mono">{c.start.slice(11, 16)} to {c.end.slice(11, 16)}{dayOf(c.end) !== dayOf(c.start) ? ' next day' : ''}, {c.span} min</dd></div>
              <div><dt>Abnormal minutes</dt><dd className="mono">{c.abnormal} of {c.span}, longest run {c.longest_run}</dd></div>
              <div><dt>Average power</dt><dd className="mono">{fmt(c.mean_observed, 1)} kW against {fmt(c.mean_expected, 1)} kW expected</dd></div>
              {POLICIES.map((p) => (
                <div key={p}><dt>{POLICY_LABEL[p]}</dt><dd className="mono">{c.alerts[p] ? `${c.held ? 'would alert' : 'alerts'} ${c.alerts[p]!.slice(11, 16)}, ${c.delay[p]} min after the case starts` : 'no alert'}</dd></div>
              ))}
              <div className="q2-wide"><dt>Abnormal pattern</dt><dd className="q2-text">{GROUP_TEXT[c.review_group]}<span className="q2-code">review_group: {c.review_group}</span></dd></div>
              {c.review && <div><dt>Reviewed ({c.review.review_id})</dt><dd><b className={c.review.rating === 'investigate' ? 'q2-red' : ''}>{c.review.rating}</b>: {c.review.reason}</dd></div>}
            </dl>
            <CaseChart d={d} />
            <div className="q2-legend muted">
              <span><i className="q2-key obs" />Observed</span><span><i className="q2-key exp" />Expected</span><span><i className="q2-key band" />Expected ± threshold</span><span><i className="q2-key dot" />Abnormal minute</span><span><i className="q2-key case" />Case</span>
            </div>
            <div className="q2-actions">
              <a className="tool" href={`/api/q2/case/${c.id}/csv`} download><Download size={16} strokeWidth={1.5} />Download these minutes (CSV)</a>
              {onReplay && <button className="tool" onClick={() => onReplay({ date: dayOf(c.start), minute: Math.max(0, minOfDay(c.start) - 10), caseId: c.id })}><ExternalLink size={16} strokeWidth={1.5} />Show in the replay</button>}
            </div>
            <div className="q2-minutes">
              <table>
                <thead><tr>
                  <th>Time</th><th className="n">Observed kW</th><th className="n">Expected kW</th><th className="n">Allowed range kW</th>
                  <th>Abnormal</th><th className="n">Abnormal in last 30</th><th className="n">In a row</th><th>Alert</th>
                </tr></thead>
                <tbody>
                  {d.rows.map((r) => (
                    <tr key={r.time} className={`${r.in_case ? 'in' : ''}${r.alerts.length ? ' fired' : ''}`}>
                      <td className="mono">{r.time.slice(11, 16)}</td>
                      <td className="n mono">{r.observed === null ? 'missing' : fmt(r.observed, 2)}</td>
                      <td className="n mono">{r.expected === null ? '' : fmt(r.expected, 2)}</td>
                      <td className="n mono">{r.expected === null || r.threshold === null ? 'no baseline' : `${fmt(Math.max(0, r.expected - r.threshold), 2)} to ${fmt(r.expected + r.threshold, 2)}`}</td>
                      <td>{r.abnormal ? <span className="q2-red">{c.direction === 'high' ? 'above' : 'below'}</span> : ''}</td>
                      <td className="n mono">{r.abnormal_in_last_30 || ''}</td>
                      <td className="n mono">{r.consecutive_abnormal || ''}</td>
                      <td>{r.alerts.join(', ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="hint">Shows {d.pad} minutes either side of the case. An alert is an excursion from the 28-day statistical baseline, not a confirmed fault. Check schedules, holidays and zone temperature before acting.</p>
          </div>
        )}
      </aside>
    </div>
  )
}

// ---------- Alerts: replay a 2019 day with alert pop-ups ----------

function Plans({ zones, levels, alerts, onSelect }: { zones: Init['zones']; levels: number[]; alerts: boolean[]; onSelect: (j: number) => void }) {
  const W = 144, H = 100
  const points = (pts: Pt[]) => pts.map(([u, v]) => `${u * W},${v * H}`).join(' ')
  return (
    <div className="plans">
      {[7, 6, 5, 4, 3].map((f) => (
        <figure key={f} className="plan">
          <figcaption className="mono">Floor {f}</figcaption>
          <svg viewBox={`-1 -1 ${W + 2} ${H + 2}`} role="group" aria-label={`Floor ${f} plan`}>
            {[1, 2, 3, 4, 5].map((z) => {
              const j = zones.findIndex((v) => v.floor === f && v.zone === z)
              const lv = j >= 0 ? levels[j] ?? 0 : 0
              const on = j >= 0 && alerts[j]
              const [lx, ly] = LABEL_AT[z]
              return (
                <g key={z} className={j >= 0 ? 'plan-zone' : ''} onClick={j >= 0 ? () => onSelect(j) : undefined}>
                  <polygon points={points(ZONE_SHAPES[z])}
                    fill={on ? '#e5484d' : j >= 0 ? `color-mix(in srgb, #f2ad45 ${Math.round(lv * 100)}%, #2a2a2c)` : '#1d1d1f'} stroke="#141415" />
                  <text x={lx * W} y={ly * H} textAnchor="middle" dominantBaseline="middle" fill={on || lv > 0.5 ? '#141415' : '#a1a1a6'}>{j >= 0 ? `Z${z}` : 'Stairs'}</text>
                </g>
              )
            })}
            <polygon points={points(LIFT_CORE)} fill="#1d1d1f" stroke="#141415" />
          </svg>
        </figure>
      ))}
    </div>
  )
}

// One row per policy: each case is a bar from its start to its end, with the alert minute marked
function Timeline({ cases, date, minute, policy, onSeek, onOpen }: {
  cases: Q2Case[]; date: string; minute: number; policy: Policy; onSeek: (m: number) => void; onOpen: (id: number) => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(800)
  useEffect(() => {
    if (!box.current) return
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width))
    ro.observe(box.current)
    return () => ro.disconnect()
  }, [])
  const L = w < 600 ? 112 : 128, R = 24, T = 20, rowH = 40, B = 28
  const H = T + rowH * POLICIES.length + B
  const X = (m: number) => L + (Math.min(1440, Math.max(0, m)) / 1440) * (w - L - R)
  const seek = (e: React.MouseEvent) => {
    const r = box.current!.getBoundingClientRect()
    const m = Math.round(((e.clientX - r.left - L) / (w - L - R)) * 1440)
    if (m >= 0 && m < 1440) onSeek(m)
  }
  return (
    <div ref={box} className="chart seek" onClick={seek}>
      <svg width={w} height={H} role="img" aria-label={`Alerts on ${longDate(date)} by policy`}>
        {Array.from({ length: w < 600 ? 7 : 13 }, (_, i) => i * (w < 600 ? 240 : 120)).map((m) => (
          <g key={m}><line x1={X(m)} x2={X(m)} y1={T - 4} y2={H - B} stroke="rgba(237,237,237,.06)" /><text x={X(m)} y={H - 8} textAnchor="middle" className="tick">{clock(m === 1440 ? 0 : m)}</text></g>
        ))}
        {POLICIES.map((p, k) => {
          const y = T + k * rowH
          const list = cases.filter((c) => c.alerts[p] && dayOf(c.alerts[p]!) === date)
          return (
            <g key={p}>
              <text x={12} y={y + rowH / 2 + 4} className={`q2-row-label${p === policy ? ' on' : ''}`}>{POLICY_LABEL[p]}</text>
              {w >= 600 && <text x={L - 12} y={y + rowH / 2 + 4} textAnchor="end" className="tick">{list.length}</text>}
              <line x1={L} x2={w - R} y1={y + rowH / 2} y2={y + rowH / 2} stroke="rgba(237,237,237,.08)" />
              {list.map((c) => {
                const a = minFrom(c.alerts[p]!, date), s = minFrom(c.start, date), e = minFrom(c.end, date)
                return (
                  <g key={c.id} className="q2-mark" onClick={(ev) => { ev.stopPropagation(); onOpen(c.id) }}>
                    <title>{`${where(c)} ${c.direction}, alert ${c.alerts[p]!.slice(11, 16)}`}</title>
                    <rect x={X(s)} y={y + rowH / 2 - 5} width={Math.max(2, X(e) - X(s))} height={10} rx={2} fill={p === policy ? 'rgba(229,72,77,.35)' : 'rgba(161,161,166,.22)'} />
                    <circle cx={X(a)} cy={y + rowH / 2} r={p === policy ? 4.5 : 3.5} fill={a <= minute ? (p === policy ? '#e5484d' : '#a1a1a6') : '#141415'} stroke={p === policy ? '#e5484d' : '#a1a1a6'} strokeWidth={1.5} />
                  </g>
                )
              })}
            </g>
          )
        })}
        <line x1={X(minute)} x2={X(minute)} y1={T - 8} y2={H - B} stroke="#ededed" />
      </svg>
    </div>
  )
}

export function AlertsPage({ zones, focus, onFocus }: { zones: Init['zones']; focus: Focus | null; onFocus: (f: Focus | null) => void }) {
  const { q, error } = useQ2()
  const [policy, setPolicy] = useState<Policy>('20of30')
  const [date, setDate] = useState('')
  const [minute, setMinute] = useState(480)
  const [playing, setPlaying] = useState(false)
  const [view, setView] = useState<'3d' | '2d'>('3d')
  const [day, setDay] = useState<{ date: string; units: (number | null)[][] } | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [hovered, setHovered] = useState<number | null>(null)

  // Opens on the busiest non-holiday evaluation day for 20of30, or wherever the alert list sent us
  useEffect(() => {
    if (!q || date) return
    if (focus) { setDate(focus.date); setMinute(focus.minute); if (focus.caseId !== undefined) setOpen(focus.caseId); onFocus(null); return }
    const evalDays = q.init.days.filter((d) => d.date >= '2019-10-01' && !HOLIDAYS[d.date])
    const best = evalDays.reduce((a, b) => (b.counts['20of30'] > a.counts['20of30'] ? b : a), evalDays[0])
    setDate(best.date)
  }, [q, focus, date, onFocus])
  useEffect(() => {
    if (!q || !focus) return
    setDate(focus.date); setMinute(focus.minute); setPlaying(false)
    if (focus.caseId !== undefined) setOpen(focus.caseId)
    onFocus(null)
  }, [q, focus, onFocus])
  useEffect(() => {
    if (!date) return
    let live = true
    fetch(`/api/q2/day/${date}`).then((r) => r.json()).then((d) => { if (live) setDay(d) })
    return () => { live = false }
  }, [date])
  useEffect(() => {
    if (!playing) return
    if (minute >= 1439) { setPlaying(false); return }
    const t = setTimeout(() => setMinute((m) => m + 1), 25)
    return () => clearTimeout(t)
  }, [playing, minute])

  const unitZone = useMemo(() => q ? q.init.units.map((u) => zones.findIndex((z) => z.floor === u.floor && z.zone === u.zone)) : [], [q, zones])
  const onDay = useMemo(() => q && date ? q.cases.filter((c) => POLICIES.some((p) => c.alerts[p] && dayOf(c.alerts[p]!) === date)) : [], [q, date])
  const todays = useMemo(() => onDay.filter((c) => !c.held), [onDay])
  const heldToday = useMemo(() => onDay.filter((c) => c.held && c.alerts[policy] && dayOf(c.alerts[policy]!) === date)
    .sort((a, b) => a.alerts[policy]!.localeCompare(b.alerts[policy]!)), [onDay, policy, date])
  const fired = useMemo(() => todays.filter((c) => c.alerts[policy] && dayOf(c.alerts[policy]!) === date)
    .sort((a, b) => a.alerts[policy]!.localeCompare(b.alerts[policy]!)), [todays, policy, date])
  if (error) return <div className="splash">{error}</div>
  if (!q || !date) return <div className="splash">Loading the 2019 alerts</div>

  const dayInfo = q.init.days.find((d) => d.date === date)!
  const di = q.init.days.indexOf(dayInfo)
  const levels = zones.map(() => 0)
  const kwZone = zones.map(() => 0)
  if (day && day.date === date) {
    day.units.forEach((u, k) => { const j = unitZone[k]; if (j >= 0) kwZone[j] += u[minute] ?? 0 })
    kwZone.forEach((v, j) => { levels[j] = Math.min(1, v / Math.max(zones[j].rated_kW * 0.75, 1)) })
  }
  const totalKW = kwZone.reduce((a, b) => a + b, 0)
  // A zone is red from the alert minute until its case ends
  const alertZones = zones.map(() => false)
  const openNow = fired.filter((c) => minFrom(c.alerts[policy]!, date) <= minute && minute < minFrom(c.end, date))
  openNow.forEach((c) => { const j = zones.findIndex((z) => z.floor === c.floor && z.zone === c.zone); if (j >= 0) alertZones[j] = true })
  const sofar = fired.filter((c) => minFrom(c.alerts[policy]!, date) <= minute)
  const latest = sofar.length ? sofar[sofar.length - 1] : null
  const fresh = latest && minute - minFrom(latest.alerts[policy]!, date) < 30 ? latest : null
  const next = fired.find((c) => minFrom(c.alerts[policy]!, date) > minute)
  const nextDay = q.init.days.slice(di + 1).find((d) => d.counts[policy] > 0)
  const goNext = () => {
    setPlaying(false)
    if (next) setMinute(minFrom(next.alerts[policy]!, date))
    else if (nextDay) { setDate(nextDay.date); setMinute(0) }
  }
  const az = (hovered ?? selected) !== null ? zones[(hovered ?? selected)!] : null
  const azUnits = az ? q.init.units.filter((u) => u.floor === az.floor && u.zone === az.zone) : []

  return (
    <div className="page replay q2-alerts">
      <div className="stage">
        {view === '3d' ? (
          <Fallback onFail={() => setView('2d')}>
            <Suspense fallback={<div className="stage-wait">Drawing the building</div>}>
              <Building zones={zones} levels={levels} alerts={alertZones} selected={selected} hovered={hovered} daylight={1} sun={0.8} humidity={60} cloud={30}
                onHover={setHovered} onSelect={(j) => setSelected((s) => (s === j ? null : j))} onDeselect={() => setSelected(null)} />
            </Suspense>
          </Fallback>
        ) : <Plans zones={zones} levels={levels} alerts={alertZones} onSelect={(j) => setSelected((s) => (s === j ? null : j))} />}
        <div className="readout">
          <div className="mono readout-clock">{longDate(date)}, {clock(minute)}</div>
          {HOLIDAYS[date] && <div className="readout-note q2-holiday">Public holiday: {HOLIDAYS[date]}. Cases starting today are held back as suspected false alarms.</div>}
          <div className="readout-kw">{fmt(totalKW)} kW</div>
          <div className="readout-note">AC load on Floors 3 to 7, as recorded</div>
          <div className="readout-peak">{POLICY_LABEL[policy]} alerts so far today <b>{sofar.length}</b> of {fired.length}</div>
          <div className="readout-note mono">Today: {POLICIES.map((p) => `${POLICY_LABEL[p]} ${dayInfo.counts[p]}`).join(', ')}</div>
          {dayInfo.held[policy] > 0 && <div className="readout-note">{dayInfo.held[policy]} {POLICY_LABEL[policy]} held back as suspected false alarms</div>}
        </div>
        {fresh && (
          <button className="q2-toast" onClick={() => setOpen(fresh.id)}>
            <BellRing size={16} strokeWidth={1.5} />
            <span><b>{POLICY_LABEL[policy]} alert {fresh.alerts[policy]!.slice(11, 16)}</b>: {where(fresh)}, power {fresh.direction === 'high' ? 'above' : 'below'} expected</span>
            <span className="q2-toast-cta">View the minutes</span>
          </button>
        )}
        <div className="stage-tools">
          <PolicySeg policy={policy} onChange={setPolicy} small />
          <div className="seg">
            <button className={view === '3d' ? 'on' : ''} onClick={() => setView('3d')}>3D</button>
            <button className={view === '2d' ? 'on' : ''} onClick={() => setView('2d')}>2D</button>
          </div>
        </div>
        <div className="log-panel q2-list-panel">
          <div className="log-head">
            <span>{POLICY_LABEL[policy]} alerts today ({fired.length})</span>
          </div>
          {fired.length ? (
            <ol>
              {fired.map((c) => (
                <li key={c.id}><button className={minFrom(c.alerts[policy]!, date) <= minute ? 'done' : ''} onClick={() => setOpen(c.id)}>
                  <span className="mono">{c.alerts[policy]!.slice(11, 16)}</span><span>{where(c)}</span><span className={`mono${c.direction === 'high' ? ' q2-red' : ''}`}>{c.direction}</span>
                </button></li>
              ))}
            </ol>
          ) : <p className="hint q2-pad">No {POLICY_LABEL[policy]} alerts on this day</p>}
          {heldToday.length > 0 && (
            <>
              <div className="log-head q2-held-head"><span>Suspected false alarms ({heldToday.length})</span></div>
              <p className="hint q2-pad">Not flagged: {heldToday[0].held!.holiday}, a public holiday</p>
              <ol className="q2-held-list">
                {heldToday.map((c) => (
                  <li key={c.id}><button onClick={() => setOpen(c.id)}>
                    <span className="mono">{c.alerts[policy]!.slice(11, 16)}</span><span>{where(c)}</span><span className="mono">{c.direction}</span>
                  </button></li>
                ))}
              </ol>
            </>
          )}
        </div>
        {az && (
          <div className="zone-card q2-zone-card">
            <div className="zone-head"><span>Floor {az.floor}, zone {az.zone}</span>{selected !== null && <button aria-label="Close zone details" onClick={() => { setSelected(null); setHovered(null) }}><X size={16} strokeWidth={1.5} /></button>}</div>
            {azUnits.map((u) => <div key={u.id} className="muted mono">{u.unit}: {day && day.date === date ? `${fmt(day.units[u.id][minute] ?? 0, 1)} kW` : ''}</div>)}
          </div>
        )}
        <div className="player">
          <button className="icon" onClick={() => { if (!playing && minute >= 1439) setMinute(0); setPlaying(!playing) }} aria-label={playing ? 'Pause' : 'Play'}>
            {playing ? <Pause size={16} strokeWidth={1.5} /> : <Play size={16} strokeWidth={1.5} />}
          </button>
          <input aria-label="Time of day" type="range" min={0} max={1439} value={minute} onChange={(e) => { setMinute(+e.target.value); setPlaying(false) }} />
          <span className="mono muted times">0:00 to 24:00</span>
          <button className="tool" onClick={goNext} disabled={!next && !nextDay}><SkipForward size={16} strokeWidth={1.5} />Next alert</button>
          <button className="icon" aria-label="Previous day" disabled={di === 0} onClick={() => { setDate(q.init.days[di - 1].date); setPlaying(false) }}><ChevronLeft size={16} strokeWidth={1.5} /></button>
          <select aria-label="Day" value={date} onChange={(e) => { setDate(e.target.value); setPlaying(false) }}>
            {q.init.days.map((d) => <option key={d.date} value={d.date}>{d.label}{HOLIDAYS[d.date] ? ' (holiday)' : ''}, {d.counts[policy]} {POLICY_LABEL[policy]}{d.held[policy] ? `, ${d.held[policy]} held` : ''}</option>)}
          </select>
          <button className="icon" aria-label="Next day" disabled={di === q.init.days.length - 1} onClick={() => { setDate(q.init.days[di + 1].date); setPlaying(false) }}><ChevronRight size={16} strokeWidth={1.5} /></button>
        </div>
      </div>
      <div className="chart-wrap q2-timeline">
        <Timeline cases={todays} date={date} minute={minute} policy={policy} onSeek={(m) => { setMinute(m); setPlaying(false) }} onOpen={setOpen} />
      </div>
      {open !== null && <AlertDetail id={open} onClose={() => setOpen(null)} />}
    </div>
  )
}

// ---------- Alert list: every alert, compiled per policy ----------

type SortKey = 'alert' | 'floor' | 'unit' | 'direction' | 'delay' | 'abnormal' | 'longest_run' | 'span'
const PAGE = 100

export function AlertListPage({ onReplay }: { onReplay: (f: Focus) => void }) {
  const { q, error } = useQ2()
  const [policy, setPolicy] = useState<Policy>('20of30')
  const [status, setStatus] = useState<'flagged' | 'held'>('flagged')
  const [floor, setFloor] = useState<'all' | number>('all')
  const [period, setPeriod] = useState('all')
  const [direction, setDirection] = useState<'all' | 'high' | 'low'>('all')
  const [unit, setUnit] = useState('all')
  const [sort, setSort] = useState<{ key: SortKey; up: boolean }>({ key: 'alert', up: true })
  const [page, setPage] = useState(0)
  const [open, setOpen] = useState<number | null>(null)
  useEffect(() => setPage(0), [policy, status, floor, period, direction, unit, sort])

  const rows = useMemo(() => {
    if (!q) return []
    const list = q.cases.filter((c) => c.alerts[policy] && !!c.held === (status === 'held') && (floor === 'all' || c.floor === floor) && (period === 'all' || c.period === period)
      && (direction === 'all' || c.direction === direction) && (unit === 'all' || c.unit === unit))
    const val = (c: Q2Case): string | number => sort.key === 'alert' ? c.alerts[policy]! : sort.key === 'delay' ? c.delay[policy] ?? 0
      : sort.key === 'floor' ? c.floor * 10 + c.zone : sort.key === 'unit' ? `${c.floor}${c.unit}` : c[sort.key]
    return list.sort((a, b) => { const x = val(a), y = val(b); return (x < y ? -1 : x > y ? 1 : 0) * (sort.up ? 1 : -1) })
  }, [q, policy, status, floor, period, direction, unit, sort])
  if (error) return <div className="splash">{error}</div>
  if (!q) return <div className="splash">Loading the 2019 alerts</div>

  const counts = POLICIES.map((p) => q.cases.filter((c) => c.alerts[p] && !!c.held === (status === 'held') && (floor === 'all' || c.floor === floor) && (period === 'all' || c.period === period)
    && (direction === 'all' || c.direction === direction) && (unit === 'all' || c.unit === unit)).length)
  const units = [...new Set(q.init.units.filter((u) => floor === 'all' || u.floor === floor).map((u) => u.unit))].sort()
  const shown = rows.slice(page * PAGE, (page + 1) * PAGE)
  const head = (key: SortKey, label: string, n?: boolean) => (
    <th className={n ? 'n' : ''} aria-sort={sort.key === key ? (sort.up ? 'ascending' : 'descending') : 'none'}>
      <button className="q2-sort" onClick={() => setSort((s) => ({ key, up: s.key === key ? !s.up : true }))}>{label}{sort.key === key ? (sort.up ? ' ↑' : ' ↓') : ''}</button>
    </th>
  )
  const exportCsv = () => {
    const cols = ['policy', 'alert_time', 'floor', 'zone', 'unit', 'direction', 'case_start', 'case_end', 'delay_min', 'abnormal_minutes', 'longest_abnormal_run', 'case_minutes',
      'mean_observed_kw', 'mean_expected_kw', ...POLICIES.map((p) => `${p}_alert`), 'review_group', 'review_id', 'review_rating', 'status', 'held_reason']
    const lines = rows.map((c) => [POLICY_LABEL[policy], c.alerts[policy], c.floor, c.zone, c.unit, c.direction, c.start, c.end, c.delay[policy], c.abnormal, c.longest_run, c.span,
      c.mean_observed, c.mean_expected, ...POLICIES.map((p) => c.alerts[p] ?? ''), c.review_group, c.review?.review_id ?? '', c.review?.rating ?? '', c.held ? 'suspected false alarm (not flagged)' : 'flagged', c.held ? `${c.held.reason}: ${c.held.holiday}` : ''].map(csvCell).join(','))
    const blob = new Blob([[cols.join(','), ...lines].join('\n')], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `ac_alerts_${status === 'held' ? 'suspected_false_alarms_' : ''}${policy}_${floor === 'all' ? 'floors3-7' : `floor${floor}`}_${period}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }
  return (
    <div className="page doc">
      <header className="doc-head">
        <h2>AC alert list</h2>
        <p>Every alert raised in {q.init.year} on Floors 3 to 7, compiled per policy. Pick a policy to see its full list. Click a row for the minute-by-minute readings. Cases that start on a Thai public holiday are not flagged; they are listed under suspected false alarms.</p>
      </header>
      <div className="q2-filters">
        <div className="seg" role="group" aria-label="Flagged or held back">
          <button className={status === 'flagged' ? 'on' : ''} onClick={() => setStatus('flagged')}>Flagged alerts</button>
          <button className={status === 'held' ? 'on' : ''} onClick={() => setStatus('held')}>Suspected false alarms</button>
        </div>
        <div className="seg" role="group" aria-label="Alert policy">
          {POLICIES.map((p, k) => <button key={p} className={policy === p ? 'on' : ''} onClick={() => setPolicy(p)} title={POLICY_NOTE[p]}>{POLICY_LABEL[p]} <span className="mono q2-count">{fmt(counts[k])}</span></button>)}
        </div>
        <select aria-label="Floor" value={floor} onChange={(e) => { setFloor(e.target.value === 'all' ? 'all' : +e.target.value); setUnit('all') }}>
          <option value="all">All floors</option>{[3, 4, 5, 6, 7].map((f) => <option key={f} value={f}>Floor {f}</option>)}
        </select>
        <select aria-label="AC unit" value={unit} onChange={(e) => setUnit(e.target.value)}>
          <option value="all">All AC units</option>{units.map((u) => <option key={u} value={u}>{u}</option>)}
        </select>
        <select aria-label="Period" value={period} onChange={(e) => setPeriod(e.target.value)}>
          {Object.entries(PERIOD_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select aria-label="Above or below expected" value={direction} onChange={(e) => setDirection(e.target.value as 'all' | 'high' | 'low')}>
          <option value="all">Above and below expected</option><option value="high">Above expected (high)</option><option value="low">Below expected (low)</option>
        </select>
        <button className="tool" onClick={exportCsv}><Download size={16} strokeWidth={1.5} />Export this list (CSV)</button>
      </div>
      <div className="panel q2-table-panel">
        <div className="table-title">{status === 'flagged'
          ? <><b>{fmt(rows.length)} {POLICY_LABEL[policy]} alerts</b> <span className="muted">{POLICY_NOTE[policy]}</span></>
          : <><b>{fmt(rows.length)} {POLICY_LABEL[policy]} suspected false alarms</b> <span className="muted">Would have alerted, but the case starts on a public holiday, when the building is likely not operating as usual. Not flagged.</span></>}</div>
        <div className="table-wrap">
          <table>
            <thead><tr>
              {head('alert', 'Alert time')}{head('floor', 'Floor, zone')}{head('unit', 'AC unit')}{head('direction', 'Power')}
              <th>Case</th>{head('delay', 'Minutes to alert', true)}{head('abnormal', 'Abnormal min', true)}{head('longest_run', 'Longest run', true)}
              <th>Other policies</th><th>{status === 'held' ? 'Reason held back' : 'Review'}</th><th />
            </tr></thead>
            <tbody>
              {shown.map((c) => (
                <tr key={c.id} onClick={() => setOpen(c.id)}>
                  <td className="mono">{shortStamp(c.alerts[policy]!)}</td>
                  <td className="mono">F{c.floor} Z{c.zone}</td>
                  <td className="mono">{c.unit}</td>
                  <td className={c.direction === 'high' ? 'q2-red' : ''}>{c.direction === 'high' ? 'Above' : 'Below'}</td>
                  <td className="mono muted">{c.start.slice(11, 16)} to {c.end.slice(11, 16)}</td>
                  <td className="n mono">{c.delay[policy]}</td>
                  <td className="n mono">{c.abnormal}</td>
                  <td className="n mono">{c.longest_run}</td>
                  <td className="muted">{POLICIES.filter((p) => p !== policy && c.alerts[p]).map((p) => POLICY_LABEL[p]).join(', ') || 'none'}</td>
                  <td>{c.held ? <span className="q2-holiday">{c.held.reason}: {c.held.holiday}</span> : c.review ? <span className={c.review.rating === 'investigate' ? 'q2-red' : 'muted'}>{c.review.rating} ({c.review.review_id})</span> : ''}</td>
                  <td><button className="ghost" onClick={(e) => { e.stopPropagation(); onReplay({ date: dayOf(c.alerts[policy]!), minute: Math.max(0, minOfDay(c.start) - 10) }) }}>Replay <ExternalLink size={14} strokeWidth={1.5} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length && <p className="hint q2-pad">{status === 'held' ? 'No suspected false alarms match these filters' : 'No alerts match these filters'}</p>}
        </div>
        {rows.length > PAGE && (
          <div className="q2-pager">
            <button className="icon" aria-label="Previous page" disabled={page === 0} onClick={() => setPage(page - 1)}><ChevronLeft size={16} strokeWidth={1.5} /></button>
            <span className="mono muted">{page * PAGE + 1} to {Math.min(rows.length, (page + 1) * PAGE)} of {fmt(rows.length)}</span>
            <button className="icon" aria-label="Next page" disabled={(page + 1) * PAGE >= rows.length} onClick={() => setPage(page + 1)}><ChevronRight size={16} strokeWidth={1.5} /></button>
          </div>
        )}
      </div>
      {open !== null && <AlertDetail id={open} onClose={() => setOpen(null)} onReplay={(f) => { setOpen(null); onReplay(f) }} />}
    </div>
  )
}

// ---------- Alert workload: what each policy asks of the facilities manager ----------

export function WorkloadPage() {
  const { q, error } = useQ2()
  const [floor, setFloor] = useState<'all' | number>('all')
  const [period, setPeriod] = useState('all')
  const [minutes, setMinutes] = useState(10)
  if (error) return <div className="splash">{error}</div>
  if (!q) return <div className="splash">Loading the 2019 alerts</div>
  const rows = Object.fromEntries(q.init.workload.filter((r) => r.floor === floor && r.period === period).map((r) => [r.policy, r])) as Record<string, WorkloadRow>
  const imm = rows.immediate
  const maxWeek = Math.max(...POLICIES.map((p) => rows[p].alerts_per_week), 1)
  const hours = (p: Policy) => (rows[p].alerts_per_week * minutes) / 60
  const saved = (p: Policy) => hours('immediate') - hours(p)
  const fewer = (p: Policy) => (imm.alerts_per_week ? 100 * (1 - rows[p].alerts_per_week / imm.alerts_per_week) : 0)
  const where_ = `${floor === 'all' ? 'Floors 3 to 7' : `Floor ${floor}`}, ${PERIOD_LABEL[period]} ${q.init.year}`
  const sh = q.init.shares
  return (
    <div className="page doc">
      <header className="doc-head">
        <h2>How many alerts would the facilities manager handle?</h2>
        <p>{where_}. Counts are real alerts from the {q.init.year} readings, after holding back cases that start on a Thai public holiday ({POLICIES.map((p) => `${POLICY_LABEL[p]} ${fmt(rows[p].held)}`).join(', ')} held back). Time figures depend on the minutes per alert you set.</p>
      </header>
      <div className="q2-filters">
        <select aria-label="Floor" value={floor} onChange={(e) => setFloor(e.target.value === 'all' ? 'all' : +e.target.value)}>
          <option value="all">All floors (3 to 7)</option>{[3, 4, 5, 6, 7].map((f) => <option key={f} value={f}>Floor {f}</option>)}
        </select>
        <select aria-label="Period" value={period} onChange={(e) => setPeriod(e.target.value)}>
          {Object.entries(PERIOD_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      <div className="stats three q2-stats">
        {POLICIES.map((p) => (
          <div className="stat" key={p}>
            <div className="stat-label">{POLICY_LABEL[p]}{p === '20of30' ? ', main policy' : ''}</div>
            <div className={`stat-value${p === '20of30' ? ' accent' : ''}`}>{fmt(rows[p].alerts_per_week, 1)} <span className="q2-unit">alerts a week</span></div>
            <div className="stat-note">{p === 'immediate' ? `${fmt(rows[p].cases_per_monitored_week ?? 0, 2)} per monitored AC-unit-week` : `${fmt(fewer(p))}% fewer than Immediate, ${fmt(rows[p].cases_per_monitored_week ?? 0, 2)} per unit-week`}</div>
          </div>
        ))}
      </div>
      <div className="doc-split q2-split">
        <div className="panel">
          <h3>Alerts a week</h3>
          <ul className="bars q2-bars">
            {POLICIES.map((p) => (
              <li key={p}>
                <span>{POLICY_LABEL[p]}</span>
                <span className="bar"><i className={p === '20of30' ? 'q2-main' : ''} style={{ width: `${(rows[p].alerts_per_week / maxWeek) * 100}%` }} /></span>
                <span className="mono">{fmt(rows[p].alerts_per_week, 1)}</span>
              </li>
            ))}
          </ul>
          <p className="hint">Total alerts in the period divided by its {fmt(imm.calendar_weeks, 1)} calendar weeks, across the AC units shown. The team's measure, alerts per monitored AC-unit-week, is under each figure above.</p>
        </div>
        <div className="panel">
          <h3>Facilities manager time</h3>
          <label className="slider">
            <span className="slider-top"><span>Minutes to check one alert</span><span className="mono">{minutes} min</span></span>
            <input type="range" min={2} max={60} step={1} value={minutes} onChange={(e) => setMinutes(+e.target.value)} />
          </label>
          <table className="q2-time">
            <thead><tr><th>Policy</th><th className="n">Hours a week</th><th className="n">Saved vs Immediate</th><th className="n">Saved a year</th></tr></thead>
            <tbody>
              {POLICIES.map((p) => (
                <tr key={p} className={p === '20of30' ? 'on' : ''}>
                  <td>{POLICY_LABEL[p]}</td>
                  <td className="n mono">{fmt(hours(p), 1)}</td>
                  <td className="n mono">{p === 'immediate' ? '' : `${fmt(saved(p), 1)} h`}</td>
                  <td className="n mono">{p === 'immediate' ? '' : `${fmt(saved(p) * 52)} h`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="hint">An estimate: alerts a week × the minutes you set. The yearly figure assumes this period's alert rate holds for 52 weeks.</p>
        </div>
      </div>
      <div className="panel panel-gap">
        <h3>What the fewer alerts cost</h3>
        <div className="table-wrap">
          <table className="q2-static">
            <thead><tr><th>Policy</th><th className="n">Cases missed (% of Immediate's)</th><th className="n">Missed per monitored week</th><th className="n">Est. missed worth investigating a week</th><th className="n">Average minutes to alert</th></tr></thead>
            <tbody>
              {POLICIES.map((p) => (
                <tr key={p} className={p === '20of30' ? 'on' : ''}>
                  <td>{POLICY_LABEL[p]}</td>
                  <td className="n mono">{p === 'immediate' ? '0%' : `${fmt(rows[p].missed_pct ?? 0, 1)}%`}</td>
                  <td className="n mono">{fmt(rows[p].missed_per_monitored_week ?? 0, 2)}</td>
                  <td className="n mono">{p === 'immediate' ? '0' : fmt(rows[p].estimated_per_week, 2)}</td>
                  <td className="n mono">{fmt(rows[p].average_delay ?? 0, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint">Missed means a flagged case Immediate alerts on that the policy does not. The estimate uses the step 1 reviewer's Floor 3 ratings for each review group: {Object.entries(sh).filter(([, v]) => v.share !== null).map(([g, v]) => `${GROUP_SHORT[g]} (${g}) ${fmt(v.share!, 2)}`).join('; ')}. Each rests on 4 plots, so treat it as rough.</p>
      </div>
      <div className="doc-split q2-split panel-gap">
        <div className="panel">
          <h3>Reviewed Floor 3 alerts worth investigating</h3>
          <ul className="bars q2-bars">
            {q.init.reviewer.map((r) => (
              <li key={r.policy}>
                <span>{r.label}</span>
                <span className="bar"><i className={r.policy === '20of30' ? 'q2-main' : ''} style={{ width: `${r.investigate_pct ?? 0}%` }} /></span>
                <span className="mono">{r.investigate} of {r.plots}</span>
              </li>
            ))}
          </ul>
          <p className="hint">Of the 16 step 1 review plots (Floor 3, May to September), those each policy alerts on and how many were rated investigate. A small sample chosen to show where the policies differ.</p>
        </div>
        <div className="panel caveats">
          <h3>Read this before quoting it</h3>
          <ul>
            <li><ChevronRight size={16} strokeWidth={1.5} />Alerts are excursions from a 28-day statistical baseline, not confirmed faults</li>
            <li><ChevronRight size={16} strokeWidth={1.5} />Settings were chosen on Floor 3, May to September, and frozen. Floors 4 to 7 and October to December were not used to tune them</li>
            <li><ChevronRight size={16} strokeWidth={1.5} />The baseline does not model holidays. Cases starting on a Thai national public holiday are held back as suspected false alarms and left out of every count here; other days when the building is closed are not detected</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
