"""Daily refresh: take in new extracts, merge, rebuild, check, and publish only if healthy.

Run:  uv run python -m sciplay.pipeline.refresh [--file PATH] [--force]

Steps
  1. Intake   New CSVs in data/raw/incoming/ (or --file) are copied into data/raw/extracts/
              with a timestamp prefix, and removed from incoming. On the first run the
              configured RAW_DATA_PATH becomes the first extract.
  2. Merge    All extracts are combined; for each (DATE, PLAYER_ID, PLATFORM_ID) the version
              with the latest LAST_UPDATE_DATETIME wins (ties: the newer extract). This keeps
              history when a file holds only new days, and applies restated rows (rows keep
              changing for 91 days after their date).
  3. Build    The prepare step writes all tables to a staging folder.
  4. Gate     Health checks run on the newest date. Any failed check, or no date newer than
              the published data (unless --force), stops the run: the dashboard keeps
              yesterday's tables.
  5. Publish  Staged files replace the published ones.
  6. LTV      Score the new date with the active LTV model (stored in SQLite); never blocks publishing.
  7. Lists    Build the daily lists for the new date; never blocks publishing.
  6. Log      Every run is appended to data/store/refresh_log.jsonl.

Exit codes: 0 published, 1 blocked by the health gate, 2 no new data, 3 no input.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from sciplay.config import REPO_ROOT, get_settings
from sciplay.data.loader import KEY_COLUMNS, load_raw
from sciplay.metrics.health import FAIL, WARN, run_checks
from sciplay.pipeline import prepare

PUBLISHED = ["player_day.parquet", "daily_metrics.parquet", "cohort_activity.parquet",
             "cohort_revenue.parquet", "raw_input.parquet", "manifest.json"]


@dataclass
class Paths:
    incoming: Path
    extracts: Path
    processed: Path
    staging: Path
    log: Path

    @classmethod
    def default(cls) -> "Paths":
        s = get_settings()
        raw_dir = s.raw_data_path.parent
        return cls(incoming=raw_dir / "incoming", extracts=raw_dir / "extracts", processed=s.processed_dir,
                   staging=s.processed_dir / "_staging", log=s.store_db_path.parent / "refresh_log.jsonl")


@dataclass
class RunResult:
    status: str  # published | blocked | no_new_data | no_input
    exit_code: int
    started_at: str
    new_extracts: list[str] = field(default_factory=list)
    extracts_used: int = 0
    rows_merged: int = 0
    rows_replaced_by_newer_version: int = 0
    previous_data_end: str | None = None
    data_end: str | None = None
    checked_date: str | None = None
    failed_checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    message: str = ""
    ltv: str = ""  # result of scoring LTV for the new data end (never blocks publishing)
    lists: str = ""  # result of the daily lists for the new data end (never blocks publishing)
    alerts: str = ""  # event alerts for the new lists, dry run to the outbox (never blocks publishing)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def intake(paths: Paths, file: Path | None = None, base_file: Path | None = None) -> list[str]:
    """Copy new extracts into the archive. Returns the archived file names."""
    paths.extracts.mkdir(parents=True, exist_ok=True)
    paths.incoming.mkdir(parents=True, exist_ok=True)
    added = []
    if not any(paths.extracts.glob("*.csv")) and base_file is not None and Path(base_file).exists():
        target = paths.extracts / f"{_stamp()}__{Path(base_file).name}"
        shutil.copy2(base_file, target)
        added.append(target.name)
    sources = [Path(file)] if file else sorted(paths.incoming.glob("*.csv"))
    for src in sources:
        target = paths.extracts / f"{_stamp()}__{src.name}"
        shutil.copy2(src, target)
        added.append(target.name)
        if not file:
            src.unlink()  # consumed from incoming; the archived copy is kept
    return added


def merge_extracts(extracts_dir: Path) -> tuple[pd.DataFrame, int, int]:
    """All extracts combined, newest version of each key kept. Returns (frame, n_files, n_replaced)."""
    files = sorted(extracts_dir.glob("*.csv"))
    if not files:
        return pd.DataFrame(), 0, 0
    frames = []
    for order, f in enumerate(files):  # file names start with a timestamp, so sorted = oldest first
        df = load_raw(f)
        df["_extract_order"] = order
        frames.append(df)
    allrows = pd.concat(frames, ignore_index=True)
    allrows = allrows.sort_values(["LAST_UPDATE_DATETIME", "_extract_order"], na_position="first")
    merged = allrows.drop_duplicates(KEY_COLUMNS, keep="last")
    replaced = len(allrows) - len(merged)
    merged = merged.drop(columns="_extract_order").sort_values(KEY_COLUMNS).reset_index(drop=True)
    return merged, len(files), replaced


def _published_data_end(processed: Path) -> str | None:
    m = processed / "manifest.json"
    return json.loads(m.read_text())["data_end"] if m.exists() else None


def _log(paths: Paths, result: RunResult) -> None:
    paths.log.parent.mkdir(parents=True, exist_ok=True)
    with paths.log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(result)) + "\n")


def refresh(paths: Paths | None = None, file: Path | None = None, force: bool = False,
            base_file: Path | None = None, ltv: bool = True) -> RunResult:
    paths = paths or Paths.default()
    base_file = base_file if base_file is not None else get_settings().raw_data_path
    res = RunResult(status="", exit_code=0, started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    res.previous_data_end = _published_data_end(paths.processed)

    res.new_extracts = intake(paths, file, base_file)
    merged, res.extracts_used, res.rows_replaced_by_newer_version = merge_extracts(paths.extracts)
    if merged.empty:
        res.status, res.exit_code, res.message = "no_input", 3, "No extracts found"
        _log(paths, res)
        return res
    res.rows_merged = len(merged)
    newest = merged["DATE"].max()
    res.data_end = str(newest.date())

    if res.previous_data_end and newest <= pd.Timestamp(res.previous_data_end) and not force:
        res.status, res.exit_code = "no_new_data", 2
        res.message = f"Newest date {res.data_end} is not after the published {res.previous_data_end}; nothing published"
        _log(paths, res)
        return res

    if paths.staging.exists():
        shutil.rmtree(paths.staging)
    prepare.run(out_dir=paths.staging, raw=merged, source=f"{res.extracts_used} extract(s)")

    pday = pd.read_parquet(paths.staging / "player_day.parquet")
    checks = run_checks(pday, newest, merged)
    res.checked_date = res.data_end
    res.failed_checks = checks.loc[checks["status"] == FAIL, "check"].tolist()
    res.warnings = checks.loc[checks["status"] == WARN, "check"].tolist()
    if res.failed_checks:
        res.status, res.exit_code = "blocked", 1
        res.message = "Health gate failed; the dashboard keeps the previous tables. Staged build kept for inspection."
        _log(paths, res)
        return res

    paths.processed.mkdir(parents=True, exist_ok=True)
    for name in PUBLISHED:
        os.replace(paths.staging / name, paths.processed / name)
    shutil.rmtree(paths.staging, ignore_errors=True)
    res.status, res.exit_code = "published", 0
    res.message = f"Published data through {res.data_end}" + (f" with {len(res.warnings)} warning(s)" if res.warnings else "")
    res.ltv = score_ltv(paths, newest) if ltv else "skipped"
    res.lists = run_lists(paths, newest) if ltv and res.ltv.startswith("scored") else "skipped"
    res.alerts = send_alerts(paths, newest) if res.lists.startswith("ok") else "skipped"
    _log(paths, res)
    return res


def score_ltv(paths: Paths, date: pd.Timestamp) -> str:
    """Score LTV for the newly published date with the active model; a failure is logged, not fatal."""
    from sciplay.config import REPO_ROOT
    if not (REPO_ROOT / "models" / "ltv" / "active.json").exists():
        return "no trained LTV model: run python -m sciplay.ltv.train"
    try:
        from sciplay.ltv import score as S, train as T
        data = T.load_data(paths.processed)
        out = S.score(date, data, db_path=paths.log.parent / get_settings().store_db_path.name)
        return f"scored {len(out)} players for {pd.Timestamp(date).date()}"
    except Exception as exc:  # the dashboard data is already published; LTV can be rerun on its own
        return f"LTV scoring failed: {exc}"


def run_lists(paths: Paths, date: pd.Timestamp) -> str:
    """Daily lists for the newly published date; a failure is logged, not fatal."""
    try:
        from sciplay.lists import run as LR
        from sciplay.ltv import train as T
        res = LR.run(date, T.load_data(paths.processed), db_path=paths.log.parent / get_settings().store_db_path.name)
        return f"{res['status']}: {res['list_sizes']}"
    except Exception as exc:
        return f"lists failed: {exc}"


def send_alerts(paths: Paths, date: pd.Timestamp) -> str:
    """One delivery run right after new lists land (alerts held in quiet hours). Never fatal."""
    try:
        from datetime import datetime

        from sciplay.delivery import run as DR
        db = paths.log.parent / get_settings().store_db_path.name
        r = DR.run_hour(datetime.now(), replay=False, db=db, lists_db=db)   # the hourly job does the rest
        return f"sent {len(r['sent'])}, failed {len(r['failed'])}"
    except Exception as exc:
        return f"alerts failed: {exc}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Merge new extracts, rebuild, check and publish.")
    ap.add_argument("--file", type=Path, help="A new extract to take in (default: everything in data/raw/incoming/)")
    ap.add_argument("--force", action="store_true", help="Rebuild and publish even without a newer date")
    args = ap.parse_args(argv)
    res = refresh(file=args.file, force=args.force)
    print(json.dumps(asdict(res), indent=2))
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
