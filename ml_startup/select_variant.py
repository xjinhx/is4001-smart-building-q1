"""Choose the optimiser variant by leave-one-month-out CV on 2019. No 2018 data is used.
Every fold refits the models without the test month, finds a schedule, then scores it on
that month with the real time-shift (the same yardstick as the benchmark).
Output: results/variant_cv.csv
"""
import numpy as np
import pandas as pd
from config import RESULTS
from sim import Profiles, day_peaks
from optimiser import Optimiser

VARIANTS = [('rule (benchmark)', 'real', 'max', 'rule'),
            ('real shift, top-3 days', 'real', 'top3', 'rule'),
            ('real shift, mean day', 'real', 'mean', 'rule'),
            ('ML pred, monthly max', 'pred', 'max', 'ml'),
            ('ML pred, top-3 days', 'pred', 'top3', 'ml'),
            ('ML pred, mean day', 'pred', 'mean', 'ml'),
            ('ML delta, monthly max', 'delta', 'max', 'ml'),
            ('ML delta, top-3 days', 'delta', 'top3', 'ml'),
            ('ML delta, mean day', 'delta', 'mean', 'ml'),
            ('ML delta, top-3, no comfort', 'delta', 'top3', 'kwh'),
            ('real shift, top-3, ML constraints', 'real', 'top3', 'ml'),
            ('real shift, monthly max, ML constraints', 'real', 'max', 'ml')]


def main():
    P = Profiles()
    base = day_peaks(P, [0] * len(P.zones))
    rows = []
    months = np.unique(P.months[P.mask(2019)])
    for m in months:
        test = P.months == m
        train = P.mask(2019) & ~test
        opt = Optimiser.build(train, P)
        for name, cube, obj, con in VARIANTS:
            offs = opt.rule_search(train) if name.startswith('rule') else opt.search(train, cube, obj, con)
            pk = day_peaks(P, offs)
            rows.append(dict(month=m, variant=name, cut_real=base[test].max() - pk[test].max(),
                             cut_ml=base[test].max() - opt.day_peaks_ml(offs, test).max(),
                             comfort_drop=np.subtract(*opt.comfort(offs, train)),
                             kwh_ml=opt.kwh_change(offs, test), offs=' '.join(map(str, offs))))
        print(m, flush=True)
    R = pd.DataFrame(rows)
    R.to_csv(RESULTS / 'variant_cv.csv', index=False)
    s = R.groupby('variant', sort=False).agg(cut_real=('cut_real', 'mean'), worst=('cut_real', 'min'),
                                             cut_ml=('cut_ml', 'mean'), kwh_ml=('kwh_ml', 'mean'),
                                             comfort_drop=('comfort_drop', 'mean'))
    print(s.round(1).to_string())


if __name__ == '__main__':
    main()
