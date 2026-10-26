"""Monthly-contribution backtest (dollar-cost averaging) with commissions.

Strategies
- no_sell:        each contribution is split 60/40 between A and B and, inside each
                  sleeve, goes to the assets furthest below target. Nothing is sold.
                  (The realistic way to rebalance with a small account.)
- full_rebalance: each month the contribution is added and the whole account is
                  brought back to the combined targets, selling what is overweight.
- spy_only:       every contribution goes to SPY (benchmark).
- a_only / b_only: 100% of the contribution to one sleeve, no-sell rule.

Contributions are invested at the close of the first trading day of each month.
Commission is charged on every buy and sell (see config.commission).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from . import config
from .metrics import combined_weights, effective_weights, max_drawdown, month_starts


@dataclass
class BacktestResult:
    name: str
    value: pd.Series            # account value, USD
    invested: pd.Series         # cumulative contributions, USD
    twr_index: pd.Series        # time-weighted return index (base 100)
    fees: float
    holdings: pd.DataFrame = field(repr=False)  # value per asset at the end of each month

    @property
    def final_value(self) -> float:
        return float(self.value.iloc[-1])

    @property
    def total_invested(self) -> float:
        return float(self.invested.iloc[-1])


def _fee_vector(assets) -> pd.Series:
    return pd.Series({a: config.commission(a) for a in assets})


def _buy_no_sell(units: pd.Series, prices: pd.Series, sleeve: dict, cash: float) -> float:
    """Spend `cash` on the most underweight assets of the sleeve. Returns fees paid."""
    w = effective_weights(sleeve, prices)
    p = prices[w.index]
    v = units[w.index] * p
    total = v.sum() + cash
    gap = (w * total - v).clip(lower=0)
    if gap.sum() <= 0:
        gap = w.copy()
    alloc = cash * gap / gap.sum()
    fee = _fee_vector(w.index)
    units[w.index] += alloc * (1 - fee) / p
    return float((alloc * fee).sum())


def _full_rebalance(units: pd.Series, prices: pd.Series, targets: dict, cash: float) -> float:
    """Add `cash` and trade the whole account back to target weights. Returns fees paid."""
    w = effective_weights(targets, prices)
    held = units[units > 0].index.union(w.index)
    p = prices[held]
    v = units[held] * p
    target = (w.reindex(held).fillna(0.0)) * (v.sum() + cash)
    trade = target - v
    fee = _fee_vector(held)
    sells = (-trade).clip(lower=0)
    buys = trade.clip(lower=0)
    cash_available = cash + float((sells * (1 - fee)).sum())
    scale = cash_available / buys.sum() if buys.sum() > 0 else 0.0
    buys = buys * scale
    units[held] += (buys * (1 - fee) - sells) / p
    return float((sells * fee).sum() + (buys * fee).sum())


def run(prices: pd.DataFrame, strategy: str,
        contribution: float = config.MONTHLY_CONTRIBUTION) -> BacktestResult:
    if strategy == "no_sell":
        sleeves = [(config.PORTFOLIO_A, config.SPLIT["A"]), (config.PORTFOLIO_B, config.SPLIT["B"])]
    elif strategy == "a_only":
        sleeves = [(config.PORTFOLIO_A, 1.0)]
    elif strategy == "b_only":
        sleeves = [(config.PORTFOLIO_B, 1.0)]
    elif strategy == "spy_only":
        sleeves = [({config.BENCHMARK: 1.0}, 1.0)]
    elif strategy == "full_rebalance":
        sleeves = None
    else:
        raise ValueError(strategy)

    targets = combined_weights()
    units = pd.Series(0.0, index=prices.columns)
    contrib_days = set(month_starts(prices.index))
    values, invested, twr = [], [], []
    total_in, fees, prev_value, index_level = 0.0, 0.0, 0.0, 100.0
    month_end_holdings = {}

    for t, row in prices.iterrows():
        p = row.fillna(0.0)
        flow = 0.0
        if t in contrib_days:
            if sleeves is None:
                fees += _full_rebalance(units, row, targets, contribution)
            else:
                for sleeve, share in sleeves:
                    fees += _buy_no_sell(units, row, sleeve, contribution * share)
            total_in += contribution
            flow = contribution
        value = float((units * p).sum())
        # TWR: daily return net of the new money. Commissions lower `value`,
        # so they show up as a loss.
        if prev_value:
            index_level *= (value - flow) / prev_value
        values.append(value)
        invested.append(total_in)
        twr.append(index_level)
        prev_value = value
        month_end_holdings[t] = units * p

    idx = prices.index
    holdings = pd.DataFrame(month_end_holdings).T.resample("ME").last()
    return BacktestResult(strategy, pd.Series(values, idx), pd.Series(invested, idx),
                          pd.Series(twr, idx), fees, holdings)


def xirr(dates: list[pd.Timestamp], flows: list[float]) -> float:
    """Annualized money-weighted return (IRR with irregular dates)."""
    t0 = dates[0]
    years = np.array([(d - t0).days / 365.25 for d in dates])
    f = np.array(flows)
    return brentq(lambda r: (f / (1 + r) ** years).sum(), -0.99, 10.0)


def money_weighted_return(res: BacktestResult) -> float:
    contrib = res.invested.diff().fillna(res.invested.iloc[0])
    contrib = contrib[contrib > 0]
    dates = list(contrib.index) + [res.value.index[-1]]
    flows = list(-contrib.values) + [res.final_value]
    return xirr(dates, flows)


def summarize(results: dict[str, BacktestResult]) -> pd.DataFrame:
    rows = {}
    for name, r in results.items():
        mdd = max_drawdown(r.twr_index)
        years = (r.twr_index.index[-1] - r.twr_index.index[0]).days / 365.25
        rows[name] = {
            "Invested (USD)": r.total_invested,
            "Final value (USD)": r.final_value,
            "Profit (USD)": r.final_value - r.total_invested,
            "Multiple": r.final_value / r.total_invested,
            "Money-weighted return (XIRR)": money_weighted_return(r),
            "Time-weighted CAGR": (r.twr_index.iloc[-1] / 100) ** (1 / years) - 1,
            "Max drawdown (TWR)": mdd["max_drawdown"],
            "Fees paid (USD)": r.fees,
        }
    return pd.DataFrame(rows).T


STRATEGIES = {
    "Your strategy (no selling)": "no_sell",
    "Full rebalance": "full_rebalance",
    "100% SPY": "spy_only",
    "100% A": "a_only",
    "100% B": "b_only",
}


def run_all(prices: pd.DataFrame) -> dict[str, BacktestResult]:
    return {label: run(prices, s) for label, s in STRATEGIES.items()}
