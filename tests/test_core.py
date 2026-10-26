"""Unit tests for the analytical core (no network access needed)."""
import numpy as np
import pandas as pd
import pytest

from src import backtest, cashflows, config, metrics, outlook, scenarios


def bdays(n, start="2022-01-03"):
    return pd.bdate_range(start, periods=n)


# --- metrics -------------------------------------------------------------------------
def test_cagr_doubling_in_one_year():
    s = pd.Series([100.0, 200.0], index=pd.to_datetime(["2022-01-01", "2023-01-01"]))
    assert metrics.cagr(s) == pytest.approx(1.0, rel=1e-3)


def test_max_drawdown_and_recovery():
    idx = bdays(6)
    s = pd.Series([100, 120, 90, 60, 100, 130.0], index=idx)
    mdd = metrics.max_drawdown(s)
    assert mdd["max_drawdown"] == pytest.approx(60 / 120 - 1)
    assert mdd["peak"] == idx[1] and mdd["trough"] == idx[3] and mdd["recovery"] == idx[5]


def test_effective_weights_redistributes_missing_asset():
    w = metrics.effective_weights({"X": 0.5, "Y": 0.25, "Z": 0.25},
                                  pd.Series({"X": np.nan, "Y": 1.0, "Z": 1.0}))
    assert w.to_dict() == {"Y": 0.5, "Z": 0.5}


def test_portfolio_index_constant_prices_is_flat():
    p = pd.DataFrame({"X": 10.0, "Y": 5.0}, index=bdays(40))
    idx = metrics.portfolio_index(p, {"X": 0.6, "Y": 0.4})
    assert np.allclose(idx.values, 100.0)


# --- bond total return -----------------------------------------------------------------
def test_total_return_neutralizes_ex_coupon_drop():
    """If the price drops exactly by the cash flow, total return must be flat."""
    idx = bdays(5, "2025-01-06")  # Mon..Fri; payment on Thu 9-Jan -> ex-date Wed 8-Jan
    price = pd.Series([80, 80, 72, 72, 72.0], index=idx, name="BOND")
    sched = pd.DataFrame({"payment_date": [pd.Timestamp("2025-01-09")], "cash_flow": [8.0]})
    tr, check = cashflows.total_return_index(price, sched)
    assert np.allclose(tr.values, 80.0)
    assert check.iloc[0]["ex_date"] == pd.Timestamp("2025-01-08").date()


def test_al30_schedule_amortization_and_coupons():
    s = cashflows.al30_schedule().set_index("payment_date")
    assert s.loc["2024-07-09", "amortization"] == 4.0
    assert s.loc["2025-01-09", "amortization"] == 8.0
    # coupon accrues on the outstanding balance: 0.75% / 2 on 96
    assert s.loc["2025-01-09", "coupon"] == pytest.approx(96 * 0.0075 / 2)


def test_al35_step_up():
    s = cashflows.al35_schedule().set_index("payment_date")
    assert s.loc["2022-01-09", "coupon"] == pytest.approx(0.5625)
    assert s.loc["2025-01-09", "coupon"] == pytest.approx(2.0625)


# --- yields ----------------------------------------------------------------------------
def test_ytm_par_bond_equals_coupon():
    settle = pd.Timestamp("2026-01-01")
    flows = [("2027-01-01", 6.0), ("2028-01-01", 6.0), ("2029-01-01", 106.0)]
    assert outlook.ytm(100.0, flows, settle) == pytest.approx(0.06, abs=2e-4)


def test_xirr_simple():
    d = [pd.Timestamp("2024-01-01"), pd.Timestamp("2025-01-01")]
    assert backtest.xirr(d, [-100, 110]) == pytest.approx(0.10, abs=2e-3)


# --- backtest --------------------------------------------------------------------------
@pytest.fixture
def flat_prices():
    cols = list(config.PORTFOLIO_A) + list(config.PORTFOLIO_B)
    return pd.DataFrame(1.0, index=pd.bdate_range("2023-01-02", "2023-12-29"), columns=cols)


def test_no_sell_with_flat_prices_hits_targets(flat_prices, monkeypatch):
    monkeypatch.setattr(config, "COMMISSION_DEFAULT", 0.0)
    r = backtest.run(flat_prices, "no_sell")
    assert r.final_value == pytest.approx(r.total_invested)
    last = r.holdings.iloc[-1]
    target = pd.Series(metrics.combined_weights())
    assert np.allclose((last / last.sum())[target.index].values, target.values, atol=1e-9)


def test_commissions_reduce_value(flat_prices):
    r = backtest.run(flat_prices, "no_sell")
    assert r.final_value < r.total_invested
    assert r.fees == pytest.approx(r.total_invested - r.final_value)


def test_full_rebalance_restores_targets_after_shock(monkeypatch):
    monkeypatch.setattr(config, "COMMISSION_DEFAULT", 0.0)
    cols = list(config.PORTFOLIO_A) + list(config.PORTFOLIO_B)
    idx = pd.bdate_range("2023-01-02", "2023-03-31")
    p = pd.DataFrame(1.0, index=idx, columns=cols)
    p.loc["2023-02-15":, "NVDA"] = 3.0  # NVDA triples mid-February
    r = backtest.run(p, "full_rebalance")
    last = r.holdings.iloc[-1]
    assert (last / last.sum())["NVDA"] == pytest.approx(metrics.combined_weights()["NVDA"], abs=1e-9)


# --- scenarios -------------------------------------------------------------------------
def test_drawdown_episodes_detects_two_episodes():
    s = pd.Series([100, 90, 100, 110, 80, 120.0], index=bdays(6))
    ep = scenarios.drawdown_episodes(s, min_depth=0.05)
    assert len(ep) == 2
    assert ep.iloc[0]["depth"] == pytest.approx(80 / 110 - 1)
