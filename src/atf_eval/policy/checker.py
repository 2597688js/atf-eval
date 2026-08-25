from __future__ import annotations

from dataclasses import dataclass, field

from atf_eval.normalized import NormalizedTurn
from atf_eval.policy.rules import PolicyRule, PolicyViolation


@dataclass
class PolicyResult:
    status: str  # "pass" | "fail" -- "fail" iff at least one critical violation
    violations: list[PolicyViolation] = field(default_factory=list)


def evaluate_conversation(
    turns: list[NormalizedTurn], rules: list[PolicyRule], context: dict
) -> PolicyResult:
    violations: list[PolicyViolation] = []
    for i, turn in enumerate(turns):
        history = turns[:i]
        for rule in rules:
            detail = rule.check(turn, history, context)
            if detail is not None:
                violations.append(
                    PolicyViolation(
                        rule_id=rule.rule_id,
                        description=rule.description,
                        severity=rule.severity,
                        turn_id=turn.turn_id,
                        detail=detail,
                    )
                )

    status = "fail" if any(v.severity == "critical" for v in violations) else "pass"
    return PolicyResult(status=status, violations=violations)
