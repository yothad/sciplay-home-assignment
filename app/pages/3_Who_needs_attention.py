"""Who needs attention: the daily underperforming-player lists (Part 4)."""

import pandas as pd
import streamlit as st

from sciplay.app import lists_view as lv
from sciplay.app import ui
from sciplay.lists import config as L

data = ui.setup("Who needs attention")
f = ui.sidebar(data, with_filters=False)
st.caption("One primary list per player, by precedence: **Technical or payment friction → Revenue decline → Engagement "
           "decline**. Each player is compared with their own baseline, peers of the same age, or their LTV forecast. "
           "Thresholds are starting values (config).")

log = lv.run_log(f.score_date)
lists = lv.lists(f.score_date)
if log is None or log["status"] == "no_data":
    st.info(lv.not_run_note(f.score_date) if log is None else log["message"])
    st.stop()
if int(log["data_incomplete"]):
    st.warning(f"**Data incomplete for this date:** {log['message']}. The list is shown but may change when late rows land.")

c = st.columns(5)
for col, name in zip(c, L.PRECEDENCE):
    sub = lists[lists["list_type"] == name]
    ui.tile(col, name, len(sub), help=f"High priority: {int((sub['priority'] == 'high').sum())}")
ui.tile(c[3], "Value at risk", lists["opportunity_gap"].sum(), "money",
        help="Sum of opportunity gaps of listed players: expected value at their baseline − revised value now")
ui.tile(c[4], "Eligible players", int(log["eligible"]),
        help="Not a cheater or legal settlement, at least 3 days old, seen in the last 30 days")

order = {"high": 0, "medium": 1, "low": 2}
cols = ["player_id", "priority", "underperformance_score", "opportunity_gap", "predicted_ltv_365", "ltv_to_date",
        "reason_text", "recommended_action"]
tabs = st.tabs([f"{n} ({int((lists['list_type'] == n).sum())})" for n in L.PRECEDENCE] + ["Changes since previous day"])
for tab, name in zip(tabs, L.PRECEDENCE):
    with tab:
        sub = lists[lists["list_type"] == name].copy()
        if sub.empty:
            st.info("Nobody on this list today.")
            continue
        sub = sub.sort_values(["priority", "opportunity_gap", "underperformance_score"],
                              key=lambda s: s.map(order) if s.name == "priority" else -s)
        st.dataframe(sub[cols], hide_index=True, width="stretch", column_config={
            "player_id": "Player", "priority": "Priority",
            "underperformance_score": st.column_config.NumberColumn("Score (0–100)", format="%d"),
            "opportunity_gap": st.column_config.NumberColumn("Opportunity gap", format="$%.2f"),
            "predicted_ltv_365": st.column_config.NumberColumn("LTV365", format="$%.2f"),
            "ltv_to_date": st.column_config.NumberColumn("Revenue to date", format="$%.2f"),
            "reason_text": "Reasons", "recommended_action": "Recommended action"})
with tabs[-1]:
    ch = lv.changes(f.score_date)
    if ch.empty:
        st.info("No changes, or no earlier run to compare with.")
    else:
        st.dataframe(ch, hide_index=True, width="stretch")

with st.expander("How the lists, scores and priorities work"):
    st.markdown(
        "- **Eligible:** not a cheater or legal settlement, at least 3 days old, seen in the last 30 days.\n"
        "- **Technical or payment friction:** in the last 7 days, more crashes, unhandled errors, failed purchases, "
        "support tickets or load failures (2+) than the player's own previous 28 days, or 2+ purchase attempts with "
        "none completed.\n"
        "- **Revenue decline** (payers, or non-payers in the top 10% of predicted LTV): spend in the last 28 days at "
        "least 50% below the 28 before; overdue (no purchase for more than 2× the usual gap); at least 50% and $5 behind "
        "the day-3 forecast; or a high-value non-payer playing less.\n"
        "- **Engagement decline:** days played or sessions in the last 7 days at most 50% of the pace before; players "
        "under 5 weeks old compared with peers of the same age; or away 7–21 days and more than twice their usual "
        "gap between days played.\n"
        "- **Score (0–100):** 0 = at baseline, 100 = play or spend stopped, or severe friction.\n"
        "- **Opportunity gap:** expected value at the player's baseline − revised value now, never below $0.\n"
        "- **Priority:** high if the gap is ≥ $20; medium if ≥ $2, money blocked by a purchase problem, or score ≥ 75; low otherwise.")
st.caption(f"Version `{log['model_rules_version']}` · produced {log['created_at']}")
