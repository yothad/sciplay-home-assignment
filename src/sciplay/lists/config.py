"""List rules. Thresholds are STARTING VALUES, tuned on list sizes and the backtest; change them here."""

from __future__ import annotations

FRICTION = "Technical or payment friction"
REVENUE = "Revenue decline"
ENGAGEMENT = "Engagement decline"
PRECEDENCE = [FRICTION, REVENUE, ENGAGEMENT]     # one primary list per player, first match wins

# Eligibility (Part 1)
MIN_AGE_DAYS = 3
MAX_DAYS_UNSEEN = 29          # seen in the last 30 days (A12)

# Windows
RECENT_DAYS = 7               # recent window: (D-7, D]
PRIOR_DAYS = 28               # baseline window just before it: (D-35, D-7]
SPEND_DAYS = 28               # revenue: last 28 days vs the 28 before

# Friction (recent window, more than the player's own baseline)
FRICTION_MIN = {"CRASHES": 1, "ERROR_UNHANDLED": 1, "purchase_failures": 1, "ZENDESK_TICKETS": 1, "load_failures": 2}
LOAD_PAIRS = [("SLOT_LOAD_STARTS", "SLOT_LOAD_COMPLETES"), ("SLOT_DOWNLOAD_STARTS", "SLOT_DOWNLOAD_COMPLETES"),
              ("INITIAL_LOBBY_LOAD_STARTED", "INITIAL_LOBBY_LOAD_COMPLETED")]   # load started, never completed
INCOMPLETE_ATTEMPTS_MIN = 2   # purchase starts with none completed

# Revenue decline
SPEND_DROP = 0.50             # last 28 days <= (1 - 0.50) x previous 28 days
OVERDUE_FACTOR = 2.0          # days since last purchase > 2 x usual gap (needs 2+ purchase days)
BEHIND_SHARE = 0.50           # model players: spent <= 50% of expected by today ...
BEHIND_MIN_DOLLARS = 5.0      # ... and at least $5 behind
VALUABLE_TOP_SHARE = 0.10     # non-payers in the top 10% of predicted LTV365 count as valuable

# Engagement decline
ACTIVITY_DROP = 0.50          # days played (or sessions) in the recent window <= 50% of the baseline pace
MIN_PRIOR_DAYS_PER_WEEK = 1.0 # baseline must be meaningful: at least 1 day played a week before
MIN_PRIOR_SESSIONS_PER_WEEK = 2.0
YOUNG_DAYS = 35               # younger players are compared with peers of the same age
RETURN_FACTOR = 2.0           # not seen for more than 2 x the usual gap between days played ...
RETURN_MIN_DAYS = 7           # ... and at least 7 days
MIN_PLAY_DAYS_FOR_GAP = 4     # a usual gap needs at least 4 days played

# Priority by opportunity gap (dollars), set from the gap distribution
PRIORITY_HIGH = 20.0
PRIORITY_MEDIUM = 2.0
