"""Dashboard metrics: one definition, used by the app, the HTML snapshot and the tests.

All metrics are computed from the prepared player-day table (one row per player per
day played). A day with no rows is a real zero for counts and revenue; a ratio whose
denominator is zero is "not applicable" (NaN), never 0.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

ALL = "All"
PAYER_STATUSES = [ALL, "Ever-payer", "Non-payer"]


@dataclass(frozen=True)
class Kpi:
    key: str
    label: str
    unit: str  # count | money | pct
    meaning: str


KPIS: list[Kpi] = [
    Kpi("active_players", "Active players", "count", "Players with a row (sessions) on the day"),
    Kpi("new_players", "New players", "count", "Players on their install day"),
    Kpi("payers", "Paying players", "count", "Active players with revenue that day"),
    Kpi("revenue", "Revenue", "money", "Gross in-app revenue that day (USD)"),
    Kpi("arpdau", "Revenue per active player", "money", "Revenue / active players (ARPDAU)"),
    Kpi("arppu", "Revenue per paying player", "money", "Revenue / paying players (ARPPU)"),
    Kpi("payer_rate", "Payer rate", "pct", "Paying players / active players"),
]
KPI_BY_KEY = {k.key: k for k in KPIS}


# --------------------------------------------------------------------------- filters


RATIOS = {"arpdau": ("revenue", "active_players"), "arppu": ("revenue", "payers"),
          "payer_rate": ("payers", "active_players")}

# Dimension columns for filters and breakdown tables (values as of each row's day).
DIMENSIONS = {
    "Platform": "MAIN_PLATFORM_ID",
    "Install month": "install_cohort",
    "Payer status": "payer_status",
    "Region": "REGION",
    "Country": "COUNTRY",
    "Acquisition type": "SOURCE_TYPE",
}


def filter_player_day(pday: pd.DataFrame, platforms: list[str] | None = None,
                      cohorts: list[str] | None = None, payer_status: str = ALL,
                      countries: list[str] | None = None, acquisition: list[str] | None = None) -> pd.DataFrame:
    """Apply the dashboard filters. Payer status, country and acquisition type are as of each row's day."""
    out = pday
    if platforms:
        out = out[out["MAIN_PLATFORM_ID"].isin(platforms)]
    if cohorts:
        out = out[out["install_cohort"].isin(cohorts)]
    if countries:
        out = out[out["COUNTRY"].isin(countries)]
    if acquisition:
        out = out[out["SOURCE_TYPE"].isin(acquisition)]
    if payer_status == "Ever-payer":
        out = out[out["ever_payer"]]
    elif payer_status == "Non-payer":
        out = out[~out["ever_payer"]]
    return out


# --------------------------------------------------------------------------- daily KPIs


def daily_kpis(pday: pd.DataFrame, start: pd.Timestamp | None = None,
               end: pd.Timestamp | None = None) -> pd.DataFrame:
    """One row per calendar day: counts, revenue and ratios."""
    start = pd.Timestamp(start) if start is not None else pday["DATE"].min()
    end = pd.Timestamp(end) if end is not None else pday["DATE"].max()
    g = pday.groupby("DATE")
    out = pd.DataFrame({
        "active_players": g["PLAYER_ID"].nunique(),
        "new_players": g["is_install_day"].sum(),
        "payers": g["is_payer_day"].sum(),
        "revenue": g["revenue"].sum(),
    })
    calendar = pd.date_range(start, end, freq="D", name="DATE")
    out = out.reindex(calendar).fillna(0)
    out[["active_players", "new_players", "payers"]] = out[["active_players", "new_players", "payers"]].astype(int)
    return _add_ratios(out, out)


def _add_ratios(out: pd.DataFrame, sums: pd.DataFrame) -> pd.DataFrame:
    """Ratios from summed numerators and denominators; a zero denominator gives NaN (not applicable)."""
    for key, (num, den) in RATIOS.items():
        out[key] = sums[num] / sums[den].replace(0, np.nan)
    return out


