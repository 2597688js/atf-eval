"""Routing Similarity (RS) — METRICS.md §5.

RS is an LLM-based semantic evaluation, not a field comparison: it asks
whether the agent chose the appropriate conversational direction given the
customer input and its own response, not just whether `routing.target`
string-matches. A judge call failure or a missing `judge_client` degrades
RS to N/A for that turn (never to 0 — a judge outage is not the agent's
fault) per spec §5's "If routing cannot meaningfully be evaluated, RS is
N/A" and Frozen Rule #11.

The judge is called at most once per turn: `semantic_routing_score()` is the
single entry point the runner calls per turn, and the resulting scores are
threaded into both `rs_turn` (turn-level reporting) and `rs_conversation`
(overall aggregation) rather than re-querying the judge for the conversation
score.
"""
from __future__ import annotations

import sys

import anthropic

from atf_eval import lcs
from atf_eval.aggregate import weighted_composite
from atf_eval.judge import run_routing_judge, verdict_to_score
from atf_eval.metric_result import MetricResult, make_result
from atf_eval.normalized import NormalizedTurn

_RS_WEIGHTS = {"semantic": 0.70, "order": 0.30}


def _trajectory_evidence(observed: NormalizedTurn) -> str:
    lines: list[str] = []
    if observed.nodes:
        lines.append("nodes visited: " + ", ".join(n.node_id for n in observed.nodes))
    if observed.tool_calls:
        lines.append("tools called: " + ", ".join(t.tool_id for t in observed.tool_calls))
    if observed.state_changes:
        lines.append(
            "state changes: "
            + "; ".join(f"{c.key}: {c.old!r} -> {c.new!r}" for c in observed.state_changes)
        )
    if observed.routing:
        lines.append(
            f"observed routing: path={observed.routing.path!r} target={observed.routing.target!r}"
        )
    return "\n".join(lines) if lines else "(no additional trajectory evidence available)"


def semantic_routing_score(
    customer_input: str,
    expected: NormalizedTurn,
    observed: NormalizedTurn,
    judge_client: anthropic.Anthropic | None,
    judge_model: str = "claude-opus-5",
    judge_effort: str | None = None,
) -> float | None:
    """One judge call for one turn. None (N/A) if there's no client, nothing
    expected to judge against, or the judge call itself fails."""
    expected_path = expected.routing.path if expected.routing else None
    expected_target = expected.routing.target if expected.routing else None
    if judge_client is None or (expected_path is None and expected_target is None):
        return None
    try:
        result = run_routing_judge(
            judge_client,
            judge_model,
            customer_input,
            observed.response,
            expected_path,
            expected_target,
            _trajectory_evidence(observed),
            effort=judge_effort,
        )
    except Exception as e:  # noqa: BLE001 - a judge outage makes RS N/A, not 0, for this turn
        print(f"[WARN] routing judge failed: {e}", file=sys.stderr)
        return None
    return verdict_to_score(result.verdict)


def rs_turn(semantic_score: float | None) -> float | None:
    """Turn-level diagnostic score from an already-computed judge verdict.
    Order is always N/A at turn level (only computable across the full
    conversation) -- weighted_composite renormalizes to just the semantic
    component, so this reduces to `semantic_score` itself."""
    return weighted_composite({"semantic": semantic_score}, _RS_WEIGHTS)


def routing_order_similarity(
    expected_turns: list[NormalizedTurn], observed_turns: list[NormalizedTurn]
) -> float | None:
    expected_seq = [t.routing.target for t in expected_turns if t.routing and t.routing.target]
    observed_seq = [t.routing.target for t in observed_turns if t.routing and t.routing.target]
    return lcs.order_similarity(expected_seq, observed_seq)


def rs_conversation(
    expected_turns: list[NormalizedTurn],
    observed_turns: list[NormalizedTurn],
    per_turn_semantic_scores: list[float | None],
) -> float | None:
    """Overall RS = 0.70 x (mean judge score across applicable turns) +
    0.30 x routing order similarity, per METRICS.md §5 ("Semantic Routing
    Score = normalized LLM judge score across applicable routing turns").
    Takes the already-computed per-turn scores rather than re-querying the
    judge."""
    applicable = [s for s in per_turn_semantic_scores if s is not None]
    semantic = sum(applicable) / len(applicable) if applicable else None

    components = {
        "semantic": semantic,
        "order": routing_order_similarity(expected_turns, observed_turns),
    }
    return weighted_composite(components, _RS_WEIGHTS)


def rs_conversation_result(
    expected_turns: list[NormalizedTurn],
    observed_turns: list[NormalizedTurn],
    per_turn_semantic_scores: list[float | None],
    availability_status: str = "available",
) -> MetricResult:
    """METRICS.md §8-shaped result for overall RS."""
    score = rs_conversation(expected_turns, observed_turns, per_turn_semantic_scores)
    applicable_turns = sum(1 for s in per_turn_semantic_scores if s is not None)

    return make_result(
        "rs",
        score,
        availability_status,
        diagnostics={
            "judged_turns": applicable_turns,
            "total_turns": len(per_turn_semantic_scores),
        },
    )
