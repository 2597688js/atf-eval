"""Evidence bundles the LLM metrics read.

Built from the same `NormalizedTurn` lists the deterministic metrics use
(expected == golden reference, observed == the trace under evaluation), so
the LLM layer needs no separate trace format. Group 5 additionally needs
audio/timing evidence, which the canonical trajectory does not currently
carry -- `has_audio` / `has_timing` stay False and those metrics return N/A.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from atf_eval.normalized import NormalizedTurn


@dataclass
class ToolEvidence:
    tool_id: str
    arguments: dict[str, Any]


@dataclass
class TurnContext:
    turn_id: int
    customer_input: str
    agent_response: str
    prior_exchanges: list[tuple[str, str]]        # [(customer, agent), ...] before this turn
    reference_response: str | None                # golden agent response for this turn
    observed_nodes: list[str] = field(default_factory=list)
    reference_nodes: list[str] = field(default_factory=list)
    observed_tools: list[ToolEvidence] = field(default_factory=list)
    reference_tools: list[ToolEvidence] = field(default_factory=list)
    observed_state_changes: list[tuple[str, Any, Any]] = field(default_factory=list)
    reference_state_changes: list[tuple[str, Any, Any]] = field(default_factory=list)
    observed_routing: tuple[str | None, str | None] | None = None
    reference_routing: tuple[str | None, str | None] | None = None

    def asks_question(self) -> bool:
        return "?" in (self.agent_response or "")

    def evidence_block(self) -> str:
        lines = []
        if self.reference_response:
            lines.append(f"reference (golden) agent response: {self.reference_response}")
        if self.reference_nodes:
            lines.append("reference nodes: " + ", ".join(self.reference_nodes))
        if self.observed_nodes:
            lines.append("observed nodes: " + ", ".join(self.observed_nodes))
        if self.reference_tools:
            lines.append(
                "reference tools: "
                + ", ".join(f"{t.tool_id}({t.arguments})" for t in self.reference_tools)
            )
        if self.observed_tools:
            lines.append(
                "observed tools: "
                + ", ".join(f"{t.tool_id}({t.arguments})" for t in self.observed_tools)
            )
        if self.observed_state_changes:
            lines.append(
                "observed state changes: "
                + "; ".join(f"{k}: {o!r}->{n!r}" for k, o, n in self.observed_state_changes)
            )
        return "\n".join(lines) if lines else "(no additional trajectory evidence)"


@dataclass
class ConversationContext:
    conversation_id: str
    turns: list[TurnContext]
    reference_outcome: dict[str, Any] | None
    observed_outcome: dict[str, Any] | None
    has_audio: bool = False
    has_timing: bool = False

    def transcript(self) -> str:
        out = []
        for t in self.turns:
            out.append(f"[turn {t.turn_id}] customer: {t.customer_input}")
            out.append(f"[turn {t.turn_id}] agent: {t.agent_response}")
        return "\n".join(out)


def _tools(turn: NormalizedTurn) -> list[ToolEvidence]:
    return [ToolEvidence(tool_id=tc.tool_id, arguments=dict(tc.arguments)) for tc in turn.tool_calls]


def _state(turn: NormalizedTurn) -> list[tuple[str, Any, Any]]:
    changes = list(turn.state_changes)
    for n in turn.nodes:
        changes.extend(n.state_changes)
    return [(c.key, c.old, c.new) for c in changes]


def _routing(turn: NormalizedTurn) -> tuple[str | None, str | None] | None:
    if turn.routing is None:
        return None
    return (turn.routing.path, turn.routing.target)


def build_context(
    conversation_id: str,
    expected_turns: list[NormalizedTurn],
    observed_turns: list[NormalizedTurn],
) -> ConversationContext:
    ref_by_id = {t.turn_id: t for t in expected_turns}
    prior: list[tuple[str, str]] = []
    turn_ctxs: list[TurnContext] = []

    for obs in observed_turns:
        ref = ref_by_id.get(obs.turn_id)
        customer = _turn_customer(obs) or (_turn_customer(ref) if ref else "") or ""
        agent = obs.response or ""
        tc = TurnContext(
            turn_id=obs.turn_id,
            customer_input=customer,
            agent_response=agent,
            prior_exchanges=list(prior),
            reference_response=ref.response if ref else None,
            observed_nodes=[n.node_id for n in obs.nodes],
            reference_nodes=[n.node_id for n in ref.nodes] if ref else [],
            observed_tools=_tools(obs),
            reference_tools=_tools(ref) if ref else [],
            observed_state_changes=_state(obs),
            reference_state_changes=_state(ref) if ref else [],
            observed_routing=_routing(obs),
            reference_routing=_routing(ref) if ref else None,
        )
        turn_ctxs.append(tc)
        prior.append((customer, agent))

    return ConversationContext(
        conversation_id=conversation_id,
        turns=turn_ctxs,
        reference_outcome=_last_outcome_attrs(expected_turns),
        observed_outcome=_last_outcome_attrs(observed_turns),
    )


def _last_outcome_attrs(turns: list[NormalizedTurn]) -> dict[str, Any] | None:
    for turn in reversed(turns):
        if turn.outcome is not None:
            attrs = dict(turn.outcome.attributes)
            if turn.outcome.id is not None:
                attrs.setdefault("outcome_id", turn.outcome.id)
            return attrs
    return None


def _turn_customer(turn: NormalizedTurn | None) -> str | None:
    """NormalizedTurn doesn't carry the customer utterance directly; the
    dashboard/reference adapters stash it nowhere canonical, so this is a
    best-effort hook. build_context falls back to the reference turn's copy
    and finally to "" -- Relevance/Intent then go N/A if both are empty."""
    if turn is None:
        return None
    return getattr(turn, "customer_input", None)
