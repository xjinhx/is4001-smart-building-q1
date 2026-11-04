"""Slide charts for the adaptive schedule. Run after adaptive_schedule.py:
    python adaptive_charts.py
Reads results/*.csv, writes charts/adaptive_01..04.png (16:9, light background, sized for slides).
Optional: python adaptive_charts.py <results_dir> <charts_dir>
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
RESULTS = Path(sys.argv[1]) if len(sys.argv) > 2 else HERE / 'results'
CHARTS = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / 'charts'
CHARTS.mkdir(exist_ok=True)

SURFACE, INK, INK2, MUTED, GRID = '#fcfcfb', '#0b0b0b', '#52514e', '#8a8984', '#e4e3df'
BLUE, ORANGE, AQUA = '#2a78d6', '#eb6834', '#1baf7a'     # categorical slots 1-3
GREY = '#b9b8b2'                                         # baselines
plt.rcParams.update({'font.size': 15, 'axes.facecolor': SURFACE, 'figure.facecolor': SURFACE,
                     'text.color': INK, 'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK2,
                     'axes.spines.top': False, 'axes.spines.right': False, 'axes.edgecolor': GRID,
                     'font.family': 'DejaVu Sans'})


def base(title, sub=None):
    fig, ax = plt.subplots(figsize=(10, 5.6))
    fig.subplots_adjust(left=0.1, right=0.97, top=0.82, bottom=0.14)
    fig.text(0.1, 0.93, title, fontsize=19, fontweight='bold', ha='left')
    if sub:
        fig.text(0.1, 0.875, sub, fontsize=13, color=INK2, ha='left')
    ax.yaxis.grid(True, color=GRID, lw=1)
    ax.set_axisbelow(True)
    return fig, ax


def save(fig, name):
    fig.savefig(CHARTS / name, dpi=200)
    plt.close(fig)
    print('wrote', CHARTS / name)


def day_types():
    P = pd.read_csv(RESULTS / 'day_type_profiles.csv', index_col=0)
    S = pd.read_csv(RESULTS / 'day_type_summary.csv')
    fig, ax = base(f'{len(P.columns)} kinds of working day', 'Average building load, 06:00-22:00, 2019 days')
    cols = [AQUA, BLUE, ORANGE, '#eda100']
    x = np.arange(len(P))
    for c, col in zip(P.columns, cols):
        n = S[(S['set'] == 'train_2019') & (S.day_type == c)].n_days
        lab = f'{c} ({int(n.iloc[0])} days)' if len(n) else c
        ax.plot(x, P[c], color=col, lw=2.5, label=lab)
    ticks = [i for i, t in enumerate(P.index) if str(t).endswith(':00') and int(str(t)[:2]) % 2 == 0]
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(P.index[i]) for i in ticks])
    ax.set_ylabel('Building load (kW)')
    ax.set_xlim(0, len(P) - 1)
    ax.legend(frameon=False, ncol=len(P.columns), loc='lower left', bbox_to_anchor=(0, 1.0), fontsize=12,
              handlelength=1.6, columnspacing=1.6)
    fig.subplots_adjust(top=0.78)
    save(fig, 'adaptive_01_day_types.png')


def forecaster():
    A = pd.read_csv(RESULTS / 'forecaster_accuracy.csv')
    h = A[A['set'] == '2018 holdout'].iloc[0]
    labels = ['Always guess the\nmost common type', 'Day-ahead\nforecaster', 'Forecaster, top-3\npeak days only']
    vals = [h.majority_baseline, h.accuracy, h.top3_peak_days_accuracy]
    fig, ax = base('Can we predict tomorrow\'s day type?', 'Share of 2018 holdout days (Jul-Dec) classified correctly')
    bars = ax.bar(labels, np.array(vals) * 100, color=[GREY, BLUE, BLUE], width=0.55)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v * 100 + 1.5, f'{v * 100:.0f}%', ha='center', fontsize=17, fontweight='bold')
    ax.set_ylim(0, 105)
    ax.set_ylabel('Correct (%)')
    save(fig, 'adaptive_02_forecaster.png')


def benchmark():
    R = pd.read_csv(RESULTS / 'adaptive_benchmark.csv')
    short = {'Fixed: rule-based benchmark': 'Fixed\n(rule-based)', 'Fixed: locked ML pick': 'Fixed\n(ML pick)',
             'Month rule (best schedule per calendar month, fit 2019)': 'Month\nrule',
             'ML adaptive (forecast day type)': 'ML adaptive\n(forecast)',
             'ML adaptive, oracle day type (reference)': 'ML adaptive\n(oracle,\nreference)'}
    R['lab'] = R.schedule.map(short)
    fig, ax = base('Peak demand cut on the 2018 holdout', 'Mean monthly cut (kW) with 95% bootstrap range, schedules fitted on 2019')
    colors = [GREY, GREY, GREY, BLUE, BLUE]
    y = R.cut_2018_kW.to_numpy()
    err = np.vstack([y - R.cut_2018_CI_lo, R.cut_2018_CI_hi - y])
    bars = ax.bar(R.lab, y, color=colors, width=0.55, yerr=err, error_kw=dict(ecolor=INK2, capsize=6, lw=1.8))
    bars[-1].set_hatch('///')
    bars[-1].set_edgecolor(SURFACE)
    for b, v, hi in zip(bars, y, R.cut_2018_CI_hi):
        ax.text(b.get_x() + b.get_width() / 2, hi + 0.6, f'{v:.1f}', ha='center', fontsize=16, fontweight='bold')
    ax.axhline(0, color=INK2, lw=1)
    ax.set_ylabel('Peak cut (kW per month)')
    ax.tick_params(axis='x', labelsize=12)
    save(fig, 'adaptive_03_benchmark.png')


def monthly():
    M = pd.read_csv(RESULTS / 'adaptive_monthly.csv')
    M = M[M.month.astype(str).str.startswith('2018')]
    x = np.arange(len(M))
    fig, ax = base('Monthly peak cut, 2018 holdout', 'Adaptive schedule vs one fixed schedule, kW')
    w = 0.38
    ax.bar(x - w / 2, M.cut_fixed_kW, w, color=GREY, label='Fixed (ML pick)')
    ax.bar(x + w / 2, M.cut_kW, w, color=BLUE, label='ML adaptive')
    ax.set_xticks(x)
    ax.set_xticklabels([pd.Period(m).strftime('%b') for m in M.month])
    ax.axhline(0, color=INK2, lw=1)
    ax.set_ylabel('Peak cut (kW)')
    ax.legend(frameon=False, loc='upper left', fontsize=13, ncol=2, bbox_to_anchor=(0, 1.02))
    save(fig, 'adaptive_04_monthly.png')


if __name__ == '__main__':
    for f in (day_types, forecaster, benchmark, monthly):
        f()
