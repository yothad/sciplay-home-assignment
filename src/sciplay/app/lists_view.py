"""Daily lists for the dashboard (Part 4)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from sciplay.config import get_settings
from sciplay.lists import history as H
from sciplay.lists import run as R


@st.cache_data(show_spinner=False)
def _read(db: str, mtime: float, score_date: str | None, table: str) -> pd.DataFrame:
    return R.read(score_date, Path(db), table=table)


def _db():
    return get_settings().store_db_path


def lists(score_date) -> pd.DataFrame:
    db = _db()
    if not db.exists():
        return pd.DataFrame(columns=R.COLUMNS)
    return _read(str(db), db.stat().st_mtime, pd.Timestamp(score_date).date().isoformat(), R.LISTS)


def history() -> pd.DataFrame:
    """Every stored date of the latest rules version (for list volume over time)."""
    db = _db()
    if not db.exists():
        return pd.DataFrame(columns=R.COLUMNS)
    return _read(str(db), db.stat().st_mtime, None, R.LISTS)


def run_log(score_date) -> pd.Series | None:
    db = _db()
    if not db.exists():
        return None
    t = _read(str(db), db.stat().st_mtime, pd.Timestamp(score_date).date().isoformat(), R.RUNS)
    return t.sort_values("created_at").iloc[-1] if len(t) else None


@st.cache_data(show_spinner=False)
def _changes(db: str, mtime: float, score_date: str) -> pd.DataFrame:
    return H.changes(score_date, Path(db))


def changes(score_date) -> pd.DataFrame:
    db = _db()
    if not db.exists():
        return pd.DataFrame(columns=["player_id", "change", "before", "after"])
    return _changes(str(db), db.stat().st_mtime, pd.Timestamp(score_date).date().isoformat())


@st.cache_data(show_spinner=False)
def _player_history(db: str, mtime: float, pid: int) -> pd.DataFrame:
    h = H.history(Path(db))
    return h[h["player_id"] == pid]


def player_history(pid: int) -> pd.DataFrame:
    db = _db()
    if not db.exists():
        return pd.DataFrame(columns=R.COLUMNS)
    return _player_history(str(db), db.stat().st_mtime, int(pid))


def not_run_note(score_date) -> str:
    return (f"No lists stored for {pd.Timestamp(score_date):%d %b}. Lists exist from 9 Oct (first day with LTV scores). "
            "Run `python -m sciplay.lists.run --date YYYY-MM-DD`.")

