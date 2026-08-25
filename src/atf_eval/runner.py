from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import anthropic

from atf_eval.adapter import TrajectoryAgent
from atf_eval.aggregate import DEFAULT_WEIGHTS, atf_score
from atf_eval.availability import compute_availability
from atf_eval.dataset import GoldenTurn
from atf_eval.metric_result import MetricResult
from atf_eval.metrics import nodes, outcome, routing, state, tools
from atf_eval.normalized import NormalizedTurn


@dataclass
class TurnResult:
    conversation_id: str
    turn_id: int
    status: str  # "ok" | "agent_error" | "skipped_after_prior_error"
    error: str | None = None
    nts: float | None = None
    sts: float | None = None
    tis: float | None = None
    rs: float | None = None
    latency_ms: float | None = None


@dataclass
class ConversationResult:
    conversation_id: str
    turns: list[TurnResult]
    nts: float | None
    sts: float | None
    tis: float | None
    rs: float | None
    os: float | None
    atf: float | None
    metric_coverage: float
    expected_turns: list[NormalizedTurn]
    observed_turns: list[NormalizedTurn]
    availability: dict[str, str]
    metric_results: dict[str, MetricResult]


def _evaluate_conversation(
    conversation_id: str,
    golden_turns: list[GoldenTurn],
    adapter: TrajectoryAgent,
    weights: dict[str, float],
    tolerance: float = 0.0,
    judge_client: anthropic.Anthropic | None = None,
    judge_model: str = "claude-opus-5",
    judge_effort: str | None = None,
) -> ConversationResult:
    history: list[NormalizedTurn] = []
    expected_turns: list[NormalizedTurn] = []
    observed_turns: list[NormalizedTurn] = []
    turn_results: list[TurnResult] = []
    per_turn_semantic_scores: list[float | None] = []
    broken = False

    for golden_turn in golden_turns:
        expected_turn = golden_turn.to_normalized()
        expected_turns.append(expected_turn)

        if broken:
            observed_turns.append(
                NormalizedTurn(conversation_id=conversation_id, turn_id=golden_turn.turn_id)
            )
            per_turn_semantic_scores.append(None)
            turn_results.append(
                TurnResult(
                    conversation_id=conversation_id,
                    turn_id=golden_turn.turn_id,
                    status="skipped_after_prior_error",
                )
            )
            continue

        start = time.monotonic()
        try:
            observed_turn = adapter.run_turn(
                conversation_id, golden_turn.turn_id, golden_turn.user_input, list(history)
            )
        except Exception as e:  # noqa: BLE001 - isolate a broken turn, don't crash the whole run
            print(
                f"[WARN] adapter failed on {conversation_id}/{golden_turn.turn_id}: {e}",
                file=sys.stderr,
            )
            observed_turns.append(
                NormalizedTurn(conversation_id=conversation_id, turn_id=golden_turn.turn_id)
            )
            per_turn_semantic_scores.append(None)
            turn_results.append(
                TurnResult(
                    conversation_id=conversation_id,
                    turn_id=golden_turn.turn_id,
                    status="agent_error",
                    error=str(e),
                    latency_ms=(time.monotonic() - start) * 1000,
                )
            )
            broken = True  # a broken turn can leave a stateful agent's context corrupted
            continue

        latency_ms = (time.monotonic() - start) * 1000
        observed_turns.append(observed_turn)
        history.append(observed_turn)

        semantic_score = routing.semantic_routing_score(
            golden_turn.user_input, expected_turn, observed_turn, judge_client, judge_model, judge_effort
        )
        per_turn_semantic_scores.append(semantic_score)

        turn_results.append(
            TurnResult(
                conversation_id=conversation_id,
                turn_id=golden_turn.turn_id,
                status="ok",
                nts=nodes.nts_turn(expected_turn, observed_turn),
                sts=state.sts_turn(expected_turn, observed_turn),
                tis=tools.tis_turn(expected_turn, observed_turn, tolerance),
                rs=routing.rs_turn(semantic_score),
                latency_ms=latency_ms,
            )
        )

    # overall NTS/STS/TIS are computed from the complete concatenated
    # trajectory, not by averaging turn scores (METRICS.md Frozen Rule #10)
    nts_score = nodes.nts_conversation(expected_turns, observed_turns)
    sts_score = state.sts_conversation(expected_turns, observed_turns)
    tis_score = tools.tis_conversation(expected_turns, observed_turns, tolerance)
    rs_score = routing.rs_conversation(expected_turns, observed_turns, per_turn_semantic_scores)
    os_score = outcome.os_conversation(expected_turns, observed_turns, tolerance)

    group_scores = {"nts": nts_score, "sts": sts_score, "tis": tis_score, "rs": rs_score, "os": os_score}
    atf, coverage = atf_score(group_scores, weights)
    availability = compute_availability(expected_turns, observed_turns, judge_configured=judge_client is not None)

    metric_results = {
        "nts": nodes.nts_conversation_result(expected_turns, observed_turns, availability["nodes"]),
        "sts": state.sts_conversation_result(expected_turns, observed_turns, availability["state"]),
        "tis": tools.tis_conversation_result(expected_turns, observed_turns, tolerance, availability["tools"]),
        "rs": routing.rs_conversation_result(
            expected_turns, observed_turns, per_turn_semantic_scores, availability["routing"]
        ),
        "os": outcome.os_conversation_result(expected_turns, observed_turns, tolerance, availability["outcome"]),
    }

    return ConversationResult(
        conversation_id=conversation_id,
        turns=turn_results,
        nts=nts_score,
        sts=sts_score,
        tis=tis_score,
        rs=rs_score,
        os=os_score,
        atf=atf,
        metric_coverage=coverage,
        expected_turns=expected_turns,
        observed_turns=observed_turns,
        availability=availability,
        metric_results=metric_results,
    )


def run_evaluation(
    conversations: dict[str, list[GoldenTurn]],
    adapter: TrajectoryAgent,
    weights: dict[str, float] | None = None,
    concurrency: int = 1,
    tolerance: float = 0.0,
    judge_client: anthropic.Anthropic | None = None,
    judge_model: str = "claude-opus-5",
    judge_effort: str | None = None,
) -> list[ConversationResult]:
    """`judge_client` powers RS's LLM-based routing judgment (METRICS.md §5).
    Pass None to skip it -- RS then reports N/A rather than making any LLM
    calls, and every other metric group is unaffected."""
    weights = weights or DEFAULT_WEIGHTS
    items = list(conversations.items())

    def _run(cid: str, turns: list[GoldenTurn]) -> ConversationResult:
        return _evaluate_conversation(
            cid, turns, adapter, weights, tolerance, judge_client, judge_model, judge_effort
        )

    if concurrency <= 1:
        return [_run(cid, turns) for cid, turns in items]

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        return list(executor.map(lambda kv: _run(kv[0], kv[1]), items))
