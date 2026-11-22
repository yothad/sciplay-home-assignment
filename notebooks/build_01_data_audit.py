"""Build notebooks/01_data_audit.ipynb from code (keeps the notebook diff-friendly).

Run:  uv run python notebooks/build_01_data_audit.py
Then: uv run jupyter nbconvert --to notebook --execute --inplace notebooks/01_data_audit.ipynb
"""

from pathlib import Path

import nbformat as nbf

md = nbf.v4.new_markdown_cell
code = nbf.v4.new_code_cell

cells = [
    md(
        "# Part 1 · Data understanding\n\n"
        "Audit of `sample_data.csv`: what a row is, what the data covers, what every column is and when it is known, "
        "the as-of policy and leakage audit, and the data issues that would change a business decision.\n\n"
        "All logic lives in `src/sciplay/` (`audit.py`, `registry.py`, `asof.py`); this notebook only calls it. "
        "Nothing is cleaned here: it describes the raw file.\n\n"
        "**Contents**\n"
        "1. Source grain and duplicate keys\n"
        "2. Coverage: dates, players, cohorts\n"
        "3. Field groups, missing values and inconsistent semantics\n"
        "4. Column registry: identifiers, dimensions, measures, derived features, targets, excluded\n"
        "5. As-of policy, with examples\n"
        "6. Leakage audit, with examples\n"
        "7. Late data, multiple platforms, sparse fields\n"
        "8. Data quality issues\n"
        "9. Definitions\n"
        "10. Summary"
    ),
    code(
        "import pandas as pd\n"
        "import plotly.io as pio\n"
        "from IPython.display import display\n\n"
        "from sciplay.audit import checks as audit\n"
        "from sciplay.data import asof, registry\n"
        "from sciplay.viz import charts as pc\n"
        "from sciplay.config import REPO_ROOT, get_settings\n"
        "from sciplay.data.loader import load_raw\n\n"
        "pio.renderers.default = 'plotly_mimetype+notebook_connected'\n"
        "pd.set_option('display.max_colwidth', 200)\n"
        "pd.set_option('display.width', 200)\n\n"
        "df = load_raw(get_settings().raw_data_path)\n"
        "profile = audit.column_profile(df)\n"
        "reg = registry.build_registry(df, profile)\n"
        "players = audit.player_summary(df)\n"
        "audit.dataset_overview(df)"
    ),
    # ------------------------------------------------------------------ 1 grain
    md(
        "## 1. Source grain and duplicate keys\n\n"
        "A key is valid when no two rows share it."
    ),
    code("audit.duplicate_keys(df)"),
    code(
        "ev = audit.grain_evidence(df)\n"
        "pd.DataFrame({\n"
        "    'check': ['Rows with SESSIONS > 0', 'DAYS_SINCE_LAST_LOGIN equals the gap to the previous row'],\n"
        "    'share': [ev.rows_with_sessions_share, ev.login_gap_matches_row_gap_share],\n"
        "}).style.format({'share': '{:.1%}'})"
    ),
    code("audit.multi_platform_player_days(df)"),
    md(
        "**Finding: aggregated data. One row = player × platform × day on which the player was active.**\n\n"
        "- `DATE + PLAYER_ID + PLATFORM_ID` is unique; no fully duplicated rows.\n"
        "- 7 player-days (3 players) have two platform rows. Lifetime fields are identical across them; daily activity "
        "is split. **Decision:** roll up to one row per player per day (sum daily measures, take lifetime fields once).\n"
        "- Almost every row has sessions and the login gap equals the gap between rows: **a missing row means the "
        "player did not play that day**, not missing data.\n"
        "- A player appears once per active day (up to 116 rows), so model validation must group rows by player."
    ),
    # ------------------------------------------------------------------ 2 coverage
    md("## 2. Coverage: dates, players, cohorts"),
    code(
        "daily = audit.daily_coverage(df)\n"
        "print(f\"{daily.index.min().date()} to {daily.index.max().date()}: {len(daily)} days, \"\n"
        "      f\"{int(daily['missing_date'].sum())} without rows\")\n"
        "pc.daily_coverage(daily).show()"
    ),
    code("pc.active_by_cohort(audit.active_players_by_cohort(df)).show()"),
    code(
        "cohorts = audit.cohort_coverage(players, df['DATE'].max())\n"
        "cohorts.style.format({'payer_share': '{:.0%}', 'first_install': '{:%Y-%m-%d}', 'last_install': '{:%Y-%m-%d}'})"
    ),
    code("pc.rows_per_player(audit.rows_per_player_distribution(players)).show()"),
    code(
        "activity = audit.cohort_activity_matrix(df, df['DATE'].max())\n"
        "pc.cohort_activity_heatmap(activity, audit.AGE_LABELS).show()"
    ),
    md(
        "**Finding: a stratified install-cohort sample.**\n\n"
        "- 180 continuous days, 9 May – 4 Nov 2026. **Exactly 100 new players per month**, and 699 of 700 are first "
        "seen on install day.\n"
        "- November's 100 installs all fall in Nov 1–4 (26–32 a day against 2–8), so the last days are distorted. "
        "Daily actives grow only because a new cohort joins every month.\n"
        "- History is thin: 332 players (47%) were seen on a single day; the median is 2 rows.\n"
        "- Oldest player: 169 days. **Nobody reaches day 365.** Only 23 players (3%) ever paid.\n"
        "- About 30% of each cohort returns on day 1 and 13–16% are active at days 91–120; cohorts look alike."
    ),
    # ------------------------------------------------------------------ 3 fields
    md(
        "## 3. Field groups and missing values\n\n"
        "409 columns grouped by name (`src/sciplay/field_groups.py`). Hover a bar segment or a dot to see the columns."
    ),
    code("pc.field_groups_bar(profile).show()"),
    code("pc.missingness_strip(profile).show()"),
    code("audit.missingness_by_group(profile).style.format({'median_null_share': '{:.0%}'})"),
    md(
        "**Finding:** 85 of 409 columns carry no information (37 all null, 48 single value), including campaign and "
        "creative fields and the cheater and settlement flags. Most other nulls are **structural**, so three states "
        "are kept apart:\n\n"
        "| Null in… | Means | Example |\n"
        "|---|---|---|\n"
        "| a daily count | **zero**: no event that day | `REVENUE` empty = no purchase |\n"
        "| a last-event field | **not applicable**: never happened | `DAYS_SINCE_LAST_PURCHASE` empty = never paid |\n"
        "| a dimension | **unknown** | `REGION` empty |"
    ),
    md(
        "### Inconsistent semantics\n\n"
        "*Semantics* is what a field actually means, as opposed to what its name says. A field has **inconsistent "
        "semantics** when the data contradicts its name or its siblings: a \"365-day\" field that is really spend so far, "
        "a \"days\" count that is only 0 or 1, or one yes/no concept stored three different ways. Each case below is "
        "tested on the data, because the brief warns that field names are clues, not definitions."
    ),
    code("audit.inconsistent_semantics(df)"),
    # ------------------------------------------------------------------ 4 registry
    md(
        "## 4. Column registry\n\n"
        "Every column is placed in one of the six categories the brief asks to separate: **identifiers, dimensions, "
        "observed measures, derived features, targets, excluded**. Derived features and targets are not in the file; "
        "they are the columns we compute, so they are added as rows of their own.\n\n"
        "Each column also gets an **as-of availability** (when its value is known relative to the row date D), a "
        "**null meaning** and a **use**. Rules are name-based (`src/sciplay/registry.py`), then corrected by evidence "
        "from the data. The full table is saved to `docs/column_registry.csv`."
    ),
    code(
        "reg_cat = registry.with_categories(reg)\n"
        "registry.category_summary(reg_cat)"
    ),
    code("reg_cat.loc[reg_cat['source'] == 'computed', ['column', 'category', 'as_of', 'use', 'note']]"),
    code("reg_cat[reg_cat['category'] == 'Excluded'].groupby('use').size().rename('columns').reset_index()"),
    code("registry.usage_summary(reg)"),
    code(
        "reg_cat.to_csv(REPO_ROOT / 'docs' / 'column_registry.csv', index=False)\n"
        "with pd.option_context('display.max_rows', 500):\n"
        "    display(reg_cat.drop(columns=['rule']).style.format({'null_share': '{:.0%}'}, na_rep='–'))"
    ),
    # ------------------------------------------------------------------ 5 as-of
    md(
        "## 5. As-of policy\n\n"
        "**A score for day D (as of the end of D, UTC) uses only rows dated D or earlier, and only columns the "
        "registry marks as features.** The future may appear in the label, never in a feature.\n\n"
        "**Revenue to date** at the end of D = `LIFETIME_REVENUE` (start of D) + `REVENUE` (day D).\n\n"
        "The policy is code (`src/sciplay/asof.py`): `rows_as_of`, `snapshot_as_of`, `feature_columns` and "
        "`assert_as_of`, which fails if a feature frame holds a row after D or a column the registry excludes."
    ),
    md(
        "### Example A · an active player\n\n"
        "Player 289987 installed on 1 Oct. We score him for **D = 8 Oct**."
    ),
    code(
        "asof.player_timeline(df, 289987, '2026-10-08',\n"
        "                     ['DAYS_SINCE_INSTALL', 'SESSIONS', 'REVENUE', 'LIFETIME_REVENUE', 'D1_RETURNER', 'NEXT_LOGIN_DATE'])"
    ),
    md(
        "- **Used:** rows 1–8 Oct, including 8 Oct itself: 6 sessions and $8.84 spent that day.\n"
        "- **Used:** revenue to date = $50.80 (lifetime at the start of 8 Oct) + $8.84 = **$59.64**. The 9 Oct row "
        "confirms it: its start-of-day lifetime revenue is exactly $59.64.\n"
        "- **Not used:** the 9 Oct row and its $17.67 purchase. That is the future.\n"
        "- **Not used:** `D1_RETURNER = 1` and `NEXT_LOGIN_DATE = 9 Oct` on the 8 Oct row. Both describe 9 Oct, "
        "which nobody knows on the night of 8 Oct (section 6).\n"
        "- **Label (training only):** his revenue from 9 Oct to 7 Nov. The future is allowed here.\n\n"
        "**Missing target ≠ zero by default.** The brief warns against filling a missing target with 0. Here it is "
        "supported: a day without a row is a day without play (A1), and an empty `REVENUE` is a day without a purchase "
        "(A2, verified), so revenue in the label window is a true $0 for a player who did not pay. The label is only "
        "built for score dates whose 30-day window ends inside the data; later dates have *no* label, not a zero one. "
        "`D365_SPEND` being empty for non-payers is not used at all."
    ),
    md(
        "### Example B · an inactive player\n\n"
        "Player 160253's last row is 6 Sep. We score everyone for **D = 10 Sep**."
    ),
    code(
        "player_day = asof.rollup_player_day(df, reg)\n"
        "snap = asof.snapshot_as_of(player_day, '2026-09-10')\n"
        "cols = ['score_date', 'PLAYER_ID', 'last_seen', 'days_since_last_seen', 'active_on_score_date',\n"
        "        'revenue_to_date', 'age_days']\n"
        "snap.loc[snap['PLAYER_ID'] == 160253, cols]"
    ),
    code(
        "print(f\"Players known by 10 Sep: {len(snap)}; with a row on 10 Sep: {int(snap['active_on_score_date'].sum())}\")"
    ),
    md(
        "He has no row on 10 Sep, so the as-of snapshot carries his 6 Sep row forward: $84.48 revenue to date, "
        "4 days since last seen. Without this, only the 30 players who played that day would be scored, and the "
        "players drifting away, the ones the lists are for, would disappear."
    ),
    md("### The policy as a check"),
    code(
        "allowed = asof.feature_columns(reg)\n"
        "ok = player_day.loc[player_day['DATE'] <= '2026-10-08', ['DATE', 'PLAYER_ID'] + allowed[:5]]\n"
        "asof.assert_as_of(ok, '2026-10-08', allowed)\n"
        "print(f'{len(allowed)} feature columns allowed; frame passes')\n\n"
        "try:\n"
        "    bad = player_day.loc[player_day['DATE'] <= '2026-10-08', ['DATE', 'PLAYER_ID', 'D1_RETURNER']]\n"
        "    asof.assert_as_of(bad, '2026-10-08', allowed)\n"
        "except ValueError as err:\n"
        "    print('Rejected:', err)"
    ),
    # ------------------------------------------------------------------ 6 leakage
    md(
        "## 6. Leakage audit\n\n"
        "A column leaks when its value on the row for day D depends on what happens after D. The registry marks each "
        "suspicious column and the decision; the evidence is below."
    ),
    md(
        "### Example: what `D1_RETURNER` really means\n\n"
        "The same player has different `D1_RETURNER` values on different rows, so it is not an install milestone. "
        "It is 1 exactly when the player has a row on the next day:"
    ),
    code("asof.returner_flag_example(df, 39593)"),
    md("Tested on every row and every horizon, `D<n>_RETURNER` = *the player played exactly n days after D*:"),
    code("registry.returner_label_evidence(df).style.format({'match_share': '{:.1%}'})"),
    code("registry.milestone_backfill_evidence(df).query('positive_before_age > 0')"),
    md("### Decisions"),
    code(
        "suspicious = reg[reg['use'].str.startswith('exclude: leak') | reg['use'].isin(\n"
        "    ['exclude: not a valid target', 'exclude until verified'])\n"
        "    | reg['column'].isin(['LIFETIME_REVENUE', 'LAST_4W_REVENUE', 'LAST_8W_REVENUE', 'LAST_12W_REVENUE',\n"
        "                          'DAYS_SINCE_LAST_LOGIN', 'DAYS_SINCE_LAST_PURCHASE', 'LT_PAYER_BIN',\n"
        "                          'TOTAL_SPEND_LAST_4W_SEGMENT'])]\n"
        "with pd.option_context('display.max_rows', 100):\n"
        "    display(suspicious[['column', 'as_of', 'use', 'evidence', 'note']].reset_index(drop=True))"
    ),
    md(
        "| Columns | Why suspicious | Decision |\n"
        "|---|---|---|\n"
        "| `D1`–`D90_RETURNER`, `D<n>`, `D<n>_CONVERTER`, `SPENDER_<n>` | Describe activity n days after D | **Excluded** (usable later as churn labels) |\n"
        "| `NEXT_LOGIN_DATE`, `DAYS_UNTIL_NEXT_PURCHASE`, `CHURNERS*` | Describe what happens after D | **Excluded** |\n"
        "| `D365_SPEND`, `D30_SPEND` | Lifetime spend so far, not a fixed window | **Excluded**, not a valid target |\n"
        "| `D7/D14/D30_ACTIVE/PURCHASE/SPINS_DAYS` | Window may run past D | **Excluded until verified** |\n"
        "| `LIFETIME_REVENUE` | Start-of-day value | **Kept**, plus same-day `REVENUE` |\n"
        "| `LAST_4W/8W/12W_*`, `DAYS_SINCE_*` | Rolling; window end not documented | **Kept**, used as given |\n"
        "| Spend segments (`LT_PAYER_BIN`, `TOTAL_SPEND_LAST_4W_SEGMENT`) | Built from spend | **Reporting only** |"
    ),
    # ------------------------------------------------------------------ 7 late / platforms / sparse
    md("## 7. Late data, multiple platforms, sparse fields"),
    code(
        "lag = audit.late_updates(df)\n"
        "pc.update_lag(audit.update_lag_rows(df)).show()\n"
        "lag.style.format({'share_over_7d': '{:.0%}'})"
    ),
    code(
        "span_days = (players['last_seen'] - players['install_date']).dt.days + 1\n"
        "pd.Series({\n"
        "    'Player-days with two platform rows': int(df.duplicated(['DATE', 'PLAYER_ID']).sum()),\n"
        "    'Days played / days between install and last seen': round(players['active_days'].sum() / span_days.sum(), 3),\n"
        "    'Rows with an empty REVENUE (no purchase)': round(df['REVENUE'].isna().mean(), 3),\n"
        "}, name='value').to_frame()"
    ),
    md(
        "| | What we see | Effect on calculations | Handling |\n"
        "|---|---|---|---|\n"
        "| **Late-arriving data** | Recent rows land ~2 days late; every row changes until 91 days after its date | Yesterday may be missing; forward-looking flags on recent rows keep changing | Score D only once its rows landed (freshness check); features only from as-of-safe columns; labels only after their window has passed |\n"
        "| **Multiple platforms** | 7 player-days with two rows | Counting rows double counts players and splits a day's play | One row per player per day; main platform + platform count |\n"
        "| **Sparse event fields** | No row on days off; `REVENUE` empty on 97% of rows | Days off look like missing data; averages over rows overstate activity; zeros dominate revenue | As-of snapshot carries players forward; empty daily count = 0, empty last-event = not applicable; two-part revenue model |"
    ),
    # ------------------------------------------------------------------ 8 quality
    md(
        "## 8. Data quality issues\n\n"
        "Six issues, grouped into four themes. Each could change a business decision if ignored."
    ),
    code("audit.quality_issues(df)"),
    code("pc.d365_vs_lifetime(df).show()"),
    code("pc.revenue_offset(df).show()"),
    md(
        "| Theme | Issues | Resolved by |\n"
        "|---|---|---|\n"
        "| Target validity | Q1 | Defining LTV365 ourselves (observed + modelled remaining revenue); `D365_SPEND` is never a label |\n"
        "| Revenue definition | Q2 | Revenue to date = `LIFETIME_REVENUE` (start of D) + `REVENUE` (day D) |\n"
        "| Time integrity | Q3, Q5 | The as-of policy and registry (sections 5–6). Training and testing are safe; auditing past lists relies on the stored daily list history |\n"
        "| Sample limitations | Q4, Q6 | Rates instead of totals; uncertainty shown on LTV; the eligibility filter is built and unit-tested on synthetic flags |"
    ),
    # ------------------------------------------------------------------ definitions
    md("## 9. Definitions"),
    code(
        "components = ['BUY_COINS_REVENUE', 'HOT_OFFER_REVENUE', 'OOC_REVENUE']\n"
        "check = (df[components].fillna(0).sum(axis=1) - df['REVENUE'].fillna(0)).abs().lt(0.01).mean()\n"
        "print(f'REVENUE equals coin packs + hot offers + out-of-coins offers on {check:.0%} of rows')\n"
        "print(f\"Net revenue exists only for direct-to-consumer purchases: \"\n"
        "      f\"${df['DTC_NET_FEE_REVENUE'].sum():,.2f} net of ${df['DTC_REVENUE'].sum():,.2f} gross\")"
    ),
    md(
        "| Term | Unit | Business meaning | Calculation |\n"
        "|---|---|---|---|\n"
        "| **Revenue** | Gross USD per player per day | In-app purchases that day, before store fees and refunds; no ad revenue in the data | `REVENUE` = coin packs + hot offers + out-of-coins offers; empty = $0 |\n"
        "| **Revenue to date** | USD per player | Everything paid since install, up to the end of D | `LIFETIME_REVENUE` (start of D) + `REVENUE` (day D) |\n"
        "| **LTV365** | USD per player | Expected gross revenue in the first year after install | Revenue to date + modelled revenue up to day 365; cohort LTV = average |\n"
        "| **Active player** | Player on a day | Played that day | Has a row with sessions on D; DAU = count of active players |\n"
        "| **Payer** | Player | Ever-payer: paid at least once. Recent payer: paid in the last 4 weeks | Revenue to date > 0; `LAST_4W_REVENUE` > 0 |\n"
        "| **Underperformance** | Player on score date D | Clearly less play or spend than expected, for a reason a team can act on | One list per player, in this order, ranked by value at risk |\n\n"
        "**The three lists**\n\n"
        "1. **Friction:** technical problems in the last 7 days: failed purchase or store verification, crash, "
        "unhandled error, support ticket. Cancelled purchases are *not* friction (mostly players browsing the store: "
        "114 players, few of them payers); they appear as a supporting reason on the other lists.\n"
        "2. **Revenue decline:** a payer whose last 4 weeks' spend is at least 50% below the 4 weeks before "
        "(`LAST_4W_REVENUE` vs `LAST_8W_REVENUE` − `LAST_4W_REVENUE`), or who is well past their usual purchase gap.\n"
        "3. **Engagement decline:** plays well below their own 28-day pace "
        "(`PLATFORM_AGNOSTIC_LAST_7_DAYS_PLAYED` vs `..._LAST_28_...` ÷ 4) or the median player of the same age, "
        "or is well past their usual gap.\n\n"
        "**Eligibility:** not a cheater or legal settlement, at least 3 days since install, seen in the last 30 days. "
        "**Value at risk** = predicted LTV365 − revenue to date (USD). Thresholds live in a config file and are tuned on list sizes."
    ),
    # ------------------------------------------------------------------ summary
    md(
        "## 10. Summary\n\n"
        "| Topic | Finding | What it means for the next steps |\n"
        "|---|---|---|\n"
        "| Grain | Player × platform × active day, aggregated | Roll up to player-day; as-of snapshot for scoring |\n"
        "| Coverage | 180 days; 700 players, 100 new per month; 23 payers; max age 169 days | No mature 365-day outcome; few payers; sample totals |\n"
        "| Columns | Six categories; 255 candidate features, 39 excluded for leakage or target, 80 with no information | Registry drives feature selection |\n"
        "| Semantics | 8 fields whose meaning differs from their name | Tested, not assumed; decisions recorded |\n"
        "| As-of policy | Rows ≤ D, columns known by end of D | Enforced in code with `assert_as_of` |\n"
        "| Leakage | D-returner flags = activity n days after D | Excluded; usable later as churn labels |\n"
        "| Leakage (found in Part 3) | I14/I30_REVENUE show purchases not made yet; I3/I7 duplicate our own sums | Excluded; I3/I7 kept as a check |\n"
        "| Quality | Four themes | LTV365 is a defined proxy; time integrity by policy; sample limits stated |"
    ),
]

nb = nbf.v4.new_notebook()
nb["cells"] = cells
nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
out = Path(__file__).with_name("01_data_audit.ipynb")
nbf.write(nb, out)
print(f"wrote {out}")
