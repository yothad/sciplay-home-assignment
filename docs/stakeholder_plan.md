# Part 5 – Proactive stakeholder delivery

The saved daily lists (Part 4) are pushed to the people who act on them, so nobody has to open the dashboard to
find out who needs attention. The design below is built as a **dry run**: every message is rendered and written to
`data/store/outbox/<date>/<channel>/`, with a full delivery audit in SQLite. Going live means replacing the outbox
writer with the ticketing, Slack and email clients; triggers, payloads, deduplication and audit stay the same.

Code: `src/sciplay/delivery/` (config, triggers, payloads, summary, store, run, simulate). Tests: `tests/test_delivery.py`
and the deep-link test in `tests/test_dashboard.py`.

```bash
uv run python -m sciplay.delivery.run --date 2026-11-04            # refresh + morning + evening slots
uv run python -m sciplay.delivery.simulate                        # 2-day demo with simulated owner actions
```

## 1. Architecture

```
daily refresh (Part 2) ──> LTV scores (Part 3) ──> daily_lists + list_runs (Part 4)
                                                          │
                                   ┌──────────────────────┴───────────────────────┐
                              triggers.py                                   payloads.py
               (events, escalation, data incomplete)          (ticket JSON, Slack blocks, email markdown,
                                   │                             deep links, summary via summary.py)
                                   └──────────────────────┬───────────────────────┘
                                                        run.py  (slots: refresh 06:00 · morning 08:00 · evening 18:00)
                                       idempotency key · retries · quiet hours · daily alert limit · audit
                                                          │
                     ┌────────────────────┬───────────────┴────────┬─────────────────────┐
                ticket queues        Slack (studio channel)     email (twice a day)     #data-alerts
                                                          │
                                         deliveries · tickets · actions (SQLite)
```

**One studio per game.** Every message is per `GAME_ID` (the sample has one game, "Sample studio", channel
`#test-player-alerts`). A second game gets its own channel, queues and email list from `delivery/config.py`.

## 2. Recipients, owners, channels and expected actions

| Recipient | Owns | Channel | Expected action |
|---|---|---|---|
| **Player support** (tech + payments, one team) | Technical or payment friction | Ticket in the *Player support queue* (one per player stay on the list) + Slack | Check crash / error logs or the failed purchase, contact the player, compensate within policy; record action and outcome on the ticket |
| **VIP hosts** (in live-ops / CRM) | Revenue decline | Ticket in the *VIP host queue* + Slack | Personal outreach or a timed offer on the player's usual purchase; any offer with a cost needs live-ops lead approval |
| **Live-ops / CRM** | Engagement decline | Slack + the list in the dashboard (CRM audience, no ticket per player) | Add players to a win-back push / in-game message campaign; record the campaign |
| **Live-ops lead / Player support lead** | Escalations | Slack mention | Reassign or act on medium/high players untouched by the evening of their 2nd day |
| **Studio GM / product lead** | Accountability | Morning and evening email | Read the state of the lists; decide on budget for offers |
| **Game economy designer** | Offer design | Morning and evening email | Watch revenue decline reasons (overdue purchases, spend drop) and adjust offers / economy |
| **Product analyst** | Measurement | Email + `actions` table | Track response and outcome rates per list; propose threshold changes |
| **Data team** | Pipeline | `#data-alerts` | Fix missing data, failed runs, failed deliveries |

## 3. Daily digest and event triggers

**Morning email (08:00, "what is open now")**: summary paragraph (template or validated LLM wording), a table per
list with owner, players, high / medium / low, change vs yesterday and value at risk, new players since yesterday, top
reasons, alerts held overnight, data freshness and a deep link.

**Evening email (18:00, "what was taken care of")**: players acted on today (owner, action, outcome), still open per
list, overdue / escalated per list, alerts that were over the daily limit.

**Event triggers** (checked right after each refresh, `triggers.py`; thresholds in `delivery/config.py`):

| Trigger | Rule | Message |
|---|---|---|
| New high-priority player | Player enters a list as high, or is raised to high | Slack to the studio channel, grouped per list |
| Large value at risk for one player | Opportunity gap ≥ $100 on entry | Slack, grouped per list |
| Material list increase | Today ≥ 1.5 × the 7-day average **and** ≥ 5 more players | Slack |
| Large total value at risk | Total gap ≥ 2 × its 7-day average | Slack |
| Escalation | Medium/high player, no action recorded by the evening of the 2nd day on the list (counting from go-live) | Slack to the list owner's lead, one message per list, 10 players max + "… N more" |
| Data incomplete / no lists / failed delivery | Health gate warning, failed run, a message failing 3 times | `#data-alerts` only; team alerts are held until the data is complete |

## 4. Example payloads (from the dry run, 3–4 Nov)

**Morning email, 3 Nov** (subject: `[test] Players to act on today · 2026-11-03 · 42 players, $352 at risk`)

