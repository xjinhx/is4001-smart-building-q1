"""Q2 AC alerts for the console: the SBA Q2 alert method applied to 2019 Floors 3 to 7.

Run from ml_startup (under a minute):
    python q2_alerts/build_alerts.py

The method is unchanged from the Q2 team's compare_floor3_alerts_v3.py (repo emmafoo-2023/SBA_Q2-main),
with the settings frozen in step 4:
  - baseline: the preceding 28 calendar days at the same minute, weekday to weekday and weekend to weekend,
    needing at least 5 weekday or 3 weekend values; April 2019 is the warm-up
  - threshold: the larger of 3 historical standard deviations and 0.5 kW; high and low handled separately
  - readings outside 0-100 kW are dropped, duplicate minutes averaged, missing minutes left missing
  - cases: abnormal minutes in the same direction grouped across gaps of up to 15 minutes with valid data
  - policies compared on the same fully observed 30-minute windows:
    Immediate (first abnormal minute), Continuous20 (20 consecutive), 20of30 (at least 20 of the last 30).
    Continuous30 is computed only to assign each case its review_group, as in the Q2 work.
Periods: May-June development, July-September validation, October-December evaluation.

Writes ml_startup/app/q2/alerts.json (cases, workload, days) and ml_startup/app/q2/minutes_2019.npz
(observed, expected and threshold kW and the abnormal flag per unit and minute, May to December), which the console reads.
Cases are statistical excursions from the baseline, not confirmed faults.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ML = Path(__file__).resolve().parents[1]
PROJECT = ML.parent
OUT = ML / 'app' / 'q2'
INPUTS = Path(__file__).resolve().parent / 'inputs'

FLOORS = (3, 4, 5, 6, 7)
WINDOW_DAYS = 28
SIGMA = 3
MIN_DEVIATION_KW = 0.5
GAP = 15
POLICIES = ['immediate', 'continuous20', 'continuous30', '20of30']
PERIODS = [('development', '2019-05-01', '2019-06-30'),
           ('validation', '2019-07-01', '2019-09-30'),
           ('evaluation', '2019-10-01', '2019-12-31')]
START, KEEP_FROM, END = '2019-04-01', '2019-05-01', '2019-12-31'
SCALE = 100            # minutes file stores kW x 100 as uint16
MISSING = 65535


def runs(mask):
    d = np.diff(np.r_[False, mask, False].astype(int))
    return zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1))


def policies(flag, valid):
    f = pd.Series(flag.astype(int))
    v = pd.Series(valid.astype(int))
    out = {'immediate': (flag, valid)}
    for minutes in (20, 30):
        enough = v.rolling(minutes, min_periods=minutes).sum().eq(minutes).to_numpy()
        out[f'continuous{minutes}'] = (f.rolling(minutes, min_periods=minutes).sum().eq(minutes).to_numpy() & enough,
                                       enough)
    enough = v.rolling(30, min_periods=30).sum().eq(30).to_numpy()
    out['20of30'] = (f.rolling(30, min_periods=30).sum().ge(20).to_numpy() & enough, enough)
    return out


def review_group(alerts):
    if alerts['20of30'] is not None and alerts['continuous20'] is None:
        return 'interruption_tolerance_adds_case'
    if alerts['continuous20'] is not None and alerts['continuous30'] is None:
        return 'shorter_duration_adds_case'
    if alerts['continuous30'] is not None:
        return 'shared_sustained_case'
    return 'immediate_only'


def load_floor(floor):
    df = pd.read_csv(PROJECT / f'2019Floor{floor}.csv')
    dates = pd.to_datetime(df['Date'], errors='coerce')
    keep = dates.notna() & dates.eq(dates.dt.floor('min'))
    cols = [c for c in df if '_AC' in c and '(kW)' in c]
    data = df.loc[keep, cols].apply(pd.to_numeric, errors='coerce')
    data.index = pd.DatetimeIndex(dates[keep])
    data = data.where(data.ge(0) & data.le(100)).groupby(level=0).mean()
    return data.reindex(pd.date_range(START, f'{END} 23:59', freq='min')), cols


def baseline(series, weekend):
    grid = series.to_numpy().reshape(len(weekend), 1440)
    mean = np.full_like(grid, np.nan)
    sd = np.full_like(grid, np.nan)
    for i in range(len(weekend)):
        previous = np.arange(max(0, i - WINDOW_DAYS), i)
        previous = previous[weekend[previous] == weekend[i]]
        if not len(previous):
            continue
        history = pd.DataFrame(grid[previous])
        enough = history.count().to_numpy() >= (3 if weekend[i] else 5)
        mean[i, enough] = history.mean().to_numpy()[enough]
        sd[i, enough] = history.std(ddof=1).to_numpy()[enough]
    return grid.ravel(), mean.ravel(), sd.ravel()


def ratings():
    """Floor 3 step-1 and step-4 review judgements, keyed by (unit, case start)."""
    key = pd.read_csv(INPUTS / 'review_answer_key.csv', parse_dates=['case_start'])
    r1 = pd.read_csv(INPUTS / 'reviewer1_ratings.csv')
    k = key.merge(r1[['review_id', 'reviewer_1_rating', 'reviewer_1_reason']], on='review_id')
    out = {}
    for row in k.itertuples():
        if row.review_group != 'random_no_threshold_excursion':
            out[(row.unit, row.case_start)] = dict(review_id=row.review_id, rating=str(row.reviewer_1_rating).lower(),
                                                   reason=row.reviewer_1_reason)
    v = pd.read_csv(INPUTS / 'review_remaining_cases.csv')
    v['window_start'] = pd.to_datetime(v.window_start, dayfirst=True)
    for row in v.itertuples():
        out[(row.unit, row.window_start)] = dict(review_id=row.review_id, rating=str(row.rating).lower(), reason=row.reason)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    index = pd.date_range(START, f'{END} 23:59', freq='min')
    days = pd.date_range(START, END, freq='D')
    weekend = days.dayofweek >= 5
    k0 = int((index < pd.Timestamp(KEEP_FROM)).sum())
    period_of = np.full(len(index), '', dtype=object)
    for period, s, e in PERIODS:
        period_of[(index >= s) & (index < pd.Timestamp(e) + pd.Timedelta(days=1))] = period
    reviewed = ratings()

    units, obs_all, exp_all, thr_all, flag_all = [], [], [], [], []
    cases, weeks = [], []
    for floor in FLOORS:
        data, cols = load_floor(floor)
        print(f'Floor {floor}: {len(cols)} AC units', flush=True)
        for unit in cols:
            u = len(units)
            zone = int(unit.split('_')[0][1:])
            units.append(dict(id=u, floor=floor, zone=zone, unit=unit.replace('(kW)', ''), column=unit))
            actual, expected, spread = baseline(data[unit], weekend)
            valid = np.isfinite(actual) & np.isfinite(expected) & np.isfinite(spread)
            threshold = np.maximum(SIGMA * spread, MIN_DEVIATION_KW)
            for arr, store in ((actual, obs_all), (expected, exp_all), (np.where(valid, threshold, np.nan), thr_all)):
                a = arr[k0:]
                store.append(np.where(np.isfinite(a), np.clip(np.round(a * SCALE), 0, MISSING - 1), MISSING).astype(np.uint16))
            flag_all.append(np.where(valid & (actual - expected > threshold), 1,
                                     np.where(valid & (expected - actual > threshold), -1, 0))[k0:].astype(np.int8))
            eligible = None
            for direction, flag in (('high', valid & (actual - expected > threshold)),
                                    ('low', valid & (expected - actual > threshold))):
                common = []
                for s, e in runs(flag):
                    if common and s - common[-1][1] <= GAP and valid[common[-1][1]:s].all():
                        common[-1][1] = e
                    else:
                        common.append([s, e])
                definitions = policies(flag, valid)
                eligible = definitions['continuous30'][1]
                first = {}
                for method, (trigger, _) in definitions.items():
                    trigger = trigger & eligible
                    for j, (s, e) in enumerate(common):
                        nxt = common[j + 1][0] if j + 1 < len(common) else len(flag)
                        hits = np.flatnonzero(trigger[s:min(e + 29, nxt, len(flag))])
                        if len(hits):
                            first.setdefault(j, {})[method] = s + int(hits[0])
                for j, alerts in first.items():
                    s, e = common[j]
                    if not period_of[s]:
                        continue            # April warm-up
                    seg = flag[s:e]
                    lengths = [b - a for a, b in runs(seg)]
                    at = {m: alerts.get(m) for m in POLICIES}
                    start = index[s]
                    rev = reviewed.get((unit, start)) if floor == 3 else None
                    cases.append(dict(
                        unit_id=u, floor=floor, zone=zone, unit=unit.replace('(kW)', ''), direction=direction,
                        period=period_of[s], start=str(start), end=str(index[e - 1] + pd.Timedelta(minutes=1)),
                        span=int(e - s), abnormal=int(seg.sum()), longest_run=int(max(lengths, default=0)),
                        mean_observed=round(float(np.nanmean(actual[s:e])), 2),
                        mean_expected=round(float(np.nanmean(expected[s:e])), 2),
                        alerts={m: (str(index[t]) if t is not None else None) for m, t in at.items()},
                        delay={m: (int(t - s) if t is not None else None) for m, t in at.items()},
                        review_group=review_group(at),
                        review=rev, s=int(s - k0), e=int(e - k0), dir=1 if direction == 'high' else -1))
            for period, ps, pe in PERIODS:
                mask = (index >= ps) & (index < pd.Timestamp(pe) + pd.Timedelta(days=1))
                weeks.append(dict(unit_id=u, floor=floor, period=period, weeks=round(int((eligible & mask).sum()) / 10080, 4)))

    cases.sort(key=lambda c: (c['start'], c['floor'], c['unit'], c['direction']))
    for i, c in enumerate(cases):
        c['id'] = i
    np.savez_compressed(OUT / 'minutes_2019.npz', observed=np.stack(obs_all), expected=np.stack(exp_all),
                        threshold=np.stack(thr_all), flag=np.stack(flag_all), start=np.array(KEEP_FROM), scale=np.array(SCALE))
    meta = dict(
        year=2019, start=KEEP_FROM, end=END, scale=SCALE, missing=MISSING,
        periods=[dict(id=p, start=s, end=e) for p, s, e in PERIODS],
        units=units, weeks=weeks, cases=cases,
        settings=dict(window_days=WINDOW_DAYS, sigma=SIGMA, min_deviation_kw=MIN_DEVIATION_KW, gap_minutes=GAP),
        note='Method and frozen settings from the SBA Q2 team (steps 1-4). Cases are excursions from a statistical '
             'baseline, not confirmed faults. Reviews exist for some Floor 3 cases only.')
    (OUT / 'alerts.json').write_text(json.dumps(meta, separators=(',', ':')), encoding='utf-8')
    df = pd.DataFrame(cases)
    for m in ('immediate', 'continuous20', '20of30'):
        df[m] = df.alerts.map(lambda a: a[m] is not None)
    print(df.groupby(['floor', 'period'])[['immediate', 'continuous20', '20of30']].sum())
    print('Saved', OUT / 'alerts.json', 'and', OUT / 'minutes_2019.npz')


if __name__ == '__main__':
    main()
