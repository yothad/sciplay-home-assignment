# Part 3 · LTV through day 365

Notebook: `notebooks/02_ltv.ipynb`. Code: `src/sciplay/ltv/`. Shipped model: `models/ltv/` (loaded by `run_all`).

## In one line

The first 3 days of play → a **validated** forecast of gross revenue in the first 30 days → **× 2.49, an assumption** → LTV365 (gross USD, a labelled proxy).

## 1. Definition

LTV365 = expected cumulative gross revenue (USD, before store fees and refunds) from install to day 365, as of a daily score date. The brief's definition is kept; *how* it is estimated is labelled a proxy because only the first 30 days can be validated.

## 2. Target validation

| Test | What we found | Verdict |
|---|---|---|
| Availability | Filled on 407 of 4,245 rows, only for players who have paid (21) | Payers only |
| Population | 0 of 700 players reach day 365; the oldest has 169 days of data | No mature outcome |
| Stability | Changes between snapshots for 12 of 21 payers | Not fixed |
| Relationship to revenue | Equals `LIFETIME_REVENUE` on 100% of filled rows | Duplicate column |
| Censoring | Every player is censored, at 0–169 days of data | Fully censored |

**There is no valid 365-day label, so `D365_SPEND` cannot be used to train.**

## 3. What we learn from, and why

| Horizon | Players with a complete label | Payers |
|---|---|---|
| **30 days** | **518** | **16** |
| 90 days | 322 | 15 |
| 365 days | 0 | 0 |

**Not 90 or 365 days: too few players with a complete label, so train and test sets would be too small.**

**How much do the first days tell us?** (train + test players, pooled dollars, so big payers dominate)

- By day 3: 39% of 30-day revenue is known, and 9 of the 16 payers have already paid.
- By day 7: 45%, and 11 of 16.

Quick out-of-time check with the simple rule:

| First k days | Rule MAE | "Revenue so far" MAE | Rule: predicted ÷ actual |
|---|---|---|---|
| 3 | $1.80 | $1.15 | 0.79 |
| 7 | **$1.01** | $1.09 | 0.71 |

**Decision: one model from the first 3 days.**

- 7 days carries more signal, but would leave all 100 November installs without a forecast; 3 days scores 132 players instead of 79.
- The 3-day rule loses to "revenue so far" on MAE (which rewards predicting $0) but is far better calibrated (0.79 vs 0.34) and better on payers.
- Train and test sizes do not depend on the window.
- Rejected: predicting days 3–7 only (2 of 518 players first pay in that window; day 365 would need two assumed multipliers).

## 4. Split by install date

| Set | Installs | Players | Paid by day 3 | Paid by day 30 |
|---|---|---|---|---|
| Train | 9 May – 31 Jul | 300 | 5 | 10 |
| Test | 1 Aug – 6 Oct | 218 | 4 | 6 |
| Inference | 7 Oct – 2 Nov | 132 | 1 | – |
| Cold start (under 3 days) | 3 – 4 Nov | 50 | 0 | – |

Players are never in two sets. The tested model is the model that ships (no refit on test players). Accepted risk: late-July training labels run into August calendar time.

## 5. From 30 days to 365: the multiplier

**LTV365 = 30-day forecast × (1 + r + r² + … + r¹¹)**

| Step | All players | Without the top spender | Without the top 2 |
|---|---|---|---|
| Month 1 → 2 | 2.84 | 2.40 | 0.32 |
| Month 2 → 3 | 0.60 | 0.08 | 0.91 |
| Month 3 → 4 | 0.66 | 0.77 | 0.77 |
| Month 4 → 5 | 0.37 | 0.00 | 0.00 |

The two top spenders hold 81% of all revenue. Without them, revenue after month 1 is under $100 a month in the whole sample.

**r cannot be estimated from this sample. We assume r = 0.6 → × 2.49, sensitivity r = 0.5–0.7 → × 2.00–3.29. One multiplier for every player. Not validated.**

## 6. Features

From rows dated install … install + 2 only, and columns the registry allows.
**359 built features → 372 after one-hot → 114 candidates** after the pre-filter (non-zero for at least 3 training
players; one of each pair with rank correlation > 0.95) → **18 in the shipped model**.

