"""Trends: is performance getting better or worse?"""

import streamlit as st

from sciplay.app import lists_view as lvl
from sciplay.app import ui
from sciplay.metrics import kpis as K
from sciplay.viz import dashboard_charts as dc

data = ui.setup("Trends")
f = ui.sidebar(data)
rows, daily = ui.filtered_daily(data, f)

view = st.segmented_control("View", ["7-day average", "Weekly"], default="7-day average")
keys = st.multiselect("Metrics", [k.key for k in K.KPIS], default=[k.key for k in K.KPIS],
                      format_func=lambda k: K.KPI_BY_KEY[k].label)
st.caption("Daily values are noisy at sample size (about 30 active players a day), so the default is a 7-day average.")

st.plotly_chart(dc.active_by_install_month(rows, f.score_date), width="stretch")

wk = K.weekly(daily)
cols = st.columns(2)
for i, key in enumerate(keys):
    fig = (dc.kpi_trend(daily, K.rolling(daily), key, "7-day average", f.score_date) if view != "Weekly"
           else dc.weekly_bars(wk, key))
    cols[i % 2].plotly_chart(fig, width="stretch")

st.markdown("#### Engagement and list volume")
c = st.columns(2)
c[0].plotly_chart(dc.engagement_trend(K.engagement_daily(rows), f.score_date), width="stretch")
hist = lvl.history()
hist = hist[hist["player_id"].isin(rows["PLAYER_ID"].unique())]
if hist.empty:
    c[1].info("No daily lists stored yet (they start on 9 Oct, the first day with LTV scores).")
else:
    c[1].plotly_chart(dc.list_volume(hist, f.score_date), width="stretch")

with st.expander("Weekly table"):
    tbl = wk.reset_index().rename(columns={"DATE": "week starting"})
    tbl["week starting"] = tbl["week starting"].dt.strftime("%d %b %Y")
    units = {k.key: k.unit for k in K.KPIS}
    na = {"arpdau": tbl["active_players"].eq(0), "payer_rate": tbl["active_players"].eq(0), "arppu": tbl["payers"].eq(0)}
    st.markdown(ui.styled_table(tbl[["week starting", "days_in_week"] + [k.key for k in K.KPIS]],
                                {**units, "days_in_week": "count"}, not_applicable=na), unsafe_allow_html=True)
