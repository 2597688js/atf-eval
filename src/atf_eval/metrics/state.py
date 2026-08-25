"""State Transition Similarity (STS) — METRICS.md §3.

State is evaluated from node-level `state_changes[]` (Frozen Rule #6): nodes
are aligned first (same LCS-based alignment used by NTS), then state changes
within each aligned node pair are compared and paired by key, in occurrence
order. Falls back to whole-turn key pairing only when neither side exposes
any nodes at all (an agent with no observable node structure).

Key/old/new-value accuracy are retained as diagnostics explaining transition
mismatches -- they are no longer part of the main weighted STS formula.
"""
from __future__ import annotations

from collections import defaultdict

from atf_eval import lcs
from atf_eval.aggregate import weighted_composite
from atf_eval.metric_result import MetricResult, make_result
from atf_eval.normalized import NormalizedNode, NormalizedTurn, StateChange

_STS_WEIGHTS = {"transition_accuracy": 0.70, "order": 0.30}


def _pair_by_key(
    expected: list[StateChange], observed: list[StateChange]
) -> list[tuple[StateChange, StateChange | None]]:
    observed_by_key: dict[str, list[StateChange]] = defaultdict(list)
    for oc in observed:
        observed_by_key[oc.key].append(oc)
    next_index: dict[str, int] = defaultdict(int)

    pairs: list[tuple[StateChange, StateChange | None]] = []
    for ec in expected:
        candidates = observed_by_key[ec.key]
        idx = next_index[ec.key]
        if idx < len(candidates):
            pairs.append((ec, candidates[idx]))
            next_index[ec.key] += 1
        else:
            pairs.append((ec, None))
    return pairs


def _aligned_node_pairs(
    expected: NormalizedTurn, observed: NormalizedTurn
) -> list[tuple[NormalizedNode | None, NormalizedNode | None]]:
    expected_ids = [n.node_id for n in expected.nodes]
    observed_ids = [n.node_id for n in observed.nodes]
    index_pairs = lcs.align(expected_ids, observed_ids)
    return [
        (
            expected.nodes[i] if i is not None else None,
            observed.nodes[j] if j is not None else None,
        )
        for i, j in index_pairs
    ]


def _transition_pairs(
    expected: NormalizedTurn, observed: NormalizedTurn
) -> list[tuple[StateChange, StateChange | None]]:
    if not expected.nodes and not observed.nodes:
        return _pair_by_key(expected.state_changes, observed.state_changes)

    pairs: list[tuple[StateChange, StateChange | None]] = []
    for e_node, o_node in _aligned_node_pairs(expected, observed):
        e_changes = e_node.state_changes if e_node is not None else []
        o_changes = o_node.state_changes if o_node is not None else []
        pairs.extend(_pair_by_key(e_changes, o_changes))
    return pairs


def _transition_counts(turn: NormalizedTurn) -> int:
    return sum(len(n.state_changes) for n in turn.nodes) if turn.nodes else len(turn.state_changes)


def _key_sequence(turn: NormalizedTurn) -> list[str]:
    if turn.nodes:
        return [c.key for n in turn.nodes for c in n.state_changes]
    return [c.key for c in turn.state_changes]


def state_key_accuracy(expected: NormalizedTurn, observed: NormalizedTurn) -> float | None:
    """Diagnostic: fraction of expected transitions whose key was found at all."""
    pairs = _transition_pairs(expected, observed)
    if not pairs:
        return None
    return sum(1 for _, o in pairs if o is not None) / len(pairs)


def old_state_accuracy(expected: NormalizedTurn, observed: NormalizedTurn) -> float | None:
    """Diagnostic: fraction of expected transitions whose old value matched."""
    pairs = _transition_pairs(expected, observed)
    if not pairs:
        return None
    return sum(1 for e, o in pairs if o is not None and o.old == e.old) / len(pairs)


def new_state_accuracy(expected: NormalizedTurn, observed: NormalizedTurn) -> float | None:
    """Diagnostic: fraction of expected transitions whose new value matched."""
    pairs = _transition_pairs(expected, observed)
    if not pairs:
        return None
    return sum(1 for e, o in pairs if o is not None and o.new == e.new) / len(pairs)


def transition_accuracy(expected: NormalizedTurn, observed: NormalizedTurn) -> float | None:
    denom = max(_transition_counts(expected), _transition_counts(observed))
    if denom == 0:
        return None
    pairs = _transition_pairs(expected, observed)
    matched = sum(
        1 for e, o in pairs if o is not None and o.old == e.old and o.new == e.new
    )
    return matched / denom


def transition_order_similarity(expected: NormalizedTurn, observed: NormalizedTurn) -> float | None:
    return lcs.order_similarity(_key_sequence(expected), _key_sequence(observed))


def sts_turn(expected: NormalizedTurn, observed: NormalizedTurn) -> float | None:
    """Turn-level diagnostic score (METRICS.md §3 "Levels": turn + overall)."""
    components = {
        "transition_accuracy": transition_accuracy(expected, observed),
        "order": transition_order_similarity(expected, observed),
    }
    return weighted_composite(components, _STS_WEIGHTS)


def sts_conversation(
    expected_turns: list[NormalizedTurn], observed_turns: list[NormalizedTurn]
) -> float | None:
    """Overall STS computed from the complete trajectory, not a turn-score
    average (METRICS.md §3, Frozen Rule #10)."""
    combined_expected = NormalizedTurn(
        conversation_id="_",
        turn_id=0,
        nodes=[n for t in expected_turns for n in t.nodes],
        state_changes=[c for t in expected_turns for c in t.state_changes],
    )
    combined_observed = NormalizedTurn(
        conversation_id="_",
        turn_id=0,
        nodes=[n for t in observed_turns for n in t.nodes],
        state_changes=[c for t in observed_turns for c in t.state_changes],
    )
    return sts_turn(combined_expected, combined_observed)


def sts_conversation_result(
    expected_turns: list[NormalizedTurn],
    observed_turns: list[NormalizedTurn],
    availability_status: str = "available",
) -> MetricResult:
    """METRICS.md §8-shaped result for overall STS."""
    combined_expected = NormalizedTurn(
        conversation_id="_",
        turn_id=0,
        nodes=[n for t in expected_turns for n in t.nodes],
        state_changes=[c for t in expected_turns for c in t.state_changes],
    )
    combined_observed = NormalizedTurn(
        conversation_id="_",
        turn_id=0,
        nodes=[n for t in observed_turns for n in t.nodes],
        state_changes=[c for t in observed_turns for c in t.state_changes],
    )
    score = sts_turn(combined_expected, combined_observed)

    pairs = _transition_pairs(combined_expected, combined_observed)
    missing = [ec.key for ec, oc in pairs if oc is None]
    mismatched = [
        {"key": ec.key, "expected_new": ec.new, "observed_new": oc.new}
        for ec, oc in pairs
        if oc is not None and (oc.old != ec.old or oc.new != ec.new)
    ]

    return make_result(
        "sts",
        score,
        availability_status,
        diagnostics={"missing_keys": missing, "mismatched": mismatched},
    )
