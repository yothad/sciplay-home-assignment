"""Prepared data, reconciliation and every dashboard page, on the real sample file."""

import glob

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


def test_deep_links_open_the_right_date_list_and_player(processed, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("PROCESSED_DIR", str(processed))
    at = AppTest.from_file(str(REPO_ROOT / "app" / "pages" / "4_Who_needs_attention.py"), default_timeout=120)
    at.query_params["date"] = "2026-11-03"
    at.query_params["list"] = "Revenue decline"
    at.run()
    assert not at.exception
    assert str(at.session_state["score_date"]) == "2026-11-03"
    assert any("Opened from an alert" in i.value for i in at.info)
    at = AppTest.from_file(str(REPO_ROOT / "app" / "pages" / "5_Player_detail.py"), default_timeout=120)
    at.query_params["date"] = "2026-11-03"
    at.query_params["player"] = "33840"
    at.run()
    assert not at.exception and at.selectbox[0].value == 33840


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


def test_segments_cover_the_player_base_once(processed):
    from sciplay.data.asof import snapshot_as_of
    from sciplay.metrics import kpis as K

    pday = pd.read_parquet(processed / "player_day.parquet")
    D = pd.Timestamp("2026-11-04")
    rows = pday[pday["DATE"] <= D]
    base = snapshot_as_of(rows, D)
    n = int((base["days_since_last_seen"] < 30).sum())
    lists = pd.DataFrame({"player_id": base["PLAYER_ID"].head(5), "opportunity_gap": 1.0})
    for column in K.SEGMENTS.values():
        t = K.segments(rows, D, column, lists=lists)
        assert t["players"].sum() == n                      # every player in exactly one group
        assert (t["list_rate"] <= 1).all()
    eng = K.engagement_daily(rows)
    assert (eng["sessions_per_active"] > 0).all()
