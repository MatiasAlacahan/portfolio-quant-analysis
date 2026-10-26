"""Run the full pipeline: data -> metrics & backtest -> robustness & outlook -> stress
scenarios -> HTML report.

    python main.py            # use cached data when available
    python main.py --refresh  # re-download everything (prices, live bond quotes, valuations)
"""
import argparse

import numpy as np
import pandas as pd

from src import (backtest, config, data_loader, figures, metrics, outlook, proxies, report,
                 robustness, scenarios)

pd.set_option("display.width", 170)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_colwidth", 70)

TABLES = config.REPORTS / "tables"
FIGS = config.REPORTS / "figures"


def _fmt(df: pd.DataFrame, pct_cols=(), money_cols=(), num_cols=()) -> pd.DataFrame:
    out = df.copy().astype(object)
    for c in pct_cols:
        out[c] = df[c].map(lambda x: f"{x:.1%}")
    for c in money_cols:
        out[c] = df[c].map(lambda x: f"{x:,.0f}")
    for c in num_cols:
        out[c] = df[c].map(lambda x: f"{x:.2f}")
    return out


METRIC_PCT = ["CAGR", "Volatility", "Max drawdown", "Best month", "Worst month", "% positive months"]
BT_PCT = ["Money-weighted return (XIRR)", "Time-weighted CAGR", "Max drawdown (TWR)"]
BT_MONEY = ["Invested (USD)", "Final value (USD)", "Profit (USD)", "Fees paid (USD)"]


# --- Stage 1 ------------------------------------------------------------------------
def stage_data(refresh: bool) -> dict:
    print("== Stage 1: data ==")
    raw = data_loader.load_all(refresh=refresh)
    built = proxies.build_prices(raw)
    built["raw"] = raw
    p = built["prices"]
    print(f"Window: {p.index[0].date()} -> {p.index[-1].date()} ({len(p)} trading days)")
    print(built["coverage"][["asset", "source_type", "series", "first_real_date", "real_data_share"]]
          .to_string(index=False))
    return built


# --- Stage 2 ------------------------------------------------------------------------
def stage_analysis(built: dict) -> dict:
    print("\n== Stage 2: metrics and backtest ==")
    TABLES.mkdir(parents=True, exist_ok=True)
    prices, extras, rf = built["prices"], built["extras"], built["rf"]

    idx = metrics.portfolio_indices(prices)
    summ = metrics.summary(idx, rf)
    summ.to_csv(TABLES / "portfolio_metrics.csv")
    print(_fmt(summ, pct_cols=METRIC_PCT, num_cols=["Sharpe", "Sortino", "Calmar"]).to_string())

    corr = metrics.correlation_matrix(prices)
    corr.to_csv(TABLES / "asset_correlations.csv")
    ab = metrics.correlation_matrix(idx[["A (income)", "B (growth)", "SPY"]])
    roll = metrics.rolling_correlation(idx["A (income)"], idx["B (growth)"])
    print("\nWeekly correlation A/B/SPY:\n" + ab.round(2).to_string())

    results = backtest.run_all(prices)
    bt = backtest.summarize(results)
    bt.to_csv(TABLES / "backtest_summary.csv")
    print("\nBacktest:\n" + _fmt(bt, BT_PCT, BT_MONEY, ["Multiple"]).to_string())
    values = pd.DataFrame({k: r.value for k, r in results.items()})
    values.to_csv(TABLES / "backtest_values.csv")

    rows = {}
    for scen in config.ON_SCENARIOS:
        p = proxies.apply_on_scenario(prices, extras, scen)
        i = metrics.portfolio_indices(p)
        s = metrics.summary(i[["A (income)", "Combined 60/40"]], rf)
        r = backtest.run(p, "no_sell")
        rows[scen] = {"A CAGR": s.loc["A (income)", "CAGR"],
                      "A max DD": s.loc["A (income)", "Max drawdown"],
                      "A Sharpe": s.loc["A (income)", "Sharpe"],
                      "60/40 CAGR": s.loc["Combined 60/40", "CAGR"],
                      "60/40 Sharpe": s.loc["Combined 60/40", "Sharpe"],
                      "Backtest final (USD)": r.final_value,
                      "Backtest XIRR": backtest.money_weighted_return(r)}
    scen_df = pd.DataFrame(rows).T
    scen_df.to_csv(TABLES / "on_proxy_scenarios.csv")

    FIGS.mkdir(parents=True, exist_ok=True)
    figures.growth_chart(idx, FIGS / "growth.png")
    figures.backtest_chart(values, results["100% SPY"].invested, FIGS / "backtest.png")
    figures.drawdown_chart(idx, FIGS / "drawdowns.png")

    return {"indices": idx, "summary": summ, "corr": corr, "corr_ab": ab, "rolling_ab": roll,
            "results": results, "backtest": bt, "values": values, "on_scenarios": scen_df}


