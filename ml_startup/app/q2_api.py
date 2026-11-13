"""Q2 AC alerts: read-only endpoints for the Alerts, Alert list and Alert workload pages.

Data comes from ml_startup/app/q2/, built by q2_alerts/build_alerts.py from the raw 2019 Floor 3-7 files.
Everything here is real 2019 data; nothing is simulated. Cases are excursions from a statistical baseline,
not confirmed faults.
"""
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

HERE = Path(__file__).resolve().parent / 'q2'
SHOWN = ('immediate', 'continuous20', '20of30')          # the policies the console shows
LABEL = {'immediate': 'Immediate', 'continuous20': 'Continuous20', 'continuous30': 'Continuous30', '20of30': '20of30'}
GROUPS = ('immediate_only', 'interruption_tolerance_adds_case', 'shorter_duration_adds_case', 'shared_sustained_case')
PAD = 45                                                # minutes shown either side of a case

router = APIRouter(prefix='/api/q2')


@lru_cache(maxsize=1)
def data():
    meta = json.loads((HERE / 'alerts.json').read_text(encoding='utf-8'))
    z = np.load(HERE / 'minutes_2019.npz')
    arrays = {k: z[k] for k in ('observed', 'expected', 'threshold', 'flag')}
    start = pd.Timestamp(str(z['start']))
    return meta, arrays, start, float(z['scale'])


def kw(a, scale):
    a = a.astype(float)
    a[a == 65535] = np.nan
    return a / scale


def review_shares(cases):
    """The step 1 reviewer's ratings per review_group (R plots only, as in the step 3 severity estimate)."""
    out = {}
    for g in GROUPS:
        r = [c['review'] for c in cases if c['floor'] == 3 and c['review_group'] == g
             and c['review'] and c['review']['review_id'].startswith('R')]
        out[g] = dict(plots=len(r), investigate=sum(x['rating'] == 'investigate' for x in r),
                      share=round(sum(x['rating'] == 'investigate' for x in r) / len(r), 2) if r else None)
    return out


@lru_cache(maxsize=1)
def summaries():
    meta, _, _, _ = data()
    cases = pd.DataFrame(meta['cases'])
    weeks = pd.DataFrame(meta['weeks'])
    shares = review_shares(meta['cases'])
    periods = {p['id']: (pd.Timestamp(p['start']), pd.Timestamp(p['end'])) for p in meta['periods']}
    periods['all'] = (pd.Timestamp(meta['start']), pd.Timestamp(meta['end']))
    rows = []
    for floor in ['all', 3, 4, 5, 6, 7]:
        for period, (ps, pe) in periods.items():
            c = cases if floor == 'all' else cases[cases.floor == floor]
            w = weeks if floor == 'all' else weeks[weeks.floor == floor]
            if period != 'all':
                c, w = c[c.period == period], w[w.period == period]
            unit_weeks = float(w.weeks.sum())
            cal_weeks = ((pe - ps).days + 1) / 7
            imm = c[c.alerts.map(lambda a: a['immediate'] is not None)]
            for p in SHOWN + ('continuous30',):
                hit = c[c.alerts.map(lambda a: a[p] is not None)]
                delays = hit.delay.map(lambda d: d[p]).astype(float)
                missed = imm[imm.alerts.map(lambda a: a[p] is None)]
                by_group = {g: int((missed.review_group == g).sum()) for g in GROUPS}
                est = sum(n * (shares[g]['share'] or 0) for g, n in by_group.items())
                rows.append(dict(
                    floor=floor, period=period, policy=p, label=LABEL[p], cases=len(hit),
                    unit_weeks=round(unit_weeks, 1), calendar_weeks=round(cal_weeks, 1),
                    cases_per_monitored_week=round(len(hit) / unit_weeks, 2) if unit_weeks else None,
                    alerts_per_week=round(len(hit) / cal_weeks, 2),
                    missed=len(missed), missed_per_monitored_week=round(len(missed) / unit_weeks, 2) if unit_weeks else None,
                    missed_pct=round(100 * len(missed) / len(imm), 1) if len(imm) else None,
                    average_delay=round(float(delays.mean()), 1) if len(hit) else None,
                    total_delay_per_monitored_week=round(float(delays.sum()) / unit_weeks, 1) if unit_weeks else None,
                    missed_by_group=by_group, estimated_missed_worth_investigating=round(est, 1),
                    estimated_per_week=round(est / cal_weeks, 2)))
    return rows, shares


def reviewer_table(cases):
    """Like step 3 Table 2: of the step 1 reviewer's 16 case plots, the ones each policy alerts on, by rating."""
    r = [c for c in cases if c['review'] and c['review']['review_id'].startswith('R')]
    out = []
    for p in SHOWN:
        a = [c for c in r if c['alerts'][p]]
        inv = sum(c['review']['rating'] == 'investigate' for c in a)
        out.append(dict(policy=p, label=LABEL[p], plots=len(a), investigate=inv, monitor=len(a) - inv,
                        investigate_pct=round(100 * inv / len(a), 1) if a else None))
    return out


