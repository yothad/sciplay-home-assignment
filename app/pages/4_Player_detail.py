"""Player detail: one player's history and as-of snapshot."""

import pandas as pd
import streamlit as st

from sciplay.app import lists_view as lvl
from sciplay.app import ltv_view as lv
from sciplay.app import ui
from sciplay.data.asof import snapshot_as_of
from sciplay.viz import dashboard_charts as dc
from sciplay.viz.formatting import State

data = ui.setup("Player detail")
f = ui.sidebar(data, with_filters=False)
rows = data.player_day[data.player_day["DATE"] <= f.score_date]
snap = snapshot_as_of(rows, f.score_date).sort_values("revenue_to_date", ascending=False)

if snap.empty:
    st.info("No players known on this date.")
    st.stop()
options = snap["PLAYER_ID"].tolist()
pid = st.selectbox("Player (sorted by revenue to date)", options,
                   format_func=lambda p: f"{p} · ${snap.set_index('PLAYER_ID').loc[p, 'revenue_to_date']:,.2f}")
s = snap.set_index("PLAYER_ID").loc[pid]
paid = s["revenue_to_date"] > 0

history_to_d = rows[rows["PLAYER_ID"] == pid]
purchase_days = history_to_d.loc[history_to_d["is_payer_day"], "DATE"]
# Days since last purchase as of the score date, not as of the player's last row.
last_purchase = (f.score_date - purchase_days.max()).days if len(purchase_days) else None

c = st.columns(6)
ui.tile(c[0], "Age (days)", s["age_days"])
ui.tile(c[1], "Days played", int(history_to_d["DATE"].nunique()))
ui.tile(c[2], "Days since last seen", s["days_since_last_seen"])
ui.tile(c[3], "Revenue to date", s["revenue_to_date"], "money")
ui.tile(c[4], "Days since last purchase", last_purchase, state=None if paid else State.NA,
        help="As of the score date; n/a for players who never paid")
ltv = lv.scores(f.score_date)
lrow = ltv.set_index("player_id").loc[pid] if pid in set(ltv["player_id"]) else None
if lrow is None:
    ui.tile(c[5], "Predicted LTV365", None, "money", state=State.NOT_YET, help="No LTV scores stored for this date")
elif lrow["source"] == "cold_start":
    ui.tile(c[5], "Predicted LTV365", None, "money", state=State.NOT_YET, help="Too new: first forecast on day 3")
else:
    ui.tile(c[5], "Predicted LTV365" if lrow["source"] == "model_d3" else "LTV365 (update rule)",
            lrow["predicted_ltv_365"], "money", help=lv.SOURCE_LABEL[lrow["source"]])

_today = lvl.lists(f.score_date)
_row = _today[_today["player_id"] == pid]
_list_note = (f"on the **{_row.iloc[0]['list_type']}** list ({_row.iloc[0]['priority']} priority)" if len(_row)
              else "not on a list today")
st.caption(f"Installed {s['install_date']:%d %b %Y} · main platform: {s['MAIN_PLATFORM_ID']} · "
           f"{'active on the score date' if s['active_on_score_date'] else 'not active on the score date'} · "
           + _list_note)
history = data.player_day[data.player_day["PLAYER_ID"] == pid].sort_values("DATE")
st.plotly_chart(dc.player_timeline(history[history["DATE"] <= f.score_date], f.score_date), width="stretch")

if lrow is not None:
    lv.player_panel(lrow)
else:
    st.info(lv.not_scored_note(f.score_date))

_hist = lvl.player_history(pid)
_hist = _hist[_hist["score_date"] <= f.score_date.date().isoformat()]
if len(_hist):
    st.markdown("#### List history")
    if len(_row):
        st.markdown(f"**Today:** {_row.iloc[0]['reason_text']}  \n**Recommended action:** {_row.iloc[0]['recommended_action']}")
    st.dataframe(_hist[["score_date", "list_type", "priority", "underperformance_score", "opportunity_gap"]]
                 .sort_values("score_date", ascending=False), hide_index=True, width="stretch")
