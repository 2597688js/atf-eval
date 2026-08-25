"""Per-conversation `availability` (METRICS.md/schema: nodes/state/tools/
routing/outcome -> available|unavailable|not_applicable), computed once from
what an adapter actually produced.

This is a corroborating diagnostic signal, not a new scoring gate: the
existing per-metric None-return N/A logic in aggregate.py and each metrics
module already decides applicability correctly and is left untouched here.
"""
from __future__ import annotations

from atf_eval.metrics.outcome import last_outcome
from atf_eval.normalized import NormalizedTurn

_STATUSES = ("available", "unavailable", "not_applicable")


def _presence_status(turns: list[NormalizedTurn], has_signal) -> str:
    return "available" if any(has_signal(t) for t in turns) else "unavailable"


def compute_availability(
    expected_turns: list[NormalizedTurn],
    observed_turns: list[NormalizedTurn],
    judge_configured: bool = False,
) -> dict[str, str]:
    """Union of what was actually present across expected+observed turns for
    each of the five ATF dimensions. `judge_configured` distinguishes routing
    being `not_applicable` (no LLM judge configured at all, so routing was
    never even attempted) from `unavailable` (a judge ran but had nothing to
    evaluate)."""
    all_turns = expected_turns + observed_turns

    nodes_status = _presence_status(all_turns, lambda t: bool(t.nodes))
    state_status = _presence_status(
        all_turns,
        lambda t: bool(t.state_changes) or any(n.state_changes for n in t.nodes),
    )
    tools_status = _presence_status(
        all_turns,
        lambda t: bool(t.tool_calls) or any(n.tool_calls for n in t.nodes),
    )

    if not judge_configured:
        routing_status = "not_applicable"
    else:
        routing_status = _presence_status(all_turns, lambda t: t.routing is not None)

    outcome_status = (
        "available"
        if last_outcome(expected_turns) is not None or last_outcome(observed_turns) is not None
        else "unavailable"
    )

    return {
        "nodes": nodes_status,
        "state": state_status,
        "tools": tools_status,
        "routing": routing_status,
        "outcome": outcome_status,
    }
