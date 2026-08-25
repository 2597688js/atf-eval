"""Tool Invocation Similarity (TIS) — spec §9.

Coverage/precision are multiset-based (presence, order-independent). Identity
accuracy and input similarity are computed over *positionally paired*
expected/observed calls (zip up to the shorter list) since "invocation"
implies order-matched pairing distinct from set-based coverage.
"""
from __future__ import annotations

from collections import Counter

from atf_eval import lcs
from atf_eval.aggregate import weighted_composite
from atf_eval.matching import values_match
from atf_eval.metric_result import MetricResult, make_result
from atf_eval.normalized import NormalizedTurn, ToolCall

_TIS_WEIGHTS = {
    "coverage": 0.25,
    "precision": 0.20,
    "identity": 0.25,
    "input": 0.20,
    "order": 0.10,
}


def _multiset_overlap(expected: list[str], observed: list[str]) -> int:
    a, b = Counter(expected), Counter(observed)
    return sum((a & b).values())


def argument_match(expected_args: dict, observed_args: dict, tolerance: float = 0.0) -> float:
    if not expected_args:
        return 1.0  # nothing was required of this call, so nothing to get wrong
    matched = sum(
        1
        for k, v in expected_args.items()
        if k in observed_args and values_match(v, observed_args[k], tolerance)
    )
    return matched / len(expected_args)


def tool_coverage(expected: list[str], observed: list[str]) -> float | None:
    if not expected:
        return None
    return _multiset_overlap(expected, observed) / len(expected)


def tool_precision(expected: list[str], observed: list[str]) -> float | None:
    if not observed:
        return None
    return _multiset_overlap(expected, observed) / len(observed)


def tool_identity_accuracy(expected: list[ToolCall], observed: list[ToolCall]) -> float | None:
    """METRICS.md §4: denominator is "Aligned Tool Pairs", not total expected
    calls -- differs from Coverage when observed has fewer calls than expected."""
    pairs = list(zip(expected, observed))
    if not pairs:
        return None
    correct = sum(1 for e, o in pairs if e.tool_id == o.tool_id)
    return correct / len(pairs)


def tool_input_similarity(
    expected: list[ToolCall], observed: list[ToolCall], tolerance: float = 0.0
) -> float | None:
    pairs = list(zip(expected, observed))
    if not pairs:
        return None
    total = sum(argument_match(e.arguments, o.arguments, tolerance) for e, o in pairs)
    return total / len(pairs)


def tool_order_similarity(expected: list[str], observed: list[str]) -> float | None:
    return lcs.order_similarity(expected, observed)


def _tis(exp_calls: list[ToolCall], obs_calls: list[ToolCall], tolerance: float) -> float | None:
    exp_names = [t.tool_id for t in exp_calls]
    obs_names = [t.tool_id for t in obs_calls]
    components = {
        "coverage": tool_coverage(exp_names, obs_names),
        "precision": tool_precision(exp_names, obs_names),
        "identity": tool_identity_accuracy(exp_calls, obs_calls),
        "input": tool_input_similarity(exp_calls, obs_calls, tolerance),
        "order": tool_order_similarity(exp_names, obs_names),
    }
    return weighted_composite(components, _TIS_WEIGHTS)


def tis_turn(
    expected: NormalizedTurn, observed: NormalizedTurn, tolerance: float = 0.0
) -> float | None:
    """Turn-level diagnostic score. Tools are aligned within corresponding
    nodes when node association is available; otherwise (as here, since no
    adapter currently attaches tool calls to a node) compared at turn level,
    per METRICS.md §4's Alignment fallback."""
    return _tis(expected.tool_calls, observed.tool_calls, tolerance)


def tis_conversation(
    expected_turns: list[NormalizedTurn], observed_turns: list[NormalizedTurn], tolerance: float = 0.0
) -> float | None:
    """Overall TIS computed from the complete trajectory, not a turn-score
    average (METRICS.md §4, Frozen Rule #10)."""
    exp_calls = [tc for t in expected_turns for tc in t.tool_calls]
    obs_calls = [tc for t in observed_turns for tc in t.tool_calls]
    return _tis(exp_calls, obs_calls, tolerance)


def tis_conversation_result(
    expected_turns: list[NormalizedTurn],
    observed_turns: list[NormalizedTurn],
    tolerance: float = 0.0,
    availability_status: str = "available",
) -> MetricResult:
    """METRICS.md §8-shaped result for overall TIS."""
    exp_calls = [tc for t in expected_turns for tc in t.tool_calls]
    obs_calls = [tc for t in observed_turns for tc in t.tool_calls]
    score = _tis(exp_calls, obs_calls, tolerance)

    exp_names = [t.tool_id for t in exp_calls]
    obs_names = [t.tool_id for t in obs_calls]
    missing = list((Counter(exp_names) - Counter(obs_names)).elements())
    extra = list((Counter(obs_names) - Counter(exp_names)).elements())

    return make_result(
        "tis",
        score,
        availability_status,
        diagnostics={"missing": missing, "extra": extra},
    )
