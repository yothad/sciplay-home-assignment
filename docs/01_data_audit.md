# Data audit

Source: `sample_data.csv` supplied with the assignment. First-pass profiling on 2026-11-20.

## Grain

**Aggregated, not raw events.** One row = player × platform × day **on which the player was active**.

Evidence:
- No duplicates on `(DATE, PLAYER_ID, PLATFORM_ID)`.
- 4,241 / 4,245 rows have `SESSIONS > 0`.
- `DAYS_SINCE_LAST_LOGIN` equals the gap to the previous row for 99.8% of rows.

Implication: a missing row = an inactive day, not missing data. Scoring needs an **as-of table** that carries each player's last snapshot forward, so inactive players are still scored.

Many columns are pre-computed rolling / lifetime snapshots (`LAST_4W_*`, `D7_*`, `D30_*`, `LIFETIME_*`).

## Coverage

| Metric | Value |
|---|---|
| Rows × columns | 4,245 × 409 |
| Players | 700 |
| Dates | 2026-05-09 → 2026-11-04 (180 distinct) |
| Rows per player | median 2, mean 6.1, max 116; 332 players have 1 row, 80 have ≥ 10 |
| Install cohorts | exactly 100 players per install month (May–Nov) → **stratified sample** |
| Age (days since install) | 0–169; nobody near day 365 |
| First observed at day 0 | 99.9% of players |
| Ever-payers | ~23 players (530 rows) |
| Platforms | android 2,743 · ios 1,424 · facebook 53 · kindle 15 · sciwebgl 8 · apple_sign_in 2 |
| Multi-platform player-days | 7 player-days (3 players) have two platform rows |

## Missingness

| Group | Count | Examples |
|---|---|---|
| 100% null | 37 | campaign / adgroup / creative, `INSTALL_TYPE`, `INSTALL_SOURCE`, DTC & SciPay lifetime fields, several revenue components |
| > 95% null | 33 | `REVENUE` (97.1%), `PAYERS`, `TRANSACTIONS`, `I3/I7/I14/I30_REVENUE`, `DAYS_UNTIL_NEXT_PURCHASE` |
| 50–95% null | 47 | |
| No nulls | 92 | |
| Constant (≤ 1 distinct value) | 85 | `GAME_ID='test'`, `IS_CHEATER='no'`, `IS_LEGAL_SETTLEMENT='no'`, `VIP_SEGMENT`, `CHURNERS_*` |

## Data quality issues that could change a business decision

1. **`D365_SPEND` is not a 365-day outcome.** Equals `LIFETIME_REVENUE` on 100% of populated rows; null exactly when the player never paid; changes across snapshots for 12 of 21 payers. It is censored lifetime-to-date spend.
2. **`REVENUE` and `LIFETIME_REVENUE` are offset by one day.** Same-row reconciliation holds for only 9% of payer rows; today's `REVENUE` appears in the *next* row's lifetime total 83% of the time. `LIFETIME_REVENUE` looks like a start-of-day value → summing both would double count.
3. **`REVENUE` null = no purchase that day** (safe to treat as 0 for daily revenue). Not the same as a null target.
4. **`D30_SPEND` keeps changing after day 30** for 7 players → not a frozen day-30 cohort metric.
5. **Late-arriving / restated rows.** May–June rows have `LAST_UPDATE_DATETIME` = 2026-09-03; most rows were last updated 2026-11-05. Re-scoring a historical date from the current file sees data that did not exist then.
6. **Cheater / settlement flags are all "no"** in the sample. The exclusion policy is implemented but cannot be tested on this data.
7. **Inconsistent semantics.** `LT_SPENDER_BUCKET` populated on 430 rows vs 407 rows with lifetime revenue; `D7_ACTIVE_DAYS` max is 1 (a flag, not a count); `apple_sign_in` appears as a platform.
8. **Extreme scales and outliers.** Coin / bankroll / wager fields in the billions (log transform); `MEDIAN_LOAD_TIME` max ≈ 98k vs mean ≈ 190; `SPIN_LATENCY` heavy tail.
9. **Sample is stratified by install month** → totals do not represent the population; the Nov cohort is ≤ 4 days old.

## Field groups

_To be completed with the column registry (identifier / dimension / measure / derived / target / excluded)._

## Open questions

- Currency and gross vs net definition of `REVENUE` (store fee, DTC net fee).
- Exact refresh time of `LIFETIME_REVENUE` and rolling windows (start vs end of day).
- Whether rows are ever restated after first load in production, and how often.
