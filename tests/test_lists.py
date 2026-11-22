"""Daily lists: exclusivity, precedence, reasons, boundary thresholds, idempotent persistence, edge cases."""

import json

import numpy as np
import pandas as pd
import pytest

from sciplay.lists import config as L, rules, run as R


def _sig(n=4, **cols):
    """A minimal signals frame: n eligible players, nothing triggered unless set."""
    base = {
        "eligible": True, "any_friction": False, "any_revenue": False, "any_engagement": False,
        "friction_triggers": "", "friction_events": 0.0, "recent_cancellations": 0.0, "recent_failed_purchases": 0.0,
        "rev_spend_drop": False, "rev_overdue": False, "rev_behind_forecast": False, "rev_valuable_losing_activity": False,
        "spend_last_28d": 0.0, "spend_prev_28d": 0.0, "spend_drop_share": np.nan, "days_since_purchase": np.nan,
        "usual_purchase_gap": np.nan, "behind_forecast_dollars": np.nan, "ltv_to_date": 0.0, "predicted_ltv_365": 1.0,
        "eng_days_drop": False, "eng_sessions_drop": False, "eng_young_vs_peers": False, "days_played_7d": 0.0,
        "baseline_days_per_week": 0.0, "sessions_7d": 0.0, "baseline_sessions_per_week": 0.0, "peer_days_7d": np.nan,
        "activity_drop_share": np.nan, "opportunity_gap": 0.0, "source": "update_rule",
        "eng_overdue_return": False, "days_since_last_seen": 0.0, "usual_play_gap": np.nan,
    }
    df = pd.DataFrame({k: [v] * n for k, v in base.items()}, index=pd.Index(range(1, n + 1), name="player_id"))
    for k, v in cols.items():
        df[k] = v
    return df


def test_one_primary_list_and_precedence():
    sig = _sig(4, any_friction=[True, False, False, False], any_revenue=[True, True, False, False],
               any_engagement=[True, True, True, False], friction_triggers=["crashes:2", "", "", ""])
    lt = rules.primary_list(sig)
    assert lt.tolist() == [L.FRICTION, L.REVENUE, L.ENGAGEMENT, ""]
    assert (lt[lt != ""].groupby(level=0).size() == 1).all()          # mutually exclusive


def test_ineligible_players_are_never_listed():
    sig = _sig(2, eligible=[False, True], any_engagement=True, eng_days_drop=True)
    assert rules.primary_list(sig).tolist() == ["", L.ENGAGEMENT]


def test_reasons_are_readable_and_cover_every_signal():
    sig = _sig(1, any_friction=True, friction_triggers="crashes:1|incomplete purchase attempts:3", any_revenue=True,
               rev_spend_drop=True, spend_last_28d=20.0, spend_prev_28d=100.0, spend_drop_share=0.8,
               any_engagement=True, eng_sessions_drop=True, sessions_7d=1.0, baseline_sessions_per_week=9.0)
    rs = rules.reasons(sig.iloc[0])
    codes = [c for c, _ in rs]
    assert codes == ["friction_crashes", "friction_incomplete_purchase", "revenue_spend_drop", "engagement_sessions_drop"]
    texts = [t for _, t in rs]
    assert texts[0] == "1 crash in the last 7 days (more than usual)"
    assert "-80%" in texts[2] and texts[3].startswith("1 session in the last 7 days vs 9")
    assert rules.recommended_action(codes, L.REVENUE).startswith("CRM / VIP")
    assert rules.recommended_action(codes, L.FRICTION).startswith("Tech support")


@pytest.mark.parametrize("recent, baseline, triggered", [(50.0, 100.0, True), (50.01, 100.0, False), (0.0, 0.0, False)])
def test_spend_drop_boundary_is_inclusive(recent, baseline, triggered):
    from sciplay.lists.signals import is_drop
    assert bool(is_drop([recent], [baseline], L.SPEND_DROP)[0]) is triggered


@pytest.mark.parametrize("days, gap, triggered", [(8, 4.0, False), (8.5, 4.0, True), (6, 2.0, False), (7, 1.0, True),
                                                   (21, 1.0, True), (22, 1.0, False), (np.nan, np.nan, False)])
def test_overdue_return_boundaries(days, gap, triggered):
    from sciplay.lists.signals import is_overdue
    assert bool(is_overdue([days], [gap], L.RETURN_FACTOR, L.RETURN_MIN_DAYS, L.RETURN_MAX_DAYS)[0]) is triggered


