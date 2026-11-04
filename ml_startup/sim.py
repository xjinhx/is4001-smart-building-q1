"""Time-shift simulator: same input/output format as stagger.py.

in  = each day's zone minute profiles + offsets
out = daily 15-min max kW + kWh change

Dessy can use day_peaks / kwh / billing directly. All numbers match stagger.py;
check_benchmark() below confirms it reproduces the published results.
"""
import numpy as np
import pandas as pd
from config import WORK, HRESULTS, OFFSETS


class Profiles:
    def __init__(self, path=WORK / 'minute_profiles.npz'):
        z = np.load(path)
        self.A, self.O, self.OUT = z['A'], z['O'], z['OUT']
        self.days = pd.to_datetime(z['days'])
        self.zones = [tuple(int(v) for v in r) for r in z['zones']]
        self.n = self.A.shape[2]
        self.months = np.array([str(d.to_period('M')) for d in self.days])
        self.year = np.array(self.days.year)
        # steady kW as in stagger.py: median over 14:15-14:45 (minutes 165-195 of the window)
        self.steady = np.nanmedian(self.A[:, :, 165:195], axis=(0, 2))

    def mask(self, year):
        return self.year == year


def shift(x, k):
    """x: D x n; k > 0 = delay. Edges are held, as in stagger.py."""
    if k == 0:
        return x
    y = np.empty_like(x)
    if k > 0:
        y[:, k:] = x[:, :-k]
        y[:, :k] = x[:, :1]
    else:
        y[:, :k] = x[:, -k:]
        y[:, k:] = x[:, -1:]
    return y


def to_15min(x):
    D, n = x.shape
    return x.reshape(D, n // 15, 15).mean(axis=2)


def day_peaks(P, offs, days=None):
    """Daily billing-relevant peak kW for one schedule. `days` is an optional index or mask."""
    idx = np.arange(len(P.days)) if days is None else np.arange(len(P.days))[days]
    tot = P.O[idx].astype(float).copy()
    for j, k in enumerate(offs):
        tot += shift(P.A[idx, j, :], int(k))
    return np.maximum(to_15min(tot).max(axis=1), P.OUT[idx])


def kwh(P, offs):
    """Rule-based kWh/day change (+ = extra): stagger.py's steady-load approximation."""
    return -sum(int(k) * P.steady[j] for j, k in enumerate(offs)) / 60


def billing(pk, months):
    """Highest daily peak in each month."""
    return pd.Series(pk).groupby(np.asarray(months)).max()


def monthly_cut(P, new_pk, mask):
    base = day_peaks(P, [0] * len(P.zones))
    return billing(base[mask], P.months[mask]) - billing(new_pk[mask], P.months[mask])


def bootstrap_cut(P, pk, mask, n=1000, seed=1, base=None):
    """Mean monthly cut, resampling days within each month (same as stagger.py)."""
    if base is None:
        base = day_peaks(P, [0] * len(P.zones))
    rng = np.random.default_rng(seed)
    idx = np.where(mask)[0]
    groups = [idx[P.months[idx] == m] for m in np.unique(P.months[idx])]
    out = np.empty(n)
    for b in range(n):
        s = []
        for g in groups:
            pick = rng.choice(g, len(g))
            s.append(base[pick].max() - pk[pick].max())
        out[b] = np.mean(s)
    return out


def shift_cube(P):
    """Precompute D x Z x K x T: each zone's clock-aligned 15-min kW under each offset."""
    D, Z, n = P.A.shape
    cube = np.empty((D, Z, len(OFFSETS), n // 15))
    for j in range(Z):
        for i, k in enumerate(OFFSETS):
            cube[:, j, i, :] = to_15min(shift(P.A[:, j, :], k))
    return cube


def check_benchmark():
    P = Profiles()
    S = pd.read_csv(HRESULTS / 'stagger_schedule.csv')
    pub = pd.read_csv(HRESULTS / 'stagger_monthly.csv').set_index('month')
    offs = [int(S[(S.floor == f) & (S.zone == z)].offset_min.iloc[0]) for f, z in P.zones]
    base, pk = day_peaks(P, [0] * len(P.zones)), day_peaks(P, offs)
    r = pd.DataFrame({'today': billing(base, P.months), 'stag': billing(pk, P.months)})
    r['pub_today'], r['pub_stag'] = pub.today_kW, pub.staggered_kW
    r['d_today'], r['d_stag'] = r.today - r.pub_today, r.stag - r.pub_stag
    print(r.round(2).to_string())
    for lab, y in (('2019', 2019), ('2018', 2018)):
        m = P.mask(y)
        b = bootstrap_cut(P, pk, m)
        print(lab, 'cut', round(monthly_cut(P, pk, m).mean(), 2), 'boot mean', round(b.mean(), 1),
              'CI', np.percentile(b, [2.5, 97.5]).round(1))
    print('kWh/day', round(kwh(P, offs), 1))
    assert r.d_today.abs().max() < 0.5 and r.d_stag.abs().max() < 0.5, 'does not match stagger_monthly.csv'
    print('OK: reproduces the published benchmark')


if __name__ == '__main__':
    check_benchmark()
