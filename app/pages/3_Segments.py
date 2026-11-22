"""Segments: how do groups of players compare, and who ends up on the lists?"""

import plotly.graph_objects as go
import streamlit as st

from sciplay.app import lists_view as lvl
from sciplay.app import ltv_view as lv
from sciplay.app import ui
from sciplay.metrics import kpis as K
from sciplay.viz.charts import SERIES, _layout

data = ui.setup("Segments")
f = ui.sidebar(data)
rows, _ = ui.filtered_daily(data, f)
rows = rows[rows["DATE"] <= f.score_date]

st.caption("Players seen in the 30 days up to the score date, split by one group. Activity and revenue cover the last "
           "28 days; LTV365 and the lists are as of the score date. Small groups move a lot: read rates with the "
           "player count next to them.")
label = st.segmented_control("Compare by", list(K.SEGMENTS), default="Payer group")
column = K.SEGMENTS[label or "Payer group"]
lists, ltv = lvl.lists(f.score_date), lv.scores(f.score_date)
tbl = K.segments(rows, f.score_date, column, lists if len(lists) else None, ltv if len(ltv) else None)
if tbl.empty:
    st.info("No players in the base on this date with the current filters.")
    st.stop()

units = {"players": "count", "payer_share": "pct", "days_played_per_player": "count", "revenue_28d": "money",
         "revenue_per_player_28d": "money", "avg_ltv_365": "money", "on_a_list": "count", "value_at_risk": "money",
         "list_rate": "pct"}
names = {"group": label, "players": "Players", "payer_share": "Ever paid", "days_played_per_player": "Days played (28d)",
         "revenue_28d": "Revenue (28d)", "revenue_per_player_28d": "Revenue per player (28d)",
         "avg_ltv_365": "Avg LTV365", "on_a_list": "On a list today", "value_at_risk": "Value at risk",
         "list_rate": "List rate"}
show = tbl.rename(columns=names)
st.markdown(ui.styled_table(show, {names[k]: v for k, v in units.items() if k in tbl.columns}), unsafe_allow_html=True)

if "list_rate" in tbl.columns:
    c = st.columns(2)
    for col, key, title, fmt in [(c[0], "revenue_per_player_28d", "Revenue per player, last 28 days", "$,.2f"),
                                 (c[1], "list_rate", "Share of the group on a list today", ".0%")]:
        fig = go.Figure(go.Bar(x=tbl["group"].astype(str), y=tbl[key], marker_color=SERIES[0],
                               text=[f"n={n}" for n in tbl["players"]], textposition="outside"))
        fig.update_yaxes(tickformat=fmt, rangemode="tozero")
        col.plotly_chart(_layout(fig, title, height=320), width="stretch")
    st.caption("List rates differ by design: the revenue list needs a payer or a high-value player, and engagement "
               "signals need a baseline, so payers and players older than a month are listed more often.")
