"""Daily lists flow: evaluate eligible players as of a date, assign one primary list each, persist.

Run:  python -m sciplay.lists.run --date 2026-11-04
      python -m sciplay.lists.run --from 2026-10-09 --to 2026-11-04
Call: from sciplay.lists.run import run; run("2026-11-04")

Edge cases
- Missing inputs (no prepared data or no trained LTV model): nothing is written; status "missing_input".
- No data for the date (after the data end): nothing is written; the run is logged as "no_data".
- No new data: rerunning a date gives the same rows (replaced, not duplicated); the refresh only builds lists for a
  newly published date.
- Late or incomplete data (the health check for that date fails): the list is written with data_incomplete = 1.
- No LTV scores for the date: they are computed and stored first.
- Ineligible players: not listed; counted by reason in `list_runs`.
- Reruns: (score_date, player_id, model_rules_version) is the key, so a rerun replaces rows. Players no longer on
  the list for that date and version are removed, so the stored list always equals the latest run.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd

from sciplay.config import get_settings
from sciplay.lists import config as L
from sciplay.lists import rules, signals
from sciplay.ltv import score as S
from sciplay.ltv import train as T
from sciplay.metrics.health import FAIL, run_checks

LISTS = "daily_lists"
RUNS = "list_runs"
COLUMNS = ["score_date", "player_id", "list_type", "priority", "underperformance_score", "predicted_ltv_365",
           "ltv_to_date", "opportunity_gap", "reason_codes", "reason_text", "recommended_action", "ltv_source",
           "data_incomplete", "model_rules_version", "created_at"]
RUN_COLUMNS = ["score_date", "model_rules_version", "status", "data_incomplete", "eligible", "listed",
               "list_sizes", "ineligible", "failed_checks", "message", "created_at"]


def rules_version(ltv_version: str, cfg=L) -> str:
    values = {k: getattr(cfg, k) for k in dir(cfg) if k.isupper()}
    h = hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()[:8]
    return f"{ltv_version}+rules-{h}"


def build(sig: pd.DataFrame, D, version: str, data_incomplete: bool, cfg=L) -> pd.DataFrame:
    """The daily output contract for the listed players."""
    lt = rules.primary_list(sig)
    score = rules.severity(sig, lt, cfg)
    prio = rules.priority(sig, lt, score, cfg)
    listed = sig.index[lt != ""]
    now = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
    rows = []
    for pid in listed:
        r = sig.loc[pid]
        rs = rules.reasons(r, cfg)
        codes = [c for c, _ in rs]
        rows.append({"score_date": pd.Timestamp(D).date().isoformat(), "player_id": int(pid), "list_type": lt[pid],
                     "priority": prio[pid], "underperformance_score": float(score[pid]),
                     "predicted_ltv_365": r["predicted_ltv_365"], "ltv_to_date": r["ltv_to_date"],
                     "opportunity_gap": round(float(r["opportunity_gap"]), 2), "reason_codes": ";".join(codes),
                     "reason_text": " | ".join(t for _, t in rs),
                     "recommended_action": rules.recommended_action(codes, lt[pid]), "ltv_source": r["source"],
                     "data_incomplete": int(data_incomplete), "model_rules_version": version, "created_at": now})
    out = pd.DataFrame(rows, columns=COLUMNS)
    if len(out):
        out = pd.concat([rules.order_players(out[out["list_type"] == n]) for n in L.PRECEDENCE])
    return out.reset_index(drop=True)


def _db(db_path: Path | None) -> Path:
    db = Path(db_path or get_settings().store_db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    return db


def _connect(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=TRUNCATE")
    cols = ", ".join(f'"{c}"' for c in COLUMNS)
    con.execute(f"CREATE TABLE IF NOT EXISTS {LISTS} ({cols}, PRIMARY KEY (score_date, player_id, model_rules_version))")
    rcols = ", ".join(f'"{c}"' for c in RUN_COLUMNS)
    con.execute(f"CREATE TABLE IF NOT EXISTS {RUNS} ({rcols}, PRIMARY KEY (score_date, model_rules_version))")
    return con


def write(lists: pd.DataFrame, run_row: dict, db_path: Path | None = None) -> None:
    with _connect(_db(db_path)) as con:
        con.execute(f"DELETE FROM {LISTS} WHERE score_date = ? AND model_rules_version = ?",
                    (run_row["score_date"], run_row["model_rules_version"]))
        if len(lists):
            cols = ", ".join(f'"{c}"' for c in COLUMNS)
            con.executemany(f"INSERT OR REPLACE INTO {LISTS} ({cols}) VALUES ({', '.join('?' * len(COLUMNS))})",
                            lists.astype(object).where(lists.notna(), None).itertuples(index=False, name=None))
        rcols = ", ".join(f'"{c}"' for c in RUN_COLUMNS)
        con.execute(f"INSERT OR REPLACE INTO {RUNS} ({rcols}) VALUES ({', '.join('?' * len(RUN_COLUMNS))})",
                    tuple(run_row[c] for c in RUN_COLUMNS))


def latest_version(db_path: Path | None = None) -> str | None:
    """The model + rules version of the most recent run (the one the dashboard and history show)."""
    runs = _read_table(RUNS, None, db_path)
    runs = runs[runs["model_rules_version"].astype(str) != ""]
    return None if runs.empty else runs.sort_values("created_at").iloc[-1]["model_rules_version"]


def _read_table(table: str, score_date, db_path) -> pd.DataFrame:
    db = Path(db_path or get_settings().store_db_path)
    cols = COLUMNS if table == LISTS else RUN_COLUMNS
    if not db.exists():
        return pd.DataFrame(columns=cols)
    with sqlite3.connect(db) as con:
        q = f"SELECT * FROM {table}" + (" WHERE score_date = ?" if score_date is not None else "")
        args = (pd.Timestamp(score_date).date().isoformat(),) if score_date is not None else ()
        try:
            return pd.read_sql_query(q, con, params=args)
        except Exception:
            return pd.DataFrame(columns=cols)


def read(score_date=None, db_path: Path | None = None, table: str = LISTS, version: str | None = "latest") -> pd.DataFrame:
    """Stored lists (or runs). By default only the latest model + rules version; pass version=None for all."""
    t = _read_table(table, score_date, db_path)
    if version == "latest":
        version = latest_version(db_path)
    if version is not None and len(t):
        t = t[t["model_rules_version"] == version]
    return t


def run(score_date, data: T.Data | None = None, store: bool = True, db_path: Path | None = None, cfg=L) -> dict:
    """Run the lists for one date. Returns the run record (status, sizes, ...) and the list frame."""
    D = pd.Timestamp(score_date).normalize()
    now = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
    try:                                   # missing inputs: no prepared data or no trained LTV model
        d = data or T.load_data()
        meta, _ = S.load_active()
    except (FileNotFoundError, OSError, KeyError) as exc:
        return {"score_date": D.date().isoformat(), "model_rules_version": "", "status": "missing_input",
                "message": f"Missing input, nothing listed: {exc}. Build the data (prepare / refresh) and train the "
                           "LTV model first.", "created_at": now, "eligible": 0, "listed": 0, "list_sizes": "{}",
                "ineligible": "{}", "failed_checks": "[]", "data_incomplete": 0, "lists": pd.DataFrame(columns=COLUMNS)}
    version = rules_version(meta["version"], cfg)
    base = {"score_date": D.date().isoformat(), "model_rules_version": version, "created_at": now,
            "eligible": 0, "listed": 0, "list_sizes": "{}", "ineligible": "{}", "failed_checks": "[]",
            "data_incomplete": 0, "message": ""}
    if D > d.data_end or (d.pday["DATE"] == D).sum() == 0:
        run_row = {**base, "status": "no_data", "message": f"No rows for {D.date()} (data ends {d.data_end.date()})"}
        if store:
            write(pd.DataFrame(columns=COLUMNS), run_row, db_path)
        return {**run_row, "lists": pd.DataFrame(columns=COLUMNS)}

    checks = run_checks(d.pday, D)
    failed = checks.loc[checks["status"] == FAIL, "check"].tolist()
    incomplete = bool(failed)

    ltv = S.read(D, db_path) if db_path else S.read(D)
    if ltv.empty or (ltv["model_version"] != meta["version"]).all():
        ltv = S.score(D, d, store=store, db_path=db_path)
    else:
        ltv = ltv[ltv["model_version"] == meta["version"]]

    sig = signals.compute(d.pday, d.installs, D, ltv, cfg)
    lists = build(sig, D, version, incomplete, cfg)
    run_row = {**base, "status": "ok_data_incomplete" if incomplete else "ok", "data_incomplete": int(incomplete),
               "eligible": int(sig["eligible"].sum()), "listed": len(lists),
               "list_sizes": json.dumps(lists["list_type"].value_counts().to_dict()),
               "ineligible": json.dumps(sig.loc[~sig["eligible"], "ineligible_reason"].value_counts().to_dict()),
               "failed_checks": json.dumps(failed),
               "message": ("Data incomplete: " + "; ".join(failed)) if incomplete else ""}
    if store:
        write(lists, run_row, db_path)
    return {**run_row, "lists": lists}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Daily underperforming-player lists")
    ap.add_argument("--date")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    a = ap.parse_args()
    data = T.load_data()
    dates = [a.date] if a.date else pd.date_range(a.start, a.end, freq="D")
    for dt in dates:
        res = run(dt, data)
        print(res["score_date"], res["status"], res["list_sizes"], res["message"])
