# Part 4 · Daily underperforming player lists

Notebook: `notebooks/03_lists.ipynb`. Code: `src/sciplay/lists/`. Thresholds: `src/sciplay/lists/config.py` (**starting values, tunable**).

## Lists and precedence

One primary list per eligible player; every triggered signal is kept as a reason code. **Precedence: Technical or payment friction → Revenue decline → Engagement decline** (first match wins): friction is fixable and often causes the other two; revenue is where the money is; engagement is the broadest.

**Eligible:** not a cheater or legal settlement, at least 3 days old, seen in the last 30 days.

| List | Business meaning | Triggers | Baseline |
|---|---|---|---|
| **Technical or payment friction** | Blocked by technical or purchase problems | In the last 7 days: crashes, unhandled errors, failed purchases or store-verification failures, support tickets, or 2+ load failures (slot load, slot download or lobby load started but never completed) — more than the player's own previous 28 days; or 2+ purchase attempts with none completed. Single cancellations are a supporting reason only | Own previous 28 days |
| **Revenue decline** | A payer or valuable player giving less than expected | Payers: last-28-day spend ≤ 50% of the 28 before, or overdue (no purchase for > 2× the usual gap). Day-3 model players: ≥ 50% and ≥ $5 behind forecast. Non-payers in the top 10% of predicted LTV365: playing less | Own history; expected trajectory (LTV forecast) |
| **Engagement decline** | Losing activity, may churn before value arrives | Days played or sessions in the last 7 days ≤ 50% of the weekly pace in the 28 days before (baseline ≥ 1 day / 2 sessions a week); players under 5 weeks old: ≤ 50% of the median for peers of the same age; **return signal:** not seen for at least 7 days and more than 2× their usual gap between days played (4+ days played) | Own pace; own play rhythm; peer cohort |

A low raw value alone never triggers a list: every trigger is relative to a baseline.

## Output contract (`daily_lists`, SQLite)

| Field | Definition |
|---|---|
| `score_date` | Business date of the list |
| `player_id` | Player (player-day grain rolled up across platforms) |
| `list_type` | Exactly one primary list |
| `priority` | **High** if opportunity gap ≥ $20; **Medium** if gap ≥ $2, or money blocked by a failed/incomplete purchase, or score ≥ 75; **Low** otherwise (dollars first, severity second) |
| `underperformance_score` | 0–100: 0 = at baseline, 100 = play or spend stopped, or severe friction. Friction: 25 per event in the last 7 days; revenue: largest of spend drop %, overdue (100 at twice the threshold), % behind forecast, activity drop of high-value non-payers; engagement: largest drop in days played or sessions, or time away (100 at twice the return threshold) |
| `predicted_ltv_365`, `ltv_to_date` | From Part 3 (`ltv_scores`) |
| `opportunity_gap` | Expected value at the player's baseline − revised value now, never below $0. Older players: update-rule LTV at the previous vs the recent 28-day spending pace. Day-3 model players: dollars behind forecast × 2.49 |
| `reason_codes`, `reason_text` | Every triggered signal, as codes and readable text |
| `recommended_action` | Set by the list and its main reason (tech support, payments, CRM/VIP offer, lifecycle push) |
| `ltv_source`, `data_incomplete` | Where the LTV came from; 1 if the date's health check failed |
| `model_rules_version` | LTV model version + hash of the rule config |
| `created_at` | When the row was written |

`list_runs` logs each run: status (`ok`, `ok_data_incomplete`, `no_data`), eligible players, list sizes, ineligible players by reason, failed checks.

## Flow

`python -m sciplay.lists.run --date 2026-11-04` (or `--from … --to …`); also `from sciplay.lists.run import run`.

| Case | Handling |
|---|---|
| Rows only up to the score date | Signals use rows dated on or before it |
| Missing inputs (no prepared data, no trained LTV model) | Nothing listed; status `missing_input` with what to build |
| No data for the date (after the data end) | Nothing listed; run logged as `no_data` |
| No new data | Rerunning a date gives the same rows (replaced); the refresh only builds lists for a newly published date |
| Late or incomplete rows (health check fails) | List written, flagged `data_incomplete`; rerun when rows land |
| LTV scores missing | Computed and stored first |
| Ineligible players | Not listed; counted by reason in `list_runs` |
| Rerun, same date and version | Key (date, player, version): rows replaced; players who left the list are removed |
| New rules or model version | New rows beside the old ones; history kept per version; the dashboard and history show the latest version |

History (`sciplay.lists.history`): `changes(date)` (entered, exited, moved list, priority up/down vs the previous run date) and `spells()` (each continuous stay on a list: entered, last day, days, priorities).

## Threshold analysis (27 dates, 9 Oct – 4 Nov)

Average per day: friction 8, revenue decline 6, engagement decline 32 of ~159 eligible; ~8% of a day's listed players are new vs the day before.

- Activity drop 30% → 70%: engagement 29 → 35 a day; nothing else moves.
- Spend drop 30% → 70%: revenue 5.9 → 5.4; overdue 1.5× → 3×: 5.9 → 5.6. The revenue list is small because only 10 eligible players ever paid.
- 14-day window: friction doubles, engagement drops, lists more stable. **Kept: 7 days, 50%.**

## Backtest (10 weekly dates, 1 Aug – 5 Oct; next 30 days)

| Signal (compared with) | Days played next 30 | Stopped playing | Payer spend next 30 ÷ last 28 |
|---|---|---|---|
| Engagement decline (players with a play baseline) | 4.2 vs 11.0 | 44% vs 25% | – |
| Revenue decline (payers and high-value players) | 6.4 vs 9.4 | 23% vs 32% | 0.45 vs 0.59 |
| Friction (players active 3+ of the last 7 days) | 18.4 vs 14.8 | 5% vs 6% | 0.74 vs 0.53 |

Engagement and revenue signals point at players who then play and spend less: flagged engagement players were almost twice as likely to stop playing (44% vs 25%) and played 4 days instead of 11 (directional; ~176 and ~44 flagged player-days). Friction does not predict decline and is not meant to: it finds a problem to fix.

## Two dates and one player

| Date | Friction | Revenue decline | Engagement decline |
|---|---|---|---|
| 29 Oct | 7 (6 medium, 1 low) | 7 (3 high, 4 medium) | 36 (31 medium, 5 low) |
| 4 Nov | 11 (8 medium, 3 low) | 8 (3 high, 5 medium) | 31 (27 medium, 4 low) |

**Player 224283** (installed 7 Sep; $14.46 on 19 Sep; played almost daily to 9 Oct, then nothing until 3 Nov; bought again on 4 Nov):
- 9–14 Oct: **friction, low** — a support ticket in the last 7 days.
- 15–16 Oct: **engagement decline, medium** — played 1, then 0 of the last 7 days vs ~5 a week (score 93 → 100).
- 17 Oct – 3 Nov: **revenue decline, high** — $0 in the last 28 days vs $14.46 before; opportunity gap ~$23.
- 4 Nov: **engagement decline, low** — came back and bought again, so the revenue decline ends; sessions still 6 vs 17 a week.

## Tests (`tests/test_lists.py`)

One primary list and precedence; ineligible players never listed; readable reasons covering every signal and the matching action; threshold boundaries on the functions the flow uses (a drop of exactly 50% triggers, 49.99% does not; overdue only strictly beyond 2× the usual gap and ≥ 7 days; $19.99 is medium); missing inputs; idempotent persistence (same date twice, a rerun where a player left, a new version beside the old); on the real data: one row per player, rerun without duplicates, `no_data` after the data end, `data_incomplete` when the health check fails.
