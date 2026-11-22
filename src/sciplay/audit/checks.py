"""Data audit: grain, coverage, missingness, duplicates and data quality checks.

Every function takes the raw frame (see `sciplay.data.loader.load_raw`) and returns
plain pandas objects, so the same results feed the audit notebook and the
dashboard's Data Health view.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from sciplay.data.field_groups import field_groups
from sciplay.data.loader import KEY_COLUMNS, parse_date_like

# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #


def dataset_overview(df: pd.DataFrame) -> pd.DataFrame:
    """One-row-per-metric headline table."""
    rows_per_player = df.groupby("PLAYER_ID").size()
    install = df["INSTALL_DATE"].dt.normalize()
    metrics = {
        "Rows": len(df),
        "Columns": df.shape[1],
        "Distinct players": df["PLAYER_ID"].nunique(),
        "Distinct data dates": df["DATE"].nunique(),
        "First data date": df["DATE"].min().date(),
        "Last data date": df["DATE"].max().date(),
        "First install date": install.min().date(),
        "Last install date": install.max().date(),
        "Max days since install": int(df["DAYS_SINCE_INSTALL"].max()),
        "Platforms": df["PLATFORM_ID"].nunique(),
        "Games": df["GAME_ID"].nunique(),
        "Median rows per player": float(rows_per_player.median()),
    }
    return pd.DataFrame({"metric": metrics.keys(), "value": [str(v) for v in metrics.values()]})


# --------------------------------------------------------------------------- #
# Grain and duplicate keys
# --------------------------------------------------------------------------- #

CANDIDATE_KEYS: dict[str, list[str]] = {
    "DATE + PLAYER_ID + PLATFORM_ID": KEY_COLUMNS,
    "DATE + PLAYER_ID": ["DATE", "PLAYER_ID"],
    "PLAYER_ID + PLATFORM_ID": ["PLAYER_ID", "PLATFORM_ID"],
    "PLAYER_ID": ["PLAYER_ID"],
}


def duplicate_keys(df: pd.DataFrame) -> pd.DataFrame:
    """How many rows share each candidate key. Zero extra rows = a valid key."""
    out = []
    for name, cols in CANDIDATE_KEYS.items():
        dup_mask = df.duplicated(cols, keep=False)
        out.append(
            {
                "candidate_key": name,
                "distinct_keys": int(df[cols].drop_duplicates().shape[0]),
                "rows_in_duplicated_keys": int(dup_mask.sum()),
                "extra_rows": int(df.duplicated(cols).sum()),
                "is_unique": not df.duplicated(cols).any(),
            }
        )
    out.append(
        {
            "candidate_key": "Full row (all columns)",
            "distinct_keys": int(len(df) - df.duplicated().sum()),
            "rows_in_duplicated_keys": int(df.duplicated(keep=False).sum()),
            "extra_rows": int(df.duplicated().sum()),
            "is_unique": not df.duplicated().any(),
        }
    )
    return pd.DataFrame(out)


def multi_platform_player_days(df: pd.DataFrame) -> pd.DataFrame:
    """Player-days that have more than one platform row, with key lifetime fields."""
    dup = df[df.duplicated(["DATE", "PLAYER_ID"], keep=False)]
    cols = [
        "DATE",
        "PLAYER_ID",
        "PLATFORM_ID",
        "SESSIONS",
        "SESSION_MINS",
        "REVENUE",
        "LIFETIME_REVENUE",
        "PLATFORM_AGNOSTIC_LIFETIME_SPINS_DAYS",
    ]
    return dup[cols].sort_values(["PLAYER_ID", "DATE", "PLATFORM_ID"]).reset_index(drop=True)


@dataclass
class GrainEvidence:
    rows_with_sessions_share: float
    login_gap_matches_row_gap_share: float
    next_login_matches_next_row_share: float


def grain_evidence(df: pd.DataFrame) -> GrainEvidence:
    """Evidence that rows exist only on days a player was active."""
    s = df.sort_values(["PLAYER_ID", "DATE"])
    gap = s.groupby("PLAYER_ID")["DATE"].diff().dt.days
    has_gap = gap.notna()
    next_row = s.groupby("PLAYER_ID")["DATE"].shift(-1)
    next_login = parse_date_like(s["NEXT_LOGIN_DATE"])
    has_next = next_row.notna()
    return GrainEvidence(
        rows_with_sessions_share=float((df["SESSIONS"].fillna(0) > 0).mean()),
        login_gap_matches_row_gap_share=float(
            (s.loc[has_gap, "DAYS_SINCE_LAST_LOGIN"] == gap[has_gap]).mean()
        ),
        next_login_matches_next_row_share=float(
            (next_login[has_next] == next_row[has_next]).mean()
        ),
    )


# --------------------------------------------------------------------------- #
# Date and player coverage
# --------------------------------------------------------------------------- #


def daily_coverage(df: pd.DataFrame) -> pd.DataFrame:
    """Rows, players, installs, payers and revenue per data date (full calendar)."""
    revenue = df["REVENUE"].fillna(0)
    daily = (
        df.assign(
            is_install_day=df["DAYS_SINCE_INSTALL"].eq(0),
            is_payer_day=revenue.gt(0),
            revenue=revenue,
        )
        .groupby("DATE")
        .agg(
            rows=("PLAYER_ID", "size"),
            players=("PLAYER_ID", "nunique"),
            installs=("is_install_day", "sum"),
            payers=("is_payer_day", "sum"),
            revenue=("revenue", "sum"),
        )
    )
    calendar = pd.date_range(df["DATE"].min(), df["DATE"].max(), freq="D", name="DATE")
    daily = daily.reindex(calendar)
    daily["missing_date"] = daily["rows"].isna()
    return daily.fillna({"rows": 0, "players": 0, "installs": 0, "payers": 0, "revenue": 0})


def player_summary(df: pd.DataFrame) -> pd.DataFrame:
    """One row per player: observation window, activity and value to date."""
    g = df.sort_values("DATE").groupby("PLAYER_ID")
    out = g.agg(
        install_date=("INSTALL_DATE", "first"),
        first_seen=("DATE", "min"),
        last_seen=("DATE", "max"),
        rows=("DATE", "size"),
        active_days=("DATE", "nunique"),
        platforms=("PLATFORM_ID", "nunique"),
        max_days_since_install=("DAYS_SINCE_INSTALL", "max"),
        lifetime_revenue=("LIFETIME_REVENUE", "max"),
        revenue_in_rows=("REVENUE", "sum"),
    )
    out["install_date"] = out["install_date"].dt.normalize()
    out["install_cohort"] = out["install_date"].dt.to_period("M").astype(str)
    out["first_seen_age"] = (out["first_seen"] - out["install_date"]).dt.days
    out["observed_span_days"] = (out["last_seen"] - out["first_seen"]).dt.days + 1
    out["ever_payer"] = (out["lifetime_revenue"] > 0) | (out["revenue_in_rows"] > 0)
    return out.reset_index()


def cohort_coverage(players: pd.DataFrame, data_end: pd.Timestamp) -> pd.DataFrame:
    """Install cohorts: size, payers, and how old the cohort could be at the data end."""
    out = players.groupby("install_cohort").agg(
        players=("PLAYER_ID", "size"),
        ever_payers=("ever_payer", "sum"),
        first_install=("install_date", "min"),
        last_install=("install_date", "max"),
        median_rows=("rows", "median"),
    )
    out["max_possible_age_days"] = (data_end - out["first_install"]).dt.days
    out["min_possible_age_days"] = (data_end - out["last_install"]).dt.days
    out["payer_share"] = out["ever_payers"] / out["players"]
    return out.reset_index()


def rows_per_player_distribution(players: pd.DataFrame) -> pd.DataFrame:
    bins = [0, 1, 2, 3, 5, 10, 30, np.inf]
    labels = ["1", "2", "3", "4-5", "6-10", "11-30", "31+"]
    bucket = pd.cut(players["rows"], bins=bins, labels=labels)
    out = bucket.value_counts().reindex(labels).rename("players").to_frame()
    out["share"] = out["players"] / out["players"].sum()
    out.index.name = "rows_per_player"
    return out.reset_index()


# --------------------------------------------------------------------------- #
# Missingness and field groups
# --------------------------------------------------------------------------- #


def column_profile(df: pd.DataFrame) -> pd.DataFrame:
    """Per-column null share, distinct values, constant flag and field group."""
    groups = field_groups(df.columns).set_index("column")["field_group"]
    n_unique = df.nunique(dropna=True)
    null_share = df.isna().mean()
    prof = pd.DataFrame(
        {
            "column": df.columns,
            "field_group": groups.reindex(df.columns).values,
            "dtype": [str(t) for t in df.dtypes],
            "null_share": null_share.values,
            "n_unique": n_unique.values,
        }
    )
    prof["is_all_null"] = prof["null_share"].eq(1)
    prof["is_constant"] = prof["n_unique"].le(1) & ~prof["is_all_null"]
    prof["null_band"] = pd.cut(
        prof["null_share"],
        bins=[-0.001, 0, 0.5, 0.95, 0.999999, 1],
        labels=["0%", "0-50%", "50-95%", "95-<100%", "100%"],
    )
    return prof


def missingness_by_group(profile: pd.DataFrame) -> pd.DataFrame:
    """Field groups with column counts, null bands and unusable columns."""
    out = profile.groupby("field_group").agg(
        columns=("column", "size"),
        median_null_share=("null_share", "median"),
        all_null=("is_all_null", "sum"),
        constant=("is_constant", "sum"),
    )
    out["usable_columns"] = out["columns"] - out["all_null"] - out["constant"]
    return out.sort_values("columns", ascending=False).reset_index()


# --------------------------------------------------------------------------- #
# Data quality issues
# --------------------------------------------------------------------------- #


def check_d365_label(df: pd.DataFrame) -> dict:
    """Is D365_SPEND a mature 365-day outcome, or lifetime-to-date spend?"""
    filled = df[df["D365_SPEND"].notna()]
    per_player = filled.groupby("PLAYER_ID")["D365_SPEND"].nunique()
    return {
        "rows_filled": int(len(filled)),
        "players_filled": int(filled["PLAYER_ID"].nunique()),
        "share_equal_lifetime_revenue": float(
            (filled["D365_SPEND"] - filled["LIFETIME_REVENUE"]).abs().lt(0.01).mean()
        ),
        "filled_iff_lifetime_revenue_positive": float(
            (df["D365_SPEND"].notna() == df["LIFETIME_REVENUE"].gt(0)).mean()
        ),
        "players_value_changes_across_snapshots": int((per_player > 1).sum()),
        "max_days_since_install_any_row": int(df["DAYS_SINCE_INSTALL"].max()),
        "rows_at_or_after_day_365": int(df["DAYS_SINCE_INSTALL"].ge(365).sum()),
    }


def check_revenue_offset(df: pd.DataFrame) -> dict:
    """Does today's REVENUE land in today's or tomorrow's LIFETIME_REVENUE?"""
    s = df.sort_values(["PLAYER_ID", "DATE"]).copy()
    s["lt_change_into_row"] = s.groupby("PLAYER_ID")["LIFETIME_REVENUE"].diff()
    s["lt_change_into_next_row"] = s.groupby("PLAYER_ID")["lt_change_into_row"].shift(-1)
    paid = s[s["REVENUE"].fillna(0) > 0]
    same = paid.dropna(subset=["lt_change_into_row"])
    nxt = paid.dropna(subset=["lt_change_into_next_row"])
    return {
        "payer_rows": int(len(paid)),
        "matches_same_row_change": float(
            (same["REVENUE"] - same["lt_change_into_row"]).abs().lt(0.01).mean()
        ),
        "matches_next_row_change": float(
            (nxt["REVENUE"] - nxt["lt_change_into_next_row"]).abs().lt(0.01).mean()
        ),
        "players_with_revenue_but_zero_lifetime": int(
            s.groupby("PLAYER_ID")
            .agg(r=("REVENUE", "sum"), lt=("LIFETIME_REVENUE", "max"))
            .query("r > 0 and lt == 0")
            .shape[0]
        ),
    }


