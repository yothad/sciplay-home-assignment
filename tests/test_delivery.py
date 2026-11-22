import json

import pandas as pd
import pytest

from sciplay.delivery import config as C
from sciplay.delivery import payloads as P
from sciplay.delivery import run as DR
from sciplay.delivery import store as S
from sciplay.delivery import summary as SM
from sciplay.delivery import triggers as TR
from sciplay.lists import config as L


def _row(date, pid, lst=L.REVENUE, pr="medium", gap=5.0):
    return {"score_date": date, "player_id": pid, "list_type": lst, "priority": pr, "underperformance_score": 80.0,
            "predicted_ltv_365": 10.0, "ltv_to_date": 2.0, "opportunity_gap": gap, "reason_codes": "revenue_overdue",
            "reason_text": "No purchase for 9 days; usually every 2 days", "recommended_action": "offer",
            "ltv_source": "model", "data_incomplete": 0, "model_rules_version": "v1", "created_at": "x"}


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(DR, "outbox_dir", lambda: tmp_path / "outbox")
    return tmp_path / "d.sqlite"


def test_new_high_priority_and_large_gap_fire_on_entry_only():
    h = pd.DataFrame([_row("2026-11-03", 1, pr="high", gap=150), _row("2026-11-04", 1, pr="high", gap=150),
                      _row("2026-11-04", 2, pr="high", gap=150)])
    run_row = pd.Series({"data_incomplete": 0, "message": ""})
    kinds = {(e.kind, e.players[0]["player_id"]) for e in TR.events("2026-11-04", h, run_row) if e.players}
    assert kinds == {("new_high_priority", 2), ("large_player_gap", 2)}


def test_data_incomplete_suppresses_team_alerts():
    h = pd.DataFrame([_row("2026-11-04", 2, pr="high", gap=150)])
    ev = TR.events("2026-11-04", h, pd.Series({"data_incomplete": 1, "message": "rows missing"}))
    assert [e.kind for e in ev] == ["data_incomplete"]


def test_escalation_after_two_days_without_action(monkeypatch):
    monkeypatch.setattr(C, "GO_LIVE", "2026-11-01")
    h = pd.DataFrame([_row("2026-11-03", 1), _row("2026-11-04", 1), _row("2026-11-04", 2),
                      _row("2026-11-03", 3, pr="low"), _row("2026-11-04", 3, pr="low"),
                      _row("2026-11-03", 4), _row("2026-11-04", 4)])
    acts = pd.DataFrame([{"score_date": "2026-11-03", "player_id": 4, "list_type": L.REVENUE}])
    od = TR.overdue("2026-11-04", h, acts)
    assert list(od["player_id"]) == [1]          # 2: one day only; 3: low priority; 4: acted on


def test_go_live_resets_the_clock(monkeypatch):
    monkeypatch.setattr(C, "GO_LIVE", "2026-11-04")
    h = pd.DataFrame([_row("2026-11-03", 1), _row("2026-11-04", 1)])
    assert TR.overdue("2026-11-04", h, pd.DataFrame(columns=["score_date", "player_id", "list_type"])).empty


def test_send_is_idempotent_and_retries(db):
    s = DR.Sender("2026-11-04", fail_first={"k1": 2}, db=db)
    assert s.send("slack", "k1", "test", "#c", {"a": 1}) == "sent"
    assert s.send("slack", "k1", "test", "#c", {"a": 1}) == "duplicate_skipped"
    row = S.read("deliveries", db).iloc[0]
    assert row["attempts"] == 3 and row["status"] == "sent"
    s2 = DR.Sender("2026-11-04", fail_first={"k2": 5}, db=db)
    assert s2.send("slack", "k2", "test", "#c", {}) == "failed" and s2.failed == ["k2"]


def test_ticket_opened_once_and_cooldown_after_resolution(db):
    t = {"ticket_id": "t1", "game_id": "test", "list_type": L.FRICTION, "player_id": 7, "queue": "q",
         "opened_date": "2026-11-03", "status": "open", "closed_date": None, "close_reason": None,
         "priority": "medium", "payload": "{}"}
    assert S.open_ticket(t, db) and not S.open_ticket(t | {"ticket_id": "t2", "priority": "high"}, db)
    assert S.read("tickets", db).iloc[0]["priority"] == "high"
    S.close_ticket(7, L.FRICTION, "2026-11-03", "resolved by owner", db)
    assert not S.open_ticket(t | {"ticket_id": "t3", "opened_date": "2026-11-05"}, db)
    assert S.open_ticket(t | {"ticket_id": "t4", "opened_date": "2026-11-12"}, db)


