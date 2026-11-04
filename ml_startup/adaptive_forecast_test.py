"""Stress test for adaptive_schedule.py: how far does its result depend on the forecast?

adaptive_schedule.py uses each day's actual weather as a stand-in for a forecast. This reruns the
2018 holdout with weather a real forecast could know, with random day types, and with one day type's
schedule on every day. Models and schedules stay fitted on 2019 only. The "same schedule" rows are
hindsight checks, because choosing among them means looking at 2018.

Run after adaptive_schedule.py:
    python adaptive_forecast_test.py
Output: results/adaptive_forecast_test.csv (changes no other results file)
"""
import warnings
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import adaptive_schedule as ad
from config import DATA, RESULTS, SEED
from sim import Profiles, day_peaks, monthly_cut, bootstrap_cut
from optimiser import Optimiser

warnings.filterwarnings('ignore')
WEATHER = ['t_max', 't_mean', 'rh']
NOISE_SD = {'t_max': 1.5, 't_mean': 1.0, 'rh': 6.0}    # assumed forecast errors (degC, degC, % RH)
NOISE_RUNS, RANDOM_RUNS = 30, 200


def main():
    P = Profiles()
    opt = Optimiser.load()
    tr, te = P.mask(2019), P.mask(2018)
    day_table = pd.read_csv(DATA / 'day_table.csv', parse_dates=['date']).set_index('date')
    S, wx, B = ad.day_shapes(P)

    # Same day types and schedules as adaptive_schedule.py
    X = ad.cluster_features(S.fillna(S.mean()))
    Xs = StandardScaler(with_std=False).fit(X[tr]).transform(X)
    ktab = ad.choose_k(Xs[tr])
    ktab['ok'] = ktab.min_days >= ad.MIN_DAYS_PER_TYPE
    k = int(ktab[ktab.ok].sort_values('silhouette', ascending=False).k.iloc[0]) if ktab.ok.any() else 3
    raw = KMeans(k, n_init=50, random_state=SEED).fit(Xs[tr]).predict(Xs)
    names = ad.name_types(raw, S.fillna(S.mean()), wx, P)
    true_lab = np.array([names[r] for r in raw], dtype=object)
    tbl = opt.schedules_for_day_types(pd.Series(true_lab, index=P.days))
    by_type = {t: tbl[tbl.day_type == t].offset_min.tolist() for t in sorted(tbl.day_type.unique())}
    for t in set(true_lab) - set(by_type):
        by_type[t] = [0] * len(P.zones)

    base = day_peaks(P, [0] * len(P.zones))
    locked = opt.search(tr, 'real', 'top3', 'ml')
    fixed_pk = day_peaks(P, locked)
    fixed_cut = monthly_cut(P, fixed_pk, te).mean()
    fixed_boot = bootstrap_cut(P, fixed_pk, te, n=ad.BOOT_N, base=base)
    cache = {t: day_peaks(P, o) for t, o in by_type.items()}
    peak_day = np.zeros(len(P.days), bool)
    for m in np.unique(P.months):
        idx = np.where(P.months == m)[0]
        peak_day[idx[np.argsort(base[idx])[-3:]]] = True

    def peaks(labels):
        return np.array([cache[l][i] for i, l in enumerate(labels)])

    def comfort(labels):
        return ad.comfort_kwh(opt, ad.offs_for_days(P, by_type, labels), te)[1]

    def scored(group, name, labels):
        pk = peaks(labels)
        b = bootstrap_cut(P, pk, te, n=ad.BOOT_N, base=base)
        d = b - fixed_boot
        cut = monthly_cut(P, pk, te).mean()
        return dict(group=group, name=name, cut_kW=cut, cut_lo=np.percentile(b, 2.5), cut_hi=np.percentile(b, 97.5),
                    vs_fixed_kW=cut - fixed_cut, vs_fixed_lo=np.percentile(d, 2.5), vs_fixed_hi=np.percentile(d, 97.5),
                    right_type_pct=100 * (labels[te] == true_lab[te]).mean(),
                    right_type_peak_days_pct=100 * (labels[te & peak_day] == true_lab[te & peak_day]).mean(),
                    comfort_2018_pct=comfort(labels))

    F = ad.forecaster_features(P, wx, B, day_table)
    rows = []
    _, predict, _ = ad.fit_forecasters(F, true_lab, tr)
    rows.append(scored('forecast', 'Actual weather', np.array(predict(F), dtype=object)))

    # Actual weather with assumed forecast errors added, using the same fitted forecaster
    runs = []
    for seed in range(NOISE_RUNS):
        r = np.random.default_rng(seed)
        Fn = F.copy()
        for col, sd in NOISE_SD.items():
            Fn[col] += r.normal(0, sd, len(F))
        labels = np.array(predict(Fn), dtype=object)
        runs.append((monthly_cut(P, peaks(labels), te).mean(), 100 * (labels[te] == true_lab[te]).mean(),
                     100 * (labels[te & peak_day] == true_lab[te & peak_day]).mean(), comfort(labels)))
    runs = np.array(runs)
    rows.append(dict(group='forecast', name='Weather with forecast errors', cut_kW=runs[:, 0].mean(), cut_lo=runs[:, 0].min(),
                     cut_hi=runs[:, 0].max(), vs_fixed_kW=runs[:, 0].mean() - fixed_cut, right_type_pct=runs[:, 1].mean(),
                     right_type_peak_days_pct=runs[:, 2].mean(), comfort_2018_pct=runs[:, 3].mean()))

    # Yesterday's weather stands in for today's, in training and prediction
    Fy = F.copy()
    prev = F.index - pd.Timedelta(days=1)
    Fy['t_max'] = wx.t_max.reindex(prev).to_numpy()
    Fy['t_mean'] = wx.t_mean.reindex(prev).to_numpy()
    Fy['rh'] = wx.rh.reindex(prev).to_numpy()
    _, predict_y, _ = ad.fit_forecasters(Fy, true_lab, tr)
    rows.append(scored('forecast', "Yesterday's weather", np.array(predict_y(Fy), dtype=object)))

    # Only what is known the evening before, with no weather for the day itself
    Fb = F.drop(columns=WEATHER)
    _, predict_b, _ = ad.fit_forecasters(Fb, true_lab, tr)
    rows.append(scored('forecast', 'No weather for the day', np.array(predict_b(Fb), dtype=object)))

    # Day types drawn at random from the 2019 mix
    random_cuts, random_comfort = [], []
    for seed in range(RANDOM_RUNS):
        labels = np.random.default_rng(1000 + seed).choice(true_lab[tr], len(P.days))
        random_cuts.append(monthly_cut(P, peaks(labels), te).mean())
        random_comfort.append(comfort(labels))
    random_cuts = np.array(random_cuts)
    rows.append(dict(group='forecast', name='Random day types', cut_kW=random_cuts.mean(), cut_lo=np.percentile(random_cuts, 2.5),
                     cut_hi=np.percentile(random_cuts, 97.5), vs_fixed_kW=random_cuts.mean() - fixed_cut,
                     comfort_2018_pct=np.mean(random_comfort)))

    # One day type's schedule on every day
    for t in sorted(by_type):
        labels = np.full(len(P.days), t, dtype=object)
        row = scored('hindsight', t, labels)
        row.pop('right_type_pct'), row.pop('right_type_peak_days_pct')
        rows.append(row)

    R = pd.DataFrame(rows)
    R.to_csv(RESULTS / 'adaptive_forecast_test.csv', index=False)
    print(R.round(2).to_string())


if __name__ == '__main__':
    main()
