# SciPlay – Player Analytics, LTV and Daily Action Lists

Home assignment for the **Data Science and AI Builder** role.
A local application that audits player data, estimates expected gross revenue through day 365 after install,
produces three mutually exclusive daily lists of underperforming players, and proposes how to push them to the people who act on them.

> Status: **work in progress**. Part 1 (data understanding) is done; Part 2 (dashboard) has a first version. Assumptions and decisions are in [`docs/00_setup_and_assumptions.md`](docs/00_setup_and_assumptions.md).

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
| Refresh data (new extracts → rebuild → health gate → publish) | `uv run python -m sciplay.pipeline.refresh` |
| Train / load LTV model | _TBD_ |
| Generate daily lists for a date | _TBD_ |
| Start dashboard | `uv run streamlit run app/Overview.py` |
| Run everything | _TBD_ |

Don't have uv? Install it with `pip install uv` (or see the uv docs). If you need a pip requirements file, generate one with `uv export --no-hashes -o requirements.txt`.

## Repository layout

```
├── src/sciplay/        # package: data/ (loader, registry, as-of), audit/, viz/
├── tests/              # pytest tests
├── notebooks/          # Part 1 notebook and its builder
├── presentation/       # PowerPoint backup of the results deck
├── data/               # raw / processed / store (gitignored)
├── docs/               # setup and assumptions, data understanding, registry
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
| [Setup and assumptions](docs/00_setup_and_assumptions.md) | How to install and run, repository layout, approved assumptions, decision log |
| [Data understanding](docs/data_understanding.md) | Part 1: grain, coverage, fields, registry, as-of policy, leakage audit, late data, quality issues, definitions |
| [Dashboard](docs/dashboard.md) | Part 2: pages, metrics, value states, data health checks, reconciliation |
| [Column registry](docs/column_registry.csv) | Every column with its category, as-of availability, null meaning, use and evidence |
| [Concerns log](docs/concerns_log.md) | Evidence, impact, mitigation, next validation step |
| [AI use disclosure](docs/ai_use_disclosure.md) | Tools used and how output was reviewed |
