"""Assign every source column to a business field group.

Rules are ordered regular expressions on the column name; the first match wins.
Names are clues, not definitions: the group is a starting point for the column
registry (role, as-of availability, keep/exclude), which is reviewed by hand.
"""

from __future__ import annotations

import re

import pandas as pd

# (group, pattern). Order matters: specific groups come before broad ones.
GROUP_RULES: list[tuple[str, str]] = [
    ("Keys & identifiers", r"^(PLAYER_ID|PLATFORM_ID|GAME_ID|SLOT_ID)$"),
    ("Pipeline metadata", r"^(CREATE|LAST_UPDATE)_"),
    ("Compliance flags", r"CHEAT|SETTLEMENT"),
    ("Activity & engagement", r"^D\d+_(ACTIVE|PURCHASE|SPINS)_DAYS$"),
    (
        "Cohort milestones & outcomes",
        r"^D\d+(_|$)|RETURNER|CONVERTER|CHURNERS|DAYS_UNTIL|^SPENDER_\d+|^NEXT_",
    ),
    ("Dates & timestamps", r"(^|_)DATE$|^DATE$|ACCOUNTING_DATE|INSTALL_DATE"),
    (
        "Acquisition",
        r"SOURCE|CAMPAIGN|ADGROUP|CREATIVE|INSTALL_TYPE|INSTALL_FLAG|ATTRIBUTION|^REACTIVATED$",
    ),
    ("Geography", r"COUNTRY|REGION"),
    ("Segments & bins", r"_BIN$|SEGMENT|BUCKET|^SENIORITY$|^DAU_TYPE$"),
    (
        "Errors & friction",
        r"CRASH|ERROR|FAIL|CANCEL|ZENDESK|WARNING",
    ),
    (
        "Revenue & payers",
        r"REVENUE|SPEND|PAYER|TRANSACTION|^FTD$|PURCHASE_DATE|DAYS_SINCE_LAST_PURCHASE|"
        r"PURCHASES?$|PURCHASE_DAYS|MAX_WEEKLY",
    ),
    (
        "Store, offers & purchase funnel",
        r"CLICKED_BUYS|IMPRESSION|STORES_|OFFER|^OOC|_OOC|OOC_|SPLASH_SALE|PAID_COIN|"
        r"PURCHASE|FREE_TO_PLAY|F2P",
    ),
    (
        "Device, app & performance",
        r"DEVICE|OS_VERSION|APP_VERSION|SERVER_VERSION|TECH_VERSION|FPS|LOAD|LATENCY|"
        r"ASSET_BUNDLE|DOWNLOAD|UPDATE|SPIN_LENGTH|_LN$",
    ),
    ("Social & notifications", r"FACEBOOK|FB_|NOTIF|PUSH|RATE_US|INVITE|GIFT|LOGIN_TYPE"),
    (
        "Game economy (coins, bankroll)",
        r"COIN|BANKROLL|RUB(Y|IES)|INFLOW|OUTFLOW|BONUS|SLIB|PEARL|JEWEL|PLAYDAYS|"
        r"WIN|JACKPOT|AWARD",
    ),
    (
        "Gameplay (spins, bets, features)",
        r"SPIN|BET|WAGER|SLOT|LEVEL|TOURNAMENT|ISLAND|IN_GAME_EVENT|ORC|FEATURE|HIGH_LIMIT|"
        r"DIVE_AND_CATCH|RUBYREEF|MULTIPLIER",
    ),
    (
        "Activity & engagement",
        r"SESSION|LOGIN|ACTIVE|DAU|DAYS_SINCE|CONSECUTIVE|PLAYED|INSTALL",
    ),
]

# Explicit assignments where the name pattern misleads.
OVERRIDES: dict[str, str] = {
    "UPGRADED_FLAG": "Device, app & performance",
    "RECOMMENDED_IMPRESSION": "Device, app & performance",
    "REQUIRED_IMPRESSION": "Device, app & performance",
    "LT_MAX_WEEK_REV": "Revenue & payers",
    "FIRST_DAILY_EVENT": "Dates & timestamps",
    "LAST_DAILY_EVENT": "Dates & timestamps",
    "RATE_US_IMPRESSIONS": "Social & notifications",
    "TOURNAMENT_WIN_DIALOG_IMPRESSIONS": "Gameplay (spins, bets, features)",
    "ORC_COLLECT_IMPRESSIONS": "Gameplay (spins, bets, features)",
    "FEATURESLOT_IMPRESSION": "Gameplay (spins, bets, features)",
    "RUBY_REEF_SLOT_SPIN": "Gameplay (spins, bets, features)",
    "RUBY_REEF_SLOT_TOTAL_WAGER": "Gameplay (spins, bets, features)",
    "RUBYREEF_CLICKED": "Gameplay (spins, bets, features)",
    "D30_PAYER_BIN": "Segments & bins",
}

_COMPILED = [(group, re.compile(pattern)) for group, pattern in GROUP_RULES]


def assign_group(column: str) -> str:
    if column in OVERRIDES:
        return OVERRIDES[column]
    for group, pattern in _COMPILED:
        if pattern.search(column):
            return group
    return "Other"


def field_groups(columns: list[str] | pd.Index) -> pd.DataFrame:
    """Return a frame of column -> field group, in source column order."""
    return pd.DataFrame(
        {"column": list(columns), "field_group": [assign_group(c) for c in columns]}
    )
