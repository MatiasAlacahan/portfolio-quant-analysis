"""Turn raw inputs into one daily USD total-return index per portfolio asset.

Output: data/processed/prices_usd.csv (index = NYSE trading days, base 100 at START)
plus a coverage table explaining where each series comes from.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import cashflows, config


# --- helpers -------------------------------------------------------------------
def clean_spikes(p: pd.Series, threshold: float = 0.15) -> pd.Series:
    """Drop one-day spikes typical of illiquid prints: a big move that fully
    reverses the next day. Genuine ex-coupon drops don't reverse, so they stay."""
    p = p.dropna().copy()
    r = p.pct_change()
    nxt = r.shift(-1)
    spike = (r.abs() > threshold) & (nxt.abs() > threshold) & (np.sign(r) != np.sign(nxt))
    p[spike] = np.nan
    return p.ffill()


def to_calendar(s: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    """Align a series to the trading calendar, carrying the last known value."""
    s = s.dropna().sort_index()
    return s.reindex(s.index.union(calendar)).ffill().reindex(calendar)


def splice(real: pd.Series, proxy: pd.Series) -> pd.Series:
    """Use proxy returns before the first real observation, real data after.
    Levels are chained so the series has no jump at the splice date."""
    real = real.dropna()
    first = real.index[0]
    head = proxy[proxy.index <= first].dropna()
    head = head / head.iloc[-1] * real.iloc[0]
    return pd.concat([head[head.index < first], real]).sort_index()


def geometric_interpolate(s: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    """Log-linear interpolation of a low-frequency NAV onto daily dates."""
    s = s.dropna().sort_index()
    idx = s.index.union(calendar)
    out = np.exp(np.log(s).reindex(idx).interpolate(method="time"))
    return out.reindex(calendar)


def blend(panel: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Daily-rebalanced blend of several total-return series (base 100)."""
    r = sum(w * panel[k].pct_change() for k, w in weights.items()).fillna(0.0)
    return 100 * (1 + r).cumprod()


def apply_on_scenario(prices: pd.DataFrame, extras: pd.DataFrame, scenario: str) -> pd.DataFrame:
    """Return a copy of `prices` with the three ONs replaced by the scenario's proxy."""
    col = config.ON_SCENARIOS[scenario]
    out = prices.copy()
    s = extras[col] / extras[col].dropna().iloc[0] * 100
    for on in config.ONS:
        out[on] = s
    return out


# --- asset builders --------------------------------------------------------------
def bond_total_return(raw_bond: pd.DataFrame, ticker: str):
    price = clean_spikes(raw_bond["c"].rename(ticker))
    schedule = cashflows.SCHEDULES[ticker]()
    tr, check = cashflows.total_return_index(price, schedule)
    return price, tr, check


def fci_spliced(nav: pd.Series, bil: pd.Series, calendar: pd.DatetimeIndex) -> pd.Series:
    real = geometric_interpolate(nav, calendar[calendar >= nav.dropna().index[0]])
    return splice(real.dropna(), bil.reindex(calendar).ffill())


def tamar_series(tamar: pd.Series, badlar: pd.Series) -> tuple[pd.Series, float]:
    """TAMAR (TNA %, private banks). Before it is published, BADLAR + average spread."""
    overlap = pd.concat([tamar, badlar], axis=1, keys=["t", "b"]).dropna()
    spread = float((overlap.t - overlap.b).mean())
    filled = tamar.combine_first(badlar + spread).sort_index()
    return filled, spread


def dual_cer_tamar_usd(cer: pd.Series, tamar: pd.Series, ccl: pd.Series,
                       calendar: pd.DatetimeIndex) -> tuple[pd.Series, pd.DataFrame]:
    """Synthetic dual CER/TAMAR bond, in USD.

    Each calendar month the holder earns whichever leg accrued more:
      - CER leg: CER_end / CER_start
      - TAMAR leg: compounded daily at TNA/365
    The ARS index is then divided by the CCL rate to get USD.
    """
    days = pd.date_range(min(cer.index.min(), tamar.index.min()), calendar.max(), freq="D")
    cer_d = cer.reindex(days).interpolate(method="time").ffill()
    tamar_d = tamar.reindex(days).ffill()
    f_cer = cer_d / cer_d.shift(1)
    f_tam = 1 + tamar_d / 100 / 365
    month = days.to_period("M")
    m_cer = f_cer.groupby(month).prod()
    m_tam = f_tam.groupby(month).prod()
    use_cer = (m_cer >= m_tam)
    chosen = pd.Series(np.where(use_cer.reindex(month).values, f_cer.values, f_tam.values),
                       index=days).fillna(1.0)
    ars_index = chosen.cumprod()
    usd = ars_index / ccl.reindex(days).ffill()
    legs = pd.DataFrame({"cer_leg": m_cer, "tamar_leg": m_tam, "winner": np.where(use_cer, "CER", "TAMAR")})
    return to_calendar(usd.dropna(), calendar), legs


# --- main ----------------------------------------------------------------------
def build_prices(raw: dict) -> dict:
    yf = raw["yf"]
    start = pd.Timestamp(config.START)
    end = pd.Timestamp(config.END) if config.END else yf["SPY"].dropna().index.max()
    calendar = yf["SPY"].dropna().loc[start:end].index

    series: dict[str, pd.Series] = {}
    for t in ["SPY", "IEUR", "QQQ", "GOOGL", "NVDA", "TSM", "NU", "VIST", "BMA",
              "CEMB", "EMB", "BIL", "YPF"]:
        series[t] = yf[t]

    bond_checks, bond_prices = {}, {}
    for t in config.DATA912_BONDS:
        price, tr, check = bond_total_return(raw[t], t)
        series[f"{t}_TR"] = tr
        series[f"{t}_PRICE"] = price
        bond_prices[t] = price
        bond_checks[t] = check

    series["FCI_DAP_SPLICED"] = fci_spliced(raw["fci"], yf["BIL"], calendar)

    tamar, spread = tamar_series(raw["tamar"], raw["badlar"])
    series["DUAL_SYNTH_USD"], dual_legs = dual_cer_tamar_usd(raw["cer"], tamar, raw["ccl"], calendar)

    panel = pd.DataFrame({k: to_calendar(v, calendar) for k, v in series.items()})
    panel["ON_BLEND"] = blend(panel, config.ON_BLEND_WEIGHTS)

    # Asset-level panel (one column per portfolio asset) + alternatives
    assets = {}
    for asset, meta in config.ASSET_SOURCES.items():
        assets[asset] = panel[meta["series"]]
    prices = pd.DataFrame(assets)
    # NU: keep NaN before its IPO; the backtest redistributes its weight.
    for asset, first in config.LATE_START.items():
        prices.loc[prices.index < pd.Timestamp(first), asset] = np.nan
    prices = prices / prices.apply(lambda s: s.dropna().iloc[0]) * 100

    extras = panel[["ON_BLEND", "CEMB", "EMB", "BIL", "AL35D_PRICE", "AL30D_PRICE", "AL35D_TR", "AL30D_TR"]]
    rf = (to_calendar(yf["^IRX"], calendar) / 100).rename("rf_annual")

    coverage = coverage_table(raw, prices, calendar)

    config.DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    prices.to_csv(config.DATA_PROCESSED / "prices_usd.csv")
    extras.to_csv(config.DATA_PROCESSED / "extras_usd.csv")
    rf.to_frame().to_csv(config.DATA_PROCESSED / "risk_free.csv")
    coverage.to_csv(config.DATA_PROCESSED / "coverage.csv", index=False)
    pd.concat(bond_checks, names=["bond"]).to_csv(config.DATA_PROCESSED / "bond_cashflow_check.csv")
    dual_legs.to_csv(config.DATA_PROCESSED / "dual_bond_legs.csv")

    return {"prices": prices, "extras": extras, "rf": rf, "coverage": coverage,
            "bond_checks": bond_checks, "dual_legs": dual_legs, "tamar_spread": spread}


def coverage_table(raw: dict, prices: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """For each asset: source type, first date of *real* data and share of window covered."""
    real_first = {t: raw["yf"][t].dropna().index[0] for t in
                  ["SPY", "IEUR", "QQQ", "GOOGL", "NVDA", "TSM", "NU", "VIST", "BMA"]}
    real_first["AL35"] = raw["AL35D"].index[0]
    real_first["FCI_IOL_DAP"] = raw["fci"].dropna().index[0]
    rows = []
    n = len(calendar)
    for asset, meta in config.ASSET_SOURCES.items():
        first = real_first.get(asset)
        share = (calendar >= first).sum() / n if first is not None else 0.0
        rows.append({"asset": asset, "source_type": meta["type"], "series": meta["series"],
                     "first_real_date": first.date() if first is not None else None,
                     "real_data_share": round(float(share), 3), "note": meta["note"]})
    return pd.DataFrame(rows)
