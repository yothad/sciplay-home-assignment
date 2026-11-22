"""LTV features, labels and split: the as-of rule for a day-7 forecast."""

import pandas as pd
import pytest

from sciplay.ltv import checks, config as C, features as F, labels, split


def _pday():
    rows = []
    for pid, install, paid_day in [(1, "2026-05-10", 2), (2, "2026-08-05", 9), (3, "2026-10-20", None)]:
        for d in range(0, 12):
            date = pd.Timestamp(install) + pd.Timedelta(days=d)
            rev = 5.0 if d == paid_day else None
            rows.append({"PLAYER_ID": pid, "DATE": date, "INSTALL_DATE": pd.Timestamp(install),
                         "REVENUE": rev, "SESSIONS": 2, "SPINS_COMPLETED": 10 * (d + 1),
                         "END_LEVEL": d + 1, "CRASHES": 0, "SPINNER": 1, "COUNTRY": "US",
                         # planted leak: on every row, the player's revenue over days 0-29
                         "LEAKY_REVENUE": 5.0 if paid_day is not None else None})
    return pd.DataFrame(rows)


SPEC = F.FeatureSpec(count=["SPINS_COMPLETED", "SESSIONS"], state=["END_LEVEL"], friction=["CRASHES"],
                     flag=["SPINNER"], categorical=["COUNTRY"])


def test_split_by_install_date_and_complete_labels():
    inst = split.install_dates(_pday())
    sets = split.assign_sets(inst, data_end="2026-11-04")
    assert sets.to_dict() == {1: "train", 2: "test", 3: "inference"}


def test_label_is_observed_first_week_plus_remainder():
    p = _pday()
    lab = labels.label_frame(p, split.install_dates(p), data_end="2026-11-04")
    assert lab.loc[1, "revenue_first_k"] == 5.0 and lab.loc[1, "target_remainder"] == 0.0
    assert lab.loc[2, "revenue_first_k"] == 0.0 and lab.loc[2, "target_remainder"] == 5.0
    assert not lab.loc[3, "complete"] and pd.isna(lab.loc[3, "target_remainder"])


def test_features_read_only_the_first_k_days():
    p = _pday()
    inst = split.install_dates(p)
    X = F.build_features(p, inst, SPEC)
    assert X.loc[2, "revenue_first_k"] == 0.0            # paid on day 9: outside the window
    assert X.loc[1, "SPINS_COMPLETED__sum"] == sum(10 * (d + 1) for d in range(C.K))
    assert X.loc[1, "END_LEVEL__last"] == C.K and X.loc[1, "END_LEVEL__change"] == C.K - 1
    assert (X["feature_date"] == inst + pd.Timedelta(days=C.K - 1)).all()
    assert checks.truncation_check(p, inst, SPEC)


def test_future_revenue_check_catches_a_rewritten_column():
    p = _pday()
    res = checks.future_revenue_check(p, split.install_dates(p), ["LEAKY_REVENUE", "REVENUE"]).set_index("column")
    assert res.loc["LEAKY_REVENUE", "rows_ahead"] > 0
    assert res.loc["REVENUE", "rows_ahead"] == 0


def test_rare_category_levels_become_other():
    X = pd.DataFrame({"COUNTRY": ["US"] * 25 + ["FR"] * 3})
    out = F.CategoryEncoder(["COUNTRY"], min_players=20).fit(X).transform(X)
    assert list(out.columns) == ["COUNTRY=US", "COUNTRY=Other"]
    assert out["COUNTRY=Other"].sum() == 3


def test_multiplier_is_the_stated_assumption():
    assert C.multiplier() == pytest.approx(2.494, abs=0.001)
    assert C.multiplier(0.5) == pytest.approx(2.0, abs=0.001)
