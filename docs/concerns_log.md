# Concerns log

| # | Concern | Evidence | Possible impact | Current mitigation | Next validation step |
|---|---|---|---|---|---|
| C1 | No mature 365-day label | Oldest player 169 days; `D365_SPEND` = lifetime spend so far | Any LTV365 is an extrapolation | Proxy: revenue to date + modelled remaining revenue, clearly labelled, with uncertainty | Label table from installs at least 365 days old |
| C2 | Very few payers | 23 of 700 players | Unstable spend estimates | Simple, regularised models; pooled curves; confidence shown | Full population or more history |
| C3 | Forward-looking columns next to features | `D<n>_RETURNER` = played n days after D; rows rewritten for 91 days | Inflated offline accuracy | As-of policy + registry exclusions, enforced in code and tests | Confirm column definitions with data engineering |
| C4 | Daily and lifetime revenue offset by a day | 90% next-row match | Revenue to date off by a day | Revenue to date = `LIFETIME_REVENUE` + `REVENUE` | Confirm refresh timing |
| C5 | Exclusion policy untestable | Cheater and settlement flags never set | Actions on ineligible players | Filter built and unit-tested on synthetic flags | Test on data with flagged players |
| C6 | Stratified sample | 100 installs per month | Totals ≠ population | Report rates; label totals as sample totals | Sampling weights from SciPlay |
| C7 | Rolling columns used as given | Window end not documented (A9) | Small leakage risk | Accepted by decision | Confirm with data engineering |
