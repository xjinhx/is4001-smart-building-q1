# IS4001 Q1: ML start-up model + stagger optimiser (Jinhong)

Builds on Haritha's `IS4001_Q1_Haritha` (definitions and cleaning unchanged). `python run_all.py` rebuilds everything from the raw CSVs in about 5 minutes.

## Result

**On the 2018 holdout, the ML schedule ties the rule-based benchmark on peak cut, and no ±10 min schedule meets the comfort rule on 2018.** By the rule the team agreed, we can't say ML beats the benchmark.

| Schedule (fitted on 2019) | Cut 2019 (kW) | **Cut 2018 (kW)** | 95% CI | vs rule (kW), 95% CI | ≤25°C 2019 (today 98.7%) | ≤25°C 2018 (today 81.0%) |
|---|---|---|---|---|---|---|
| Rule benchmark (Haritha) | 34.9 | **15.6** | 13.7–20.5 | – | 97.1% | 76.5% |
| **Locked pick:** real profiles + ML comfort and kWh checks | 31.1 | **16.3** | 11.2–21.8 | +0.6 (−5.7 to +4.9) | 98.9% | 74.9% |
| Pure ML kW model + the same checks | 32.0 | **19.9** | 14.8–24.3 | +4.3 (−2.0 to +7.6) | 98.7% | 73.9% |
| Real profiles, top-3-days objective, no comfort rule (no ML) | 34.8 | **23.4** | 20.9–28.3 | +7.7 (+6.4 to +9.2) | 97.1% | 70.6% |
| Locked pick limited to ±5 min | 9.9 | **7.5** | 2.9–9.2 | −8.2 (−14.7 to −7.1) | 98.7% | 80.2% |

All cuts use the same yardstick as the benchmark: real minute profiles, time-shifted. 16.3 kW is about 2,160 baht/month (indicative). Full table: `results/schedule_comparison.csv`.

What this means:

- **Peak:** the biggest gain came from a better objective, not from ML. Optimising the top 3 days per month instead of the single worst day generalises better (23.4 vs 15.6 kW), but it gives up the most comfort.
- **Comfort:** the ML comfort check is where ML adds something. It shows the rule schedule isn't quite "no worse than today" on 2019 (98.7% to 97.1%, and one zone loses 11 points), and the locked pick fixes that on 2019. On 2018 it doesn't hold: the 2018 sensors read about 2.8°C warmer at +30 min (24.0 vs 21.2°C), so many zones sit just under 25°C and a +10 min delay (+1 to +1.5°C on large zones) tips them over. A comfort margin of up to 2°C didn't fix this (`Exploratory` rows, added after seeing the holdout, so not used for any claim).
- **Rebound:** SHAP shows minutes off (0.09 kW) and start time (0.14 kW) barely move kW, which backs Haritha's finding 4: the peak comes from synchronised starts, not catch-up cooling. Time-shifting is a fair approximation.
- **kWh:** every schedule passes (rule estimate about 0, model about −11 kWh/day on 2018). Treat this as "no increase", not a saving.

## Models

Trained on 2019 only. XGBoost was chosen over LightGBM (5-fold CV by date: 14.5% vs 14.9% MAPE at similar settings) and gives exact SHAP values without the `shap` package.

| Model | Test | Result | Naive comparison |
|---|---|---|---|
| Zone 15-min kW after PM restart | 2018 holdout | MAPE 24.1%, WAPE 14.3% | 27.6%, 18.3% |
| | Unseen floors 3/4/5/6/7 | MAPE 19 / 17 / 16 / 53 / 16% | 28 / 28 / 25 / 106 / 41% |
| | All zones summed, 13:00–13:30, 2018 | MAPE 7.1%, bias −25 kW | – |
| Zone temp 30 min after PM restart | 2018 holdout | MAE 1.14°C, bias −1.09°C | 3.75°C (temp at start) |
| | Unseen floors (mean) | MAE 1.12°C | – |
| Zone temp at 08:00 | 2018 holdout | MAE 0.81°C, bias −0.72°C | 2.24°C (temp at start) |
| | Unseen floors (mean) | MAE 0.87°C | – |

- MAPE counts AC-on intervals only (≥15 min after start, >1 kW), because it is meaningless near 0 kW. Floor 6 is high because its small loads inflate MAPE (WAPE 20%).
- Temperature models get the ≤25°C call right 82% (PM) and 77% (08:00) of the time on 2018, barely above always guessing the majority class (81%, 75%). So comfort checks use **measured temp + the model's change for that offset**, not the model's absolute temp.

