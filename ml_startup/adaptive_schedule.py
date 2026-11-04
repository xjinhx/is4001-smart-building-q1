"""Adaptive schedule. Day types -> schedule per type -> day-ahead forecaster -> 3-way benchmark.

Run after prep.py, events.py and run_schedule.py (needs work/minute_profiles.npz, work/model_cubes.npz):
    python adaptive_schedule.py
Everything is fitted on 2019 only. 2018 Jul-Dec is the holdout and is never used for fitting.

Outputs (results/): day_types.csv, day_type_summary.csv, adaptive_schedules.csv, forecaster_accuracy.csv,
adaptive_benchmark.csv, adaptive_monthly.csv, adaptive_bootstrap.csv
"""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from config import DATA, HRESULTS, RESULTS, OFFSETS, DEMAND_BAHT_PER_KW, SEED
from sim import Profiles, day_peaks, billing, monthly_cut, bootstrap_cut, kwh as rule_kwh
from optimiser import Optimiser, K0

BOOT_N = 1000
MIN_DAYS_PER_TYPE = 15            # a type with fewer 2019 days is too thin for the optimiser
SHAPE_HOURS = (6, 22)             # clustered on 06:00-22:00 building load


# ---------- 1. day features ----------
def day_shapes(P):
    """D x 64 building 15-min kW (06:00-22:00) for every day in P.days, plus daily weather."""
    B = pd.read_csv(DATA / 'building_15min_alldays.csv', parse_dates=['ts']).set_index('ts')
    B['date'] = B.index.normalize()
    h = B.index.hour
    inb = (h >= SHAPE_HOURS[0]) & (h < SHAPE_HOURS[1])
    S = B[inb].pivot_table(index='date', columns=B[inb].index.strftime('%H:%M'), values='total_kW')
    S = S.reindex(P.days)
    wx = B.groupby('date').agg(t_mean=('out_temp_C', 'mean'), t_max=('out_temp_C', 'max'),
                               rh=('out_rh_pct', 'mean'), kw_mean=('total_kW', 'mean'))
    return S, wx, B


def cluster_features(S):
    """Level + shape: raw kW curve (so a heavy day and a light day differ) -> standardised."""
    return S.to_numpy()


def choose_k(X, ks=(3, 4, 5)):
    rows = []
    for k in ks:
        km = KMeans(k, n_init=20, random_state=SEED).fit(X)
        rows.append(dict(k=k, silhouette=silhouette_score(X, km.labels_), inertia=km.inertia_,
                         min_days=int(np.bincount(km.labels_).min())))
    return pd.DataFrame(rows)


def name_types(labels, S, wx, P):
    """Order types by mean daily kW and name them from level + temperature."""
    df = pd.DataFrame({'label': labels, 'kw': S.mean(axis=1).to_numpy(), 't': wx.t_mean.reindex(P.days).to_numpy()})
    order = df.groupby('label').kw.mean().sort_values().index.tolist()
    names = {}
    for rank, lab in enumerate(order):
        t = df[df.label == lab].t.mean()
        lvl = ['Low', 'Mid', 'High', 'Peak', 'Top'][min(rank, 4)] if len(order) > 3 else ['Low', 'Mid', 'High'][rank]
        names[lab] = f'T{rank + 1}-{lvl}-{"hot" if t >= 29.5 else "mild" if t >= 27 else "cool"}'
    return names


# ---------- 2. day-ahead forecaster ----------
def forecaster_features(P, wx, B, day_table):
    """Only what is known the evening before. Weather uses the day's actual (stand-in for a forecast)."""
    d = pd.DataFrame(index=P.days)
    d['dow'] = d.index.dayofweek
    d['month'] = d.index.month
    d['t_max'] = wx.t_max.reindex(d.index).to_numpy()
    d['t_mean'] = wx.t_mean.reindex(d.index).to_numpy()
    d['rh'] = wx.rh.reindex(d.index).to_numpy()
    prev = d.index - pd.Timedelta(days=1)
    d['prev_kw_mean'] = wx.kw_mean.reindex(prev).to_numpy()          # yesterday (any calendar day)
    d['prev_t_max'] = wx.t_max.reindex(prev).to_numpy()
    d['prev_is_working'] = day_table.working.reindex(prev).fillna(False).astype(int).to_numpy()
    nxt_hol = day_table.holiday.reindex(d.index + pd.Timedelta(days=1)).notna().astype(int).to_numpy()
    d['day_before_holiday'] = nxt_hol
    term = day_table.chula_term.reindex(d.index).fillna('none')
    for t in sorted(day_table.chula_term.dropna().unique()):
        d[f'term_{t}'] = (term.to_numpy() == t).astype(int)
    return d


