"""Rebuild the minute profiles stagger.py needs, from the raw CU-BEMS CSVs.

The zip has 15-min data only, so this repeats load.py + clean.py (same spike and
gap rules), then builds the same arrays as stagger.py:
  A   : D x Z x n   zone AC kW per minute in the 11:30-15:30 window
  O   : D x n       non-AC kW (lighting + plug) per minute in the window
  OUT : D           max building 15-min kW in TOU on-peak outside the window
Also saves full-day zone AC and indoor temp minutes for the start-up detector.
Output: work/minute_profiles.npz, work/full_day_minutes.npz, work/zone_attrs.csv
"""
import numpy as np
import pandas as pd
from config import PROJECT, DATA, WORK, FLOORS, YEARS, WINDOW


def load_clean(y, f):
    d = pd.read_csv(PROJECT / f'{y}Floor{f}.csv')
    d['Date'] = pd.to_datetime(d['Date'], errors='coerce')
    d = d.dropna(subset=['Date']).drop_duplicates('Date').set_index('Date').sort_index()
    full = pd.date_range('2018-07-01' if y == 2018 else '2019-01-01', f'{y}-12-31 23:59', freq='min')
    d = d.reindex(full)
    d = d[[c for c in d.columns if '(kW)' in c or '(degC)' in c]].astype('float32')
    d.columns = [c.replace('(kW)', '').replace('(degC)', '_T') for c in d.columns]
    for c in d.columns:                         # clean.py rules, unchanged
        s = d[c]
        if c.endswith('_T'):
            bad = (s < 15) | (s > 40)
        elif '_AC' in c:
            q = s.quantile(.9999)
            nb = pd.concat([s.shift(1), s.shift(-1)], axis=1).max(axis=1)
            bad = (s > 1.25 * q) & (s > 1.5 * nb)
        else:
            q = s.quantile(.999)
            rm = s.rolling(31, center=True, min_periods=5).median()
            bad = (s > 3 * q) & (s > 3 * rm + 0.5)
        s = s.mask(bad.fillna(False))
        d[c] = s.interpolate(limit=30 if c.endswith('_T') else 15, limit_area='inside')
    if f == 5:
        d['z1_S1_T'] = np.nan                   # faulty sensor, excluded in build.py
    return d


def main():
    day = pd.read_csv(DATA / 'day_table.csv', parse_dates=['date']).set_index('date')
    wd = day[day.working].index
    LO, HI = pd.Timedelta(WINDOW[0]), pd.Timedelta(WINDOW[1])
    n = int((HI - LO) / pd.Timedelta('1min'))
    zones, ac, other, attrs, full_ac, full_T = [], {}, {}, [], {}, {}
    for y in YEARS:
        for f in FLOORS:
            d = load_clean(y, f)
            print(y, f, d.shape, flush=True)
            kw = [c for c in d.columns if not c.endswith('_T')]
            for z in sorted({int(c[1]) for c in d.columns if '_AC' in c}):
                if (f, z) not in zones:
                    zones.append((f, z))
                units = [c for c in kw if c.startswith(f'z{z}_AC')]
                s = d[units].sum(axis=1, min_count=1)
                for dt in wd[wd.year == y]:
                    ac[(dt, f, z)] = s.loc[dt + LO:dt + HI - pd.Timedelta('1min')].to_numpy()
                # Nameplate is not in the data, so rated_kW = sum of each unit's P99.9.
                # Main units only for n_units: under 5 kW is a fan/small cassette.
                attrs.append(dict(year=y, floor=f, zone=z,
                                  rated_kW=float(sum(d[u].quantile(.999) for u in units)),
                                  n_units=len(units),
                                  n_main_units=int(sum(d[u].quantile(.999) >= 5 for u in units)),
                                  light_kW=float(d[f'z{z}_Light'].quantile(.999))))
                tcol = f'z{z}_S1_T'
                T = d[tcol] if tcol in d else pd.Series(np.nan, index=d.index)
                for dt in wd[wd.year == y]:
                    e = dt + pd.Timedelta('1439min')
                    full_ac[(dt, f, z)] = s.loc[dt:e].to_numpy()
                    full_T[(dt, f, z)] = T.loc[dt:e].to_numpy()
            nac = d[[c for c in kw if '_AC' not in c]].sum(axis=1, min_count=1)
            for dt in wd[wd.year == y]:
                other[(dt, f)] = nac.loc[dt + LO:dt + HI - pd.Timedelta('1min')].to_numpy()

    # Same OUT as stagger.py, using the published building total
    B = pd.read_csv(DATA / 'building_15min_alldays.csv', parse_dates=['ts'], usecols=['ts', 'total_kW']) \
        .set_index('ts').total_kW
    tod = B.index.hour * 60 + B.index.minute
    tou = (tod >= 540) & (tod < 1320)
    inwin = (tod >= 690) & (tod < 930)
    outside = B[tou & ~inwin].groupby(B[tou & ~inwin].index.normalize()).max()

    days = [dt for dt in wd if all(np.isfinite(ac[(dt, f, z)]).all() for f, z in zones) and dt in outside.index]
    A = np.stack([np.stack([ac[(dt, f, z)] for f, z in zones]) for dt in days]).astype('float32')
    O = np.nan_to_num(np.stack([sum(other[(dt, f)] for f in FLOORS) for dt in days])).astype('float32')
    OUT = outside.reindex(days).to_numpy()
    np.savez_compressed(WORK / 'minute_profiles.npz', A=A, O=O, OUT=OUT,
                        days=np.array([str(x.date()) for x in days]),
                        zones=np.array(zones))
    pd.DataFrame(attrs).to_csv(WORK / 'zone_attrs.csv', index=False)
    np.savez_compressed(WORK / 'full_day_minutes.npz',
                        ac=np.stack([np.stack([full_ac[(dt, f, z)] for f, z in zones]) for dt in days]).astype('float32'),
                        T=np.stack([np.stack([full_T[(dt, f, z)] for f, z in zones]) for dt in days]).astype('float32'))
    print('days', len(days), 'zones', len(zones), 'A', A.shape)


if __name__ == '__main__':
    main()
