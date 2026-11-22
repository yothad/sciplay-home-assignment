"""Refresh: first build, incremental merge with restated rows, no new data, health gate."""

import json

import pandas as pd
import pytest

from sciplay.pipeline.refresh import Paths, refresh


@pytest.fixture
def env(tmp_path, sample):
    raw = tmp_path / "raw"
    (raw / "incoming").mkdir(parents=True)
    base = raw / "base.csv"
    sample.to_csv(base, index=False)
    paths = Paths(incoming=raw / "incoming", extracts=raw / "extracts", processed=tmp_path / "processed",
                  staging=tmp_path / "processed" / "_staging", log=tmp_path / "store" / "refresh_log.jsonl")
    return paths, base, sample


def _extract(paths: Paths, rows: pd.DataFrame, name: str) -> None:
    rows.to_csv(paths.incoming / name, index=False)


def _manifest(paths: Paths) -> dict:
    return json.loads((paths.processed / "manifest.json").read_text())


def test_first_run_publishes_the_base_file(env):
    paths, base, _ = env
    res = refresh(paths, base_file=base)
    assert res.status == "published" and res.exit_code == 0
    assert _manifest(paths)["data_end"] == "2026-10-03"
    assert len(list(paths.extracts.glob("*.csv"))) == 1


def test_rerun_without_new_data_publishes_nothing(env):
    paths, base, _ = env
    refresh(paths, base_file=base)
    before = (paths.processed / "manifest.json").read_text()
    res = refresh(paths, base_file=base)
    assert res.status == "no_new_data" and res.exit_code == 2
    assert (paths.processed / "manifest.json").read_text() == before


def test_incremental_extract_adds_days_and_applies_restated_rows(env):
    paths, base, sample = env
    refresh(paths, base_file=base)
    new_day = sample[sample["PLAYER_ID"] == 1].tail(1).copy()
    new_day["DATE"] = pd.Timestamp("2026-10-04")
    new_day["LIFETIME_REVENUE"] = 10.0
    new_day["LAST_UPDATE_DATETIME"] = pd.Timestamp("2026-10-05")
    restated = sample[(sample["PLAYER_ID"] == 1) & (sample["DATE"] == "2026-10-03")].copy()
    restated["SESSIONS"] = 9
    restated["LAST_UPDATE_DATETIME"] = pd.Timestamp("2026-10-10 06:30:00")  # different timestamp format on purpose
    _extract(paths, pd.concat([new_day, restated]), "extract_2.csv")
    res = refresh(paths, base_file=base)
    assert res.status == "published"
    assert res.rows_replaced_by_newer_version == 1
    assert not list(paths.incoming.glob("*.csv"))  # consumed
    pday = pd.read_parquet(paths.processed / "player_day.parquet")
    assert pday["DATE"].max() == pd.Timestamp("2026-10-04")
    assert pday.loc[(pday["PLAYER_ID"] == 1) & (pday["DATE"] == "2026-10-03"), "SESSIONS"].item() == 9


def test_health_gate_blocks_bad_data_and_keeps_yesterday(env):
    paths, base, sample = env
    refresh(paths, base_file=base)
    bad = sample.head(2).copy()
    bad["DATE"] = pd.Timestamp("2026-10-05")
    bad["REVENUE"] = -5.0
    bad["LAST_UPDATE_DATETIME"] = pd.Timestamp("2026-10-06")
    _extract(paths, bad, "extract_bad.csv")
    res = refresh(paths, base_file=base)
    assert res.status == "blocked" and res.exit_code == 1
    assert "Negative revenue" in res.failed_checks
    assert _manifest(paths)["data_end"] == "2026-10-03"
    log = [json.loads(line) for line in paths.log.read_text().splitlines()]
    assert [r["status"] for r in log] == ["published", "blocked"]
