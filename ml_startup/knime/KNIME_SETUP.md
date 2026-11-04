# KNIME setup

**Not yet run in KNIME.** KNIME isn't installed on the machine this was built on, so the node code was only tested with `test_nodes.py`, which fakes `knime.scripting.io`. Port counts and the Python environment still need checking in KNIME itself. There is no `.knwf` file; build the workflow below by hand.

## Environment

KNIME 5.x with the Python extension (*Python Script* node). Under Preferences > KNIME > Python, point it at an environment with: `xgboost pandas numpy pyarrow matplotlib scikit-learn`.

## Workflow

Add a *Variable Creator* node with a string `ml_startup_dir` set to the full path of the `ml_startup` folder, and connect it to each Python Script node's flow variable port. Paste the code for each node from `nodes.py`, including the `COMMON` lines, and set its ports (right-click > Configure ports).

| # | Node | Code in `nodes.py` | Ports | Connect outputs to |
|---|---|---|---|---|
| 1 | Prepare data + check benchmark | `NODE_1_PREPARE` | 1 table out | Table View |
| 2 | Train + validate | `NODE_2_VALIDATE` | 2 tables out | Table View (accuracy), Bar Chart (SHAP) |
| 3 | 2019 CV + score schedules | `NODE_3_OPTIMISE` | 2 tables out | Table View (each) |
| 4 | Schedule + charts | `NODE_4_SCHEDULE_OUT` | 2 tables out, 1 image out | CSV Writer (schedule), Line Plot (monthly), Image Writer |
| 5 | Day-type schedules (Dessy) | `NODE_5_DAY_TYPE_SCHEDULES` | 1 table in, 2 tables out | Dessy's benchmark |

Run order is 1 > 2 > 3 > 4 > 5; link them with flow variable connections so that KNIME keeps the order. Node 5's input needs the columns `date` and `day_type`. Node 1 needs the raw `20xxFloorN.csv` files in the folder above `ml_startup`. Nodes 2 to 4 can be re-executed without it once `work/` exists.

Timing: node 1 takes about 1.5 min, node 2 about 1 min, node 3 about 2.5 min.

Tip for the demo: reset and rerun from node 4 onward; it reads saved results, so it is quick.

## Test without KNIME

```bash
python knime/test_nodes.py
```

Add `--all` to include the slow nodes 1 and 3.
