"""Node Traversal Similarity (NTS) — METRICS.md §2.

Alignment is position-aware LCS alignment (missing/extra/reordered nodes
identified without cascading later nodes into failures), not a bag-of-words
multiset count.
"""
from __future__ import annotations

from atf_eval import lcs
from atf_eval.aggregate import weighted_composite
from atf_eval.metric_result import MetricResult, make_result
from atf_eval.normalized import NormalizedTurn

_NTS_WEIGHTS = {"coverage": 0.40, "precision": 0.30, "order": 0.30}


def _matched_count(expected: list[str], observed: list[str]) -> int:
    pairs = lcs.align(expected, observed)
    return sum(1 for i, j in pairs if i is not None and j is not None)


def node_coverage(expected: list[str], observed: list[str]) -> float | None:
    if not expected:
        return None
    return _matched_count(expected, observed) / len(expected)


def node_precision(expected: list[str], observed: list[str]) -> float | None:
    if not observed:
        return None
    return _matched_count(expected, observed) / len(observed)


def node_recall(expected: list[str], observed: list[str]) -> float | None:
    """Diagnostic only -- identical to coverage under the frozen definitions."""
    return node_coverage(expected, observed)


def node_order_similarity(expected: list[str], observed: list[str]) -> float | None:
    return lcs.order_similarity(expected, observed)


def _nts(expected_ids: list[str], observed_ids: list[str]) -> float | None:
    components = {
        "coverage": node_coverage(expected_ids, observed_ids),
        "precision": node_precision(expected_ids, observed_ids),
        "order": node_order_similarity(expected_ids, observed_ids),
    }
    return weighted_composite(components, _NTS_WEIGHTS)


def nts_turn(expected: NormalizedTurn, observed: NormalizedTurn) -> float | None:
    """Turn-level diagnostic score (METRICS.md §2 "Levels": turn-level
    diagnostics + overall trajectory score -- this is the turn-level half)."""
    expected_ids = [n.node_id for n in expected.nodes]
    observed_ids = [n.node_id for n in observed.nodes]
    return _nts(expected_ids, observed_ids)


def nts_conversation(
    expected_turns: list[NormalizedTurn], observed_turns: list[NormalizedTurn]
) -> float | None:
    """Overall NTS computed from the complete concatenated trajectory, not a
    turn-score average (METRICS.md §2, Frozen Rule #10)."""
    expected_ids = [n.node_id for t in expected_turns for n in t.nodes]
    observed_ids = [n.node_id for t in observed_turns for n in t.nodes]
    return _nts(expected_ids, observed_ids)


def nts_conversation_result(
    expected_turns: list[NormalizedTurn],
    observed_turns: list[NormalizedTurn],
    availability_status: str = "available",
) -> MetricResult:
    """METRICS.md §8-shaped result for overall NTS."""
    expected_ids = [n.node_id for t in expected_turns for n in t.nodes]
    observed_ids = [n.node_id for t in observed_turns for n in t.nodes]
    score = _nts(expected_ids, observed_ids)

    pairs = lcs.align(expected_ids, observed_ids)
    missing = [expected_ids[i] for i, j in pairs if j is None and i is not None]
    extra = [observed_ids[j] for i, j in pairs if i is None and j is not None]
    matched = [expected_ids[i] for i, j in pairs if i is not None and j is not None]

    return make_result(
        "nts",
        score,
        availability_status,
        diagnostics={"matched": matched, "missing": missing, "extra": extra},
    )
