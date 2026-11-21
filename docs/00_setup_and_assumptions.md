# 00 · Setup and assumptions

## Setup

### Requirements

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 itself). Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- The sample CSV from SciPlay (not committed)

### Install

```bash
uv sync                       # creates .venv from uv.lock (Python 3.12)
cp .env.example .env          # Windows: copy .env.example .env
```

Put the data file at `data/raw/sample_data.csv` (the path is set by `RAW_DATA_PATH` in `.env`).

In VS Code, select the kernel `.venv\Scripts\python.exe` for notebooks.

### Run

| What | Command |
|---|---|
| Tests | `uv run pytest` |
| Daily refresh (new extracts → merge → rebuild → health gate → publish) | `uv run python -m sciplay.pipeline.refresh` |
| Rebuild prepared data from the single raw file | `uv run python -m sciplay.pipeline.prepare` |
| Dashboard | `uv run streamlit run app/Overview.py` |
| Rebuild the Part 1 notebook | `uv run python notebooks/build_01_data_audit.py` then `uv run jupyter nbconvert --to notebook --execute --inplace notebooks/01_data_audit.ipynb` |
| Rebuild the PowerPoint backup of the deck | `uv run python presentation/export_deck_data.py` then `node presentation/build_deck.js` (needs Node.js and `pptxgenjs`) |

The results deck itself is in Claude Slides; the PowerPoint is a backup.

### Repository layout

```
src/sciplay/
  config.py              paths from .env
  data/                  data layer
    loader.py            reads the CSV with light typing; no cleaning
    field_groups.py      column -> business field group
    registry.py          column registry: category, as-of availability, null meaning, use, evidence
    asof.py              as-of policy: player-day rollup, as-of snapshot, policy check
  audit/
    checks.py            grain, coverage, missingness, quality checks, inconsistent semantics
  metrics/
    kpis.py              dashboard KPI definitions, filters, breakdowns, cohort curves
    health.py            data health checks for one date against its history
    reconcile.py         dashboard totals vs independent SQL on the raw file
  pipeline/
    prepare.py           raw CSV -> prepared Parquet tables
    refresh.py           daily refresh: intake, merge, rebuild, health gate, publish, log
  app/
    ui.py                shared Streamlit helpers
  viz/
    charts.py            interactive Plotly charts (audit)
    dashboard_charts.py  dashboard charts
    formatting.py        the four value states
app/                     Streamlit pages (Overview + pages/)
tests/                   pytest: as-of policy, registry, smoke tests on the real file
notebooks/               Part 1 notebook and the script that builds it
docs/                    this file, data_understanding.md, column_registry.csv, concerns, AI use
presentation/            PowerPoint backup of the deck and its generator
data/                    raw / processed / store (gitignored)
```

## Assumptions

Approved on 2026-11-21. **Verified** = tested on the sample data. **Assumed** = not testable here; needs confirmation from SciPlay.

### Data meaning

| # | Assumption | Status | Evidence | Impact if wrong |
|---|---|---|---|---|
| A1 | One row = a day the player played; no row = did not play | Verified | 99.9% of rows have sessions; `DAYS_SINCE_LAST_LOGIN` equals the gap between rows on 99.8% | Engagement metrics and the as-of snapshot |
| A2 | An empty daily count means 0; an empty last-event field means "never happened" | Verified for `REVENUE`; assumed for other counts (approved) | `REVENUE` is empty exactly on days without a purchase | Biased averages and features |
| A3 | `D<n>_RETURNER` = played exactly n days after the row date | Verified | 99.9–100% match for n = 1…90 | Forward-looking columns used as features (leakage) |
| A4 | Lifetime fields are identical across a player's platforms on one day | Verified | All 7 multi-platform player-days | Revenue to date double counted |
| A5 | `apple_sign_in` is a login method, kept as a platform value | Assumed | 2 rows | Negligible |

### Revenue and time

| # | Assumption | Status | Evidence | Impact if wrong |
|---|---|---|---|---|
| A6 | Revenue is gross USD, before store fees and refunds; no ad revenue | Assumed (approved); components verified | `REVENUE` = coin packs + hot offers + out-of-coins offers on 100% of rows; net exists only for DTC ($19.34 of $20.80) | LTV unit and level |
| A7 | `LIFETIME_REVENUE` is a start-of-day value | Verified | Today's `REVENUE` matches the change into the next row 90% of the time, the same row 9%; `LT_SPENDER_BUCKET` confirms it | Revenue to date off by a day |
| A8 | Days are UTC; rows for day D land within about 2 days | Assumed | Median update lag of November rows is 2 days | As-of cut-off and freshness check |
| A9 | Provided rolling columns (`LAST_4W_*`, `LAST_8W_*`, …) end at D | Assumed; used as given, not rebuilt (decision) | Not documented | Small leakage risk |

### Sample and population

