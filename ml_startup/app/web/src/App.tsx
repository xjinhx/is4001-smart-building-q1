import { useCallback, useEffect, useRef, useState } from 'react'
import type { Conditions, Init, Result } from './types'
import { post } from './types'
import { AdaptivePage, NO_CHANGE, ReplayPage, SchedulesPage, WhatIfPage, YearlyPage } from './pages'
import { AlertListPage, AlertsPage, WorkloadPage, type Focus } from './q2'

const PAGES = [['replay', 'Replay'], ['schedules', 'Schedules'], ['whatif', 'What if'], ['yearly', 'Yearly value'], ['adaptive', 'Adaptive'],
  ['alerts', 'Alerts'], ['alertlist', 'Alert list'], ['workload', 'Alert workload']] as const
// Q2 pages: real 2019 AC alerts, with their own day and policy controls
const Q2_PAGES: readonly string[] = ['alerts', 'alertlist', 'workload']
type Page = (typeof PAGES)[number][0]
const pageFromHash = (): Page => {
  const h = location.hash.replace('#/', '')
  return (PAGES.find(([k]) => k === h)?.[0]) ?? 'replay'
}

export default function App() {
  const [init, setInit] = useState<Init | null>(null)
  const [page, setPage] = useState<Page>(pageFromHash)
  const [date, setDate] = useState('')
  const [scheduleId, setScheduleId] = useState('Recommended')
  const [offsets, setOffsets] = useState<number[]>([])
  const [cond, setCond] = useState<Conditions>(NO_CHANGE)
  const [r, setR] = useState<Result | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const seq = useRef(0)
  const [focus, setFocus] = useState<Focus | null>(null)
  const toReplay = useCallback((f: Focus) => { setFocus(f); location.hash = '#/alerts' }, [])

  useEffect(() => {
    const on = () => setPage(pageFromHash())
    addEventListener('hashchange', on)
    return () => removeEventListener('hashchange', on)
  }, [])

  useEffect(() => {
    fetch('/api/init').then((x) => x.json()).then((i: Init) => {
      setInit(i)
      setDate(i.default_date)
      setOffsets(i.schedules.find((s) => s.id === 'Recommended')!.offsets)
    }).catch(() => setError('Start the backend first: python app/api.py'))
  }, [])

  useEffect(() => {
    if (!date || !offsets.length) return
    const id = ++seq.current
    const t = setTimeout(() => {
      post<Result>('/api/simulate', { date, offsets, conditions: cond })
        .then((res) => { if (id === seq.current) { setR(res); setError('') } })
        .catch((e) => { if (id === seq.current) setError(e.message) })
    }, 60)
    return () => clearTimeout(t)
  }, [date, offsets, cond])

  const suggest = useCallback(() => {
    setBusy(true)
    const id = ++seq.current
    post<Result>('/api/suggest', { date, conditions: cond })
      .then((res) => { if (id === seq.current) { setR(res); setOffsets(res.offsets); setScheduleId('Suggested'); setError('') } })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false))
  }, [date, cond])

  const pickSchedule = (id: string) => {
    setScheduleId(id)
    const s = init?.schedules.find((x) => x.id === id)
    if (s) setOffsets(s.offsets)
  }
  const setOffset = (j: number, v: number) => {
    setOffsets((o) => o.map((x, i) => (i === j ? v : x)))
    setScheduleId('Custom')
  }

  if (error && !r) return <div className="splash">{error}</div>
  if (!init || !r) return <div className="splash">Loading the 2018 replay</div>

  const day = init.days.find((d) => d.date === date)!
  const whatIf = cond.outdoor_delta_C !== 0 || cond.indoor_delta_C !== 0 || cond.load_delta_pct !== 0
  const named = init.schedules.find((s) => s.id === scheduleId)
  const label = named?.label ?? (scheduleId === 'Suggested' ? 'Suggested for this day' : 'Edited by hand')
  const q2 = Q2_PAGES.includes(page)

  return (
    <div className="shell">
      <header className="top">
        <div className="brand">
          <h1>Chamchuri 5 restart console</h1>
          <span>{q2 ? 'AC alerts from recorded 2019 data' : 'Simulated from recorded 2018 data'}</span>
        </div>
        <nav aria-label="Pages">
          {PAGES.map(([k, name]) => <a key={k} href={`#/${k}`} className={page === k ? 'on' : ''} aria-current={page === k ? 'page' : undefined}>{name}</a>)}
        </nav>
        <div className="controls">
          {page !== 'yearly' && page !== 'schedules' && page !== 'adaptive' && !q2 && (
            <select aria-label="Day" value={date} onChange={(e) => setDate(e.target.value)}>
              {init.days.map((d) => <option key={d.date} value={d.date}>{d.label}{d.month_peak ? ', month peak' : ''}</option>)}
            </select>
          )}
          {page !== 'adaptive' && !q2 && (
            <select aria-label="Schedule" value={scheduleId} onChange={(e) => pickSchedule(e.target.value)}>
              {init.schedules.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
              {scheduleId === 'Suggested' && <option value="Suggested">Suggested for this day</option>}
              {scheduleId === 'Custom' && <option value="Custom">Edited by hand</option>}
            </select>
          )}
        </div>
      </header>
      {error && <div className="error" role="alert">{error}. These figures are out of date</div>}
      <main className="body">
        {page === 'replay' && <ReplayPage init={init} r={r} day={day} whatIf={whatIf} />}
        {page === 'schedules' && <SchedulesPage init={init} r={r} offsets={offsets} scheduleId={scheduleId} onPick={pickSchedule} />}
        {page === 'whatif' && <WhatIfPage init={init} r={r} offsets={offsets} cond={cond} scheduleId={scheduleId} busy={busy} setOffset={setOffset} setCond={setCond} onSuggest={suggest} />}
        {page === 'yearly' && <YearlyPage offsets={offsets} scheduleId={scheduleId} label={label} />}
        {page === 'adaptive' && <AdaptivePage init={init} />}
        {page === 'alerts' && <AlertsPage zones={init.zones} focus={focus} onFocus={setFocus} />}
        {page === 'alertlist' && <AlertListPage onReplay={toReplay} />}
        {page === 'workload' && <WorkloadPage />}
      </main>
    </div>
  )
}
