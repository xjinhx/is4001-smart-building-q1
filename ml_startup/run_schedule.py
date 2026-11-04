"""Fit on all of 2019, then score the schedules on the 2018 holdout.
Variants were fixed beforehand from results/variant_cv.csv (2019 only).
Output (same formats as Haritha's stagger_*.csv):
  results/ml_schedule.csv, ml_monthly.csv, ml_bootstrap.csv
  results/schedule_comparison.csv, schedule_offsets_all.csv
"""
import numpy as np
import pandas as pd
from config import RESULTS, HRESULTS, DEMAND_BAHT_PER_KW
from sim import Profiles, day_peaks, kwh, billing, monthly_cut, bootstrap_cut
from optimiser import Optimiser
from models import load_events


def main():
    P = Profiles()
    opt = Optimiser.build(P.mask(2019), P)
    opt.save()
    tr, te = P.mask(2019), P.mask(2018)
    S = pd.read_csv(HRESULTS / 'stagger_schedule.csv')
    rule = [int(S[(S.floor == f) & (S.zone == z)].offset_min.iloc[0]) for f, z in P.zones]
    schedules = {
        'Rule benchmark (Haritha)': rule,
        'Recommended: real profiles + ML constraints': opt.search(tr, 'real', 'top3', 'ml'),
        'Pure ML kW model (delta) + constraints': opt.search(tr, 'delta', 'top3', 'ml'),
        'Real profiles, top-3, no comfort rule': opt.search(tr, 'real', 'top3', 'rule'),
        'Recommended variant limited to +/-5 min': opt.search(tr, 'real', 'top3', 'ml', offsets=(-5, 0, 5)),
    }
    # Exploratory, added after seeing comfort fail on the warmer 2018: not used to claim a win
    for m in (0.5, 1.0, 1.5, 2.0):
        schedules[f'Exploratory: comfort margin {m}C'] = opt.search(tr, 'real', 'top3', 'ml', comfort_margin=m)
    base = day_peaks(P, [0] * len(P.zones))
    # Offsets outside what the data has seen: share of new start times outside the 2019 P1-P99 range
    E = load_events().query("event == 'PM'")
    lo, hi = E[E.set == 'train_2019'].start_min.quantile([.01, .99])
    z_ix = {v: i for i, v in enumerate(P.zones)}
    Ej = np.array([z_ix[(f, z)] for f, z in zip(E.floor, E.zone)])

    rows, boots = [], {}
    rule_pk = day_peaks(P, rule)
    rule_boot = bootstrap_cut(P, rule_pk, te, base=base)
    for name, offs in schedules.items():
        pk = day_peaks(P, offs)
        b = bootstrap_cut(P, pk, te, base=base)
        b19 = bootstrap_cut(P, pk, tr, base=base)
        boots[name] = (b19, b)
        diff = b - rule_boot
        ml_pk = opt.day_peaks_ml(offs)
        new_start = E.start_min.values + np.array(offs)[Ej]
        c19, c18 = opt.comfort(offs, tr), opt.comfort(offs, te)
        rows.append({
            'schedule': name,
            'cut_2019_kW': monthly_cut(P, pk, tr).mean(),
            'cut_2018_kW': monthly_cut(P, pk, te).mean(),
            'cut_2018_CI_lo': np.percentile(b, 2.5), 'cut_2018_CI_hi': np.percentile(b, 97.5),
            'vs_rule_2018_kW': monthly_cut(P, pk, te).mean() - monthly_cut(P, rule_pk, te).mean(),
            'vs_rule_CI_lo': np.percentile(diff, 2.5), 'vs_rule_CI_hi': np.percentile(diff, 97.5),
            'cut_2018_ML_yardstick_kW': (billing(base[te], P.months[te]) - billing(ml_pk[te], P.months[te])).mean(),
            'cut_2019_ML_yardstick_kW': (billing(base[tr], P.months[tr]) - billing(ml_pk[tr], P.months[tr])).mean(),
            'baht_per_month_2018': monthly_cut(P, pk, te).mean() * DEMAND_BAHT_PER_KW,
            'kWh_day_rule': kwh(P, offs),
            'kWh_day_ML_2019': opt.kwh_change(offs, tr), 'kWh_day_ML_2018': opt.kwh_change(offs, te),
            'comfort_2019_today': c19[0], 'comfort_2019_new': c19[1],
            'comfort_2018_today': c18[0], 'comfort_2018_new': c18[1],
            'worst_zone_comfort_change_2019_pp': np.nanmin(opt.comfort_by_zone(offs, tr)),
            'worst_zone_comfort_change_2018_pp': np.nanmin(opt.comfort_by_zone(offs, te)),
            'starts_outside_2019_P1_P99_pct': 100 * np.mean((new_start < lo) | (new_start > hi)),
        })
    C = pd.DataFrame(rows)
    C.to_csv(RESULTS / 'schedule_comparison.csv', index=False)
    print(C.set_index('schedule').T.round(2).to_string())
    print('2019 start P1-P99', lo, hi, 'today outside',
          round(100 * np.mean((E.start_min < lo) | (E.start_min > hi)), 2))

    all_off = pd.DataFrame({'floor': [f for f, _ in P.zones], 'zone': [z for _, z in P.zones]})
    for name, offs in schedules.items():
        all_off[name] = offs
    all_off.to_csv(RESULTS / 'schedule_offsets_all.csv', index=False)
    print(all_off.to_string())

    best = schedules['Recommended: real profiles + ML constraints']
    opt.schedule_table(best).to_csv(RESULTS / 'ml_schedule.csv', index=False)
    pk = day_peaks(P, best)
    res = pd.DataFrame({'today_kW': billing(base, P.months), 'staggered_kW': billing(pk, P.months)})
    res['cut_kW'] = res.today_kW - res.staggered_kW
    res['cut_pct'] = 100 * res.cut_kW / res.today_kW
    res.rename_axis('month').reset_index().to_csv(RESULTS / 'ml_monthly.csv', index=False)
    print(res.round(1).to_string())
    b19, b18 = boots['Recommended: real profiles + ML constraints']
    pd.DataFrame({'train_2019': b19, 'holdout_2018': b18}).to_csv(RESULTS / 'ml_bootstrap.csv', index=False)


if __name__ == '__main__':
    main()
