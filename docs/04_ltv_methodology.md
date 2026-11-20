# LTV methodology

## Definition
**LTV365** = expected cumulative gross revenue (USD) from install through day 365, scored as of a daily player snapshot.
LTV365 = observed revenue to date + expected revenue from the score date to day 365.

## Target validation
_Results of testing `D365_SPEND`: availability, population, stability across snapshots, relation to lifetime revenue, censoring._

## Baseline
_Cohort cumulative-revenue curve by age, extrapolated to day 365._

## Model
_Two-part model (P(pay) × E[spend | pay]) on an observable forward horizon, combined with a retention decay to day 365._

## Validation design
_Time cutoff, player-grouped, by install cohort. Metrics: MAE, total predicted / actual, calibration by decile, segment performance._

## Handling of non-payers, censoring, skew, sparse labels, cold start
_TBD_

## Output fields
prediction_date, feature_date, predicted_ltv_365, confidence, model_version, eligibility_status, reason_codes

## Model risk and monitoring
_Cost of over / under prediction; calibration, drift, coverage, freshness monitoring._

## Production target spec
_Target table, maturity window, history required._
