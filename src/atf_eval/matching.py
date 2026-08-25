"""Value equality with configurable numeric tolerance, shared by TIS (tool
arguments) and OS (outcome attributes) — spec §9.4 mentions tolerance for
tool arguments; outcome attributes reuse the same comparator.
"""
from __future__ import annotations

from numbers import Real


def values_match(expected_val: object, observed_val: object, tolerance: float = 0.0) -> bool:
    if (
        isinstance(expected_val, Real)
        and isinstance(observed_val, Real)
        and not isinstance(expected_val, bool)
        and not isinstance(observed_val, bool)
    ):
        return abs(float(expected_val) - float(observed_val)) <= tolerance
    return expected_val == observed_val