def fit_forecasters(X, y, tr):
    """Time-ordered CV on 2019 picks the model. Returns fitted models dict and the CV table."""
    months = X.index.month
    Xtr, ytr = X[tr], y[tr]
    mtr = months[tr]
    cvrows = {}
    folds = [m for m in sorted(set(mtr)) if m >= 4]                  # expanding window: train < m, test = m
    models = {
        'logistic': lambda: LogisticRegression(max_iter=2000, C=1.0),
        'gboost': lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.08, max_iter=150,
                                                         random_state=SEED),
    }
    for name, mk in models.items():
        acc = []
        for m in folds:
            a, b = mtr < m, mtr == m
            if b.sum() == 0 or len(np.unique(ytr[a])) < 2:
                continue
            Xa, Xb = Xtr[a], Xtr[b]
            mdl = mk()
            if name == 'logistic':
                sc = StandardScaler().fit(Xa.fillna(Xa.median()))
                mdl.fit(sc.transform(Xa.fillna(Xa.median())), ytr[a])
                p = mdl.predict(sc.transform(Xb.fillna(Xa.median())))
            else:
                mdl.fit(Xa, ytr[a])
                p = mdl.predict(Xb)
            acc.append((p == ytr[b]).mean())
        cvrows[name] = float(np.mean(acc))
    # baselines in the same CV
    base_acc = []
    for m in folds:
        a, b = mtr < m, mtr == m
        if b.sum():
            base_acc.append((ytr[b] == pd.Series(ytr[a]).mode()[0]).mean())
    cvrows['majority'] = float(np.mean(base_acc))
    best = max(['logistic', 'gboost'], key=lambda n: cvrows[n])
    mdl = models[best]()
    if best == 'logistic':
        med = Xtr.median()
        sc = StandardScaler().fit(Xtr.fillna(med))
        mdl.fit(sc.transform(Xtr.fillna(med)), ytr)
        predict = lambda Xn: mdl.predict(sc.transform(Xn.fillna(med)))
    else:
        mdl.fit(Xtr, ytr)
        predict = lambda Xn: mdl.predict(Xn)
    return best, predict, cvrows


# ---------- 3. scoring helpers ----------
def pk_mixed(P, sched_by_label, labels):
    """Per-day peak when each day uses the schedule of its (predicted or true) label."""
    cache = {lab: day_peaks(P, offs) for lab, offs in sched_by_label.items()}
    return np.array([cache[l][i] for i, l in enumerate(labels)])


def offs_for_days(P, sched_by_label, labels):
    """D x Z array of offsets, one schedule per day."""
    return np.array([sched_by_label[l] for l in labels])


def comfort_kwh(opt, offs_dz, mask):
    """Comfort share (<=25C at restart+30) and model kWh/day for per-day schedules."""
    ki = np.vectorize(OFFSETS.index)(offs_dz)
    idx = np.where(mask)[0]
    Z = ki.shape[1]
    r = np.arange(Z)
    now, new = opt.T[idx][:, :, K0], np.stack([opt.T[i][r, ki[i]] for i in idx])
    ok = np.isfinite(now)
    c_today = 100 * (now[ok] <= 25).mean()
    c_new = 100 * (new[ok] <= 25).mean()
    kwh_ml = np.mean([opt.kwh_ml[i][r, ki[i]].sum() for i in idx])
    kwh_rule = np.mean([-sum(OFFSETS[ki[i][j]] * opt.P.steady[j] for j in range(Z)) / 60 for i in idx])
    return c_today, c_new, kwh_ml, kwh_rule


