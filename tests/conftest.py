"""Shared fixtures: a tiny synthetic sample with the columns the logic needs."""

import pandas as pd
import pytest

from sciplay.audit.checks import column_profile
from sciplay.data.registry import build_registry


def _row(date, player, platform="android", sessions=1, revenue=None, lifetime=0.0, install="2026-10-01",
         d1=0, next_login=None, crashes=0):
    return {
        "DATE": pd.Timestamp(date), "PLAYER_ID": player, "PLATFORM_ID": platform, "GAME_ID": "test",
        "INSTALL_DATE": pd.Timestamp(install), "SESSIONS": sessions, "REVENUE": revenue,
        "LIFETIME_REVENUE": lifetime, "D1_RETURNER": d1, "NEXT_LOGIN_DATE": next_login, "CRASHES": crashes,
        "DAYS_SINCE_INSTALL": (pd.Timestamp(date) - pd.Timestamp(install)).days,
        "LAST_4W_REVENUE": lifetime, "COUNTRY": "US", "D365_SPEND": lifetime if lifetime > 0 else None,
        "LAST_UPDATE_DATETIME": pd.Timestamp(date) + pd.Timedelta(days=1),
    }


@pytest.fixture
def sample() -> pd.DataFrame:
    """Player 1 plays 1-3 Oct and buys on 2 Oct; player 2 plays only on 1 Oct, on two platforms."""
    rows = [
        _row("2026-10-01", 1, sessions=3, d1=1, next_login="2026-10-02"),
        _row("2026-10-02", 1, sessions=2, revenue=10.0, lifetime=0.0, d1=1, next_login="2026-10-03"),
        _row("2026-10-03", 1, sessions=1, lifetime=10.0, d1=0),
        _row("2026-10-01", 2, platform="android", sessions=2, lifetime=5.0, install="2026-09-20"),
        _row("2026-10-01", 2, platform="ios", sessions=1, lifetime=5.0, install="2026-09-20", crashes=1),
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def sample_registry(sample) -> pd.DataFrame:
    return build_registry(sample, column_profile(sample))
