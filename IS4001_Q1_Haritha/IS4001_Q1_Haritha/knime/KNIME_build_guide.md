# KNIME cleaning workflow: build guide (Q1 data foundation)

KNIME 5.x. Standard nodes do the loading, joins, flags and outputs. One **Python Script** node does the column-by-column cleaning, which would take ~200 Rule Engine nodes otherwise. Tested: it reproduces the Python pipeline exactly (680 spikes, 171 + 89 working days).

**Before you start**
- Extract `archive.zip` (CU-BEMS) into a folder, e.g. `Downloads\CU-BEMS_raw\`.
- Files from this folder you'll need: `node_clean_minute.py`, `holidays_TH_2018_2019.csv`, `chula_calendar_daily.csv`, and `data/weather_hourly_openmeteo.csv`.
- Python Script nodes need the *KNIME Python Integration* extension (bundled environment is fine).

---

## Part A: Load + clean every floor-year (loop)

| # | Node | Settings |
|---|---|---|
| A1 | **List Files/Folders** | Folder = `CU-BEMS_raw`. Filter files by name, regex `201[89]Floor[3-7]\.csv` → 10 rows |
| A2 | **Path to String** | Column `Path`, *append* new column `path_str` (keep `Path`) |
| A3 | **String Manipulation** | New col `floor`: `toInt(regexReplace($path_str$, ".*Floor(\\d)\\.csv$", "$1"))` |
| A4 | **String Manipulation** | New col `year`: `toInt(regexReplace($path_str$, ".*(201\\d)Floor.*", "$1"))` |
| A5 | **Table Row To Variable Loop Start** | Defaults: makes `Path`, `floor`, `year` flow variables |
| A6 | **CSV Reader** | Click the variable button next to the file chooser → `Path`. *Advanced*: tick **Support short data rows** (2019 Floor 6 ends mid-row). *Transformation*: set `Date` to **String** |
| A7 | **CSV Reader** (outside loop) | `holidays_TH_2018_2019.csv` (`date` = Local Date) |
| A8 | **Python Script** | Add **2 input** ports (A6 → in 0, A7 → in 1) and **3 output** ports. Paste `node_clean_minute.py`. `floor` and `year` arrive automatically through A6's connection (check the node's Flow Variables tab) |
| A9 | **Loop End (3 ports)** | Connect all 3 outputs. Leave "collect rows". 10 iterations; takes a few minutes |

Loop End outputs:
- **port 1**: 15-min long table `ts | floor | zone | enduse | unit | value` (~5.5M rows)
- **port 2**: floor-day quality `date | floor | major_miss_pct | AC_kWh | Light_kWh | Plug_kWh`
- **port 3**: spike + fill log

**Check 1:** port 3 → **Row Filter** `step` starts with `spike_AC` or `spike_LP` → **GroupBy** sum(`n`) = **680**.

---

## Part B: Working-day list (all standard nodes)

| # | Node | Settings |
|---|---|---|
| B1 | **Math Formula** (port 2) | `day_kWh = $AC_kWh$ + $Light_kWh$ + $Plug_kWh$` |
| B2 | **Modify Time** | Remove time from `date` → Local Date |
| B3 | **GroupBy** by `date` | max(`major_miss_pct`) → rename `worst_miss`; sum(`day_kWh`) → rename `kWh` |
| B4 | **Row Filter** (port 1) | `enduse` = `AC` |
| B5 | **GroupBy** by `ts` | sum(`value`) |
| B6 | **Rule Engine** | append `on_h`: `$Sum(value)$ > 20 => 0.25` / `TRUE => 0` |
| B7 | **Modify Time** | remove time from `ts` → `date` (append) |
| B8 | **GroupBy** by `date` | sum(`on_h`) → `AC_on_h` |
| B9 | **Joiner** B3 ⨝ B8 | on `date`, inner |
| B10 | **Joiner** + holidays (A7) | on `date`, **left outer** → `holiday` empty on normal days |
| B11 | **CSV Reader** `chula_calendar_daily.csv` → **Joiner** | left outer on `date` |
| B12 | **Extract Date&Time Fields** | from `date`: Year, Month (number), Day of week (**name**) |
| B13 | **Rule Engine** → `candidate` | `NOT $Day of week (name)$ IN ("Saturday","Sunday") AND MISSING $holiday$ AND $worst_miss$ <= 5 => "yes"` / `TRUE => "no"` |
| B14 | **Row Filter** `candidate = yes` → **GroupBy** Year, Month | median(`kWh`) |
| B15 | **Joiner** B13 ⨝ B14 | on Year + Month, left outer |
| B16 | **Math Formula** | `threshold = 0.6 * $Median(kWh)$` |
| B17 | **Rule Engine** → `near_empty` | `$candidate$ = "yes" AND $kWh$ < $threshold$ => "yes"` / `$candidate$ = "yes" AND $AC_on_h$ < 4 => "yes"` / `TRUE => "no"` |
| B18 | **Rule Engine** → `working` | `$candidate$ = "yes" AND $near_empty$ = "no" => "yes"` / `TRUE => "no"` |
| B19 | **Rule Engine** → `set` | `$Year$ = 2019 => "train_2019"` / `TRUE => "holdout_2018"` |
| B20 | **CSV Writer** | `day_table.csv` |

**Check 2:** **Row Filter** `working = yes` → **GroupBy** Year, count = **2018: 89, 2019: 171**. Near-empty days = 12 Apr and 9 May 2019.

---

## Part C: 15-min outputs + weather

| # | Node | Settings |
|---|---|---|
| C1 | **Row Filter** (port 1) | `enduse` ≠ `Temp` |
| C2 | **Pivot** | group `ts`; pivot `enduse`; sum(`value`) → AC / Light / Plug columns |
| C3 | **Math Formula** | `total_kW = AC + Light + Plug` (rename columns first if you like) |
| C4 | **Modify Time** | remove time from `ts` → `date` (append) |
| C5 | **Joiner** + day table (B19) | on `date`; then **Row Filter** `working = yes` |
| C6 | **CSV Reader** `weather_hourly_openmeteo.csv` | `ts` = Local Date Time |
| C7 | **Round Date&Time** on C5 | round `ts` **down** to 1 hour → append `ts_hour` |
| C8 | **Joiner** C7 ⨝ C6 | `ts_hour` = `ts`, left outer |
| C9 | **Rule Engine** → `tou_onpeak` | time-of-day 09:00–21:45 (extract Hour first with Extract Date&Time Fields): `$Hour$ >= 9 AND $Hour$ < 22 => "yes"` / `TRUE => "no"` |
| C10 | **CSV Writer** | `building_15min_workingdays.csv` |

*Zone-level file for Jinhong (optional):* port 1 → **Pivot** (group `ts`, `floor`, `zone`; pivot `enduse`; sum `value`) → same C4–C8 → **CSV Writer**.

**Check 3:** C10 → **GroupBy** month, max(`total_kW`) where `tou_onpeak = yes` → matches `results/monthly_peaks.csv` (`peak_TOU_kW`, e.g. May 2019 = 675.8).

*Small difference:* weather here is matched to the hour. The Python version interpolates to 15 min, so `out_temp_C` differs by up to ~0.5°C. Peaks and the working-day list are unaffected.

---

## What each part shows on the slide

Load (A1–A6) → Clean (A8: spikes, short gaps, profile fill, 15-min) → Flag days (B: holidays, gaps, near-empty, Chula term) → Join weather (C) → Outputs.
