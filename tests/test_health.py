"""Health checks on synthetic data: a date without rows fails freshness."""

import pandas as pd

from sciplay.metrics.health import FAIL, PASS, run_checks
from sciplay.pipeline.prepare import build_player_day


def test_date_without_rows_fails_freshness(sample):
    pday = build_player_day(sample)
    checks = run_checks(pday, pd.Timestamp("2026-10-04")).set_index("check")
    assert checks.loc["Rows have landed for the date", "status"] == FAIL


def test_date_with_rows_passes_freshness_and_validity(sample):
    pday = build_player_day(sample)
    checks = run_checks(pday, pd.Timestamp("2026-10-02"), raw=sample).set_index("check")
    assert checks.loc["Rows have landed for the date", "status"] == PASS
    assert checks.loc["Negative revenue", "status"] == PASS
    assert checks.loc["Duplicate keys (date, player, platform)", "status"] == PASS
