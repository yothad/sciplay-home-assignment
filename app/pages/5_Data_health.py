"""Data health: is the data for the selected date complete and normal, compared with its history?"""

import pandas as pd
import streamlit as st

from sciplay.app import ui
from sciplay.metrics.health import FAIL, INFO, PASS, WARN, history_band, run_checks
from sciplay.metrics.reconcile import reconcile, reconcile_day
from sciplay.viz import dashboard_charts as dc

data = ui.setup("Data health")
f = ui.sidebar(data, with_filters=False)
# The exact raw rows the prepared tables were built from (saved by the prepare step).
raw_path = data.processed_dir / "raw_input.parquet"


@st.cache_data(show_spinner=False)
def raw_file(path: str, mtime: float):
    return pd.read_parquet(path)


raw = raw_file(str(raw_path), raw_path.stat().st_mtime) if raw_path.exists() else None
checks = run_checks(data.player_day, f.score_date, raw)

st.subheader(f"Checking {f.score_date:%A %d %b %Y} against the 28 days before it")
counts = checks["status"].value_counts()
c = st.columns(4)
ui.tile(c[0], "Passed", int(counts.get(PASS, 0)))
ui.tile(c[1], "Warnings", int(counts.get(WARN, 0)))
ui.tile(c[2], "Failed", int(counts.get(FAIL, 0)))
ui.tile(c[3], "For information", int(counts.get(INFO, 0)))

icon = {PASS: "✅ pass", WARN: "⚠️ warn", FAIL: "❌ fail", INFO: "ℹ️ info"}
order = {FAIL: 0, WARN: 1, INFO: 2, PASS: 3}
shown = checks.assign(result=checks["status"].map(icon), _o=checks["status"].map(order)).sort_values(["_o", "area"])
num = lambda v: "–" if pd.isna(v) else (f"{v:.1%}" if 0 < abs(v) < 1 and v != int(v) else f"{v:,.4g}")
shown["on the date"] = shown["on_date"].map(num)
shown["history (28 days)"] = shown["history"].map(num)
st.dataframe(shown[["result", "area", "check", "on the date", "history (28 days)", "detail"]], hide_index=True,
             width="stretch")
st.caption("– = no history comparison for this check. Shares of empty values are shown as percentages.")

st.plotly_chart(dc.health_band(history_band(data.player_day), f.score_date), width="stretch")

st.markdown("#### Reconciliation of dashboard totals")
st.caption("Dashboard numbers (pandas over the prepared tables) against the same numbers computed independently with "
           "SQL over the raw rows the build used: first the selected date's Overview tiles, then the whole period.")
if raw is None:
    st.warning("The build's raw input was not found: reconciliation is *not yet available*. Rerun the prepare step.")
else:
    rec = pd.concat([reconcile_day(data.daily, raw_path, f.score_date),
                     reconcile(data.daily.reset_index(), data.player_day, raw_path)], ignore_index=True)
    rec["result"] = rec["passed"].map({True: "✅ pass", False: "❌ fail"})
    st.dataframe(rec[["result", "check", "dashboard", "independent_sql", "difference"]], hide_index=True, width="stretch",
                 column_config={k: st.column_config.NumberColumn(format="%.2f")
                                for k in ("dashboard", "independent_sql", "difference")})

m = data.manifest
st.caption(f"Prepared from {m['source_file']}: {m['raw_rows']:,} raw rows → {m['player_day_rows']:,} player-days "
           f"(one row per player per day played; 7 player-days had two platform rows) · {m['players']} players · "
           f"built {m['built_at'][:16].replace('T', ' ')} UTC")
st.markdown("#### How values are shown")
ui.legend()
