# Process log

Running record of what was done, when, and why. Newest entries at the bottom.

## 2026-11-20 – Kick-off

- Read the assignment brief. Timebox: ~2 working days (brief suggests 8–10 focused hours).
- Hiring manager is revenue-driven, so all outputs should be in dollars where possible: predicted LTV, value-to-date and **value at risk** (opportunity gap).
- Ran a first profiling pass on the CSV (findings in [01_data_audit.md](01_data_audit.md)).
- **Key early finding:** no mature 365-day label exists. `D365_SPEND` equals `LIFETIME_REVENUE` on every populated row, is null for non-payers, and the oldest install is 169 days. The LTV deliverable must be a clearly labeled proxy / extrapolation with a production target spec.
- Set up the repo: uv project (Python 3.12), `uv.lock`, `.env.example`, docs skeleton.

### Plan

| Day | Block | Output |
|---|---|---|
| 1 | Audit + data prep | Audit notebook, player-day table, as-of snapshot table, column registry |
| 1 | Target validation | Evidence that `D365_SPEND` is not a valid label |
| 1 | LTV | Cohort-curve baseline + two-part model on an observable horizon, time-based validation |
| 2 | Daily lists | `run(score_date)`, SQLite persistence, precedence rule, tests |
| 2 | Dashboard | Streamlit: overview, trends, segments, lists, player detail, data health |
| 2 | Delivery + docs | Stakeholder proposal, payload example, technical note, concerns log |

## Decisions

| Date | Decision | Reason |
|---|---|---|
| 2026-11-20 | Raw CSV is not committed to git | Company-provided sample data; README documents where to put it |
| 2026-11-20 | Parquet for prepared data, SQLite for list history | Local, reproducible, primary keys give idempotent reruns |
| 2026-11-20 | No requirements.txt; pyproject.toml + uv.lock are the only dependency files | Single source of truth; `uv export` can produce one on demand |
