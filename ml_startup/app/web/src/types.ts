export type Zone = { floor: number; zone: number; rated_kW: number; sensor: boolean }
export type Adaptive = {
  benchmark: { schedule: string; cut_2018_kW: number; cut_2018_CI_lo: number; cut_2018_CI_hi: number; vs_fixed_2018_kW: number; vs_fixed_CI_lo: number; vs_fixed_CI_hi: number; comfort_2018_today: number; comfort_2018_new: number; baht_per_month_2018: number }[]
  forecaster: { set: string; accuracy: number; top3_peak_days_accuracy: number; majority_baseline: number }[]
  day_types: { set: string; day_type: string; n_days: number; mean_kW: number; t_mean: number }[]
  schedules: { floor: number; zone: number; offset_min: number; day_type: string; n_days: number }[]
  monthly: { month: string; cut_kW: number; cut_fixed_kW: number }[]
  forecast_test: { group: string; name: string; cut_kW: number; cut_lo: number; cut_hi: number; vs_fixed_kW: number; vs_fixed_lo: number | null; vs_fixed_hi: number | null; right_type_pct: number | null; right_type_peak_days_pct: number | null; comfort_2018_pct: number }[]
}
export type Day = { date: string; label: string; month: string; peak: number; month_peak: boolean; readings: number; sunrise: number; sunset: number; out_temp: number[]; out_rh: number[]; cloud: number[] }
export type Schedule = {
  id: string; label: string; offsets: number[]; cut_2018: number; ci: [number, number]
  comfort_2018: number; comfort_2019: number; vs_rule: number | null; vs_rule_ci: [number, number] | null
  kwh_steady: number; outside_pct: number | null
}
export type Init = {
  days: Day[]; default_date: string; schedules: Schedule[]; replay_from: number; replay_to: number; zones: Zone[]
  demand_baht_per_kW: number; start_range: [number, number]
}
export type Conditions = { outdoor_delta_C: number; indoor_delta_C: number; load_delta_pct: number }
export type LogRow = { floor: number; zone: number; offset: number; today_min: number; new_min: number }
export type Result = {
  date: string; offsets: number[]; bins: number[]
  curve_actual: number[]; curve_today: number[]; curve_schedule: number[]
  morning_peak: number; morning_peak_bin: number
  peak_today: number; peak_schedule: number; peak_bin_today: number; peak_bin_schedule: number
  peak_elsewhere_kW: number; peak_floor_binds: boolean
  month: string; month_peak_today: number; month_peak_schedule: number; baht_month: number
  holdout_avg_cut: number; cut_2019: number; kwh_steady: number; kwh_model: number
  comfort_day: { readings: number; today: number; schedule: number }
  comfort_holdout: { today: number; schedule: number }
  at_risk: { floor: number; zone: number; today_C: number; new_C: number }[]
  log: LogRow[]; starts_outside_range: number; no_sensor_delayed: { floor: number; zone: number }[]
  minutes_today: number[][]; minutes_schedule: number[][]; other_minutes: number[]
  conditions_used: { outdoor_C: number; indoor_C: number | null; load_kW: number } | null
}
export type Yearly = {
  outdoor_delta_C: number; cut: number; cut_lo: number; cut_hi: number; baht: number; baht_lo: number; baht_hi: number
  months: { month: string; today: number; schedule: number }[]; comfort_today: number; comfort_schedule: number; rate: number
}

export const clock = (m: number) => `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}`
export const signed = (n: number) => (n > 0 ? `+${n}` : n < 0 ? `−${Math.abs(n)}` : '0')
export const fmt = (n: number, d = 0) => n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
export const post = async <T,>(path: string, body: unknown): Promise<T> => {
  const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!res.ok) throw new Error(`The backend returned ${res.status}`)
  return res.json()
}
