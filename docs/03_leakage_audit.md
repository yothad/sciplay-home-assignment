# Leakage audit

**As-of policy:** a score for `score_date = D` may only use rows with `DATE <= D` and fields known by end of day D.
Fields that describe the future relative to the row date, or are only complete after a maturity window, are excluded from features.

| Column | Suspicion | Evidence | Decision |
|---|---|---|---|
| `D365_SPEND` | Name implies a 365-day outcome | = `LIFETIME_REVENUE`; null for non-payers | Excluded as feature **and** as label |
| `NEXT_LOGIN_DATE` | Future date | Always > `DATE`; equals next row date 99.6% | Excluded |
| `DAYS_UNTIL_NEXT_PURCHASE` | Looks forward | 100 populated rows | Excluded |
| `D30_SPEND` | Fixed-window target-like | Changes after day 30 | Excluded until semantics confirmed |
| `*_RETURNER` (D1…D90) | Requires observing a future return | Flags relative to install | _To verify availability by age_ |
| `CHURNERS*` | Churn defined with future inactivity | Constant in sample | Excluded |
| `REACTIVATION_*_DATE` | Depends on future activity | | _To verify_ |
| `CREATE_DATETIME`, `LAST_UPDATE_DATETIME` | Processing metadata | After `DATE`; restatements | Used only for freshness / late-data checks |

_To be completed with the full column registry._
