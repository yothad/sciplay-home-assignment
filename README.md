# SciPlay – player analytics, LTV and daily action lists

Home assignment for the **Data Science and AI Builder** role. A local application that:

1. audits the player data (Part 1),
2. shows current performance in a dashboard (Part 2),
3. estimates each player's gross revenue through day 365 after install (Part 3),
4. builds three daily lists of players who need attention (Part 4),
5. pushes those lists to the teams that act on them (Part 5, dry run).

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (`pip install uv`); it installs Python 3.12 and the pinned packages.

```bash
uv sync                                   # install (versions pinned in uv.lock)
cp .env.example .env                      # Windows: copy .env.example .env
#   put the provided CSV at data/raw/sample_data.csv (not in git)
uv run python -m sciplay.run_all --app    # prepare, load model, score, build lists, open the dashboard
```

The trained LTV model is in the repo (`models/`), so no training is needed. Checked on a fresh clone: `run_all` took
**about 1 minute** (prepare 3 s, load model 8 s, score 27 s, lists 26 s) and gives the same lists as the original run;
all 97 tests pass there. The dashboard opens on 4 Nov 2026.

| Option | What it adds |
|---|---|
| `--app` | Starts the dashboard at the end (otherwise prints the command) |
| `--deliver` | Replays hourly delivery for 3–5 Nov with simulated feedback; messages go to `data/store/outbox/` |
| `--retrain` | Trains the LTV model again instead of loading the shipped one (same result: fixed seed) |

Example delivery output is also committed in [`docs/examples/outbox/`](docs/examples/outbox/).

## Step by step

| Step | Command |
|---|---|
| Prepare data: new extracts → rebuild → health gate → publish | `uv run python -m sciplay.pipeline.refresh` |
| Train the LTV model (select on training folds, then fit and grade on test) | `uv run python -m sciplay.ltv.train select`, then `... train finalize` |
| Score LTV for a date or a range | `uv run python -m sciplay.ltv.score --from 2026-10-09 --to 2026-11-04` |
| Build the daily lists for a date or a range | `uv run python -m sciplay.lists.run --from 2026-10-09 --to 2026-11-04` |
| Deliver: one hourly run, or replay past hours | `uv run python -m sciplay.delivery.run` (`--from "2026-11-03 06:00" --to "2026-11-05 18:00"`) |
| Delivery demo with simulated feedback | `uv run python -m sciplay.delivery.simulate` |
| Dashboard | `uv run streamlit run app/Overview.py` |
| Tests | `uv run pytest` |

## Architecture

```
raw CSV ──> 1 prepare ──> 2 health gate ──> 3 LTV scores ──> 4 daily lists ──> 5 delivery (hourly)
            (Parquet)     (publish or         (SQLite          (SQLite           (tickets, Slack, email
                           keep yesterday)     ltv_scores)      daily_lists)      as files + audit tables)
                                      └──────────── dashboard reads only stored outputs ────────────┘
```

| Area | Code | Stores |
|---|---|---|
| Data preparation, as-of rules, column registry | `src/sciplay/data/`, `src/sciplay/pipeline/` | `data/processed/*.parquet` |
| Data health, metrics, reconciliation | `src/sciplay/metrics/`, `src/sciplay/audit/` | – |
| Features and model training | `src/sciplay/ltv/` (`features`, `select`, `train`, `learners`) | `models/ltv/` |
| LTV scoring | `src/sciplay/ltv/score.py` | `ltv_scores` (SQLite) |
| List generation | `src/sciplay/lists/` (`signals`, `rules`, `run`, `history`) | `daily_lists`, `list_runs` |
| Delivery | `src/sciplay/delivery/` | `tickets`, `deliveries`, `actions`, outbox files |
| User interface | `app/` (pages), `src/sciplay/app/`, `src/sciplay/viz/` | – |
| One command | `src/sciplay/run_all.py` | – |

