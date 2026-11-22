"""Demo of two delivery days (3-4 Nov) with simulated owner actions (is_demo=1).

Shows: quiet-hours hold, tickets opened once, a transient Slack failure retried, a re-run skipped as duplicate,
owner actions closing tickets, escalation of medium/high players with no action for 2+ days.
"""

from __future__ import annotations

import shutil

from sciplay.delivery import run as DR
from sciplay.delivery import store as S
from sciplay.lists import config as L
from sciplay.lists import run as LR

DAYS = ["2026-11-03", "2026-11-04"]


def reset(db=None) -> None:
    with S.connect(db) as con:
        for t in S.SCHEMA:
            con.execute(f"DELETE FROM {t}")
    for d in DAYS:
        shutil.rmtree(DR.outbox_dir() / d, ignore_errors=True)


PLAN_DAY1 = [(L.FRICTION, 1, "Player support", "Checked crash logs, sent apology + bonus coins", "resolved"),
            (L.REVENUE, 1, "VIP host", "Called the player, offer approved by live-ops lead", "pending"),
            (L.ENGAGEMENT, 3, "Live-ops / CRM", "Added to the 'we miss you' push campaign", "pending")]
PLAN_DAY2 = [(L.FRICTION, 2, "Player support", "Reproduced the loading failure, ticket to the game team", "pending"),
             (L.REVENUE, 1, "VIP host", "Follow-up message after yesterday's call", "pending")]


def demo_actions(date: str, plan: list, db=None) -> list[dict]:
    """Owners act on the top players of a list (by value at risk); players already acted on today are skipped."""
    t = LR.read(date)
    done = set(S.read("actions", db).query("score_date == @date")["player_id"])
    out = []
    for name, n, owner, action, outcome in plan:
        cand = t[(t["list_type"] == name) & ~t["player_id"].isin(done)]
        for _, r in cand.sort_values(["opportunity_gap", "underperformance_score"], ascending=False).head(n).iterrows():
            row = {"score_date": date, "player_id": int(r["player_id"]), "list_type": name, "owner": owner,
                   "acknowledged_at": f"{date}T10:15:00", "action": action, "outcome": outcome, "is_demo": 1}
            S.add_action(row, db)
            out.append(row)
    return out


def main(db=None) -> list[dict]:
    reset(db)
    log = []
    d1, d2 = DAYS
    log.append(DR.deliver(d1, "refresh", db=db))                       # 06:00 -> held (quiet hours)
    log.append(DR.deliver(d1, "morning", db=db))                       # 08:00 -> held alerts, tickets, email
    log.append(DR.deliver(d1, "morning", db=db) | {"note": "re-run"})  # same slot again -> all duplicates
    acts = demo_actions(d1, PLAN_DAY1, db)
    log.append(DR.deliver(d1, "evening", db=db))
    log.append(DR.deliver(d2, "refresh", db=db))
    log.append(DR.deliver(d2, "morning", db=db,                        # email times out twice, 3rd attempt succeeds
                          fail_first={f"{d2}|email_morning|test": 2}))
    acts += demo_actions(d2, PLAN_DAY2, db)
    log.append(DR.deliver(d2, "evening", db=db))
    return log, acts



if __name__ == "__main__":
    log, acts = main()
    for r in log:
        print({k: (len(v) if isinstance(v, list) else v) for k, v in r.items()})
    print("actions:", [(a["list_type"], a["player_id"], a["outcome"]) for a in acts])
    dl = S.read("deliveries")
    print(dl.groupby(["score_date", "channel", "kind", "status"]).size())
    print(S.read("tickets")[["ticket_id", "status", "close_reason"]])
