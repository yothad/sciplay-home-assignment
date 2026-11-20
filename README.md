# SciPlay – Player Analytics, LTV and Daily Action Lists

Home assignment for the **Data Science and AI Builder** role.
A local application that audits player data, estimates expected gross revenue through day 365 after install,
produces three mutually exclusive daily lists of underperforming players, and proposes how to push them to the people who act on them.

> Status: **work in progress** – see [`docs/00_process_log.md`](docs/00_process_log.md) for the running log.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (it installs the right Python automatically). Dependencies live in `pyproject.toml`; exact versions are pinned in `uv.lock`.

```bash
# 1. install dependencies into .venv (Python 3.12, pinned by uv.lock)
uv sync

# 2. configure
cp .env.example .env          # Windows: copy .env.example .env

# 3. put the provided CSV here (not committed to git)
#    data/raw/sample_data.csv

# 4. run tests
uv run pytest
```

Pipeline and app commands will be added here as they are built:

| Step | Command |
|---|---|
| Prepare data | _TBD_ |
| Train / load LTV model | _TBD_ |
| Generate daily lists for a date | _TBD_ |
| Start dashboard | _TBD_ |
| Run everything | _TBD_ |

Don't have uv? Install it with `pip install uv` (or see the uv docs). If you need a pip requirements file, generate one with `uv export --no-hashes -o requirements.txt`.

## Repository layout

```
├── src/sciplay/        # package: data prep, features, ltv, lists, store, app
├── tests/              # pytest tests
├── notebooks/          # exploration / audit notebooks
├── data/
│   ├── raw/            # input CSV (gitignored)
│   ├── processed/      # prepared Parquet layers (gitignored)
│   └── store/          # SQLite list history (gitignored)
├── docs/               # process log, audit, methodology, concerns log
├── pyproject.toml      # project + dependencies (uv)
└── uv.lock             # exact pinned versions
```

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Data prep | pandas, DuckDB | SQL over Parquet; fast and readable |
| Storage | Parquet (prepared layers), SQLite (daily list history, run log) | Local, idempotent upserts via primary key |
| Modelling | scikit-learn, LightGBM, SciPy, SHAP | CPU-friendly, open source, explainable |
| App | Streamlit + Plotly | Quick local dashboard |
| Quality | pytest, ruff | Tests for the operational guarantees |

## Documentation

| Doc | Content |
|---|---|
| [Process log](docs/00_process_log.md) | Dated log of steps and decisions |
| [Data audit](docs/01_data_audit.md) | Grain, coverage, missingness, duplicates, quality issues |
| [Assumptions](docs/02_assumptions.md) | Every material assumption and the evidence needed to confirm it |
| [Leakage audit](docs/03_leakage_audit.md) | Suspicious columns and keep/exclude decisions |
| [LTV methodology](docs/04_ltv_methodology.md) | Target validation, model, baseline, validation design |
| [Action lists](docs/05_action_lists.md) | List definitions, precedence, thresholds, output contract |
| [Stakeholder delivery](docs/06_stakeholder_delivery.md) | Push design, triggers, payload, controls |
| [Technical note](docs/technical_note.md) | 1–2 page summary for reviewers |
| [Concerns log](docs/concerns_log.md) | Evidence, impact, mitigation, next validation step |
| [AI use disclosure](docs/ai_use_disclosure.md) | Tools used and how output was reviewed |
