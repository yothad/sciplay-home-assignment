"""30-day revenue label. The model predicts the remainder after the feature window."""

from __future__ import annotations

import pandas as pd

from sciplay.ltv import config as C


def day_index(pday: pd.DataFrame, installs: pd.Series) -> pd.Series:
    return (pd.to_datetime(pday["DATE"]) - pday["PLAYER_ID"].map(installs)).dt.days


def label_frame(pday: pd.DataFrame, installs: pd.Series, data_end,
                k: int = C.K, horizon: int = C.HORIZON) -> pd.DataFrame:
    """Per player: revenue in days 0..k-1 (observed), days 0..horizon-1, and the remainder (target).

    No row on a day = $0 (the player did not play). `complete` = the whole window is in the data.
    """
    d = day_index(pday, installs)
    rev = pday["REVENUE"].fillna(0.0)
    first_k = rev[d < k].groupby(pday.loc[d < k, "PLAYER_ID"]).sum()
    first_h = rev[d < horizon].groupby(pday.loc[d < horizon, "PLAYER_ID"]).sum()
    out = pd.DataFrame(index=installs.index)
    out["revenue_first_k"] = first_k.reindex(out.index).fillna(0.0)
    out["revenue_first_30d"] = first_h.reindex(out.index).fillna(0.0)
    out["target_remainder"] = out["revenue_first_30d"] - out["revenue_first_k"]
    out["complete"] = installs + pd.Timedelta(days=horizon - 1) <= pd.Timestamp(data_end)
    out.loc[~out["complete"], ["revenue_first_30d", "target_remainder"]] = float("nan")
    return out
