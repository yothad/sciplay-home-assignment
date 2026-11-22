"""Build notebooks/02_ltv.ipynb from code (keeps the notebook diff-friendly).

Run:  uv run python notebooks/build_02_ltv.py
Then: uv run jupyter nbconvert --to notebook --execute --inplace notebooks/02_ltv.ipynb
"""

from pathlib import Path

import nbformat as nbf

md = nbf.v4.new_markdown_cell
code = nbf.v4.new_code_cell

cells = [
    md(
        "# Part 3 · LTV through day 365\n\n"
        "Every analysis behind the Part 3 decisions, in the order they were made. Logic lives in `src/sciplay/ltv/`; "
        "this notebook only calls it.\n\n"
        "**The approach in one line:** the first 3 days of play → a validated forecast of revenue in the first 30 days "
        "→ **× 2.49, an assumption** → LTV365 (gross USD, a labelled proxy).\n\n"
        "**Contents**\n"
        "1. Target validation: is there a 365-day label?\n"
        "2. Which horizon can we learn from?\n"
        "3. Split by install date\n"
        "4. Early behaviour: why 3 days\n"
        "5. From 30 days to 365: the multiplier\n"
        "6. Features and leakage checks\n"
        "7. Model selection on the training folds\n"
        "8. Test results\n"
        "9. Explanations (SHAP) and reason codes\n"
        "10. Uncertainty and confidence\n"
        "11. Players too old for the model: the update rule\n"
        "12. The output table"
    ),
    code(
        "import pandas as pd\n"
        "import plotly.graph_objects as go\n"
        "import plotly.io as pio\n"
        "from IPython.display import display\n\n"
        "from sciplay.config import REPO_ROOT, get_settings\n"
        "from sciplay.data.loader import load_raw\n"
        "from sciplay.ltv import analysis as A, checks, config as C, features as F, labels, split\n\n"
        "pio.renderers.default = 'plotly_mimetype+notebook_connected'\n"
        "pd.set_option('display.max_colwidth', 200)\n"
        "pd.set_option('display.width', 200)\n\n"
        "pday = pd.read_parquet(get_settings().processed_dir / 'player_day.parquet')\n"
        "pday['DATE'] = pd.to_datetime(pday['DATE'])\n"
        "raw = load_raw(get_settings().raw_data_path)\n"
        "registry = pd.read_csv(REPO_ROOT / 'docs' / 'column_registry.csv')\n"
        "installs = split.install_dates(pday)\n"
        "data_end = pday['DATE'].max()\n"
        "sets = split.assign_sets(installs, data_end)\n"
        "lab = labels.label_frame(pday, installs, data_end)\n"
        "print(f'{installs.size} players, data {pday.DATE.min():%d %b} – {data_end:%d %b %Y}')"
    ),
    # ------------------------------------------------------------------ 1
    md(
        "## 1. Target validation: is there a 365-day label?\n\n"
        "The brief asks not to assume `D365_SPEND` is a label because of its name, and to test its availability, "
        "population, stability across snapshots, relationship to lifetime revenue and exposure to censoring."
    ),
    code("A.target_validation(raw, installs, pday)"),
    md(
        "**Conclusion:** `D365_SPEND` is lifetime spend so far, not spend at day 365, and no player is old enough for a "
        "365-day outcome. **There is no valid 365-day label, so it cannot be used to train.** Any 365-day figure from this "
        "sample is a labelled proxy."
    ),
    # ------------------------------------------------------------------ 2
    md(
        "## 2. Which horizon can we learn from?\n\n"
        "A label is usable only when its whole window is inside the data (the data ends 4 Nov)."
    ),
    code("A.label_horizons(pday, installs, data_end)"),
    md(
        "**Decision: learn from revenue in the first 30 days.** 518 players have a complete 30-day label (16 paid). "
        "**Not 90 or 365 days: too few players with a complete label, so train and test sets would be too small** "
        "(90 days: 322 players, a test cohort ending in early August with about 4–5 payers; 365 days: none)."
    ),
    # ------------------------------------------------------------------ 3
    md(
        "## 3. Split by install date\n\n"
        "Every player belongs to exactly one set, by install date. Train and test players have a complete 30-day label; "
        "inference players have at least 3 days of data but an incomplete month; younger players are cold start. "
        "The model that is tested is the model that ships (no refit on test players)."
    ),
    code(
        "summary = lab.groupby(sets).agg(players=('complete', 'size'),\n"
        "                                paid_by_day_3=('revenue_first_k', lambda s: int((s > 0).sum())),\n"
        "                                paid_by_day_30=('revenue_first_30d', lambda s: int((s > 0).sum())))\n"
        "summary['installs'] = installs.groupby(sets).agg(lambda s: f'{s.min():%d %b} – {s.max():%d %b}')\n"
        "summary.loc[['train', 'test', 'inference', 'cold_start'], ['installs', 'players', 'paid_by_day_3', 'paid_by_day_30']]"
    ),
    md(
        "Accepted risk: labels of late-July training players run into August, overlapping the test players' calendar "
        "time. Players never overlap."
    ),
    # ------------------------------------------------------------------ 4
    md(
        "## 4. Early behaviour: why 3 days\n\n"
        "How much of a player's first-month revenue is visible after 3 or 7 days (train + test players)?"
    ),
    code("A.early_signal(pday, installs, sets.index[sets.isin(['train', 'test'])])"),
    code(
        "curve = A.revenue_curve(pday, installs, sets.index[sets == 'train'])\n"
        "fig = go.Figure(go.Scatter(x=curve.index, y=curve.values, mode='lines+markers', line=dict(color='#6B3FA0', width=2),\n"
        "                           hovertemplate='Day %{x}: %{y:.0%} of 30-day revenue<extra></extra>'))\n"
        "fig.add_vline(x=C.K - 1, line_dash='dot', line_color='#6E6680', annotation_text='feature date (day 3)')\n"
        "fig.update_layout(title='Share of first-30-day revenue earned by each day (training players)',\n"
        "                  xaxis_title='Days since install', yaxis_title=None, yaxis_tickformat='.0%',\n"
        "                  template='plotly_white', height=380, showlegend=False)\n"
        "fig.show()"
    ),
    md(
        "This curve is also used to compute **expected revenue by day d** for the ahead/behind-forecast tracking.\n\n"
        "A quick out-of-time check with the simple rule (no tuning): fit on train, score test."
    ),
    code(
        "for k in (3, 7):\n"
        "    t, info = A.rule_benchmark(pday, installs, sets, k)\n"
        "    print(f\"First {k} days: {info['train_early_payers']} training players had paid by day {k}; \"\n"
        "          f\"test = {info['test_players']} players, {info['test_payers']} payers, ${info['test_actual_total']:.0f}\")\n"
        "    display(t)"
    ),
    md(
        "**Decision: one model, from the first 3 days.** 7 days was considered first:\n"
        "- 7 days carries more signal: 45% of 30-day revenue known vs 39% at day 3; 11 vs 9 of the 16 payers have paid; "
        "7 training payers vs 5; and the 7-day rule beats both baselines on every measure.\n"
        "- But 7 days leaves **all 100 November installs** (and 103 players in total) in cold start. The November cohort "
        "(100 installs in 4 days) looks deliberately placed to be scored with almost no history.\n"
        "- 3 days scores **132 players instead of 79**, half of November among them. The 3-day rule is worse than "
        "\"revenue so far\" on error per player (MAE rewards predicting $0), but much better calibrated "
        "(predicted ÷ actual 0.79 vs 0.34) and better on payers; the model adds activity features the rule does not use.\n"
        "- Train and test sizes do not depend on the window: they are set by the complete 30-day label.\n\n"
        "**Why not predict days 3–7 instead of 30?** Only 2 of 518 players make a first purchase between day 3 and day 7, "
        "and reaching day 365 would need two assumed multipliers instead of one.\n\n"
        "Players younger than 3 days (installed 3–4 Nov) are **cold start**: they get the new-player average, marked low confidence.\n\n"
        "*How the shares are calculated:* pooled dollars, i.e. total revenue all players spent by day d ÷ the total they spent "
        "in days 0–29. Dollar-weighted, so big payers dominate. The table uses train + test players (39% by day 3); the curve "
        "uses training players only (43% by day 3)."
    ),
    # ------------------------------------------------------------------ 5
    md(
        "## 5. From 30 days to 365: the multiplier\n\n"
        "LTV365 = 30-day forecast × (1 + r + r² + … + r¹¹): each later 30-day block is worth r × the block before. "
        "Can r be estimated from the data? Month-to-month revenue for cohorts old enough to have both months:"
    ),
    code(
        "total = pday.assign(R=pday['REVENUE'].fillna(0)).groupby('PLAYER_ID')['R'].sum().sort_values(ascending=False)\n"
        "top2 = total.index[:2].tolist()\n"
        "print('Top spenders:', {p: round(v) for p, v in total.head(2).items()}, f'= {total.head(2).sum() / total.sum():.0%} of all revenue')\n"
        "for name, ex in [('All players', []), ('Without the top spender', top2[:1]), ('Without the top 2', top2)]:\n"
        "    print(name)\n"
        "    display(A.monthly_ratios(pday, installs, data_end, exclude=ex))"
    ),
    md(
        "With all players the later steps look like 0.4–0.65, but **without the top two spenders, revenue after month 1 "
        "is under $100 a month in the whole sample** and the ratios jump around with no pattern. Those apparent ratios "
        "came from two players.\n\n"
        "**Conclusion: r cannot be estimated from this sample. We assume r = 0.6, giving × 2.49, with "
        "sensitivity r = 0.5–0.7 (× 2.00–3.29). One multiplier for every player.** The month-1 → 2 rise also shows that "
        "month 1 can understate players who ramp up."
    ),
    code("A.multiplier_table()"),
    # ------------------------------------------------------------------ 6
    md(
        "## 6. Features and leakage checks\n\n"
        "Features come only from rows dated install … install + 2 and only from columns the registry allows, typed by "
        "how they should be summarised over the week."
    ),
    code(
        "spec = F.build_spec(registry, pday)\n"
        "types = spec.as_table()\n"
        "types['type'] = types['feature_type'].str.replace(r':.*', '', regex=True)\n"
        "display(types['type'].value_counts().rename('columns').to_frame())\n"
        "display(types[types['type'] == 'excluded'].groupby('feature_type')['column']\n"
        "        .agg(columns='size', examples=lambda s: ', '.join(s.head(4))))"
    ),
    md(
        "| Type | Summary over days 0–2 |\n|---|---|\n"
        "| count | sum, mean per active day, max |\n| state | value on the last day (+ change for levels) |\n"
        "| average | mean over active days |\n| friction | sum + any |\n| flag | share of active days |\n"
        "| categorical | first row; one-hot, levels with fewer than 20 training players → Other |\n"
        "| built from our rows | revenue in days 0–2, active days, played on day 1, last active day, day of first purchase "
        "(n/a + never-paid flag), revenue per session, store conversion, purchase failure rate |\n\n"
        "Ordered segment bins (`LEVEL_BIN`, `SPINNER_SEGMENT`, …) are not used: they are bucketed from measures already "
        "included (registry: use the source measures)."
    ),
    code(
        "X = F.build_features(pday, installs, spec)\n"
        "train_ids = sets.index[sets == 'train']\n"
        "enc = F.CategoryEncoder(spec.categorical).fit(X.loc[train_ids])\n"
        "Xt = enc.transform(X.loc[train_ids].drop(columns='feature_date'))\n"
        "kept, dropped = F.prefilter(Xt, priority=['revenue_first_k', 'active_days'])\n"
        "print(f'{X.shape[1] - 1} built features -> {Xt.shape[1]} after one-hot -> {len(kept)} candidates after the pre-filter')\n"
        "display(dropped['dropped_because'].str.replace(r' with .*', '', regex=True).value_counts().rename('features').to_frame())\n"
        "pd.Series({c: ', '.join(v) + ', Other' for c, v in enc.levels_.items()}, name='levels kept').to_frame()"
    ),
    md(
        "The pre-filter keeps a feature if at least 3 training players have a non-zero value (revenue features are "
        "non-zero for only 7 players, so a share-based rule would remove them), then keeps one of each pair with rank "
        "correlation above 0.95.\n\n"
        "**Leakage checks** (all must pass before training):\n"
        "1. *Truncation:* features built from data cut at each player's feature date equal features built from the full file.\n"
        "2. *Future revenue:* no revenue-type feature column shows more than the player's revenue so far on its row.\n"
        "3. *Consistency:* our revenue over days 0–2 / 0–6 equals `I3_REVENUE` / `I7_REVENUE` read inside their windows."
    ),
    code(
        "rev_cols = [c for c in spec.count + spec.state + spec.average if 'REVENUE' in c]\n"
        "print('1. Truncation check passed:', checks.truncation_check(pday, installs, spec))\n"
        "print('2. Future revenue check:')\n"
        "display(checks.future_revenue_check(pday, installs, rev_cols))\n"
        "print('3. Consistency with I3/I7_REVENUE:')\n"
        "display(checks.install_window_consistency(pday, installs))"
    ),
    md(
        "`I14_REVENUE` and `I30_REVENUE` are excluded outright: on early rows they already contain purchases made later "
        "(player 8520 shows $15.40 on install day; the purchase was on day 1–2). `I3`/`I7` are equal to our own sums, "
        "so they add nothing as features and serve only as this check."
    ),
    # ------------------------------------------------------------------ 7
    md(
        "## 7. Model selection on the training folds\n\n"
        "Two candidates through the **same** pipeline (features, pre-filter, rounds, SHAP): **LightGBM** (Tweedie), the "
        "model you would run at scale, and a **regularised Tweedie GLM**, a simpler challenger. Each runs 4 rounds "
        "(all → 50 → 20 → 10 features by mean |SHAP|) × 8 settings on two forward folds (May → June, May–June → July), "
        "scored by Tweedie deviance on the remaining revenue (days 3–29). The test set is not used.\n\n"
        "Device, app and performance columns (load times, latency, FPS, spin length, device type, OS version) were removed "
        "from the LTV candidates before this run: they describe the phone and app, not the player's intent to spend; with 6 "
        "payers the first run learned \"slower loading → higher value\" from them. They stay in the Part 4 friction list. "
        "*Transparency:* a diagnostic on the test set was looked at when discussing this; nothing else was chosen from it.\n\n"
        "Only 4 of the 200 validation players spent anything in days 3–29, so read differences with care."
    ),
    code(
        "import json\n"
        "from sciplay.ltv import learners as L, train as T\n"
        "root = REPO_ROOT / 'models' / 'ltv'\n"
        "best = pd.read_json(root / 'selection' / 'best_rounds.json')\n"
        "cols = ['model', 'round', 'n_features', 'deviance', 'MAE_30d', 'pred_over_actual_30d', 'dollar_recall_30d', 'payer_recall_30d', 'picked']\n"
        "display(best[cols].round(3))\n"
        "print('Winner by the rule set in advance (lowest fold deviance; within 5% the simpler model):', T.pick_winner(best))"
    ),
    md(
        "**Decision: LightGBM** (deviance 2.18 vs 2.44 for the GLM, 12% apart, beyond the 5% tie margin), with 18 features "
        "(the 10-feature round scored clearly worse). With 4 validation payers the gap is within noise; the simpler GLM was "
        "close. The pipeline swaps models with one setting. *With more data, a smarter tuning search (e.g. Optuna) would "
        "replace the small fixed grid; here more trials would only fit noise.*"
    ),
    code(
        "meta = json.loads((root / json.loads((root / 'active.json').read_text())['version'] / 'meta.json').read_text())\n"
        "art_dir = root / meta['version']\n"
        "print('Shipped:', meta['model'], '|', len(meta['features']), 'features |', meta['setting'], '|', meta['n_estimators'], 'trees')\n"
        "print('Model version:', meta['version'])\n"
        "pd.Series(meta['features'], name='features').to_frame()"
    ),
    # ------------------------------------------------------------------ 8
    md(
        "## 8. Test results\n\n"
        "Every approach fitted on train and graded **once** on the 218 test players (6 payers). The 30-day forecast = "
        "revenue in days 0–2 + predicted days 3–29. Ranges: the test players redrawn 1,000 times (model fixed), 5th–95th "
        "percentile. Dollar recall = share of actual revenue from players predicted at $1 or more."
    ),
    code(
        "res = pd.read_csv(art_dir / 'test_results.csv')\n"
        "res['MAE range'] = res.apply(lambda r: f\"${r.MAE_low:.2f}–{r.MAE_high:.2f}\", axis=1)\n"
        "res['ratio range'] = res.apply(lambda r: f\"{r.ratio_low:.2f}–{r.ratio_high:.2f}\", axis=1)\n"
        "res[['approach', 'MAE', 'MAE range', 'MAE_payers', 'pred_over_actual', 'ratio range', 'dollar_recall', 'payer_recall', 'deviance']].round(3)"
    ),
    code(
        "print('Value bands (predicted 30-day revenue):')\n"
        "display(pd.read_csv(art_dir / 'value_bands.csv'))\n"
        "print('By install month:')\n"
        "display(pd.read_csv(art_dir / 'test_by_month.csv').round(2))"
    ),
    md(
        "**Headline:** the day-3 forecast **ranks** players well: the 3 players it values at $20+ brought in 91% of test "
        "revenue ($345 of $378), the 212 it values under $1 brought in 6%. But with only 6 paying test players it **cannot "
        "beat simply \"revenue so far\" on error per player** ($1.17 vs $1.15; all ranges overlap), and like every approach "
        "it **under-predicts total dollars** (0.43): one player spent $50.80 by day 3 and $225 in 30 days. It did not catch "
        "the 2 test players who first paid after day 3. **Use it to rank and prioritise players now; trust its dollar levels "
        "once more payers are available** (maturity table, section 2 of the docs).\n\n"
        "Why not just use revenue so far? It gives $0 to every player who has not paid yet (97%), so it cannot rank them."
    ),
    # ------------------------------------------------------------------ 9
    md(
        "## 9. Explanations (SHAP) and reason codes\n\n"
        "Global importance = mean |SHAP| of the shipped model on the training players (both directions count).\n\n"
        "**Player reason codes:** the features with the largest |SHAP| for that player, until they cover 70% of the "
        "player's total |SHAP| (at most 3, none under 10%). Each reads *\"feature: this player's value vs typical (median "
        "training player) (±$ effect)\"*. The $ effect is how much lower (or higher) the forecast would be **without that "
        "one signal**, all else equal: the model works on a log scale, so contributions multiply and removing one divides "
        "the forecast by exp(SHAP). Effects overlap, so they do not add up to the forecast. Players with no effect above "
        "$0.05 get *\"No strong value signals in the first 3 days\"* with the average new player's value for comparison."
    ),
    code(
        "import joblib\n"
        "from sciplay.ltv import score as S\n"
        "art = joblib.load(art_dir / 'model.joblib')\n"
        "dd = T.load_data()\n"
        "tr_ids = dd.sets.index[dd.sets == 'train']\n"
        "Xtr = art['encoder'].transform(dd.X_raw.loc[tr_ids].drop(columns='feature_date')).reindex(columns=art['features'])\n"
        "sv = L.LEARNERS[art['learner']].shap_values(art['model'], Xtr)\n"
        "imp = pd.Series(abs(sv).mean(axis=0), index=[S.feature_label(f) for f in art['features']]).sort_values()\n"
        "fig = go.Figure(go.Bar(x=imp.values, y=imp.index, orientation='h', marker_color='#6B3FA0',\n"
        "                       hovertemplate='%{y}: %{x:.3f}<extra></extra>'))\n"
        "fig.update_layout(title='What drives the forecast: mean |SHAP| (log scale), training players', template='plotly_white',\n"
        "                  height=560, margin=dict(l=380), xaxis_title=None)\n"
        "fig.show()"
    ),
    code(
        "scores = S.read('2026-11-04')\n"
        "m = scores[scores.source == 'model_d3'].sort_values('predicted_ltv_365', ascending=False)\n"
        "m[['player_id', 'age_days', 'ltv_to_date', 'predicted_ltv_30', 'predicted_ltv_365', 'reason_1', 'reason_2', 'reason_3']].head(5).round(2)"
    ),
    # ------------------------------------------------------------------ 10
    md(
        "## 10. Uncertainty and confidence\n\n"
        "**Range (bootstrap):** the shipped model is retrained 50 times, each time on the 300 training players drawn with "
        "replacement; every player gets 50 forecasts. The spread shows how much a forecast depends on which players happened "
        "to be in training. The shown range is the forecast × (25th or 75th percentile ÷ median of the 50), so it keeps the "
        "relative spread and always contains the forecast. LTV365 range = 30-day range × 2.49.\n\n"
        "**Why the confidence label is rule-based for now:** with 6 payers most resampled models predict close to $0 for "
        "nearly everyone, so they agree; the spread could not separate good forecasts from bad ones (the first run put all 6 "
        "test payers in the 'High' group). With thousands of payers the spread becomes a real, checkable measure (low "
        "confidence should mean larger errors). Until then: **High** = paid in the first 3 days (the forecast rests on real "
        "spending); **Medium** = active non-payer; under 3 days old = no forecast."
    ),
    code("pd.read_csv(art_dir / 'confidence_check.csv').round(2)"),
    # ------------------------------------------------------------------ 11
    md(
        "## 11. Players too old for the model: the update rule\n\n"
        "Players installed before 7 Oct are older than the model's window. They get a rule, **not the LTV model**: revenue "
        "to date + last 30 days' revenue × (r + r² + …) over the 30-day blocks left until day 365, with the same assumed "
        "r = 0.6; nothing more if not seen for 30+ days. Backtest of its next-30-day part at past dates:"
    ),
    code("A.update_rule_backtest(pday, installs)"),
    md(
        "The rule is in the right range (0.64–1.35 of actual) and closer than repeating the last 30 days at two of three "
        "dates. It is labelled \"not from the LTV model\" everywhere it appears."
    ),
    # ------------------------------------------------------------------ 12
    md(
        "## 12. The output table\n\n"
        "`ltv_scores` in SQLite, one row per player per score date, keyed on (score date, player, model version) so reruns "
        "replace rather than duplicate. Run `python -m sciplay.ltv.score --date 2026-11-04`."
    ),
    code(
        "display(scores.groupby('source').agg(players=('player_id', 'size'), ltv_to_date=('ltv_to_date', 'sum'),\n"
        "                                     predicted_ltv_365=('predicted_ltv_365', 'sum')).round(0))\n"
        "scores[scores.source == 'model_d3'].head(3).T"
    ),

]

nb = nbf.v4.new_notebook()
nb["cells"] = cells
nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
out = Path(__file__).with_name("02_ltv.ipynb")
nbf.write(nb, out)
print(f"wrote {out}")