def late_updates(df: pd.DataFrame) -> pd.DataFrame:
    """Lag between the data date and the last update, by data month."""
    lag = (df["LAST_UPDATE_DATETIME"].dt.normalize() - df["DATE"]).dt.days
    return (
        df.assign(data_month=df["DATE"].dt.to_period("M").astype(str), update_lag_days=lag)
        .groupby("data_month")["update_lag_days"]
        .agg(rows="size", median_lag="median", max_lag="max", share_over_7d=lambda x: (x > 7).mean())
        .reset_index()
    )


def check_future_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Date fields that are later than the row's DATE (future information)."""
    cols = [
        "NEXT_LOGIN_DATE",
        "LAST_LOGIN_DATE",
        "PLATFORM_AGNOSTIC_LAST_LOGIN_DATE",
        "FIRST_PURCHASE_DATE",
        "LAST_PURCHASE_DATE",
        "REACTIVATION_3_DATE",
        "REACTIVATION_7_DATE",
        "REACTIVATION_14_DATE",
        "REACTIVATION_28_DATE",
    ]
    out = []
    for col in cols:
        d = parse_date_like(df[col])
        out.append(
            {
                "column": col,
                "filled_rows": int(d.notna().sum()),
                "rows_after_DATE": int((d > df["DATE"]).sum()),
                "share_after_DATE": float((d > df["DATE"]).sum() / max(d.notna().sum(), 1)),
            }
        )
    return pd.DataFrame(out)


