"""Smoke tests on the real sample file; skipped when the CSV is not present."""

import pytest

from sciplay.audit import checks as audit
from sciplay.data import asof, registry
from sciplay.config import get_settings
from sciplay.data.loader import load_raw

RAW = get_settings().raw_data_path
pytestmark = pytest.mark.skipif(not RAW.exists(), reason=f"sample data not found at {RAW}")


@pytest.fixture(scope="module")
def df():
    return load_raw(RAW)


def test_file_matches_the_brief(df):
    assert df.shape == (4245, 409)
    assert df["PLAYER_ID"].nunique() == 700
    assert df["DATE"].nunique() == 180


def test_grain_key_is_unique(df):
    assert not df.duplicated(["DATE", "PLAYER_ID", "PLATFORM_ID"]).any()


def test_audit_and_registry_run_end_to_end(df):
    reg = registry.with_categories(registry.build_registry(df, audit.column_profile(df)))
    assert reg["category"].notna().all()
    assert len(audit.quality_issues(df)) == 6
    assert not reg.set_index("column").loc["D90_RETURNER", "model_feature"]


def test_snapshot_covers_every_player_seen_so_far(df):
    reg = registry.build_registry(df, audit.column_profile(df))
    snap = asof.snapshot_as_of(asof.rollup_player_day(df, reg), "2026-10-31")
    assert snap["PLAYER_ID"].is_unique
    assert len(snap) == df.loc[df["DATE"] <= "2026-10-31", "PLAYER_ID"].nunique()
