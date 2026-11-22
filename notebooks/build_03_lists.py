"""Build notebooks/03_lists.ipynb from code (keeps the notebook diff-friendly).

Run:  uv run python notebooks/build_03_lists.py
Then: uv run jupyter nbconvert --to notebook --execute --inplace notebooks/03_lists.ipynb
"""

from pathlib import Path

import nbformat as nbf

md = nbf.v4.new_markdown_cell
code = nbf.v4.new_code_cell

cells = [
    md(
        "# Part 4 · Daily underperforming player lists\n\n"
        "Every eligible player is checked as of a score date; one primary list per player by precedence: "
        "**Technical or payment friction → Revenue decline → Engagement decline**. Logic lives in `src/sciplay/lists/`.\n\n"
        "This first part sets the thresholds and priority tiers. **All thresholds are starting values** in "
        "`src/sciplay/lists/config.py` and can be tuned.\n\n"
        "**Contents**\n"
        "1. Eligibility over time\n"
        "2. Signals on one date, before precedence\n"
        "3. Threshold sweep: list sizes and stability\n"
        "4. Backtest: do the signals point at players who then play or spend less?\n"
        "5. Opportunity gap and priority tiers\n"
        "6. The daily flow and output contract\n"
        "7. Two dates: 29 Oct and 4 Nov\n"
        "8. One player who changes list and priority\n"
        "9. History: entry, exit, duration"
    ),
    code(
        "import pandas as pd\n"
        "import plotly.graph_objects as go\n"
        "import plotly.io as pio\n"
        "from IPython.display import display\n\n"
        "from sciplay.lists import analysis as A, config as L\n"
        "from sciplay.ltv import train as T\n\n"
        "pio.renderers.default = 'plotly_mimetype+notebook_connected'\n"
        "pd.set_option('display.width', 200)\n"
        "data = T.load_data()\n"
        "dates = pd.date_range('2026-10-09', '2026-11-04')          # days with LTV scores\n"
        "runs = A.run_dates(data, dates)\n"
        "print(f'{len(dates)} score dates, {dates[0]:%d %b} – {dates[-1]:%d %b}')"
    ),
    md(
        "## 1. Eligibility over time\n\n"
        "Eligible = not a cheater or legal settlement, at least 3 days old, seen in the last 30 days (Part 1)."
    ),
    code(
        "sz = A.sizes(runs)\n"
        "fig = go.Figure()\n"
        "for name, color in zip(L.PRECEDENCE, ['#E8664A', '#6B3FA0', '#3A86C8']):\n"
        "    fig.add_bar(x=sz['date'], y=sz[name], name=name, marker_color=color)\n"
        "fig.update_layout(barmode='stack', title='Players on each list per day (one primary list each)', template='plotly_white',\n"
        "                  height=380, legend=dict(orientation='h', y=-0.2))\n"
        "fig.show()\n"
        "sz.describe().loc[['mean', 'min', 'max']].round(1)"
    ),
    md("## 2. Signals on one date, before precedence\n\nHow many eligible players trigger each list on 4 Nov, and how much the lists overlap."),
    code(
        "s = runs[pd.Timestamp('2026-11-04')]\n"
        "e = s[s.eligible]\n"
        "print('Eligible:', len(e), '| ineligible:', s.loc[~s.eligible, 'ineligible_reason'].value_counts().to_dict())\n"
        "display(pd.DataFrame({'friction': e.any_friction, 'revenue': e.any_revenue, 'engagement': e.any_engagement})\n"
        "        .value_counts().rename('players').to_frame())\n"
        "print('Valuable:', e.valuable.replace('', 'not valuable').value_counts().to_dict())"
    ),
    md(
        "## 3. Threshold sweep: list sizes and stability\n\n"
        "Each threshold varied on its own, all other values at their defaults, over the 27 dates. "
        "*New on list vs previous day* = share of a day's listed players who were not listed the day before "
        "(lower = more stable lists)."
    ),
    code(
        "grid = {'ACTIVITY_DROP': [0.3, 0.4, 0.5, 0.6, 0.7], 'SPEND_DROP': [0.3, 0.5, 0.7],\n"
        "        'RECENT_DAYS': [7, 14], 'OVERDUE_FACTOR': [1.5, 2.0, 3.0]}\n"
        "A.sweep(data, dates, grid)"
    ),
    md(
        "Read with the backtest below: a looser threshold mostly adds players to the engagement list (part of that list comes from the return signal: away 7–21 days, longer than usual for the player); the friction and "
        "revenue lists are small at any setting because few players have friction events or have ever paid."
    ),
    md(
        "## 4. Backtest: do the signals point at players who then play or spend less?\n\n"
        "At weekly dates from 1 Aug to 5 Oct (the next 30 days are fully in the data), compare flagged with not-flagged "
        "**comparable** eligible players: share who **stopped playing** (no day played in the next 30), days played in the "
        "next 30, and payers' spend in the next 30 days ÷ their last 28. Comparable = had a meaningful baseline for that "
        "signal: engagement — played at least weekly before (or young with active peers); friction — played 3+ of the last "
        "7 days (heavy players crash more simply because they play more); revenue — payers and high-predicted-value "
        "players. Each signal on its own (before precedence). Small numbers: directional."
    ),
    code("A.backtest(data, pd.date_range('2026-08-01', '2026-10-05', freq='7D'))"),
    md("## 5. Opportunity gap and priority tiers\n\n"
       "Opportunity gap = expected value at the player's baseline − revised value now, never below $0 "
       "(older players: update-rule LTV at the previous vs the recent spending pace; model players: dollars behind "
       "forecast × 2.49). Distribution over all listed player-days:"),
    code(
        "g = A.gap_distribution(runs)\n"
        "display(g.groupby('list_type').opportunity_gap.describe(percentiles=[.5, .75, .9]).round(2))\n"
        "for hi, mid in [(10, 1), (20, 2), (50, 5)]:\n"
        "    print(f'high >= ${hi}, medium >= ${mid}:', (g.opportunity_gap >= hi).mean().round(2), 'high,',\n"
        "          ((g.opportunity_gap >= mid) & (g.opportunity_gap < hi)).mean().round(2), 'medium')"
    ),    md(
        "**Decision (b): dollars first, severity second.** High = opportunity gap ≥ $20; Medium = gap ≥ $2, or money "
        "directly blocked (failed or incomplete purchases), or a severe decline (score ≥ 75); Low otherwise. Dollar tiers "
        "alone would make every friction and engagement player low, every day: they are non-payers with no dollar gap."
    ),
    # ------------------------------------------------------------------ 6
    md(
        "## 6. The daily flow and output contract\n\n"
        "`python -m sciplay.lists.run --date 2026-11-04` (or `--from … --to …`):\n"
        "1. **No rows for the date** (after the data end): nothing listed, the run is logged as `no_data`.\n"
        "2. **Health check for the date fails** (late or incomplete rows): the list is still written, flagged `data_incomplete`.\n"
        "3. LTV scores for the date are read, or computed and stored if missing.\n"
        "4. Signals as of the date (rows dated on or before it only), one primary list by precedence, score, priority, "
        "reasons, action.\n"
        "5. Stored in SQLite `daily_lists`, key (score date, player, model + rules version): a rerun replaces rows; "
        "`list_runs` logs status, list sizes and ineligible players by reason.\n\n"
        "**Underperformance score (0–100):** 0 = at the player's baseline; 100 = spend or play stopped, or severe friction. "
        "Friction: 25 points per event in the last 7 days. Revenue: the largest of spend drop %, overdue, % behind forecast, "
        "activity drop % for high-value non-payers. Engagement: the largest drop in days played or sessions, or time away."
    ),
    code(
        "from sciplay.lists import history as H, run as R\n"
        "runs_log = R.read(None, table=R.RUNS)\n"
        "runs_log[['score_date', 'status', 'eligible', 'listed', 'list_sizes', 'ineligible']].tail(5)"
    ),
    # ------------------------------------------------------------------ 7
    md("## 7. Two dates: 29 Oct and 4 Nov"),
    code(
        "for D in ['2026-10-29', '2026-11-04']:\n"
        "    l = R.read(D)\n"
        "    print(D, '-', len(l), 'players listed')\n"
        "    display(l.groupby(['list_type', 'priority']).size().unstack(fill_value=0)\n"
        "            .reindex(L.PRECEDENCE).reindex(columns=['high', 'medium', 'low'], fill_value=0))\n"
        "R.read('2026-11-04')[['player_id', 'list_type', 'priority', 'underperformance_score', 'predicted_ltv_365',\n"
        "                     'ltv_to_date', 'opportunity_gap', 'reason_text', 'recommended_action']].head(10).round(2)"
    ),
    code("print('Changes on 4 Nov vs 3 Nov:')\nH.changes('2026-11-04')"),
    # ------------------------------------------------------------------ 8
    md(
        "## 8. One player who changes list and priority: player 224283\n\n"
        "Installed 7 Sep; one purchase of $14.46 on 19 Sep; played almost daily until 9 Oct, then nothing until 3 Nov; "
        "bought again ($14.46) on 4 Nov."
    ),
    code(
        "h = H.history()\n"
        "p = h[h.player_id == 224283][['score_date', 'list_type', 'priority', 'underperformance_score', 'opportunity_gap', 'reason_text']]\n"
        "p[p.score_date.isin(['2026-10-09', '2026-10-15', '2026-10-17', '2026-10-29', '2026-11-03', '2026-11-04'])]"
    ),
    md(
        "- **9–14 Oct · Technical or payment friction (low):** a support ticket in the last 7 days. Friction comes first "
        "even though play is already falling.\n"
        "- **15–16 Oct · Engagement decline (medium):** the ticket is older than 7 days; played 1, then 0 of the last 7 "
        "days against about 5 a week before (score 93 → 100, severe → medium).\n"
        "- **17 Oct – 3 Nov · Revenue decline (high):** the purchase dropped out of the last 28 days: $0 vs $14.46 in the "
        "28 before. At that pace the update rule's value falls by about $23 → high priority. Action: CRM/VIP offer.\n"
        "- **4 Nov · Engagement decline (low):** the player came back and bought again, so the revenue decline ends; "
        "sessions are still well below their usual pace (6 vs 17 a week), so they stay on a list, at low priority.\n\n"
        "This is the precedence rule at work: one list at a time, moving as the evidence changes."
    ),
    # ------------------------------------------------------------------ 9
    md("## 9. History: entry, exit, duration\n\nEach continuous stay on a list (27 run dates, 9 Oct – 4 Nov):"),
    code(
        "sp = H.spells()\n"
        "display(sp.groupby('list_type').agg(stays=('days', 'size'), median_days=('days', 'median'), longest=('days', 'max')))\n"
        "sp.sort_values('days', ascending=False).head(8)"
    ),

]

nb = nbf.v4.new_notebook()
nb["cells"] = cells
nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
out = Path(__file__).with_name("03_lists.ipynb")
nbf.write(nb, out)
print(f"wrote {out}")
