"""Data health checks for one data date, compared with its own history.

Each check answers "is the data for day D complete and normal?" by comparing D with
the trailing `window` days before it. Status: pass / warn / fail, with the reason.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PASS, WARN, FAIL, INFO = "pass", "warn", "fail", "info"
WINDOW = 28
KEY_FIELDS = ["COUNTRY", "REGION", "DEVICE_TYPE", "SOURCE_TYPE", "SESSIONS", "LIFETIME_REVENUE"]
CATEGORIES = {"Platform": "MAIN_PLATFORM_ID", "Country": "COUNTRY", "Acquisition type": "SOURCE_TYPE"}
REWRITE_DAYS = 91  # rows keep changing until 91 days after their date (Part 1, Q3)


def _row(check, area, value, baseline, status, detail):
    return {"area": area, "check": check, "on_date": value, "history": baseline, "status": status, "detail": detail}


def _volume(series: pd.Series, d: pd.Timestamp, label: str, area: str, window: int, tol: float = 3.0) -> dict:
    hist = series.loc[d - pd.Timedelta(days=window): d - pd.Timedelta(days=1)]
    value = float(series.get(d, 0))
    mean, sd = hist.mean(), hist.std(ddof=0)
    if len(hist) < 7:
        return _row(label, area, value, np.nan, INFO, "Fewer than 7 days of history")
    z = (value - mean) / sd if sd > 0 else 0.0
    status = PASS if abs(z) <= tol else WARN
    return _row(label, area, value, round(mean, 2), status,
                f"{z:+.1f} standard deviations from the {window}-day average" + ("" if status == PASS else " (outside ±3)"))


def run_checks(pday: pd.DataFrame, score_date: pd.Timestamp, raw: pd.DataFrame | None = None,
               window: int = WINDOW) -> pd.DataFrame:
    d = pd.Timestamp(score_date)
    rows = []
    latest = pday["DATE"].max()
    day = pday[pday["DATE"] == d]
    hist = pday[(pday["DATE"] < d) & (pday["DATE"] >= d - pd.Timedelta(days=window))]

    # Freshness
    rows.append(_row("Rows have landed for the date", "Freshness", len(day), np.nan,
                     PASS if len(day) else FAIL, "No rows for this date: data has not landed" if not len(day) else
                     f"Latest date in the data: {latest:%d %b %Y}"))
    prev = pday[pday["DATE"] == d - pd.Timedelta(days=1)]
    rows.append(_row("Previous day has rows", "Freshness", len(prev), np.nan, PASS if len(prev) else WARN,
                     "A gap the day before can mean a missed load"))
    if "LAST_UPDATE_DATETIME" in day and len(day):
        lag = (day["LAST_UPDATE_DATETIME"].dt.normalize() - day["DATE"]).dt.days.median()
        open_days = (latest - d).days
        rows.append(_row("Rows for the date may still change", "Freshness", open_days, REWRITE_DAYS,
                         INFO if open_days < REWRITE_DAYS else PASS,
                         f"Median update lag {lag:.0f} days. Rows keep changing until {REWRITE_DAYS} days after their date "
                         f"(forward-looking flags); this date is {open_days} days old in the file"))

    # Volume against history
    daily_rows = pday.groupby("DATE").size()
    daily_new = pday.groupby("DATE")["is_install_day"].sum()
    daily_pay = pday.groupby("DATE")["is_payer_day"].sum()
    rows.append(_volume(daily_rows, d, "Player-days (rows) vs history", "Volume", window))
    rows.append(_volume(daily_new, d, "New players vs history", "Volume", window))
    rows.append(_volume(daily_pay, d, "Paying players vs history", "Volume", window))

    # Missing values in key fields
    for col in [c for c in KEY_FIELDS if c in pday.columns]:
        share_d = day[col].isna().mean() if len(day) else np.nan
        share_h = hist[col].isna().mean() if len(hist) else np.nan
        worse = (share_d - share_h) if not (np.isnan(share_d) or np.isnan(share_h)) else 0
        status = PASS if worse <= 0.10 else WARN
        rows.append(_row(f"Empty {col}", "Missing values", round(share_d, 3), round(share_h, 3), status,
                         "Share of rows empty on the date vs the previous days" +
                         ("" if status == PASS else " (more than 10 points worse)")))

    # New categories
    before = pday[pday["DATE"] < d]
    for label, col in [(lb, c) for lb, c in CATEGORIES.items() if c in pday.columns]:
        new_values = sorted(set(day[col].dropna().astype(str)) - set(before[col].dropna().astype(str)))
        rows.append(_row(f"New {label.lower()} values", "Consistency", len(new_values), np.nan,
                         PASS if not new_values else WARN, ", ".join(new_values) if new_values else "None"))

    # Validity
    neg = int((day["revenue"] < 0).sum())
    rows.append(_row("Negative revenue", "Validity", neg, np.nan, PASS if neg == 0 else FAIL, "Revenue must be ≥ 0"))
    no_sessions = int((day["SESSIONS"].fillna(0) <= 0).sum())
    rows.append(_row("Rows without sessions", "Validity", no_sessions, np.nan, PASS if no_sessions == 0 else WARN,
                     "A row should mean the player played (A1)"))
    s = pday[pday["DATE"] <= d].sort_values(["PLAYER_ID", "DATE"])
    drop = s.groupby("PLAYER_ID")["revenue_to_date"].diff() < -0.01
    dropped = int((drop & s["DATE"].eq(d)).sum())
    rows.append(_row("Revenue to date decreased", "Validity", dropped, np.nan, PASS if dropped == 0 else FAIL,
                     "Lifetime revenue can only grow (refunds would show here)"))

    # Raw-file checks
    if raw is not None:
        raw_day = raw[raw["DATE"] == d]
        dups = int(raw_day.duplicated(["DATE", "PLAYER_ID", "PLATFORM_ID"]).sum())
        rows.append(_row("Duplicate keys (date, player, platform)", "Validity", dups, np.nan,
                         PASS if dups == 0 else FAIL, "The grain key must be unique"))
        multi = int(raw_day.duplicated(["DATE", "PLAYER_ID"]).sum())
        rows.append(_row("Players on two platforms", "Consistency", multi, np.nan, INFO,
                         "Combined into one row per player per day"))
    return pd.DataFrame(rows)


def history_band(pday: pd.DataFrame, window: int = WINDOW) -> pd.DataFrame:
    """Daily player-days with a trailing mean ± 3 standard deviations, for the chart."""
    s = pday.groupby("DATE").size()
    s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq="D"), fill_value=0)
    m = s.shift(1).rolling(window, min_periods=7).mean()
    sd = s.shift(1).rolling(window, min_periods=7).std(ddof=0)
    return pd.DataFrame({"rows": s, "mean": m, "low": (m - 3 * sd).clip(lower=0), "high": m + 3 * sd})
