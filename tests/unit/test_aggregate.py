from atf_eval.aggregate import DEFAULT_WEIGHTS, atf_score, weighted_composite


def test_weighted_composite_excludes_none_not_zero():
    # STS missing entirely (None) must renormalize the remaining weights,
    # not drag the composite down as if STS scored 0.
    components = {"nts": 1.0, "sts": None}
    weights = {"nts": 0.5, "sts": 0.5}
    assert weighted_composite(components, weights) == 1.0


def test_weighted_composite_all_none_is_none():
    assert weighted_composite({"nts": None, "sts": None}, {"nts": 0.5, "sts": 0.5}) is None


def test_atf_score_coverage_renormalizes_around_na_groups():
    group_scores = {"nts": 1.0, "sts": 1.0, "tis": None, "rs": 1.0, "os": 1.0}
    atf, coverage = atf_score(group_scores, DEFAULT_WEIGHTS)
    assert atf == 1.0
    assert coverage == (0.30 + 0.30 + 0.10 + 0.15) / 1.0


def test_atf_score_all_na_is_none_zero_coverage():
    group_scores = {k: None for k in DEFAULT_WEIGHTS}
    atf, coverage = atf_score(group_scores, DEFAULT_WEIGHTS)
    assert atf is None
    assert coverage == 0.0
