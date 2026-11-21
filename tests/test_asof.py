"""As-of policy: a score for day D uses only rows dated <= D and only allowed columns."""

import pandas as pd
import pytest

from sciplay.data import asof


def test_rows_as_of_excludes_future_rows(sample):
    rows = asof.rows_as_of(sample, "2026-10-02")
    assert rows["DATE"].max() == pd.Timestamp("2026-10-02")
    assert not (rows["DATE"] > pd.Timestamp("2026-10-02")).any()


def test_revenue_to_date_is_start_of_day_lifetime_plus_same_day_revenue(sample):
    row = sample[(sample["PLAYER_ID"] == 1) & (sample["DATE"] == "2026-10-02")]
    assert asof.revenue_to_date(row).iloc[0] == pytest.approx(10.0)


def test_snapshot_carries_inactive_players_forward(sample, sample_registry):
    player_day = asof.rollup_player_day(sample, sample_registry)
    snap = asof.snapshot_as_of(player_day, "2026-10-03").set_index("PLAYER_ID")
    assert set(snap.index) == {1, 2}
    assert snap.loc[2, "days_since_last_seen"] == 2
    assert not snap.loc[2, "active_on_score_date"]
    assert snap.loc[1, "active_on_score_date"]
    assert snap.loc[1, "revenue_to_date"] == pytest.approx(10.0)


def test_snapshot_never_uses_rows_after_score_date(sample, sample_registry):
    player_day = asof.rollup_player_day(sample, sample_registry)
    snap = asof.snapshot_as_of(player_day, "2026-10-01")
    assert (snap["DATE"] <= pd.Timestamp("2026-10-01")).all()
    assert snap.set_index("PLAYER_ID").loc[1, "revenue_to_date"] == 0


def test_assert_as_of_accepts_a_valid_frame(sample, sample_registry):
    allowed = asof.feature_columns(sample_registry)
    ok = asof.rows_as_of(sample, "2026-10-02")[["DATE", "PLAYER_ID", "SESSIONS"]]
    asof.assert_as_of(ok, "2026-10-02", allowed)


def test_assert_as_of_rejects_rows_after_score_date(sample, sample_registry):
    allowed = asof.feature_columns(sample_registry)
    with pytest.raises(ValueError, match="after"):
        asof.assert_as_of(sample[["DATE", "PLAYER_ID", "SESSIONS"]], "2026-10-02", allowed)


@pytest.mark.parametrize("column", ["D1_RETURNER", "NEXT_LOGIN_DATE", "D365_SPEND"])
def test_assert_as_of_rejects_excluded_columns(sample, sample_registry, column):
    allowed = asof.feature_columns(sample_registry)
    frame = asof.rows_as_of(sample, "2026-10-02")[["DATE", "PLAYER_ID", column]]
    with pytest.raises(ValueError, match="not allowed"):
        asof.assert_as_of(frame, "2026-10-02", allowed)


def test_rollup_gives_one_row_per_player_day(sample, sample_registry):
    player_day = asof.rollup_player_day(sample, sample_registry)
    assert not player_day.duplicated(["DATE", "PLAYER_ID"]).any()
    p2 = player_day[player_day["PLAYER_ID"] == 2].iloc[0]
    assert p2["SESSIONS"] == 3          # daily measures are summed
    assert p2["CRASHES"] == 1
    assert p2["LIFETIME_REVENUE"] == 5  # lifetime fields taken once
    assert p2["n_platforms"] == 2
    assert p2["MAIN_PLATFORM_ID"] == "android"  # most sessions
