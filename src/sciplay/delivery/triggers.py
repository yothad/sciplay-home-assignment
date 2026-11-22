"""Event triggers and escalations, computed from the stored daily lists."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import pandas as pd

from sciplay.delivery import config as C
from sciplay.lists import config as L
from sciplay.lists.rules import order_players


@dataclass
class Event:
    key: str                 # idempotency key: one message per key, ever
    kind: str                # new_high_priority | list_increase | large_player_gap | large_total_gap | data_incomplete
    list_type: str
    text: str
    players: list[dict] = field(default_factory=list)
    members: list[str] = field(default_factory=list)   # per-player keys inside a grouped message


def _prev_dates(history: pd.DataFrame, date: str, n: int = 7) -> list[str]:
    dates = sorted(d for d in history["score_date"].unique() if d < date)
    return dates[-n:]


def events(date: str, history: pd.DataFrame, run_row: pd.Series | None) -> list[Event]:
    """All event triggers for the date. `history` = stored lists of the current version (all dates)."""
    out = []
    today = history[history["score_date"] == date]
    prev = _prev_dates(history, date)
    yday = history[history["score_date"] == prev[-1]].set_index("player_id") if prev else pd.DataFrame()
    if run_row is not None and int(run_row.get("data_incomplete", 0) or 0):
        out.append(Event(f"{date}|data_incomplete", "data_incomplete", "",
                         f"Data incomplete for {date}: {run_row['message']}. Team alerts are held until the rows land."))
        return out                                     # no team alerts on incomplete data
    for _, r in today.iterrows():
        before = yday.loc[r["player_id"]] if len(yday) and r["player_id"] in yday.index else None
        entered = before is None or before["list_type"] != r["list_type"]
        if r["priority"] == "high" and (entered or before["priority"] != "high"):
            out.append(Event(f"{date}|new_high|{r['list_type']}|{r['player_id']}", "new_high_priority", r["list_type"],
                             f"New high-priority player on {r['list_type']}", [r.to_dict()]))
        if entered and r["opportunity_gap"] >= C.PLAYER_GAP_ALERT:
            out.append(Event(f"{date}|large_gap|{r['list_type']}|{r['player_id']}", "large_player_gap", r["list_type"],
                             f"Large value at risk: ${r['opportunity_gap']:,.2f} for one player", [r.to_dict()]))
    if prev:
        past = history[history["score_date"].isin(prev)]
        for name in L.PRECEDENCE:
            avg = past[past["list_type"] == name].groupby("score_date").size().reindex(prev, fill_value=0).mean()
            now = int((today["list_type"] == name).sum())
            if now >= C.LIST_INCREASE_FACTOR * avg and now >= avg + C.LIST_INCREASE_MIN:
                out.append(Event(f"{date}|list_increase|{name}", "list_increase", name,
                                 f"{name}: {now} players today vs {avg:.1f} a day over the last {len(prev)} days"))
        avg_gap = past.groupby("score_date")["opportunity_gap"].sum().reindex(prev, fill_value=0).mean()
        total = float(today["opportunity_gap"].sum())
        if avg_gap > 0 and total >= C.TOTAL_GAP_FACTOR * avg_gap:
            out.append(Event(f"{date}|total_gap", "large_total_gap", "",
                             f"Value at risk ${total:,.2f} today vs ${avg_gap:,.2f} a day over the last {len(prev)} days"))
    return out


def stay_start(history: pd.DataFrame, date: str, player_id, list_type: str) -> str:
    """First list date of the player's current, unbroken stay on this list (counted from go-live)."""
    dates = sorted(d for d in history["score_date"].unique() if d <= date)
    on = set(history[(history["player_id"] == player_id) & (history["list_type"] == list_type)]["score_date"])
    start = date
    for d in reversed(dates):
        if d in on:
            start = d
        else:
            break
    return max(start, C.GO_LIVE)


def status(date: str, history: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    """Today's list with each player's state: new (first day), open (carried over, no action), in_progress
    (an owner acted, outcome pending) or handled (resolved, still showing in the 7-day signals)."""
    today = history[history["score_date"] == date].copy()
    rows = []
    for _, r in today.iterrows():
        start = stay_start(history, date, r["player_id"], r["list_type"])
        a = actions[(actions["player_id"] == r["player_id"]) & (actions["list_type"] == r["list_type"])
                    & (actions["score_date"] >= start)] if len(actions) else actions
        if len(a) and (a["outcome"] != "pending").any():
            st = "handled"
        elif len(a):
            st = "in_progress"
        else:
            st = "new" if start == date else "open"
        rows.append({**r.to_dict(), "on_list_since": start, "state": st,
                     "days_on_list": (pd.Timestamp(date) - pd.Timestamp(start)).days + 1})
    return pd.DataFrame(rows, columns=[*today.columns, "on_list_since", "state", "days_on_list"])


def overdue(date: str, history: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    """Medium/high-priority players on a list for 2+ days (counting today) with no action recorded in that stay."""
    today = history[history["score_date"] == date]
    rows = []
    for _, r in today[today["priority"].isin(C.ESCALATE_PRIORITIES)].iterrows():
        start = stay_start(history, date, r["player_id"], r["list_type"])   # the team can act only once told
        days = (pd.Timestamp(date) - pd.Timestamp(start)).days + 1   # days on the list, counting today
        acted = actions[(actions["player_id"] == r["player_id"]) & (actions["list_type"] == r["list_type"])
                        & (actions["score_date"] >= start) & (actions["score_date"] <= date)] if len(actions) else []
        if days >= C.ESCALATE_AFTER_DAYS and len(acted) == 0:
            rows.append({**r.to_dict(), "on_list_since": start, "days_without_action": days})
    return pd.DataFrame(rows)


ORDER = ["data_incomplete", "new_high_priority", "large_player_gap", "large_total_gap", "list_increase"]


def group(evs: list[Event]) -> list[Event]:
    """One message per (kind, list): player events of the same kind and list are sent together (alert fatigue).
    The group remembers its members' keys, so a player is alerted once even if the run is repeated."""
    out: dict[tuple, Event] = {}
    for e in evs:
        k = (e.kind, e.list_type)
        if k not in out:
            out[k] = Event(e.key, e.kind, e.list_type, e.text, list(e.players))
            out[k].members = [e.key]
        else:
            g = out[k]
            g.players += e.players
            g.members.append(e.key)
    for g in out.values():
        if len(g.members) > 1:
            g.key = f"{g.members[0].rsplit('|', 1)[0]}|group|{len(g.members)}|{hashlib.sha1('|'.join(sorted(g.members)).encode()).hexdigest()[:8]}"
            g.text = g.text.replace("New high-priority player", f"{len(g.members)} new high-priority players") \
                           .replace("Large value at risk", f"{len(g.members)} players with large value at risk")
            g.players = order_players(pd.DataFrame(g.players)).to_dict("records")
    return sorted(out.values(), key=lambda g: ORDER.index(g.kind))
