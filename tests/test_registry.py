"""Column registry: every column classified once, forward-looking columns never features."""

from sciplay.data import registry


def test_every_column_has_exactly_one_registry_row(sample, sample_registry):
    assert list(sample_registry["column"]) == list(sample.columns)


def test_forward_looking_and_invalid_target_columns_are_not_features(sample_registry):
    reg = sample_registry.set_index("column")
    for col in ["D1_RETURNER", "NEXT_LOGIN_DATE", "D365_SPEND"]:
        assert not reg.loc[col, "model_feature"], col


def test_categories_use_the_six_names_from_the_brief(sample_registry):
    reg = registry.with_categories(sample_registry)
    assert set(reg["category"]) <= set(registry.CATEGORIES)
    assert {"revenue_to_date", "revenue_next_30d", "ltv365"} <= set(reg["column"])
    assert reg.set_index("column").loc["PLAYER_ID", "category"] == registry.IDENTIFIERS
    assert reg.set_index("column").loc["D1_RETURNER", "category"] == registry.EXCLUDED


def test_returner_evidence_matches_synthetic_next_day_activity(sample):
    ev = registry.returner_label_evidence(sample, horizons=(1,)).iloc[0]
    assert ev["match_share"] == 1.0