Design choices:

- **Features:** minutes since start, start time, minutes off, indoor and outdoor temp, RH, month, day of week, zone kW before lunch, rated kW, unit count, lighting size. No floor or zone IDs. `morning_kW` wasn't in the brief; it cut CV MAPE from 18.8% to 15.3% and is known by restart time.
- **Rated kW** isn't in the data, so it's the sum of each unit's P99.9. To avoid leakage, the 2018 test uses 2019 values and an unseen floor uses its own 2018 values.
- **Comfort model monotonicity:** temp can only fall with more cooling time and rise with warmer start or outdoor temp, so the optimiser can't exploit noise.
- **Missing indoor temp** (34% of events): XGBoost handles it natively. Comfort stats use only zone-days with a reading.

## How the schedule was chosen

Leave-one-month-out CV on 2019 compared 12 variants (`results/variant_cv.csv`), refitting models each fold. The pick was fixed before scoring 2018: the top CV variant that meets all constraints (31.8 kW; rule 32.0 kW). Offsets are {−10, −5, 0, +5, +10} min per zone. Constraints: comfort share no lower than today, and kWh not higher on both the rule and model estimates. `sim.py` reproduces `stagger_monthly.csv` to within 0.01 kW, and `rule_search` reproduces Haritha's schedule exactly.

## Limits to say out loud

1. **Nobody has run a staggered start here.** Zones on a floor start within about 3 min of each other, so all savings are simulated. Zones are assumed independent. Recommend a pilot before quoting baht.
2. **±10 min goes beyond the data.** 61% of the locked pick's new start times fall outside the 2019 P1–P99 range (12:56–13:08), against 3% today; ±5 min gives 24%.
3. **The 08:00 model doesn't constrain anything.** The schedule only moves the PM restart (the AM start never bills), so 08:00 is unaffected. The comfort rule that binds is +30 min after restart, so I added that model.
4. **F5 Z1 has no working sensor**, yet the pick delays it +10 min. Its comfort is unchecked.
5. **The 2018 temperature shift is unexplained** (setpoints or sensors?), and rests on 888 readings. Single-zone 2018 changes are noisy: F4 Z1 loses 83 points on 41 readings.

## For Haritha

`data/startup_events.csv` misses about 49% of zone-day starts, and almost all of F4 Z2, F5 Z2, F6 Z5 and F7 Z5 (2019). `startups.py` needs the minute right before >3 kW to be <1 kW, but many units run a 1–3 kW fan phase first. `results/startup_events_complete.csv` keeps the locked definition but allows up to 15 min of fan phase: it covers 98% of PM and 99.7% of AM zone-days and agrees with the original on 99.2% of shared starts. Comfort shares barely change (64%, 94%), but the surge ratios and start-time spread in findings 3 and 4 came from the partial set and should be rechecked. Her files are untouched.

## For Dessy

```python
from optimiser import Optimiser
opt = Optimiser.load()                      # needs work/minute_profiles.npz + work/model_cubes.npz
offs = opt.optimise(mask)                   # mask over opt.P.days, e.g. one day type in 2019
pk = opt.day_peaks(offs)                    # daily 15-min max kW, same as stagger.py
change = opt.kwh_change(offs, mask)         # kWh/day (sim.kwh gives the rule version)
sched = opt.schedules_for_day_types(series) # Series of labels by date: one schedule per type
```

Use `sim.bootstrap_cut` for ranges (same resampling as `stagger.py`). The best fixed schedules are in `results/schedule_offsets_all.csv`. Fit only on 2019 days and score on 2018. `work/` isn't committed, so run `prep.py` and `run_schedule.py`, or get the two files (under 2 MB each) from Jinhong.

## Files

| File | Does |
|---|---|
| `prep.py`, `events.py` | Minute profiles from raw data; complete start-up events |
| `sim.py` | `stagger.py`'s simulator, checked against published numbers |
| `models.py`, `validate.py` | Training tables and models; holdout, unseen-floor and SHAP checks |
| `optimiser.py`, `select_variant.py`, `run_schedule.py` | Optimiser and API; 2019 CV; final scoring |
| `charts.py`, `knime/` | Slide charts `charts/ml_01–05`; KNIME node code and setup |
| `results/ml_schedule.csv`, `ml_monthly.csv`, `ml_bootstrap.csv` | Same formats as `stagger_*.csv` |
