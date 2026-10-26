"""Bond cash-flow schedules and total-return indices.

Argentine bonds on BYMA are quoted per 100 of ORIGINAL face value, and the
price drops on the ex-date (the last trading day before the payment date)
by the amount of coupon + amortization paid. A price-only series therefore
understates the return of a bond portfolio. This module rebuilds the
total-return (TR) index:

    TR_t = TR_{t-1} * (P_t + CF_t) / P_{t-1}

where CF_t is the cash flow (per 100 original face value) whose ex-date is t.
This assumes every cash flow is reinvested in the same bond at the close.
"""
from __future__ import annotations

import pandas as pd


def build_schedule(payment_dates: list[str],
                   coupon_rate_by_period_end: dict[str, float],
                   amortization: dict[str, float]) -> pd.DataFrame:
    """Return a schedule with coupon, amortization and total flow per 100 VN original.

    coupon_rate_by_period_end: annual coupon rate (in %) that applies to the
        accrual period ending on each payment date (semiannual coupons).
    amortization: % of original face value repaid on each payment date.
    """
    outstanding = 100.0
    rows = []
    for d in payment_dates:
        rate = coupon_rate_by_period_end[d]
        coupon = outstanding * rate / 100 / 2
        amort = amortization.get(d, 0.0)
        rows.append({"payment_date": pd.Timestamp(d), "coupon": coupon,
                     "amortization": amort, "cash_flow": coupon + amort,
                     "outstanding_before": outstanding})
        outstanding -= amort
    return pd.DataFrame(rows)


def _semiannual(start_year: int, end_year: int) -> list[str]:
    return [f"{y}-{m}-09" for y in range(start_year, end_year + 1) for m in ("01", "07")]


def al35_schedule() -> pd.DataFrame:
    """Bonar 2035 (AL35 / GD35). Step-up coupon, bullet-like until 2031."""
    # Accrual periods run 9-Jul to 9-Jul, so both the Jan-YYYY and the Jul-YYYY
    # payments belong to the period ending Jul-YYYY.
    step_up = {2022: 1.125, 2023: 1.5, 2024: 3.625}  # 4.125% from Jul-2024 to Jul-2027
    dates = _semiannual(2022, 2027)
    rates = {d: step_up.get(int(d[:4]), 4.125) for d in dates}
    return build_schedule(dates, rates, amortization={})


def al30_schedule() -> pd.DataFrame:
    """Bonar 2030 (AL30 / GD30). Amortizes 4% Jul-2024 then 8% every semester."""
    dates = _semiannual(2022, 2027)
    # 0.5% for periods ending Jul-2022/Jul-2023, 0.75% from then to Jul-2027.
    rates = {d: 0.5 if int(d[:4]) <= 2023 else 0.75 for d in dates}
    amort = {"2024-07-09": 4.0}
    for d in dates:
        if pd.Timestamp(d) > pd.Timestamp("2024-07-09"):
            amort[d] = 8.0
    return build_schedule(dates, rates, amort)


SCHEDULES = {"AL35D": al35_schedule, "AL30D": al30_schedule}


def ex_dates(prices: pd.Series, payment_dates: pd.Series) -> pd.Series:
    """Map each payment date to its ex-date: the last trading day before payment."""
    idx = prices.dropna().index
    out = {}
    for pd_ in payment_dates:
        prior = idx[idx < pd_]
        if len(prior) and prior[-1] >= idx[0]:
            out[pd_] = prior[-1]
    return pd.Series(out)


def total_return_index(prices: pd.Series, schedule: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """Build the TR index (base = first price) and a validation table.

    The validation table compares, on each ex-date, the price drop with the
    scheduled cash flow. A drop close to the cash flow confirms both the
    schedule and the ex-date rule.
    """
    p = prices.dropna().sort_index()
    sched = schedule[(schedule.payment_date > p.index[0]) &
                     (schedule.payment_date <= p.index[-1] + pd.Timedelta(days=5))]
    exd = ex_dates(p, sched.payment_date)
    cf = pd.Series(0.0, index=p.index)
    rows = []
    for _, r in sched.iterrows():
        if r.payment_date not in exd.index:
            continue
        e = exd[r.payment_date]
        cf[e] += r.cash_flow
        i = p.index.get_loc(e)
        prev = p.iloc[i - 1] if i > 0 else float("nan")
        rows.append({"payment_date": r.payment_date.date(), "ex_date": e.date(),
                     "cash_flow": round(r.cash_flow, 4),
                     "price_before": prev, "price_ex": p.iloc[i],
                     "price_drop": round(prev - p.iloc[i], 4)})
    gross = (p + cf) / p.shift(1)
    gross.iloc[0] = 1.0
    tr = p.iloc[0] * gross.cumprod()
    return tr.rename(f"{prices.name}_TR"), pd.DataFrame(rows)
