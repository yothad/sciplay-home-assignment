# AI use disclosure

| Tool | What it produced | How I reviewed and tested it |
|---|---|---|
| Claude (Anthropic) | Data profiling, the audit, registry and as-of modules, the Part 1 notebook builder, tests, documentation drafts and the results deck | Every decision was discussed and approved by me before it was recorded (grain rollup, split, definitions, friction scope, assumptions A1–A12, churn cut-off). Key numbers were re-checked against the data; the as-of policy and registry are covered by pytest tests; the notebook is rebuilt from code and runs without errors |
| Claude (Anthropic) | Part 2 dashboard (Streamlit pages, metrics, health checks, refresh command) | Page designs and every metric definition approved by me; totals reconciled with independent SQL; every page has a render test |
| Claude (Anthropic) | Part 3 LTV: features, leakage checks, selection, LightGBM and GLM models, bootstrap, scoring, notebook 02 | Plan reviewed point by point against the brief before building; I chose the 3-day window, the install-date split, no refit on test, the 2.49 multiplier as an explicit assumption and the removal of device features; results were reviewed before the winner was chosen; leakage checks and scoring helpers are unit-tested |

_Updated as the work progresses._
