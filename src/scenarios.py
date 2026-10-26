"""Stress scenarios: how each portfolio behaved in the worst drawdowns of the period.

Episodes are detected automatically (peak -> trough of a reference series),
taking the deepest non-overlapping drawdowns of SPY (global shocks) and of the
combined portfolio (shocks that hurt *this* investor, e.g. Argentine stress).
"""
from __future__ import annotations

import pandas as pd

from .metrics import drawdown

# Context labels for the report (matched by overlap with an episode).
KNOWN_EVENTS = [
    ("2021-11-01", "2022-10-31", "2022: Fed hikes, tech sell-off and Argentine bond crisis"),
    ("2023-07-15", "2023-10-31", "Aug-Oct 2023: US rates spike, Argentine pre-election volatility"),
    ("2024-07-01", "2024-08-15", "Jul-Aug 2024: AI/tech correction, yen carry unwind"),
    ("2025-02-15", "2025-04-30", "Feb-Apr 2025: US tariff shock"),
    ("2025-08-01", "2025-10-27", "Aug-Oct 2025: Argentine pre-election stress"),
    ("2026-01-15", "2026-04-15", "Jan-Mar 2026: US equity correction"),
]


def drawdown_episodes(index: pd.Series, min_depth: float = 0.05) -> pd.DataFrame:
    """Every peak-to-trough episode deeper than `min_depth`."""
    s = index.dropna()
    dd = drawdown(s)
    episodes, in_dd, peak = [], False, s.index[0]
    for t, v in dd.items():
        if v == 0:
            if in_dd:
                seg = dd.loc[peak:t]
                episodes.append((peak, seg.idxmin(), t, float(seg.min())))
                in_dd = False
            peak = t
        else:
            in_dd = True
    if in_dd:  # still under water at the end
        seg = dd.loc[peak:]
        episodes.append((peak, seg.idxmin(), None, float(seg.min())))
    df = pd.DataFrame(episodes, columns=["peak", "trough", "recovery", "depth"])
    return df[df.depth <= -min_depth].sort_values("depth").reset_index(drop=True)


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start <= b_end and b_start <= a_end


def label_for(start, end) -> str:
    for s, e, label in KNOWN_EVENTS:
        if _overlaps(start, end, pd.Timestamp(s), pd.Timestamp(e)):
            return label
    return f"{start:%b %Y} - {end:%b %Y}"


def select_episodes(indices: pd.DataFrame,
                    refs=("SPY", "Combined 60/40", "A (income)", "B (growth)"),
                    top: int = 3) -> pd.DataFrame:
    chosen = []
    for ref in refs:
        for _, ep in drawdown_episodes(indices[ref]).head(top).iterrows():
            if not any(_overlaps(ep.peak, ep.trough, c["peak"], c["trough"]) for c in chosen):
                chosen.append({"reference": ref, "peak": ep.peak, "trough": ep.trough,
                               "ref_depth": ep.depth})
    out = pd.DataFrame(chosen).sort_values("peak").reset_index(drop=True)
    out["event"] = [label_for(r.peak, r.trough) for r in out.itertuples()]
    return out


def stress_table(indices: pd.DataFrame, episodes: pd.DataFrame) -> pd.DataFrame:
    """Return of each portfolio from the episode's peak to its trough, plus the
    days each portfolio needed to get back to its level at the peak."""
    rows = []
    for ep in episodes.itertuples():
        for name in indices:
            s = indices[name].dropna()
            start = s.loc[:ep.peak].iloc[-1]
            window = s.loc[ep.peak:ep.trough]
            ret = window.iloc[-1] / start - 1
            worst = window.min() / start - 1
            after = s.loc[ep.trough:]
            back = after[after >= start]
            days = (back.index[0] - ep.trough).days if len(back) else None
            rows.append({"event": ep.event, "peak": ep.peak.date(), "trough": ep.trough.date(),
                         "portfolio": name, "peak_to_trough": ret, "worst_point": worst,
                         "days_to_recover": days})
    return pd.DataFrame(rows)
