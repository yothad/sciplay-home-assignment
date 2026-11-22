"""Message payloads: ticket (JSON), Slack (Block Kit JSON), email (markdown). Deep links open the dashboard filtered."""

from __future__ import annotations

from urllib.parse import urlencode

import pandas as pd

from sciplay.delivery import config as C
from sciplay.lists import config as L
from sciplay.lists.rules import order_players


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
        "needs_approval_before_any_cost": True,          # owner decides; above the studio limit, the team lead
        "link": deep_link(r["score_date"], player_id=int(r["player_id"])),
        "rules_version": r["model_rules_version"],
    }


def slack_event(ev, date: str, game_id: str, freshness: str) -> dict:
    lines = [f"*{ev.text}*"]
    for p in ev.players[: C.MAX_PLAYERS_PER_MESSAGE]:
        ltv = "" if pd.isna(p["predicted_ltv_365"]) else f"LTV ${p['predicted_ltv_365']:,.2f} · "
        lines.append(f"• Player {p['player_id']} · {p['priority']} · {ltv}gap ${p['opportunity_gap']:,.2f} · "
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
    for _, r in order_players(rows).head(C.MAX_PLAYERS_PER_MESSAGE).iterrows():   # money first
        ltv = "" if pd.isna(r["predicted_ltv_365"]) else f"LTV ${r['predicted_ltv_365']:,.2f} · "
        lines.append(f"• Player {r['player_id']} · {r['priority']} · {ltv}on the list since {r['on_list_since']} · "
                     f"{r['reason_text'].split(' | ')[0]}")
    if len(rows) > C.MAX_PLAYERS_PER_MESSAGE:
        lines.append(f"… and {len(rows) - C.MAX_PLAYERS_PER_MESSAGE} more in the dashboard")
    return {"channel": C.slack_channel(game_id),
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
                       {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Open list"},
                                                         "url": deep_link(date, list_type)}]}]}


def _counts_table(state: pd.DataFrame, yday: pd.DataFrame) -> str:
    rows = ["| List | Owner | Players | Still open | New | In progress | Handled | High | Value at risk |",
            "|---|---|---|---|---|---|---|---|---|"]
    for name in L.PRECEDENCE:
        t = state[state["list_type"] == name]
        n = t["state"].value_counts()
        rows.append(f"| {name} | {C.OWNERS[name]} | {len(t)} | {n.get('open', 0)} | {n.get('new', 0)} | "
                    f"{n.get('in_progress', 0)} | {n.get('handled', 0)} | {int((t['priority'] == 'high').sum())} | ${t['opportunity_gap'].sum():,.2f} |")
    return "\n".join(rows)


def _by_list(df: pd.DataFrame) -> str:
    return ", ".join(f"{n}: {int((df['list_type'] == n).sum())}" for n in L.PRECEDENCE)


def email_morning(sent_on: str, list_date: str, game_id: str, state: pd.DataFrame, yday: pd.DataFrame,
                  handled: pd.DataFrame, summary: str, freshness: str, held: list) -> dict:
    """08:00: what is left from yesterday + what is new overnight."""
    from sciplay.delivery.summary import REASON_LABELS
    open_, new = state[state["state"] == "open"], state[state["state"] == "new"]
    left = yday[~yday["player_id"].isin(state["player_id"])] if len(yday) else yday
    reasons = state["reason_codes"].str.split(";").explode().value_counts().head(5)
    oldest = open_.sort_values("days_on_list", ascending=False).head(1)
    body = [f"# {C.STUDIO_NAMES.get(game_id, game_id)} · morning · {sent_on}", "", summary, "",
            _counts_table(state, yday), "",
            f"**Still open from yesterday (no action yet):** {len(open_)} ({_by_list(open_)})"
            + (f"; longest open: {int(oldest['days_on_list'].iloc[0])} days." if len(oldest) else "."),
            f"**New overnight:** {len(new)} ({_by_list(new)}).",
            f"**Closed overnight:** {len(left)} left the lists on their own; {len(handled)} handled by owners since "
            "last evening.",
            "**Top reasons:** " + ", ".join(f"{REASON_LABELS.get(k, k)} ({v})" for k, v in reasons.items()), ""]
    if held:
        body += ["**Alerts held overnight (quiet hours) or over the daily alert limit:**"] + [f"- {e}" for e in held] + [""]
    body += [f"Open the lists: {deep_link(list_date)}", "",
             f"_{freshness}. Player IDs are in the tickets and the dashboard, not in this email._"]
    return {"to": C.EMAIL_TO, "subject": f"[{game_id}] Morning · {sent_on} · {len(open_)} still open, {len(new)} new, "
                                         f"${state['opportunity_gap'].sum():,.0f} at risk",
            "body_markdown": "\n".join(body)}


def email_evening(sent_on: str, list_date: str, game_id: str, state: pd.DataFrame, actions_today: pd.DataFrame,
                  closed_today: pd.DataFrame, overdue: pd.DataFrame, freshness: str, capped: list[str] | None = None) -> dict:
    """18:00: what was taken care of today and what is still open."""
    open_ = state[state["state"].isin(["open", "new"])]
    prog = state[state["state"] == "in_progress"]
    body = [f"# {C.STUDIO_NAMES.get(game_id, game_id)} · end of day · {sent_on}", "",
            f"**Taken care of today:** {len(actions_today)} actions, {len(closed_today)} tickets closed as handled."]
    for _, a in actions_today.iterrows():
        body.append(f"- {a['list_type']}: {a['owner']} · {a['action']} · outcome: {a['outcome']}")
    body += ["", f"**In progress (acted on, outcome pending):** {len(prog)} ({_by_list(prog)}).",
             f"**Still open (no action yet):** {len(open_)} ({_by_list(open_)})."]
    if len(overdue):
        body += [f"**Overdue, escalated to the leads (medium/high, no action by day {C.ESCALATE_AFTER_DAYS}):** "
                 f"{len(overdue)} ({_by_list(overdue)})."]
    if capped:
        body += ["", "**Alerts over the daily limit (not sent to Slack):**"] + [f"- {c}" for c in capped]
    body += ["", f"Open the lists: {deep_link(list_date)}", "", f"_{freshness}._"]
    return {"to": C.EMAIL_TO, "subject": f"[{game_id}] End of day · {sent_on} · {len(closed_today)} closed, "
                                         f"{len(prog)} in progress, {len(open_)} open, {len(overdue)} overdue",
            "body_markdown": "\n".join(body)}
