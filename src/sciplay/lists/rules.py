"""Primary list by precedence, severity score, priority, reason codes and recommended actions."""

from __future__ import annotations

import numpy as np
import pandas as pd

from sciplay.lists import config as L


def primary_list(sig: pd.DataFrame, precedence=L.PRECEDENCE) -> pd.Series:
    """Exactly one list per eligible, triggered player; empty string otherwise (first match wins)."""
    flags = {L.FRICTION: sig["any_friction"], L.REVENUE: sig["any_revenue"], L.ENGAGEMENT: sig["any_engagement"]}
    conds = [sig["eligible"] & flags[name] for name in precedence]
    return pd.Series(np.select(conds, precedence, ""), index=sig.index, name="list_type")


# ------------------------------------------------------------------ score (0-100)

def _pct(x) -> pd.Series:
    return (pd.Series(x, dtype=float).clip(0, 1) * 100).fillna(0)


def severity(sig: pd.DataFrame, list_type: pd.Series, cfg=L) -> pd.Series:
    """Underperformance score, 0-100, comparable across lists.

    0 = at the player's baseline; 100 = spend or play stopped completely, or severe friction.
    Friction: 25 points per friction event in the last 7 days (4+ events = 100).
    Revenue: the largest of spend drop %, overdue (100 at twice the overdue threshold), % behind forecast,
             and activity drop % for high-value non-payers.
    Engagement: the largest drop in days played or sessions vs the baseline (own pace, or peers if young).
    """
    friction = (sig["friction_events"] * 25).clip(0, 100)
    overdue = _pct((sig["days_since_purchase"] / (2 * cfg.OVERDUE_FACTOR * sig["usual_purchase_gap"])).where(sig["rev_overdue"]))
    behind = _pct((1 - sig["ltv_to_date"] / (sig["ltv_to_date"] + sig["behind_forecast_dollars"])).where(sig["rev_behind_forecast"]))
    spend = _pct(sig["spend_drop_share"].where(sig["rev_spend_drop"]))
    sess_drop = (1 - sig["sessions_7d"] / sig["baseline_sessions_per_week"]).where(sig["eng_sessions_drop"])
    away = _pct((sig["days_since_last_seen"] / (2 * cfg.RETURN_FACTOR * sig["usual_play_gap"])).where(sig["eng_overdue_return"]))
    activity = pd.concat([_pct(sig["activity_drop_share"].where(sig["eng_days_drop"] | sig["eng_young_vs_peers"])),
                          _pct(sess_drop), away], axis=1).max(axis=1)
    revenue = pd.concat([spend, overdue, behind, activity.where(sig["rev_valuable_losing_activity"], 0)], axis=1).max(axis=1)
    score = np.select([list_type == L.FRICTION, list_type == L.REVENUE, list_type == L.ENGAGEMENT],
                      [friction, revenue, activity], np.nan)
    return pd.Series(score, index=sig.index).round(0)


def priority(sig: pd.DataFrame, list_type: pd.Series, score: pd.Series, cfg=L) -> pd.Series:
    """Dollars first, severity second (decision b)."""
    gap = sig["opportunity_gap"].fillna(0)
    money_blocked = (list_type == L.FRICTION) & (
        (sig["recent_failed_purchases"] > 0) | sig["friction_triggers"].str.contains("incomplete purchase"))
    high = gap >= cfg.PRIORITY_HIGH
    medium = (gap >= cfg.PRIORITY_MEDIUM) | money_blocked | (score >= 75)
    p = np.select([high, medium], ["high", "medium"], "low")
    return pd.Series(np.where(list_type != "", p, ""), index=sig.index)


# ------------------------------------------------------------------ reasons and actions

def _money(v) -> str:
    return f"${v:,.2f}"


def _n(v) -> str:
    v = float(v)
    return f"{v:.0f}" if v == int(v) else f"{v:.1f}"


SINGULAR = {"crashes": "crash", "unhandled errors": "unhandled error", "failed purchases": "failed purchase",
            "support tickets": "support ticket", "sessions": "session", "cancelled purchases": "cancelled purchase",
            "load failures": "load failure"}


def _count(n, noun: str) -> str:
    return f"{_n(n)} {SINGULAR.get(noun, noun) if float(n) == 1 else noun}"


