"""Policy Compliance is deliberately separate from ATF (spec §21's own
principle applied one level up): trajectory fidelity answers "did the agent
follow the expected path", policy compliance answers "did the agent stay
within the rules regardless of path". A trajectory can score well on ATF
while still taking an action that violates policy (e.g. waiving a premium
a customer wasn't eligible for) -- that's exactly what this catches.

A PolicyRule is a plain Python predicate, mirroring the Adapter pattern:
domain-specific policy knowledge belongs in the rule the caller writes, not
in a declarative format this engine has to interpret generically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from atf_eval.normalized import NormalizedTurn

Severity = Literal["critical", "warning"]

# Returns None if not violated, or a human-readable detail string if violated.
RuleCheck = Callable[[NormalizedTurn, list[NormalizedTurn], dict], "str | None"]


@dataclass
class PolicyRule:
    rule_id: str
    description: str
    severity: Severity
    check: RuleCheck


@dataclass
class PolicyViolation:
    rule_id: str
    description: str
    severity: Severity
    turn_id: int
    detail: str