def check_window_freeze(df: pd.DataFrame) -> dict:
    """Is D30_SPEND frozen after day 30, as a cohort metric should be?"""
    after = df[df["DAYS_SINCE_INSTALL"] > 30]
    changes = after.groupby("PLAYER_ID")["D30_SPEND"].nunique()
    return {"players_with_D30_SPEND_changing_after_day_30": int((changes > 1).sum())}


def quality_issues(df: pd.DataFrame) -> pd.DataFrame:
    """Headline data quality issues with evidence and business impact."""
    d365 = check_d365_label(df)
    offset = check_revenue_offset(df)
    lag = late_updates(df)
    future = check_future_dates(df).set_index("column")
    players = player_summary(df)
    cohort_sizes = players.groupby("install_cohort").size()
    window = check_window_freeze(df)
    from sciplay.data.registry import milestone_backfill_evidence
    backfill = milestone_backfill_evidence(df).set_index("column")
    d1 = backfill.loc["D1_RETURNER"]

    issues = [
        {
            "id": "Q1",
            "issue": "D365_SPEND is lifetime-to-date spend, not a 365-day outcome",
            "evidence": (
                f"Equals LIFETIME_REVENUE on {d365['share_equal_lifetime_revenue']:.0%} of filled rows; "
                f"null exactly when the player never paid; changes across snapshots for "
                f"{d365['players_value_changes_across_snapshots']} of {d365['players_filled']} payers; "
                f"oldest row is day {d365['max_days_since_install_any_row']} after install"
            ),
            "business_impact": (
                "Training on it would teach the model that LTV365 equals spend so far: "
                "systematic underprediction for young players and wrong UA / CRM budgets"
            ),
        },
        {
            "id": "Q2",
            "issue": "REVENUE and LIFETIME_REVENUE are offset by one day",
            "evidence": (
                f"Today's REVENUE matches the change into the same row "
                f"{offset['matches_same_row_change']:.0%} of the time and the change into the "
                f"next row {offset['matches_next_row_change']:.0%} of the time"
            ),
            "business_impact": (
                "Adding REVENUE to LIFETIME_REVENUE double counts; using only LIFETIME_REVENUE "
                "misses today's purchases. LTV-to-date and the opportunity gap shift by a day"
            ),
        },
        {
            "id": "Q3",
            "issue": "Rows keep being rewritten for 91 days after their data date",
            "evidence": (
                "Median days from data date to LAST_UPDATE_DATETIME, by data month: "
                + ", ".join(f"{r.data_month}: {r.median_lag:.0f}d" for r in lag.itertuples())
            ),
            "business_impact": (
                "Each row is updated until 91 days after its date, then freezes: D90_RETURNER can only "
                "be filled on D+90. Same mechanism as Q5. Once forward-looking columns are excluded the "
                "training data is safe; what remains is auditability of past lists"
            ),
        },
        {
            "id": "Q4",
            "issue": "Stratified sample: a fixed number of installs per month",
            "evidence": (
                "Players per install cohort: "
                + ", ".join(f"{k}: {v}" for k, v in cohort_sizes.items())
            ),
            "business_impact": (
                "Totals and pay rates are not population figures; dashboard totals must be "
                "labelled as sample totals, and the newest cohort is only days old"
            ),
        },
        {
            "id": "Q5",
            "issue": "Forward-looking and back-filled fields sit next to features",
            "evidence": (
                f"D<n>_RETURNER means 'played exactly n days after D' (100% match), so D1_RETURNER is already 1 on "
                f"{d1.positive_before_age} day-0 rows; "
                f"NEXT_LOGIN_DATE is after DATE on "
                f"{future.loc['NEXT_LOGIN_DATE', 'share_after_DATE']:.0%} of filled rows; "
                f"D30_SPEND changes after day 30 for "
                f"{window['players_with_D30_SPEND_changing_after_day_30']} players"
            ),
            "business_impact": (
                "Leaky features inflate offline accuracy and fail silently in production, "
                "so lists would flag the wrong players"
            ),
        },
        {
            "id": "Q6",
            "issue": "Cheater and legal-settlement flags are never set",
            "evidence": "IS_CHEATER, IS_CHEATER_DETECTED and IS_LEGAL_SETTLEMENT have a single value ('no' / False)",
            "business_impact": (
                "The exclusion policy cannot be tested on this sample; in production an "
                "untested filter could push offers to excluded players"
            ),
        },
    ]
    themes = {
        "Q1": "Target validity",
        "Q2": "Revenue definition",
        "Q3": "Time integrity (as-of policy)",
        "Q5": "Time integrity (as-of policy)",
        "Q4": "Sample limitations",
        "Q6": "Sample limitations",
    }
    out = pd.DataFrame(issues)
    out.insert(1, "theme", out["id"].map(themes))
    return out