def reasons(r: pd.Series, cfg=L) -> list[tuple[str, str]]:
    """(code, readable text) for every signal the player triggers, in precedence order."""
    out = []
    if r["any_friction"]:
        for part in r["friction_triggers"].split("|"):
            label, n = part.split(":")
            if label == "incomplete purchase attempts":
                out.append(("friction_incomplete_purchase", f"{n} purchase attempts in the last {cfg.RECENT_DAYS} days, none completed"))
            else:
                out.append((f"friction_{label.replace(' ', '_')}", f"{_count(n, label)} in the last {cfg.RECENT_DAYS} days (more than usual)"))
    elif r["recent_cancellations"] > 0:
        out.append(("supporting_cancellations", f"{_count(r['recent_cancellations'], 'cancelled purchases')} in the last {cfg.RECENT_DAYS} days"))
    if r["any_revenue"]:
        if r["rev_spend_drop"]:
            out.append(("revenue_spend_drop", f"Spent {_money(r['spend_last_28d'])} in the last 28 days vs {_money(r['spend_prev_28d'])} "
                                              f"in the 28 before ({-r['spend_drop_share']:.0%})"))
        if r["rev_overdue"]:
            every = "day" if float(r["usual_purchase_gap"]) == 1 else f"{_n(r['usual_purchase_gap'])} days"
            out.append(("revenue_overdue", f"No purchase for {_n(r['days_since_purchase'])} days; usually every {every}"))
        if r["rev_behind_forecast"]:
            exp = r["ltv_to_date"] + r["behind_forecast_dollars"]
            out.append(("revenue_behind_forecast", f"Spent {_money(r['ltv_to_date'])} vs {_money(exp)} expected by now (day-3 forecast)"))
        if r["rev_valuable_losing_activity"]:
            out.append(("revenue_valuable_losing_activity", f"High predicted value ({_money(r['predicted_ltv_365'])} LTV365) "
                                                            "and playing less"))
    if r["any_engagement"]:
        if r["eng_days_drop"]:
            out.append(("engagement_days_drop", f"Played {_n(r['days_played_7d'])} of the last {cfg.RECENT_DAYS} days vs "
                                                f"{_n(r['baseline_days_per_week'])} a week before"))
        if r["eng_sessions_drop"]:
            out.append(("engagement_sessions_drop", f"{_count(r['sessions_7d'], 'sessions')} in the last {cfg.RECENT_DAYS} days vs "
                                                    f"{_n(r['baseline_sessions_per_week'])} a week before"))
        if r["eng_overdue_return"]:
            every = "day" if float(r["usual_play_gap"]) == 1 else f"{_n(r['usual_play_gap'])} days"
            out.append(("engagement_overdue_return", f"Not seen for {_n(r['days_since_last_seen'])} days; usually plays every {every}"))
        if r["eng_young_vs_peers"]:
            out.append(("engagement_young_vs_peers", f"Played {_n(r['days_played_7d'])} of the last {cfg.RECENT_DAYS} days; "
                                                     f"players of the same age typically {_n(r['peer_days_7d'])}"))
    return out


ACTIONS = {
    "friction_crashes": "Tech support: check crash logs for this player's device and app version; send an apology with bonus coins",
    "friction_unhandled_errors": "Tech support: check error logs for this player's device and app version; send an apology with bonus coins",
    "friction_failed_purchases": "Payments: check store and billing logs; contact the player to complete the purchase with a bonus",
    "friction_incomplete_purchase": "Payments: check store and billing logs for the abandoned purchases; offer help or a bonus to complete",
    "friction_support_tickets": "Support: follow up on the open ticket within a day",
    "friction_load_failures": "Tech support: check slot and lobby loading for this player's device, app version and network; send bonus coins",
    "revenue_spend_drop": "CRM / VIP: personalised offer based on the player's past purchases",
    "revenue_overdue": "CRM / VIP: timed offer on the player's usual purchase",
    "revenue_behind_forecast": "CRM: first-purchase offer while the player is still active",
    "revenue_valuable_losing_activity": "CRM: first-purchase offer plus free coins to bring the player back",
    "engagement_days_drop": "Lifecycle: re-engagement push or email with free coins",
    "engagement_sessions_drop": "Lifecycle: re-engagement push or email with free coins",
    "engagement_young_vs_peers": "Lifecycle: onboarding nudge (push with free coins and a feature tip)",
    "engagement_overdue_return": "Lifecycle: come-back message with a free-coins bonus timed to the player's usual play days",
}
LIST_PREFIX = {L.FRICTION: "friction", L.REVENUE: "revenue", L.ENGAGEMENT: "engagement"}


def recommended_action(codes: list[str], list_type: str) -> str:
    """The action for the first reason that belongs to the player's primary list."""
    prefix = LIST_PREFIX[list_type]
    main = next(c for c in codes if c.startswith(prefix))
    return ACTIONS[main]


PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def order_players(df: pd.DataFrame) -> pd.DataFrame:
    """Display and message order: money first. Priority (high to low), then predicted LTV365 (high to low,
    unscored last), then underperformance score (high to low)."""
    if df.empty:
        return df
    key = df.assign(_p=df["priority"].map(PRIORITY_RANK), _v=df["predicted_ltv_365"].astype(float).fillna(-1.0),
                    _s=df["underperformance_score"].astype(float))
    return df.loc[key.sort_values(["_p", "_v", "_s"], ascending=[True, False, False], kind="stable").index]
