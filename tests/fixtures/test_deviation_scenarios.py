"""End-to-end conformance check using agent-eval-main's own canonical golden
scenario and its 3 deviation fixtures -- the strongest available check since
these are authored by the spec's own owners, not derived from atf_eval's
code. Values below were captured by actually running the metric functions
against these exact fixtures (not assumed) -- see the reference_adapter
module for how the pre-Adapter raw fixture vocabulary is normalized.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from atf_eval.metrics.nodes import nts_conversation
from atf_eval.metrics.state import sts_conversation
from atf_eval.metrics.tools import tis_conversation
from tests.fixtures.reference_adapter import load_fixture_turns, load_golden_turns

AGENT_EVAL_MAIN = Path(__file__).resolve().parents[2] / "agent-eval-main"
GOLDEN = AGENT_EVAL_MAIN / "golden" / "motor_insurance_hardship_installment.json"
SCENARIOS = AGENT_EVAL_MAIN / "tests" / "fixtures" / "scenarios"


@pytest.fixture(scope="module")
def golden_turns():
    if not GOLDEN.exists():
        pytest.skip(
            "agent-eval-main not found locally (it's a separate repo, not bundled here) -- "
            "clone it as a sibling folder to run this conformance suite"
        )
    return load_golden_turns(GOLDEN)


def test_golden_against_itself_is_a_perfect_baseline(golden_turns):
    assert nts_conversation(golden_turns, golden_turns) == 1.0
    assert sts_conversation(golden_turns, golden_turns) == 1.0
    assert tis_conversation(golden_turns, golden_turns) == 1.0


def test_correct_answer_wrong_trajectory_degrades_nodes_and_state(golden_turns):
    """Deviation: hardship_node is skipped at turn 4 even though the agent's
    reply is contextually appropriate. Both the node sequence and the state
    transition that only hardship_node produces are affected; tool calls
    elsewhere in the conversation are untouched."""
    observed = load_fixture_turns(SCENARIOS / "correct_answer_wrong_trajectory.json")

    assert nts_conversation(golden_turns, observed) < 1.0
    assert sts_conversation(golden_turns, observed) < 1.0
    assert tis_conversation(golden_turns, observed) == 1.0


def test_missing_tool_call_degrades_only_tis(golden_turns):
    """Deviation: the expected `instalment_eligibility` tool is never
    invoked at turn 5, but the node sequence and the resulting state change
    are otherwise identical to golden -- only TIS should see this."""
    golden_turn_5 = [t for t in golden_turns if t.turn_id == 5]
    observed = load_fixture_turns(SCENARIOS / "missing_tool_call.json")

    assert nts_conversation(golden_turn_5, observed) == 1.0
    assert sts_conversation(golden_turn_5, observed) == 1.0
    assert tis_conversation(golden_turn_5, observed) == 0.0


def test_wrong_tool_input_stays_perfect_because_nothing_was_required(golden_turns):
    """Deviation: the correct tool is invoked but with different arguments
    (`policy_id`/`requested_amount` instead of nothing). Per METRICS.md's own
    tool-input formula ("if nothing was required of this call, nothing to
    get wrong"), the golden scenario's expected input for this tool is `{}`
    -- so this specific fixture does not actually move TIS, even though its
    name suggests it should. This is the frozen formula's real behavior, not
    a bug in this test suite or in atf_eval."""
    golden_turn_5 = [t for t in golden_turns if t.turn_id == 5]
    observed = load_fixture_turns(SCENARIOS / "wrong_tool_input.json")

    assert nts_conversation(golden_turn_5, observed) == 1.0
    assert sts_conversation(golden_turn_5, observed) == 1.0
    assert tis_conversation(golden_turn_5, observed) == 1.0
