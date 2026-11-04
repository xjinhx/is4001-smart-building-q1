# IS4001 Q1 – Data foundation + peak diagnosis (Haritha)

Chamchuri 5, Floors 3–7. 2019 = train, 2018 Jul–Dec = holdout. Everything here is reproducible from `code/` To re-run: put the 10 CU-BEMS CSVs (2018/2019 Floor 3–7) in a `raw/` folder inside this folder and the weather file at `work/weather_hourly.csv`, then run the scripts in order: load → clean → build → days → baseline → startups → peaks → stagger → charts → export. All paths are relative to this folder.

## Shared definitions (lock these)

| Item | Definition |
|---|---|
| Billing interval | Clock-aligned 15-min mean kW (:00, :15, :30, :45). Timestamp = interval start. Interval kept if ≥10 of 15 minutes present |
| Building load | Sum of all AC + lighting + plug on Floors 3–7 |
| Billing peak | Highest 15-min kW in **MEA TOU on-peak (Mon–Fri 09:00–22:00)** per month, working days only |
| AM window | 07:30–09:00 (morning start-up) |
| PM window | 12:45–14:15 (post-lunch restart) |
| Working day | Mon–Fri, not a Thai public holiday, not gappy, not near-empty (see below) |
| Start-up event | First minute a zone's AC goes >3 kW after ≥30 min (AM) / ≥10 min (PM) below 1 kW |

## Cleaning decisions

- **Spikes (680 readings):** lighting/plug > 3× the column's P99.9 *and* > 3× its 31-min rolling median (500); AC isolated readings > 1.25× P99.99 and > 1.5× both neighbours (180). AC start-up surges are real and kept.
- **Short gaps:** linear fill up to 15 min (kW) / 30 min (temp).
- **Small columns** (lighting, plug, small AC units < 5 kW): longer gaps filled with that column's median profile for the same minute of day in the same month (log: `results/impute_log.csv`). Mainly Floor 4 zone-1 small AC units, missing Mar–May 2019.
- **Gappy day:** any main AC unit (≥ 5 kW) on any floor > 5% missing between 06:00 and 19:00.
- **Near-empty day:** < 60% of that month's median daily kWh, or AC on < 4 h (2 days: 12 Apr and 9 May 2019).
- **Floor 6's meter stops on 22 Oct 2019**, so Nov–Dec 2019 can't be used for the F3–7 total. 2019 effectively runs Jan–Oct.
- **Floor 5 zone 1 temp sensor** reads 11–15°C for long stretches, so it's excluded as unreliable.
- **Indoor temp missing:** 19–44% of minutes per sensor in 2019, ~60% in 2018. Comfort stats use only zone-days that have a reading.

| | 2019 | 2018 holdout |
|---|---|---|
| Weekdays | 261 | 131 |
| − Public holidays | 18 | 8 |
| − Gappy | 70 | 34 |
| − Near-empty | 2 | 0 |
| **Working days** | **171** | **89** |

## Outside data

- Thai public holidays: Python `holidays` package (TH), incl. substitution days.
- Chula calendar: 2019/20 from chula.ac.th/en/news/18302. **AY2018 dates (Aug 2018–Jul 2019) are assumed** to follow the same pattern; flagged in `day_table.csv`.
- Weather: **Open-Meteo historical archive (ERA5 reanalysis)**, hourly temp + RH at Chula (13.737 N, 100.533 E), interpolated to 15 min. Replaces Meteostat in the references.
- Tariff: MEA TOU (Schedules 3.2/4.2). Demand charge is on the max 15-min on-peak demand, 132.93 baht/kW at 12–24 kV (voltage level assumed).

## Baseline (ASHRAE G14)

Hourly OLS: hour + day of week + outdoor temp × occupied + RH × occupied + teaching term × occupied.

| | CV(RMSE) | NMBE | Limit |
|---|---|---|---|
| Train 2019 | 13.9% | 0.0% | ≤ 30%, ±10% |
| **Holdout 2018** | **15.2%** | **−2.6%** | pass |

About 19 kW more load per +1°C outdoors during occupied hours.

## Peak diagnosis: findings

