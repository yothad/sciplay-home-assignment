"""Who needs attention: the daily lists (filled in Part 4)."""

import streamlit as st

from sciplay.app import ui
from sciplay.viz.formatting import State

data = ui.setup("Who needs attention")
f = ui.sidebar(data, with_filters=False)

st.info("The daily lists are built in Part 4 and ranked with the LTV model from Part 3. Until then their values are "
        "shown as *not yet available*, never as zero.")
c = st.columns(4)
ui.tile(c[0], "Friction", None, state=State.NOT_YET, help="Technical problems in the last 7 days")
ui.tile(c[1], "Revenue decline", None, state=State.NOT_YET, help="Payers spending at least 50% less than the 4 weeks before")
ui.tile(c[2], "Engagement decline", None, state=State.NOT_YET, help="Playing well below their own pace or their age group")
ui.tile(c[3], "Value at risk", None, "money", state=State.NOT_YET, help="Predicted LTV365 − revenue to date")
st.markdown(
    "**What this page will show:** each list's size and value at risk on the score date, the top players by value at "
    "risk with their reason codes, and who joined or left each list since the previous day."
)
