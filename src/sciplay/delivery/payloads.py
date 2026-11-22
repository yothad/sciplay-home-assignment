"""Message payloads: ticket (JSON), Slack (Block Kit JSON), email (markdown). Deep links open the dashboard filtered."""

from __future__ import annotations

from urllib.parse import urlencode

import pandas as pd

from sciplay.delivery import config as C
from sciplay.lists import config as L


def deep_link(date: str, list_type: str | None = None, player_id: int | None = None) -> str:
    if player_id is not None:
        return f"{C.DASHBOARD_URL}/Player_detail?{urlencode({'date': date, 'player': player_id})}"
    q = {"date": date} | ({"list": list_type} if list_type else {})
    return f"{C.DASHBOARD_URL}/Who_needs_attention?{urlencode(q)}"


def ticket(r: dict, game_id: str) -> dict:
    """One ticket per player stay on a list (opened once, updated after)."""
    return {
        "ticket_id": f"{game_id}-{r['list_type'][:3].upper()}-{r['player_id']}-{r['score_date']}",
        "queue": C.TICKET_QUEUES[r["list_type"]],
        "studio": C.STUDIO_NAMES.get(game_id, game_id),
        "title": f"{r['list_type']}: player {r['player_id']} ({r['priority']} priority)",
        "player_id": int(r["player_id"]),
        "priority": r["priority"],
        "reasons": r["reason_text"].split(" | "),
        "recommended_action": r["recommended_action"],
        "value": {"opportunity_gap": round(float(r["opportunity_gap"]), 2),
                  "predicted_ltv_365": None if pd.isna(r["predicted_ltv_365"]) else round(float(r["predicted_ltv_365"]), 2),
                  "ltv_to_date": round(float(r["ltv_to_date"]), 2)},
        "needs_approval_before_any_cost": True,
        "link": deep_link(r["score_date"], player_id=int(r["player_id"])),
        "rules_version": r["model_rules_version"],
    }


def slack_event(ev, date: str, game_id: str, freshness: str) -> dict:
    lines = [f"*{ev.text}*"]
    for p in ev.players[: C.MAX_PLAYERS_PER_MESSAGE]:
        lines.append(f"• Player {p['player_id']} · {p['priority']} · gap ${p['opportunity_gap']:,.2f} · "
                     f"{p['reason_text'].split(' | ')[0]}")
    return {
        "channel": C.DATA_CHANNEL if ev.kind == "data_incomplete" else C.slack_channel(game_id),
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"{freshness} · event `{ev.kind}`"}]},
            {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Open in dashboard"},
                                              "url": deep_link(date, ev.list_type or None)}]},
        ],
    }


def slack_escalation(rows: pd.DataFrame, list_type: str, date: str, game_id: str) -> dict:
    lines = [(f"*Escalation to {C.OWNER_LEADS[list_type]}: {len(rows)} medium/high-priority players on "
             f"{list_type} with no action for {C.ESCALATE_AFTER_DAYS}+ days*")]
    for _, r in rows.sort_values("opportunity_gap", ascending=False).head(C.MAX_PLAYERS_PER_MESSAGE).iterrows():
        lines.append(f"• Player {r['player_id']} · {r['priority']} · on the list since {r['on_list_since']} · "
                     f"{r['reason_text'].split(' | ')[0]}")
    if len(rows) > C.MAX_PLAYERS_PER_MESSAGE:
        lines.append(f"… and {len(rows) - C.MAX_PLAYERS_PER_MESSAGE} more in the dashboard")
    return {"channel": C.slack_channel(game_id),
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
                       {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Open list"},
                                                         "url": deep_link(date, list_type)}]}]}


def _counts_table(today: pd.DataFrame, yday: pd.DataFrame) -> str:
    rows = ["| List | Owner | Players | High | Medium | Low | Change vs yesterday | Value at risk |", "|---|---|---|---|---|---|---|---|"]
    for name in L.PRECEDENCE:
        t, y = today[today["list_type"] == name], yday[yday["list_type"] == name]
        pr = t["priority"].value_counts()
        rows.append(f"| {name} | {C.OWNERS[name]} | {len(t)} | {pr.get('high', 0)} | {pr.get('medium', 0)} | "
                    f"{pr.get('low', 0)} | {len(t) - len(y):+d} | ${t['opportunity_gap'].sum():,.2f} |")
    return "\n".join(rows)


def email_morning(date: str, game_id: str, today: pd.DataFrame, yday: pd.DataFrame, summary: str, freshness: str,
                  held: list) -> dict:
    new = today[~today["player_id"].isin(yday["player_id"])] if len(yday) else today
    reasons = today["reason_codes"].str.split(";").explode().value_counts().head(5)
    from sciplay.delivery.summary import REASON_LABELS
    body = [f"# {C.STUDIO_NAMES.get(game_id, game_id)} · players to act on today · {date}", "", summary, "",
            _counts_table(today, yday), "",
            f"**New since yesterday:** {len(new)} players. **Top reasons:** "
            + ", ".join(f"{REASON_LABELS.get(k, k)} ({v})" for k, v in reasons.items()), ""]
    if held:
        body += ["**Alerts held overnight (quiet hours) or over the daily alert limit:**"] + [f"- {e.text}" for e in held] + [""]
    body += [f"Open the lists: {deep_link(date)}", "", (f"_{freshness}. Player IDs are in the tickets and the dashboard, "
             "not in this email._")]
    return {"to": C.EMAIL_TO, "subject": f"[{game_id}] Players to act on today · {date} · "
                                         f"{len(today)} players, ${today['opportunity_gap'].sum():,.0f} at risk",
            "body_markdown": "\n".join(body)}


def email_evening(date: str, game_id: str, today: pd.DataFrame, actions_today: pd.DataFrame, overdue: pd.DataFrame,
                  freshness: str, capped: list[str] | None = None) -> dict:
    done = actions_today
    open_ = today[~today["player_id"].isin(done["player_id"])] if len(done) else today
    body = [f"# {C.STUDIO_NAMES.get(game_id, game_id)} · end of day · {date}", "",
            f"**Taken care of today:** {len(done)} players."]
    for _, a in done.iterrows():
        body.append(f"- {a['list_type']}: {a['owner']} · {a['action']} · outcome: {a['outcome']}")
    body += ["", (f"**Still open:** {len(open_)} players "
             f"({', '.join(f'{n}: {int((open_.list_type == n).sum())}' for n in L.PRECEDENCE)}).")]
    if len(overdue):
        body += ["", (f"**Overdue (medium/high, no action for {C.ESCALATE_AFTER_DAYS}+ days, escalated):** {len(overdue)} players "
                 f"({', '.join(f'{n}: {int((overdue.list_type == n).sum())}' for n in L.PRECEDENCE)}).")]
    if capped:
        body += ["", "**Alerts over the daily limit (not sent to Slack):**"] + [f"- {c}" for c in capped]
    body += ["", f"Open the lists: {deep_link(date)}", "", f"_{freshness}._"]
    return {"to": C.EMAIL_TO, "subject": f"[{game_id}] End of day · {date} · {len(done)} handled, {len(open_)} open, "
                                         f"{len(overdue)} overdue",
            "body_markdown": "\n".join(body)}