# --------------------------------------------------------------------------- #
# Cohort views (used by the interactive charts)
# --------------------------------------------------------------------------- #


def active_players_by_cohort(df: pd.DataFrame) -> pd.DataFrame:
    """Distinct active players per data date, split by install month (long format)."""
    cohort = df["INSTALL_DATE"].dt.to_period("M").astype(str)
    out = (
        df.assign(install_cohort=cohort)
        .groupby(["DATE", "install_cohort"])["PLAYER_ID"]
        .nunique()
        .rename("players")
        .reset_index()
    )
    return out


AGE_BUCKETS = [0, 1, 2, 4, 8, 15, 31, 61, 91, 121, 181]
AGE_LABELS = ["D0", "D1", "D2-3", "D4-7", "D8-14", "D15-30", "D31-60", "D61-90", "D91-120", "D121-180"]


def cohort_activity_matrix(df: pd.DataFrame, data_end: pd.Timestamp, min_eligible: int = 1) -> pd.DataFrame:
    """Share of each install cohort active in each age bucket.

    Only players who had lived through the whole bucket by `data_end` are counted
    in its denominator, so young cohorts are not penalised for time they have not
    lived yet (cells with fewer than `min_eligible` eligible players are NaN).
    """
    install = df.groupby("PLAYER_ID")["INSTALL_DATE"].first().dt.normalize()
    cohort = install.dt.to_period("M").astype(str)
    max_age = (data_end - install).dt.days

    bucket = pd.cut(df["DAYS_SINCE_INSTALL"], bins=AGE_BUCKETS, labels=AGE_LABELS, right=False)
    active = (
        df.assign(bucket=bucket)
        .groupby(["PLAYER_ID", "bucket"], observed=True)
        .size()
        .gt(0)
        .rename("active")
        .reset_index()
    )
    rows = []
    for label, end in zip(AGE_LABELS, AGE_BUCKETS[1:]):
        eligible_ids = max_age.index[max_age >= end - 1]
        denom = cohort.loc[eligible_ids].value_counts()
        hit = active.loc[(active["bucket"] == label) & active["PLAYER_ID"].isin(eligible_ids), "PLAYER_ID"]
        numer = cohort.loc[hit.unique()].value_counts()
        for c in sorted(cohort.unique()):
            d = int(denom.get(c, 0))
            n = int(numer.get(c, 0))
            rows.append(
                {"install_cohort": c, "age_bucket": label, "eligible_players": d,
                 "active_players": n, "active_share": n / d if d >= max(min_eligible, 1) else np.nan}
            )
    return pd.DataFrame(rows)


