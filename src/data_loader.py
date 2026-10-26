"""Download raw data from public sources and cache it in data/raw/.

Sources
- yfinance: US-listed ETFs/stocks (dividend-adjusted), proxies and the T-bill rate.
- data912.com: daily history of Argentine sovereign bonds (USD-MEP lines).
- api.argentinadatos.com: CCL exchange rate and daily FCI NAVs (from CAFCI).
- api.bcra.gob.ar: CER index, TAMAR and BADLAR rates.

Every loader reads the cached CSV when it exists, unless refresh=True.
"""
from __future__ import annotations

import time
import warnings

import pandas as pd
import requests

from . import config

warnings.filterwarnings("ignore", category=FutureWarning)
try:  # pandas >= 3.1 deprecation warnings raised inside yfinance
    warnings.filterwarnings("ignore", category=pd.errors.Pandas4Warning)
except AttributeError:
    pass

HEADERS = {"User-Agent": "portfolio-quant-analysis/1.0 (research project)"}


def _get_json(url: str, params: dict | None = None, retries: int = 3):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def _cache(name: str):
    config.DATA_RAW.mkdir(parents=True, exist_ok=True)
    return config.DATA_RAW / f"{name}.csv"


def _read_cache(path) -> pd.DataFrame:
    return pd.read_csv(path, index_col=0, parse_dates=True)