| Type | Columns | Summary over days 0–2 |
|---|---|---|
| Count | 96 | sum, mean per active day, max |
| State | 14 | last value (+ change for levels) |
| Average | 8 | mean over active days |
| Friction | 10 | sum + any |
| Flag | 11 | share of active days |
| Categorical | 6 | first row; one-hot, levels under 20 training players → Other |
| Built from our rows | 10 | revenue days 0–2, active days, played day 1, last active day, first purchase day, never paid, revenue per session, store conversion, purchase failure rate |

Left out (111 columns): the file's own rolling windows (45), device, app and performance (41), lifetime / consecutive
counters (12), recency columns rebuilt from our rows (7), non-numeric (4), near-constant (2). Install-window revenue
(`I14/I30_REVENUE`) is excluded by the registry (it shows later purchases).

**The 18 features in the shipped model**, by theme:

| Theme | Features |
|---|---|
| Bet size (5) | max bet amount, min and max bets, bet denomination, median bet |
| Play volume (6) | regular spins (total, per day), auto-spins, sessions, daily jewel tasks (per day, best day) |
| Balances (5) | max and ending bankroll, ending SLIB, ending ruby bankroll, pearl coin inflow |
| Spend (1) | revenue in days 0–2 |
| Friction (1) | warning errors |

"Plays a lot, at higher stakes" drives the forecast; early spend matters little for the *remaining* revenue, because
most players who spent in days 3–29 had not paid in days 0–2.

**Leakage checks (all pass):** truncation (features from data cut at the feature date = from the full file); no revenue-type column ahead of revenue so far; our day 0–2 / 0–6 revenue equals `I3_REVENUE` (100%) / `I7_REVENUE` (99.9%).

## 7. Maturity (production)

| Stage | Label final at | Trustworthy model needs | In this sample |
|---|---|---|---|
| 30-day | install + 30 + 91 days (~4 months) | ~6 matured install months, full player base | 518 labels, 16 payers: enough to build and check, too few to trust |
| 90-day | install + 90 + 91 days (~6 months) | ~12 months of data | 322 labels, 15 payers: too small to split |
| 365-day | install + 365 + 91 days (~15 months) | ~27 months of data (12 matured install months) | 0 labels |

91 days = observed rewrite lag (90% of rows). "Trust" = enough payers in held-out cohorts for stable calibration; working rule ≥ 200 payers (proposal). Production label table: `gross_revenue_d30` per player, written once its window has passed.

## 8. Non-payers, censoring, skew, sparse labels, cold start

| Issue | How it is handled |
|---|---|
| **Non-payers** (97% of players) | Kept in training as $0 labels; Tweedie objective built for many zeros plus a few large values; early activity separates engaged non-payers from one-day players |
| **Censored outcomes** | Only players with a complete 30-day window are trained or tested on; no row on a day = $0 (did not play); the 365-day value is never treated as observed |
| **Skewed revenue** | Tweedie objective; top spenders kept (their 30-day values are not extreme); bootstrap ranges on every test metric; the multiplier is an assumption, not estimated from two players |
| **Sparse labels** (6 training players spend in days 3–29) | Strong regularisation (4 leaves, ≥ 40 players per leaf), selection on training folds, the simple rule as benchmark, no synthetic oversampling; results reported as directional |
| **Cold start** | Under 3 days of data: no forecast (n/a); from day 3 the model |

## 9. How much of the value is observed, validated or assumed (4 Nov)

| Players | LTV365 shown | Already spent | Validated forecast (rest of the 30 days) | Assumption (× 2.49 beyond day 30, or update-rule projection) |
|---|---|---|---|---|
| Day-3 model (132) | $131.85 | $12.05 (9%) | $40.81 (31%) | $78.99 (60%) |
| Update rule (518) | $4,885.97 | $4,176.09 (85%) | – | $709.88 (15%) |
| All | $5,017.83 | 83% | 1% | 16% |

Most of the money on the dashboard is revenue already spent; for new players most of LTV365 is the assumption.

## 10. Model selection (training folds only)

Two candidates go through the same pipeline: **LightGBM** (Tweedie), the model to run at scale, and a
**regularised Tweedie GLM**, a simpler challenger.

