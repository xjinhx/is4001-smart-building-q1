"""Backend for the what-if console: python app/api.py, then open http://127.0.0.1:8000

Offsets use the same real time-shifted curves as sim.py, so with the what-if sliders at
zero the numbers match results/. Moving a slider adds the model's estimated change on top
(model with the edited inputs - model with the actual inputs). Replays 2018 holdout days;
every model here was fitted on 2019 only.
"""
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import uvicorn
import xgboost as xgb
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import COMFORT_C, DATA, DEMAND_BAHT_PER_KW, OFFSETS, PM_COMFORT_ELAPSED, RESULTS, WORK
from models import (BIN_MINS, KW_FEATURES, PM_T_FEATURES, REL_HI, REL_LO, add_attrs, attrs_table, fit_kw, fit_temp,
                    kw_table, load_events, temp_tables)
from optimiser import K0, Optimiser
from sim import bootstrap_cut, shift

WINDOW_START = 690      # 11:30, in minutes after midnight: offsets only change this window
WINDOW_LEN = 240
REPLAY_FROM, REPLAY_TO = 360, 1170     # 06:00 to 19:30. AC is off by about 17:00, sunset is 18:00-18:50
HEAT_STEPS = (0, 1, 2)
SCHEDULE_LABELS = {'No change': 'No change',
                   'Recommended: real profiles + ML constraints': 'Recommended',
                   'Rule benchmark (Haritha)': 'Rule-based benchmark',
                   'Recommended variant limited to +/-5 min': '±5 min only',
                   'Pure ML kW model (delta) + constraints': 'ML kW model',
                   'Real profiles, top-3, no comfort rule': 'Top 3 days, no comfort rule'}


def clean(x):
    """JSON has no NaN: days with no indoor readings send null instead."""
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v) for v in x]
    return None if isinstance(x, float) and not np.isfinite(x) else x


def fitted(name, fit):
    """Load a 2019-only model from work/, fitting it the first time."""
    path = WORK / name
    m = xgb.XGBRegressor()
    if path.exists():
        m.load_model(path)
        return m
    m = fit()
    m.save_model(path)
    return m


class Conditions(BaseModel):
    outdoor_delta_C: float = Field(0, ge=-5, le=5)
    indoor_delta_C: float = Field(0, ge=-3, le=3)
    load_delta_pct: float = Field(0, ge=-30, le=30)

    def active(self):
        return bool(self.outdoor_delta_C or self.indoor_delta_C or self.load_delta_pct)


class Request(BaseModel):
    date: str
    offsets: list[int] | None = None
    conditions: Conditions = Conditions()


class YearlyRequest(BaseModel):
    offsets: list[int]
    outdoor_delta_C: int = 0


