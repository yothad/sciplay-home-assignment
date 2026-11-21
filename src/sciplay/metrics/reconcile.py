"""Reconcile dashboard totals to the data, computed a second, independent way.

The dashboard path is pandas over the prepared player-day table. The check path is
DuckDB SQL straight over the raw CSV. A mismatch means the prepare step or a metric
definition changed something it should not have.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

TOLERANCE = 0.01


def _source(raw_path: Path) -> str:
    p = Path(raw_path).as_posix()
    return f"read_parquet('{p}')" if p.endswith(".parquet") else f"read_csv_auto('{p}', sample_size=-1)"


def _sql_totals(raw_csv: Path) -> dict:
    con = duckdb.connect()
    q = f"""
    WITH raw AS (SELECT * FROM {_source(raw_csv)}),
    pd AS (
        SELECT CAST(DATE AS DATE) AS d, PLAYER_ID,
               SUM(COALESCE(REVENUE, 0)) AS rev,
               MAX(CASE WHEN DAYS_SINCE_INSTALL = 0 THEN 1 ELSE 0 END) AS install_day
        FROM raw GROUP BY 1, 2)
    SELECT
        (SELECT COUNT(*) FROM raw)                                  AS raw_rows,
        COUNT(*)                                                    AS player_days,
        COUNT(DISTINCT PLAYER_ID)                                   AS players,
        SUM(rev)                                                    AS revenue,
        SUM(CASE WHEN rev > 0 THEN 1 ELSE 0 END)                    AS payer_days,
        SUM(install_day)                                            AS new_players,
        MIN(d)                                                      AS data_start,
        MAX(d)                                                      AS data_end
    FROM pd
    """
    row = con.execute(q).fetchdf().iloc[0].to_dict()
    con.close()
    return row


def reconcile(daily_metrics: pd.DataFrame, player_day: pd.DataFrame, raw_csv: Path) -> pd.DataFrame:
    """Table of dashboard total vs independent total, with difference and pass/fail."""
    sql = _sql_totals(raw_csv)
    dash = {
        "player_days": float(daily_metrics["active_players"].sum()),
        "players": float(player_day["PLAYER_ID"].nunique()),
        "revenue": float(daily_metrics["revenue"].sum()),
        "payer_days": float(daily_metrics["payers"].sum()),
        "new_players": float(daily_metrics["new_players"].sum()),
    }
    labels = {
        "player_days": "Active player-days (sum of daily active players)",
        "players": "Distinct players",
        "revenue": "Total revenue (USD)",
        "payer_days": "Paying player-days",
        "new_players": "New players (install days)",
    }
    rows = []
    for key, label in labels.items():
        a, b = dash[key], float(sql[key])
        rows.append({"check": label, "dashboard": a, "independent_sql": b, "difference": a - b,
                     "passed": abs(a - b) <= TOLERANCE})
    rows.append({"check": "Raw rows → player-days (platform rollup)", "dashboard": float(len(player_day)),
                 "independent_sql": float(sql["player_days"]),
                 "difference": float(len(player_day)) - float(sql["player_days"]),
                 "passed": len(player_day) == int(sql["player_days"])})
    return pd.DataFrame(rows)


def reconcile_day(daily_metrics: pd.DataFrame, raw_path: Path, score_date) -> pd.DataFrame:
    """The score date's headline numbers (as shown on the Overview, no filters) vs SQL on the raw input."""
    d = pd.Timestamp(score_date).date()
    con = duckdb.connect()
    q = f"""
    WITH raw AS (SELECT * FROM {_source(raw_path)} WHERE CAST(DATE AS DATE) = DATE '{d}'),
    pd AS (SELECT PLAYER_ID, SUM(COALESCE(REVENUE, 0)) AS rev,
                  MAX(CASE WHEN DAYS_SINCE_INSTALL = 0 THEN 1 ELSE 0 END) AS inst
           FROM raw GROUP BY PLAYER_ID)
    SELECT COUNT(*) AS active_players, COALESCE(SUM(inst), 0) AS new_players,
           COALESCE(SUM(CASE WHEN rev > 0 THEN 1 ELSE 0 END), 0) AS payers, COALESCE(SUM(rev), 0) AS revenue
    FROM pd
    """
    sql = con.execute(q).fetchdf().iloc[0].to_dict()
    con.close()
    dm = daily_metrics.copy()
    if "DATE" in dm.columns:
        dm = dm.set_index("DATE")
    day = dm.loc[pd.Timestamp(score_date)] if pd.Timestamp(score_date) in dm.index else None
    labels = {"active_players": "Active players", "new_players": "New players", "payers": "Paying players",
              "revenue": "Revenue (USD)"}
    rows = []
    for key, label in labels.items():
        a = float(day[key]) if day is not None else 0.0
        b = float(sql[key])
        rows.append({"check": f"{label} on {d:%d %b %Y}", "dashboard": a, "independent_sql": b,
                     "difference": a - b, "passed": abs(a - b) <= TOLERANCE})
    return pd.DataFrame(rows)