def test_missing_inputs_are_handled(monkeypatch):
    from sciplay.ltv import train as T
    def boom(*a, **k):
        raise FileNotFoundError("player_day.parquet")
    monkeypatch.setattr(T, "load_data", boom)
    res = R.run("2026-11-04", store=False)
    assert res["status"] == "missing_input" and res["lists"].empty


def test_priority_dollars_first_then_severity():
    lt = pd.Series([L.REVENUE, L.ENGAGEMENT, L.ENGAGEMENT, L.FRICTION, L.REVENUE], index=range(1, 6))
    sig = _sig(5, opportunity_gap=[25.0, 0.0, 0.0, 0.0, 2.0], friction_triggers=["", "", "", "incomplete purchase attempts:2", ""])
    score = pd.Series([10.0, 80.0, 40.0, 50.0, 10.0], index=range(1, 6))
    assert rules.priority(sig, lt, score).tolist() == ["high", "medium", "low", "medium", "medium"]
    sig2 = _sig(1, opportunity_gap=[L.PRIORITY_HIGH - 0.01])
    assert rules.priority(sig2, pd.Series([L.REVENUE], index=[1]), pd.Series([0.0], index=[1])).tolist() == ["medium"]


def test_persistence_is_idempotent(tmp_path):
    db = tmp_path / "s.sqlite"
    row = {c: None for c in R.COLUMNS}
    row.update(score_date="2026-11-04", player_id=1, list_type=L.ENGAGEMENT, priority="low", model_rules_version="v")
    lists = pd.DataFrame([row, {**row, "player_id": 2}])[R.COLUMNS]
    run_row = {c: None for c in R.RUN_COLUMNS}
    run_row.update(score_date="2026-11-04", model_rules_version="v", status="ok", list_sizes="{}", created_at="a")
    R.write(lists, run_row, db)
    R.write(lists, run_row, db)                         # same date and version twice
    assert len(R.read("2026-11-04", db)) == 2
    R.write(lists.iloc[[0]], run_row, db)               # a rerun where player 2 left the list
    assert R.read("2026-11-04", db)["player_id"].tolist() == [1]
    assert len(R.read(None, db, table=R.RUNS)) == 1
    run_v2 = {**run_row, "model_rules_version": "v2", "created_at": "z"}       # a new rules version
    R.write(lists.assign(model_rules_version="v2"), run_v2, db)
    assert R.read("2026-11-04", db)["model_rules_version"].unique().tolist() == ["v2"]   # latest version shown
    assert len(R.read("2026-11-04", db, version=None)) == 3                             # history per version kept


from sciplay.config import REPO_ROOT, get_settings  # noqa: E402

REAL = (get_settings().processed_dir / "player_day.parquet").exists() and (REPO_ROOT / "models" / "ltv" / "active.json").exists()


@pytest.mark.skipif(not REAL, reason="needs prepared data and a trained LTV model")
def test_real_run_edge_cases(tmp_path, monkeypatch):
    from sciplay.ltv import train as T
    data = T.load_data()
    db = tmp_path / "s.sqlite"
    res = R.run("2026-11-04", data, db_path=db)
    lists = R.read("2026-11-04", db)
    assert res["status"] == "ok" and len(lists) == res["listed"] > 0
    assert lists["player_id"].is_unique                                  # one primary list per player
    assert set(lists["list_type"]) <= set(L.PRECEDENCE)
    R.run("2026-11-04", data, db_path=db)                               # rerun: no duplicates
    assert len(R.read("2026-11-04", db)) == len(lists)
    assert R.run("2026-11-30", data, db_path=db)["status"] == "no_data"  # after the data end: nothing listed
    assert R.read("2026-11-30", db).empty

    def failing(pday, D, raw=None):
        return pd.DataFrame({"check": ["Rows have landed for the date"], "status": ["fail"]})
    monkeypatch.setattr(R, "run_checks", failing)
    late = R.run("2026-11-03", data, db_path=db)                        # late data: published, flagged
    assert late["status"] == "ok_data_incomplete"
    assert R.read("2026-11-03", db)["data_incomplete"].eq(1).all()


def test_order_is_money_first_priority_then_ltv_then_score():
    from sciplay.lists.rules import order_players
    df = pd.DataFrame({"player_id": [1, 2, 3, 4, 5],
                       "priority": ["medium", "high", "medium", "medium", "low"],
                       "predicted_ltv_365": [5.0, 1.0, 50.0, 5.0, 999.0],
                       "underperformance_score": [90.0, 10.0, 20.0, 95.0, 100.0]})
    assert list(order_players(df)["player_id"]) == [2, 3, 4, 1, 5]