def _facts():
    today = pd.DataFrame([_row("2026-11-04", 1, pr="high", gap=20), _row("2026-11-04", 2, L.FRICTION, gap=0)])
    return SM.facts("2026-11-04", "test", today, today.iloc[0:0], 0)


def test_template_summary_is_valid_and_grounded():
    s = SM.template(_facts())
    assert s.headline.startswith("2 players") and len(s.bullets) <= 4


@pytest.mark.parametrize("bad", [
    {"headline": "5 players need attention.", "bullets": [], "data_status": "complete"},                 # wrong number
    {"headline": "2 players, due to a bug.", "bullets": [], "data_status": "complete"},                  # causal claim
    {"headline": "2 players.", "bullets": [], "data_status": "incomplete"},                              # status mismatch
    "not json",
])
def test_llm_output_rejected_falls_back_to_template(bad):
    f = _facts()
    s, src = SM.summarize(f, llm=lambda prompt: bad if isinstance(bad, str) else json.dumps(bad))
    assert src == "template" and s == SM.template(f)


def test_llm_output_accepted_when_grounded():
    good = {"headline": "2 players need attention today, $20.00 of value at risk.",
            "bullets": ["Revenue decline: 1 player (1 high priority)."], "data_status": "complete"}
    s, src = SM.summarize(_facts(), llm=lambda prompt: json.dumps(good))
    assert src == "llm" and s.headline == good["headline"]


def test_prompt_contains_facts_and_rules():
    seen = {}
    SM.summarize(_facts(), llm=lambda p: seen.setdefault("p", p) and "x")
    assert '"players_total": 2' in seen["p"] and "Do not explain why" in seen["p"]


def test_deep_links():
    assert P.deep_link("2026-11-04", L.REVENUE).endswith("Who_needs_attention?date=2026-11-04&list=Revenue+decline")
    assert P.deep_link("2026-11-04", player_id=5).endswith("Player_detail?date=2026-11-04&player=5")


def test_quiet_hours():
    assert DR.in_quiet_hours(22) and DR.in_quiet_hours(6) and not DR.in_quiet_hours(8) and not DR.in_quiet_hours(20)


def test_player_events_grouped_and_not_repeated(db):
    h = pd.DataFrame([_row("2026-11-04", 1, pr="high"), _row("2026-11-04", 2, pr="high")])
    lists_db = db.parent / "l.sqlite"
    from sciplay.lists import run as LR
    LR.write(h, {"score_date": "2026-11-04", "model_rules_version": "v1", "status": "ok", "data_incomplete": 0,
                 "eligible": 2, "listed": 2, "list_sizes": "{}", "ineligible": "{}", "failed_checks": "[]",
                 "message": "", "created_at": "2026-11-04T06:00:00"}, lists_db)
    r1 = DR.deliver("2026-11-04", "refresh", hour=10, db=db, lists_db=lists_db)
    assert len(r1["sent"]) == 1                                  # two players, one message
    r2 = DR.deliver("2026-11-04", "refresh", hour=10, db=db, lists_db=lists_db)
    assert r2["sent"] == [] and r2["skipped"] == []              # members already alerted: nothing new
    r3 = DR.deliver("2026-11-04", "refresh", hour=23, db=db, lists_db=lists_db)
    assert r3["held"] == 0


def test_daily_alert_limit(db, monkeypatch):
    monkeypatch.setattr(C, "MAX_ALERTS_PER_DAY", 0)
    h = pd.DataFrame([_row("2026-11-04", 1, pr="high")])
    lists_db = db.parent / "l.sqlite"
    from sciplay.lists import run as LR
    LR.write(h, {"score_date": "2026-11-04", "model_rules_version": "v1", "status": "ok", "data_incomplete": 0,
                 "eligible": 1, "listed": 1, "list_sizes": "{}", "ineligible": "{}", "failed_checks": "[]",
                 "message": "", "created_at": "2026-11-04T06:00:00"}, lists_db)
    r = DR.deliver("2026-11-04", "refresh", hour=10, db=db, lists_db=lists_db)
    assert r["capped"] == 1 and r["sent"] == []
    DR.deliver("2026-11-04", "evening", db=db, lists_db=lists_db)
    body = json.loads((db.parent / "outbox" / "2026-11-04" / "email" / "2026-11-04_email_evening_test.json").read_text())
    assert "over the daily limit" in body["body_markdown"]