def rolling(kpis: pd.DataFrame, window: int = 7) -> pd.DataFrame:
    """Trailing averages; ratios are recomputed from rolled sums, not averaged."""
    sums = kpis[["active_players", "new_players", "payers", "revenue"]].rolling(window, min_periods=window).sum()
    return _add_ratios(sums / window, sums)


def weekly(kpis: pd.DataFrame) -> pd.DataFrame:
    """Weeks starting Monday: averages per day for counts and revenue, ratios from sums."""
    s = kpis[["active_players", "new_players", "payers", "revenue"]]
    sums = s.resample("W-MON", label="left", closed="left").sum()
    days = s["active_players"].resample("W-MON", label="left", closed="left").size()
    out = _add_ratios(sums.div(days, axis=0), sums)
    out["days_in_week"] = days
    return out


def overview(kpis: pd.DataFrame, score_date: pd.Timestamp, window: int = 7) -> pd.DataFrame:
    """Each KPI on the score date against the average of the previous `window` days."""
    d = pd.Timestamp(score_date)
    prior = kpis.loc[d - pd.Timedelta(days=window): d - pd.Timedelta(days=1)]
    rows = []
    for k in KPIS:
        value = kpis.loc[d, k.key] if d in kpis.index else np.nan
        if k.key in RATIOS:
            num, den = RATIOS[k.key]
            base = prior[num].sum() / prior[den].sum() if prior[den].sum() else np.nan
        else:
            base = prior[k.key].mean() if len(prior) else np.nan
        change = (value - base) / base if base and not np.isnan(base) and not np.isnan(value) else np.nan
        rows.append({"key": k.key, "label": k.label, "unit": k.unit, "value": value,
                     "prior_avg": base, "change": change})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- player base as of D


def player_base(snapshot: pd.DataFrame, churn_days: int = 30) -> dict:
    """Counts from the as-of snapshot: who is in the active base and who has churned (A12)."""
    seen_recently = snapshot["days_since_last_seen"] < churn_days
    return {
        "players_known": int(len(snapshot)),
        "active_base": int(seen_recently.sum()),
        "churned": int((~seen_recently).sum()),
        "ever_payers_in_base": int((seen_recently & snapshot["revenue_to_date"].gt(0)).sum()),
        "revenue_to_date": float(snapshot["revenue_to_date"].sum()),
    }


# --------------------------------------------------------------------------- cohorts


MIN_PLAYERS_PER_POINT = 20
MIN_PLAYERS_POOLED = 50  # the pooled line mixes cohorts; at older ages only the earliest installs remain


def cumulative_revenue_per_install(pday: pd.DataFrame, data_end: pd.Timestamp,
                                   max_age: int = 180, min_players: int = MIN_PLAYERS_PER_POINT,
                                   min_players_pooled: int = MIN_PLAYERS_POOLED) -> pd.DataFrame:
    """Cumulative revenue per install by age, per install month and pooled.

    At each age a, the average revenue on day a is taken over the players who had reached
    age a by `data_end`; the curve is the running sum of those daily averages. This uses
    every player available at each age and cannot fall when the mix of players changes
    (a plain average of cumulative revenue drops when early big spenders leave the set).
    Ages no player of a cohort has reached are missing (not yet available), not zero.
    Points based on fewer than `min_players` players (`min_players_pooled` for the pooled
    line) are dropped: one big spender among a handful would dominate them.
    """
    players = pday.groupby("PLAYER_ID").agg(install_date=("install_date", "first"),
                                            install_cohort=("install_cohort", "first"))
    players["max_age"] = (pd.Timestamp(data_end) - players["install_date"]).dt.days
    rev = pday.groupby(["PLAYER_ID", "age_days"])["revenue"].sum()
    ages = np.arange(0, max_age + 1)
    daily = rev.unstack(fill_value=0).reindex(index=players.index, columns=ages, fill_value=0)
    lived = players["max_age"].to_numpy()[:, None] >= ages[None, :]
    daily = daily.where(lived)

    out = []
    for cohort, idx in list(players.groupby("install_cohort").groups.items()) + [("All cohorts", players.index)]:
        sub = daily.loc[idx]
        n = sub.notna().sum()
        out.append(pd.DataFrame({"install_cohort": cohort, "age_days": ages,
                                 "revenue_per_install": sub.mean().fillna(0).cumsum().to_numpy(),
                                 "players": n.to_numpy()}))
    res = pd.concat(out, ignore_index=True)
    floor = np.where(res["install_cohort"] == "All cohorts", min_players_pooled, min_players)
    return res[res["players"] >= floor].reset_index(drop=True)


