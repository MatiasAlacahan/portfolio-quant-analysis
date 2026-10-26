"""Project configuration: portfolios, data sources, proxies and backtest parameters.

Everything a user might want to change lives here.
"""
from pathlib import Path

# --- Paths -----------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"

# --- Analysis window ---------------------------------------------------------
# 5 years. data912 bond history starts 2021-09-16, so this window is fully covered.
START = "2021-10-25"
END = None  # None = latest available date

# Robustness window: starts after the 2023 Argentine rally.
ROBUSTNESS_START = "2024-10-01"

# --- Portfolios (target weights)---------------------------------------------
PORTFOLIO_A = {  # USD income
    "AL35": 0.15,
    "AO27": 0.15,
    "YMCXO": 0.10,   # ON YPF 2031
    "VSCRO": 0.10,   # ON Vista 2031
    "TTCDO": 0.10,   # ON Tecpetrol 2030 (TTCDD/TTCDO matures 3-Nov-2030, not 2034)
    "SPY": 0.20,
    "IEUR": 0.10,
    "FCI_IOL_DAP": 0.10,  # FCI IOL Dólar Ahorro Plus
}

PORTFOLIO_B = {  # Growth
    "QQQ": 0.20,
    "GOOGL": 0.10,
    "NVDA": 0.10,
    "TSM": 0.10,
    "NU": 0.10,
    "VIST": 0.15,
    "BMA": 0.15,
    "TXMD9": 0.10,   # Dual CER/TAMAR bond (ARS)
}

SPLIT = {"A": 0.60, "B": 0.40}

# Assets that start trading inside the window. Until their start date their
# weight is redistributed pro-rata across the rest of the same portfolio.
LATE_START = {"NU": "2021-12-09"}

# --- Data sources ------------------------------------------------------------
YF_TICKERS = ["SPY", "QQQ", "IEUR", "GOOGL", "NVDA", "TSM", "NU", "VIST", "BMA",
              "YPF", "CEMB", "EMB", "BIL", "^IRX"]

DATA912_BONDS = ["AL35D", "AL30D"]  # USD-MEP lines, price per 100 original face value

# Proxy map: which series represents each asset and why (shown in the report).
ASSET_SOURCES = {
    "AL35": {"series": "AL35D_TR", "type": "real",
             "note": "data912 AL35D (USD MEP) + coupons reinvested (total return)."},
    "AO27": {"series": "AL30D_TR", "type": "proxy",
             "note": "No public price history for AO27 (issued 2025). Proxy: AL30D total return "
                     "(Argentine hard-dollar sovereign, same issuer). AL30 matures in 2030 and is "
                     "longer and more volatile than AO27 (2027), so the proxy overstates AO27's volatility."},
    "YMCXO": {"series": "ON_BLEND", "type": "proxy",
              "note": "No public history for this ON. Base proxy: 50% CEMB + 50% AL30D total return "
                      "(AAA Argentine USD corporates sit between EM corporates and the sovereign)."},
    "VSCRO": {"series": "ON_BLEND", "type": "proxy",
              "note": "No public history for this ON. Base proxy: 50% CEMB + 50% AL30D total return."},
    "TTCDO": {"series": "ON_BLEND", "type": "proxy",
              "note": "No public history for this ON. Base proxy: 50% CEMB + 50% AL30D total return."},
    "FCI_IOL_DAP": {"series": "FCI_DAP_SPLICED", "type": "real+proxy",
                    "note": "Real NAV (ArgentinaDatos/CAFCI, Clase D) when available; BIL (US T-bills) before."},
    "TXMD9": {"series": "DUAL_SYNTH_USD", "type": "synthetic",
              "note": "No history (issued 2025). Synthetic: monthly max(CER, TAMAR) accrual in ARS, "
                      "converted to USD at CCL. TAMAR before Oct-2024 = BADLAR + avg spread."},
}
for _t in ["SPY", "IEUR", "QQQ", "GOOGL", "NVDA", "TSM", "NU", "VIST", "BMA"]:
    ASSET_SOURCES[_t] = {"series": _t, "type": "real",
                         "note": "yfinance, dividend-adjusted close (US-listed underlying)."}

# Proxy scenarios for the three ONs (column in extras_usd.csv).
ONS = ["YMCXO", "VSCRO", "TTCDO"]
ON_BLEND_WEIGHTS = {"CEMB": 0.5, "AL30D_TR": 0.5}  # daily-rebalanced blend
ON_SCENARIOS = {
    "base": "ON_BLEND",       # 50% CEMB + 50% AL30D
    "pessimistic": "CEMB",    # EM corporates only
    "sensitivity_EMB": "EMB", # EM sovereigns
}

# FCI share class used (ArgentinaDatos fund name)
FCI_NAME = "IOL Dólar Ahorro Plus - Clase D"

# --- Backtest ----------------------------------------------------------------
MONTHLY_CONTRIBUTION = 200.0  # USD
# Commission per trade (fraction of traded amount). 0.5% + VAT + market fees at IOL.
COMMISSION_DEFAULT = 0.0065
COMMISSION_OVERRIDES = {"FCI_IOL_DAP": 0.0}
BENCHMARK = "SPY"


def commission(asset: str) -> float:
    return COMMISSION_OVERRIDES.get(asset, COMMISSION_DEFAULT)
