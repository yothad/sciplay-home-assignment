"""Prepare step: raw CSV -> prepared Parquet tables the dashboard and models read.

Run:  uv run python -m sciplay.pipeline.prepare

Writes to PROCESSED_DIR (default data/processed):
  player_day.parquet          one row per player per day played (platforms rolled up)
  daily_metrics.parquet       dashboard KPIs per calendar day, no filters
  cohort_activity.parquet     share of each install cohort active by age bucket
  cohort_revenue.parquet      cumulative revenue per install by age
  raw_input.parquet           the exact raw rows this build used (for reconciliation)
  manifest.json               source file, row counts, data end, cohort sizes, build time
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from sciplay.audit.checks import cohort_activity_matrix, column_profile
from sciplay.config import get_settings
from sciplay.data.asof import revenue_to_date, rollup_player_day
from sciplay.data.loader import load_raw
from sciplay.data.registry import build_registry
from sciplay.metrics.kpis import cumulative_revenue_per_install, daily_kpis

PREPARE_VERSION = "1"


def build_player_day(raw: pd.DataFrame) -> pd.DataFrame:
    """Roll platforms up to player-day and add the columns the dashboard needs."""
    reg = build_registry(raw, column_profile(raw))
    pday = rollup_player_day(raw, reg)
    pday["revenue"] = pday["REVENUE"].fillna(0.0)
    pday["revenue_to_date"] = revenue_to_date(pday)
    pday["ever_payer"] = pday["revenue_to_date"] > 0
    pday["is_payer_day"] = pday["revenue"] > 0
    pday["is_install_day"] = pday["DAYS_SINCE_INSTALL"].eq(0)
    pday["install_date"] = pday["INSTALL_DATE"].dt.normalize()
    pday["install_cohort"] = pday["install_date"].dt.to_period("M").astype(str)
    pday["age_days"] = (pday["DATE"] - pday["install_date"]).dt.days
    return pday


def run(raw_path: Path | None = None, out_dir: Path | None = None, raw: pd.DataFrame | None = None,
        source: str | None = None) -> dict:
    """Build every prepared table from a raw file (or an already merged raw frame)."""
    settings = get_settings()
    out_dir = Path(out_dir or settings.processed_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if raw is None:
        raw_path = Path(raw_path or settings.raw_data_path)
        raw = load_raw(raw_path)
        source = source or raw_path.name

    raw_out = raw.copy()
    for col in raw_out.columns[raw_out.dtypes == object]:
        raw_out[col] = raw_out[col].astype("string")
    raw_out.to_parquet(out_dir / "raw_input.parquet", index=False)
    pday = build_player_day(raw)
    data_end = pday["DATE"].max()

    # Object columns with mixed types do not round-trip through Parquet: store them as text.
    for col in pday.columns[pday.dtypes == object]:
        pday[col] = pday[col].astype("string")
    pday.to_parquet(out_dir / "player_day.parquet", index=False)
    daily_kpis(pday).reset_index().to_parquet(out_dir / "daily_metrics.parquet", index=False)
    cohort_activity_matrix(pday, data_end).to_parquet(out_dir / "cohort_activity.parquet", index=False)
    cumulative_revenue_per_install(pday, data_end).to_parquet(out_dir / "cohort_revenue.parquet", index=False)

    manifest = {
        "prepare_version": PREPARE_VERSION,
        "source_file": source or "unknown",
        "raw_rows": int(len(raw)),
        "player_day_rows": int(len(pday)),
        "players": int(pday["PLAYER_ID"].nunique()),
        "data_start": str(pday["DATE"].min().date()),
        "data_end": str(data_end.date()),
        "installs_per_month": {k: int(v) for k, v in pday.groupby("install_cohort")["PLAYER_ID"].nunique().items()},
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