# --------------------------------------------------------------------------- breakdowns


def breakdown(rows: pd.DataFrame, score_date: pd.Timestamp, column: str) -> pd.DataFrame:
    """KPIs on the score date split by one dimension (values as of that day)."""
    day = rows[rows["DATE"] == pd.Timestamp(score_date)].copy()
    if column == "payer_status":
        day["payer_status"] = np.where(day["ever_payer"], "Ever-payer", "Non-payer")
    day[column] = day[column].astype("string").fillna("— missing")
    g = day.groupby(column)
    out = pd.DataFrame({
        "active_players": g["PLAYER_ID"].nunique(),
        "new_players": g["is_install_day"].sum().astype(int),
        "payers": g["is_payer_day"].sum().astype(int),
        "revenue": g["revenue"].sum(),
    })
    out = _add_ratios(out, out).sort_values("active_players", ascending=False)
    return out.reset_index().rename(columns={column: "group"})


# --------------------------------------------------------------------------- payer cohorts


def first_purchases(pday: pd.DataFrame, score_date: pd.Timestamp | None = None) -> pd.DataFrame:
    """One row per payer: first purchase date (first day with revenue), its value, and timing."""
    rows = pday if score_date is None else pday[pday["DATE"] <= pd.Timestamp(score_date)]
    paid = rows[rows["is_payer_day"]].sort_values("DATE")
    first = paid.groupby("PLAYER_ID").agg(first_purchase=("DATE", "first"), first_value=("revenue", "first"),
                                          install_date=("install_date", "first"))
    first["purchase_cohort"] = first["first_purchase"].dt.to_period("M").astype(str)
    first["days_install_to_first_purchase"] = (first["first_purchase"] - first["install_date"]).dt.days
    return first.reset_index()


def cumulative_revenue_per_payer(pday: pd.DataFrame, score_date: pd.Timestamp, max_days: int = 120,
                                 min_payers: int = 5) -> pd.DataFrame:
    """Average cumulative revenue per payer by days since first purchase (pooled).

    Same rule as the install curves: only payers whose first purchase is at least t days
    before the score date count at day t; points with fewer than `min_payers` are dropped.
    """
    d = pd.Timestamp(score_date)
    first = first_purchases(pday, d).set_index("PLAYER_ID")
    if first.empty:
        return pd.DataFrame(columns=["days_since_first_purchase", "revenue_per_payer", "payers"])
    rows = pday[(pday["DATE"] <= d) & pday["PLAYER_ID"].isin(first.index)].copy()
    rows["t"] = (rows["DATE"] - rows["PLAYER_ID"].map(first["first_purchase"])).dt.days
    rows = rows[rows["t"] >= 0]
    days = np.arange(0, max_days + 1)
    grid = (rows.groupby(["PLAYER_ID", "t"])["revenue"].sum().unstack(fill_value=0)
            .reindex(index=first.index, columns=days, fill_value=0).cumsum(axis=1))
    lived = (d - first["first_purchase"]).dt.days.to_numpy()[:, None] >= days[None, :]
    grid = grid.where(lived)
    out = pd.DataFrame({"days_since_first_purchase": days, "revenue_per_payer": grid.mean().to_numpy(),
                        "payers": grid.notna().sum().to_numpy()})
    return out[out["payers"] >= min_payers].reset_index(drop=True)


