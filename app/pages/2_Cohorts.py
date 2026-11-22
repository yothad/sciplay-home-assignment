"""Cohorts: are newer players as good as older ones?"""

import streamlit as st

from sciplay.app import ui
from sciplay.audit.checks import AGE_LABELS, cohort_activity_matrix
from sciplay.metrics import kpis as K
from sciplay.viz import charts as pc
from sciplay.viz import dashboard_charts as dc

data = ui.setup("Cohorts")
f = ui.sidebar(data, with_filters=False)
rows = data.player_day[data.player_day["DATE"] <= f.score_date]

st.caption(f"As of {f.score_date:%d %b %Y}: only what had happened by then is counted. Cells based on fewer than "
           "10 players show n/a.")
activity = cohort_activity_matrix(rows, f.score_date, min_eligible=10)
st.plotly_chart(pc.cohort_activity_heatmap(activity, AGE_LABELS), width="stretch")

curves = K.cumulative_revenue_per_install(rows, f.score_date)
st.plotly_chart(dc.cumulative_revenue(curves), width="stretch")

st.markdown("#### Cohort summary")
players = rows.groupby("PLAYER_ID").agg(cohort=("install_cohort", "first"), install=("install_date", "first"),
                                         rtd=("revenue_to_date", "max"))
players["age"] = (f.score_date - players["install"]).dt.days
summary = players.groupby("cohort").agg(players=("rtd", "size"), payers=("rtd", lambda s: int((s > 0).sum())),
                                        min_age=("age", "min"))
summary["payer_share"] = summary["payers"] / summary["players"]
for age in (30, 90):
    c = curves[(curves["age_days"] == age) & (curves["install_cohort"] != "All cohorts")].set_index("install_cohort")
    summary[f"revenue_per_install_d{age}"] = c["revenue_per_install"].reindex(summary.index)
tbl = summary.reset_index()
not_yet = {f"revenue_per_install_d{a}": tbl[f"revenue_per_install_d{a}"].isna() for a in (30, 90)}
st.markdown(ui.styled_table(tbl, {"players": "count", "payers": "count", "min_age": "count", "payer_share": "pct",
                                  "revenue_per_install_d30": "money", "revenue_per_install_d90": "money"},
                            not_yet=not_yet), unsafe_allow_html=True)
st.caption("Revenue per install at day 30 / 90 is *not yet available* for cohorts with no player that old yet. "
           "min_age = age of the cohort's youngest player.")

st.markdown("#### Payers, from their first purchase")
st.caption("A second cohort view: players grouped by the month of their first purchase. Only 23 players ever paid, "
           "so the numbers are indicative.")
first = K.first_purchases(rows, f.score_date)
if first.empty:
    st.info("No purchases by this date.")
else:
    st.plotly_chart(dc.payer_curve(K.cumulative_revenue_per_payer(rows, f.score_date)), width="stretch")
    rtd = rows.groupby("PLAYER_ID")["revenue_to_date"].max()
    first["revenue_to_date"] = first["PLAYER_ID"].map(rtd)
    pc_tbl = (first.groupby("purchase_cohort")
              .agg(payers=("PLAYER_ID", "size"),
                   median_days_install_to_first_purchase=("days_install_to_first_purchase", "median"),
                   avg_first_purchase=("first_value", "mean"),
                   avg_revenue_to_date=("revenue_to_date", "mean"))
              .reset_index().rename(columns={"purchase_cohort": "first purchase month"}))
    st.markdown(ui.styled_table(pc_tbl, {"payers": "count", "median_days_install_to_first_purchase": "count",
                                         "avg_first_purchase": "money", "avg_revenue_to_date": "money"}),
                unsafe_allow_html=True)
