# Concerns log

| # | Concern | Evidence | Possible impact | Current mitigation | Next validation step |
|---|---|---|---|---|---|
| C1 | No mature 365-day label | Oldest player 169 days; `D365_SPEND` = lifetime spend so far | Any LTV365 is an extrapolation | Proxy: validated 30-day forecast × 2.49 (assumed fade), labelled, with a range | Label table from installs at least 365 + 91 days old (maturity slide) |
| C2 | Very few payers | 23 of 700 players | Unstable spend estimates | Simple, regularised models; pooled curves; confidence shown | Full population or more history |
| C3 | Forward-looking columns next to features | `D<n>_RETURNER` = played n days after D; rows rewritten for 91 days | Inflated offline accuracy | As-of policy + registry exclusions, enforced in code and tests | Confirm column definitions with data engineering |
| C4 | Daily and lifetime revenue offset by a day | 90% next-row match | Revenue to date off by a day | Revenue to date = `LIFETIME_REVENUE` + `REVENUE` | Confirm refresh timing |
| C5 | Exclusion policy untestable | Cheater and settlement flags never set | Actions on ineligible players | Filter built and unit-tested on synthetic flags | Test on data with flagged players |
| C6 | Stratified sample | 100 installs per month | Totals ≠ population | Report rates; label totals as sample totals | Sampling weights from SciPlay |
| C7 | Rolling columns used as given | Window end not documented (A9) | Small leakage risk | Accepted by decision | Confirm with data engineering |
| C8 | Install-window revenue columns leak | `I14/I30_REVENUE` on install-day rows show purchases made later (player 8520) | Inflated accuracy if used as features | Excluded; `I3/I7` used only as a consistency check | Confirm how install-window columns are filled |
| C9 | Six paying test players | 218 test players, 6 payers | Test metrics are directional; model choice within noise | Bootstrap ranges; tie rule; benchmark comparison | Re-test with more matured cohorts |
| C10 | Day-365 multiplier is an assumption | Month-to-month ratios come from two players | LTV365 level may be off by a factor | × 2.49 stated everywhere; sensitivity × 2.00–3.29 | Replace with a model on 90/365-day labels |
| C11 | Device and performance features learned noise | First run: "slower loading → higher value"; did not hold | Misleading reason codes | Removed from LTV features (domain decision); kept for the friction list | Revisit with more payers |