class Console:
    def __init__(self):
        self.opt = Optimiser.load()
        self.P = P = self.opt.P
        self.m_kw = fitted('app_kw.json', self._fit_kw)
        self.m_t = fitted('app_temp.json', self._fit_t)
        self.Z = len(P.zones)
        self.d_ix = {str(d.date()): i for i, d in enumerate(P.days)}
        self.z_ix = {v: i for i, v in enumerate(P.zones)}
        self.te = P.mask(2018)
        E = add_attrs(load_events().query("event == 'PM'"))
        E['d'] = E.date.map({d: i for i, d in enumerate(P.days)})
        E['j'] = [self.z_ix[(f, z)] for f, z in zip(E.floor, E.zone)]
        self.E = E
        self.events = {d: g for d, g in E.groupby('d')}
        self.drift = float(E.T_drift_10min.median()) / 10
        tr = E[E.set == 'train_2019']
        self.bounds = {c: tuple(tr[c].quantile([.01, .99])) for c in ('out_T', 'T_start', 'morning_kW')}
        self.start_lo, self.start_hi = tr.start_min.quantile([.01, .99])
        self.base = self._all_peaks(np.full(self.Z, K0))
        a = attrs_table().query('year == 2019').set_index(['floor', 'zone'])
        self.rated = np.array([a.loc[z, 'rated_kW'] for z in P.zones])
        self.schedules = self._schedules()
        self.full_ac = np.load(WORK / 'full_day_minutes.npz')['ac']
        self.building = pd.read_csv(DATA / 'building_15min_alldays.csv', parse_dates=['ts'],
                                    usecols=['ts', 'total_kW', 'Light_kW', 'Plug_kW']).set_index('ts')
        self.sun = pd.read_csv(Path(__file__).parent / 'sun_times_2018.csv').set_index('date')
        self.heat_lock = threading.Lock()
        self.heat = {}

    @staticmethod
    def _fit_kw():
        K = add_attrs(kw_table())
        return fit_kw(K[K.set == 'train_2019'])

    @staticmethod
    def _fit_t():
        pm, _ = temp_tables()
        pm = add_attrs(pm)
        return fit_temp(pm[pm.set == 'train_2019'], PM_T_FEATURES)

    def _schedules(self):
        O = pd.read_csv(RESULTS / 'schedule_offsets_all.csv')
        C = pd.read_csv(RESULTS / 'schedule_comparison.csv').set_index('schedule')
        out = [dict(id='none', label='No change', offsets=[0] * self.Z, cut_2018=0.0, ci=[0.0, 0.0],
                    comfort_2018=round(float(C.comfort_2018_today.iloc[0]), 1),
                    comfort_2019=round(float(C.comfort_2019_today.iloc[0]), 1), vs_rule=None, vs_rule_ci=None,
                    kwh_steady=0.0, outside_pct=None)]
        for col, lab in SCHEDULE_LABELS.items():
            if col in O:
                offs = [int(O[(O.floor == f) & (O.zone == z)][col].iloc[0]) for f, z in self.P.zones]
                r = C.loc[col]
                out.append(dict(id=lab, label=lab, offsets=offs, cut_2018=round(float(r.cut_2018_kW), 1),
                                ci=[round(float(r.cut_2018_CI_lo), 1), round(float(r.cut_2018_CI_hi), 1)],
                                comfort_2018=round(float(r.comfort_2018_new), 1),
                                comfort_2019=round(float(r.comfort_2019_new), 1),
                                vs_rule=round(float(r.vs_rule_2018_kW), 1),
                                vs_rule_ci=[round(float(r.vs_rule_CI_lo), 1), round(float(r.vs_rule_CI_hi), 1)],
                                kwh_steady=round(float(r.kWh_day_rule), 1),
                                outside_pct=round(float(r.starts_outside_2019_P1_P99_pct))))
        return out

    def _all_peaks(self, ki):
        total = self.opt.O15 + self.opt.real[:, np.arange(self.Z), ki, :].sum(axis=1)
        return np.maximum(total.max(axis=1), self.P.OUT)

    def _edit(self, g, c):
        """Apply the what-if inputs, kept inside the 2019 P1-P99 range the models were fitted on."""
        g = g.copy()
        for col, new in (('out_T', g.out_T + c.outdoor_delta_C), ('T_start', g.T_start + c.indoor_delta_C),
                         ('morning_kW', g.morning_kW * (1 + c.load_delta_pct / 100))):
            if (col == 'out_T' and c.outdoor_delta_C) or (col == 'T_start' and c.indoor_delta_C) \
                    or (col == 'morning_kW' and c.load_delta_pct):
                g[col] = new.clip(*self.bounds[col])
        return g

    def _kw_model(self, g):
        """Model kW for this day's events: Z x K x T, with 0 change outside the modelled range."""
        nk, nt = len(OFFSETS), len(BIN_MINS)
        R = g.loc[g.index.repeat(nk * nt)].copy()
        R['k'] = np.tile(np.repeat(np.arange(nk), nt), len(g))
        R['t'] = np.tile(np.arange(nt), nk * len(g))
        off = np.array(OFFSETS)[R.k]
        raw = BIN_MINS[R.t] - (R.start_min.values + off)
        R['rel_min'] = np.clip(raw, REL_LO, REL_HI)
        R['start_min'] = R.start_min.values + off
        R['minutes_off'] = R.minutes_off.values + off
        R['T_start'] = R.T_start.values + self.drift * off
        p = np.maximum(self.m_kw.predict(R[KW_FEATURES].astype(float)), 0)
        p[(raw < REL_LO) | (raw > REL_HI)] = 0
        out = np.zeros((self.Z, nk, nt))
        out[R.j.values, R.k.values, R.t.values] = p
        return out

    def _temp_model(self, g):
        """Model temp at today's restart + 30 min on the clock: Z x K."""
        nk = len(OFFSETS)
        C = g.loc[g.index.repeat(nk)].copy()
        C['k'] = np.tile(np.arange(nk), len(g))
        off = np.array(OFFSETS)[C.k]
        C['elapsed'] = PM_COMFORT_ELAPSED - off
        C['minutes_off'] = C.minutes_off.values + off
        C['T_start'] = C.T_start.values + self.drift * off
        out = np.full((self.Z, nk), np.nan)
        out[C.j.values, C.k.values] = self.m_t.predict(C[PM_T_FEATURES].astype(float))
        return out

    def _day_cubes(self, d, c):
        """kW cube (Z,K,T) and comfort temp (Z,K) for one day under the what-if inputs."""
        cube = self.opt.real[d].copy()
        T = self.opt.T[d].copy()
        g = self.events.get(d)
        if g is None or not c.active():
            return cube, T, np.zeros_like(cube)
        e = self._edit(g, c)
        delta = self._kw_model(e) - self._kw_model(g)
        t0, t1 = self._temp_model(g), self._temp_model(e)
        return np.maximum(cube + delta, 0), T + (t1 - t0), delta

    def simulate(self, r):
        d = self._day(r.date)
        offs = r.offsets if r.offsets is not None else [0] * self.Z
        if len(offs) != self.Z or any(o not in OFFSETS for o in offs):
            raise HTTPException(422, 'Offsets must be -10, -5, 0, +5 or +10 for each zone')
        P, opt = self.P, self.opt
        ki = np.array([OFFSETS.index(o) for o in offs])
        cube, T, delta = self._day_cubes(d, r.conditions)
        z = np.arange(self.Z)
        base15 = opt.O15[d] + cube[z, K0].sum(axis=0)
        new15 = opt.O15[d] + cube[z, ki].sum(axis=0)
        out = float(P.OUT[d])
        pk0, pk1 = max(base15.max(), out), max(new15.max(), out)

        month = P.months[d]
        m = P.months == month
        peaks = self._all_peaks(ki)
        b, n = self.base.copy(), peaks.copy()
        if r.conditions.active():
            b[d], n[d] = pk0, pk1
        month0, month1 = float(b[m].max()), float(n[m].max())
        months = np.unique(P.months[self.te])
        holdout = np.mean([self.base[P.months == x].max() - peaks[P.months == x].max() for x in months])
        # A schedule tuned on a 2018 day hasn't seen 2019, so that's its fair test
        months19 = np.unique(P.months[P.mask(2019)])
        cut_2019 = np.mean([self.base[P.months == x].max() - peaks[P.months == x].max() for x in months19])

        comfort_today, comfort_new = opt.comfort(offs, self.te)
        readings = np.isfinite(T[:, K0])
        new_T = T[z, ki]
        at_risk = [dict(floor=P.zones[j][0], zone=P.zones[j][1], today_C=round(float(T[j, K0]), 1),
                        new_C=round(float(new_T[j]), 1))
                   for j in z if readings[j] and new_T[j] > COMFORT_C and T[j, K0] <= COMFORT_C]
        at_risk.sort(key=lambda x: -x['new_C'])
        g = self.events.get(d)
        starts = {int(j): int(s) for j, s in zip(g.j, g.start_min)} if g is not None else {}
        log = [dict(floor=P.zones[j][0], zone=P.zones[j][1], offset=offs[j],
                    today_min=starts.get(j), new_min=(starts[j] + offs[j]) if j in starts else None)
               for j in z if j in starts]
        log.sort(key=lambda x: (x['new_min'], x['floor'], x['zone']))
        outside = sum(not self.start_lo <= x['new_min'] <= self.start_hi for x in log)
        # Full-day minutes: real AC outside the window, shifted (and any what-if change) inside it
        lo, hi = WINDOW_START - REPLAY_FROM, WINDOW_START - REPLAY_FROM + WINDOW_LEN
        minutes0 = self.full_ac[d, :, REPLAY_FROM:REPLAY_TO].copy()
        minutes = minutes0.copy()
        for j in z:
            minutes0[j, lo:hi] = P.A[d, j, :] + np.repeat(delta[j, K0], 15)
            minutes[j, lo:hi] = shift(P.A[[d], j, :], offs[j])[0] + np.repeat(delta[j, ki[j]], 15)
        day = self.building.loc[r.date]
        tod = day.index.hour * 60 + day.index.minute
        keep = (tod >= REPLAY_FROM) & (tod < REPLAY_TO)
        bins = tod[keep].to_numpy()
        total = day.total_kW.to_numpy()[keep].astype(float)
        full_today, full_new, full_actual = total.copy(), total.copy(), total.copy()
        ix = np.searchsorted(bins, BIN_MINS)
        full_today[ix], full_new[ix] = base15, new15
        full_actual[ix] = opt.O15[d] + opt.real[d][z, K0].sum(axis=0)
        other = np.repeat((day.Light_kW + day.Plug_kW).to_numpy()[keep].astype(float), 15)
        other[lo:hi] = P.O[d]
        am = (bins >= 450) & (bins < 540)       # locked AM window, before TOU billing starts at 09:00
        am_i = np.where(am)[0][full_today[am].argmax()]
        no_sensor_delayed = [dict(floor=P.zones[j][0], zone=P.zones[j][1]) for j in z
                             if not np.isfinite(opt.T[:, j, K0]).any() and offs[j] > 0]
        return dict(
            date=r.date, offsets=offs, bins=bins.tolist(),
            curve_actual=np.round(full_actual, 1).tolist(),
            curve_today=np.round(full_today, 1).tolist(), curve_schedule=np.round(full_new, 1).tolist(),
            morning_peak=round(float(full_today[am_i]), 1), morning_peak_bin=int(bins[am_i]),
            peak_today=round(float(pk0), 1), peak_schedule=round(float(pk1), 1),
            peak_bin_today=int(BIN_MINS[base15.argmax()]), peak_bin_schedule=int(BIN_MINS[new15.argmax()]),
            peak_elsewhere_kW=round(out, 1), peak_floor_binds=bool(out >= new15.max()),
            month=str(month), month_peak_today=round(month0, 1), month_peak_schedule=round(month1, 1),
            baht_month=round((month0 - month1) * DEMAND_BAHT_PER_KW),
            holdout_avg_cut=round(float(holdout), 1), cut_2019=round(float(cut_2019), 1),
            kwh_steady=round(float(-sum(o * P.steady[j] for j, o in enumerate(offs)) / 60), 1),
            kwh_model=round(float(opt.kwh_ml[d][z, ki].sum()), 1),
            comfort_day=dict(readings=int(readings.sum()), today=int((T[readings, K0] <= COMFORT_C).sum()),
                             schedule=int((new_T[readings] <= COMFORT_C).sum())),
            comfort_holdout=dict(today=round(float(comfort_today), 1), schedule=round(float(comfort_new), 1)),
            at_risk=at_risk, log=log, starts_outside_range=outside, no_sensor_delayed=no_sensor_delayed,
            minutes_today=np.round(np.maximum(minutes0, 0), 1).tolist(),
            minutes_schedule=np.round(np.maximum(minutes, 0), 1).tolist(),
            other_minutes=np.round(other, 1).tolist(), conditions_used=self._conditions(d, r.conditions))

    def suggest(self, r):
        """Lowest peak for this day and these inputs, with kWh and comfort no worse than today."""
        d = self._day(r.date)
        cube, T, _ = self._day_cubes(d, r.conditions)
        steady, O, out = self.P.steady, self.opt.O15[d], float(self.P.OUT[d])
        ok = T <= COMFORT_C
        comfort0 = ok[:, K0].sum()
        kw = np.array([[-o * steady[j] / 60 for o in OFFSETS] for j in range(self.Z)])
        abs_off = np.abs(np.array(OFFSETS))
        z = np.arange(self.Z)

        def score(st):
            peak = max((O + cube[z, st].sum(axis=0)).max(), out)
            bad = max(0.0, kw[z, st].sum()) + max(0, comfort0 - ok[z, st].sum())
            return peak + 1e3 * bad + 0.01 * abs_off[st].sum()     # no needless moves

        rng = np.random.default_rng(1)
        starts = [np.full(self.Z, K0)] + [rng.integers(0, len(OFFSETS), self.Z) for _ in range(12)]
        best, best_v = starts[0], score(starts[0])
        for st in starts:
            st, v, improved = st.copy(), score(st), True
            while improved:
                improved = False
                for j in z:
                    for k in range(len(OFFSETS)):
                        t = st.copy()
                        t[j] = k
                        vt = score(t)
                        if vt < v - 0.01:
                            st, v, improved = t, vt, True
            if v < best_v:
                best, best_v = st, v
        r.offsets = [OFFSETS[k] for k in best]
        return self.simulate(r)

    def _heat_cubes(self, step):
        """Every 2018 day with outdoor temp raised: kW cube (D,Z,K,T) and comfort temp (D,Z,K)."""
        with self.heat_lock:
            if step not in self.heat:
                c = Conditions(outdoor_delta_C=step)
                pairs = [self._day_cubes(d, c)[:2] for d in np.where(self.te)[0]]
                self.heat[step] = (np.stack([p[0] for p in pairs]), np.stack([p[1] for p in pairs]))
            return self.heat[step]

    def yearly(self, r):
        if r.outdoor_delta_C not in HEAT_STEPS or len(r.offsets) != self.Z or any(o not in OFFSETS for o in r.offsets):
            raise HTTPException(422, 'Use 0, 1 or 2 degrees and an offset for each zone')
        P, opt = self.P, self.opt
        te = np.where(self.te)[0]
        cube, T = self._heat_cubes(r.outdoor_delta_C)
        ki = np.array([OFFSETS.index(o) for o in r.offsets])
        z = np.arange(self.Z)
        O, out = opt.O15[te], P.OUT[te]
        base_te = np.maximum((O + cube[:, z, K0].sum(axis=1)).max(axis=1), out)
        new_te = np.maximum((O + cube[:, z, ki].sum(axis=1)).max(axis=1), out)
        base, new = self.base.copy(), self.base.copy()
        base[te], new[te] = base_te, new_te
        boot = bootstrap_cut(P, new, self.te, base=base)
        months = []
        for m in np.unique(P.months[te]):
            i = P.months[te] == m
            months.append(dict(month=str(m), today=round(float(base_te[i].max()), 1), schedule=round(float(new_te[i].max()), 1)))
        cut = float(np.mean([base_te[P.months[te] == x['month']].max() - new_te[P.months[te] == x['month']].max() for x in months]))
        lo, hi = np.percentile(boot, [2.5, 97.5])
        readings = np.isfinite(T[:, :, K0])
        now = (T[:, :, K0] <= COMFORT_C).sum()
        then = (T[:, z, ki] <= COMFORT_C).sum()
        year = DEMAND_BAHT_PER_KW * 12
        return dict(outdoor_delta_C=r.outdoor_delta_C, cut=round(cut, 1), cut_lo=round(float(lo), 1), cut_hi=round(float(hi), 1),
                    baht=round(cut * year), baht_lo=round(float(lo) * year), baht_hi=round(float(hi) * year), months=months,
                    comfort_today=round(100 * float(now) / int(readings.sum()), 1),
                    comfort_schedule=round(100 * float(then) / int(readings.sum()), 1), rate=DEMAND_BAHT_PER_KW)

    def _day(self, date):
        if date not in self.d_ix or not self.te[self.d_ix[date]]:
            raise HTTPException(404, 'Pick a 2018 holdout working day')
        return self.d_ix[date]

    def _conditions(self, d, c):
        g = self.events.get(d)
        if g is None:
            return None
        e = self._edit(g, c)
        return dict(outdoor_C=round(float(e.out_T.mean()), 1), indoor_C=round(float(e.T_start.mean()), 1),
                    load_kW=round(float(e.morning_kW.sum()), 0))

    def init(self):
        P, te = self.P, np.where(self.te)[0]
        days = []
        for d in te:
            m = P.months == P.months[d]
            days.append(dict(date=str(P.days[d].date()), label=P.days[d].strftime('%a %d %b %Y'), month=str(P.months[d]),
                             peak=round(float(self.base[d]), 1), month_peak=bool(self.base[d] >= self.base[m].max()),
                             readings=int(np.isfinite(self.opt.T[d, :, K0]).sum()),
                             sunrise=int(self.sun.loc[str(P.days[d].date()), 'sunrise_min']),
                             sunset=int(self.sun.loc[str(P.days[d].date()), 'sunset_min'])))
        # Open on a typical month rather than the best one: the monthly-peak day whose cut
        # under the recommended schedule is closest to the 2018 average
        rec = next(x for x in self.schedules if x['label'] == 'Recommended')
        peaks = self._all_peaks(np.array([OFFSETS.index(o) for o in rec['offsets']]))
        cuts = {m: self.base[P.months == m].max() - peaks[P.months == m].max() for m in np.unique(P.months[te])}
        tops = [x for x in days if x['month_peak'] and x['readings'] >= 8] or days
        default = min(tops, key=lambda x: abs(cuts[x['month']] - np.mean(list(cuts.values()))))
        sensor = np.isfinite(self.opt.T[:, :, K0]).any(axis=0)
        return dict(days=days, default_date=default['date'], schedules=self.schedules, replay_from=REPLAY_FROM, replay_to=REPLAY_TO,
                    zones=[dict(floor=f, zone=z, rated_kW=round(float(self.rated[j]), 1), sensor=bool(sensor[j]))
                           for j, (f, z) in enumerate(P.zones)],
                    demand_baht_per_kW=DEMAND_BAHT_PER_KW, start_range=[int(self.start_lo), int(self.start_hi)])


console = Console()
app = FastAPI(title='Chamchuri 5 restart console')
app.get('/api/init')(console.init)


@app.post('/api/simulate')
def simulate(r: Request):
    return clean(console.simulate(r))


@app.post('/api/suggest')
def suggest(r: Request):
    return clean(console.suggest(r))


@app.post('/api/yearly')
def yearly(r: YearlyRequest):
    return clean(console.yearly(r))


# Fill the hotter-year figures in the background so that page opens quickly
threading.Thread(target=lambda: [console._heat_cubes(h) for h in HEAT_STEPS], daemon=True).start()

dist = Path(__file__).parent / 'web' / 'dist'
if dist.exists():
    app.mount('/', StaticFiles(directory=dist, html=True), name='web')

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8000)