def update_lag_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Row-level data date, last update date and lag in days."""
    upd = df["LAST_UPDATE_DATETIME"].dt.normalize()
    return pd.DataFrame(
        {"DATE": df["DATE"], "last_update": upd, "lag_days": (upd - df["DATE"]).dt.days}
    )


# --------------------------------------------------------------------------- #
# Inconsistent semantics: the name says one thing, the data shows another
# --------------------------------------------------------------------------- #


def inconsistent_semantics(df: pd.DataFrame) -> pd.DataFrame:
    """Fields whose meaning (semantics) differs from what their name suggests, with evidence."""
    from sciplay.data.registry import returner_label_evidence

    d365 = check_d365_label(df)
    window = check_window_freeze(df)
    offset = check_revenue_offset(df)
    ret = returner_label_evidence(df, horizons=(1, 7, 30))
    active_max = int(pd.to_numeric(df["D7_ACTIVE_DAYS"], errors="coerce").max())
    bucket = df["LT_SPENDER_BUCKET"]
    bucket_no_lt = bucket.notna() & df["LIFETIME_REVENUE"].eq(0)
    bucket_no_lt_paid = int((bucket_no_lt & df["REVENUE"].fillna(0).gt(0)).sum())
    flags = {c: sorted(df[c].dropna().map(str).unique()) for c in ["IS_CHEATER", "IS_CHEATER_DETECTED", "CHEATS_DETECTED"]}
    apple = int(df["PLATFORM_ID"].eq("apple_sign_in").sum())

    rows = [
        ("D365_SPEND", "Spend in the first 365 days",
         f"Equals LIFETIME_REVENUE on {d365['share_equal_lifetime_revenue']:.0%} of filled rows; oldest player is "
         f"{d365['max_days_since_install_any_row']} days old",
         "Excluded; not a valid target"),
        ("D1_RETURNER … D90_RETURNER", "Install milestone: came back by day n",
         "Played exactly n days after the row date: " + ", ".join(
             f"{r.column} {r.match_share:.1%}" for r in ret.itertuples()),
         "Excluded (future); possible churn label later"),
        ("D30_SPEND", "Spend in the first 30 days (fixed once day 30 has passed)",
         f"Still changes after day 30 for {window['players_with_D30_SPEND_changing_after_day_30']} players",
         "Excluded"),
        ("D7 / D14 / D30_ACTIVE_DAYS", "Number of active days",
         f"Maximum value is {active_max}: a yes/no flag, not a count", "Excluded until verified"),
        ("LIFETIME_REVENUE", "Revenue up to and including the row date",
         f"Excludes the row date: today's REVENUE shows up in the next row {offset['matches_next_row_change']:.0%} of the time",
         "Kept; revenue to date = LIFETIME_REVENUE + REVENUE"),
        ("LT_SPENDER_BUCKET", "Lifetime spender tier, consistent with LIFETIME_REVENUE",
         f"{int(bucket_no_lt.sum())} rows say 'Minnow' while LIFETIME_REVENUE = 0; {bucket_no_lt_paid} of them are "
         "first-purchase days (bucket is end of day, lifetime is start of day)",
         "Reporting only"),
        ("IS_CHEATER, IS_CHEATER_DETECTED, CHEATS_DETECTED", "One yes/no concept",
         "Three encodings: " + "; ".join(f"{k} = {v}" for k, v in flags.items()),
         "Normalised to one boolean in the eligibility filter"),
        ("PLATFORM_ID = apple_sign_in", "A platform", f"A login method ({apple} rows)", "Kept as a platform value (A5)"),
    ]
    return pd.DataFrame(rows, columns=["field", "name suggests", "data shows", "decision"])
