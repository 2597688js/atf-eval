"""Policy Compliance rules for the collections domain, checked against the
golden script's `context.policy` fixture (max_waiver_pct, waiver_allowed,
requires_hardship_for_discount, ...) -- separate from and orthogonal to ATF:
a conversation can score well on trajectory fidelity while still granting a
discount the policy never allowed.

Discount decisions can show up under either tool name: `installment_discount_apply`
(the direct tool, per the tool catalog) or `discount_planning_handoff` (a
synthetic entry the adapter adds for the separate DiscountPlanningAgent
handoff -- discounts in this codebase don't always go through a directly
observable tool_execution call). A discount_pct of 0 isn't a waiver, so it's
excluded from all three checks below.
"""
from __future__ import annotations

from atf_eval.policy.helpers import latest_state_value
from atf_eval.policy.rules import PolicyRule

_DISCOUNT_TOOL_NAMES = {"installment_discount_apply", "discount_planning_handoff"}


def _discount_grants(turn):
    return [
        tc
        for tc in turn.tool_calls
        if tc.tool_id in _DISCOUNT_TOOL_NAMES and (tc.arguments.get("discount_pct") or 0) > 0
    ]


def waiver_allowed_gate(turn, history, context):
    policy = context.get("policy", {})
    if policy.get("waiver_allowed", True):
        return None
    grants = _discount_grants(turn)
    if grants:
        return (
            f"Applied a {grants[0].arguments.get('discount_pct')}% discount via "
            f"{grants[0].tool_id}, but policy.waiver_allowed is False for this loan."
        )
    return None


def discount_pct_within_policy_max(turn, history, context):
    policy = context.get("policy", {})
    max_pct = policy.get("max_waiver_pct")
    if max_pct is None:
        return None
    for tc in _discount_grants(turn):
        pct = tc.arguments.get("discount_pct")
        if pct is not None and pct > max_pct:
            return f"Discount of {pct}% via {tc.tool_id} exceeds policy.max_waiver_pct of {max_pct}%."
    return None


def discount_requires_hardship(turn, history, context):
    policy = context.get("policy", {})
    if not policy.get("requires_hardship_for_discount", False):
        return None
    grants = _discount_grants(turn)
    if not grants:
        return None
    hardship_context = latest_state_value(history, turn, "hardship_context", default={}) or {}
    hardship_detected = hardship_context.get("hardship_detected", False)
    if not hardship_detected:
        return (
            f"Applied a {grants[0].arguments.get('discount_pct')}% discount via "
            f"{grants[0].tool_id} without hardship having been established "
            f"(policy.requires_hardship_for_discount is True)."
        )
    return None


RULES = [
    PolicyRule(
        rule_id="waiver_allowed_gate",
        description="Discounts must not be applied when the loan's policy disallows waivers entirely.",
        severity="critical",
        check=waiver_allowed_gate,
    ),
    PolicyRule(
        rule_id="discount_pct_within_policy_max",
        description="Discount percentage must not exceed the policy's max_waiver_pct.",
        severity="critical",
        check=discount_pct_within_policy_max,
    ),
    PolicyRule(
        rule_id="discount_requires_hardship",
        description="A discount must not be granted without an established hardship when the policy requires one.",
        severity="critical",
        check=discount_requires_hardship,
    ),
]
