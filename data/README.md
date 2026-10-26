# Data / Datos

`raw/` holds cached downloads (re-create with `python main.py --refresh`).
`processed/` holds the analysis-ready series built by `src/proxies.py`.

## Sources / Fuentes

| Input | Source | Notes |
|---|---|---|
| US ETFs & stocks (SPY, QQQ, IEUR, GOOGL, NVDA, TSM, NU, VIST, BMA), CEMB, EMB, BIL, ^IRX | yfinance | Dividend-adjusted close (total return) |
| AL35D, AL30D | data912.com `/historical/bonds/{ticker}` | USD-MEP line, price per 100 of original face value, price only |
| CCL exchange rate | api.argentinadatos.com | `venta` |
| FCI IOL Dólar Ahorro Plus – Clase D NAV | api.argentinadatos.com (CAFCI data) | Sampled weekly; available from Nov-2024 |
| CER (id 30), TAMAR (id 44), BADLAR (id 7) | api.bcra.gob.ar v4.0 | TAMAR published from Oct-2024 |

## What data912 has (checked 2026-10-26)

| Asset | data912 history? | Used |
|---|---|---|
| AL35 (AL35D) | Yes, since 2021-09 | Real data + cash flows |
| AO27 (AO27D) | No (only live quotes) | Proxy: AL30D total return (*) |
| ON YPF 2031 (YMCXD/YMCXO) | No (corporate bonds have no history endpoint) | Proxy: 50% CEMB + 50% AL30D (**) |
| ON Vista 2031 (VSCRD/VSCRO) | No | Same |
| ON Tecpetrol 2030 (TTCDD/TTCDO; matures 3-Nov-2030) | No | Same |
| TXMD9 | No (only live quotes) | Synthetic dual CER/TAMAR |

Note: on BYMA the `O` suffix is the peso line and `D` the USD-MEP line.

(*) AL30 matures in 2030; AO27 in 2027. AL30 is longer and more volatile, so the
proxy **overstates** AO27's volatility and drawdowns.

(**) ON proxy scenarios: **base** = 50% CEMB + 50% AL30D total return (AAA Argentine
USD corporates trade between EM corporates and the Argentine sovereign);
**pessimistic** = CEMB only; **sensitivity** = EMB.

## Bond total return / Retorno total de bonos

data912 prices are **price only** and are quoted per 100 of **original** face value.
On the ex-date (last trading day before payment) the price drops by the coupon +
amortization paid. Ignoring that understates bond returns badly
(AL30D 2021-2026: 9% per year price-only vs 24% per year total return).

We rebuild a total-return index:

```
TR_t = TR_{t-1} × (P_t + CF_t) / P_{t-1}
```

- `CF_t` = cash flow per 100 original face value whose ex-date is `t`
  (schedules in `src/cashflows.py`: step-up coupons for AL35; coupons on
  outstanding capital + 4%/8% amortizations for AL30).
- Ex-date = last trading day before the payment date (verified: the price drop on
  that day matches the scheduled flow, see `processed/bond_cashflow_check.csv`).
- Each cash flow is assumed to be reinvested in the same bond at that day's close.

## Synthetic TXMD9 (dual CER/TAMAR)

Each month the synthetic bond earns the larger of the CER accrual and the TAMAR
accrual (TNA/365 compounded daily), in pesos, then it is converted to USD at the
CCL rate. Before Oct-2024 TAMAR = BADLAR + average TAMAR–BADLAR spread over the
overlap. It captures carry and FX risk but not mark-to-market price risk, so its
volatility is understated.
