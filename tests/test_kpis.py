"""Dashboard metrics: zero vs not applicable, filters, rolling ratios, cohort curves."""

import math

import pandas as pd
import pytest

from sciplay.metrics import kpis as K
from sciplay.pipeline.prepare import build_player_day


@pytest.fixture
def pday(sample):
    return build_player_day(sample)


def test_daily_counts_and_revenue(pday):
    d = K.daily_kpis(pday)
    assert d.loc["2026-10-01", "active_players"] == 2      # player 2's two platforms count once
    assert d.loc["2026-10-01", "new_players"] == 1          # player 1 installed that day
    assert d.loc["2026-10-02", "payers"] == 1
    assert d.loc["2026-10-02", "revenue"] == pytest.approx(10.0)


def test_day_without_rows_is_zero_and_ratios_not_applicable(pday):
    d = K.daily_kpis(pday, end=pd.Timestamp("2026-10-04"))
    assert d.loc["2026-10-04", "active_players"] == 0
    assert d.loc["2026-10-04", "revenue"] == 0
    assert math.isnan(d.loc["2026-10-04", "arpdau"])
    assert math.isnan(d.loc["2026-10-04", "payer_rate"])


def test_payer_status_filter_is_as_of_each_day(pday):
    payers = K.filter_player_day(pday, payer_status="Ever-payer")
    # player 1 becomes a payer on 2 Oct; player 2 has $5 lifetime revenue from before
    assert set(zip(payers["PLAYER_ID"], payers["DATE"].dt.day)) == {(1, 2), (1, 3), (2, 1)}


def test_rolling_ratio_is_computed_from_sums(pday):
    d = K.daily_kpis(pday)
    r = K.rolling(d, window=3)
    expected = d["revenue"].sum() / d["active_players"].sum()
    assert r["arpdau"].iloc[-1] == pytest.approx(expected)


def test_cumulative_revenue_counts_only_players_old_enough(pday):
    # Data ends 3 Oct: player 1 (installed 1 Oct) is 2 days old, player 2 (installed 20 Sep) is 13.
    curves = K.cumulative_revenue_per_install(pday, pd.Timestamp("2026-10-03"), max_age=30, min_players=1,
                                              min_players_pooled=1)
    pooled = curves[curves["install_cohort"] == "All cohorts"].set_index("age_days")
    assert pooled.loc[2, "players"] == 2
    assert pooled.loc[5, "players"] == 1        # only player 2 has lived to day 5
    assert 14 not in pooled.index               # nobody is 14 days old: not yet available, not zero
    assert pooled.loc[2, "revenue_per_install"] == pytest.approx(5.0)  # player 1's $10 / 2 players