# --- Stage 2b: robustness + outlook ----------------------------------------------------
def stage_robustness(built: dict, analysis: dict, refresh: bool) -> dict:
    print("\n== Robustness: window from", config.ROBUSTNESS_START, "==")
    prices, rf, raw = built["prices"], built["rf"], built["raw"]
    win = robustness.window_analysis(prices, rf, config.ROBUSTNESS_START)
    win["summary"].to_csv(TABLES / "robustness_metrics.csv")
    win["backtest"].to_csv(TABLES / "robustness_backtest.csv")
    print(_fmt(win["summary"][["CAGR", "Volatility", "Sharpe", "Max drawdown"]],
               pct_cols=["CAGR", "Volatility", "Max drawdown"], num_cols=["Sharpe"]).to_string())
    print(_fmt(win["backtest"], BT_PCT, BT_MONEY, ["Multiple"]).to_string())

    embi = robustness.country_risk_context(raw["riesgo_pais"], prices.index[0],
                                           config.ROBUSTNESS_START, prices.index[-1])
    embi.to_csv(TABLES / "country_risk_context.csv")
    print("\nCountry risk (EMBI, bps):\n" + embi.to_string())

    print("\n== Outlook from today's prices ==")
    live = data_loader.load_live_bond_prices(list(outlook.BOND_FLOWS), refresh=refresh)
    val = data_loader.load_valuation(outlook.ETFS, refresh=refresh)
    rf_now = float(rf.dropna().iloc[-1])
    er, details = outlook.expected_returns(prices, raw, live, val, rf_now)
    er.to_csv(TABLES / "expected_returns_by_asset.csv")
    details["bonds"].to_csv(TABLES / "bond_yields_today.csv")
    cov = outlook.covariance(prices, details["bonds"])
    vols = pd.Series(np.sqrt(np.diag(cov)), index=cov.index)
    er["expected_volatility"] = vols.reindex(er.index)
    port = outlook.portfolio_expectations(er["expected_return"], cov, rf_now, analysis["summary"])
    sims = {name: outlook.simulate_plan(r["Expected return"], r["Expected volatility"])
            for name, r in port.iterrows()}
    sim_df = pd.DataFrame(sims).T
    port.to_csv(TABLES / "expected_portfolio.csv")
    sim_df.to_csv(TABLES / "plan_simulation_5y.csv")
    print(er[["expected_return", "method", "detail"]].assign(
        expected_return=er.expected_return.map(lambda x: f"{x:.1%}")).to_string())
    print(_fmt(port, pct_cols=list(port.columns.drop("Expected Sharpe")),
               num_cols=["Expected Sharpe"]).to_string())
    print("\n5-year plan simulation (USD 200/month):\n" + sim_df.round(2).to_string())
    return {"window": win, "embi": embi, "expected": er, "outlook_details": details,
            "expected_portfolio": port, "simulation": sim_df, "live": live}


# --- Stage 3: stress scenarios --------------------------------------------------------
def stage_scenarios(analysis: dict) -> dict:
    print("\n== Stress scenarios ==")
    eps = scenarios.select_episodes(analysis["indices"])
    table = scenarios.stress_table(analysis["indices"], eps)
    table.to_csv(TABLES / "stress_scenarios.csv", index=False)
    pivot = table.pivot_table(index=["peak", "event"], columns="portfolio", values="peak_to_trough")
    print(pivot.map(lambda x: f"{x:.1%}").to_string())
    return {"episodes": eps, "table": table}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    built = stage_data(args.refresh)
    analysis = stage_analysis(built)
    extra = stage_robustness(built, analysis, args.refresh)
    stress = stage_scenarios(analysis)
    path = report.build(built, analysis, extra, stress)
    print(f"\nReport written to {path}")


if __name__ == "__main__":
    main()