# --------------------------------------------------------------------------- segments

SEGMENTS = {"Platform": "MAIN_PLATFORM_ID", "Country": "COUNTRY", "Seniority": "seniority",
            "Acquisition type": "SOURCE_TYPE", "Payer group": "payer_status"}
SENIORITY_BINS, SENIORITY_LABELS = [-1, 29, 89, 10_000], ["0–29 days", "30–89 days", "90+ days"]


def segments(rows: pd.DataFrame, score_date: pd.Timestamp, column: str, lists: pd.DataFrame | None = None,
             ltv: pd.DataFrame | None = None, window: int = 28, top: int = 8) -> pd.DataFrame:
    """Compare groups of the player base (seen in the last 30 days) on the score date: activity and revenue over the
    last `window` days, payer share, predicted LTV365 and how many are on today's lists."""
    from sciplay.data.asof import snapshot_as_of
    D = pd.Timestamp(score_date)
    snap = snapshot_as_of(rows, D)
    snap = snap[snap["days_since_last_seen"] < 30].copy()
    if snap.empty:
        return pd.DataFrame()
    snap["payer_status"] = np.where(snap["ever_payer"], "Ever-payer", "Non-payer")
    snap["seniority"] = pd.cut((D - snap["install_date"]).dt.days, SENIORITY_BINS, labels=SENIORITY_LABELS).astype(str)
    snap[column] = snap[column].astype("string").fillna("— missing")
    if column == "COUNTRY":                                 # many small countries: keep the largest, pool the rest
        keep = snap[column].value_counts().index[:top]
        snap.loc[~snap[column].isin(keep), column] = "Other"
    recent = rows[(rows["DATE"] > D - pd.Timedelta(days=window)) & (rows["DATE"] <= D)]
    recent = recent[recent["PLAYER_ID"].isin(snap["PLAYER_ID"])].merge(snap[["PLAYER_ID", column]], on="PLAYER_ID",
                                                                         suffixes=("_row", ""))
    g = snap.groupby(column)
    out = pd.DataFrame({"players": g["PLAYER_ID"].nunique(), "payer_share": g["ever_payer"].mean()})
    r = recent.groupby(column)
    out["days_played_per_player"] = r.size() / out["players"]
    out["revenue_28d"] = r["revenue"].sum()
    out["revenue_per_player_28d"] = out["revenue_28d"] / out["players"]
    if ltv is not None and len(ltv):
        v = snap.merge(ltv[["player_id", "predicted_ltv_365"]], left_on="PLAYER_ID", right_on="player_id", how="left")
        out["avg_ltv_365"] = v.groupby(column)["predicted_ltv_365"].mean()
    if lists is not None:
        on = snap.merge(lists[["player_id", "opportunity_gap"]], left_on="PLAYER_ID", right_on="player_id", how="inner")
        out["on_a_list"] = on.groupby(column).size()
        out["value_at_risk"] = on.groupby(column)["opportunity_gap"].sum()
        out[["on_a_list", "value_at_risk"]] = out[["on_a_list", "value_at_risk"]].fillna(0)
        out["list_rate"] = out["on_a_list"] / out["players"]
    out = out.fillna({"days_played_per_player": 0, "revenue_28d": 0, "revenue_per_player_28d": 0})
    return out.sort_values("players", ascending=False).reset_index().rename(columns={column: "group"})


def engagement_daily(rows: pd.DataFrame) -> pd.DataFrame:
    """Sessions and session minutes per active player, per day."""
    g = rows.groupby("DATE")
    out = pd.DataFrame({"active": g["PLAYER_ID"].nunique(), "sessions": g["SESSIONS"].sum(),
                        "minutes": g["SESSION_MINS"].sum()})
    out["sessions_per_active"] = out["sessions"] / out["active"]
    out["minutes_per_active"] = out["minutes"] / out["active"]
    return out