Configuration is read from `.env` (see `.env.example`): data, store and model paths, and the dashboard URL used in
message links. No secrets or machine-specific paths in the code. Stack: Python 3.12, pandas, DuckDB (check),
LightGBM, SHAP, pydantic, Streamlit, Plotly; all open source and CPU-only.

## Tests (97)

| Area | Tests | What they guarantee |
|---|---|---|
| Data, as-of, registry | 15 | No look-ahead columns; null meanings |
| Refresh, health checks, dashboard | 18 | Health gate, reconciliation to the raw file, every page renders, deep links |
| LTV features and scoring | 15 | Features use only the first 3 days; reproducible training; the range holds the forecast |
| Daily lists | 18 | One list per player, threshold boundaries, reasons, idempotent writes, money-first order |
| Delivery | 19 | No duplicates, retries, quiet hours, grouping, daily cap, escalation, LLM fallback |
| Other | 12 | KPI definitions, value states, smoke tests |

## Key definitions and assumptions

- **Grain:** one row per player per day (platforms combined). **Revenue to date** = lifetime revenue before the day + the day's revenue.
- **LTV365:** a proxy. Revenue in days 0–29 is predicted from the first 3 days, then × 2.49 (an assumed monthly fade of 0.6; range × 2.00–3.29). Players installed before 7 Oct get an update rule instead.
- **Lists:** one per player, by precedence: Technical or payment friction → Revenue decline → Engagement decline. Priority by the dollar gap, then severity; sorted by priority, then LTV365, then score.
- **Delivery:** every hour; the list for day D lands at 06:00 on D+1; emails at 08:00 and 18:00.

All assumptions and decisions, with dates: [`docs/00_setup_and_assumptions.md`](docs/00_setup_and_assumptions.md).

## Known issues

- **No 365-day outcome yet:** the oldest player is 169 days old; LTV365 rests on the × 2.49 assumption.
- **Few payers:** 23 of 700 players, 6 in the test set; model results are directional.
- **Stratified sample:** 100 installs a month, so totals are sample totals; compare rates.
- **Simulated feedback:** owner actions in the delivery demo are simulated (`is_demo = 1`).
- **Thresholds are starting values,** checked on the list history; to be reviewed with the studios.

Full list with evidence and next steps: [`docs/concerns_log.md`](docs/concerns_log.md).

## Documentation

| Doc | Content |
|---|---|
| [Assumptions and decisions](docs/00_setup_and_assumptions.md) | Every assumption with evidence, and the dated decision log |
| [Data understanding](docs/data_understanding.md) | Part 1: grain, coverage, fields, as-of policy, leakage audit, quality issues, definitions |
| [Column registry](docs/column_registry.csv) | Every column: category, as-of availability, null meaning, use |
| [Dashboard](docs/dashboard.md) | Part 2: pages, metrics, value states, data health checks, refresh |
| [LTV](docs/ltv.md) | Part 3: target, split, features, model choice, validation, scoring |
| [Daily lists](docs/lists.md) | Part 4: rules, priority, reasons, persistence, backtest |
| [Stakeholder plan](docs/stakeholder_plan.md) | Part 5: recipients, triggers, payloads, reliability, security, feedback, AI summary |
| [Walkthrough](docs/walkthrough.md) | 20-minute script and likely questions |
| [Concerns log](docs/concerns_log.md) | Evidence, impact, mitigation, next validation step |
| [AI use disclosure](docs/ai_use_disclosure.md) | Tools used and how output was reviewed |
| [Presentations](presentation/README.md) | The walkthrough deck and the full results deck |

## Repository layout

```
├── app/                # Streamlit pages
├── src/sciplay/        # package (see Architecture)
├── tests/              # pytest
├── notebooks/          # 01 data audit, 02 LTV, 03 lists, and the scripts that build them
├── models/ltv/         # the shipped LTV model and its selection record
├── docs/               # documentation, column registry, example delivery output
├── presentation/       # where the decks are
├── data/               # raw / processed / store (not in git)
├── pyproject.toml      # project and dependencies
└── uv.lock             # pinned versions
```
