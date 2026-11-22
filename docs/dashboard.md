# Part 2 · Dashboard

A local Streamlit app for a manager: current performance, trends, and who needs attention. It reads only the prepared tables; no number in it is hard-coded.

## Run

```bash
uv run python -m sciplay.pipeline.refresh          # take in new extracts, rebuild, check, publish
uv run streamlit run app/Overview.py               # opens http://localhost:8501
```

The app opens on 4 Nov, the last data day: every player installed up to 2 Nov has a day-3 LTV forecast by then.

## Prepared data

| Table | Grain | Built from |
|---|---|---|
| `player_day.parquet` | One row per player per day played (platforms rolled up) | Raw CSV + Part 1 rollup |
| `daily_metrics.parquet` | One row per calendar day, all players | `player_day` |
| `cohort_activity.parquet` | Install month × age bucket | `player_day` |
| `cohort_revenue.parquet` | Install month × age in days | `player_day` |
| `manifest.json` | Build metadata: source, row counts, data end, build time | – |

## Pages

| Page | Question | Content |
|---|---|---|
| Overview | How did we do on the score date? | Seven KPI tiles against the previous 7-day average; player base on the score date (players so far, seen in the last 30 days, churned, revenue to date); lifetime value (Part 3): LTV365 from the day-3 model and from the update rule shown separately, players per source, players too new to forecast; last 8 weeks of active players, new players and revenue; the score date split by platform, install month, payer status, region, country and acquisition type |
| Trends | Better or worse? | Each KPI as a 7-day average or weekly bars; weekly table |
| Cohorts | Are newer players as good as older ones? | Activity by age heatmap; cumulative revenue per install by age; cohort summary; payers by first-purchase month and their revenue since first purchase |
| Who needs attention | Who should someone act on today? | Placeholder until Parts 3–4: list sizes and value at risk shown as *not yet available* |
| Player detail | Why is this player where they are? | As-of snapshot tiles and the days-played timeline; lifetime value panel: source (day-3 model / update rule, not from the model / too new), LTV365 and range, confidence, ahead or behind forecast, the calculation and up to 3 reasons |
| Data health | Is the data for the selected date complete and normal? | 20 checks of the date against the 28 days before it (freshness, volume, missing values, new categories, validity, duplicates); player-days against their normal range; reconciliation; LTV model check (test results with ranges, value bands, by install month, by confidence, selection on training folds, monitoring plan); value-state legend |

Filters (sidebar): score date, platform, install month, country, acquisition type, payer status (as of each day).

## Metrics

| KPI | Definition |
|---|---|
| Active players | Players with a row (sessions) on the day |
| New players | Players on their install day |
| Paying players | Active players with revenue that day |
| Revenue | Gross in-app revenue that day, USD |
| Revenue per active player | Revenue / active players (ARPDAU) |
| Revenue per paying player | Revenue / paying players (ARPPU); n/a on a day without payers |
| Payer rate | Paying players / active players |

Smoothed and weekly ratios are recomputed from summed numerators and denominators, never averaged.

## Zero, missing, not yet available, not applicable

| State | Meaning | Shown as |
|---|---|---|
| Zero | Measured, and it was 0 | `0` / `$0.00` |
| Missing | Should exist but is not in the data | `— missing` (grey) |
| Not yet available | Cannot be known yet: a cohort too young, or a value built in a later part | *not yet available* (purple, italic) |
| Not applicable | Does not apply | *n/a* (grey, italic) |

A **player-day** is one player who played on one day, after combining that player's platforms; it is one row of the prepared table.

Examples: a day with no players has 0 active players but *n/a* revenue per active player; days since last purchase is *n/a* for a non-payer; revenue per install at day 90 is *not yet available* for a cohort younger than 90 days.

## Reconciliation

The Data health page and `tests/test_dashboard.py` compare dashboard numbers (pandas over the prepared tables) with the same numbers computed independently by DuckDB SQL over the raw rows the build used (`raw_input.parquet`):

- the selected date's Overview tiles: active players, new players, paying players, revenue;
- the whole period: active player-days, distinct players, total revenue, paying player-days, new players, and the raw-row to player-day rollup.

All pass on the sample. The banner's "100 new players per install month" is computed from the data, not typed in.

## Refreshing with new data

```bash
# put new extracts in data/raw/incoming/, then:
uv run python -m sciplay.pipeline.refresh
```

| Step | What happens |
|---|---|
| Intake | New CSVs move from `data/raw/incoming/` into `data/raw/extracts/` with a timestamp (the first run archives the configured raw file) |
| Merge | All extracts combined; for each date, player and platform the version with the latest `LAST_UPDATE_DATETIME` wins, so a file can hold only new days and restated rows are applied |
| Build | The prepare step writes all tables to a staging folder |
| Gate | Health checks on the newest date; any failed check, or no newer date, stops the run and the dashboard keeps yesterday's tables |
| Publish | Staged files replace the published ones; the app reloads on the next browser refresh |
| Log | Every run appended to `data/store/refresh_log.jsonl` |

Exit codes: 0 published, 1 blocked by the gate, 2 no new data, 3 no input. Tested in `tests/test_refresh.py`. In production the same steps would run as a scheduled job in a data orchestration pipeline (for example Airflow or Dagster) with storage in the cloud.

## Data health checks

For the selected date, against the 28 days before it:

| Area | Checks |
|---|---|
| Freshness | Rows have landed for the date and the day before; how long the date's rows may still change (91 days, Part 1 Q3) |
| Volume | Player-days, new players and paying players against their 28-day average (warn beyond ±3 standard deviations) |
| Missing values | Share of empty country, region, device, acquisition type, sessions and lifetime revenue (warn if more than 10 points worse) |
| Consistency | Platform, country or acquisition values never seen before; players on two platforms |
| Validity | Negative revenue, rows without sessions, revenue to date going down, duplicate keys |

Example: 2 Nov warns on player-days (+5.7 sd) and new players (+3.9 sd), the November cohort arriving, and on a first-time country (Sweden).