| # | Assumption | Status | Evidence | Impact if wrong |
|---|---|---|---|---|
| A10 | The sample is 100 random installs per month: rates carry to the population, totals do not | Count verified; randomness assumed | Exactly 100 players per install month | Biased pay rate and retention |
| A11 | Cohorts behave alike enough to pool into one curve | Supported | D1 activity 26–40%, D91–120 9–16% across cohorts | LTV extrapolation off for unusual cohorts |
| A12 | A player with no row for 30 days or more has churned | Assumed (approved: 30 days) | – | Wrong players included in or excluded from the lists |

### Dashboard (Part 2)

| # | Assumption | Status | Impact if wrong |
|---|---|---|---|
| B1 | Default score date = 31 Oct, the last fully representative day | Decided | – |
| B2 | Filters: platform, install month, payer status, country, acquisition type | Decided | – |
| B3 | A day with no rows is a real zero for counts and revenue; a ratio with a zero denominator is not applicable | Follows A1 | – |
| B4 | Tiles compare the score date with the average of the previous 7 days | Assumed | Different baseline, different arrows |
| B5 | Trend charts default to 7-day averages (daily values are noisy at ~30 players a day) | Assumed | – |
| B6 | Cohort revenue curves drop points based on fewer than 20 players (5 payers for the payer curve) | Assumed | Curves end earlier; avoids one big spender dominating |
| B7 | Payer status, country and acquisition type are taken from each day's row (56 players change source over time) | Assumed | A player can move between groups |
| B8 | Weeks start on Monday | Assumed | – |
| B10 | Each new extract may hold only new or changed rows; for a repeated key the latest `LAST_UPDATE_DATETIME` wins | Assumed | Restated rows ignored, or history lost |
| B11 | A failed health check on the newest date blocks publishing; warnings do not | Assumed | Bad data reaches the dashboard, or good data is held back |
| B9 | Data health compares the selected date with the 28 days before it; volume is unusual beyond ±3 standard deviations, missing values when more than 10 points worse | Assumed | More or fewer warnings |

LTV-specific assumptions (revenue decay after day 169, the forward window) are added with the LTV part.

## Open questions

Answer inline; answered questions move into the decision log.

| # | Question | Current default |
|---|---|---|
| – | None open | – |

## Decision log

| Date | Decision | Reason |
|---|---|---|
| 2026-11-20 | Raw CSV and brief are not committed | Company-provided material |
| 2026-11-20 | Parquet for prepared data, SQLite for list history | Local, reproducible; primary keys give idempotent reruns |
| 2026-11-20 | `pyproject.toml` + `uv.lock` are the only dependency files | One source of truth; `uv export` makes a requirements file on demand |
| 2026-11-21 | Multi-platform player-days: sum daily measures, take lifetime fields once; main platform + platform count | 7 cases; lifetime fields equal across platform rows |
| 2026-11-21 | Proposed split: train and test end 31 Oct, inference on 1–4 Nov | Shows train → test → daily scoring; November is unseen, like production |
| 2026-11-21 | Provided rolling / lifetime columns used as they are (or ignored), not rebuilt | Simplicity |
| 2026-11-21 | Revenue = gross USD; days = UTC | Not stated in the data |
| 2026-11-21 | Active on D = has a row with sessions on D; inactive players carried forward | Rows exist only on days played |
| 2026-11-21 | Definitions of revenue, revenue to date, LTV365, active player, payer, underperformance approved | See `data_understanding.md` |
| 2026-11-21 | Friction = technical problems only; cancelled purchases are a supporting reason | Cancels are mostly players browsing the store |
| 2026-11-21 | Value at risk = predicted LTV365 − revenue to date | Simple, in dollars |
| 2026-11-21 | Churn cut-off: 30 days without a row | Approved |
| 2026-11-21 | Claude Slides is the master deck; PowerPoint is a backup | Edited and presented in the browser |
| 2026-11-21 | Dashboard opens on 31 Oct | Last fully representative day |
| 2026-11-21 | Filters add country and acquisition type | Answer to Q2 |
| 2026-11-21 | Both revenue per active player and revenue per paying player shown | Answer to Q5 |
| 2026-11-21 | No HTML snapshot; a sample of the dashboard on 31 Oct goes into the deck instead | Simpler; the deck is what gets shared |
| 2026-11-21 | "Who needs attention" stays in the dashboard (brief, Part 2); filled from the Part 4 lists | Manager sees the lists; Part 5 pushes them |
| 2026-11-21 | Refresh command: intake → merge (latest version per key wins) → rebuild in staging → health gate → publish → log | Handles incremental files, restated rows, missing or bad data |
| 2026-11-21 | Sample banner and Overview tiles reconciled from data: banner computed from installs per month; score-date tiles checked with SQL | Brief: no hard-coded values; reconcile what the manager sees |
| 2026-11-21 | Production: refresh runs as a job in a data orchestration pipeline with cloud storage | Noted on the deck; out of scope locally |
