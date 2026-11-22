"""Delivery tables in SQLite: tickets (opened once), deliveries (audit, idempotent), actions (feedback loop)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from sciplay.config import get_settings
from sciplay.delivery.config import RESOLVED_COOLDOWN_DAYS

SCHEMA = {
    "tickets": """ticket_id TEXT PRIMARY KEY, game_id TEXT, list_type TEXT, player_id INTEGER, queue TEXT,
                  opened_date TEXT, status TEXT, closed_date TEXT, close_reason TEXT, priority TEXT, payload TEXT""",
    "deliveries": """delivery_key TEXT PRIMARY KEY, score_date TEXT, channel TEXT, recipient TEXT, kind TEXT,
                     status TEXT, attempts INTEGER, last_error TEXT, outbox_path TEXT, created_at TEXT""",
    "actions": """action_id INTEGER PRIMARY KEY AUTOINCREMENT, score_date TEXT, player_id INTEGER, list_type TEXT,
                  owner TEXT, acknowledged_at TEXT, action TEXT, outcome TEXT, is_demo INTEGER""",
}


def db_path(path: Path | None = None) -> Path:
    p = Path(path or get_settings().store_db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def connect(path: Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(db_path(path))
    con.execute("PRAGMA journal_mode=TRUNCATE")
    for name, cols in SCHEMA.items():
        con.execute(f"CREATE TABLE IF NOT EXISTS {name} ({cols})")
    return con


def read(table: str, path: Path | None = None) -> pd.DataFrame:
    with connect(path) as con:
        return pd.read_sql_query(f"SELECT * FROM {table}", con)


def delivered(key: str, path: Path | None = None) -> bool:
    with connect(path) as con:
        r = con.execute("SELECT status FROM deliveries WHERE delivery_key = ?", (key,)).fetchone()
    return bool(r) and r[0] == "sent"


def record_delivery(row: dict, path: Path | None = None) -> None:
    with connect(path) as con:
        cols = ", ".join(row)
        con.execute(f"INSERT OR REPLACE INTO deliveries ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))


def open_ticket(row: dict, path: Path | None = None) -> bool:
    """Open a ticket once per player stay on a list. Returns False if an open ticket already exists."""
    with connect(path) as con:
        exists = con.execute("SELECT 1 FROM tickets WHERE player_id = ? AND list_type = ? AND status = 'open'",
                             (row["player_id"], row["list_type"])).fetchone()
        cooldown = con.execute(
            "SELECT 1 FROM tickets WHERE player_id = ? AND list_type = ? AND close_reason = 'resolved by owner' "
            "AND julianday(?) - julianday(closed_date) < ?",
            (row["player_id"], row["list_type"], row["opened_date"], RESOLVED_COOLDOWN_DAYS)).fetchone()
        if cooldown:                                   # just resolved: signals still in the 7-day window
            return False
        if exists:
            con.execute("UPDATE tickets SET priority = ? WHERE player_id = ? AND list_type = ? AND status = 'open'",
                        (row["priority"], row["player_id"], row["list_type"]))
            return False
        cols = ", ".join(row)
        con.execute(f"INSERT INTO tickets ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
        return True


def close_ticket(player_id: int, list_type: str, date: str, reason: str, path: Path | None = None) -> None:
    with connect(path) as con:
        con.execute("UPDATE tickets SET status = 'closed', closed_date = ?, close_reason = ? "
                    "WHERE player_id = ? AND list_type = ? AND status = 'open'", (date, reason, player_id, list_type))


def add_action(row: dict, path: Path | None = None) -> None:
    with connect(path) as con:
        cols = ", ".join(row)
        con.execute(f"INSERT INTO actions ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
