"""Validate the kW and temperature models: 2018 holdout + leave-one-floor-out, MAPE + SHAP.
Output: results/model_accuracy.csv, results/shap_importance.csv, work/shap_*.npz
"""
import numpy as np
import pandas as pd
from config import RESULTS, WORK, FLOORS, COMFORT_C, PM_COMFORT_ELAPSED
from models import (KW_FEATURES, PM_T_FEATURES, AM_T_FEATURES, kw_table, temp_tables, add_attrs, fit_kw,
                    fit_temp, predict, shap_values)


def kw_metrics(y, p, rel):
    y, p, rel = np.asarray(y), np.asarray(p), np.asarray(rel)
    on = (rel >= 15) & (y > 1)           # MAPE on "AC running" intervals; near 0 kW it is meaningless
    return dict(MAPE_pct=100 * np.mean(np.abs(y[on] - p[on]) / y[on]),
                WAPE_pct=100 * np.abs(y - p).sum() / y.sum(),
                RMSE_kW=np.sqrt(np.mean((y - p) ** 2)), n=len(y))


def naive_zone(tr, te):
    """Benchmark 1: that zone's median 2019 profile by minutes since start."""
    m = tr.assign(r=tr.rel_min // 5 * 5).groupby(['floor', 'zone', 'r']).y.median().rename('p').reset_index()
    return te.assign(r=te.rel_min // 5 * 5).merge(m, on=['floor', 'zone', 'r'], how='left').p.fillna(tr.y.median()).values


def naive_fleet(tr, te):
    """Benchmark for an unseen floor: fleet median of kW per rated kW, scaled by the zone's rating."""
    m = tr.assign(r=tr.rel_min // 5 * 5, u=tr.y / tr.rated_kW).groupby('r').u.median().rename('p').reset_index()
    return te.assign(r=te.rel_min // 5 * 5).merge(m, on='r', how='left').p.fillna(0).values * te.rated_kW.values


def temp_metrics(y, p):
    y, p = np.asarray(y), np.asarray(p)
    return dict(MAE_C=np.mean(np.abs(y - p)), bias_C=np.mean(p - y), RMSE_C=np.sqrt(np.mean((y - p) ** 2)),
                comfort_hit_pct=100 * np.mean((y <= COMFORT_C) == (p <= COMFORT_C)), n=len(y))


def main():
    rows = []
    K = add_attrs(kw_table())
    tr, te = K[K.set == 'train_2019'], K[K.set == 'holdout_2018']
    m_kw = fit_kw(tr)
    p = predict(m_kw, te, KW_FEATURES)
    rows.append(dict(model='kW', test='holdout_2018', method='XGBoost', **kw_metrics(te.y, p, te.rel_min)))
    rows.append(dict(model='kW', test='holdout_2018', method='naive zone profile', **kw_metrics(te.y, naive_zone(tr, te), te.rel_min)))
    rows.append(dict(model='kW', test='train_2019 (in-sample)', method='XGBoost', **kw_metrics(tr.y, predict(m_kw, tr, KW_FEATURES), tr.rel_min)))

    # Building-level check on the intervals that matter for billing (zones summed, 13:00-13:30)
    bins = te[te.bin_min.isin([780, 795])].assign(p=p[te.bin_min.isin([780, 795])])
    agg = bins.groupby(['date', 'bin_min'])[['y', 'p']].sum()
    rows.append(dict(model='kW', test='holdout_2018', method='XGBoost, all zones summed, 13:00-13:30',
                     MAPE_pct=100 * np.mean(np.abs(agg.y - agg.p) / agg.y), WAPE_pct=100 * np.abs(agg.y - agg.p).sum() / agg.y.sum(),
                     RMSE_kW=np.sqrt(np.mean((agg.y - agg.p) ** 2)), bias_kW=(agg.p - agg.y).mean(), n=len(agg)))

    # Leave one floor out, on 2019. The unseen floor's attributes come from its 2018 data
    for f in FLOORS:
        a, b = tr[tr.floor != f], add_attrs(tr[tr.floor == f], floor_year={f: 2018})
        pf = predict(fit_kw(a), b, KW_FEATURES)
        rows.append(dict(model='kW', test=f'unseen floor {f}', method='XGBoost', **kw_metrics(b.y, pf, b.rel_min)))
        rows.append(dict(model='kW', test=f'unseen floor {f}', method='naive fleet profile', **kw_metrics(b.y, naive_fleet(a, b), b.rel_min)))

    pm, am = temp_tables()
    pm, am = add_attrs(pm), add_attrs(am)
    for name, tab, feats in (('T +30 min after PM restart', pm, PM_T_FEATURES), ('T at 08:00', am, AM_T_FEATURES)):
        a, b = tab[tab.set == 'train_2019'], tab[tab.set == 'holdout_2018']
        if 'PM' in name:
            b = b[b.elapsed == PM_COMFORT_ELAPSED]
        m = fit_temp(a, feats)
        rows.append(dict(model=name, test='holdout_2018', method='XGBoost (monotone)', **temp_metrics(b.y, predict(m, b, feats))))
        rows.append(dict(model=name, test='holdout_2018', method='naive: T at start', **temp_metrics(b.y, b.T_start.where(b.T_start.notna(), a.y.mean()))))
        for f in FLOORS:
            aa, bb = a[a.floor != f], add_attrs(a[a.floor == f], floor_year={f: 2018})
            if 'PM' in name:
                bb = bb[bb.elapsed == PM_COMFORT_ELAPSED]
            rows.append(dict(model=name, test=f'unseen floor {f}', method='XGBoost (monotone)', **temp_metrics(bb.y, predict(fit_temp(aa, feats), bb, feats))))
        # Temperature response slope at the point the optimiser uses
        if 'PM' in name:
            s = shap_values(m, a[a.elapsed == 30], feats)
            np.savez(WORK / 'shap_pmT.npz', s=s, X=a[a.elapsed == 30][feats].values.astype(float), f=np.array(feats))
    R = pd.DataFrame(rows)
    R.to_csv(RESULTS / 'model_accuracy.csv', index=False)
    print(R.round(2).to_string())

    # SHAP on the holdout (a sample keeps the chart readable)
    samp = te.sample(6000, random_state=1)
    s = shap_values(m_kw, samp, KW_FEATURES)
    np.savez(WORK / 'shap_kw.npz', s=s, X=samp[KW_FEATURES].values.astype(float), f=np.array(KW_FEATURES))
    # Same features among intervals where AC is on, to see what drives kW beyond the on/off shape
    on = te[te.rel_min >= 15].sample(6000, random_state=1)
    s_on = shap_values(m_kw, on, KW_FEATURES)
    imp = pd.DataFrame({'feature': KW_FEATURES, 'mean_abs_shap_kW': np.abs(s).mean(axis=0),
                        'mean_abs_shap_kW_AC_on': np.abs(s_on).mean(axis=0)}).sort_values('mean_abs_shap_kW', ascending=False)
    imp.to_csv(RESULTS / 'shap_importance.csv', index=False)
    print(imp.round(2).to_string())
    print('pct of mean holdout PM-window month-level: month shift check')
    print(te.groupby('month').apply(lambda g: pd.Series(kw_metrics(g.y, predict(m_kw, g, KW_FEATURES), g.rel_min))).round(2).to_string())


if __name__ == '__main__':
    main()
