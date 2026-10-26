"""Forward-looking view: what is reasonable to expect from today's prices.

Past returns are a poor guide when the starting point was extreme (Argentine
country risk ~1,700 bps in 2021 vs ~700 today). Instead we use simple,
transparent "building blocks" for each asset:

- Bonds / ONs: yield to maturity (TIR) at today's price. This is the return
  if held to maturity and the issuer pays; it is a ceiling, not an average.
- FCI (USD money-market-like fund): its annualized return over the last 26 weeks.
- Equity ETFs: earnings yield (1 / trailing P/E) as a real return + USD inflation.
- Single stocks: CAPM. rf + beta × (expected SPY return − rf), beta measured on
  5 years of weekly returns. No stock-picking alpha is assumed.
- TXMD9 (pesos): real peso yield assuming a flat real exchange rate:
  max((1 + TAMAR) / (1 + inflation) − 1, 0), with TAMAR at its latest value and
  inflation = CER growth over the last 12 months (the CER leg is the floor).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from . import config, metrics

USD_INFLATION = 0.025  # long-run assumption

# Remaining cash flows per 100 original face value (USD).
# Source: Rava Bursátil bond pages, schedules as of 2026-10-25. Verify against the
# prospectus before relying on them.
BOND_FLOWS = {
    "AL35D": [  # Bonar 2035, step-up, amortizes 10% per semester from 2031
        ("2027-01-11", 2.0625), ("2027-07-12", 2.0625), ("2028-01-10", 2.375), ("2028-07-10", 2.375),
        ("2029-01-09", 2.5), ("2029-07-10", 2.5), ("2030-01-09", 2.5), ("2030-07-10", 2.5),
        ("2031-01-09", 12.5), ("2031-07-10", 12.25), ("2032-01-09", 12.0), ("2032-07-12", 11.75),
        ("2033-01-10", 11.5), ("2033-07-11", 11.25), ("2034-01-09", 11.0), ("2034-07-10", 10.75),
        ("2035-01-09", 10.5), ("2035-07-10", 10.25)],
    "AO27D": [  # Bonar 2027, 6% paid monthly, bullet 29-Oct-2027
        ("2026-10-30", 0.5), ("2026-11-30", 0.5), ("2026-12-30", 0.5), ("2027-01-29", 0.5),
        ("2027-02-26", 0.4667), ("2027-03-31", 0.55), ("2027-04-30", 0.5), ("2027-05-31", 0.5),
        ("2027-06-30", 0.5), ("2027-07-30", 0.5), ("2027-08-31", 0.5), ("2027-09-30", 0.5),
        ("2027-10-29", 100.4833)],
    "YMCXD": [  # YPF Clase XXXI, 8.75% semiannual, amortizes 20/20/60 (2029-2031)
        ("2027-03-11", 4.375), ("2027-09-11", 4.375), ("2028-03-11", 4.375), ("2028-09-11", 4.375),
        ("2029-03-11", 4.375), ("2029-09-11", 24.375), ("2030-03-11", 3.5), ("2030-09-11", 23.5),
        ("2031-03-11", 2.625), ("2031-09-11", 62.625)],
    "VSCRD": [  # Vista 2031, 7.65% semiannual, amortizes 33/33/34 (2029-2031)
        ("2027-04-12", 3.8145), ("2027-10-12", 3.8355), ("2028-04-10", 3.8355), ("2028-10-10", 3.8355),
        ("2029-04-10", 3.8145), ("2029-10-10", 36.8355), ("2030-04-10", 2.5557), ("2030-10-10", 35.5698),
        ("2031-04-14", 1.2969), ("2031-10-10", 35.3041)],
    "TTCDD": [  # Tecpetrol 2030 (not 2034), 7.625% semiannual, bullet 3-Nov-2030
        ("2026-11-03", 3.8125), ("2027-05-03", 3.8125), ("2027-11-03", 3.8125), ("2028-05-03", 3.8125),
        ("2028-11-03", 3.8125), ("2029-05-03", 3.8125), ("2029-11-05", 3.8125), ("2030-05-03", 3.8125),
        ("2030-11-04", 103.8125)],
}
ASSET_TO_BOND = {"AL35": "AL35D", "AO27": "AO27D", "YMCXO": "YMCXD", "VSCRO": "VSCRD", "TTCDO": "TTCDD"}
# Reference TIRs published by Rava on 2026-10-26 (cross-check only).
RAVA_TIR = {"AL35D": 0.1248, "AO27D": 0.0276, "YMCXD": 0.0653, "VSCRD": 0.0604, "TTCDD": 0.0612}

ETFS = ["SPY", "QQQ", "IEUR"]
STOCKS = ["GOOGL", "NVDA", "TSM", "NU", "VIST", "BMA"]


# --- bonds -----------------------------------------------------------------------
def ytm(price: float, flows: list[tuple[str, float]], settle: pd.Timestamp) -> float:
    """Effective annual yield (Act/365) that discounts future flows to `price`."""
    t = np.array([(pd.Timestamp(d) - settle).days / 365 for d, _ in flows])
    cf = np.array([c for _, c in flows])
    keep = t > 0
    t, cf = t[keep], cf[keep]
    return brentq(lambda y: (cf / (1 + y) ** t).sum() - price, -0.5, 2.0)


def modified_duration(price: float, flows, settle: pd.Timestamp) -> float:
    y = ytm(price, flows, settle)
    t = np.array([(pd.Timestamp(d) - settle).days / 365 for d, _ in flows])
    cf = np.array([c for _, c in flows])
    keep = t > 0
    pv = cf[keep] / (1 + y) ** t[keep]
    return float((t[keep] * pv).sum() / pv.sum() / (1 + y))


def bond_yields(live: pd.DataFrame) -> pd.DataFrame:
    as_of = pd.Timestamp(live["as_of"].iloc[0][:10])
    settle = as_of + pd.offsets.BDay(1)  # T+1
    rows = {}
    for asset, sym in ASSET_TO_BOND.items():
        price = float(live.loc[sym, "mid"])
        flows = BOND_FLOWS[sym]
        rows[asset] = {"symbol": sym, "price": price, "ytm": ytm(price, flows, settle),
                       "mod_duration": modified_duration(price, flows, settle),
                       "maturity": flows[-1][0], "rava_tir": RAVA_TIR.get(sym)}
    return pd.DataFrame(rows).T


# --- other assets ------------------------------------------------------------------
def betas(prices: pd.DataFrame, market: str = "SPY") -> pd.Series:
    w = metrics.weekly_returns(prices)
    var = w[market].var()
    return w.apply(lambda s: s.cov(w[market]) / var)


def fci_recent_yield(nav: pd.Series, weeks: int = 26) -> float:
    s = nav.dropna().sort_index()
    start = s.loc[: s.index[-1] - pd.Timedelta(weeks=weeks)]
    first = start.iloc[-1] if len(start) else s.iloc[0]
    first_date = start.index[-1] if len(start) else s.index[0]
    days = (s.index[-1] - first_date).days
    return (s.iloc[-1] / first) ** (365 / days) - 1


def dual_bond_real_yield(tamar: pd.Series, cer: pd.Series) -> dict:
    tna = float(tamar.dropna().iloc[-1]) / 100
    tamar_eff = (1 + tna / 12) ** 12 - 1  # monthly capitalization
    c = cer.dropna()
    infl = float(c.iloc[-1] / c.loc[: c.index[-1] - pd.Timedelta(days=365)].iloc[-1] - 1)
    # The dual bond pays the better of the two legs, so the CER leg is a floor
    # at ~0% real (ignoring the small real coupon and the purchase price).
    return {"tamar_tna": tna, "tamar_effective": tamar_eff, "inflation_12m": infl,
            "tamar_real": (1 + tamar_eff) / (1 + infl) - 1,
            "real_yield": max((1 + tamar_eff) / (1 + infl) - 1, 0.0)}


# --- putting it together --------------------------------------------------------------
def expected_returns(prices: pd.DataFrame, raw: dict, live: pd.DataFrame,
                     valuation: pd.DataFrame, rf_now: float) -> tuple[pd.DataFrame, dict]:
    bonds = bond_yields(live)
    rows = {}
    for asset, r in bonds.iterrows():
        note = f"TIR at {r.price:.2f} ({r.symbol}), duration {r.mod_duration:.1f}"
        rows[asset] = (r.ytm, "Bond yield to maturity", note)

    fci = fci_recent_yield(raw["fci"])
    rows["FCI_IOL_DAP"] = (fci, "Recent fund yield", "Last 26 weeks, annualized")

    for t in ETFS:
        pe = float(valuation.loc[t, "trailingPE"])
        rows[t] = (1 / pe + USD_INFLATION, "Earnings yield + inflation",
                   f"P/E {pe:.1f} → {1/pe:.1%} real + {USD_INFLATION:.1%}")
    spy_er = rows["SPY"][0]

    b = betas(prices)
    for t in STOCKS:
        er = rf_now + b[t] * (spy_er - rf_now)
        rows[t] = (er, "CAPM", f"beta {b[t]:.2f} vs SPY (5y weekly)")

    dual = dual_bond_real_yield(raw["tamar"], raw["cer"])
    rows["TXMD9"] = (dual["real_yield"], "Real peso yield, flat real FX",
                     f"TAMAR {dual['tamar_effective']:.1%} eff. vs inflation {dual['inflation_12m']:.1%}")

    er = pd.DataFrame(rows, index=["expected_return", "method", "detail"]).T
    er["expected_return"] = er["expected_return"].astype(float)
    return er, {"bonds": bonds, "dual": dual, "betas": b, "rf_now": rf_now, "spy_er": spy_er}


def covariance(prices: pd.DataFrame, bonds: pd.DataFrame,
               start: str = config.ROBUSTNESS_START) -> pd.DataFrame:
    """Forward-looking covariance (annualized, weekly returns).

    - Estimated on the recent window only (current country-risk regime, not 2022).
    - AO27's history is a proxy (AL30) with a much longer duration, so its volatility
      is rescaled from AL35 (same issuer, real data) by the duration ratio:
      price vol ≈ modified duration × yield vol. Correlations are kept.
    """
    cov = metrics.weekly_returns(prices.loc[start:]).cov() * 52
    vol = pd.Series(np.sqrt(np.diag(cov)), index=cov.index)
    corr = cov / np.outer(vol, vol)
    vol["AO27"] = vol["AL35"] * bonds.loc["AO27", "mod_duration"] / bonds.loc["AL35", "mod_duration"]
    return corr * np.outer(vol, vol)


def portfolio_expectations(er: pd.Series, cov: pd.DataFrame, rf_now: float,
                           history: pd.DataFrame) -> pd.DataFrame:
    rows = {}
    for name, w in {**metrics.PORTFOLIOS, "SPY": {"SPY": 1.0}}.items():
        w = pd.Series(w, dtype=float)
        mu = float((w * er[w.index]).sum())
        vol = float(np.sqrt(w @ cov.loc[w.index, w.index] @ w))
        rows[name] = {"Expected return": mu, "Expected volatility": vol,
                      "Expected Sharpe": (mu - rf_now) / vol,
                      "Past 5y CAGR": history.loc[name, "CAGR"]}
    return pd.DataFrame(rows).T


def simulate_plan(mu: float, vol: float, years: int = 5, monthly: float = config.MONTHLY_CONTRIBUTION,
                  n: int = 10_000, seed: int = 42) -> dict:
    """Monte Carlo of the monthly-contribution plan with lognormal returns."""
    rng = np.random.default_rng(seed)
    months = years * 12
    m_mu = (np.log(1 + mu) - vol ** 2 / 2) / 12
    m_sd = vol / np.sqrt(12)
    growth = np.exp(rng.normal(m_mu, m_sd, size=(n, months)))
    value = np.zeros(n)
    fee = config.COMMISSION_DEFAULT
    for m in range(months):
        value = (value + monthly * (1 - fee)) * growth[:, m]
    invested = monthly * months
    return {"invested": invested, "p10": float(np.percentile(value, 10)),
            "p50": float(np.percentile(value, 50)), "p90": float(np.percentile(value, 90)),
            "prob_loss": float((value < invested).mean())}
