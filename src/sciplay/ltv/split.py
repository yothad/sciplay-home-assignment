"""Train / test / inference / cold start, by install date."""

from __future__ import annotations

import pandas as pd

from sciplay.ltv import config as C


def install_dates(pday: pd.DataFrame) -> pd.Series:
    """Install date (midnight) per player."""
    return pd.to_datetime(pday.groupby("PLAYER_ID")["INSTALL_DATE"].min()).dt.normalize()


def assign_sets(installs: pd.Series, data_end, k: int = C.K, horizon: int = C.HORIZON) -> pd.Series:
    """One set per player. Test players must have a complete label; inference players K days of data."""
    data_end = pd.Timestamp(data_end)
    out = pd.Series("cold_start", index=installs.index, name="set")
    out[installs.between(*map(pd.Timestamp, C.TRAIN))] = "train"
    out[installs.between(*map(pd.Timestamp, C.TEST))] = "test"
    after_test = installs > pd.Timestamp(C.TEST[1])
    out[after_test & (installs + pd.Timedelta(days=k - 1) <= data_end)] = "inference"
    labelled = out.isin(["train", "test"])
    if (installs[labelled] + pd.Timedelta(days=horizon - 1) > data_end).any():
        raise ValueError("a train/test player has an incomplete label window")
    return out
