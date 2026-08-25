from __future__ import annotations

from typing import Protocol, runtime_checkable

from atf_eval.normalized import NormalizedTurn


@runtime_checkable
class TrajectoryAgent(Protocol):
    """Your agent, wrapped to satisfy this one method.

    `run_turn` both invokes your agent for this turn AND normalizes its trace
    into the common `NormalizedTurn` shape. `history` is the normalized
    observed trajectory of every prior turn in this conversation (in order),
    so a stateful/multi-turn agent can rebuild its own context.
    """

    def run_turn(
        self,
        conversation_id: str,
        turn_id: int,
        user_input: str,
        history: list[NormalizedTurn],
    ) -> NormalizedTurn: ...
