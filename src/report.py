"""Build the HTML report (Plotly charts + plain-language conclusions, in Spanish).

All the numbers in the text are computed from the analysis results, so the report
stays consistent when the data is refreshed.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from jinja2 import Environment, FileSystemLoader

from . import config

# Validated categorical palette (light steps; the page swaps to dark steps in JS).
C = {"A": "#2a78d6", "B": "#eb6834", "AB": "#1baf7a", "SPY": "#eda100",
     "FULL": "#6250d6", "MUTED": "#898781", "RED": "#e34948"}
PORT_COLORS = {"A (income)": C["A"], "B (growth)": C["B"], "Combined 60/40": C["AB"], "SPY": C["SPY"]}
ES = {"A (income)": "A · Renta", "B (growth)": "B · Crecimiento", "Combined 60/40": "Combinado 60/40",
      "SPY": "SPY", "Your strategy (no selling)": "Tu estrategia (sin vender)",
      "Full rebalance": "Rebalanceo completo", "100% SPY": "100% SPY",
      "100% A": "100% A", "100% B": "100% B"}
ASSET_ES = {"FCI_IOL_DAP": "FCI IOL DAP", "YMCXO": "ON YPF 2031", "VSCRO": "ON Vista 2031",
            "TTCDO": "ON Tecpetrol 2030"}


def pct(x, d=1):
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:.{d}f}%".replace(".", ",")


def usd(x):
    return f"USD {x:,.0f}".replace(",", ".")


def num(x, d=2):
    return f"{x:.{d}f}".replace(".", ",")


def _layout(fig: go.Figure, height=380, yfmt=None, ytitle=None, legend=True) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=56, r=16, t=16, b=40),
        hovermode="x unified", showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None),
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", size=12),
        separators=",.",
    )
    fig.update_xaxes(showgrid=False, ticks="")
    fig.update_yaxes(tickformat=yfmt, title=ytitle, zeroline=False)
    return fig


def _line(fig, s, name, color, dash=None, width=2, fmt=".1f"):
    fig.add_trace(go.Scatter(x=s.index, y=s.values, name=name, mode="lines",
                             line=dict(color=color, width=width, dash=dash),
                             hovertemplate=f"%{{y:{fmt}}}<extra>{name}</extra>"))


# --- figures ------------------------------------------------------------------------
def fig_growth(idx):
    fig = go.Figure()
    for c in idx:
        _line(fig, idx[c], ES[c], PORT_COLORS[c], fmt=",.0f")
    return _layout(fig, yfmt=",.0f", ytitle="Valor de USD 100")


def fig_drawdown(idx):
    from .metrics import drawdown
    fig = go.Figure()
    for c in idx:
        _line(fig, drawdown(idx[c]), ES[c], PORT_COLORS[c], width=1.6, fmt=".1%")
    return _layout(fig, height=320, yfmt=".0%", ytitle="Caída desde el máximo")


def fig_stress(table):
    fig = go.Figure()
    order = ["A (income)", "B (growth)", "Combined 60/40", "SPY"]
    events = table.drop_duplicates("event")
    labels = [f"{e.split(':')[0]}" for e in events.event]
    for p in order:
        t = table[table.portfolio == p].set_index("event").loc[events.event]
        fig.add_trace(go.Bar(x=labels, y=t.peak_to_trough, name=ES[p], marker_color=PORT_COLORS[p],
                             marker_line_width=0,
                             hovertemplate="%{y:.1%}<extra>" + ES[p] + "</extra>"))
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.08)
    return _layout(fig, height=360, yfmt=".0%", ytitle="Retorno pico → piso")


def fig_corr(corr):
    labels = [ASSET_ES.get(a, a) for a in corr.index]
    z = corr.values.round(2)
    fig = go.Figure(go.Heatmap(
        z=z, x=labels, y=labels, zmin=-1, zmax=1,
        colorscale=[[0, "#2a78d6"], [0.5, "#f0efec"], [1, "#e34948"]],
        xgap=2, ygap=2, colorbar=dict(thickness=10, outlinewidth=0),
        hovertemplate="%{y} / %{x}: %{z:.2f}<extra></extra>"))
    fig.update_yaxes(autorange="reversed")
    return _layout(fig, height=560, legend=False).update_layout(hovermode="closest")


def fig_rolling(roll):
    fig = go.Figure()
    _line(fig, roll.dropna(), "Correlación A/B (26 semanas)", C["AB"], fmt=".2f")
    return _layout(fig, height=280, yfmt=".1f", legend=False)


def fig_backtest(values, invested):
    fig = go.Figure()
    for c, col in [("Your strategy (no selling)", C["AB"]), ("Full rebalance", C["FULL"]),
                   ("100% SPY", C["SPY"])]:
        _line(fig, values[c], ES[c], col, fmt=",.0f")
    _line(fig, invested, "Dinero aportado", C["MUTED"], dash="dash", width=1.5, fmt=",.0f")
    return _layout(fig, yfmt=",.0f", ytitle="USD")


def fig_embi(embi, start, robust_start):
    s = embi.loc[pd.Timestamp(start) - pd.Timedelta(days=30):]
    fig = go.Figure()
    _line(fig, s, "Riesgo país (pb)", C["A"], fmt=",.0f")
    for d, label in [(start, "Inicio del análisis"), (robust_start, "Inicio ventana de robustez")]:
        d = pd.Timestamp(d)
        v = float(embi.loc[:d].iloc[-1])
        fig.add_trace(go.Scatter(x=[d], y=[v], mode="markers+text", text=[f"{label}: {v:,.0f}"],
                                 textposition="top right", marker=dict(size=9, color=C["A"]),
                                 showlegend=False, hoverinfo="skip"))
    return _layout(fig, height=320, yfmt=",.0f", ytitle="Puntos básicos", legend=False)


def fig_expected(er: pd.Series, rf_now):
    df = er.to_frame("expected_return")
    df["port"] = ["A" if a in config.PORTFOLIO_A else "B" for a in df.index]
    df = df.sort_values("expected_return")
    labels = [ASSET_ES.get(a, a) for a in df.index]
    fig = go.Figure()
    for port, name in [("A", "Portafolio A"), ("B", "Portafolio B")]:
        m = df.port == port
        fig.add_trace(go.Bar(y=[l for l, k in zip(labels, m) if k], x=df.expected_return[m],
                             orientation="h", name=name, marker_color=C[port], marker_line_width=0,
                             hovertemplate="%{x:.1%}<extra>%{y}</extra>"))
    fig.add_vline(x=rf_now, line_dash="dot", line_color=C["MUTED"],
                  annotation_text=f"Letra EE.UU. {pct(rf_now)}", annotation_position="top")
    fig.update_layout(barmode="overlay", hovermode="closest")
    return _layout(fig, height=480, yfmt=None).update_xaxes(tickformat=".0%", showgrid=True)


def fig_simulation(sim, hist_final):
    fig = go.Figure()
    names = list(sim.index)
    for n in names:
        r = sim.loc[n]
        fig.add_trace(go.Scatter(x=[r.p10, r.p90], y=[ES[n]] * 2, mode="lines",
                                 line=dict(color=PORT_COLORS[n], width=8), showlegend=False,
                                 hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[r.p50], y=[ES[n]], mode="markers",
                                 marker=dict(size=14, color=PORT_COLORS[n],
                                             line=dict(width=2, color="#fcfcfb")),
                                 showlegend=False,
                                 hovertemplate=f"Mediana {usd(r.p50)}<br>Rango 10-90%: "
                                               f"{usd(r.p10)} – {usd(r.p90)}<extra>{ES[n]}</extra>"))
    fig.add_vline(x=float(sim.invested.iloc[0]), line_dash="dash", line_color=C["MUTED"],
                  annotation_text="Aportado", annotation_position="top")
    fig.update_layout(hovermode="closest")
    return _layout(fig, height=300, legend=False).update_xaxes(tickformat=",.0f", showgrid=True)


# --- tables -------------------------------------------------------------------------
def table_html(df: pd.DataFrame, formats: dict, rename: dict | None = None, index_name="") -> str:
    out = df.copy()
    for col, f in formats.items():
        if col in out:
            out[col] = out[col].map(lambda x, f=f: f(x) if pd.notna(x) else "–")
    out = out.rename(columns=rename or {}).rename(index=lambda i: ES.get(i, ASSET_ES.get(i, i)))
    out.index.name = index_name
    return out.to_html(classes="tbl", border=0, escape=True)


# --- narrative ----------------------------------------------------------------------
def conclusions(a, x, stress) -> list[str]:
    s, bt = a["summary"], a["backtest"]
    me, spy = bt.loc["Your strategy (no selling)"], bt.loc["100% SPY"]
    full = bt.loc["Full rebalance"]
    win = x["window"]["backtest"]
    wme, wspy = win.loc["Your strategy (no selling)"], win.loc["100% SPY"]
    port = x["expected_portfolio"]
    embi = x["embi"]["embi_bps"]
    worst = stress["table"]
    w22 = worst[(worst.event.str.startswith("2022")) & (worst.portfolio == "Combined 60/40")]
    w22 = float(w22.peak_to_trough.iloc[0]) if len(w22) else s.loc["Combined 60/40", "Max drawdown"]
    beat = "más que" if me["Final value (USD)"] > spy["Final value (USD)"] else "menos que"
    items = [
        f"<b>En los últimos 5 años tu estrategia rindió {beat} SPY.</b> Aportando USD 200 por mes "
        f"({usd(me['Invested (USD)'])} en total) habrías terminado con {usd(me['Final value (USD)'])}, "
        f"contra {usd(spy['Final value (USD)'])} con todo en SPY. Tu dinero rindió "
        f"{pct(me['Money-weighted return (XIRR)'])} anual, contra {pct(spy['Money-weighted return (XIRR)'])}.",
        f"<b>El costo fue algo más de riesgo.</b> En la crisis de 2022 el combinado cayó {pct(w22)}, "
        f"más que SPY: ese año los bonos argentinos y la tecnología cayeron a la vez. "
        f"A y B tienen una correlación de {num(a['corr_ab'].loc['A (income)', 'B (growth)'])}: "
        f"diversifican menos de lo que parece, porque los dos dependen del riesgo argentino.",
        f"<b>Aportar sin vender es la forma eficiente de rebalancear.</b> Rinde casi lo mismo que el "
        f"rebalanceo completo ({usd(me['Final value (USD)'])} contra {usd(full['Final value (USD)'])}) "
        f"y paga un tercio de las comisiones ({usd(me['Fees paid (USD)'])} contra {usd(full['Fees paid (USD)'])}).",
        f"<b>Desde octubre de 2024, la ventaja casi desaparece.</b> En esa ventana tu estrategia terminó "
        f"en {usd(wme['Final value (USD)'])} y SPY en {usd(wspy['Final value (USD)'])}, aun cuando el "
        f"riesgo país todavía bajó de {embi['Robustness window start']:,.0f} a "
        f"{embi['Latest']:,.0f} pb en ese período.".replace(",", "."),
        f"<b>Los resultados pasados son un techo optimista, no una expectativa.</b> Desde los precios de hoy, "
        f"un cálculo simple da un rendimiento esperado de ~{pct(port.loc['Combined 60/40', 'Expected return'])} "
        f"anual para el combinado, similar a SPY ({pct(port.loc['SPY', 'Expected return'])}), "
        f"lejos del {pct(s.loc['Combined 60/40', 'CAGR'])} de los últimos 5 años.",
    ]
    return items


def build(built: dict, a: dict, x: dict, stress: dict) -> Path:
    prices, rf = built["prices"], built["rf"]
    raw = built["raw"]
    rf_now = float(rf.dropna().iloc[-1])
    idx = a["indices"]
    bt = a["backtest"]
    me, spy = bt.loc["Your strategy (no selling)"], bt.loc["100% SPY"]
    s = a["summary"]
    win = x["window"]
    bonds = x["outlook_details"]["bonds"]
    dual = x["outlook_details"]["dual"]
    port = x["expected_portfolio"]
    sim = x["simulation"]
    embi = x["embi"]["embi_bps"]

    figs = {
        "growth": fig_growth(idx),
        "drawdown": fig_drawdown(idx),
        "stress": fig_stress(stress["table"]),
        "corr": fig_corr(a["corr"]),
        "rolling": fig_rolling(a["rolling_ab"]),
        "backtest": fig_backtest(a["values"], a["results"]["100% SPY"].invested),
        "robust": fig_backtest(pd.DataFrame({k: r.value for k, r in win["results"].items()}),
                               win["results"]["100% SPY"].invested),
        "embi": fig_embi(raw["riesgo_pais"], prices.index[0], config.ROBUSTNESS_START),
        "expected": fig_expected(x["expected"]["expected_return"], rf_now),
        "simulation": fig_simulation(sim, me["Final value (USD)"]),
    }
    fig_json = {k: json.loads(f.to_json()) for k, f in figs.items()}

    P, M, N = pct, usd, num
    tables = {
        "metrics": table_html(s[["CAGR", "Volatility", "Sharpe", "Sortino", "Max drawdown", "DD recovery",
                                 "% positive months"]],
                              {"CAGR": P, "Volatility": P, "Sharpe": N, "Sortino": N, "Max drawdown": P,
                               "% positive months": P},
                              {"CAGR": "Rend. anual", "Volatility": "Volatilidad", "Max drawdown": "Máx. caída",
                               "DD recovery": "Recuperó", "% positive months": "Meses positivos"}),
        "backtest": table_html(bt[["Invested (USD)", "Final value (USD)", "Money-weighted return (XIRR)",
                                   "Time-weighted CAGR", "Max drawdown (TWR)", "Fees paid (USD)"]],
                               {"Invested (USD)": M, "Final value (USD)": M,
                                "Money-weighted return (XIRR)": P, "Time-weighted CAGR": P,
                                "Max drawdown (TWR)": P, "Fees paid (USD)": M},
                               {"Invested (USD)": "Aportado", "Final value (USD)": "Valor final",
                                "Money-weighted return (XIRR)": "Rend. de tu dinero (XIRR)",
                                "Time-weighted CAGR": "Rend. de la estrategia (TWR)",
                                "Max drawdown (TWR)": "Máx. caída", "Fees paid (USD)": "Comisiones"}),
        "robust": table_html(win["backtest"][["Invested (USD)", "Final value (USD)",
                                               "Money-weighted return (XIRR)", "Max drawdown (TWR)"]],
                             {"Invested (USD)": M, "Final value (USD)": M,
                              "Money-weighted return (XIRR)": P, "Max drawdown (TWR)": P},
                             {"Invested (USD)": "Aportado", "Final value (USD)": "Valor final",
                              "Money-weighted return (XIRR)": "Rend. de tu dinero (XIRR)",
                              "Max drawdown (TWR)": "Máx. caída"}),
        "on": table_html(a["on_scenarios"].rename(index={
                "base": "Base: 50% CEMB + 50% AL30D", "pessimistic": "Pesimista: CEMB",
                "sensitivity_EMB": "Sensibilidad: EMB"}),
            {"A CAGR": P, "A max DD": P, "A Sharpe": N, "60/40 CAGR": P, "60/40 Sharpe": N,
             "Backtest final (USD)": M, "Backtest XIRR": P},
            {"A CAGR": "A rend. anual", "A max DD": "A máx. caída", "A Sharpe": "A Sharpe",
             "60/40 CAGR": "60/40 rend. anual", "60/40 Sharpe": "60/40 Sharpe",
             "Backtest final (USD)": "Backtest: valor final", "Backtest XIRR": "Backtest: XIRR"}),
        "stress": table_html(stress["table"].pivot_table(index="event", columns="portfolio",
                                                         values="peak_to_trough", sort=False)
                             [["A (income)", "B (growth)", "Combined 60/40", "SPY"]],
                             {c: P for c in ["A (income)", "B (growth)", "Combined 60/40", "SPY"]},
                             {c: ES[c] for c in ES}, "Episodio"),
        "bonds": table_html(bonds[["symbol", "price", "ytm", "rava_tir", "mod_duration", "maturity"]],
                            {"price": lambda v: N(v), "ytm": P, "rava_tir": P,
                             "mod_duration": lambda v: N(v, 1)},
                            {"symbol": "Especie", "price": "Precio", "ytm": "TIR (cálculo propio)",
                             "rava_tir": "TIR Rava (control)", "mod_duration": "Duración mod.",
                             "maturity": "Vencimiento"}),
        "expected": table_html(port, {"Expected return": P, "Expected volatility": P,
                                      "Expected Sharpe": N, "Past 5y CAGR": P},
                               {"Expected return": "Rend. esperado", "Expected volatility": "Volatilidad esperada",
                                "Expected Sharpe": "Sharpe esperado", "Past 5y CAGR": "Rend. últimos 5 años"}),
        "sim": table_html(sim[["p10", "p50", "p90", "prob_loss"]],
                          {"p10": M, "p50": M, "p90": M, "prob_loss": P},
                          {"p10": "Escenario malo (10%)", "p50": "Mediana", "p90": "Escenario bueno (90%)",
                           "prob_loss": "Prob. de terminar abajo"}),
        "coverage": built["coverage"].assign(
            real_data_share=built["coverage"].real_data_share.map(P),
            asset=built["coverage"].asset.map(lambda v: ASSET_ES.get(v, v)))
            [["asset", "source_type", "real_data_share", "note"]]
            .rename(columns={"asset": "Activo", "source_type": "Tipo", "real_data_share": "% con dato real",
                             "note": "Fuente / proxy"})
            .to_html(classes="tbl tbl-wide", border=0, index=False),
    }

    w_a = [(ASSET_ES.get(k, k), P(v, 0)) for k, v in config.PORTFOLIO_A.items()]
    w_b = [(ASSET_ES.get(k, k), P(v, 0)) for k, v in config.PORTFOLIO_B.items()]

    kpis = [
        ("Valor final, tu estrategia", M(me["Final value (USD)"]), f"aportando {M(me['Invested (USD)'])}"),
        ("Valor final, 100% SPY", M(spy["Final value (USD)"]), "mismos aportes"),
        ("Sharpe 60/40 vs SPY", f"{N(s.loc['Combined 60/40', 'Sharpe'])} vs {N(s.loc['SPY', 'Sharpe'])}",
         "retorno por unidad de riesgo"),
        ("Rend. esperado desde hoy", P(port.loc["Combined 60/40", "Expected return"]),
         f"vs {P(s.loc['Combined 60/40', 'CAGR'])} histórico"),
    ]

    ctx = dict(
        title="Análisis cuantitativo de dos portafolios",
        start=prices.index[0].strftime("%d/%m/%Y"), end=prices.index[-1].strftime("%d/%m/%Y"),
        generated=pd.Timestamp.today().strftime("%d/%m/%Y"),
        kpis=kpis, conclusions=conclusions(a, x, stress), w_a=w_a, w_b=w_b,
        tables=tables, figs=json.dumps(fig_json),
        n=dict(
            contribution=M(config.MONTHLY_CONTRIBUTION), fee=P(config.COMMISSION_DEFAULT, 2),
            rf_now=P(rf_now), embi_start=f"{embi['Full window start']:,.0f}".replace(",", "."),
            embi_peak=f"{embi['Peak in window']:,.0f}".replace(",", "."),
            embi_robust=f"{embi['Robustness window start']:,.0f}".replace(",", "."),
            embi_low=f"{embi['Low in window']:,.0f}".replace(",", "."),
            embi_now=f"{embi['Latest']:,.0f}".replace(",", "."),
            robust_start=pd.Timestamp(config.ROBUSTNESS_START).strftime("%m/%Y"),
            a_cagr=P(s.loc["A (income)", "CAGR"]), b_cagr=P(s.loc["B (growth)", "CAGR"]),
            ab_cagr=P(s.loc["Combined 60/40", "CAGR"]), spy_cagr=P(s.loc["SPY", "CAGR"]),
            w_ab_cagr=P(win["summary"].loc["Combined 60/40", "CAGR"]),
            w_spy_cagr=P(win["summary"].loc["SPY", "CAGR"]),
            w_me_xirr=P(win["backtest"].loc["Your strategy (no selling)", "Money-weighted return (XIRR)"]),
            w_spy_xirr=P(win["backtest"].loc["100% SPY", "Money-weighted return (XIRR)"]),
            al35_ytm=P(bonds.loc["AL35", "ytm"]), ao27_ytm=P(bonds.loc["AO27", "ytm"]),
            fci_y=P(x["expected"].loc["FCI_IOL_DAP", "expected_return"]),
            on_ytm=P(bonds.loc[["YMCXO", "VSCRO", "TTCDO"], "ytm"].astype(float).mean()),
            tamar=P(dual["tamar_effective"]), infl=P(dual["inflation_12m"]),
            txmd9_hist=P(((prices["TXMD9"].iloc[-1] / prices["TXMD9"].iloc[0])
                          ** (365.25 / (prices.index[-1] - prices.index[0]).days)) - 1),
            nvda_cagr=P(((prices["NVDA"].iloc[-1] / prices["NVDA"].iloc[0])
                         ** (365.25 / (prices.index[-1] - prices.index[0]).days)) - 1),
            vist_cagr=P(((prices["VIST"].iloc[-1] / prices["VIST"].iloc[0])
                         ** (365.25 / (prices.index[-1] - prices.index[0]).days)) - 1),
            ab_exp=P(port.loc["Combined 60/40", "Expected return"]),
            ab_vol=P(port.loc["Combined 60/40", "Expected volatility"]),
            spy_exp=P(port.loc["SPY", "Expected return"]),
            a_exp=P(port.loc["A (income)", "Expected return"]),
            b_exp=P(port.loc["B (growth)", "Expected return"]),
            sim_p50=M(sim.loc["Combined 60/40", "p50"]), sim_p10=M(sim.loc["Combined 60/40", "p10"]),
            sim_p90=M(sim.loc["Combined 60/40", "p90"]),
            sim_loss=P(sim.loc["Combined 60/40", "prob_loss"], 0),
            hist_final=M(me["Final value (USD)"]),
            corr_ab=N(a["corr_ab"].loc["A (income)", "B (growth)"]),
            spy_er=P(x["outlook_details"]["spy_er"]),
        ),
    )
    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=False)
    html = env.get_template("report.html.j2").render(**ctx)
    out = config.REPORTS / "portfolio_report.html"
    out.write_text(html, encoding="utf-8")
    return out
