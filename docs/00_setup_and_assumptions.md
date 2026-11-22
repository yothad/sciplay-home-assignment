# Assumptions and decisions

Setup and commands are in the [README](../README.md). This file holds every assumption (with its evidence and the
impact if wrong) and the dated decision log.

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
| B1 | Default score date = 4 Nov, the last data day: every player installed up to 2 Nov has a day-3 LTV forecast (was 31 Oct before Part 3) | Decided | – |
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

### LTV (Part 3)

| # | Assumption | Status | Evidence | Impact if wrong |
|---|---|---|---|---|
| C1 | **Each 30-day block after the first is worth r = 0.6 × the block before, so LTV365 = 30-day forecast × 2.49** | **Assumption, not estimated** | Month-to-month ratios come from two players; without them revenue after month 1 is under $100 a month in the sample | LTV365 level; sensitivity r = 0.5–0.7 gives × 2.00–3.29 |
| C2 | One multiplier fits every player | Assumption | Too few payers to estimate groups | Ramping payers understated |
| C3 | The first 3 days are enough to forecast the first 30 | Tested out of time | 39% of 30-day revenue known by day 3; the 3-day rule is better calibrated than "revenue so far" (0.79 vs 0.34) but worse on MAE | Weaker forecasts for new players |
| C4 | Late-July training labels overlapping August test calendar time is harmless | Accepted risk | No known August event | Slightly optimistic test results |
| C5 | Recent 30-day labels are final | Assumed | Rows are rewritten up to 91 days later; labels used up to 6 Oct installs | Test labels could still change |

### Daily lists (Part 4)

