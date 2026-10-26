"""Portfolio construction (constant target weights) and risk/return metrics."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config

TRADING_DAYS = 252


# --- weights -------------------------------------------------------------------
def combined_weights(split: dict = config.SPLIT) -> dict[str, float]:
    w = {a: split["A"] * x for a, x in config.PORTFOLIO_A.items()}
    w.update({a: split["B"] * x for a, x in config.PORTFOLIO_B.items()})
    return w


PORTFOLIOS = {
    "A (income)": config.PORTFOLIO_A,
    "B (growth)": config.PORTFOLIO_B,
    "Combined 60/40": combined_weights(),
}


def effective_weights(weights: dict[str, float], available: pd.Series) -> pd.Series:
    """Target weights restricted to assets with a price, renormalized to 1.
    This is how NU's weight is spread over the rest of B before its IPO."""
    w = pd.Series(weights, dtype=float)
    w = w[available.reindex(w.index).notna().values]
    return w / w.sum()


def month_starts(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = index.to_series()
    return pd.DatetimeIndex(s.groupby(index.to_period("M")).first().values)


def portfolio_index(prices: pd.DataFrame, weights: dict[str, float],
                    rebalance: str = "monthly") -> pd.Series:
    """Value of 100 USD invested at target weights, rebalanced on the first trading
    day of each month (no costs, no contributions). Used for risk metrics."""
    px = prices[list(weights)]
    rebal = set(month_starts(px.index)) if rebalance == "monthly" else set()
    value, units, out = 100.0, None, []
    for t, row in px.iterrows():
        if units is None or t in rebal:
            w = effective_weights(weights, row)
            units = value * w / row[w.index]
        value = float((units * row[units.index]).sum())
        out.append(value)
    return pd.Series(out, index=px.index)


def portfolio_indices(prices: pd.DataFrame) -> pd.DataFrame:
    idx = {name: portfolio_index(prices, w) for name, w in PORTFOLIOS.items()}
    idx["SPY"] = prices["SPY"] / prices["SPY"].iloc[0] * 100
    return pd.DataFrame(idx)


# --- metrics -------------------------------------------------------------------
def cagr(index: pd.Series) -> float:
    s = index.dropna()
    years = (s.index[-1] - s.index[0]).days / 365.25
    return (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1


def ann_vol(index: pd.Series) -> float:
    return index.dropna().pct_change().std() * np.sqrt(TRADING_DAYS)


def drawdown(index: pd.Series) -> pd.Series:
    s = index.dropna()
    return s / s.cummax() - 1


def max_drawdown(index: pd.Series) -> dict:
    """Depth, peak date, trough date and recovery date (None if not recovered)."""
    s = index.dropna()
    dd = drawdown(s)
    trough = dd.idxmin()
    peak = s.loc[:trough].idxmax()
    after = s.loc[trough:]
    recovered = after[after >= s.loc[peak]]
    rec = recovered.index[0] if len(recovered) else None
    return {"max_drawdown": float(dd.min()), "peak": peak, "trough": trough, "recovery": rec,
            "days_to_recover": (rec - trough).days if rec is not None else None}


def sharpe(index: pd.Series, rf_annual: pd.Series) -> float:
    r = index.dropna().pct_change().dropna()
    rf = rf_annual.reindex(r.index).ffill() / TRADING_DAYS
    ex = r - rf
    return ex.mean() / ex.std() * np.sqrt(TRADING_DAYS)


def sortino(index: pd.Series, rf_annual: pd.Series) -> float:
    r = index.dropna().pct_change().dropna()
    rf = rf_annual.reindex(r.index).ffill() / TRADING_DAYS
    ex = r - rf
    downside = np.sqrt((np.minimum(ex, 0) ** 2).mean())
    return ex.mean() / downside * np.sqrt(TRADING_DAYS)


def summary(indices: pd.DataFrame, rf_annual: pd.Series) -> pd.DataFrame:
    rows = {}
    for name in indices:
        s = indices[name].dropna()
        mdd = max_drawdown(s)
        monthly = s.resample("ME").last().pct_change().dropna()
        rows[name] = {
            "CAGR": cagr(s),
            "Volatility": ann_vol(s),
            "Sharpe": sharpe(s, rf_annual),
            "Sortino": sortino(s, rf_annual),
            "Max drawdown": mdd["max_drawdown"],
            "Calmar": cagr(s) / abs(mdd["max_drawdown"]),
            "DD peak": mdd["peak"].date(),
            "DD trough": mdd["trough"].date(),
            "DD recovery": mdd["recovery"].date() if mdd["recovery"] is not None else "not yet",
            "Best month": monthly.max(),
            "Worst month": monthly.min(),
            "% positive months": (monthly > 0).mean(),
        }
    return pd.DataFrame(rows).T


def weekly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Friday-to-Friday returns. Used for correlations because Argentine assets
    trade on a different holiday calendar: daily returns would understate them."""
    return prices.resample("W-FRI").last().pct_change(fill_method=None).dropna(how="all")


def correlation_matrix(prices: pd.DataFrame) -> pd.DataFrame:
    return weekly_returns(prices).corr()


def rolling_correlation(a: pd.Series, b: pd.Series, weeks: int = 26) -> pd.Series:
    w = weekly_returns(pd.concat([a, b], axis=1, keys=["a", "b"]))
    return w["a"].rolling(weeks).corr(w["b"])
