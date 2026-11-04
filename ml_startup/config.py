"""Shared paths and the locked project definitions (see Haritha's README)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent                                    # raw 20xxFloorN.csv live here
HARITHA = PROJECT / 'IS4001_Q1_Haritha' / 'IS4001_Q1_Haritha'
DATA = HARITHA / 'data'
HRESULTS = HARITHA / 'results'
WORK = ROOT / 'work'          # regenerated caches (not committed)
RESULTS = ROOT / 'results'
CHARTS = ROOT / 'charts'
for p in (WORK, RESULTS, CHARTS):
    p.mkdir(exist_ok=True)

FLOORS = range(3, 8)
YEARS = (2018, 2019)
OFFSETS = (-10, -5, 0, 5, 10)      # minutes; +ve = later. Data only supports about +/-10
WINDOW = ('11:30:00', '15:30:00')  # same minute window as stagger.py
DEMAND_BAHT_PER_KW = 132.93
COMFORT_C = 25.0
PM_COMFORT_ELAPSED = 30            # README comfort rule: <=25C 30 min after the restart
SEED = 1
