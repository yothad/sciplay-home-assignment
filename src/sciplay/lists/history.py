"""List history: entry, exit, duration and priority changes between run dates."""

from __future__ import annotations

import pandas as pd

from sciplay.lists import run as R

PRIO = {"high": 3, "medium": 2, "low": 1}


def history(db_path=None, version: str | None = None) -> pd.DataFrame:
    h = R.read(None, db_path)
    if version:
        h = h[h["model_rules_version"] == version]
    return h.sort_values(["player_id", "score_date"])


def changes(score_date, db_path=None, version: str | None = None) -> pd.DataFrame:
    """What changed on this date compared with the previous run date: entered, exited, moved list, priority up/down."""
    h = history(db_path, version)
    dates = sorted(h["score_date"].unique())
    D = pd.Timestamp(score_date).date().isoformat()
    if D not in dates or dates.index(D) == 0:
        return pd.DataFrame(columns=["player_id", "change", "before", "after"])
    prev = h[h["score_date"] == dates[dates.index(D) - 1]].set_index("player_id")
    cur = h[h["score_date"] == D].set_index("player_id")
    rows = []
    for pid in cur.index.union(prev.index):
        a = prev.loc[pid] if pid in prev.index else None
        b = cur.loc[pid] if pid in cur.index else None
        if a is None:
            rows.append((pid, "entered", "", f"{b['list_type']} ({b['priority']})"))
        elif b is None:
            rows.append((pid, "exited", f"{a['list_type']} ({a['priority']})", ""))
        elif a["list_type"] != b["list_type"]:
            rows.append((pid, "moved list", f"{a['list_type']} ({a['priority']})", f"{b['list_type']} ({b['priority']})"))
        elif a["priority"] != b["priority"]:
            word = "priority up" if PRIO[b["priority"]] > PRIO[a["priority"]] else "priority down"
            rows.append((pid, word, a["priority"], b["priority"]))
    return pd.DataFrame(rows, columns=["player_id", "change", "before", "after"])


def spells(db_path=None, version: str | None = None) -> pd.DataFrame:
    """Each continuous stay on a list: player, list, first and last date, days, priorities seen."""
    h = history(db_path, version)
    if h.empty:
        return pd.DataFrame(columns=["player_id", "list_type", "entered", "last_seen_on_list", "days", "priorities"])
    dates = sorted(h["score_date"].unique())
    pos = {d: i for i, d in enumerate(dates)}
    h = h.assign(i=h["score_date"].map(pos))
    h["new_spell"] = (h.groupby("player_id")["i"].diff() != 1) | (h.groupby("player_id")["list_type"].shift() != h["list_type"])
    h["spell"] = h.groupby("player_id")["new_spell"].cumsum()
    g = h.groupby(["player_id", "spell"])
    return pd.DataFrame({"list_type": g["list_type"].first(), "entered": g["score_date"].min(),
                         "last_seen_on_list": g["score_date"].max(), "days": g.size(),
                         "priorities": g["priority"].agg(lambda s: " → ".join(dict.fromkeys(s)))}).reset_index().drop(columns="spell")
