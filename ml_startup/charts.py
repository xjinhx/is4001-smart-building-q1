"""Slide charts for the ML start-up model and optimiser. Output: charts/ml_0*.png"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from config import RESULTS, CHARTS, WORK
from models import KW_FEATURES, kw_table, add_attrs, fit_kw, predict

BLUE, ORANGE = '#2a78d6', '#eb6834'
INK, INK2, MUTED, GRID, AXIS, SURFACE = '#0b0b0b', '#52514e', '#898781', '#e1e0d9', '#c3c2b7', '#fcfcfb'
plt.rcParams.update({'font.family': ['Segoe UI', 'DejaVu Sans'], 'font.size': 11, 'text.color': INK2,
                     'axes.edgecolor': AXIS, 'axes.labelcolor': INK2, 'xtick.color': MUTED, 'ytick.color': MUTED,
                     'axes.spines.top': False, 'axes.spines.right': False, 'axes.grid': True, 'grid.color': GRID,
                     'grid.linewidth': .7, 'axes.axisbelow': True, 'figure.facecolor': SURFACE,
                     'axes.facecolor': SURFACE, 'savefig.dpi': 180, 'savefig.bbox': 'tight'})


def title(ax, t, sub=None):
    ax.set_title(t, loc='left', color=INK, fontsize=14, fontweight='bold', pad=26 if sub else 10)
    if sub:
        ax.text(0, 1.02, sub, transform=ax.transAxes, color=INK2, fontsize=10.5)


def accuracy():
    R = pd.read_csv(RESULTS / 'model_accuracy.csv')
    R = R[R.model == 'kW']
    tests = ['holdout_2018'] + [f'unseen floor {f}' for f in range(3, 8)]
    labels = ['2018 holdout'] + [f'Floor {f}\n(unseen)' for f in range(3, 8)]
    ml = [R[(R.test == t) & (R.method == 'XGBoost')].MAPE_pct.iloc[0] for t in tests]
    na = [R[(R.test == t) & R.method.str.startswith('naive')].MAPE_pct.iloc[0] for t in tests]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    x = np.arange(len(tests))
    ax.bar(x - .19, na, .36, color=ORANGE, label='Naive median profile')
    ax.bar(x + .19, ml, .36, color=BLUE, label='XGBoost')
    for i, (a, b) in enumerate(zip(na, ml)):
        ax.text(i - .19, a + 1.5, f'{a:.0f}', ha='center', fontsize=10, color=INK)
        ax.text(i + .19, b + 1.5, f'{b:.0f}', ha='center', fontsize=10, color=INK)
    ax.set_xticks(x, labels)
    ax.tick_params(axis='x', length=0, labelcolor=INK2)
    ax.grid(axis='x', visible=False)
    ax.set_ylabel('MAPE, AC-on intervals (%)')
    ax.legend(frameon=False, loc='upper left', ncols=2)
    title(ax, 'The model beats a naive profile, most clearly on unseen floors',
          'Zone 15-min kW after the PM restart. Floor 6 is high because its small loads inflate MAPE')
    fig.savefig(CHARTS / 'ml_01_accuracy.png')


def profile():
    K = add_attrs(kw_table())
    tr, te = K[K.set == 'train_2019'], K[K.set == 'holdout_2018'].copy()
    te['p'] = predict(fit_kw(tr), te, KW_FEATURES)
    g = te.groupby(['date', 'bin_min'])[['y', 'p']].sum().groupby('bin_min').mean()
    g = g[(g.index >= 750) & (g.index <= 885)]
    t = [f'{m // 60}:{m % 60:02d}' for m in g.index]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    ax.plot(t, g.y, color=ORANGE, lw=2, marker='o', ms=5, label='Actual')
    ax.plot(t, g.p, color=BLUE, lw=2, marker='o', ms=5, label='Model')
    ax.set_ylabel('Zone AC, summed (kW)')
    ax.set_ylim(0)
    ax.legend(frameon=False, loc='lower right', ncols=2)
    title(ax, 'The model tracks the 2018 surge, but undershoots 13:00 by about 40 kW',
          'Mean of 2018 holdout working days, 15-min billing intervals (model trained on 2019 only)')
    fig.savefig(CHARTS / 'ml_02_holdout_profile.png')


def shap():
    z = np.load(WORK / 'shap_kw.npz')
    names = {'rel_min': 'Minutes since start', 'morning_kW': 'Zone kW before lunch', 'rated_kW': 'Rated kW',
             'light_kW': 'Lighting size', 'out_T': 'Outdoor temp', 'T_start': 'Indoor temp at start',
             'start_min': 'Start time', 'out_rh': 'Outdoor RH', 'minutes_off': 'Minutes off',
             'dow': 'Day of week', 'month': 'Month', 'n_units': 'Unit count'}
    v = pd.Series(np.abs(z['s']).mean(axis=0), index=[names[f] for f in z['f']]).sort_values()
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.barh(v.index, v.values, color=BLUE, height=.62)
    for i, val in enumerate(v.values):
        ax.text(val + .05, i, f'{val:.2f}', va='center', color=INK, fontsize=10)
    ax.tick_params(axis='y', length=0, labelcolor=INK2)
    ax.grid(axis='y', visible=False)
    ax.set_xlabel('Mean |SHAP| on the 2018 holdout (kW per zone interval)')
    title(ax, 'Minutes off and start time barely move kW: little rebound',
          'What matters is where you are in the start-up and how loaded the zone is that day')
    fig.savefig(CHARTS / 'ml_03_shap.png')


def tradeoff():
    C = pd.read_csv(RESULTS / 'schedule_comparison.csv')
    keep = {'Rule benchmark (Haritha)': ('Rule benchmark', (10, 4)),
            'Recommended: real profiles + ML constraints': ('Real profiles +\nML constraints', (-44, -66)),
            'Pure ML kW model (delta) + constraints': ('Pure ML kW model', (-50, 46)),
            'Real profiles, top-3, no comfort rule': ('Top-3 days,\nno comfort rule', (10, -6)),
            'Recommended variant limited to +/-5 min': ('±5 min only', (-70, 4))}
    C = C[C.schedule.isin(keep)]
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    x = C.comfort_2018_new - C.comfort_2018_today
    ax.errorbar(x, C.cut_2018_kW, yerr=[C.cut_2018_kW - C.cut_2018_CI_lo, C.cut_2018_CI_hi - C.cut_2018_kW],
                fmt='o', color=BLUE, ms=8, elinewidth=1.5, capsize=0, mec=SURFACE, mew=2)
    for xi, y, s in zip(x, C.cut_2018_kW, C.schedule):
        ax.annotate(keep[s][0], (xi, y), xytext=keep[s][1], textcoords='offset points', color=INK, fontsize=10)
    ax.axvline(0, color=AXIS, lw=1)
    ax.text(.12, 1.5, 'No worse than today', rotation=90, ha='left', va='bottom', color=MUTED, fontsize=9.5)
    ax.set_xlim(-12.5, 1.2)
    ax.set_ylim(0, 32)
    ax.set_xlabel('Change in zone-days at or below 25°C, 30 min after restart (percentage points, 2018)')
    ax.set_ylabel('Mean monthly peak cut (kW, 2018)')
    title(ax, 'On the warmer 2018 holdout, more kW cut costs more comfort',
          'Bars: 95% bootstrap range. No ±10 min schedule meets the comfort rule on 2018')
    fig.savefig(CHARTS / 'ml_04_cut_vs_comfort.png')


def heatmap():
    O = pd.read_csv(RESULTS / 'ml_schedule.csv')
    M = O.pivot(index='floor', columns='zone', values='offset_min').sort_index(ascending=False)
    cmap = LinearSegmentedColormap.from_list('div', ['#2a78d6', '#f0efec', '#e34948'])
    fig, ax = plt.subplots(figsize=(6.6, 4.4))
    ax.imshow(M.values, cmap=cmap, vmin=-16, vmax=16, aspect='auto')
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks(range(M.shape[1]), [f'Zone {z}' for z in M.columns])
    ax.set_yticks(range(M.shape[0]), [f'Floor {f}' for f in M.index])
    ax.tick_params(length=0, labelcolor=INK2)
    ax.set_xticks(np.arange(-.5, M.shape[1]), minor=True)
    ax.set_yticks(np.arange(-.5, M.shape[0]), minor=True)
    ax.grid(which='minor', color=SURFACE, lw=2)
    ax.tick_params(which='minor', length=0)
    for i, f in enumerate(M.index):
        for j, z in enumerate(M.columns):
            v = int(M.iloc[i, j])
            star = '*' if (f, z) == (5, 1) else ''
            ax.text(j, i, (f'{v:+d}' if v else '0') + star, ha='center', va='center', color=INK, fontsize=12, fontweight='bold')
    title(ax, 'Draft PM restart offsets by zone (minutes)',
          '+ later, − earlier than today. *F5 Z1 has no working sensor: comfort unchecked')
    fig.savefig(CHARTS / 'ml_05_schedule.png')


if __name__ == '__main__':
    accuracy()
    profile()
    shap()
    tradeoff()
    heatmap()
