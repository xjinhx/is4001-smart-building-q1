# IS4001 Smart Building Analytics: Q1 staggered AC start-up

Chamchuri 5 (CU-BEMS), Floors 3 to 7. See [ml_startup/README.md](ml_startup/README.md) for the ML start-up model, the optimiser and the results.

## Setup

The data isn't in this repo. After cloning, put these in the repo root:

- The raw `2018FloorN.csv` and `2019FloorN.csv` files
- Haritha's zip, extracted so that this path exists: `IS4001_Q1_Haritha/IS4001_Q1_Haritha/README.md`

Then rebuild everything (about 5 minutes):

```bash
pip install xgboost pandas numpy pyarrow matplotlib scikit-learn
cd ml_startup
python run_all.py
```
