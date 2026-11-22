# Part 1 · Data understanding

Everything for Part 1 in one place. The evidence and charts are in `notebooks/01_data_audit.ipynb`; every number below is produced by `src/sciplay/`. Assumptions A1–A12 are in `00_setup_and_assumptions.md`.

## 1. Source grain and duplicate keys

**One row = one player, on one platform, on a day the player was active.** The file is a daily summary, not raw events; many columns are pre-computed rolling or lifetime snapshots.

- `DATE + PLAYER_ID + PLATFORM_ID` is unique; no row is fully duplicated.
- 7 player-days (3 players) have two platform rows. Lifetime fields are identical across them; daily activity is split.
- 99.9% of rows have sessions and the login gap equals the gap between rows on 99.8%: **a missing row means the player did not play**, not missing data.
- A player appears once per active day (up to 116 rows). Model validation must therefore group rows by player.

**Handling:** roll up to one row per player per day (sum daily measures, take lifetime fields once, keep the main platform and a platform count). Repeated snapshots are scored through the as-of snapshot (section 5).

## 2. Coverage

| | |
|---|---|
| Rows × columns | 4,245 × 409 |
| Dates | 9 May – 4 Nov 2026, 180 continuous days |
| Players | 700; **exactly 100 new players per install month** (May–Nov) |
| First seen on install day | 699 of 700 |
| Rows per player | median 2; 332 players (47%) seen on one day only |
| Oldest player | 169 days since install; **nobody reaches day 365** |
| Payers | 23 players (3%) ever paid |
| Activity by age | ~30% active on day 1, 13–16% at days 91–120; cohorts look alike |

November's 100 installs all fall in 1–4 Nov (26–32 a day against 2–8), so the last days of the series are distorted. Daily active players grow only because a new cohort joins each month.

## 3. Field groups, missing values and inconsistent semantics

409 columns in 16 business groups (gameplay, game economy, device and performance, revenue and payers, store and offers, cohort milestones, social, activity, errors and friction, dates, acquisition, segments, pipeline metadata, compliance, keys, geography).

**85 columns carry no information** (37 all null, 48 a single value), including campaign and creative names and the cheater and settlement flags.

Most other nulls are structural, and three states are kept apart:

| Null in… | Means | Example |
|---|---|---|
| a daily count | **zero**: no event that day | `REVENUE` empty = no purchase |
| a last-event field | **not applicable**: never happened | `DAYS_SINCE_LAST_PURCHASE` empty = never paid |
| a dimension | **unknown** | `REGION` empty |

**Inconsistent semantics.** *Semantics* is what a field actually means, as opposed to what its name says. A field has inconsistent semantics when the data contradicts its name or its siblings.

| Field | Name suggests | Data shows | Decision |
|---|---|---|---|
| `D365_SPEND` | Spend in the first 365 days | Equals `LIFETIME_REVENUE` on 100% of filled rows; oldest player is 169 days | Excluded; not a valid target |
| `D1_RETURNER` … `D90_RETURNER` | Install milestone: came back by day n | Played exactly n days after the row date (99.9–100%) | Excluded (future); possible churn label later |
| `D30_SPEND` | Spend in the first 30 days | Still changes after day 30 for 7 players | Excluded |
| `D7/D14/D30_ACTIVE_DAYS` | Number of active days | Maximum value is 1: a yes/no flag | Excluded until verified |
| `LIFETIME_REVENUE` | Revenue up to and including the row date | Excludes the row date (90% next-row match) | Kept; revenue to date = `LIFETIME_REVENUE` + `REVENUE` |
| `LT_SPENDER_BUCKET` | Tier consistent with lifetime revenue | 23 rows say "Minnow" with lifetime revenue 0; all are first-purchase days | Reporting only |
| `IS_CHEATER`, `IS_CHEATER_DETECTED`, `CHEATS_DETECTED` | One yes/no concept | Three encodings: `'no'`, `False`, `0.0` | Normalised to one boolean in the eligibility filter |
| `PLATFORM_ID = apple_sign_in` | A platform | A login method (2 rows) | Kept as a platform value |

## 4. Column registry

