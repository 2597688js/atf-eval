"""Renders a single conversation's ATF result (+ optional Policy Compliance
result) as a readable text scorecard -- actionable engineering information
instead of one more number, per spec §17's "never collapse into ATF alone."
"""
from __future__ import annotations

from atf_eval.diagnostics import find_key_state_deviation, find_key_tool_deviation
from atf_eval.policy.checker import PolicyResult
from atf_eval.runner import ConversationResult

_WIDTH = 40
_DIVIDER = "─" * _WIDTH


def _pct(score: float | None) -> str:
    return "N/A" if score is None else f"{score * 100:.1f}%"


def _row(label: str, value: str) -> str:
    return f"{label}{value:>{max(1, _WIDTH - len(label))}}"


def render_scorecard(
    scenario_name: str, conv: ConversationResult, policy: PolicyResult | None = None
) -> str:
    lines: list[str] = ["Scenario", scenario_name, "", _DIVIDER, "", _row("ATF SCORE", _pct(conv.atf)), ""]
    lines += [
        _row("Node Traversal", _pct(conv.nts)),
        _row("State Transition", _pct(conv.sts)),
        _row("Tool Invocation", _pct(conv.tis)),
        _row("Routing", _pct(conv.rs)),
        _row("Outcome", _pct(conv.os)),
        "",
        _DIVIDER,
        "",
    ]

    if policy is not None:
        status_label = "PASS" if policy.status == "pass" else "FAIL"
        lines += [_row("POLICY COMPLIANCE", status_label), "", _DIVIDER, ""]
        if policy.violations:
            lines.append("Policy Violations")
            lines.append("")
            for v in policy.violations:
                lines.append(f"[{v.severity.upper()}] {v.rule_id} (turn {v.turn_id})")
                lines.append(f"  {v.detail}")
            lines += ["", _DIVIDER, ""]

    state_dev = find_key_state_deviation(conv.expected_turns, conv.observed_turns)
    if state_dev is not None:
        observed = state_dev.observed_new if state_dev.observed_new is not None else "(not updated)"
        lines += [
            "Key Deviation",
            "",
            "STS ↓",
            "",
            "Expected:",
            f"{state_dev.expected_old} → {state_dev.expected_new}",
            "",
            "Observed:",
            str(observed),
            "",
            "Reason:",
            state_dev.reason,
            "",
            _DIVIDER,
            "",
        ]

    tool_dev = find_key_tool_deviation(conv.expected_turns, conv.observed_turns)
    if tool_dev is not None:
        lines += ["Tool Deviation", "", "Expected:", tool_dev.expected_tool, "", "Observed:", tool_dev.observed]

    return "\n".join(lines).rstrip() + "\n"
