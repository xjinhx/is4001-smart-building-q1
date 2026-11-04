"""ML stagger optimiser. Keeps stagger.py's format so Dessy can plug it in.

    from optimiser import Optimiser
    opt = Optimiser.load()                 # cached model predictions for every working day
    offs = opt.optimise(mask)              # mask = boolean array over opt.P.days, e.g. one day type
    pk = opt.day_peaks(offs)               # daily 15-min max kW (real profiles time-shifted)
    change = opt.kwh_change(offs, mask)    # kWh/day change
    table = opt.schedule_table(offs)       # same columns as stagger_schedule.csv

Three "cubes" share one search engine. Each is D x Z x K x T: zone 15-min kW per day,
zone, offset and billing interval.
  real  : measured minute profiles time-shifted (stagger.py; no rebound)
  pred  : what the ML model predicts for that offset
  delta : measured kW today + (model at offset k - model at offset 0), which keeps the
          real day-to-day peaks and uses the model only for the effect of the offset
"""
import numpy as np
import pandas as pd
from config import WORK, OFFSETS, COMFORT_C, PM_COMFORT_ELAPSED, SEED
from models import (KW_FEATURES, PM_T_FEATURES, BIN_MINS, REL_LO, REL_HI, kw_table, temp_tables, add_attrs, load_events,
                    fit_kw, fit_temp, predict)
from sim import Profiles, shift_cube, to_15min, kwh as rule_kwh, day_peaks as sim_day_peaks

K0 = OFFSETS.index(0)


def build_model_cubes(P, train_mask):
    """Fit on the days in train_mask, predict every day under every offset.
    Returns pred (D,Z,K,T), comfort temp T' (D,Z,K; NaN = no reading), kWh change (D,Z,K)."""
    train_days = set(P.days[train_mask])
    K = add_attrs(kw_table())
    m_kw = fit_kw(K[K.date.isin(train_days)])
    pm_t, _ = temp_tables()
    pm_t = add_attrs(pm_t)
    m_t = fit_temp(pm_t[pm_t.date.isin(train_days)], PM_T_FEATURES)

    E = add_attrs(load_events().query("event == 'PM'"))
    d_ix = {d: i for i, d in enumerate(P.days)}
    z_ix = {v: i for i, v in enumerate(P.zones)}
    E['d'], E['j'] = E.date.map(d_ix), [z_ix[(f, z)] for f, z in zip(E.floor, E.zone)]
    # Warming while still off, for a delay: fleet median over the 10 min before restart
    drift = float(E.T_drift_10min.median()) / 10
    real = shift_cube(P)
    pred = real.copy()                      # zone-days with no detected start stay as measured

    nk, nt = len(OFFSETS), len(BIN_MINS)
    R = E.loc[E.index.repeat(nk * nt)].copy()
    R['k'] = np.tile(np.repeat(np.arange(nk), nt), len(E))
    R['t'] = np.tile(np.arange(nt), nk * len(E))
    off = np.array(OFFSETS)[R.k]
    raw_rel = BIN_MINS[R.t] - (R.start_min.values + off)
    R['rel_min'] = np.clip(raw_rel, REL_LO, REL_HI)
    R['start_min'] = R.start_min.values + off
    R['minutes_off'] = R.minutes_off.values + off
    R['T_start'] = R.T_start.values + drift * off
    p = np.maximum(predict(m_kw, R, KW_FEATURES), 0)
    ix = (R.d.values, R.j.values, R.k.values, R.t.values)
    raw = np.zeros_like(real)
    raw[ix] = p
    dcube = raw - raw[:, :, [K0], :]
    # Outside the modelled range a zone is off before the restart or steady after it: no effect,
    # and the pred cube keeps the measured kW (e.g. 11:30-11:45, before the lunch stop)
    out = (raw_rel < REL_LO) | (raw_rel > REL_HI)
    dcube[R.d.values[out], R.j.values[out], R.k.values[out], R.t.values[out]] = 0
    pred[ix] = np.where(out, real[R.d.values, R.j.values, K0, R.t.values], p)

    # Comfort at today's restart + 30 min on the clock. A delay k leaves 30-k min of cooling.
    F = E.dropna(subset=['T_plus30'])
    C = F.loc[F.index.repeat(nk)].copy()
    C['k'] = np.tile(np.arange(nk), len(F))
    koff = np.array(OFFSETS)[C.k]
    C['elapsed'] = PM_COMFORT_ELAPSED - koff
    C['minutes_off'] = C.minutes_off.values + koff
    C['T_start'] = C.T_start.values + drift * koff
    tp = predict(m_t, C, PM_T_FEATURES)
    tp0 = np.repeat(tp[C.k.values == K0], nk)
    T = np.full(real.shape[:3], np.nan)
    T[C.d.values, C.j.values, C.k.values] = C.T_plus30.values + tp - tp0
    return pred, dcube, T, drift


