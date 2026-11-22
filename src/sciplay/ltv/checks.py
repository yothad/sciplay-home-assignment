"""Leakage checks for the LTV features."""

from __future__ import annotations

import numpy as np
import pandas as pd

from sciplay.ltv import config as C
from sciplay.ltv.features import FeatureSpec, build_features
from sciplay.ltv.labels import day_index


def truncation_check(pday: pd.DataFrame, installs: pd.Series, spec: FeatureSpec, k: int = C.K) -> bool:
    """Features from data cut at each player's feature date must equal features from the full data."""
    feat_date = pday["PLAYER_ID"].map(installs) + pd.Timedelta(days=k - 1)
    cut = pday[pd.to_datetime(pday["DATE"]) <= feat_date]
    a = build_features(pday, installs, spec, k).sort_index()
    b = build_features(cut, installs, spec, k).sort_index()
    return a.shape == b.shape and a.equals(b)


def future_revenue_check(pday: pd.DataFrame, installs: pd.Series, columns: list[str],
                         k: int = C.K, tol: float = 0.01) -> pd.DataFrame:
    """For revenue-type columns: the value on day d must not exceed our own revenue up to day d.

    A larger value means the row already holds money spent later (it was rewritten after its date).
    """
    d = day_index(pday, installs)
    rows = pday.loc[(d >= 0) & (d < k)].assign(day=d).sort_values(["PLAYER_ID", "day"])
    so_far = rows["REVENUE"].fillna(0).groupby(rows["PLAYER_ID"]).cumsum()
    out = []
    for c in columns:
        v = rows[c].astype(float)
        bad = (v > so_far + tol) & v.notna()
        out.append({"column": c, "rows_checked": int(v.notna().sum()), "rows_ahead": int(bad.sum())})
    return pd.DataFrame(out)


def install_window_consistency(pday: pd.DataFrame, installs: pd.Series) -> pd.DataFrame:
    """I3/I7_REVENUE (read within their own window) vs our own revenue over days 0-2 / 0-6."""
    d = day_index(pday, installs)
    out = []
    for col, n in [("I3_REVENUE", 3), ("I7_REVENUE", 7)]:
        if col not in pday:
            continue
        w = pday[d.between(0, n - 1)]
        ours = w["REVENUE"].fillna(0).groupby(w["PLAYER_ID"]).sum()
        theirs = w[col].groupby(w["PLAYER_ID"]).max().fillna(0)
        idx = ours.index.union(theirs.index)
        a, b = ours.reindex(idx).fillna(0), theirs.reindex(idx).fillna(0)
        match = np.isclose(a, b, atol=0.01)
        out.append({"column": col, "players": len(idx), "match_share": float(match.mean()),
                    "mismatches": int((~match).sum())})
    return pd.DataFrame(out)
