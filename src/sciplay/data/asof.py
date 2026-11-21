"""As-of policy: what may be used for a score on day D.

Policy
------
A score for score date D (as of the end of D, UTC) uses
- only rows with DATE <= D, and
- only columns the registry marks as features (known by the end of D).
The future may appear in a label, never in a feature.

Revenue to date at the end of D = LIFETIME_REVENUE (start of D) + REVENUE (day D).
"""

from __future__ import annotations

import pandas as pd

from sciplay.data.registry import MEASURE, U_FEATURE


def rollup_player_day(df: pd.DataFrame, registry: pd.DataFrame) -> pd.DataFrame:
    """One row per player per day: sum daily measures, take everything else once.

    The platform with the most sessions is the main platform; `n_platforms` counts them.
    """
    measures = [c for c in registry.loc[registry["role"] == MEASURE, "column"]
                if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]
    ordered = df.sort_values(["DATE", "PLAYER_ID", "SESSIONS"], ascending=[True, True, False])
    keys = ["DATE", "PLAYER_ID"]
    first = ordered.groupby(keys, sort=False).first()
    summed = ordered.groupby(keys, sort=False)[measures].sum(min_count=1)
    n_platforms = ordered.groupby(keys, sort=False)["PLATFORM_ID"].nunique().rename("n_platforms")
    out = pd.concat([first.drop(columns=measures), summed, n_platforms], axis=1)[list(first.columns) + ["n_platforms"]]
    return out.reset_index().rename(columns={"PLATFORM_ID": "MAIN_PLATFORM_ID"})


def rows_as_of(df: pd.DataFrame, score_date: str | pd.Timestamp) -> pd.DataFrame:
    """Rows a score for `score_date` may see."""
    return df[df["DATE"] <= pd.Timestamp(score_date)]


def revenue_to_date(rows: pd.DataFrame) -> pd.Series:
    """Revenue to date at the end of each row's day (start-of-day lifetime + that day)."""
    return rows["LIFETIME_REVENUE"].fillna(0) + rows["REVENUE"].fillna(0)


def snapshot_as_of(df: pd.DataFrame, score_date: str | pd.Timestamp) -> pd.DataFrame:
    """Each player's last known row on or before D, carried forward to D.

    Players without a row on D are kept (inactive that day), with days since last seen.
    """
    d = pd.Timestamp(score_date)
    last = rows_as_of(df, d).sort_values("DATE").groupby("PLAYER_ID").tail(1).copy()
    last.insert(0, "score_date", d)
    last["last_seen"] = last["DATE"]
    last["days_since_last_seen"] = (d - last["DATE"]).dt.days
    last["active_on_score_date"] = last["days_since_last_seen"].eq(0)
    last["revenue_to_date"] = revenue_to_date(last)
    last["age_days"] = (d - last["INSTALL_DATE"].dt.normalize()).dt.days
    return last.reset_index(drop=True)


def feature_columns(registry: pd.DataFrame) -> list[str]:
    """Columns allowed as model features under the as-of policy."""
    return registry.loc[registry["use"].str.startswith(U_FEATURE), "column"].tolist()


def assert_as_of(features: pd.DataFrame, score_date: str | pd.Timestamp, allowed: list[str],
                 date_col: str = "DATE") -> None:
    """Fail loudly if a feature frame breaks the policy."""
    d = pd.Timestamp(score_date)
    if (features[date_col] > d).any():
        raise ValueError(f"rows dated after {d.date()} in features")
    extra = set(features.columns) - set(allowed) - {date_col, "PLAYER_ID", "score_date"}
    if extra:
        raise ValueError(f"columns not allowed by the registry: {sorted(extra)[:10]}")


# ------------------------------------------------------------------ worked examples


def player_timeline(df: pd.DataFrame, player_id: int, score_date: str | pd.Timestamp,
                    columns: list[str], window_after: int = 2) -> pd.DataFrame:
    """A player's rows around D, marked as usable for the score or not."""
    d = pd.Timestamp(score_date)
    rows = df[(df["PLAYER_ID"] == player_id) & (df["DATE"] <= d + pd.Timedelta(days=window_after))]
    out = rows.sort_values("DATE")[["DATE"] + columns].copy()
    out["revenue_to_date_end_of_day"] = revenue_to_date(out)
    out.insert(1, "row_usable_for_score", out["DATE"].le(d).map({True: "yes", False: "no: after D"}))
    return out.reset_index(drop=True)


def returner_flag_example(df: pd.DataFrame, player_id: int, n_rows: int = 6) -> pd.DataFrame:
    """Show that D1_RETURNER on a row equals 'the player has a row on the next day'."""
    rows = df[df["PLAYER_ID"] == player_id].sort_values("DATE").head(n_rows + 1)
    nxt = rows["DATE"].shift(-1)
    out = rows[["DATE", "D1_RETURNER", "NEXT_LOGIN_DATE"]].copy()
    out["next_row_date"] = nxt
    out["played_next_day"] = (nxt - rows["DATE"]).dt.days.eq(1).astype(int)
    return out.head(n_rows).reset_index(drop=True)