def score(P, opt, name, pk, offs_dz, base, te, tr, ref_boot=None):
    b18 = bootstrap_cut(P, pk, te, n=BOOT_N, base=base)
    row = dict(schedule=name,
               cut_2018_kW=monthly_cut(P, pk, te).mean(), cut_2018_CI_lo=np.percentile(b18, 2.5),
               cut_2018_CI_hi=np.percentile(b18, 97.5),
               cut_2019_kW=monthly_cut(P, pk, tr).mean())
    if ref_boot is not None:
        d = b18 - ref_boot
        row.update(vs_fixed_2018_kW=d.mean(), vs_fixed_CI_lo=np.percentile(d, 2.5), vs_fixed_CI_hi=np.percentile(d, 97.5))
    for yr, m in (('2019', tr), ('2018', te)):
        ct, cn, km, kr = comfort_kwh(opt, offs_dz, m)
        row.update({f'comfort_{yr}_today': ct, f'comfort_{yr}_new': cn, f'kWh_day_ML_{yr}': km, f'kWh_day_rule_{yr}': kr})
    row['baht_per_month_2018'] = row['cut_2018_kW'] * DEMAND_BAHT_PER_KW
    return row, b18


def main():
    P = Profiles()
    opt = Optimiser.load()
    tr, te = P.mask(2019), P.mask(2018)
    day_table = pd.read_csv(DATA / 'day_table.csv', parse_dates=['date']).set_index('date')
    S, wx, B = day_shapes(P)
    ok = S.notna().all(axis=1).to_numpy()
    print('days', len(P.days), 'complete shapes', ok.sum(), '| 2019', (tr & ok).sum(), '2018', (te & ok).sum())

    # ---- 1. day types: fit on 2019, assign 2018 by nearest centroid ----
    X = cluster_features(S.fillna(S.mean()))
    sc = StandardScaler(with_std=False).fit(X[tr])          # centre only: keeps kW scale, so level matters
    Xs = sc.transform(X)
    ktab = choose_k(Xs[tr])
    ktab['ok'] = ktab.min_days >= MIN_DAYS_PER_TYPE
    print(ktab.round(3).to_string())
    k = int(ktab[ktab.ok].sort_values('silhouette', ascending=False).k.iloc[0]) if ktab.ok.any() else 3
    km = KMeans(k, n_init=50, random_state=SEED).fit(Xs[tr])
    raw = km.predict(Xs)
    names = name_types(raw[tr], S.to_numpy()[:], wx, P) if False else name_types(raw, S.fillna(S.mean()), wx, P)
    true_lab = np.array([names[r] for r in raw], dtype=object)
    print('chosen k =', k)
    DT = pd.DataFrame({'date': P.days, 'day_type': true_lab, 'set': np.where(tr, 'train_2019', 'holdout_2018'),
                       'mean_kW': S.mean(axis=1).to_numpy(), 't_mean': wx.t_mean.reindex(P.days).to_numpy()})
    DT.to_csv(RESULTS / 'day_types.csv', index=False)
    summ = DT.groupby(['set', 'day_type']).agg(n_days=('date', 'size'), mean_kW=('mean_kW', 'mean'),
                                              t_mean=('t_mean', 'mean')).round(1)
    summ['months'] = DT.assign(m=DT.date.dt.month).groupby(['set', 'day_type']).m.agg(lambda s: s.value_counts().head(3).index.tolist())
    summ.to_csv(RESULTS / 'day_type_summary.csv')
    prof = S[tr].groupby(true_lab[tr]).mean().T          # mean building kW by time of day, 2019 days
    prof.rename_axis('time').to_csv(RESULTS / 'day_type_profiles.csv')
    print(summ.to_string())

    # ---- 2. schedule per day type (the ML optimiser, 2019 days only) ----
    ser = pd.Series(true_lab, index=P.days)
    sched_tbl = opt.schedules_for_day_types(ser)
    sched_tbl.to_csv(RESULTS / 'adaptive_schedules.csv', index=False)
    types = sorted(sched_tbl.day_type.unique())
    by_type = {t: sched_tbl[sched_tbl.day_type == t].offset_min.tolist() for t in types}
    print(sched_tbl.groupby('day_type').agg(n_days=('n_days', 'first'), mean_offset=('offset_min', 'mean')))
    # Days of a type the optimiser never saw in 2019 fall back to "no change"
    for t in set(true_lab) - set(types):
        by_type[t] = [0] * len(P.zones)

    # ---- 3. day-ahead forecaster ----
    F = forecaster_features(P, wx, B, day_table)
    best, predict, cv = fit_forecasters(F, true_lab, tr)
    pred_lab = np.array(predict(F), dtype=object)
    peak_day = np.zeros(len(P.days), bool)                       # the day that sets each month's billing peak
    base = day_peaks(P, [0] * len(P.zones))
    for m in np.unique(P.months):
        idx = np.where(P.months == m)[0]
        peak_day[idx[np.argsort(base[idx])[-3:]]] = True         # top-3 days per month (the optimiser's target)
    acc = []
    for nm, mask in (('2019 train (in-sample)', tr), ('2018 holdout', te)):
        acc.append(dict(set=nm, model=best, accuracy=(pred_lab[mask] == true_lab[mask]).mean(),
                        top3_peak_days_accuracy=(pred_lab[mask & peak_day] == true_lab[mask & peak_day]).mean(),
                        majority_baseline=(true_lab[mask] == pd.Series(true_lab[tr]).mode()[0]).mean(),
                        cv_logistic=cv['logistic'], cv_gboost=cv['gboost'], cv_majority=cv['majority']))
    A = pd.DataFrame(acc)
    A.to_csv(RESULTS / 'forecaster_accuracy.csv', index=False)
    print(A.round(3).to_string())

    # ---- 4. three-way benchmark on the 2018 holdout ----
    S_rule = pd.read_csv(HRESULTS / 'stagger_schedule.csv')
    rule = [int(S_rule[(S_rule.floor == f) & (S_rule.zone == z)].offset_min.iloc[0]) for f, z in P.zones]
    locked = opt.search(tr, 'real', 'top3', 'ml')
    month_sched = {}
    for m in range(1, 13):
        mm = tr & (P.months.astype('U7') != '') & np.array([int(s[5:7]) == m for s in P.months])
        # 2019 only covers Jan-Oct, so Nov/Dec 2018 have no same-month training days: use the all-2019 pick
        month_sched[m] = opt.search(mm, 'real', 'top3', 'ml') if mm.sum() >= 5 else locked
        if mm.sum() < 5:
            print(f'month rule: no 2019 days for month {m}, using the all-2019 locked pick')
    day_month = np.array([int(s[5:7]) for s in P.months])
    n = len(P.days)
    cands = {
        'Fixed: rule-based benchmark': (np.tile(rule, (n, 1)), None),
        'Fixed: locked ML pick': (np.tile(locked, (n, 1)), None),
        'Month rule (best schedule per calendar month, fit 2019)': (np.array([month_sched[m] for m in day_month]), None),
        'ML adaptive (forecast day type)': (offs_for_days(P, by_type, pred_lab), pred_lab),
        'ML adaptive, oracle day type (reference)': (offs_for_days(P, by_type, true_lab), true_lab),
    }
    base_boot = bootstrap_cut(P, day_peaks(P, locked), te, n=BOOT_N, base=base)      # reference = locked ML pick
    rows, boots = [], {}
    for name, (odz, _) in cands.items():
        pk = np.array([day_peaks(P, odz[i].tolist(), np.array([i]))[0] for i in range(n)]) \
            if 'Fixed' not in name else day_peaks(P, odz[0].tolist())
        row, b = score(P, opt, name, pk, odz, base, te, tr, ref_boot=base_boot)
        rows.append(row)
        boots[name] = b
    R = pd.DataFrame(rows)
    R.to_csv(RESULTS / 'adaptive_benchmark.csv', index=False)
    pd.DataFrame(boots).to_csv(RESULTS / 'adaptive_bootstrap.csv', index=False)
    print(R.set_index('schedule').T.round(2).to_string())

    # monthly detail for the adaptive schedule
    name = 'ML adaptive (forecast day type)'
    odz = cands[name][0]
    pk = np.array([day_peaks(P, odz[i].tolist(), np.array([i]))[0] for i in range(n)])
    mo = pd.DataFrame({'today_kW': billing(base, P.months), 'adaptive_kW': billing(pk, P.months)})
    mo['cut_kW'] = mo.today_kW - mo.adaptive_kW
    mo['fixed_locked_kW'] = billing(day_peaks(P, locked), P.months)
    mo['cut_fixed_kW'] = mo.today_kW - mo.fixed_locked_kW
    mo.rename_axis('month').reset_index().to_csv(RESULTS / 'adaptive_monthly.csv', index=False)
    print(mo.round(1).to_string())


if __name__ == '__main__':
    main()
