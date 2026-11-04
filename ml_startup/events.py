"""Complete start-up events for all zone-days.

data/startup_events.csv misses about half of the starts: startups.py needs the
minute just before >3 kW to be <1 kW, but many units run a 1-3 kW fan phase for
a few minutes first. This keeps the locked definition (first minute >3 kW after
>=30 min AM / >=10 min PM below 1 kW) and allows up to MAX_FAN_MIN between.
Output: results/startup_events_complete.csv
"""
import numpy as np
import pandas as pd
from config import DATA, WORK, RESULTS

MAX_FAN_MIN = 15
WINDOWS = {'AM': (300, 630, 30), 'PM': (705, 900, 10)}   # same search windows as startups.py


def detect(x, lo, hi, min_off):
    """Return (start minute, minutes off before) or None. x is one day's AC kW per minute."""
    run, last_end, last_run = 0, -10**6, 0
    for i in range(hi + 1):
        if x[i] < 1:
            run += 1
            if run >= min_off:
                last_end, last_run = i, run
        else:
            run = 0
        if i >= lo and x[i] > 3 and i - last_end <= MAX_FAN_MIN:
            return i, last_run
    return None


def build():
    p = np.load(WORK / 'minute_profiles.npz')
    f = np.load(WORK / 'full_day_minutes.npz')
    AC, T = f['ac'], f['T']
    days = pd.to_datetime(p['days'])
    zones = [tuple(int(v) for v in r) for r in p['zones']]
    wx = pd.read_csv(DATA / 'weather_hourly_openmeteo.csv', parse_dates=['ts']).set_index('ts')
    wx_m = wx[['out_temp_C', 'out_rh_pct']].resample('min').interpolate()
    rows = []
    for d, dt in enumerate(days):
        for j, (fl, z) in enumerate(zones):
            x, t = AC[d, j], T[d, j]
            for ev, (lo, hi, mo) in WINDOWS.items():
                r = detect(x, lo, hi, mo)
                if r is None:
                    continue
                s, off = r
                w = wx_m.loc[dt + pd.Timedelta(minutes=s)]
                pre = (600, 690) if ev == 'PM' else (s - 60, s)     # zone load before the lunch stop
                rows.append(dict(
                    date=dt, set='train_2019' if dt.year == 2019 else 'holdout_2018', floor=fl, zone=z,
                    event=ev, start_min=s, minutes_off=off if ev == 'PM' else np.nan,
                    T_start=t[s - 1], T_drift_10min=t[s - 1] - t[s - 11],
                    T_0800=t[480] if ev == 'AM' else np.nan, T_plus30=t[s + 30] if ev == 'PM' else np.nan,
                    out_T=w.out_temp_C, out_rh=w.out_rh_pct,
                    morning_kW=np.nanmean(x[pre[0]:pre[1]]) if ev == 'PM' else np.nan))
    E = pd.DataFrame(rows)
    E.to_csv(RESULTS / 'startup_events_complete.csv', index=False)
    return E


if __name__ == '__main__':
    E = build()
    print(E.groupby(['event', 'set']).size())
    print('coverage of zone-days', E.groupby('event').size() / (259 * 20))
    print(E.groupby('event').start_min.describe(percentiles=[.05, .95]).round(1).to_string())
    print(E.groupby('event')[['T_start', 'T_0800', 'T_plus30']].apply(lambda g: g.isna().mean()).round(2).to_string())
    for ev, c in (('AM', 'T_0800'), ('PM', 'T_plus30')):
        g = E[E.event == ev].dropna(subset=[c])
        print(ev, c, 'share <=25C', round((g[c] <= 25).mean(), 3), 'n', len(g), g.groupby('set')[c].apply(lambda s: round((s <= 25).mean(), 3)).to_dict())
    print('fleet PM T drift C/10min', E[E.event == 'PM'].T_drift_10min.describe().round(3).to_dict())
