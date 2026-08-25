"""ATF adapter for `discount_planning_agent` -- a deliberately different
shape of example from collection_agent.

This agent is a 72-line, stateless, single-shot pure function: one method,
`DiscountPlanningAgent.run(handoff_payload) -> dict`. No LangGraph, no named
execution nodes, no external tool calls, no persistent state between calls.

Rather than fabricate nodes/state/tool_calls that don't really exist just to
give every ATF metric group something to report, this adapter is honest:
only Outcome (the returned recommendation) is populated. NTS/STS/TIS/RS all
come back N/A for every turn -- which is the *correct* ATF result for a
component this thin (spec §14: N/A must not be interpreted as 0), not a
limitation of the adapter. Metric coverage will show ~15% (OS's weight
alone), which is itself the useful finding: ATF's five-dimension trajectory
model is a poor fit for a stateless scoring function like this one, and a
plain input/output regression test would suit it better than ATF.

Since this agent has no multi-turn conversation concept, the ATF golden
dataset's per-turn `user_input` field is repurposed to carry the JSON-encoded
`handoff_payload` -- the only real "input" this agent has.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EASY_AGENTS_ROOT = Path("/Users/janarddan/1.jana files/3.MyMacProjects/easy_agents")
for p in (str(EASY_AGENTS_ROOT), str(EASY_AGENTS_ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from agents.discount_planning_agent.agent import DiscountPlanningAgent  # noqa: E402

from atf_eval.normalized import NormalizedTurn, Outcome  # noqa: E402


class DiscountPlanningAgentAdapter:
    def __init__(self) -> None:
        self.agent = DiscountPlanningAgent()

    def run_turn(
        self,
        conversation_id: str,
        turn_id: int,
        user_input: str,
        history: list[NormalizedTurn],
    ) -> NormalizedTurn:
        handoff_payload = json.loads(user_input) if user_input else {}
        result = self.agent.run(handoff_payload)
        offer = result.get("recommended_offer", {}) or {}

        outcome = Outcome(
            id="discount_recommendation_generated",
            attributes={
                "offer_type": offer.get("offer_type"),
                "waiver_pct": offer.get("waiver_pct"),
                "tenure_months": offer.get("tenure_months"),
                "monthly_emi": offer.get("monthly_emi"),
                "hardship_reason": offer.get("hardship_reason"),
            },
        )

        return NormalizedTurn(
            conversation_id=conversation_id,
            turn_id=turn_id,
            outcome=outcome,
        )
