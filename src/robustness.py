"""Robustness checks: re-run the analysis on a shorter, more recent window and put
the results in the context of Argentine country risk (look-ahead / hindsight bias)."""
from __future__ import annotations

import pandas as pd

from . import backtest, metrics


def window_analysis(prices: pd.DataFrame, rf: pd.Series, start: str) -> dict:
    """Same metrics and backtest, starting at `start` (prices are re-based automatically)."""
    p = prices.loc[start:]
    idx = metrics.portfolio_indices(p)
    results = backtest.run_all(p)
    return {"start": p.index[0], "end": p.index[-1],
            "summary": metrics.summary(idx, rf), "indices": idx,
            "results": results, "backtest": backtest.summarize(results)}


def country_risk_context(embi: pd.Series, full_start, robust_start, end) -> pd.DataFrame:
    """Key country-risk levels: the starting point explains much of the bond returns."""
    e = embi.sort_index()
    window = e.loc[full_start:end]

    def at(d):
        return float(e.loc[:d].iloc[-1])

    rows = [
        ("Full window start", pd.Timestamp(full_start), at(full_start)),
        ("Peak in window", window.idxmax(), float(window.max())),
        ("Robustness window start", pd.Timestamp(robust_start), at(robust_start)),
        ("Low in window", window.idxmin(), float(window.min())),
        ("Latest", window.index[-1], float(window.iloc[-1])),
    ]
    return pd.DataFrame(rows, columns=["point", "date", "embi_bps"]).set_index("point")
