"""Who gets what, when. Values are proposals for the studios to confirm."""

from __future__ import annotations

import os

from sciplay.lists import config as L

# One studio per game (GAME_ID); the sample has one game.
STUDIO_NAMES = {"test": "Sample studio"}

OWNERS = {  # list -> owning function in the studio
    L.FRICTION: "Player support",            # tech and payment problems handled by one team
    L.REVENUE: "Live-ops / CRM (VIP hosts)",
    L.ENGAGEMENT: "Live-ops / CRM",
}
OWNER_LEADS = {L.FRICTION: "Player support lead", L.REVENUE: "Live-ops lead", L.ENGAGEMENT: "Live-ops lead"}
TICKET_QUEUES = {L.FRICTION: "Player support queue", L.REVENUE: "VIP host queue"}   # engagement: CRM audience, no ticket
EMAIL_TO = ["Studio GM / product lead", "Live-ops lead", "Player support lead", "Game economy designer",
            "Product analyst"]
DATA_CHANNEL = "#data-alerts"


def slack_channel(game_id: str) -> str:
    return f"#{game_id}-player-alerts"


MORNING_HOUR, EVENING_HOUR = 8, 18       # email slots (studio local time)
QUIET_START, QUIET_END = 21, 8           # no team messages in this window (data alerts excepted)
ESCALATE_AFTER_DAYS = 2                  # medium or high priority, no action by the evening of the 2nd day on the list
GO_LIVE = "2026-11-03"                   # first day teams receive the lists; days before it don't count as "no action"
RESOLVED_COOLDOWN_DAYS = 7               # a ticket resolved by its owner is not reopened for 7 days (signals use 7-day windows)
ESCALATE_PRIORITIES = ("high", "medium")
MAX_PLAYERS_PER_MESSAGE = 10            # more than that: "... and N more in the dashboard"
MAX_ALERTS_PER_DAY = 5                   # event messages per studio channel per day; the rest go into the next email
RETRIES = 3                              # attempts per message; the same idempotency key on every attempt

# Event triggers
LIST_INCREASE_FACTOR = 1.5               # list size >= 1.5 x its 7-day average ...
LIST_INCREASE_MIN = 5                    # ... and at least 5 more players
PLAYER_GAP_ALERT = 100.0                 # one player's opportunity gap at or above $100 (on entry)
TOTAL_GAP_FACTOR = 2.0                   # total value at risk >= 2 x its 7-day average

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:8501")
