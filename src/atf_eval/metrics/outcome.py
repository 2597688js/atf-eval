"""Outcome Similarity (OS) — spec §11. Conversation-level only.

The expected/observed outcome for a conversation is the last non-null
`Outcome` across its turns, since (per the spec) the final business outcome
usually isn't determinable from a single turn.
"""
from __future__ import annotations

from atf_eval.aggregate import weighted_composite
from atf_eval.matching import values_match
from atf_eval.metric_result import MetricResult, make_result
from atf_eval.normalized import NormalizedTurn, Outcome

_OS_WEIGHTS = {"identity": 0.50, "attribute": 0.30, "completion": 0.20}


def last_outcome(turns: list[NormalizedTurn]) -> Outcome | None:
    for turn in reversed(turns):
        if turn.outcome is not None:
            return turn.outcome
    return None


def outcome_identity_accuracy(expected: Outcome | None, observed: Outcome | None) -> float | None:
    if expected is None or expected.id is None:
        return None
    if observed is None:
        return 0.0
    return 1.0 if observed.id == expected.id else 0.0


def outcome_attribute_accuracy(
    expected: Outcome | None, observed: Outcome | None, tolerance: float = 0.0
) -> float | None:
    if expected is None or not expected.attributes:
        return None
    if observed is None:
        return 0.0
    matched = sum(
        1
        for k, v in expected.attributes.items()
        if k in observed.attributes and values_match(v, observed.attributes[k], tolerance)
    )
    return matched / len(expected.attributes)


def outcome_completion(
    expected: Outcome | None, observed: Outcome | None, tolerance: float = 0.0
) -> float | None:
    if expected is None or not expected.required_conditions:
        return None
    if observed is None:
        return 0.0
    satisfied = sum(
        1
        for key in expected.required_conditions
        if key in expected.attributes
        and key in observed.attributes
        and values_match(expected.attributes[key], observed.attributes[key], tolerance)
    )
    return satisfied / len(expected.required_conditions)


def os_conversation(
    expected_turns: list[NormalizedTurn],
    observed_turns: list[NormalizedTurn],
    tolerance: float = 0.0,
) -> float | None:
    expected_outcome = last_outcome(expected_turns)
    observed_outcome = last_outcome(observed_turns)
    components = {
        "identity": outcome_identity_accuracy(expected_outcome, observed_outcome),
        "attribute": outcome_attribute_accuracy(expected_outcome, observed_outcome, tolerance),
        "completion": outcome_completion(expected_outcome, observed_outcome, tolerance),
    }
    return weighted_composite(components, _OS_WEIGHTS)


def os_conversation_result(
    expected_turns: list[NormalizedTurn],
    observed_turns: list[NormalizedTurn],
    tolerance: float = 0.0,
    availability_status: str = "available",
) -> MetricResult:
    """METRICS.md §8-shaped result for overall OS."""
    score = os_conversation(expected_turns, observed_turns, tolerance)
    expected_outcome = last_outcome(expected_turns)
    observed_outcome = last_outcome(observed_turns)

    return make_result(
        "os",
        score,
        availability_status,
        diagnostics={
            "expected_id": expected_outcome.id if expected_outcome else None,
            "observed_id": observed_outcome.id if observed_outcome else None,
        },
    )
