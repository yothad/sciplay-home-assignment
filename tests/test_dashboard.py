"""Prepared data, reconciliation and every dashboard page, on the real sample file."""

import glob
import os
from pathlib import Path

import pandas as pd
import pytest

from sciplay.config import REPO_ROOT, get_settings
from sciplay.metrics.reconcile import reconcile
from sciplay.pipeline import prepare

RAW = get_settings().raw_data_path
pytestmark = pytest.mark.skipif(not RAW.exists(), reason=f"sample data not found at {RAW}")


@pytest.fixture(scope="module")
def processed(tmp_path_factory):
    out = tmp_path_factory.mktemp("processed")
    prepare.run(RAW, out)
    return out


def test_prepared_tables_exist(processed):
    for name in ["player_day", "daily_metrics", "cohort_activity", "cohort_revenue"]:
        assert (processed / f"{name}.parquet").exists()
    assert (processed / "manifest.json").exists()


def test_dashboard_totals_reconcile_to_raw_file(processed):
    daily = pd.read_parquet(processed / "daily_metrics.parquet")
    pday = pd.read_parquet(processed / "player_day.parquet")
    result = reconcile(daily, pday, RAW)
    assert result["passed"].all(), result[~result["passed"]]


@pytest.mark.parametrize("page", [str(REPO_ROOT / "app" / "Overview.py")]
                         + sorted(glob.glob(str(REPO_ROOT / "app" / "pages" / "*.py"))))
def test_every_page_renders(processed, page, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("PROCESSED_DIR", str(processed))
    at = AppTest.from_file(page, default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]


def test_health_checks_flag_the_november_spike_and_pass_on_31_october(processed):
    from sciplay.metrics.health import FAIL, WARN, run_checks

    pday = pd.read_parquet(processed / "player_day.parquet")
    oct31 = run_checks(pday, pd.Timestamp("2026-10-31")).set_index("check")
    assert oct31.loc["Rows have landed for the date", "status"] == "pass"
    assert (oct31["status"] != FAIL).all()
    nov2 = run_checks(pday, pd.Timestamp("2026-11-02")).set_index("check")
    assert nov2.loc["Player-days (rows) vs history", "status"] == WARN
    assert nov2.loc["New players vs history", "status"] == WARN


def test_score_date_tiles_reconcile_to_raw_input(processed):
    from sciplay.metrics.reconcile import reconcile_day

    daily = pd.read_parquet(processed / "daily_metrics.parquet")
    for day in ["2026-10-31", "2026-11-02"]:
        assert reconcile_day(daily, processed / "raw_input.parquet", day)["passed"].all()


def test_sample_banner_comes_from_the_data(processed):
    import json

    from sciplay.app.ui import sample_note

    note = sample_note(json.loads((processed / "manifest.json").read_text()))
    assert "exactly 100 new players per install month" in note