1. Start from the same 114 candidates.
2. Try 8 settings × 4 feature-set sizes (all → 50 → 20 → 10), keeping the features with the largest SHAP each round.
3. Score every try by Tweedie deviance on remaining revenue (days 3–29), on two forward folds inside training:
   fit on May, predict June; fit on May–June, predict July. Only 4 validation players spent in days 3–29.
4. Pick by a rule fixed in advance: lowest deviance; within 5%, the simpler model. The test set is not used.

Device, app and performance columns (load times, latency, FPS, spin length, device type, OS version) are **not LTV features**: they describe the phone and app, not the player's intent to spend; with 6 payers the first run learned "slower loading → higher value", which did not hold. They stay in the Part 4 friction list.

| Model | Picked round | Features | Fold deviance | Fold MAE | Predicted ÷ actual |
|---|---|---|---|---|---|
| **LightGBM** | 3 | 18 | **2.18** | $0.42 | 0.74 |
| Tweedie GLM | 4 | 10 | 2.44 | $0.60 | 1.08 |

*Deviance* (Tweedie deviance) is the error measure the model itself minimises, built for revenue that is mostly $0 with a few large values; lower is better. It is not variance, and unlike average error per player a model cannot score well on it by predicting $0 for everyone.

**Why LightGBM:**

- The rule picked it before the test set was touched: 12% lower deviance than the GLM, beyond the 5% tie margin.
- It also had the lower error per player; the GLM was better calibrated. With 4 validation payers the gap is within noise.
- Settings: 4 leaves, ≥ 40 players per leaf, Tweedie power 1.2, 135 trees (strongly regularised for few payers).
- With more data, a smarter search (e.g. Optuna) would replace the fixed grid.

## 11. Test results (graded once; 218 players, 6 payers)

| Approach | MAE (range) | Payers MAE | Predicted ÷ actual | Dollar recall | Payer recall |
|---|---|---|---|---|---|
| Revenue so far | $1.15 ($0.17–2.73) | $41.7 | 0.34 | 94% | 4 of 6 |
| Training average | $3.04 ($1.59–5.12) | $61.7 | 0.80 | 100% | 6 of 6 (flags all) |
| Simple rule (benchmark) | $1.80 ($0.87–3.33) | $39.6 | 0.79 | 94% | 4 of 6 |
| **LightGBM (shipped)** | **$1.17 ($0.23–2.77)** | $39.7 | 0.43 | 94% | 4 of 6 |
| Tweedie GLM (challenger) | $1.44 ($0.46–3.06) | $41.2 | 0.53 | 94% | 4 of 6 |

*MAE* = error per player: the average of |actual 30-day revenue − forecast| over the test players. "Revenue so far"
predicts no spending after day 3, so its error is the spending it misses in days 3–29. Four real test players:

| Test player | Spent by day 3 | Spent by day 30 | Revenue so far: miss | Model: prediction, miss |
|---|---|---|---|---|
| A · 186166, never pays | $0.00 | $0.00 | $0.00 | $0.00, $0.00 |
| B · 169231, pays early only | $10.96 | $10.96 | $0.00 | $13.75, $2.79 |
| C · 208292, keeps paying | $17.77 | $35.54 | $17.77 | $23.42, $12.12 |
| D · 289987, big spender later | $50.80 | $225.34 | $174.54 | $50.89, $174.45 |

212 of 218 players are like A, so "no more spending" costs nothing there; player D alone is $0.80 of the $1.15.

Value bands: predicted $20+ → 3 players, all payers, $345 actual (91% of test revenue); predicted under $1 → 212 players, $22.

**Headline:**

- On error per player the model only ties "revenue so far" ($1.17 vs $1.15, ranges overlap).
- It **ranks** players well: revenue so far gives every non-payer $0 and cannot rank the 97% who have not paid yet.
- Like every approach it under-predicts total dollars (player D), and it missed the 2 players who first paid after day 3.
- **Use it to rank and prioritise now; trust dollar levels once more payers are available.**

The tested model is the shipped model (no refit on test players).

## 12. Reasons, uncertainty, confidence