Every column is in one of the six categories the brief names. Derived features and targets are computed by us, so they are added as rows of their own. Full table: `docs/column_registry.csv`.

| Category | Columns | Examples |
|---|---|---|
| Identifiers | 5 | `PLAYER_ID`, `PLATFORM_ID`, `GAME_ID`, `SLOT_ID`, `DATE` |
| Dimensions | 35 | `COUNTRY`, `SOURCE`, `DEVICE_TYPE`, `LT_PAYER_BIN`, `IS_CHEATER` |
| Observed measures | 245 | `SESSIONS`, `REVENUE`, `CRASHES`, `LAST_4W_REVENUE`, `LIFETIME_REVENUE` |
| Derived features | 7 | revenue to date, age in days, days since last seen, active on score date, platform count, main platform, install cohort |
| Targets | 2 | `revenue_first_30d` (training label), `ltv365` (model output) |
| Excluded | 124 | leakage 28, not a valid target 2, unverified 9, no information 80, redundant 3, freshness metadata 2 |

409 file columns + 9 computed = 418 rows.

## 5. As-of policy

**A score for day D, as of the end of D (UTC), uses only rows dated D or earlier, and only columns the registry marks as features. The future may appear in the label, never in a feature.**

Revenue to date at the end of D = `LIFETIME_REVENUE` (start of D) + `REVENUE` (day D).

The policy is code (`src/sciplay/asof.py`) and tested (`tests/test_asof.py`): `assert_as_of` fails if a feature frame holds a row after D or a column the registry excludes.

**Example A, an active player.** Player 289987 installed on 1 Oct, scored for D = 8 Oct.

| Date | Sessions | REVENUE | LIFETIME_REVENUE | D1_RETURNER | NEXT_LOGIN_DATE | Used? |
|---|---|---|---|---|---|---|
| 7 Oct | 1 | – | 50.80 | 1 | 8 Oct | Row yes; flags no |
| **8 Oct** | **6** | **8.84** | **50.80** | **1** | **9 Oct** | Row yes; flags no |
| 9 Oct | 9 | 17.67 | 59.64 | 1 | 10 Oct | No: after D |

- Revenue to date = $50.80 + $8.84 = **$59.64**; the 9 Oct row confirms it.
- `D1_RETURNER = 1` and `NEXT_LOGIN_DATE = 9 Oct` on the 8 Oct row describe 9 Oct: excluded.
- Label (training only): his revenue from 9 Oct to 7 Nov.

**Example B, an inactive player.** Player 160253's last row is 6 Sep. Scored on 10 Sep, the snapshot carries that row forward: $84.48 revenue to date, 4 days since last seen. Of 440 players known by 10 Sep, only 30 played that day; without the snapshot the other 410 would not be scored.

**Missing target.** The label is revenue in the 30 days after D. A day without a row is a day without play (A1) and an empty `REVENUE` is a day without a purchase (A2), so $0 is supported for players who did not pay. Score dates whose 30-day window runs past the data have *no* label, not a zero one.

## 6. Leakage audit

A column leaks when its value on the row for day D depends on what happens after D.

| Columns | Why suspicious | Decision |
|---|---|---|
| `D1`–`D90_RETURNER`, `D<n>`, `D<n>_CONVERTER`, `SPENDER_<n>` | Describe activity n days after D (verified 99.9–100%) | **Excluded** |
| `NEXT_LOGIN_DATE`, `DAYS_UNTIL_NEXT_PURCHASE`, `CHURNERS*` | Describe what happens after D | **Excluded** |
| `D365_SPEND`, `D30_SPEND` | Lifetime spend so far, not a fixed window | **Excluded**, not a valid target |
| `D7/D14/D30_ACTIVE/PURCHASE/SPINS_DAYS` | Window may run past D | **Excluded until verified** |
| `I14_REVENUE`, `I30_REVENUE` | Revenue in the first 14/30 days after install, written on every early row: early rows show purchases not made yet (player 8520: $15.40 on install day, spent on day 1–2) | **Excluded** (found in Part 3) |
| `I3_REVENUE`, `I7_REVENUE` | Same pattern; equal to our own sum of `REVENUE` over days 0–2 / 0–6 (99.9% / 99.7%) | **Excluded as features**, kept as a consistency check |
| `LIFETIME_REVENUE` | Start-of-day value | **Kept**, plus same-day `REVENUE` |
| `LAST_4W/8W/12W_*`, `DAYS_SINCE_*` | Rolling; window end not documented | **Kept**, used as given (A9) |
| Spend segments (`LT_PAYER_BIN`, `TOTAL_SPEND_LAST_4W_SEGMENT`) | Built from spend | **Reporting only** |

