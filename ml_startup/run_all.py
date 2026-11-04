"""Rebuild everything from the raw CSVs, in order (about 5 minutes)."""
import prep
import events
import sim
import validate
import select_variant
import run_schedule
import charts

prep.main()
events.build()
sim.check_benchmark()
validate.main()
select_variant.main()
run_schedule.main()
for chart in (charts.accuracy, charts.profile, charts.shap, charts.tradeoff, charts.heatmap):
    chart()
