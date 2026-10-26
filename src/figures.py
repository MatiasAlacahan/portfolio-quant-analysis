"""Static PNG charts (used in the README and for quick checks)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import pandas as pd

from . import config

# Validated categorical palette (fixed order) + chart chrome.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK_2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"

# Entity -> color stays fixed across every chart.
COLORS = {
    "A (income)": SERIES[0], "100% A": SERIES[0],
    "B (growth)": SERIES[1], "100% B": SERIES[1],
    "Combined 60/40": SERIES[2], "Your strategy (no selling)": SERIES[2],
    "SPY": SERIES[3], "100% SPY": SERIES[3],
    "Full rebalance": SERIES[6],
}


def _style(ax, title: str, subtitle: str = ""):
    fig = ax.figure
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.set_title(title, loc="left", color=INK, fontsize=13, fontweight="bold", pad=22)
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, color=INK_2, fontsize=9.5)


def _direct_labels(ax, df: pd.DataFrame, fmt):
    """Label each line at its right end (sorted to avoid collisions)."""
    last = df.iloc[-1].sort_values()
    ymin, ymax = ax.get_ylim()
    min_gap = (ymax - ymin) * 0.045
    prev = None
    for name, y in last.items():
        y_txt = y if prev is None else max(y, prev + min_gap)
        prev = y_txt
        ax.annotate(f"{name}  {fmt(y)}", xy=(df.index[-1], y_txt), xytext=(8, 0),
                    textcoords="offset points", va="center", fontsize=9, color=INK_2,
                    annotation_clip=False)


def growth_chart(indices: pd.DataFrame, path):
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
    for c in indices:
        ax.plot(indices.index, indices[c], color=COLORS.get(c, MUTED), linewidth=2, label=c)
    _style(ax, "Growth of USD 100 (total return, rebalanced monthly)",
           "Base ON proxy. No contributions or commissions.")
    ax.yaxis.set_major_formatter(mtick.StrMethodFormatter("{x:,.0f}"))
    ax.legend(frameon=False, loc="upper left", fontsize=9, labelcolor=INK_2)
    _direct_labels(ax, indices, lambda v: f"{v:,.0f}")
    fig.subplots_adjust(right=0.78)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def backtest_chart(values: pd.DataFrame, invested: pd.Series, path):
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
    cols = ["Your strategy (no selling)", "100% SPY"]
    for c in cols:
        ax.plot(values.index, values[c], color=COLORS[c], linewidth=2, label=c)
    ax.plot(invested.index, invested, color=MUTED, linewidth=1.5, linestyle="--", label="Money invested")
    _style(ax, f"USD {config.MONTHLY_CONTRIBUTION:.0f} per month: your strategy vs 100% SPY",
           "Account value in USD, after commissions.")
    ax.yaxis.set_major_formatter(mtick.StrMethodFormatter("${x:,.0f}"))
    ax.legend(frameon=False, loc="upper left", fontsize=9, labelcolor=INK_2)
    df = values[cols].copy()
    df["Money invested"] = invested
    _direct_labels(ax, df, lambda v: f"${v:,.0f}")
    fig.subplots_adjust(right=0.75)
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def drawdown_chart(indices: pd.DataFrame, path):
    from .metrics import drawdown
    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=150)
    for c in indices:
        ax.plot(indices.index, drawdown(indices[c]), color=COLORS.get(c, MUTED), linewidth=1.6, label=c)
    _style(ax, "Drawdown: distance from the previous peak")
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.legend(frameon=False, loc="lower right", fontsize=9, labelcolor=INK_2, ncol=4)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
