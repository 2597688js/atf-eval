"""Shared N/A-aware weighting rules, reused at every level the spec calls
"Both" or "Overall" (turn composites, turn->conversation rollups, and the
top-level ATF formula in spec §15) rather than duplicated per metric group.
"""
from __future__ import annotations

DEFAULT_WEIGHTS = {"nts": 0.30, "sts": 0.30, "tis": 0.15, "rs": 0.10, "os": 0.15}


def weighted_composite(components: dict[str, float | None], weights: dict[str, float]) -> float | None:
    """Σ(weight*score) / Σ(weight) over components whose score is not None.

    None components are excluded from both numerator and denominator (the
    remaining weights are implicitly renormalized) rather than treated as 0.
    Returns None if every component is None.
    """
    total_weight = 0.0
    total_score = 0.0
    for key, score in components.items():
        if score is None:
            continue
        weight = weights[key]
        total_weight += weight
        total_score += weight * score

    if total_weight == 0.0:
        return None
    return total_score / total_weight


def aggregate_turns(turn_scores: list[float | None], turn_weight: float = 1.0) -> float | None:
    """Σ(score*turn_weight) / Σ(turn_weight) over non-None turn scores (spec §7.5)."""
    applicable = [s for s in turn_scores if s is not None]
    if not applicable:
        return None
    return sum(s * turn_weight for s in applicable) / (len(applicable) * turn_weight)


def atf_score(
    group_scores: dict[str, float | None], weights: dict[str, float]
) -> tuple[float | None, float]:
    """Spec §15/§16: ATF weighted mean over applicable groups + metric coverage."""
    total_weight = sum(weights.values())
    applicable_weight = sum(
        weights[key] for key, score in group_scores.items() if score is not None
    )
    metric_coverage = applicable_weight / total_weight if total_weight else 0.0
    atf = weighted_composite(group_scores, weights)
    return atf, metric_coverage
