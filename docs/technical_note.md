# Technical note

Two pages on the decisions that matter most. Details: [`ltv.md`](ltv.md), [`lists.md`](lists.md),
[`data_understanding.md`](data_understanding.md), [`stakeholder_plan.md`](stakeholder_plan.md).

## 1. Data and the as-of rule

The file has one row per player, platform and day played (4,245 rows, 700 players, 9 May – 4 Nov 2026). It is rolled
up to **one row per player per day**: daily measures are summed across platforms, lifetime fields taken once (7
player-days had two platforms). No row means the player did not play. **Revenue** is gross USD before store fees;
**revenue to date** = `LIFETIME_REVENUE` (a start-of-day value) + the day's `REVENUE`.

A score for day D uses only rows dated D or earlier and only columns known by the end of D. The column registry
(`docs/column_registry.csv`) records, for all 409 columns, its category, when it is known and whether it may be a
feature; 124 are excluded with a reason. The sample is 100 new players per install month, so totals are sample
totals and rates are what carries over.

## 2. Target validity

`D365_SPEND` is **not** a 365-day outcome: it equals `LIFETIME_REVENUE` on every filled row, is filled only for
payers, changes between snapshots, and no player is older than 169 days. There is no valid 365-day label.

What can be validated is **revenue in the first 30 days after install** (complete for the 518 players installed by 6
Oct; 16 paid). LTV365 is therefore a labelled proxy: a validated 30-day forecast × 2.49, where 2.49 comes from an
**assumed** monthly fade of 0.6 (sensitivity × 2.00–3.29). Two players hold 81% of all revenue, so the fade cannot be
estimated here. Players installed before 7 Oct are past the model's window and get an update rule (revenue to date +
a fading projection of the last 30 days), labelled "not from the LTV model" everywhere it is shown.

**Production target table:** `gross_revenue_d30` per player, written once install + 30 days + 91 days (the observed
rewrite lag) have passed. A trustworthy 30-day model needs about 6 matured install months of the full player base; a
365-day model about 27 months of history.

## 3. Leakage

Columns named like future outcomes were tested, not trusted:

| Columns | Finding | Decision |
|---|---|---|
| `D1`–`D90_RETURNER`, converters, `SPENDER_n` | Mean "played/paid n days after D" (100% match) | Excluded |
| `NEXT_LOGIN_DATE`, `DAYS_UNTIL_NEXT_PURCHASE`, churn flags | Describe what happens after D | Excluded |
| `I14`/`I30_REVENUE` | Install-day rows already show later purchases | Excluded (`I3`/`I7` kept only as a check) |
| `D7`/`D14`/`D30` window columns | Window may run past D | Excluded until verified |
| `LAST_4W_*` rolling columns | Window end not documented | Kept, used as given (logged risk) |

Rows are rewritten for up to 91 days after their date. Automated checks run before every training: features built
from data cut at day 3 equal features from the full file; no revenue column is ahead of revenue to date.

## 4. Validation and model choice

**Features** come from the first 3 days only (7 days would leave all November installs unscored): 359 built → 114
candidates → 18 in the model (play volume, bet size, balances, early spend, warning errors). Device and performance
columns were removed: with 6 payers the first run learned "slower loading → higher value".

**Split by install date**, every player in one set: train 9 May – 31 Jul (300 players, 10 payers by day 30), test
1 Aug – 6 Oct (218, 6), inference from 7 Oct. Feature selection and tuning use two forward folds inside training (May →
June, May–June → July). LightGBM (Tweedie) and a regularised Tweedie GLM went through the same pipeline; a rule fixed in
advance (lowest Tweedie deviance, within 5% the simpler model) picked **LightGBM** (deviance 2.18 vs 2.44). The test set
was used once, and the tested model is the shipped model.

**Results** on 218 test players: error per player $1.17, against $1.15 for "revenue so far" (no spending after day 3),
$1.80 for a simple rule and $3.04 for the training average. The tie is real: 212 players spend nothing after day 3,
and one late big spender is $0.80 of the $1.15. The model's value is **ranking**: the 3 players it valued at $20+ brought
91% of test revenue. Calibration (predicted ÷ actual) is 0.43 overall; by install month 0.80 (Aug), 0.60 (Sep), 0.23
(Oct, one player). With 6 test payers every number is directional. Use it to rank now; trust dollar levels later.

## 5. List logic

Each day, every eligible player (not a cheater or settlement, at least 3 days old, seen in the last 30 days) gets **at
most one** primary list, by precedence:

1. **Technical or payment friction** (fixable, and often the cause of the other two): crashes, errors, failed
   purchases, tickets or load failures above the player's own previous 28 days, or 2+ purchase attempts with none
   completed.
2. **Revenue decline** (where the money is): spend down ≥ 50% vs the previous 28 days, a purchase overdue by 2× the
   usual gap, ≥ 50% and $5 behind the LTV forecast, or a top-10% LTV non-payer playing less.
3. **Engagement decline** (the broadest): days or sessions ≤ 50% of the player's pace, new players below peers of the
   same age, or away 7–21 days and more than twice the usual gap.

Every player is compared with a baseline (own history, peers or forecast), never on a low raw value alone. Other
signals stay as reason codes. **Opportunity gap** = value at the player's baseline − revised value now; **priority**:
high if the gap ≥ $20, medium if ≥ $2, money blocked or score ≥ 75. Lists are ordered by priority, LTV365, then score.
Results go to SQLite, keyed by (date, player, model + rules version), so reruns never duplicate. A backtest on 10
weekly dates found flagged engagement players stopped playing far more often than comparable players (41% vs 27%).

## 6. Production data needs

- **Full population or sampling weights**, so totals and payer counts are real.
- **Matured labels** at 30, 90 and 365 days, to replace the × 2.49 assumption with a model.
- **Column definitions** confirmed with data engineering (rolling windows, the late-revenue offset, eligibility flags,
  which are never set in the sample).
- **Intraday events** (failed purchases, crashes, tickets) so friction can be caught within the hour.
- **Owner feedback** (ticket outcomes, Slack buttons, campaign membership) and a holdout to measure whether the lists
  change outcomes.
- **Monitoring**: calibration on matured cohorts, feature drift, coverage and freshness, with monthly retraining.
