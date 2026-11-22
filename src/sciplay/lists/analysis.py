"""Analyses behind the Part 4 thresholds and priority tiers (used by notebooks/03_lists.ipynb)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from sciplay.lists import config as L
from sciplay.lists import rules, signals
from sciplay.ltv import score as S


def cfg(**overrides) -> SimpleNamespace:
    base = {k: getattr(L, k) for k in dir(L) if k.isupper()}
    base.update(overrides)
    return SimpleNamespace(**base)


def ltv_for(date, data) -> pd.DataFrame:
    """Stored LTV scores for the date, or computed on the fly (not stored)."""
    s = S.read(date)
    return s if len(s) else S.score(date, data, store=False)


def run_dates(data, dates, c=None) -> dict:
    out = {}
    for D in dates:
        sig = signals.compute(data.pday, data.installs, D, ltv_for(D, data), c or L)
        sig["list_type"] = rules.primary_list(sig)
        out[pd.Timestamp(D)] = sig
    return out


def sizes(runs: dict) -> pd.DataFrame:
    rows = []
    for D, s in runs.items():
        vc = s.loc[s["list_type"] != "", "list_type"].value_counts()
        rows.append({"date": D.date(), "eligible": int(s["eligible"].sum()),
                     **{name: int(vc.get(name, 0)) for name in L.PRECEDENCE}})
    return pd.DataFrame(rows)


def membership_churn(runs: dict) -> float:
    """Average share of a day's listed players who were not listed (on any list) the day before."""
    dates = sorted(runs)
    vals = []
    for a, b in zip(dates[:-1], dates[1:]):
        prev = set(runs[a].index[runs[a]["list_type"] != ""])
        cur = set(runs[b].index[runs[b]["list_type"] != ""])
        if cur:
            vals.append(len(cur - prev) / len(cur))
    return float(np.mean(vals)) if vals else np.nan


def sweep(data, dates, grid: dict) -> pd.DataFrame:
    """Average list sizes and day-to-day churn for each threshold setting (one parameter varied at a time)."""
    rows = []
    for param, values in grid.items():
        for v in values:
            runs = run_dates(data, dates, cfg(**{param: v}))
            sz = sizes(runs)
            rows.append({"parameter": param, "value": v, "default": v == getattr(L, param),
                         **{f"avg {n}": round(sz[n].mean(), 1) for n in L.PRECEDENCE},
                         "new on list vs previous day": round(membership_churn(runs), 2)})
    return pd.DataFrame(rows)


def backtest(data, dates, horizon: int = 30) -> pd.DataFrame:
    """Do the signals point at players who then play or spend less? Outcomes in the next `horizon` days."""
    rows = []
    rev = data.pday.assign(R=data.pday["REVENUE"].fillna(0.0))
    for D, s in run_dates(data, dates).items():
        e = s[s["eligible"]]
        nxt = rev[(rev["DATE"] > D) & (rev["DATE"] <= D + pd.Timedelta(days=horizon))]
        played_next = nxt.groupby("PLAYER_ID")["DATE"].nunique().reindex(e.index).fillna(0)
        spend_next = nxt.groupby("PLAYER_ID")["R"].sum().reindex(e.index).fillna(0)
        # Compare like with like: players who had a meaningful baseline for that signal.
        had_pace = (e["baseline_days_per_week"] >= L.MIN_PRIOR_DAYS_PER_WEEK) | (e["peer_days_7d"] >= 1)
        busy = e["days_played_7d"] >= 3
        valuable = e["valuable"] != ""
        for name, flag, base in [("Engagement decline signal", e["any_engagement"], had_pace),
                                 ("Friction signal", e["any_friction"], busy),
                                 ("Revenue decline signal", e["any_revenue"], valuable)]:
            for grp, m in [("flagged", flag & base), ("not flagged, comparable", ~flag & base)]:
                if m.sum() == 0:
                    continue
                payers = m & (e["ltv_to_date"] > 0)
                rows.append({"date": D.date(), "signal": name, "group": grp, "players": int(m.sum()),
                             "stopped playing (0 days next 30)": float((played_next[m] == 0).mean()),
                             "days played next 30 (avg)": float(played_next[m].mean()),
                             "payers": int(payers.sum()),
                             "payer spend next 30 vs last 28": (float(spend_next[payers].sum() / e.loc[payers, "spend_last_28d"].sum())
                                                                if payers.sum() and e.loc[payers, "spend_last_28d"].sum() > 0 else np.nan)})
    t = pd.DataFrame(rows)
    agg = t.groupby(["signal", "group"]).agg(dates=("date", "nunique"), player_days=("players", "sum"),
                                              stopped_playing=("stopped playing (0 days next 30)", "mean"),
                                              days_played_next_30=("days played next 30 (avg)", "mean"),
                                              payer_spend_next_vs_last=("payer spend next 30 vs last 28", "mean"))
    return agg.round(2)


def gap_distribution(runs: dict) -> pd.DataFrame:
    listed = pd.concat([s.loc[s["list_type"] != "", ["list_type", "opportunity_gap", "ltv_to_date"]].assign(date=D)
                        for D, s in runs.items()])
    return listed
