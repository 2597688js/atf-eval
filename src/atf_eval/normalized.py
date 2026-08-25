"""The normalized trajectory contract every adapter (golden or observed) produces.

This is the common currency the metric engine operates on — it never understands
a specific agent's or domain's trace format directly (spec §20/§21).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StateChange:
    key: str
    old: Any = None
    new: Any = None
    source: str = "explicit"  # explicit | reconstructed | unavailable — spec §6.1
    # `source` is internal-only diagnostics; it has no home in the canonical
    # schema's stateChange def (key/old/new only) and is dropped at export time.


@dataclass
class ToolCall:
    tool_id: str
    arguments: dict = field(default_factory=dict)
    result: Any = None
    sequence: int | None = None
    status: str = "unknown"


@dataclass
class NormalizedNode:
    node_id: str
    node_type: str | None = None  # internal-only; folded into output.node_type at export, not a schema field
    sequence: int | None = None
    output: dict = field(default_factory=dict)
    state_changes: list[StateChange] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class Routing:
    path: str | None = None
    target: str | None = None


@dataclass
class Outcome:
    id: str | None = None
    attributes: dict = field(default_factory=dict)
    required_conditions: list[str] = field(default_factory=list)


@dataclass
class NormalizedTurn:
    conversation_id: str
    turn_id: int
    nodes: list[NormalizedNode] = field(default_factory=list)
    state_changes: list[StateChange] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)  # exported as turn.unassociated_tool_calls
    routing: Routing | None = None
    outcome: Outcome | None = None
    response: str | None = None  # observed agent's reply text, used by the RS LLM judge
