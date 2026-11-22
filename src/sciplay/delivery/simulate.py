"""Hourly replay of 3 Nov 06:00 -> 5 Nov 18:00 with simulated owner feedback (is_demo = 1).

Lists for day D land at 06:00 on D+1 (go-live: the 2 Nov list, delivered 3 Nov). Feedback is inserted at the hour
it happens, as the ticket system / Slack buttons / dashboard form would deliver it in production.
Shows: quiet-hours hold, tickets opened once and closed when handled or when the player leaves the list, a re-run
that sends nothing, a retried email, escalation on the evening of day 2, morning and evening emails.
"""

from __future__ import annotations

import shutil
from datetime import datetime

import pandas as pd

from sciplay.delivery import run as DR
from sciplay.delivery import store as S
from sciplay.delivery import triggers as TR
from sciplay.lists import config as L
from sciplay.lists import run as LR
from sciplay.lists.rules import order_players

START, END = "2026-11-03 06:00", "2026-11-05 18:00"

# (hour, list, owner, action, outcome, which player: rank among untouched players by priority and value at risk)
DAILY_PLAN = [
    (10, L.FRICTION, "Player support team", "Checked crash logs, sent apology + bonus coins", "resolved"),
    (11, L.REVENUE, "VIP team", "Called the player; offer approved by the VIP lead", "pending"),
    (13, L.FRICTION, "Player support team", "Purchase failed at the store; refund confirmed", "resolved"),
    (14, L.ENGAGEMENT, "CRM team", "Added to the 'we miss you' push campaign", "pending"),
    (14, L.ENGAGEMENT, "CRM team", "Added to the 'we miss you' push campaign", "pending"),
    (14, L.ENGAGEMENT, "CRM team", "Added to the 'we miss you' push campaign", "pending"),
    (16, L.REVENUE, "VIP team", "Personal message sent; no reply", "no response"),
]
FOLLOW_UP = (12, L.REVENUE, "VIP team", "Follow-up: player bought the offer", "purchase made")  # day 2 onwards


def reset(db=None) -> None:
    with S.connect(db) as con:
        for t in S.SCHEMA:
            con.execute(f"DELETE FROM {t}")
    for d in pd.date_range(START[:10], END[:10]):
        shutil.rmtree(DR.outbox_dir() / d.strftime("%Y-%m-%d"), ignore_errors=True)


def feedback(at: datetime, db=None) -> list[dict]:
    """Owner actions happening at this hour, on the list delivered this morning."""
    runs = LR.read(table=LR.RUNS)
    L_date = DR.landed(at, runs, replay=True)
    if L_date is None:
        return []
    acts = S.read("actions", db)
    st = TR.status(L_date, LR.read(), acts)
    out = []
    plan = [p for p in DAILY_PLAN if p[0] == at.hour]
    if at.hour == FOLLOW_UP[0]:                               # follow up yesterday's pending VIP call
        last = acts.sort_values("acknowledged_at").groupby(["player_id", "list_type"]).tail(1) if len(acts) else acts
        prev = last[(last["list_type"] == L.REVENUE) & (last["outcome"] == "pending")
                    & (last["acknowledged_at"].str[:10] < at.strftime("%Y-%m-%d"))] if len(last) else last
        on = set(st.loc[st["list_type"] == L.REVENUE, "player_id"])
        for pid in [p for p in prev["player_id"] if p in on][:1]:
            out.append((FOLLOW_UP, pid))
    taken = set(acts["player_id"]) if len(acts) else set()
    for p in plan:
        cand = st[(st["list_type"] == p[1]) & st["state"].isin(["open", "new"]) & ~st["player_id"].isin(taken)]
        cand = order_players(cand)                            # owners work the list top-down
        if len(cand):
            pid = int(cand["player_id"].iloc[0])
            taken.add(pid)
            out.append((p, pid))
    rows = []
    for (hour, lst, owner, action, outcome), pid in out:
        row = {"score_date": L_date, "player_id": int(pid), "list_type": lst, "owner": owner,
               "acknowledged_at": at.isoformat(timespec="minutes"), "action": action, "outcome": outcome, "is_demo": 1}
        S.add_action(row, db)
        rows.append(row)
    return rows


def main(db=None):
    reset(db)
    log, acts = [], []
    fail = {"2026-11-04|email_morning|test": 2}               # the 4 Nov morning email times out twice
    for at in DR.hours(START, END):
        acts += feedback(at, db)
        r = DR.run_hour(at, db=db, fail_first=fail)
        if at == datetime(2026, 11, 4, 8):
            r2 = DR.run_hour(at, db=db)                       # same hour again: nothing new
            log.append(r)
            r = r2 | {"note": "re-run"}
        log.append(r)
    return log, acts


if __name__ == "__main__":
    log, acts = main()
    for r in log:
        if r.get("sent") or r.get("skipped") or r.get("new_list") or r.get("tickets_closed_handled") or r.get("note"):
            print({k: (len(v) if isinstance(v, list) else v) for k, v in r.items()})
    print("actions:", [(a["acknowledged_at"], a["list_type"][:10], a["player_id"], a["outcome"]) for a in acts])
    tk = S.read("tickets")
    print(tk.groupby(["status", "close_reason"], dropna=False).size())