- **Reasons:** the 1–3 features with the largest |SHAP| for the player (until 70% of their total |SHAP| is covered; none under 10%), both directions. Each reads *"Regular spins, first 3 days: 6,365 vs typical 217 (+$9.25)"*: this player's value, the median training player's value, and how much lower the forecast would be **without that one signal**, all else equal (the model works on a log scale, so removing a contribution divides the forecast by exp(SHAP)). Effects overlap, so they do not add up. With no effect above $0.05: *"No strong value signals in the first 3 days … (average new player: $0.73 still to come)"*.
- **Range:** 50 bootstrap refits of the shipped model; shown range = forecast × (25th or 75th percentile ÷ median), so it always contains the forecast. LTV365 range = 30-day range × 2.49.
- **Confidence (rule-based):** High = paid in the first 3 days; Medium = active non-payer; under 3 days old = no forecast. The bootstrap spread could not yet separate good from bad forecasts (most resampled models predict close to $0); with thousands of payers it becomes a checkable confidence measure.

## 13. Who gets which value (`ltv_scores`, SQLite)

| Source | Who | Value |
|---|---|---|
| `model_d3` | Installed from 7 Oct, at least 3 days old | 30-day forecast × 2.49, carried forward; ahead/behind against expected revenue by day d |
| `update_rule` | Installed before 7 Oct | **Not from the LTV model:** revenue to date + last 30 days × (r + r² + …) over the blocks left until day 365; nothing more if unseen for 30+ days |
| `cold_start` | Fewer than 3 days of data | n/a: first forecast on day 3 |

**Update rule, worked example** (player 33840 on 4 Nov): 162 days old, revenue to date $2,366.73, spent $239.29 in the last 30 days, last seen 9 days ago. Days left to day 365: 202 = 6.7 blocks of 30. Each block is worth 0.6 × the one before: $143.57 + $86.14 + $51.69 + $31.01 + $18.61 + $11.16 + 0.7 × $6.70 = **$347.10** still to come. LTV365 = $2,366.73 + $347.10 = **$2,713.83**. A player not seen for 30+ days (e.g. 39593, 121 days) gets nothing more: LTV365 = revenue to date ($1,013.26). Players who spent nothing in the last 30 days also get nothing more.

Update-rule backtest (next 30 days, predicted ÷ actual): 0.79 (1 Aug), 0.64 (1 Sep), 1.35 (1 Oct).

Fields: score date, feature date, player, install date, age, source, eligibility, revenue to date, 30-day forecast, multiplier, LTV365 and its range, confidence, expected by today, gap to forecast, days since last seen, reasons 1–3, model version, created at. Key (score date, player, model version): reruns replace.

Commands: `python -m sciplay.ltv.train select`, then `... train finalize`; `python -m sciplay.ltv.score --date 2026-11-04`
(or `--from … --to …`); or everything with `python -m sciplay.run_all`. Fixed seeds and deterministic LightGBM; model
version = hash of model, features, settings and the training players.

## 14. Model risk

| | What goes wrong | Cost |
|---|---|---|
| Overprediction | Offers and VIP care go to players who will not pay; inflated value at risk | Wasted acquisition and bonus spend, wrong list order |
| Underprediction | Early big spenders treated as average | Lost revenue from the players who matter most (top 3 = 86% of revenue) |

Not symmetric: missing a big spender costs more. Keep the forecast unbiased for totals; lean generous in decisions (e.g. use the upper end of the range to decide who gets attention — Parts 4–5). Report dollar recall, payer recall and underprediction share.

**Limits:**

- 100 installs a month: rates carry over, totals do not.
- 16 labelled payers, 6 in test; the top 2 players hold 81% of revenue.
- 169 days of data, so day 365 rests on the assumed × 2.49.
- The newest labels may still be rewritten; May–Nov only; eligibility flags never set; gross revenue only.

**Monitoring** (thresholds are proposals):

| Check | What | Alert |
|---|---|---|
| Calibration | Matured 30-day actual ÷ forecast, by cohort, source, platform, confidence, weekly | Outside 0.8–1.25 two weeks running |
| Drift | PSI of the top features; share paying by day 3; source / country mix; average forecast | PSI > 0.2 |
| Coverage | Share of eligible players scored; cold-start share | Under 99% |
| Freshness | Latest data date; model age | Retrain after ~2 months |

Monthly champion / challenger retraining as new 30-day cohorts mature; a challenger must not lower dollar recall.
