"""Paste each block into its own KNIME Python Script node (see knime/KNIME_SETUP.md).
Every node starts with the same two lines; set the flow variable ml_startup_dir to the
ml_startup folder. test_nodes.py runs these against a stand-in for knime.scripting.io.
"""

COMMON = """
import sys
import knime.scripting.io as knio
sys.path.insert(0, knio.flow_variables['ml_startup_dir'])
import pandas as pd
"""

# 1 output table: the rebuilt start-up events
NODE_1_PREPARE = COMMON + """
import prep, events, sim
prep.main()
knio.output_tables[0] = knio.Table.from_pandas(events.build().assign(date=lambda d: d.date.astype(str)))
sim.check_benchmark()
"""

# 2 output tables: accuracy, SHAP importance
NODE_2_VALIDATE = COMMON + """
import validate
from config import RESULTS
validate.main()
knio.output_tables[0] = knio.Table.from_pandas(pd.read_csv(RESULTS / 'model_accuracy.csv'))
knio.output_tables[1] = knio.Table.from_pandas(pd.read_csv(RESULTS / 'shap_importance.csv'))
"""

# 2 output tables: 2019 CV by variant and month, then schedule comparison on the holdout
NODE_3_OPTIMISE = COMMON + """
import select_variant, run_schedule
from config import RESULTS
select_variant.main()
run_schedule.main()
knio.output_tables[0] = knio.Table.from_pandas(pd.read_csv(RESULTS / 'variant_cv.csv'))
knio.output_tables[1] = knio.Table.from_pandas(pd.read_csv(RESULTS / 'schedule_comparison.csv'))
"""

# 2 output tables: BMS schedule, monthly peaks. 1 output image: the schedule chart
NODE_4_SCHEDULE_OUT = COMMON + """
import charts
from config import RESULTS, CHARTS
for chart in (charts.accuracy, charts.profile, charts.shap, charts.tradeoff, charts.heatmap):
    chart()
knio.output_tables[0] = knio.Table.from_pandas(pd.read_csv(RESULTS / 'ml_schedule.csv'))
knio.output_tables[1] = knio.Table.from_pandas(pd.read_csv(RESULTS / 'ml_monthly.csv'))
knio.output_images[0] = (CHARTS / 'ml_05_schedule.png').read_bytes()
"""

# Dessy. 1 input table with columns date, day_type. 2 output tables: schedule per type, daily peaks
NODE_5_DAY_TYPE_SCHEDULES = COMMON + """
from optimiser import Optimiser
types = knio.input_tables[0].to_pandas()
s = pd.Series(types['day_type'].values, index=pd.to_datetime(types['date']))
opt = Optimiser.load()
sched = opt.schedules_for_day_types(s)
peaks = []
for lab, g in sched.groupby('day_type'):
    peaks.append(pd.DataFrame({'date': opt.P.days.astype(str), 'schedule_day_type': lab,
                               'daily_peak_kW': opt.day_peaks(g.offset_min.tolist())}))
knio.output_tables[0] = knio.Table.from_pandas(sched)
knio.output_tables[1] = knio.Table.from_pandas(pd.concat(peaks, ignore_index=True))
"""
