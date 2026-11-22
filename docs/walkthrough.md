# Walkthrough script (about 20 minutes)

**What the brief asks:** about 20 minutes presenting, then about 25 minutes of questions, with the concerns log at hand.
The presentation must:

- demo the app from raw file to dashboard, LTV score, saved daily lists and a stakeholder message;
- explain the architecture and the data flow;
- explain the target, feature timing, validation, model choice and baseline;
- explain the three lists, how conflicts are resolved and why each action fits;
- show the main tests and one failure handled safely;
- say what changes before production and what evidence or decisions are still needed.

Deck: **SciPlay walkthrough – 20 minutes** (17 slides). Backup for questions: the full results deck.

## Before the call

Run these in the repo folder.

**Setup, once:**

```bash
uv sync                          # install Python 3.12 and the pinned packages
copy .env.example .env           # Windows (Mac/Linux: cp .env.example .env)
#   put the CSV at data/raw/sample_data.csv
```

**Run everything and open the dashboard** (about 1 minute, then http://localhost:8501):

```bash
uv run python -m sciplay.run_all --deliver --app
```

This prepares the data (health gate), loads the shipped LTV model, scores 9 Oct – 4 Nov, builds the daily lists,
replays the hourly delivery into `data/store/outbox/`, and starts the app.

**Optional:** `uv run pytest -q` (99 tests). App only, later: `uv run streamlit run app/Overview.py`.

Have open: the walkthrough deck, the dashboard, `data/store/outbox/2026-11-04/`, `docs/concerns_log.md`.

## Script

| Min | Slides | Show | Say |
|---|---|---|---|
| 0–1 | Title, agenda | – | Five parts, one pipeline; the agenda follows the brief |
| 1–3 | Architecture | `src/sciplay/` | Refresh → health gate → LTV scores → daily lists → hourly delivery; the dashboard reads only stored outputs; bad data is never published |
| 3–6 | Demo | Terminal: `run_all`; dashboard Overview, Segments (payer group) and Data health on 4 Nov; Player detail 33840 | Score date drives every tile; the 1–4 Nov spike is flagged; totals reconciled with SQL; how one player's value is calculated |
| 6–8 | Target and timing; features | – | No 365-day label (oldest player 169 days), so a 30-day target from the first 3 days, × 2.49 as a stated assumption. 359 features → 114 candidates → 18 in the model; device columns dropped and why |
| 8–11 | Why LightGBM; error example; results | – | Same pipeline for LightGBM and a GLM; picked by deviance on later training months, rule fixed in advance. On error it ties "revenue so far" (four real players show why); it wins on ranking (91% of test revenue in its $20+ band) |
| 11–14 | Lists; dashboard | Who needs attention, Revenue decline tab | Three lists, one per player by precedence; priority by the dollar gap; sorted money first; reasons and the owning team's action; player 224283 moving between lists |
| 14–17 | Delivery; two emails | Outbox: email, Slack alert, VIP ticket; click a deep link | Hourly runs; tickets opened once; quiet hours; retries; no duplicates; escalation after 2 days; AI summary checked by pydantic with a template fallback |
| 17–18 | Tests | `pytest tests/test_refresh.py -q` | 99 tests by area; a bad extract fails the gate and nothing downstream moves |
| 18–20 | Before production; concerns | `docs/concerns_log.md` | What changes; what evidence and decisions are still needed; the five main concerns |

## Likely questions (short answers)

- **Why not 365-day labels?** The oldest player is 169 days old; none exist. 30-day labels are complete for installs to 6 Oct.
- **Why 3 days of features?** 7 days would leave the whole November cohort unscored; 3 days scores 132 players instead of 79.
- **Why does the model only tie "revenue so far" on error?** 212 of 218 test players spend nothing after day 3, so "no more spending" is almost always right; one late big spender is $0.80 of the $1.15. The model's value is ranking.
- **Why LightGBM over the GLM?** 12% lower deviance on later training months, beyond the 5% tie margin, chosen before the test set was used; with 4 validation payers the gap is within noise.
- **How do you stop alert fatigue?** Alerts only on change, thresholds with a minimum size, grouping, 5 alerts a day per channel, quiet hours, escalation only for medium/high.
- **What if the LLM invents a cause?** The validator rejects causal wording and numbers not in the facts; the template is used instead.
- **How do you know the lists help?** The `actions` table (acknowledgment, action, outcome) and a suggested 10% holdout.
