# Concerns log

| # | Concern | Evidence | Possible impact | Current mitigation | Next validation step |
|---|---|---|---|---|---|
| C1 | No mature 365-day label | Max age 169 days; `D365_SPEND` = lifetime-to-date | Any LTV365 is an extrapolation | Proxy model, clearly labeled; uncertainty shown | Build label table from installs ≥ 365 days old |
| C2 | Very few payers (~23) | Payer counts | Unstable spend estimates, wide uncertainty | Simple, regularized models; pooled curves | Larger sample / full population |
| C3 | Late-arriving / restated data | May–Jun rows updated 2026-09-03 | Non-reproducible historical scores | Snapshot inputs per run; freshness check | Confirm restatement policy with data eng |
| C4 | Revenue fields offset by one day | 83% next-row match | Double counting LTV-to-date | Use `LIFETIME_REVENUE` + same-day `REVENUE` explicitly | Confirm refresh timing |
| C5 | Cheater / settlement policy untestable | All flags "no" | Actions on ineligible players in production | Filter implemented anyway | Test on data with flagged players |
| C6 | Stratified sample | 100 installs per month | Totals ≠ population | Report rates, not totals, where possible | Get sampling weights |
