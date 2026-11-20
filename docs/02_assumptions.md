# Assumptions

Every material assumption, the evidence behind it and what would confirm it in production.

| # | Assumption | Current evidence | Evidence needed in production | Impact if wrong |
|---|---|---|---|---|
| A1 | A row exists only on days the player was active | 99.9% rows have sessions > 0; login gap matches row gap | Data dictionary / pipeline spec for the daily table | Engagement metrics and as-of logic |
| A2 | `REVENUE` is gross USD for that day; null = no purchase | Non-negative, null 97%, small typical values | Finance definition, currency field | LTV unit and totals |
| A3 | `LIFETIME_REVENUE` is as of start of day (excludes today's `REVENUE`) | Today's revenue appears in next row's lifetime value 83% of the time | Pipeline refresh-time documentation | Double counting, LTV-to-date |
| A4 | `D365_SPEND` is lifetime-to-date spend, not a mature label | Equal to `LIFETIME_REVENUE`; null for non-payers; max age 169 days | Label table definition | Whether a supervised 365-day model is possible |
| A5 | Multi-platform rows for the same player-day can be summed for flows and maxed for lifetime fields | Only 7 cases; lifetime fields equal across platform rows | Confirm lifetime fields are platform-agnostic | Player-level totals |
| A6 | Features dated D are available for scoring at end of day D | `LAST_UPDATE_DATETIME` usually D+1 | Actual load SLA | As-of policy, leakage |
| A7 | Sample is stratified 100 installs per month | Exact counts per cohort | Sampling spec from SciPlay | Totals and pay-rate estimates are not population figures |

_Add new rows as they come up._
