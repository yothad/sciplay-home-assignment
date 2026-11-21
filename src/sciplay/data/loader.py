"""Load the raw CSV with light, lossless typing.

Nothing is cleaned or imputed here: the raw frame is the audit's source of truth.
Only obvious types are parsed so that date arithmetic and comparisons work.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Columns parsed as calendar dates (time part dropped). Timestamps keep their time.
DATE_COLUMNS = ["DATE"]
TIMESTAMP_COLUMNS = ["INSTALL_DATE", "FIRST_INSTALL_DATE", "CREATE_DATETIME", "LAST_UPDATE_DATETIME"]

KEY_COLUMNS = ["DATE", "PLAYER_ID", "PLATFORM_ID"]


def load_raw(path: str | Path) -> pd.DataFrame:
    """Read the sample CSV. Returns one row per source record, columns unchanged."""
    df = pd.read_csv(path, low_memory=False)
    for col in DATE_COLUMNS:
        df[col] = pd.to_datetime(df[col]).dt.normalize()
    for col in TIMESTAMP_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", format="ISO8601")
    return df.copy()  # de-fragment after column assignments


def parse_date_like(series: pd.Series) -> pd.Series:
    """Parse a date or timestamp column stored as text into a calendar date."""
    return pd.to_datetime(series.astype("string").str[:10], format="%Y-%m-%d", errors="coerce")