1. **The PM restart sets the billing peak in all 16 months** under TOU. Even counting the morning, it set every 2019 month at building level. The AM start (≈07:46) only beat it in Jul–Oct 2018, and it's off-peak under TOU anyway. *The Floor 3 "AM until March" pattern doesn't hold for F3–7.*
2. **AC is ~85% of the billing peak** (lighting ~12%, plug ~3%). AC zones 1 and 4 are the biggest on every floor; zone 3 has no AC.
3. **All zones on a floor start in the same minute, every day.** 90% of AM starts fall in 07:40–07:50 and 90% of PM starts in 12:56–13:04. Floors are naturally ~5–6 min apart (F7 first, F3/F5 last). → **The data only covers about ±5–10 min of start-time variation**, so Jinhong's model shouldn't be asked about ±30 min.
4. **The surge comes from units starting together, not from catch-up cooling.** First-30-min peak is 1.4× (AM) / 1.55× (PM) the steady kW. Correlation of the surge with indoor temp at start is ≈0.02.
5. Lunch shutdown: AC off ~11:46 → back on ~13:01 (≈75 min).
6. Arrival proxy (lighting + plug reach 50% of their morning rise): median 06:28. It's likely partly cleaners or a lighting schedule, so treat it as a soft proxy.
7. **Comfort today:** only **64% of zone-days are ≤25°C at 08:00**. PM: 93% are ≤25°C 30 min after restart. → Use the comfort rule "no worse than today", not "every zone ≤ 25°C every day" (that fails without any change).
8. Peak-to-average ratio: 3.2–4.0 (working days).

## First-cut stagger (placeholder for the ML optimiser)

Real minute profiles shifted by zone offsets of {−10, −5, 0, +5, +10} min. Delays and advances net out, so daily kWh is unchanged. Searched on 2019, tested on 2018. No ML and no rebound term; it sets the KPI target range.

| | Mean monthly peak cut | 95% bootstrap CI | ≈ baht/month @132.93 |
|---|---|---|---|
| 2019 (fitted) | 35 kW (5.5%) | 33–41 | ~4,650 |
| **2018 holdout** | **16 kW (2.7%)** | 14–20 | ~2,100 |

A simpler floor-level version (F3 −10, F4 +10, F5 −5, F6 −10, F7 +10 min) gives 32 kW on 2019 and 13 kW on the holdout. **Honest range: roughly 15–35 kW, i.e. ~25k–56k baht/yr** (indicative only: F3–7 is part of the building meter).

## KPI targets (proposed)

| KPI | Today | Target |
|---|---|---|
| Monthly billing peak (TOU) | 573–676 kW (2019: 590–676) | −15 to −35 kW |
| Peak-to-average ratio | 3.2–4.0 | lower |
| Daily kWh | 2019 median ~4,090 kWh | no rise |
| Comfort AM (≤25°C at 08:00) | 64% of zone-days | ≥ 64% |
| Comfort PM (≤25°C 30 min after restart) | 93% | ≥ 93% |
| Start-up model MAPE / forecaster hit-rate | Jinhong / Dessy | – |

## Files

- `data/building_15min_alldays.csv`: 15-min F3–7 total, by end-use and floor, weather, TOU flag, AM/PM window, working/set/term/holiday flags.
- `data/zone_15min_workingdays.csv`: **Jinhong's input.** One row per 15-min × floor × zone on working days: AC/Light/Plug kW, indoor temp, outdoor temp/RH. Zone 3 AC = blank.
- `data/startup_events.csv`: **Jinhong's input.** One row per zone-day × AM/PM: start time, minutes off before (PM only; AM blank = overnight), indoor temp at start and at 08:00 / +30 min, outdoor temp, peak/mean kW first 30 min, steady kW 60–90 min, surge ratio.
- `data/day_table.csv`: **Dessy's input.** Working-day list, daily kWh, holiday, Chula term, gap flags, set.
- `data/weather_hourly_openmeteo.csv`, `data/arrival_proxy.csv`
- `results/`: monthly peaks, peak shares, G14, baseline fit, stagger schedule/monthly/bootstrap, spike and impute logs.
- `charts/01–07`: slide-ready PNGs.

## Notes for the team

- **Jinhong:** bound offsets to ±10 min (the data range). Use zone attributes (rated kW, number of units) rather than zone ID if you're testing on an unseen floor. Start time alone won't explain much because it barely varies; outdoor temp and month will carry the model.
- **Dessy:** the optimiser's in/out format can be the same as `stagger.py`: in = day's zone minute profiles + offsets; out = 15-min max kW + kWh change. The 3-way benchmark can use this rule-based stagger as the "fixed schedule" arm.
- If ML doesn't beat ~16 kW on the 2018 holdout, recommend the fixed schedule.