class Optimiser:
    def __init__(self, P, real, pred, dcube, T):
        self.P, self.real, self.pred, self.dcube, self.T = P, real, pred, dcube, T
        self.O15 = to_15min(P.O.astype(float))
        self.today = real[:, :, K0, :]
        self.delta_cube = self.today[:, :, None, :] + dcube
        # kWh/day per zone-day-offset, from the model's change over the window
        self.kwh_ml = dcube.sum(axis=3) / 4
        self.fl = sorted({f for f, _ in P.zones})

    @classmethod
    def build(cls, train_mask=None, P=None):
        P = P or Profiles()
        train_mask = P.mask(2019) if train_mask is None else train_mask
        pred, dcube, T, _ = build_model_cubes(P, train_mask)
        return cls(P, shift_cube(P), pred, dcube, T)

    @classmethod
    def load(cls, path=WORK / 'model_cubes.npz'):
        z = np.load(path)
        P = Profiles()
        return cls(P, shift_cube(P), z['pred'], z['dcube'], z['T'])

    def save(self, path=WORK / 'model_cubes.npz'):
        np.savez_compressed(path, pred=self.pred.astype('float32'), dcube=self.dcube.astype('float32'),
                            T=self.T.astype('float32'))

    def cube(self, name):
        return dict(real=self.real, pred=self.pred, delta=self.delta_cube)[name]

    def _obj_fn(self, mask, objective):
        idx = np.where(mask)[0]
        groups = [np.where(self.P.months[idx] == m)[0] for m in np.unique(self.P.months[idx])]
        out = self.P.OUT[idx]

        def f(total):
            d = np.maximum(total.max(axis=1), out)
            if objective == 'max':
                return np.mean([d[g].max() for g in groups])
            if objective == 'top3':
                return np.mean([np.sort(d[g])[-3:].mean() for g in groups])
            return d.mean()
        return f

    def search(self, mask, cube='real', objective='top3', constraints='ml', offsets=OFFSETS, starts=(), n_random=15,
               seed=SEED, comfort_margin=0.0):
        """Multi-start coordinate descent. constraints: 'rule' = stagger.py's kWh rule only;
        'kwh' adds the model's kWh; 'ml' adds the comfort rule as well. comfort_margin applies the
        comfort rule at 25C - margin, for a schedule that holds up in a warmer year."""
        idx = np.where(mask)[0]
        c = self.cube(cube)[idx]
        Z = c.shape[1]
        allowed = [OFFSETS.index(o) for o in offsets]
        base = self.O15[idx]
        f = self._obj_fn(mask, objective)
        steady = self.P.steady
        kw_rule = np.array([[-OFFSETS[k] * steady[j] / 60 for k in range(len(OFFSETS))] for j in range(Z)])
        kw_ml = self.kwh_ml[idx].mean(axis=0)
        Ti = self.T[idx]
        ok = (Ti <= COMFORT_C - comfort_margin).sum(axis=0).astype(float)
        comfort_today = ok[:, K0].sum()

        def penalty(state):
            r = np.arange(Z)
            p = max(0.0, kw_rule[r, state].sum())
            if constraints in ('kwh', 'ml'):
                p += max(0.0, kw_ml[r, state].sum())
            if constraints == 'ml':
                p += max(0.0, comfort_today - ok[r, state].sum())
            return 1e3 * p

        rng = np.random.default_rng(seed)
        inits = [np.full(Z, K0)] + [np.array([OFFSETS.index(o) for o in s]) for s in starts]
        inits += [rng.choice(allowed, Z) for _ in range(n_random)]
        best, best_v = None, np.inf
        r = np.arange(Z)
        for s in inits:
            state = s.copy()
            total = base + c[:, r, state, :].sum(axis=1)
            v = f(total) + penalty(state)
            improved = True
            while improved:
                improved = False
                for j in range(Z):
                    for k in allowed:
                        if k == state[j]:
                            continue
                        t2 = total + c[:, j, k, :] - c[:, j, state[j], :]
                        s2 = state.copy()
                        s2[j] = k
                        v2 = f(t2) + penalty(s2)
                        if v2 < v - 0.05:
                            total, state, v, improved = t2, s2, v2, True
            if penalty(state) == 0 and v < best_v:
                best, best_v = state.copy(), v
        if best is None:
            best = np.full(Z, K0)
        return [OFFSETS[k] for k in best]

    def rule_search(self, mask):
        """Haritha's method on any set of days: floor grid, then zone-level local search."""
        import itertools
        idx = np.where(mask)[0]
        Z = len(self.P.zones)
        c, base = self.real[idx], self.O15[idx]
        f = self._obj_fn(mask, 'max')
        r = np.arange(Z)
        floors = np.array([self.fl.index(fl) for fl, _ in self.P.zones])
        best_v, best = np.inf, None
        for combo in itertools.product(range(len(OFFSETS)), repeat=len(self.fl)):
            st = np.array(combo)[floors]
            if rule_kwh(self.P, [OFFSETS[k] for k in st]) > 0:
                continue
            v = f(base + c[:, r, st, :].sum(axis=1))
            if v < best_v:
                best_v, best = v, st
        improved = True
        cur = best.copy()
        while improved:
            improved = False
            for j in range(Z):
                for k in range(len(OFFSETS)):
                    t = cur.copy()
                    t[j] = k
                    if rule_kwh(self.P, [OFFSETS[i] for i in t]) > 0:
                        continue
                    v = f(base + c[:, r, t, :].sum(axis=1))
                    if v < best_v - 0.05:
                        cur, best_v, improved = t, v, True
        return [OFFSETS[k] for k in cur]

    # --- stagger.py format ---
    def optimise(self, mask=None, **kw):
        """Best schedule for the given days. Defaults are the variant chosen by CV on 2019."""
        mask = self.P.mask(2019) if mask is None else mask
        return self.search(mask, **kw)

    def day_peaks(self, offs, mask=None):
        return sim_day_peaks(self.P, offs, mask)

    def day_peaks_ml(self, offs, mask=None):
        """Same, measured today + the model's offset effect (includes any rebound)."""
        mask = np.ones(len(self.P.days), bool) if mask is None else mask
        idx = np.where(mask)[0]
        ki = np.array([OFFSETS.index(o) for o in offs])
        c = self.delta_cube[idx][:, np.arange(len(ki)), ki, :]
        return np.maximum((self.O15[idx] + c.sum(axis=1)).max(axis=1), self.P.OUT[idx])

    def kwh_change(self, offs, mask=None):
        """Mean kWh/day change from the model (+ = more). Rule version: sim.kwh."""
        mask = np.ones(len(self.P.days), bool) if mask is None else mask
        ki = np.array([OFFSETS.index(o) for o in offs])
        return float(self.kwh_ml[mask][:, np.arange(len(ki)), ki].sum(axis=1).mean())

    def comfort(self, offs, mask=None):
        """Share of zone-days <=25C at today's restart + 30 min, today vs this schedule (%)."""
        mask = np.ones(len(self.P.days), bool) if mask is None else mask
        ki = np.array([OFFSETS.index(o) for o in offs])
        Ti = self.T[mask]
        new = Ti[:, np.arange(len(ki)), ki]
        now = Ti[:, :, K0]
        n = np.isfinite(now).sum()
        return 100 * (now <= COMFORT_C).sum() / n, 100 * (new <= COMFORT_C).sum() / n

    def comfort_by_zone(self, offs, mask=None):
        """Percentage-point change in each zone's <=25C share (NaN = no working sensor)."""
        mask = np.ones(len(self.P.days), bool) if mask is None else mask
        Ti = self.T[mask]
        out = np.full(len(offs), np.nan)
        for j, o in enumerate(offs):
            n = np.isfinite(Ti[:, j, K0]).sum()
            if n:
                out[j] = 100 * ((Ti[:, j, OFFSETS.index(o)] <= COMFORT_C).sum() - (Ti[:, j, K0] <= COMFORT_C).sum()) / n
        return out

    def schedules_for_day_types(self, day_types, **kw):
        """Dessy's hook. day_types: Series of labels indexed by date. Fits on 2019 days only,
        and returns one row per day type x zone, in stagger_schedule.csv's columns."""
        day_types = day_types.copy()
        day_types.index = pd.to_datetime(day_types.index)
        labels = np.array(pd.Series(self.P.days).map(day_types), dtype=object)
        out = []
        for lab in pd.unique(labels[pd.notna(labels)]):
            mask = (labels == lab) & self.P.mask(2019)
            if mask.sum():
                out.append(self.schedule_table(self.search(mask, **kw)).assign(day_type=lab, n_days=int(mask.sum())))
        return pd.concat(out, ignore_index=True)

    def schedule_table(self, offs):
        return pd.DataFrame({'floor': [f for f, _ in self.P.zones], 'zone': [z for _, z in self.P.zones],
                             'offset_min': list(offs), 'steady_kW': self.P.steady.round(1)})
