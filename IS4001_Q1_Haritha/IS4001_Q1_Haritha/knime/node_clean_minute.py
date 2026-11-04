# KNIME Python Script node: "Clean one floor-year file"
# Input 0 : raw CSV table from CSV Reader (Date + all columns as read)
# Input 1 : holidays table (column "date", from holidays_TH_2018_2019.csv)
# Flow variables needed: floor (int), year (int)  -> set in the loop (see guide)
# Output 0: 15-min long table  ts | floor | zone | enduse | value
# Output 1: floor-day quality  date | floor | major_miss_pct | AC_kWh | Light_kWh | Plug_kWh
# Output 2: spike + impute log
import knime.scripting.io as knio
import pandas as pd, numpy as np

f = int(knio.flow_variables['floor']); y = int(knio.flow_variables['year'])
d = knio.input_tables[0].to_pandas()
hol = set(pd.to_datetime(knio.input_tables[1].to_pandas()['date']).dt.date)

# --- 1. parse time, drop broken rows (2019 Floor 6 ends mid-row), full minute grid
d['Date'] = pd.to_datetime(d['Date'].astype(str), errors='coerce')
d = d.dropna(subset=['Date']).drop_duplicates('Date').set_index('Date').sort_index()
full = pd.date_range('2018-07-01' if y == 2018 else '2019-01-01', f'{y}-12-31 23:59', freq='min')
d = d.reindex(full)
d = d[[c for c in d.columns if '(kW)' in c or '(degC)' in c]].apply(pd.to_numeric, errors='coerce').astype('float32')
d.columns = [c.replace('(kW)', '').replace('(degC)', '_T') for c in d.columns]

# --- 2. spikes  +  3. short-gap fill
log = []
for c in d.columns:
    s = d[c]
    if c.endswith('_T'):
        bad = (s < 15) | (s > 40); rule = 'T_range'
    elif '_AC' in c:
        q = s.quantile(.9999); nb = pd.concat([s.shift(1), s.shift(-1)], axis=1).max(axis=1)
        bad = (s > 1.25 * q) & (s > 1.5 * nb); rule = 'AC_isolated'
    else:
        q = s.quantile(.999); rm = s.rolling(31, center=True, min_periods=5).median()
        bad = (s > 3 * q) & (s > 3 * rm + 0.5); rule = 'LP_spike'
    bad = bad.fillna(False)
    if bad.sum(): log.append(dict(year=y, floor=f, col=c, step='spike_' + rule, n=int(bad.sum())))
    d[c] = s.mask(bad).interpolate(limit=30 if c.endswith('_T') else 15, limit_area='inside')

if f == 5 and 'z1_S1_T' in d: d['z1_S1_T'] = np.nan          # faulty sensor (reads 11-15 C)

# --- 4. long gaps in small columns -> typical profile
kw = [c for c in d.columns if not c.endswith('_T')]
major = [c for c in kw if '_AC' in c and d[c].quantile(.999) >= 5]
idx = d.index; mod = idx.hour * 60 + idx.minute
wk = (idx.dayofweek < 5) & ~pd.Index(idx.date).isin(hol)
for c in [c for c in kw if c not in major]:
    miss = d[c].isna()
    if not miss.any(): continue
    s = d[c]
    pm = s[wk].groupby([idx[wk].month, mod[wk]]).median()
    py = s[wk].groupby(mod[wk]).median()
    pw = s[~wk].groupby(mod[~wk]).median()
    fill = np.where(wk, pm.reindex(pd.MultiIndex.from_arrays([idx.month, mod])).values, pw.reindex(mod).values)
    fill = np.where(np.isnan(fill) & wk, py.reindex(mod).values, fill)
    d[c] = s.fillna(pd.Series(fill, index=idx))
    log.append(dict(year=y, floor=f, col=c, step='profile_fill_minutes', n=int(miss.sum())))

# --- 5. floor-day quality
work = d.between_time('06:00', '19:00')
q = pd.DataFrame({'major_miss_pct': work[major].isna().any(axis=1).groupby(work.index.date).mean() * 100})
for eu, pat in (('AC', '_AC'), ('Light', '_Light'), ('Plug', '_Plug')):
    q[eu + '_kWh'] = d[[c for c in kw if pat in c]].sum(axis=1, min_count=1).groupby(d.index.date).sum() / 60
q = q.rename_axis('date').reset_index(); q['date'] = pd.to_datetime(q['date']); q.insert(1, 'floor', f)

# --- 6. 15-min billing intervals (clock aligned, need >=10 of 15 minutes)
g = d.resample('15min').mean(); ok = d.notna().resample('15min').sum() >= 10
out = []
for c in d.columns:
    v = g[c] if c.endswith('_T') else g[c].where(ok[c])
    eu = 'Temp' if c.endswith('_T') else ('AC' if '_AC' in c else c.split('_')[1])
    out.append(pd.DataFrame({'ts': g.index, 'floor': f, 'zone': int(c[1:c.index('_')]), 'enduse': eu, 'unit': c.split('_', 1)[1], 'value': v.values.astype('float64')}))
out = pd.concat(out, ignore_index=True)

knio.output_tables[0] = knio.Table.from_pandas(out)
knio.output_tables[1] = knio.Table.from_pandas(q)
knio.output_tables[2] = knio.Table.from_pandas(pd.DataFrame(log, columns=['year', 'floor', 'col', 'step', 'n']))