Every excluded column and its evidence is in `column_registry.csv` (`use`, `evidence`).

## 7. Late data, multiple platforms, sparse fields

| | What we see | Effect on calculations | Handling |
|---|---|---|---|
| **Late-arriving data** | Recent rows land ~2 days late; every row changes until 91 days after its date (because `D90_RETURNER` can only be filled on D+90) | Yesterday may be missing; forward-looking flags on recent rows keep changing | Score D only once its rows have landed (freshness check); features only from as-of-safe columns; labels only after their window has passed |
| **Multiple platforms** | 7 player-days with two rows | Counting rows double counts players and splits a day's play | One row per player per day; main platform + platform count |
| **Sparse event fields** | No row on days off; `REVENUE` empty on 97% of rows | Days off look like missing data; averages over rows overstate activity; zeros dominate revenue | As-of snapshot carries players forward; empty daily count = 0, empty last-event = not applicable; LTV model built for many zeros (Tweedie, Part 3) |

## 8. Data quality issues

| Theme | Issues | Evidence | Resolved by |
|---|---|---|---|
| Target validity | Q1 `D365_SPEND` is lifetime spend so far | 100% equal to `LIFETIME_REVENUE`; max age 169 days | Defining LTV365 ourselves: validated 30-day forecast × an assumed multiplier (Part 3) |
| Revenue definition | Q2 daily and lifetime revenue offset by a day | 90% next-row match vs 9% same row | Revenue to date = `LIFETIME_REVENUE` + `REVENUE` |
| Time integrity | Q3 rows rewritten for 91 days; Q5 forward-looking fields | `D<n>_RETURNER` = played n days later; `D1_RETURNER` = 1 on 213 install-day rows | As-of policy and registry; training and testing are safe, past lists are audited from the stored list history |
| Sample limitations | Q4 100 installs per month; Q6 exclusion flags never set | Exact cohort sizes; single-value flags | Rates instead of totals; uncertainty on LTV; eligibility filter built and unit-tested |

## 9. Definitions

| Term | Unit | Business meaning | Calculation |
|---|---|---|---|
| **Revenue** | Gross USD per player per day | In-app purchases that day, before store fees and refunds; no ad revenue in the data | `REVENUE` = coin packs + hot offers + out-of-coins offers; empty = $0 |
| **Revenue to date** | USD per player | Everything paid since install, up to the end of D | `LIFETIME_REVENUE` (start of D) + `REVENUE` (day D) |
| **LTV365** | USD per player | Expected gross revenue in the first year after install | Revenue to date + modelled revenue up to day 365; cohort LTV = average |
| **Active player** | Player on a day | Played that day | Has a row with sessions on D; DAU = count of active players |
| **Payer** | Player | Ever-payer: paid at least once. Recent payer: paid in the last 4 weeks | Revenue to date > 0; `LAST_4W_REVENUE` > 0 |
| **Underperformance** | Player on score date D | Clearly less play or spend than expected, for a reason a team can act on | One list per player, in this order, ranked by value at risk |

**The three lists**

1. **Friction:** technical problems in the last 7 days: failed purchase or store verification, crash, unhandled error, support ticket. Cancelled purchases are not friction (mostly players browsing the store); they are a supporting reason on the other lists.
2. **Revenue decline:** a payer whose last 4 weeks' spend is at least 50% below the 4 weeks before, or who is well past their usual purchase gap.
3. **Engagement decline:** plays well below their own 28-day pace or the median player of the same age, or is well past their usual gap.

**Eligibility:** not a cheater or legal settlement (flags normalised to one boolean), at least 3 days since install, seen in the last 30 days (A12). **Value at risk** = predicted LTV365 − revenue to date (USD). Thresholds live in a config file.
