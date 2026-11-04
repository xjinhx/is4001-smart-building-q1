import { Component, lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ChevronRight, ListOrdered, Pause, Play, RotateCcw, TriangleAlert, X } from 'lucide-react'
import Chart from './Chart'
import type { Conditions, Day, Init, Result, Schedule, Yearly } from './types'
import { clock, fmt, post, signed } from './types'
import { LABEL_AT, LIFT_CORE, ZONE_SHAPES, type Pt } from './plan'

const Building = lazy(() => import('./Building'))
const RESTART_FROM = 760, RESTART_TO = 820       // 12:40 to 13:40 plays slower
const STEPS = [-10, -5, 0, 5, 10]
export const NO_CHANGE: Conditions = { outdoor_delta_C: 0, indoor_delta_C: 0, load_delta_pct: 0 }

// If 3D can't start on the presenting laptop, the page drops to the flat view by itself
class Fallback extends Component<{ onFail: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch() { this.props.onFail() }
  render() { return this.state.failed ? null : this.props.children }
}

function Elevation({ init, levels, selected, onSelect }: { init: Init; levels: number[]; selected: number | null; onSelect: (j: number) => void }) {
  const W = 144, H = 100
  const points = (pts: Pt[]) => pts.map(([u, v]) => `${u * W},${v * H}`).join(' ')
  return (
    <div className="plans">
      {[7, 6, 5, 4, 3].map((f) => (
        <figure key={f} className="plan">
          <figcaption className="mono">Floor {f}</figcaption>
          <svg viewBox={`-1 -1 ${W + 2} ${H + 2}`} role="group" aria-label={`Floor ${f} plan`}>
            {[1, 2, 3, 4, 5].map((z) => {
              const j = init.zones.findIndex((v) => v.floor === f && v.zone === z)
              const lv = j >= 0 ? levels[j] ?? 0 : 0
              const [lx, ly] = LABEL_AT[z]
              return (
                <g key={z} className={j >= 0 ? 'plan-zone' : ''} onClick={j >= 0 ? () => onSelect(j) : undefined}>
                  <polygon
                    points={points(ZONE_SHAPES[z])}
                    fill={j >= 0 ? `color-mix(in srgb, #f2ad45 ${Math.round(lv * 100)}%, #2a2a2c)` : '#1d1d1f'}
                    stroke={selected === j && j >= 0 ? '#ededed' : '#141415'} strokeWidth={selected === j && j >= 0 ? 1.5 : 1}
                  />
                  <text x={lx * W} y={ly * H} textAnchor="middle" dominantBaseline="middle" fill={lv > 0.5 ? '#141415' : '#a1a1a6'}>{j >= 0 ? `Z${z}` : 'Stairs'}</text>
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

function Stat({ label, value, note, accent, warn }: { label: string; value: string; note: string; accent?: boolean; warn?: boolean }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value${accent ? ' accent' : ''}`}>{value}</div>
      <div className={`stat-note${warn ? ' warn' : ''}`}>{note}</div>
    </div>
  )
}

function ZoneGrid({ init, offsets, selected, onSelect }: { init: Init; offsets: number[]; selected?: number | null; onSelect?: (j: number) => void }) {
  return (
    <div className="grid">
      <span /><span className="mono muted">Z1</span><span className="mono muted">Z2</span><span className="mono muted">Z4</span><span className="mono muted">Z5</span>
      {[7, 6, 5, 4, 3].flatMap((f) => [
        <span className="mono muted" key={`f${f}`}>F{f}</span>,
        ...[1, 2, 4, 5].map((z) => {
          const j = init.zones.findIndex((v) => v.floor === f && v.zone === z)
          const o = offsets[j] ?? 0
          const cls = `cell${selected === j ? ' sel' : ''}${o > 0 ? ' later' : o < 0 ? ' earlier' : ''}`
          const text = `${signed(o)}${init.zones[j].sensor ? '' : '*'}`
          return onSelect
            ? <button key={`${f}-${z}`} className={cls} aria-label={`Floor ${f} zone ${z}, offset ${o} minutes`} onClick={() => onSelect(j)}>{text}</button>
            : <div key={`${f}-${z}`} className={cls}>{text}</div>
        }),
      ])}
    </div>
  )
}

function Flags({ r }: { r: Result }) {
  if (!r.at_risk.length && !r.no_sensor_delayed.length) return <p className="hint">No zone newly goes over 25{'°'}C on this day</p>
  return (
    <>
      {r.at_risk.map((a) => (
        <div className="flag" key={`${a.floor}-${a.zone}`}><TriangleAlert size={16} strokeWidth={1.5} /><span>F{a.floor} Z{a.zone} goes over 25{'°'}C: {fmt(a.today_C, 1)} to {fmt(a.new_C, 1)}{'°'}C</span></div>
      ))}
      {r.no_sensor_delayed.map((a) => (
        <div className="flag" key={`s${a.floor}-${a.zone}`}><TriangleAlert size={16} strokeWidth={1.5} /><span>F{a.floor} Z{a.zone} is delayed with no working sensor</span></div>
      ))}
    </>
  )
}

export function ReplayPage({ init, r, day, whatIf }: { init: Init; r: Result; day: Day; whatIf: boolean }) {
  const from = init.replay_from, to = init.replay_to
  const [minute, setMinute] = useState(RESTART_FROM)
  const [playing, setPlaying] = useState(false)
  const [mode, setMode] = useState<'today' | 'schedule'>('today')
  const [selected, setSelected] = useState<number | null>(null)
  const [hovered, setHovered] = useState<number | null>(null)
  const [view, setView] = useState<'3d' | '2d'>('3d')
  const [showLog, setShowLog] = useState(false)

  useEffect(() => {
    if (!playing) return
    if (minute >= to - 1) { setPlaying(false); return }
    // Slows down through the restart, the part that sets the bill
    const delay = minute >= RESTART_FROM && minute < RESTART_TO ? 220 : 40
    const t = setTimeout(() => setMinute((m) => m + 1), delay)
    return () => clearTimeout(t)
  }, [playing, minute, to])

  // Clicking the same zone again, clicking empty space, the X or Esc all close the zone card
  const toggleZone = (j: number) => setSelected((s) => (s === j ? null : j))
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setSelected(null); setHovered(null) } }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [])

  const series = mode === 'today' ? r.minutes_today : r.minutes_schedule
  const i = minute - from
  const levels = useMemo(() => series.map((z, j) => Math.min(1, (z[i] ?? 0) / Math.max(init.zones[j].rated_kW * 0.75, 1))), [series, i, init])
  const liveKW = series.reduce((a, z) => a + (z[i] ?? 0), 0) + (r.other_minutes[i] ?? 0)
  const logKey = mode === 'today' ? 'today_min' : 'new_min'
  const log = [...r.log].sort((a, b) => a[logKey] - b[logKey])
  const active = hovered ?? selected
  const az = active !== null ? init.zones[active] : null
  const azStart = az ? r.log.find((l) => l.floor === az.floor && l.zone === az.zone) : undefined
  // Sky is only a cue: 0 at night, 1 in daylight, 30 min either side of sunrise and sunset
  const daylight = Math.min(1, Math.max(0, (minute - day.sunrise + 30) / 60)) * Math.min(1, Math.max(0, (day.sunset + 30 - minute) / 60))
  const sun = Math.max(0, Math.sin((Math.PI * (minute - day.sunrise)) / (day.sunset - day.sunrise)))
  const hourly = (v: number[]) => { const h = minute / 60, a = Math.floor(h); return v[a] + (v[Math.min(a + 1, 23)] - v[a]) * (h - a) }
  const outTemp = hourly(day.out_temp), outRh = hourly(day.out_rh), cloud = hourly(day.cloud)
  const peak = mode === 'today' ? r.peak_today : r.peak_schedule

  return (
    <div className="page replay">
      <div className="stage">
        {view === '3d' ? (
          <Fallback onFail={() => setView('2d')}>
            <Suspense fallback={<div className="stage-wait">Drawing the building</div>}>
              <Building zones={init.zones} levels={levels} selected={selected} hovered={hovered} daylight={daylight} sun={sun} humidity={outRh} cloud={cloud} onHover={setHovered} onSelect={toggleZone} onDeselect={() => setSelected(null)} />
            </Suspense>
          </Fallback>
        ) : <Elevation init={init} levels={levels} selected={selected} onSelect={toggleZone} />}
        <div className="readout">
          <div className="mono readout-clock">{clock(minute)}</div>
          <div className="readout-kw">{fmt(liveKW)} kW</div>
          <div className="readout-note">{mode === 'today' ? 'As it really happened' : 'With this schedule'}</div>
          <div className="readout-note">Outside {outTemp.toFixed(1)}°C, {Math.round(outRh)}% humidity</div>
          <div className="readout-note">About {Math.round(cloud)}% cloud</div>
          <div className="readout-peak">Billed peak this day <b>{fmt(peak)} kW</b>{mode === 'schedule' && ` (${signed(Math.round(r.peak_schedule - r.peak_today))} vs today)`}</div>
          {whatIf && <div className="readout-note warn">What-if inputs are on</div>}
        </div>
        <div className="stage-tools">
          <button className="tool" onClick={() => setShowLog(!showLog)} aria-pressed={showLog}><ListOrdered size={16} strokeWidth={1.5} />Restart order</button>
          <div className="seg">
            <button className={view === '3d' ? 'on' : ''} onClick={() => setView('3d')}>3D</button>
            <button className={view === '2d' ? 'on' : ''} onClick={() => setView('2d')}>2D</button>
          </div>
        </div>
        {showLog && (
          <div className="log-panel">
            <div className="log-head"><span>Restart order, {mode === 'today' ? 'today' : 'with schedule'}</span><button aria-label="Close" onClick={() => setShowLog(false)}><X size={16} strokeWidth={1.5} /></button></div>
            <ol>
              {log.map((l) => {
                const j = init.zones.findIndex((v) => v.floor === l.floor && v.zone === l.zone)
                return (
                  <li key={j}><button className={`${l[logKey] <= minute ? 'done' : ''}${selected === j ? ' sel' : ''}`} onClick={() => toggleZone(j)}>
                    <span className="mono">{clock(l[logKey])}</span><span>F{l.floor} Z{l.zone}</span><span className="mono muted">{mode === 'schedule' ? signed(l.offset) : ''}</span>
                  </button></li>
                )
              })}
            </ol>
          </div>
        )}
        {az && !showLog && (
          <div className="zone-card">
            <div className="zone-head">
              <span>Floor {az.floor}, zone {az.zone}</span>
              {selected !== null && <button aria-label="Close zone details" onClick={() => { setSelected(null); setHovered(null) }}><X size={16} strokeWidth={1.5} /></button>}
            </div>
            <div className="muted">{fmt(series[active!]?.[i] ?? 0, 1)} kW now, {fmt(az.rated_kW)} kW rated</div>
            {azStart
              ? <div className="muted mono">Restarts {clock(azStart.today_min)} today{azStart.new_min !== azStart.today_min ? `, ${clock(azStart.new_min)} with schedule` : ', same with schedule'}</div>
              : <div className="muted">No restart detected this day</div>}
          </div>
        )}
        <div className="stage-note">Zones follow the CU-BEMS floor plan. Which way it faces is assumed</div>
        <div className="player">
          <button className="icon" onClick={() => { if (!playing && minute >= to - 1) setMinute(from); setPlaying(!playing) }} aria-label={playing ? 'Pause' : 'Play'}>
            {playing ? <Pause size={16} strokeWidth={1.5} /> : <Play size={16} strokeWidth={1.5} />}
          </button>
          <input aria-label="Replay time" type="range" min={from} max={to - 1} value={minute} onChange={(e) => { setMinute(+e.target.value); setPlaying(false) }} />
          <span className="mono muted times">{clock(from)} to {clock(to)}</span>
          <button className="tool" onClick={() => { setMinute(RESTART_FROM); setPlaying(false) }}>Jump to restart</button>
          <div className="seg">
            <button className={mode === 'today' ? 'on' : ''} onClick={() => setMode('today')}>Today</button>
            <button className={mode === 'schedule' ? 'on' : ''} onClick={() => setMode('schedule')}>With schedule</button>
          </div>
        </div>
      </div>
      <div className="chart-wrap"><Chart r={r} minute={minute} onSeek={(m) => { setMinute(m); setPlaying(false) }} /></div>
    </div>
  )
}

function Scatter({ list, selected, today, onPick }: { list: Schedule[]; selected: string; today: number; onPick: (id: string) => void }) {
  const W = 560, H = 300, L = 44, R = 16, T = 12, B = 44
  const X = (v: number) => L + ((v + 12) / 13) * (W - L - R)
  const Y = (v: number) => T + (1 - v / 32) * (H - T - B)
  const labelAt = (id: string): [number, number, 'start' | 'end'] => {
    if (id === 'Rule-based benchmark') return [10, 4, 'start']
    if (id === 'Recommended') return [-10, 16, 'end']
    if (id === 'ML kW model') return [-10, -6, 'end']
    if (id === '±5 min only') return [-10, 4, 'end']
    if (id === 'none') return [-10, -8, 'end']
    if (id === 'Top 3 days, no comfort rule') return [10, -8, 'start']
    return [10, 4, 'start']
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="scatter" role="img" aria-label="Peak cut against change in comfort for each schedule on 2018 data">
      {[0, 10, 20, 30].map((v) => <g key={v}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} stroke="rgba(237,237,237,.08)" /><text x={L - 8} y={Y(v) + 4} textAnchor="end" className="tick">{v}</text></g>)}
      {[-12, -8, -4, 0].map((v) => <text key={v} x={X(v)} y={H - B + 18} textAnchor="middle" className="tick">{signed(v)}</text>)}
      <line x1={X(0)} x2={X(0)} y1={T} y2={H - B} stroke="rgba(237,237,237,.28)" strokeDasharray="3 3" />
      <text x={X(0) - 6} y={T + 12} textAnchor="end" className="tick">No worse than today</text>
      <text x={L + (W - L - R) / 2} y={H - 6} textAnchor="middle" className="tick">Comfort change on 2018 (points)</text>
      <text x={12} y={T + (H - T - B) / 2} textAnchor="middle" transform={`rotate(-90 12 ${T + (H - T - B) / 2})`} className="tick">Monthly cut (kW)</text>
      {list.map((s) => {
        const x = X(s.comfort_2018 - today), on = s.id === selected, [dx, dy, anchor] = labelAt(s.id)
        return (
          <g key={s.id} className="pt" onClick={() => onPick(s.id)}>
            {s.id !== 'none' && <line x1={x} x2={x} y1={Y(s.ci[0])} y2={Y(s.ci[1])} stroke={on ? '#f2ad45' : '#85858b'} strokeWidth={1.5} />}
            <circle cx={x} cy={Y(s.cut_2018)} r={on ? 6 : 4.5} fill={on ? '#f2ad45' : '#a1a1a6'} stroke="#141415" strokeWidth={2} />
            <text x={x + dx} y={Y(s.cut_2018) + dy} textAnchor={anchor} className={on ? 'pt-label on' : 'pt-label'}>{s.label}</text>
          </g>
        )
      })}
    </svg>
  )
}

export function SchedulesPage({ init, r, offsets, scheduleId, onPick }: { init: Init; r: Result; offsets: number[]; scheduleId: string; onPick: (id: string) => void }) {
  const list = init.schedules
  const today = list[0].comfort_2018
  const rec = list.find((s) => s.id === 'Recommended')!
  const rule = list.find((s) => s.id === 'Rule-based benchmark')!
  return (
    <div className="page doc">
      <header className="doc-head">
        <h2>Which schedule should we use?</h2>
        <p>Fitted on 2019, scored on the 2018 holdout. Recommended cuts {fmt(rec.cut_2018, 1)} kW a month, level with the rule-based {fmt(rule.cut_2018, 1)} kW, since the gap could easily be zero. No {'±'}10 min schedule keeps 2018 comfort at today's {fmt(today, 1)}%.</p>
      </header>
      <div className="doc-split">
        <div className="panel wide">
          <Scatter list={list} selected={scheduleId} today={today} onPick={onPick} />
        </div>
        <div className="panel">
          <h3>{list.find((s) => s.id === scheduleId)?.label ?? (scheduleId === 'Suggested' ? 'Suggested for this day' : 'Edited by hand')}</h3>
          <ZoneGrid init={init} offsets={offsets} />
          <p className="hint">Minutes from today's restart. + later, {'−'} earlier. * No working sensor, so comfort is unchecked</p>
          <div className="panel-gap"><h3>On {new Date(r.date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}</h3><Flags r={r} /></div>
        </div>
      </div>
      <div className="panel table-wrap">
        <table>
          <thead><tr><th>Schedule</th><th className="n">Monthly cut, 2018</th><th className="n">95% range</th><th className="n">vs rule-based</th><th className="n">{'≤'}25{'°'}C, 2018</th><th className="n">{'≤'}25{'°'}C, 2019</th><th className="n">kWh a day</th><th className="n">Starts outside 2019 range</th></tr></thead>
          <tbody>
            {list.map((s) => (
              <tr key={s.id} className={s.id === scheduleId ? 'on' : ''} onClick={() => onPick(s.id)}>
                <td><button>{s.label}</button></td>
                <td className="n">{fmt(s.cut_2018, 1)} kW</td>
                <td className="n">{s.id === 'none' ? '' : `${fmt(s.ci[0], 1)} to ${fmt(s.ci[1], 1)}`}</td>
                <td className="n">{s.vs_rule === null || s.id === rule.id ? '' : `${signed(s.vs_rule)} (${signed(s.vs_rule_ci![0])} to ${signed(s.vs_rule_ci![1])})`}</td>
                <td className="n">{fmt(s.comfort_2018, 1)}%</td>
                <td className="n">{fmt(s.comfort_2019, 1)}%</td>
                <td className="n">{signed(s.kwh_steady)}</td>
                <td className="n">{s.outside_pct === null ? '' : `${s.outside_pct}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Slider({ label, value, min, max, step, unit, now, onChange }: { label: string; value: number; min: number; max: number; step: number; unit: string; now: string; onChange: (v: number) => void }) {
  return (
    <label className="slider">
      <span className="slider-top"><span>{label}</span><span className="mono muted">{now}{value ? ` (${value > 0 ? '+' : '−'}${Math.abs(value)}${unit})` : ''}</span></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(+e.target.value)} />
    </label>
  )
}

export function WhatIfPage({ init, r, offsets, cond, scheduleId, busy, setOffset, setCond, onSuggest }: {
  init: Init; r: Result; offsets: number[]; cond: Conditions; scheduleId: string; busy: boolean
  setOffset: (j: number, v: number) => void; setCond: (c: Conditions) => void; onSuggest: () => void
}) {
  const [selected, setSelected] = useState<number | null>(null)
  const monthName = new Date(r.date).toLocaleDateString('en-GB', { month: 'long' })
  const tuned = scheduleId === 'Suggested' || scheduleId === 'Custom'
  const active = cond.outdoor_delta_C !== 0 || cond.indoor_delta_C !== 0 || cond.load_delta_pct !== 0
  return (
    <div className="page whatif">
      <aside className="tools">
        <section>
          <div className="head-row"><h3>Change a zone</h3></div>
          <ZoneGrid init={init} offsets={offsets} selected={selected} onSelect={setSelected} />
          {selected !== null
            ? <div className="stepper"><span>F{init.zones[selected].floor} Z{init.zones[selected].zone}</span><div className="seg small">{STEPS.map((v) => <button key={v} className={offsets[selected] === v ? 'on' : ''} onClick={() => setOffset(selected, v)}>{signed(v)}</button>)}</div></div>
            : <p className="hint">Pick a zone to change its restart time</p>}
          <p className="hint">* No working sensor, so comfort is unchecked</p>
        </section>
        <section>
          <div className="head-row"><h3>Change the conditions</h3>{active && <button className="ghost" onClick={() => setCond(NO_CHANGE)}><RotateCcw size={14} strokeWidth={1.5} />Reset</button>}</div>
          <Slider label="Outdoor temp at restart" value={cond.outdoor_delta_C} min={-3} max={3} step={0.5} unit={'°C'} now={r.conditions_used ? `${fmt(r.conditions_used.outdoor_C, 1)}°C` : ''} onChange={(v) => setCond({ ...cond, outdoor_delta_C: v })} />
          <Slider label="Indoor temp at restart" value={cond.indoor_delta_C} min={-2} max={2} step={0.5} unit={'°C'} now={r.conditions_used?.indoor_C != null ? `${fmt(r.conditions_used.indoor_C, 1)}°C` : 'No reading'} onChange={(v) => setCond({ ...cond, indoor_delta_C: v })} />
          <Slider label="Zone load before lunch" value={cond.load_delta_pct} min={-20} max={20} step={5} unit="%" now={r.conditions_used ? `${fmt(r.conditions_used.load_kW)} kW` : ''} onChange={(v) => setCond({ ...cond, load_delta_pct: v })} />
          <p className="hint">Model estimates, weaker than the replay</p>
        </section>
        <section>
          <button className="primary full" onClick={onSuggest} disabled={busy}>{busy ? 'Searching' : 'Suggest schedule'}</button>
          <p className="hint">Finds the lowest peak for this day only, with kWh and comfort no worse than today</p>
        </section>
      </aside>
      <div className="results">
        <div className="stats three">
          <Stat label="Billed peak this day" value={`${fmt(r.peak_schedule)} kW`} note={`${signed(Math.round(r.peak_schedule - r.peak_today))} vs today`} />
          <Stat label={`Billed peak, ${monthName}`} value={`${fmt(r.month_peak_schedule)} kW`} note={`${signed(-Math.round(r.month_peak_today - r.month_peak_schedule))} vs today`} />
          <Stat label="Demand charge saved" value={`${fmt(r.baht_month)} baht`} note={`${monthName}, vs today`} accent />
        </div>
        <div className="chart-wrap tall"><Chart r={r} from={690} to={930} /></div>
        <div className="result-notes">
          <div>
            <h3>Comfort, 30 min after restart</h3>
            <p className="big-line">{r.comfort_day.readings ? `${r.comfort_day.schedule} of ${r.comfort_day.readings} zones at or below 25°C` : 'No indoor readings this day'}</p>
            {r.comfort_day.readings > 0 && <p className="hint">{r.comfort_day.today} of {r.comfort_day.readings} today</p>}
            <Flags r={r} />
          </div>
          <div>
            <h3>Across all of 2018</h3>
            <p className="big-line">{fmt(r.holdout_avg_cut, 1)} kW monthly cut</p>
            <p className="hint">{tuned ? `Chosen on a 2018 day, so not a holdout result. ${fmt(r.cut_2019, 1)} kW on 2019 data is the fairer test` : 'Holdout result for this schedule'}</p>
            <p className="hint">{fmt(r.comfort_holdout.schedule, 1)}% of zone-days at or below 25{'°'}C, {fmt(r.comfort_holdout.today, 1)}% today. kWh a day {signed(r.kwh_steady)}</p>
            {r.starts_outside_range > 0 && <p className="hint">{r.starts_outside_range} of {r.log.length} new start times fall outside what 2019 covers</p>}
            {r.peak_floor_binds && <p className="hint">Another interval sets this day's peak at {fmt(r.peak_elsewhere_kW)} kW, so restarts can't lower it further</p>}
            {active && <p className="hint strong">What-if inputs are on, so this day's figures are model estimates</p>}
          </div>
        </div>
      </div>
    </div>
  )
}

export function YearlyPage({ offsets, scheduleId, label }: { offsets: number[]; scheduleId: string; label: string }) {
  const [heat, setHeat] = useState(0)
  const [y, setY] = useState<Yearly | null>(null)
  const [error, setError] = useState('')
  const seq = useRef(0)
  useEffect(() => {
    const id = ++seq.current
    post<Yearly>('/api/yearly', { offsets, outdoor_delta_C: heat })
      .then((v) => { if (id === seq.current) { setY(v); setError('') } })
      .catch((e) => { if (id === seq.current) setError(e.message) })
  }, [offsets, heat])
  if (error) return <div className="splash">{error}</div>
  if (!y) return <div className="splash">Working out the year</div>
  const tuned = scheduleId === 'Suggested' || scheduleId === 'Custom'
  const maxCut = Math.max(...y.months.map((m) => m.today - m.schedule), 1)
  const drop = y.comfort_schedule - y.comfort_today
  return (
    <div className="page doc">
      <header className="doc-head">
        <h2>What's it worth over a year?</h2>
        <p>{label}, projected from the 2018 holdout. An estimate from simulated replays, not a measured saving.</p>
      </header>
      <div className="doc-split yearly">
        <div className="panel value">
          <div className="seg heat" role="group" aria-label="Outdoor temperature scenario">
            {[0, 1, 2].map((h) => <button key={h} className={heat === h ? 'on' : ''} onClick={() => setHeat(h)}>{h === 0 ? 'As in 2018' : `+${h}°C`}</button>)}
          </div>
          <div className="value-num">{fmt(y.baht)} <span>baht a year</span></div>
          <div className="value-range">Range {fmt(y.baht_lo)} to {fmt(y.baht_hi)} baht</div>
          <div className="value-math mono">{fmt(y.cut, 1)} kW {'×'} {y.rate} baht {'×'} 12 months</div>
          <dl className="value-facts">
            <div><dt>Zone-days at or below 25{'°'}C</dt><dd className={drop < 0 ? 'warn' : ''}>{fmt(y.comfort_schedule, 1)}%, {signed(Math.round(drop * 10) / 10)} points vs no change</dd></div>
            <div><dt>No change, same conditions</dt><dd>{fmt(y.comfort_today, 1)}%</dd></div>
          </dl>
        </div>
        <div className="panel">
          <h3>Monthly cut behind the estimate</h3>
          <ul className="bars">
            {y.months.map((m) => {
              const cut = m.today - m.schedule
              return (
                <li key={m.month}>
                  <span>{new Date(`${m.month}-01`).toLocaleDateString('en-GB', { month: 'short' })}</span>
                  <span className="bar"><i style={{ width: `${Math.max(0, cut / maxCut) * 100}%` }} /></span>
                  <span className="mono">{fmt(cut, 1)} kW</span>
                </li>
              )
            })}
          </ul>
        </div>
      </div>
      <div className="panel caveats">
        <h3>Read this before quoting it</h3>
        <ul>
          <li><ChevronRight size={16} strokeWidth={1.5} />Assumes the July to December 2018 cuts hold for all 12 months</li>
          <li><ChevronRight size={16} strokeWidth={1.5} />Floors 3 to 7 are only part of the building meter, and the 12 to 24 kV tariff is assumed</li>
          <li><ChevronRight size={16} strokeWidth={1.5} />{heat === 0 ? 'Uses real time-shifted curves, with no staggered start ever run in the building' : 'Hotter scenarios are model estimates. Inputs stay inside what 2019 covers, so the hottest days are understated'}</li>
          {tuned && <li><ChevronRight size={16} strokeWidth={1.5} />This schedule was chosen on a 2018 day, so this isn't a holdout result</li>}
        </ul>
      </div>
    </div>
  )
}
