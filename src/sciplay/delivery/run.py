"""Dry-run delivery: decide what to send, render payloads, 'send' them to an outbox folder, keep an audit.

Three slots a day (studio local time):
  refresh  - after the daily lists are built (early morning): event alerts; held if inside quiet hours
  morning  - 08:00: held alerts go out, tickets opened/closed, morning email (what is open now)
  evening  - 18:00: escalations (medium/high, no action for 2+ days), evening email (handled today, still open)

Reliability: every message has an idempotency key; a key already 'sent' is never sent again (re-runs are safe).
Each send is tried up to RETRIES times with the same key; a message that still fails is recorded 'failed' and
reported to the data channel instead of being lost. In production the outbox writer is replaced by the
ticketing / Slack / email clients; nothing else changes.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from sciplay.config import get_settings
from sciplay.delivery import config as C
from sciplay.delivery import payloads as P
from sciplay.delivery import store as S
from sciplay.delivery import summary as SM
from sciplay.delivery import triggers as TR
from sciplay.lists import run as LR

SLOT_HOURS = {"refresh": 6, "morning": C.MORNING_HOUR, "evening": C.EVENING_HOUR}


def outbox_dir() -> Path:
    return Path(get_settings().store_db_path).parent / "outbox"


def in_quiet_hours(hour: int) -> bool:
    return hour >= C.QUIET_START or hour < C.QUIET_END


class Sender:
    """Writes each message to outbox/<date>/<channel>/<key>.json. `fail_first` simulates transient failures."""

    def __init__(self, date: str, fail_first: dict[str, int] | None = None, db=None):
        self.date, self.fail_first, self.db = date, dict(fail_first or {}), db
        self.sent, self.skipped, self.failed = [], [], []

    def _write(self, channel: str, key: str, payload: dict) -> Path:
        if self.fail_first.get(key, 0) > 0:
            self.fail_first[key] -= 1
            raise ConnectionError("simulated timeout")
        d = (Path(self.db).parent / "outbox" if self.db else outbox_dir()) / self.date / channel
        d.mkdir(parents=True, exist_ok=True)
        p = d / (re.sub(r"[^A-Za-z0-9_.-]+", "_", key) + ".json")
        p.write_text(json.dumps({k: v for k, v in payload.items() if not k.startswith("_")}, indent=2, default=str))
        return p

    def send(self, channel: str, key: str, kind: str, recipient: str, payload: dict) -> str:
        if S.delivered(key, self.db):
            self.skipped.append(key)
            return "duplicate_skipped"
        err, path = None, None
        for attempt in range(1, C.RETRIES + 1):
            try:
                path = self._write(channel, key, payload)
                break
            except Exception as e:  # noqa: BLE001  -- in production: backoff 1s, 4s, 16s
                err = str(e)
        status = "sent" if path else "failed"
        S.record_delivery({"delivery_key": key, "score_date": self.date, "channel": channel, "recipient": recipient,
                           "kind": kind, "status": status, "attempts": attempt, "last_error": err,
                           "outbox_path": str(path) if path else None,
                           "created_at": datetime.now(UTC).isoformat(timespec="seconds")}, self.db)
        (self.sent if path else self.failed).append(key)
        return status

    def mark_members(self, keys: list[str], kind: str) -> None:
        """Per-player event keys covered by a grouped message: recorded as sent so a re-run never repeats them."""
        for k in keys:
            if not S.delivered(k, self.db):
                S.record_delivery({"delivery_key": k, "score_date": self.date, "channel": "slack", "recipient": "group",
                                   "kind": "member", "status": "sent", "attempts": 0, "last_error": None,
                                   "outbox_path": None,
                                   "created_at": datetime.now(UTC).isoformat(timespec="seconds")}, self.db)

    def hold(self, key: str, kind: str, payload: dict, status: str = "held") -> None:
        if S.delivered(key, self.db):
            return
        S.record_delivery({"delivery_key": key, "score_date": self.date, "channel": "slack", "recipient": payload["channel"],
                           "kind": kind, "status": status, "attempts": 0,
                           "last_error": "quiet hours" if status == "held" else "daily alert limit reached",
                           "outbox_path": json.dumps(payload),
                           "created_at": datetime.now(UTC).isoformat(timespec="seconds")}, self.db)


def _context(date: str, lists_db=None):
    history = LR.read(db_path=lists_db)
    runs = LR.read(db_path=lists_db, table=LR.RUNS)
    run_row = runs[runs["score_date"] == date].iloc[-1] if (runs["score_date"] == date).any() else None
    today = history[history["score_date"] == date]
    prev = sorted(d for d in history["score_date"].unique() if d < date)
    yday = history[history["score_date"] == prev[-1]] if prev else history.iloc[0:0]
    fresh = f"Data as of {date}" + (f" · {run_row['model_rules_version'].split('+')[-1]}" if run_row is not None else "")
    return history, run_row, today, yday, fresh


def deliver(date: str, slot: str, game_id: str = "test", hour: int | None = None, fail_first=None,
            db=None, lists_db=None, llm=None) -> dict:
    date = str(pd.Timestamp(date).date())
    hour = SLOT_HOURS[slot] if hour is None else hour
    history, run_row, today, yday, fresh = _context(date, lists_db)
    actions = S.read("actions", db)
    snd = Sender(date, fail_first, db)
    report = {"date": date, "slot": slot, "hour": hour}

    if run_row is None or run_row["status"] != "ok":      # no lists: tell the data channel, nothing to teams
        msg = run_row["message"] if run_row is not None else "no list run for this date"
        snd.send("slack", f"{date}|no_lists|{slot}", "no_lists", C.DATA_CHANNEL,
                 {"channel": C.DATA_CHANNEL, "text": f"No lists for {date}: {msg}. Team messages skipped."})
        return report | {"sent": snd.sent, "skipped": snd.skipped, "failed": snd.failed}

    if slot == "refresh":
        held = capped = 0
        fresh_events = [e for e in TR.events(date, history, run_row) if not S.delivered(e.key, db)]
        dl = S.read("deliveries", db)
        used = int(((dl["score_date"] == date) & dl["kind"].isin(TR.ORDER) & dl["status"].isin(["sent", "held"])
                    & (dl["recipient"] != C.DATA_CHANNEL)).sum())
        for ev in TR.group(fresh_events):
            payload = P.slack_event(ev, date, game_id, fresh) | {"_members": ev.members or [ev.key]}
            team = ev.kind != "data_incomplete"
            if team and used >= C.MAX_ALERTS_PER_DAY:          # rate limit: rolled into the next email instead
                snd.hold(ev.key, ev.kind, payload, status="capped")
                capped += 1
            elif team and in_quiet_hours(hour):
                snd.hold(ev.key, ev.kind, payload)
                held += 1
                used += 1
            else:
                if snd.send("slack", ev.key, ev.kind, payload["channel"], payload) == "sent":
                    snd.mark_members(payload["_members"], ev.kind)
                used += team
        report |= {"held": held, "capped": capped}

    elif slot == "morning":
        dl = S.read("deliveries", db)
        waiting = dl[dl["status"].isin(["held", "capped"]) & (dl["score_date"] == date)]
        held_events = []
        for _, h in waiting.iterrows():
            payload = json.loads(h["outbox_path"])
            if h["status"] == "held" and snd.send("slack", h["delivery_key"], h["kind"], h["recipient"], payload) == "sent":
                snd.mark_members(payload.get("_members", []), h["kind"])
            held_events.append(type("E", (), {"text": payload["blocks"][0]["text"]["text"].split("\n")[0].strip("*")
                                              + (" (daily alert limit: email only)" if h["status"] == "capped" else "")}))
        opened = closed = 0
        for _, r in today[today["list_type"].isin(C.TICKET_QUEUES)].iterrows():
            t = P.ticket(r.to_dict(), game_id)
            if S.open_ticket({"ticket_id": t["ticket_id"], "game_id": game_id, "list_type": r["list_type"],
                              "player_id": int(r["player_id"]), "queue": t["queue"], "opened_date": date,
                              "status": "open", "closed_date": None, "close_reason": None, "priority": r["priority"],
                              "payload": json.dumps(t)}, db):
                snd.send("ticket", f"ticket|{t['ticket_id']}", "ticket_open", t["queue"], t)
                opened += 1
        tickets = S.read("tickets", db)
        on_list = set(zip(today["player_id"], today["list_type"]))
        for _, t in tickets[tickets["status"] == "open"].iterrows():
            if (t["player_id"], t["list_type"]) not in on_list:
                S.close_ticket(int(t["player_id"]), t["list_type"], date, "left the list", db)
                closed += 1
        overdue_n = len(TR.overdue(date, history, actions))
        f = SM.facts(date, game_id, today, yday, overdue_n,
                     "incomplete" if int(run_row["data_incomplete"] or 0) else "complete")
        s, source = SM.summarize(f, llm)
        mail = P.email_morning(date, game_id, today, yday, SM.to_markdown(s), fresh, held_events)
        mail["summary_source"] = source
        snd.send("email", f"{date}|email_morning|{game_id}", "email_morning", ", ".join(C.EMAIL_TO), mail)
        report |= {"tickets_opened": opened, "tickets_closed": closed, "summary_source": source}

    elif slot == "evening":
        od = TR.overdue(date, history, actions)
        for name, rows in (od.groupby("list_type") if len(od) else []):
            snd.send("slack", f"{date}|escalation|{name}", "escalation", C.OWNER_LEADS[name],
                     P.slack_escalation(rows, name, date, game_id))
        acted = actions[actions["score_date"] == date]
        for _, a in acted[acted["outcome"] == "resolved"].iterrows():
            S.close_ticket(int(a["player_id"]), a["list_type"], date, "resolved by owner", db)
        dl = S.read("deliveries", db)
        capped = [json.loads(x)["blocks"][0]["text"]["text"].split("\n")[0].strip("*")
                  for x in dl[(dl["status"] == "capped") & (dl["score_date"] == date)]["outbox_path"]]
        mail = P.email_evening(date, game_id, today, acted, od, fresh, capped)
        snd.send("email", f"{date}|email_evening|{game_id}", "email_evening", ", ".join(C.EMAIL_TO), mail)
        report["overdue"] = len(od)

    if snd.failed:                                        # never lose a message silently
        snd.send("slack", f"{date}|delivery_failed|{slot}", "delivery_failed", C.DATA_CHANNEL,
                 {"channel": C.DATA_CHANNEL, "text": f"{len(snd.failed)} messages failed after {C.RETRIES} attempts: "
                                                     + ", ".join(snd.failed)})
    return report | {"sent": snd.sent, "skipped": snd.skipped, "failed": snd.failed}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Dry-run delivery of the daily lists (writes to data/store/outbox)")
    ap.add_argument("--date", required=True)
    ap.add_argument("--slot", choices=["refresh", "morning", "evening", "day"], default="day",
                    help="'day' runs refresh, morning and evening in order")
    a = ap.parse_args()
    for sl in (["refresh", "morning", "evening"] if a.slot == "day" else [a.slot]):
        r = deliver(a.date, sl)
        print(sl, {k: (len(v) if isinstance(v, list) else v) for k, v in r.items()})