@router.get('/init')
def init():
    meta, _, _, _ = data()
    rows, shares = summaries()
    days = pd.date_range(meta['start'], meta['end'], freq='D')
    per_day = {d.strftime('%Y-%m-%d'): {p: 0 for p in SHOWN} for d in days}
    for c in meta['cases']:
        for p in SHOWN:
            t = c['alerts'][p]
            if t:
                per_day[t[:10]][p] += 1
    return dict(
        year=meta['year'], start=meta['start'], end=meta['end'], periods=meta['periods'], units=meta['units'],
        settings=meta['settings'], note=meta['note'], policies=[dict(id=p, label=LABEL[p]) for p in SHOWN],
        days=[dict(date=d, label=pd.Timestamp(d).strftime('%a %d %b %Y'), weekend=pd.Timestamp(d).dayofweek >= 5,
                   counts=v) for d, v in per_day.items()],
        workload=rows, shares=shares, reviewer=reviewer_table(meta['cases']))


@router.get('/cases')
def cases():
    """Every case with at least one alert, with the alert time of each shown policy."""
    meta, _, _, _ = data()
    keep = ('id', 'floor', 'zone', 'unit', 'direction', 'period', 'start', 'end', 'span', 'abnormal', 'longest_run',
            'mean_observed', 'mean_expected', 'review_group', 'review')
    return [dict({k: c[k] for k in keep}, alerts={p: c['alerts'][p] for p in SHOWN},
                 delay={p: c['delay'][p] for p in SHOWN}) for c in meta['cases']]


@router.get('/day/{date}')
def day(date: str):
    """Observed kW of every AC unit for each minute of one day, for the replay."""
    meta, arr, start, scale = data()
    try:
        d = pd.Timestamp(date)
    except ValueError:
        raise HTTPException(400, 'Use a date like 2019-10-01')
    i = int((d - start) / pd.Timedelta(minutes=1))
    if d.strftime('%Y-%m-%d') != date or i < 0 or i + 1440 > arr['observed'].shape[1]:
        raise HTTPException(404, f"Pick a day from {meta['start']} to {meta['end']}")
    obs = kw(arr['observed'][:, i:i + 1440], scale)
    return dict(date=date, units=[[None if not np.isfinite(v) else round(float(v), 1) for v in u] for u in obs])


def case_rows(cid):
    meta, arr, start, scale = data()
    if not 0 <= cid < len(meta['cases']):
        raise HTTPException(404, 'No such case')
    c = meta['cases'][cid]
    u, s, e, sign = c['unit_id'], c['s'], c['e'], c['dir']
    lo, hi = max(0, s - PAD), min(arr['observed'].shape[1], e + PAD)
    look = max(0, lo - 1440)                            # history so rolling and consecutive counts are right at the window start
    obs, exp, thr = (kw(arr[k][u, lo:hi], scale) for k in ('observed', 'expected', 'threshold'))
    flags = (arr['flag'][u, look:hi] == sign).astype(int)
    roll = pd.Series(flags).rolling(30, min_periods=1).sum().to_numpy()[lo - look:]
    run, streak = [], 0
    for f in flags:
        streak = streak + 1 if f else 0
        run.append(streak)
    run = run[lo - look:]
    flags = flags[lo - look:]
    alert_min = {p: c['alerts'][p] for p in SHOWN}
    rows = []
    for k in range(hi - lo):
        t = start + pd.Timedelta(minutes=lo + k)
        ts = str(t)
        rows.append(dict(
            time=ts, in_case=bool(s <= lo + k < e),
            observed=None if not np.isfinite(obs[k]) else round(float(obs[k]), 2),
            expected=None if not np.isfinite(exp[k]) else round(float(exp[k]), 2),
            threshold=None if not np.isfinite(thr[k]) else round(float(thr[k]), 2),
            abnormal=bool(flags[k]), abnormal_in_last_30=int(roll[k]), consecutive_abnormal=int(run[k]),
            alerts=[LABEL[p] for p, a in alert_min.items() if a == ts]))
    return c, rows


@router.get('/case/{cid}')
def case(cid: int):
    c, rows = case_rows(cid)
    keep = ('id', 'floor', 'zone', 'unit', 'direction', 'period', 'start', 'end', 'span', 'abnormal', 'longest_run',
            'mean_observed', 'mean_expected', 'review_group', 'review')
    return dict(case=dict({k: c[k] for k in keep}, alerts={p: c['alerts'][p] for p in SHOWN},
                          delay={p: c['delay'][p] for p in SHOWN}), rows=rows, pad=PAD)


@router.get('/case/{cid}/csv')
def case_csv(cid: int):
    c, rows = case_rows(cid)
    df = pd.DataFrame(rows)
    df['alerts'] = df.alerts.map(' '.join)
    df.insert(1, 'unit', f"F{c['floor']} {c['unit']}")
    df.insert(2, 'direction', c['direction'])
    name = f"alert_{c['floor']}_{c['unit']}_{c['start'][:16].replace(' ', '_').replace(':', '')}.csv"
    return Response(df.to_csv(index=False), media_type='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="{name}"'})
