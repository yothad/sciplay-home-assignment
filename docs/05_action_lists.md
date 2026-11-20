# Daily underperforming player lists

## Lists
| Primary list | Business meaning | Owner |
|---|---|---|
| Payment / engagement friction | Player blocked by technical or purchase problems | _TBD_ |
| Revenue decline | Payer or valuable player generating less value than expected | _TBD_ |
| Engagement decline | Player losing activity, may churn before expected value is realized | _TBD_ |

## Eligibility
_Exclusions: cheaters, legal settlement, cold start, inactive beyond N days, etc._

## Precedence rule
_Proposed: friction > revenue decline > engagement decline. Rationale and tests._

## Baselines and thresholds
_Own prior behavior, peer cohort, expected trajectory. Thresholds in config._

## Output contract
score_date, player_id, list_type, priority, underperformance_score, predicted_ltv_365, ltv_to_date, opportunity_gap, reason_codes, recommended_action, model_rules_version, created_at

## Persistence and idempotency
_SQLite, primary key (score_date, player_id, model_rules_version)._

## Worked example
_One player who changes status or priority between two dates._
