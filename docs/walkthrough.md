# Walkthrough script (≈ 20 minutes)

Brief requirements: ~20 minutes presenting + ~25 minutes of questions; demo raw file → dashboard → LTV score → saved
daily lists → stakeholder message; architecture and data flow; target, feature timing, validation, model choice,
baseline; list definitions, conflicts and actions; main tests and one safely handled failure; what changes before
production and what evidence or decisions are still needed; bring the concerns log.

The brief asks for a demo from raw file to dashboard, LTV score, saved lists and a stakeholder message, plus
architecture, LTV design, list logic, tests, an edge case and what changes before production. Times are targets.

## Before the call

```bash
uv sync && cp .env.example .env            # data/raw/sample_data.csv in place
uv run pytest -q                            # all green (≈ 95 tests)
uv run python -m sciplay.pipeline.refresh --force
uv run python -m sciplay.ltv.score --from 2026-10-09 --to 2026-11-04
uv run python -m sciplay.lists.run --from 2026-10-09 --to 2026-11-04
uv run python -m sciplay.delivery.simulate  # hourly outbox, 3 Nov 06:00 – 5 Nov 18:00
uv run streamlit run app/Overview.py
```

Open: the deck, the dashboard, `data/store/outbox/2026-11-04/`, `docs/concerns_log.md`.

## Script

| # | Min | Show | Say |
|---|---|---|---|
| 1 | 0–1 | Deck: title, roadmap | Five parts, one pipeline: raw file → prepared data → LTV score → daily lists → messages |
| 2 | 1–3 | Deck: architecture slide; `src/sciplay/` folders | Modules: `data` (registry, as-of), `pipeline` (refresh with health gate), `ltv`, `lists`, `delivery`, `app`. Storage: Parquet layers, SQLite for scores, lists, runs, deliveries, actions. Refresh = intake → merge → rebuild in staging → gate → publish → score → lists → alerts; never publishes bad data |
| 3 | 3–5 | Deck: Part 1 grain, as-of, leakage audit | One row per player per day; forward-looking columns (`D<n>_RETURNER`, `I14/I30_REVENUE`) excluded by the registry, enforced in code and tests |
| 4 | 5–7 | Dashboard: Overview on 4 Nov, Data health | Score date drives every tile; health checks flag the 1–4 Nov spike; reconciled with SQL |
| 5 | 7–11 | Deck: target, horizon, split, features, selection, results | LTV365 proxy = validated 30-day forecast × 2.49 (stated assumption, range 2.00–3.29). Features from the first 3 days only. Split by install date, test once, no refit. LightGBM (Tweedie) vs GLM chosen on forward folds; benchmarks: revenue so far and a simple rule. Ranking is the real value: the $20+ band holds 91% of test revenue |
| 6 | 11–12 | Dashboard: Player detail for 33840 | Forecast, range, confidence, reasons in dollars, revenue to date $2,366.73 |
| 7 | 12–15 | Dashboard: Who needs attention on 4 Nov | Three lists, one per player by precedence (friction → revenue → engagement), eligibility, priority by dollar gap then severity, reasons and the action per list. Player 224283: on Engagement decline, left on 4 Nov after buying again (the "changes status" example) |
| 8 | 15–17 | Outbox: morning email 4 Nov, Slack alert, VIP ticket 33840, escalation 4 Nov; click a deep link | Hourly runs, owners per list, two emails a day (still open + new; handled), event triggers, tickets opened once, quiet hours, retries, idempotency keys, escalation after 2 days without action. Summary: template by default; prompt + pydantic validation shown on the slide, no API needed |
| 9 | 17–18 | Terminal: `pytest tests/test_lists.py tests/test_delivery.py -q` | Main tests: list exclusivity, boundaries, reasons, idempotent persistence; delivery dedupe, retry, grouping, escalation, LLM rejection → fallback |
| 10 | 18–19 | Edge case: `tests/test_refresh.py::test_health_gate_blocks_bad_data_and_keeps_yesterday`, or a data-incomplete day | Bad extract → gate blocks, yesterday's data stays, no scores, no lists, no team alerts; only `#data-alerts` hears about it |
| 11 | 19–20 | Deck: before production; concerns log | Owners/thresholds with each studio, real clients and secrets, orchestrator, SSO, holdout decision, labels at 90/365 days, sampling weights |

## Likely questions (short answers)

- **Why not 365-day labels?** Oldest player is 169 days old; none exist. 30-day labels are complete for installs to 6 Oct.
- **Why 3 days of features?** 7 days would leave the whole November cohort unscored; 3 days scores 132 players instead of 79.
- **Why does MAE barely beat revenue-so-far?** Few payers in test (6); the model's value is ranking and the dollar recall in the top band.
- **How do you stop alert fatigue?** Change-only events, thresholds with a minimum size, grouping, 5 alerts a day per channel, quiet hours, escalation only for medium/high.
- **What if the LLM invents a cause?** The validator rejects causal wording and numbers not in the facts; the template is used instead.
- **How do you know the lists help?** `actions` table (acknowledge, action, outcome) + suggested 10% holdout.