| # | Assumption | Status | Evidence | Impact if wrong |
|---|---|---|---|---|
| D1 | Thresholds (7-day window vs the previous 28; 50% drops; 2× usual purchase gap; ≥ 50% and $5 behind forecast) are reasonable starting values | Starting values, tunable | Sweep: only the activity threshold moves list sizes much | Lists too long or too short |
| D2 | Repeated incomplete purchase attempts are friction; single cancellations are not | Decided | Cancellations are mostly store browsing (Part 1) | Missed or false payment-friction cases |
| D3 | Priority: dollars first ($20 / $2 tiers), then blocked money or severity ≥ 75 | Decided | Dollar tiers alone make every non-payer list low | Wrong order of work |
| D4 | A failed health check for the date means late data: publish the list flagged | Decided | – | Lists from incomplete data acted on |
| D5 | Return signal: away 7–21 days and more than 2× the usual gap between days played | Decided (option b) | Backtest: flagged players stop playing 41% vs 27% | Players lost later than 21 days get no come-back message from this list |

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
| 2026-11-21 | Proposed split: train and test end 31 Oct, inference on 1–4 Nov (superseded by the Part 3 split by install date) | Shows train → test → daily scoring; November is unseen, like production |
| 2026-11-21 | Provided rolling / lifetime columns used as they are (or ignored), not rebuilt | Simplicity |
| 2026-11-21 | Revenue = gross USD; days = UTC | Not stated in the data |
| 2026-11-21 | Active on D = has a row with sessions on D; inactive players carried forward | Rows exist only on days played |
| 2026-11-21 | Definitions of revenue, revenue to date, LTV365, active player, payer, underperformance approved | See `data_understanding.md` |
| 2026-11-21 | Friction = technical problems only; cancelled purchases are a supporting reason | Cancels are mostly players browsing the store |
| 2026-11-21 | Value at risk = predicted LTV365 − revenue to date | Simple, in dollars |
| 2026-11-21 | Churn cut-off: 30 days without a row | Approved |
| 2026-11-21 | Claude Slides is the master deck; PowerPoint is a backup | Edited and presented in the browser |
| 2026-11-21 | Dashboard opens on 31 Oct (changed to 29 Oct in Part 3) | Last fully representative day |
| 2026-11-21 | Filters add country and acquisition type | Answer to Q2 |
| 2026-11-21 | Both revenue per active player and revenue per paying player shown | Answer to Q5 |
| 2026-11-21 | No HTML snapshot; a sample of the dashboard on 31 Oct goes into the deck instead | Simpler; the deck is what gets shared |
| 2026-11-21 | "Who needs attention" stays in the dashboard (brief, Part 2); filled from the Part 4 lists | Manager sees the lists; Part 5 pushes them |
| 2026-11-21 | Refresh command: intake → merge (latest version per key wins) → rebuild in staging → health gate → publish → log | Handles incremental files, restated rows, missing or bad data |
| 2026-11-21 | Sample banner and Overview tiles reconciled from data: banner computed from installs per month; score-date tiles checked with SQL | Brief: no hard-coded values; reconcile what the manager sees |
| 2026-11-21 | Production: refresh runs as a job in a data orchestration pipeline with cloud storage | Noted on the deck; out of scope locally |
| 2026-11-21 | LTV365 (gross USD) stays the target, labelled a proxy; the validated piece is revenue in the first 30 days | Brief's definition; Part 4 value at risk needs a year |
| 2026-11-21 | Label = revenue on days 0–29 after install; not 90 or 365 days | Too few complete labels for 90/365 (322 / 0 players) |
| 2026-11-21 | Features from the first 3 days only (7 days considered first, then changed) | 7 days would leave all 100 November installs in cold start; 3 days scores 132 players instead of 79 |
| 2026-11-21 | Split by install date: train 9 May–31 Jul, test 1 Aug–6 Oct, inference 7 Oct–2 Nov, cold start 3–4 Nov | Players never in two sets; time order respected; test needs complete 30-day labels (installs up to 6 Oct) |
| 2026-11-21 | Ship the tested model; no refit on test players | Every reported number describes the model in use |
| 2026-11-21 | LightGBM (Tweedie) is the model; baselines and the simple rule are benchmarks | Brief: compare with a simple baseline |
| 2026-11-21 | Model predicts revenue on days 3–29; 30-day forecast = observed days 0–2 + prediction | Forecast never below revenue so far; SHAP explains only the future |
| 2026-11-21 | Feature selection + tuning on two forward folds inside training, by Tweedie deviance; 4 rounds (~150 → 50 → 20 → 10) × 8 settings | Test set used once; MAE rewards predicting $0 |
| 2026-11-21 | I14/I30_REVENUE excluded (forward-looking); I3/I7 excluded as duplicates, kept as a check | Early rows show later purchases |
| 2026-11-21 | Confidence from a 50-model bootstrap: interquartile range × 2.49; High/Medium/Low by width ÷ max(forecast, $1) | Brief: uncertainty indicator |
| 2026-11-21 | Reasons: top 1–3 SHAP effects by absolute size, in dollars, both directions | Stakeholder-readable |
| 2026-11-21 | Players installed before 7 Oct (too old for the model's window): update rule (revenue to date + last 30 days × remaining decay; $0 after 30 days unseen), labelled "not from the LTV model" | Part 4 needs a value for every eligible player |
| 2026-11-21 | Model forecasts carried forward with ahead/behind against expected revenue by day d | Brief: updates as behaviour arrives |
| 2026-11-21 | Scores stored in SQLite (`ltv_scores`) | Unique key makes reruns idempotent |
| 2026-11-21 | Dashboard default date 4 Nov (briefly 29 Oct while the model used 7 days) | Every inference player has a day-3 forecast by then |
| 2026-11-22 | Lists: Technical or payment friction → Revenue decline → Engagement decline (precedence) | Fixable first, money next, broadest last |
| 2026-11-22 | Valuable = payer or top 10% predicted LTV365; LTV feeds the behind-forecast trigger and the opportunity gap | Brief: "payer or valuable player"; LTV is good at ranking |
| 2026-11-22 | Opportunity gap = expected value at baseline − revised value (not LTV − revenue to date) | LTV − revenue to date lowers the priority of players whose spending dropped |
| 2026-11-22 | Daily lists in SQLite (`daily_lists`, `list_runs`), key (date, player, model + rules version) | Idempotent reruns; history per version |
| 2026-11-22 | Part 5 built as a dry run: messages rendered to an outbox, full audit; no real Slack / email / ticket clients | Brief: implementation optional; swapping the writer for clients is the only change |
| 2026-11-22 | One studio per game (GAME_ID); payments and tech support = one Player support team; economy designer and product analyst on the emails | Owners as discussed; one team handles friction |
| 2026-11-22 | Tickets for friction and revenue lists (opened once per stay); engagement goes to CRM campaigns, no ticket | Ticket per player only where a person acts on one player |
| 2026-11-22 | Delivery runs every hour; lists rebuilt only when the daily extract lands (day D at 06:00 on D+1); Slack hourly with no duplicates | Find players quickly; data is daily, intraday data listed as a production need |
| 2026-11-22 | Emails at 08:00 (still open from yesterday + new overnight) and 18:00 (handled today, in progress, open, overdue); quiet hours 21–08 | Fewer, predictable messages |
| 2026-11-22 | Feedback inputs described, not built: ticket webhook, Slack buttons, dashboard form; simulation inserts them hourly | Agreed scope |
| 2026-11-22 | Escalation: medium/high player with no action by the evening of the 2nd day on the list, counted from go-live | Agreed rule; teams can only act from the day they are told |
| 2026-11-22 | Event alerts grouped per list, max 5 per channel per day; retries ×3 with one idempotency key | Alert fatigue; safe re-runs |
| 2026-11-22 | AI summary: prompt template + desired result + pydantic validation + template fallback; no LLM API connected | Brief: paid model not required |
| 2026-11-22 | Holdout written as a suggestion only | Needs a studio decision |
| 2026-11-22 | Order in the dashboard, tickets and messages: priority → predicted LTV365 → score; the score stays behaviour-only | Money first; LTV already drives the priority through the gap |
| 2026-11-22 | Two-dates example: 3 and 4 Nov (consecutive, the same days as the delivery simulation), was 29 Oct | Consistent story |
| 2026-11-22 | One name per team everywhere: Player support team, VIP team, CRM team (leads: Player support / VIP / CRM lead) | Consistent recipients; actions in the lists use the same names |
| 2026-11-22 | Trigger thresholds kept as starting values, checked on 26 days of list history (about one alert every 3 days) | Evidence for the values; review after 4 weeks |
| 2026-11-22 | The trained LTV model (`models/ltv/`) and example delivery output (`docs/examples/outbox/`) are committed; raw CSV and brief still are not | Quick setup for reviewers: no training needed; messages visible without running |
| 2026-11-22 | One command, `python -m sciplay.run_all` (prepare → load or train → score → lists → optional delivery and app) | Brief: one clear command |
| 2026-11-22 | Final review against the brief: technical note added; dashboard gains daily list counts (Overview), engagement and list volume (Trends), a Segments page, priority and reason filters with CSV download (Who needs attention), and the rules version (Data health); concerns C13–C16 added | Brief's Part 2 minimum content, submission package and concern areas |