```markdown
# Sample studio · players to act on today · 2026-11-03

**42 players need attention today, $352.46 of value at risk.**

- Technical or payment friction: 8 players, -1 vs yesterday, $0.00 at risk.
- Revenue decline: 9 players (4 high priority), +1 vs yesterday, $352.18 at risk.
- Engagement decline: 25 players, -2 vs yesterday, $0.28 at risk.
- Most common reason: away longer than usual (20 players).

| List | Owner | Players | High | Medium | Low | Change vs yesterday | Value at risk |
|---|---|---|---|---|---|---|---|
| Technical or payment friction | Player support | 8 | 0 | 7 | 1 | -1 | $0.00 |
| Revenue decline | Live-ops / CRM (VIP hosts) | 9 | 4 | 4 | 1 | +1 | $352.18 |
| Engagement decline | Live-ops / CRM | 25 | 0 | 22 | 3 | -2 | $0.28 |

**New since yesterday:** 2 players. **Top reasons:** away longer than usual (20), fewer sessions than usual (19), ...

**Alerts held overnight (quiet hours) or over the daily alert limit:**
- New high-priority player on Revenue decline

Open the lists: http://localhost:8501/Who_needs_attention?date=2026-11-03
_Data as of 2026-11-03 · rules-6fa388be. Player IDs are in the tickets and the dashboard, not in this email._
```

**Slack event (held at 06:00, sent at 08:00)**

```json
{"channel": "#test-player-alerts",
 "blocks": [
  {"type": "section", "text": {"type": "mrkdwn", "text": "*New high-priority player on Revenue decline*\n• Player 287726 · high · gap $21.05 · Spent $0.00 vs $8.44 expected by now (day-3 forecast)"}},
  {"type": "context", "elements": [{"type": "mrkdwn", "text": "Data as of 2026-11-03 · rules-6fa388be · event `new_high_priority`"}]},
  {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Open in dashboard"},
    "url": "http://localhost:8501/Who_needs_attention?date=2026-11-03&list=Revenue+decline"}]}]}
```

**Ticket (VIP host queue)**

```json
{"ticket_id": "test-REV-33840-2026-11-03", "queue": "VIP host queue", "studio": "Sample studio",
 "title": "Revenue decline: player 33840 (high priority)", "player_id": 33840, "priority": "high",
 "reasons": ["No purchase for 8 days; usually every 1.5 days", "Played 0 of the last 7 days vs 1.5 a week before",
             "0 sessions in the last 7 days vs 9.2 a week before", "Not seen for 8 days; usually plays every day"],
 "recommended_action": "CRM / VIP: timed offer on the player's usual purchase",
 "value": {"opportunity_gap": 266.96, "predicted_ltv_365": 2714.05, "ltv_to_date": 2366.73},
 "needs_approval_before_any_cost": true,
 "link": "http://localhost:8501/Player_detail?date=2026-11-03&player=33840",
 "rules_version": "ltv-d3-lightgbm-6008a0b5-729fa670+rules-6fa388be"}
```

**Escalation (Slack, 4 Nov 18:00)**: "Escalation to Player support lead: 4 medium/high-priority players on Technical or
payment friction with no action for 2+ days", then one line per player (priority, on the list since, top reason) and an
"Open list" button.

**Deep links.** `Who_needs_attention?date=…&list=…` opens the dashboard on that date with the alert's list as the first
tab; `Player_detail?date=…&player=…` opens the player. Covered by a dashboard test.

## 5. Reliability and alert fatigue

| Concern | Design |
|---|---|
| Deduplication | Every message has an idempotency key (`date|event|list|player`, `ticket|<id>`, `date|email_morning|game`). A key already `sent` is never sent again, so re-running a slot or the whole day is safe. Player events inside a grouped message are recorded per player, so a player is alerted once per event even when the list is rebuilt |
| Tickets | Opened once per player stay on a list; while open only the priority is updated; closed when the player leaves the list or the owner resolves it; not reopened for 7 days after resolution (signals use 7-day windows) |
| Rate limits | At most 5 event messages per studio channel per day; the rest go into the next email. Players grouped into one message per event type and list, 10 players max per message. In production, also respect Slack's ~1 message per second per channel |
| Quiet periods | No team messages 21:00–08:00 studio time; events found then are held and sent at 08:00 (and listed in the morning email). Data alerts are not held |
| Retries | Up to 3 attempts per message with the same key (production: backoff 1 s, 4 s, 16 s). The demo forces two timeouts on the 4 Nov morning email: it goes out on attempt 3 |
| Delivery audit | `deliveries` table: key, date, channel, recipient, kind, status (sent / held / capped / failed), attempts, last error, outbox path, time |
| Failure escalation | A message still failing after 3 attempts is recorded `failed` and reported to `#data-alerts` with its key; no lists for a date → data channel message, teams get nothing rather than stale lists |
| Alert fatigue | Events only on change (entry or priority up), material thresholds with a minimum size, grouping, daily cap, quiet hours, escalation only for medium/high, one escalation message per list. Review after 4 weeks: alerts with no action → raise the threshold or drop the trigger |

## 6. Security, player identifiers and review

- **Access control.** Tickets go only to the owning queue; Slack only to private studio channels (members = studio
  staff); the dashboard sits behind company SSO with a per-studio role. The email to managers has counts and
  reasons only.
