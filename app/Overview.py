"""Overview: how did we do on the score date? Run: uv run streamlit run app/Overview.py"""

import pandas as pd
import streamlit as st

from sciplay.app import lists_view as lvl
from sciplay.app import ltv_view as lv
from sciplay.app import ui
from sciplay.data.asof import snapshot_as_of
from sciplay.metrics import kpis as K
from sciplay.viz import dashboard_charts as dc
from sciplay.viz.formatting import State

data = ui.setup("Overview")
f = ui.sidebar(data)
rows, daily = ui.filtered_daily(data, f)

st.subheader(f"{f.score_date:%A %d %b %Y}" + (" · filtered" if f.active else ""))
st.caption("Each arrow compares the day with the **average of the previous 7 days** "
           "(e.g. ↑ 53% = 53% above that average). Ratios compare with the ratio of the 7 days' totals.")
ov = K.overview(daily, f.score_date).set_index("key")


def show(keys):
    cols = st.columns(len(keys))
    for col, key in zip(cols, keys):
        r = ov.loc[key]
        num, den = K.RATIOS.get(key, (None, None))
        state = State.NA if den and daily.loc[f.score_date, den] == 0 else None
        ui.tile(col, r["label"], r["value"], r["unit"], r["change"], state=state, help=K.KPI_BY_KEY[key].meaning)


st.markdown("**Activity**")
show(["active_players", "new_players", "payers", "payer_rate"])
st.markdown("**Revenue**")
show(["revenue", "arpdau", "arppu"])

st.markdown("#### Player base on the score date")
snap = snapshot_as_of(rows, f.score_date) if len(rows) else pd.DataFrame(columns=["days_since_last_seen", "revenue_to_date"])
base = K.player_base(snap) if len(snap) else {"players_known": 0, "active_base": 0, "churned": 0,
                                              "ever_payers_in_base": 0, "revenue_to_date": 0.0}
c = st.columns(6)
ui.tile(c[0], "Players so far", base["players_known"], help="Installed and seen at least once by the score date")
ui.tile(c[1], "Seen in last 30 days", base["active_base"], help="Played at least once in the 30 days up to the score date: not churned (A12)")
ui.tile(c[2], "Churned", base["churned"], help="No day played in the last 30 days")
ui.tile(c[3], "Payers seen in 30 days", base["ever_payers_in_base"], help="Ever-payers among the players seen in the last 30 days")
ui.tile(c[4], "Revenue to date", base["revenue_to_date"], "money", help="Everything players known by the score date have paid")
_lists = lvl.lists(f.score_date)
if _lists.empty:
    ui.tile(c[5], "Value at risk", None, "money", state=State.NOT_YET, help="No daily lists stored for this date")
else:
    _lists = _lists[_lists["player_id"].isin(rows["PLAYER_ID"].unique())]
    ui.tile(c[5], "Value at risk", _lists["opportunity_gap"].sum(), "money",
            help=f"Opportunity gap of the {len(_lists)} players on today's lists (see Who needs attention)")

st.markdown("#### Lifetime value on the score date (Part 3)")
ltv = lv.scores(f.score_date)
if ltv.empty:
    st.info(lv.not_scored_note(f.score_date))
else:
    ltv = ltv[ltv["player_id"].isin(rows["PLAYER_ID"].unique())]
    by = ltv.groupby("source")
    model = ltv[ltv["source"] == "model_d3"]
    rule = ltv[ltv["source"] == "update_rule"]
    c = st.columns(5)
    ui.tile(c[0], "LTV365 · day-3 model", model["predicted_ltv_365"].sum(), "money",
            help="Players installed from 7 Oct, at least 3 days old: 30-day forecast × 2.49 (assumed fade, not validated)")
    ui.tile(c[1], "Players with a model forecast", len(model))
    ui.tile(c[2], "LTV365 · update rule", rule["predicted_ltv_365"].sum(), "money",
            help="NOT from the LTV model. Players installed before 7 Oct: revenue to date + last 30 days × "
                 "(0.6 + 0.6² + …) until day 365; nothing more if unseen for 30+ days")
    ui.tile(c[3], "Players on the update rule", len(rule))
    ui.tile(c[4], "Too new to forecast", int((ltv["source"] == "cold_start").sum()),
            help="Fewer than 3 days of data: no forecast yet (n/a)")
    st.caption("The two LTV totals come from different methods and are shown separately on purpose. "
               "Most of the money sits with older players on the update rule. See *Player detail* for how a "
               "player's value is calculated.")

st.markdown("#### Last 8 weeks")
recent = daily.loc[f.score_date - pd.Timedelta(days=55):]
smooth = K.rolling(daily).loc[recent.index]
c = st.columns(3)
for col, key in zip(c, ["active_players", "new_players", "revenue"]):
    col.plotly_chart(dc.kpi_trend(recent, smooth, key, "7-day average", f.score_date, height=280), width="stretch")

st.markdown("#### The score date, split by group")
units = {"active_players": "count", "new_players": "count", "payers": "count", "revenue": "money",
         "arpdau": "money", "arppu": "money", "payer_rate": "pct"}
tabs = st.tabs(list(K.DIMENSIONS))
for tab, (label, column) in zip(tabs, K.DIMENSIONS.items()):
    with tab:
        tbl = K.breakdown(rows, f.score_date, column).rename(columns={"group": label})
        if tbl.empty:
            st.info("No players played on this day with the current filters.")
            continue
        na = {"arpdau": tbl["active_players"].eq(0), "arppu": tbl["payers"].eq(0), "payer_rate": tbl["active_players"].eq(0)}
        st.markdown(ui.styled_table(tbl, units, not_applicable=na), unsafe_allow_html=True)
        st.caption("Revenue per paying player is *n/a* for groups with no paying players that day.")
