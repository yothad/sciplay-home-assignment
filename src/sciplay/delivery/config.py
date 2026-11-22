"""Who gets what, when. Values are proposals for the studios to confirm."""

from __future__ import annotations

from sciplay.config import get_settings
from sciplay.lists import config as L

# One studio per game (GAME_ID); the sample has one game.
STUDIO_NAMES = {"test": "Sample studio"}

# One name per team, used everywhere (lists' actions, tickets, Slack, emails):
#   Player support team - customer support, including technical and payment problems
#   VIP team            - hosts / account managers for high-value and high-potential players
#   CRM team            - lifecycle marketing: push, email and in-game messages (part of live-ops)
OWNERS = {L.FRICTION: "Player support team", L.REVENUE: "VIP team", L.ENGAGEMENT: "CRM team"}
OWNER_LEADS = {L.FRICTION: "Player support lead", L.REVENUE: "VIP lead", L.ENGAGEMENT: "CRM lead"}
TICKET_QUEUES = {L.FRICTION: "Player support queue", L.REVENUE: "VIP queue"}   # CRM team: campaign audience, no ticket
EMAIL_TO = ["Studio GM", "Player support lead", "VIP lead", "CRM lead", "Game economy designer", "Product analyst"]
DATA_CHANNEL = "#data-alerts"


def slack_channel(game_id: str) -> str:
    return f"#{game_id}-player-alerts"


# Runs every hour. Lists are rebuilt only when a new daily extract lands; every hour the run sends what is not
# sent yet, reads feedback, closes handled tickets and checks escalations.
MORNING_HOUR, EVENING_HOUR = 8, 18       # email slots (studio local time)
QUIET_START, QUIET_END = 21, 8           # no team messages in this window (data alerts excepted)
ESCALATE_AFTER_DAYS = 2                  # medium/high priority, no action by the evening of the 2nd day it was delivered
GO_LIVE = "2026-11-02"                   # first list date teams receive (delivered 3 Nov); earlier days don't count
DATA_LANDS_HOUR = 6                      # the list for day D lands at 06:00 on D+1 (used when replaying past days)
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

DASHBOARD_URL = get_settings().dashboard_url    # deep links in messages; set in .env
