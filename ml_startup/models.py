"""Training tables and models: zone 15-min kW after start-up, and zone temperature.

kW target: clock-aligned 15-min mean (the billing interval). rel_min = interval
start - zone start, so a start at 13:03 gives -3, 12, 27 ... An offset k just moves
rel_min by -k, which lets the model answer "what if this zone started k min later".
No floor or zone IDs, so the same model runs on a floor it has never seen.
"""
import numpy as np
import pandas as pd
import xgboost as xgb
from config import WORK, RESULTS, SEED

ATTRS = ['rated_kW', 'n_units', 'light_kW']
KW_FEATURES = ['rel_min', 'start_min', 'minutes_off', 'T_start', 'out_T', 'out_rh',
               'month', 'dow', 'morning_kW'] + ATTRS
REL_LO, REL_HI = -30, 135
BIN_MINS = np.arange(690, 930, 15)                # 11:30 ... 15:15, as in the simulator

PM_T_FEATURES = ['elapsed', 'T_start', 'out_T', 'out_rh', 'minutes_off', 'month', 'dow'] + ATTRS
AM_T_FEATURES = ['elapsed', 'start_min', 'T_start', 'out_T', 'out_rh', 'month', 'dow'] + ATTRS
# Physics the optimiser must not be able to game: more cooling time = cooler,
# warmer at the start or outside = warmer
T_MONOTONE = {'elapsed': -1, 'T_start': 1, 'out_T': 1}

XGB_KW = dict(n_estimators=800, learning_rate=0.03, max_depth=8, subsample=0.8, colsample_bytree=0.8,
              min_child_weight=5, reg_lambda=2.0, tree_method='hist', random_state=SEED, n_jobs=-1)
XGB_T = dict(n_estimators=300, learning_rate=0.04, max_depth=4, subsample=0.8, colsample_bytree=0.8,
             min_child_weight=10, reg_lambda=2.0, tree_method='hist', random_state=SEED, n_jobs=-1)


def attrs_table():
    return pd.read_csv(WORK / 'zone_attrs.csv')


def load_events():
    E = pd.read_csv(RESULTS / 'startup_events_complete.csv', parse_dates=['date'])
    E['month'] = E.date.dt.month
    E['dow'] = E.date.dt.dayofweek
    E['day_year'] = E.date.dt.year
    return E


def add_attrs(df, attr_year=2019, floor_year=None):
    """Join zone attributes, measured in attr_year so a test period never informs its own features.
    floor_year overrides that for given floors, e.g. {4: 2018} when floor 4 is the unseen one."""
    a = attrs_table()
    out = df.drop(columns=[c for c in ATTRS if c in df], errors='ignore').copy()
    out['_ay'] = out.floor.map(floor_year or {}).fillna(attr_year).astype(int)
    out = out.merge(a[['year', 'floor', 'zone'] + ATTRS], left_on=['_ay', 'floor', 'zone'],
                    right_on=['year', 'floor', 'zone'], how='left').drop(columns=['_ay', 'year'])
    return out


def kw_table():
    """One row per PM event x clock interval, with the actual 15-min kW as target."""
    z = np.load(WORK / 'minute_profiles.npz')
    A = z['A']
    days = pd.to_datetime(z['days'])
    zones = [tuple(int(v) for v in r) for r in z['zones']]
    q = A.reshape(*A.shape[:2], 16, 15).mean(axis=3)      # D x Z x 16
    d_ix = {d: i for i, d in enumerate(days)}
    z_ix = {v: i for i, v in enumerate(zones)}
    E = load_events()
    E = E[E.event == 'PM'].copy()
    E['d'], E['j'] = E.date.map(d_ix), [z_ix[(f, zz)] for f, zz in zip(E.floor, E.zone)]
    rows = E.loc[E.index.repeat(16)].copy()
    rows['t'] = np.tile(np.arange(16), len(E))
    rows['bin_min'] = BIN_MINS[rows.t]
    rows['rel_min'] = rows.bin_min - rows.start_min
    rows['y'] = q[rows.d.values, rows.j.values, rows.t.values]
    return rows[rows.rel_min.between(REL_LO, REL_HI)].reset_index(drop=True)


def temp_tables():
    """PM: T at 15-45 min after restart (the elapsed spread identifies the effect of a delay).
    AM: T at 08:00, with elapsed = 08:00 - start."""
    f = np.load(WORK / 'full_day_minutes.npz')
    z = np.load(WORK / 'minute_profiles.npz')
    T = f['T']
    days = pd.to_datetime(z['days'])
    zones = [tuple(int(v) for v in r) for r in z['zones']]
    d_ix = {d: i for i, d in enumerate(days)}
    z_ix = {v: i for i, v in enumerate(zones)}
    E = load_events()
    E['d'], E['j'] = E.date.map(d_ix), [z_ix[(fl, zz)] for fl, zz in zip(E.floor, E.zone)]
    pm = E[E.event == 'PM']
    pm = pm.loc[pm.index.repeat(7)].copy()
    pm['elapsed'] = np.tile(np.arange(15, 50, 5), len(pm) // 7)
    pm['y'] = T[pm.d.values, pm.j.values, np.minimum(pm.start_min.values + pm.elapsed.values, 1439)]
    pm = pm.dropna(subset=['y']).reset_index(drop=True)
    am = E[(E.event == 'AM') & (E.start_min < 480)].copy()
    am['elapsed'] = 480 - am.start_min
    am['y'] = am.T_0800
    am = am.dropna(subset=['y']).reset_index(drop=True)
    return pm, am


def fit_kw(df, params=None, features=KW_FEATURES):
    m = xgb.XGBRegressor(**{**XGB_KW, **(params or {})})
    m.fit(df[features].astype(float), df.y)
    return m


def fit_temp(df, features, params=None):
    mono = tuple(T_MONOTONE.get(c, 0) for c in features)
    m = xgb.XGBRegressor(**{**XGB_T, **(params or {})}, monotone_constraints=mono)
    m.fit(df[features].astype(float), df.y)
    return m


def predict(m, df, features):
    return m.predict(df[features].astype(float))


def shap_values(m, df, features):
    """Exact TreeSHAP from XGBoost itself (no shap package needed, so it also runs in KNIME)."""
    d = xgb.DMatrix(df[features].astype(float), feature_names=list(features))
    return m.get_booster().predict(d, pred_contribs=True)[:, :-1]