- **Player identifiers.** Only the internal `PLAYER_ID` is used: no names, emails, device IDs or payment details in any
  message. Player IDs appear in tickets, Slack and the dashboard (internal tools), never in email. Links carry the ID
  only, and open nothing without SSO.
- **Retention.** Outbox / delivery audit 90 days; tickets follow the ticketing system's policy; `actions` kept 13 months
  for measuring value; daily lists kept for the model's backtest window. Deletion requests (GDPR / CCPA) remove the
  player from lists, tickets and actions.
- **Review before any player action.** The system never contacts a player or grants anything. Every ticket says
  `needs_approval_before_any_cost: true`: an offer, compensation or bonus needs the owner's decision, and anything with a
  cost above the studio's limit needs the live-ops lead. Players excluded in Part 1 (flags, settlements) never reach a
  list. Regulated markets (social casino) follow the studio's responsible-gaming policy before any promotion.

## 7. Feedback loop: did the lists create value?

`actions` table: `score_date, player_id, list_type, owner, acknowledged_at, action, outcome, is_demo`. Filled from the
ticket (acknowledge, action, outcome) or the dashboard for engagement campaigns. In the demo, owners act on the top
players of each list (`is_demo = 1`); actions remove players from escalation and resolved tickets close.

What the product analyst tracks per list and week: acknowledgment rate and time to acknowledge, action rate, outcome
(resolved / purchase made / returned within 7 days), and revenue in the 30 days after the action compared with the
forecast.

**Suggestion: holdout.** Not built. To measure the effect of the actions and not just the activity, keep a random 10% of
eligible players on each list out of the tickets and campaigns for a few weeks (friction excepted: fixing a broken
purchase is not withheld), and compare their 30-day revenue and return rate with the treated players. Needs a
decision from the studio GM.

## 8. AI-assisted summary

The summary at the top of the morning email is built from structured facts only (`summary.facts`: counts, changes,
value at risk, top reason labels, data status). No LLM API is called in this project; the code accepts any function
that takes the prompt and returns JSON.

**Prompt template** (`summary.PROMPT_TEMPLATE`)

```text
You write the opening summary of a daily email for a mobile game studio.
Readers: studio GM, live-ops lead, player support lead, game economy designer, product analyst.

Use ONLY the facts in the JSON below. Rules:
- Every number you write must appear in the facts exactly as given (same rounding).
- Mention reasons only by their label from "top_reasons".
- Do not explain why something happened (no "because", "due to", "driven by"); state what the lists show.
- If "data_status" is not "complete", the headline must say the data is incomplete.
- Plain English, no player IDs, no hype.

Return JSON only, matching this schema:
{"headline": "<one sentence, max 120 characters>",
 "bullets": ["<max 4 bullets, each one sentence>"],
 "data_status": "complete" | "incomplete"}

FACTS:
{facts_json}
```

**Desired result**

```json
{"headline": "43 players need attention today, $1,234.56 of value at risk.",
 "bullets": ["Revenue decline: 8 players (3 high priority), the largest share of value at risk.",
             "Technical or payment friction: 11 players, 2 more than yesterday.",
             "Most common reason: fewer active days than usual (18 players)."],
 "data_status": "complete"}
```

**Validation** (pydantic `DigestSummary`, run with the facts as context): headline ≤ 120 characters, ≤ 4 bullets;
every number must exist in the facts; no causal wording (`because`, `due to`, `caused by`, `driven by`, `led to`, `as a
result of`); a sentence about reasons must use a reason label from the facts; `data_status` must match. Player IDs
cannot pass (they are not in the facts). No recommendations are generated: actions come from the rules (Part 4).

**Fallback.** Invalid JSON, a failed check or an API error → the deterministic template (`summary.template`), which
builds the same structure from the facts and is valid by construction. The email records `summary_source`
(`llm` or `template`). Tests cover acceptance, each rejection and the fallback.

## 9. Simulation (3–4 Nov)

| Slot | What happened |
|---|---|
| 3 Nov 06:00 refresh | 1 event (new high-priority player on Revenue decline) found inside quiet hours → held |
| 3 Nov 08:00 morning | Held alert sent; 17 tickets opened (8 friction, 9 revenue); morning email |
| 3 Nov 08:00 re-run | Nothing sent: every key already delivered |
| 3 Nov (demo actions) | Player support resolves the top friction ticket; VIP host calls player 33840; CRM adds 3 engagement players to a campaign |
| 3 Nov 18:00 evening | Evening email (5 handled); no escalations (day 1) |
| 4 Nov 08:00 morning | 5 new tickets, 2 closed (players left the list); morning email times out twice, sent on attempt 3 |
| 4 Nov (demo actions) | 2 friction players worked, VIP follow-up |
| 4 Nov 18:00 evening | 28 medium/high players with no action for 2 days → 3 escalation messages (friction 4, revenue 7, engagement 17); evening email |

## 10. Before production

Confirm owners, channels, quiet hours and thresholds with each studio; connect the ticketing, Slack and email clients
(secrets in the secret manager, not `.env`); run the delivery slots from the orchestrator after the refresh job;
time zones per studio; SSO on the dashboard; 4-week review of alert volume and action rates; holdout decision.
