"""LTV scoring helpers: ranges, update rule, reasons, idempotent store."""

import numpy as np
import pandas as pd
import pytest

from sciplay.ltv import config as C, model as M, score as S, train as T


def test_scaled_range_always_contains_the_forecast():
    pred = np.array([12.0, 1.0, 0.0])
    boot = np.array([[1, 1, 0], [3, 2, 0], [5, 3, 0]], dtype=float)   # median 3, 2, 0
    lo, hi = T.scaled_range(pred, boot)
    assert (lo <= pred).all() and (pred <= hi).all()
    assert lo[0] == pytest.approx(12 * 2 / 3) and hi[0] == pytest.approx(12 * 4 / 3)
    assert lo[2] == hi[2] == 0.0


def test_update_rule_fades_and_stops_at_day_365():
    assert S.update_rule_remainder(100.0, age=364) == 0.0
    young = S.update_rule_remainder(100.0, age=59)
    left = (365 - 60) / 30                    # 10 full blocks + a sixth of one
    expected = sum(C.R ** j for j in range(1, 11)) + (left - 10) * C.R ** 11
    assert young == pytest.approx(100 * expected, rel=1e-6)


def test_remainder_share_runs_from_zero_to_one():
    curve = pd.Series(np.linspace(0.1, 1.0, C.HORIZON))
    assert S.remainder_share(curve, C.K - 1) == 0.0
    assert S.remainder_share(curve, C.HORIZON - 1) == pytest.approx(1.0)
    assert S.remainder_share(curve, 200) == pytest.approx(1.0)


def test_reasons_rank_by_absolute_shap_and_stop_at_coverage():
    w = pd.Series({"revenue_first_k": 0.8, "active_days": -0.15, "SESSIONS__sum": 0.05})
    eff = pd.Series({"revenue_first_k": 8.0, "active_days": -1.5, "SESSIONS__sum": 0.5})
    vals = pd.Series({"revenue_first_k": 12.0, "active_days": 1, "SESSIONS__sum": 3})
    rs = S.top_reasons(eff, w, vals, typical=pd.Series({"revenue_first_k": 0.0}))
    assert rs == ["Spent in the first 3 days: 12 vs typical 0 (+$8.00)"]      # 0.8 / 1.0 >= 70% coverage
    rs2 = S.top_reasons(pd.Series({"a": 1.0, "active_days": -1.5}), pd.Series({"a": 0.4, "active_days": -0.6}),
                        pd.Series({"a": 0, "active_days": 1}))
    assert rs2[0].startswith("Days played (of 3): 1") and "−$1.50" in rs2[0]


def test_dollar_effect_is_the_change_without_that_feature():
    sv = np.array([[np.log(2.0), 0.0]])          # feature 1 doubles the forecast
    eff = S.dollar_effects(sv, np.array([10.0]))
    assert eff[0, 0] == pytest.approx(5.0) and eff[0, 1] == 0.0


def test_store_is_idempotent(tmp_path):
    row = {c: None for c in S.COLUMNS}
    row.update(score_date="2026-11-04", player_id=1, model_version="v", predicted_ltv_365=5.0)
    df = pd.DataFrame([row])[S.COLUMNS]
    db = tmp_path / "s.sqlite"
    S.write(df, db)
    S.write(df.assign(predicted_ltv_365=6.0), db)
    out = S.read("2026-11-04", db)
    assert len(out) == 1 and out.loc[0, "predicted_ltv_365"] == 6.0


def test_metrics_dollar_recall_and_calibration():
    y = pd.Series([0, 0, 10.0, 30.0])
    p = pd.Series([0.1, 0.2, 5.0, 0.5])
    m = M.metrics(y, p)
    assert m["dollar_recall"] == pytest.approx(10 / 40) and m["payer_recall"] == 0.5
    assert m["pred_over_actual"] == pytest.approx(5.8 / 40)