# --- yfinance ------------------------------------------------------------------
def load_yfinance(refresh: bool = False) -> pd.DataFrame:
    path = _cache("yfinance_adj_close")
    if path.exists() and not refresh:
        return _read_cache(path)
    start = (pd.Timestamp(config.START) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    # yfinance's `end` is exclusive: default to today so a still-open session is left out.
    end = config.END or pd.Timestamp.today().strftime("%Y-%m-%d")
    # yfinance emits pandas deprecation warnings that are not ours to fix.
    warnings.filterwarnings("ignore", module=r"yfinance")
    import yfinance as yf
    df = yf.download(config.YF_TICKERS, start=start, end=end, auto_adjust=True,
                     progress=False, threads=False)["Close"]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.to_csv(path)
    return df


# --- data912 -------------------------------------------------------------------
def load_data912_bond(ticker: str, refresh: bool = False) -> pd.DataFrame:
    path = _cache(f"data912_{ticker}")
    if path.exists() and not refresh:
        return _read_cache(path)
    data = _get_json(f"https://data912.com/historical/bonds/{ticker}")
    if not isinstance(data, list):
        raise ValueError(f"data912 has no history for {ticker}: {data}")
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")[["o", "h", "l", "c", "v"]].sort_index()
    df.to_csv(path)
    return df


def data912_has_history(ticker: str) -> bool:
    data = _get_json(f"https://data912.com/historical/bonds/{ticker}")
    return isinstance(data, list) and len(data) > 0


# --- ArgentinaDatos --------------------------------------------------------------
def load_ccl(refresh: bool = False) -> pd.Series:
    path = _cache("ccl")
    if path.exists() and not refresh:
        return _read_cache(path)["ccl"]
    data = _get_json("https://api.argentinadatos.com/v1/cotizaciones/dolares/contadoconliqui")
    df = pd.DataFrame(data)
    df["fecha"] = pd.to_datetime(df["fecha"])
    s = df.set_index("fecha")["venta"].astype(float).rename("ccl").sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s.to_frame().to_csv(path)
    return s


def load_fci_nav(fund_name: str = config.FCI_NAME, refresh: bool = False,
                 first_date: str = "2024-06-01", freq: str = "W-FRI") -> pd.Series:
    """Fund NAV (cuotaparte) sampled weekly from ArgentinaDatos' daily snapshots.

    The API only serves one date per request, so we sample Fridays (falling back
    to the previous 3 days when a snapshot is missing) and cache incrementally.
    """
    path = _cache("fci_iol_dolar_ahorro_plus")
    cached = _read_cache(path)["vcp"] if path.exists() else pd.Series(dtype=float, name="vcp")
    if not refresh and path.exists():
        # only fetch dates after the last cached one
        first_date = (cached.index.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    dates = pd.date_range(first_date, pd.Timestamp.today().normalize(), freq=freq)
    new = {}
    for d in dates:
        for lag in range(4):
            day = d - pd.Timedelta(days=lag)
            data = _get_json(f"https://api.argentinadatos.com/v1/finanzas/fci/rentaFija/"
                             f"{day:%Y/%m/%d}")
            time.sleep(0.15)
            if not data:
                continue
            hit = [x for x in data if x.get("fondo") == fund_name and x.get("vcp")]
            if hit:
                new[pd.Timestamp(hit[0].get("fecha") or day)] = float(hit[0]["vcp"])
                break
    s = pd.concat([cached, pd.Series(new, name="vcp", dtype=float)]).sort_index()
    s = s[~s.index.duplicated(keep="last")].rename("vcp")
    s.index.name = "date"
    s.to_frame().to_csv(path)
    return s


# --- BCRA ----------------------------------------------------------------------
BCRA_IDS = {"cer": 30, "tamar": 44, "badlar": 7}


def load_bcra(name: str, refresh: bool = False) -> pd.Series:
    path = _cache(f"bcra_{name}")
    if path.exists() and not refresh:
        return _read_cache(path)[name]
    var_id = BCRA_IDS[name]
    desde = (pd.Timestamp(config.START) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    hasta = pd.Timestamp.today().strftime("%Y-%m-%d")
    rows, offset = [], 0
    while True:
        data = _get_json(f"https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/{var_id}",
                         params={"desde": desde, "hasta": hasta, "limit": 3000, "offset": offset})
        detalle = data["results"][0]["detalle"] if data and data.get("results") else []
        rows += detalle
        if len(detalle) < 3000:
            break
        offset += 3000
    df = pd.DataFrame(rows)
    df["fecha"] = pd.to_datetime(df["fecha"])
    s = df.set_index("fecha")["valor"].astype(float).sort_index().rename(name)
    s = s[~s.index.duplicated(keep="last")]
    s.to_frame().to_csv(path)
    return s


def load_riesgo_pais(refresh: bool = False) -> pd.Series:
    """JP Morgan EMBI Argentina spread (basis points), via ArgentinaDatos."""
    path = _cache("riesgo_pais")
    if path.exists() and not refresh:
        return _read_cache(path)["embi_bps"]
    data = _get_json("https://api.argentinadatos.com/v1/finanzas/indices/riesgo-pais")
    df = pd.DataFrame(data)
    df["fecha"] = pd.to_datetime(df["fecha"])
    s = df.set_index("fecha")["valor"].astype(float).rename("embi_bps").sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s.to_frame().to_csv(path)
    return s


def load_live_bond_prices(tickers, refresh: bool = False) -> pd.DataFrame:
    """Snapshot of current bond prices (USD-MEP lines) from data912, with a timestamp."""
    path = _cache("live_bond_prices")
    if path.exists() and not refresh:
        return pd.read_csv(path, index_col=0)
    rows = []
    for endpoint in ("arg_bonds", "arg_corp"):
        for x in _get_json(f"https://data912.com/live/{endpoint}") or []:
            if x["symbol"] in tickers:
                mid = (x["px_bid"] + x["px_ask"]) / 2 if x["px_bid"] and x["px_ask"] else x["c"]
                rows.append({"symbol": x["symbol"], "bid": x["px_bid"], "ask": x["px_ask"],
                             "last": x["c"], "mid": mid,
                             "as_of": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")})
    df = pd.DataFrame(rows).set_index("symbol")
    df.to_csv(path)
    return df


def load_valuation(tickers, refresh: bool = False) -> pd.DataFrame:
    """Trailing P/E and dividend yield from yfinance (used for ETF expected returns)."""
    path = _cache("valuation")
    if path.exists() and not refresh:
        return pd.read_csv(path, index_col=0)
    warnings.filterwarnings("ignore", module=r"yfinance")
    import yfinance as yf
    rows = {}
    for t in tickers:
        info = yf.Ticker(t).info
        rows[t] = {"trailingPE": info.get("trailingPE"), "forwardPE": info.get("forwardPE"),
                   "dividend_yield": info.get("yield") or (info.get("dividendYield") or 0) / 100,
                   "as_of": pd.Timestamp.today().strftime("%Y-%m-%d")}
    df = pd.DataFrame(rows).T
    df.to_csv(path)
    return df


def load_all(refresh: bool = False) -> dict:
    """Download (or read from cache) every raw input."""
    raw = {"yf": load_yfinance(refresh)}
    raw["riesgo_pais"] = load_riesgo_pais(refresh)
    for t in config.DATA912_BONDS:
        raw[t] = load_data912_bond(t, refresh)
    raw["ccl"] = load_ccl(refresh)
    raw["fci"] = load_fci_nav(refresh=refresh)
    for name in BCRA_IDS:
        raw[name] = load_bcra(name, refresh)
    return raw
