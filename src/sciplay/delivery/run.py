"""Dry-run delivery, run every hour: decide what to send, render it, 'send' it to an outbox folder, keep an audit.

Each hourly run (studio local time):
  1. New list landed? (the daily extract for day D arrives about 06:00 on D+1; lists are rebuilt only then)
     -> open tickets for players who entered a list, close tickets for players who left, find event alerts.
  2. Read feedback recorded since the last run (production: ticket updates, Slack buttons, a dashboard form) and
     close tickets an owner resolved.
  3. Send Slack messages not sent yet; inside quiet hours hold them until 08:00.
  4. 08:00 morning email (still open from yesterday + new overnight); 18:00 escalations and evening email.

Reliability: every message has an idempotency key; a key already 'sent' is never sent again, so hourly runs and
re-runs never duplicate. Each send is tried up to RETRIES times with the same key; a message that still fails is
recorded 'failed' and reported to the data channel. In production the outbox writer is replaced by the ticketing /
Slack / email clients; nothing else changes.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from sciplay.config import get_settings
from sciplay.delivery import config as C
from sciplay.delivery import payloads as P
from sciplay.delivery import store as S
from sciplay.delivery import summary as SM
from sciplay.delivery import triggers as TR
from sciplay.lists import run as LR


def outbox_dir() -> Path:
    return Path(get_settings().store_db_path).parent / "outbox"


def in_quiet_hours(hour: int) -> bool:
    return hour >= C.QUIET_START or hour < C.QUIET_END


class Sender:
    """Writes each message to outbox/<day sent>/<channel>/<key>.json. `fail_first` simulates transient failures."""

    def __init__(self, at: datetime, fail_first: dict[str, int] | None = None, db=None):
        self.at, self.fail_first, self.db = at, fail_first if fail_first is not None else {}, db
        self.day = at.strftime("%Y-%m-%d")
        self.sent, self.skipped, self.failed = [], [], []

    def _row(self, key, channel, recipient, kind, status, attempts, err, path, list_date):
        return {"delivery_key": key, "score_date": list_date, "channel": channel, "recipient": recipient, "kind": kind,
                "status": status, "attempts": attempts, "last_error": err, "outbox_path": path,
                "created_at": self.at.isoformat(timespec="minutes")}

    def _write(self, channel: str, key: str, payload: dict) -> Path:
        if self.fail_first.get(key, 0) > 0:
            self.fail_first[key] -= 1
            raise ConnectionError("simulated timeout")
        d = (Path(self.db).parent / "outbox" if self.db else outbox_dir()) / self.day / channel
        d.mkdir(parents=True, exist_ok=True)
        p = d / (re.sub(r"[^A-Za-z0-9_.-]+", "_", key) + ".json")
        p.write_text(json.dumps({k: v for k, v in payload.items() if not k.startswith("_")}, indent=2, default=str))
        return p

    def send(self, channel: str, key: str, kind: str, recipient: str, payload: dict, list_date: str = "") -> str:
        if S.delivered(key, self.db):
            self.skipped.append(key)
            return "duplicate_skipped"
        err, path = None, None
        for attempt in range(1, C.RETRIES + 1):
            try:
                path = self._write(channel, key, payload)
                break
            except Exception as e:  # noqa: BLE001 -- production: backoff 1s, 4s, 16s
                err = str(e)
        status = "sent" if path else "failed"
        S.record_delivery(self._row(key, channel, recipient, kind, status, attempt, err,
                                    str(path) if path else None, list_date), self.db)
        (self.sent if path else self.failed).append(key)
        return status

    def mark_members(self, keys: list[str], list_date: str) -> None:
        """Per-player event keys covered by a grouped message: recorded as sent so no later run repeats them."""
        for k in keys:
            if not S.delivered(k, self.db):
                S.record_delivery(self._row(k, "slack", "group", "member", "sent", 0, None, None, list_date), self.db)

    def hold(self, key: str, kind: str, payload: dict, list_date: str, status: str = "held") -> None:
        if S.delivered(key, self.db):
            return
        why = "quiet hours" if status == "held" else "daily alert limit reached"
        S.record_delivery(self._row(key, "slack", payload["channel"], kind, status, 0, why, json.dumps(payload),
                                    list_date), self.db)


def _headline(payload: dict) -> str:
    return payload["blocks"][0]["text"]["text"].split("\n")[0].strip("*")


def landed(at: datetime, runs: pd.DataFrame, replay: bool) -> str | None:
    """Latest list date available at `at`. Replay (past days): day D lands at DATA_LANDS_HOUR on D+1;
    live: whatever the refresh has written."""
    dates = sorted(runs["score_date"].unique())
    if replay:
        cutoff = (at - timedelta(hours=C.DATA_LANDS_HOUR) - timedelta(days=1)).strftime("%Y-%m-%d")
        dates = [d for d in dates if d <= cutoff]
    return dates[-1] if dates else None


def run_hour(at: datetime, game_id: str = "test", replay: bool = True, fail_first=None, db=None, lists_db=None,
             llm=None) -> dict:
    at = at.replace(minute=0, second=0, microsecond=0)
    day, hour = at.strftime("%Y-%m-%d"), at.hour
    history = LR.read(db_path=lists_db)
    runs = LR.read(db_path=lists_db, table=LR.RUNS)
    snd = Sender(at, fail_first, db)
    report = {"at": at.isoformat(timespec="minutes")}
    L_date = landed(at, runs, replay)
    if L_date is None:
        return report | {"sent": [], "skipped": [], "failed": []}
    run_row = runs[runs["score_date"] == L_date].iloc[-1]
    today = history[history["score_date"] == L_date]
    prev = sorted(d for d in history["score_date"].unique() if d < L_date)
    yday = history[history["score_date"] == prev[-1]] if prev else history.iloc[0:0]
    fresh = f"Data as of {L_date} · {run_row['model_rules_version'].split('+')[-1]}"
    report["list_date"] = L_date
    all_actions = S.read("actions", db)
    actions = all_actions[all_actions["acknowledged_at"] <= at.isoformat()] if len(all_actions) else all_actions

    # 1. a new list landed: tickets and event alerts (once per list date)
    if run_row["status"] != "ok":
        snd.send("slack", f"{L_date}|no_lists", "no_lists", C.DATA_CHANNEL,
                 {"channel": C.DATA_CHANNEL, "text": f"No lists for {L_date}: {run_row['message']}. Team messages skipped."},
                 L_date)
        return report | {"sent": snd.sent, "skipped": snd.skipped, "failed": snd.failed}
    if not S.delivered(f"{L_date}|landed", db):
        opened = closed = 0
        for _, r in today[today["list_type"].isin(C.TICKET_QUEUES)].iterrows():
            t = P.ticket(r.to_dict(), game_id)
            if S.open_ticket({"ticket_id": t["ticket_id"], "game_id": game_id, "list_type": r["list_type"],
                              "player_id": int(r["player_id"]), "queue": t["queue"], "opened_date": day,
                              "status": "open", "closed_date": None, "close_reason": None, "priority": r["priority"],
                              "payload": json.dumps(t)}, db):
                snd.send("ticket", f"ticket|{t['ticket_id']}", "ticket_open", t["queue"], t, L_date)
                opened += 1
        on_list = set(zip(today["player_id"], today["list_type"]))
        tickets = S.read("tickets", db)
        for _, t in tickets[tickets["status"] == "open"].iterrows():
            if (t["player_id"], t["list_type"]) not in on_list:
                S.close_ticket(int(t["player_id"]), t["list_type"], day, "left the list", db)
                closed += 1
        dl = S.read("deliveries", db)
        used = int((dl["created_at"].str[:10] == day).mul(dl["kind"].isin(TR.ORDER)).mul(
            dl["status"].isin(["sent", "held"])).mul(dl["recipient"] != C.DATA_CHANNEL).sum()) if len(dl) else 0
        for ev in TR.group([e for e in TR.events(L_date, history, run_row) if not S.delivered(e.key, db)]):
            payload = P.slack_event(ev, L_date, game_id, fresh) | {"_members": ev.members or [ev.key]}
            team = ev.kind != "data_incomplete"
            if team and used >= C.MAX_ALERTS_PER_DAY:                 # rate limit: into the next email instead
                snd.hold(ev.key, ev.kind, payload, L_date, status="capped")
            elif team and in_quiet_hours(hour):
                snd.hold(ev.key, ev.kind, payload, L_date)
                used += 1
            elif snd.send("slack", ev.key, ev.kind, payload["channel"], payload, L_date) == "sent":
                snd.mark_members(payload["_members"], L_date)
                used += team
        S.record_delivery(snd._row(f"{L_date}|landed", "internal", "", "list_landed", "sent", 1, None, None, L_date), db)
        report |= {"new_list": L_date, "tickets_opened": opened, "tickets_closed_left_list": closed}

    # 2. feedback: tickets an owner resolved since the last run
    resolved = 0
    for _, a in actions[actions["outcome"] != "pending"].iterrows() if len(actions) else []:
        tk = S.read("tickets", db)
        if ((tk["player_id"] == a["player_id"]) & (tk["list_type"] == a["list_type"]) & (tk["status"] == "open")
                & (tk["opened_date"] <= a["acknowledged_at"][:10])).any():
            S.close_ticket(int(a["player_id"]), a["list_type"], day, f"handled: {a['outcome']}", db)
            resolved += 1
    if resolved:
        report["tickets_closed_handled"] = resolved

    # 3. held alerts go out after quiet hours
    dl = S.read("deliveries", db)
    if not in_quiet_hours(hour) and len(dl):
        for _, h in dl[dl["status"] == "held"].iterrows():
            payload = json.loads(h["outbox_path"])
            if snd.send("slack", h["delivery_key"], h["kind"], h["recipient"], payload, h["score_date"]) == "sent":
                snd.mark_members(payload.get("_members", []), h["score_date"])

    state = TR.status(L_date, history, actions)
    # 4. emails and escalation
    if hour == C.MORNING_HOUR:
        dl = S.read("deliveries", db)
        overnight = dl[(dl["created_at"] >= (at - timedelta(hours=24 - C.EVENING_HOUR + C.MORNING_HOUR)).isoformat())
                       & dl["kind"].isin(TR.ORDER) & dl["status"].isin(["sent", "capped"]) & dl["outbox_path"].notna()]
        held = []
        for _, h in overnight.iterrows():
            src = h["outbox_path"]
            payload = json.loads(src) if h["status"] == "capped" else json.loads(Path(src).read_text())
            held.append(_headline(payload) + (" (daily alert limit: email only)" if h["status"] == "capped" else ""))
        since = (at - timedelta(hours=24 - C.EVENING_HOUR + C.MORNING_HOUR)).isoformat()
        handled = actions[actions["acknowledged_at"] > since] if len(actions) else actions
        overdue_n = len(TR.overdue(L_date, history, actions))
        f = SM.facts(L_date, game_id, today, yday, overdue_n,
                     "incomplete" if int(run_row["data_incomplete"] or 0) else "complete", state, len(handled))
        s, source = SM.summarize(f, llm)
        mail = P.email_morning(day, L_date, game_id, state, yday, handled, SM.to_markdown(s), fresh, held)
        mail["summary_source"] = source
        snd.send("email", f"{day}|email_morning|{game_id}", "email_morning", ", ".join(C.EMAIL_TO), mail, L_date)
        report["email"] = "morning"
    elif hour == C.EVENING_HOUR:
        od = TR.overdue(L_date, history, actions)
        for name, rows in (od.groupby("list_type") if len(od) else []):
            snd.send("slack", f"{day}|escalation|{name}", "escalation", C.OWNER_LEADS[name],
                     P.slack_escalation(rows, name, L_date, game_id), L_date)
        acted = actions[actions["acknowledged_at"].str[:10] == day] if len(actions) else actions
        tk = S.read("tickets", db)
        closed_today = tk[(tk["closed_date"] == day) & tk["close_reason"].fillna("").str.startswith("handled")]
        dl = S.read("deliveries", db)
        capped = [_headline(json.loads(x)) for x in
                  dl[(dl["status"] == "capped") & (dl["created_at"].str[:10] == day)]["outbox_path"]]
        mail = P.email_evening(day, L_date, game_id, state, acted, closed_today, od, fresh, capped)
        snd.send("email", f"{day}|email_evening|{game_id}", "email_evening", ", ".join(C.EMAIL_TO), mail, L_date)
        report |= {"email": "evening", "escalated": len(od)}

    if snd.failed:                                        # never lose a message silently
        snd.send("slack", f"{at.isoformat(timespec='minutes')}|delivery_failed", "delivery_failed", C.DATA_CHANNEL,
                 {"channel": C.DATA_CHANNEL, "text": f"{len(snd.failed)} messages failed after {C.RETRIES} attempts: "
                                                     + ", ".join(snd.failed)}, L_date)
    return report | {"sent": snd.sent, "skipped": snd.skipped, "failed": snd.failed}


def hours(start: str, end: str) -> list[datetime]:
    return list(pd.date_range(start, end, freq="h").to_pydatetime())


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Hourly dry-run delivery of the daily lists (writes to data/store/outbox)")
    ap.add_argument("--at", help="one hourly run, e.g. '2026-11-05 08:00' (default: now, live)")
    ap.add_argument("--from", dest="start", help="replay every hour from ... (with --to)")
    ap.add_argument("--to", dest="end")
    a = ap.parse_args()
    if a.start:
        times, replay = hours(a.start, a.end), True
    else:
        times, replay = [pd.Timestamp(a.at).to_pydatetime() if a.at else datetime.now()], bool(a.at)
    for t in times:
        r = run_hour(t, replay=replay)
        if r.get("sent") or r.get("new_list") or r.get("tickets_closed_handled"):
            print({k: (len(v) if isinstance(v, list) else v) for k, v in r.items()})
