# Agent Eval

A trajectory-based evaluation framework for AI agents.

The project evaluates an agent's **execution trajectory**, not only its final conversational response. A Golden Dataset defines the expected trajectory, an Adapter normalizes the observed agent trace, and the evaluation engine compares the two to produce explainable metric results and an overall Agent Trajectory Fidelity (ATF) score.

## Core idea

```text
Golden Dataset                         Observed Agent Trace
      │                                         │
      │                                         ▼
      │                                  Adapter Module
      │                                         │
      │                                         ▼
      │                                Normalized Trace
      │                                         │
      └──────────────────┬──────────────────────┘
                         ▼
                 Trajectory Evaluation
                         │
        ┌────────────────┼─────────────────┐
        ▼                ▼                 ▼
       NTS              STS               TIS
   Node/Path          State             Tool
   fidelity          fidelity          fidelity
        │                │                 │
        └────────────────┼─────────────────┘
                         ▼
                    RS / OS
                 Routing / Outcome
                         │
                         ▼
                        ATF
```

The key evaluation principle is:

```text
Conversation
     ↓
   Nodes
     ↓
   States
     ↓
   Tools
     ↓
  Outcome
```

The conversation provides context, but the primary ground truth is the execution path represented by nodes, state changes, tools, routing and outcome.

## Project goals

- Evaluate different agent architectures through one normalized trajectory contract.
- Compare Golden and Observed traces at turn and overall levels.
- Preserve ground-level diagnostic results for individual metric components.
- Support agents that expose different amounts of node, state and tool information.
- Return **N/A rather than a false failure** when the trace does not expose enough evidence for a metric.
- Keep normalization/reconstruction inside the Adapter so the evaluation engine remains agent-agnostic.
- Produce explainable deviations such as skipped nodes, wrong state transitions, missing tools and incorrect outcomes.

## Architecture

The framework is agent-framework agnostic. The Adapter understands the source trace; everything downstream consumes the canonical normalized trajectory.

```text
                         Golden Dataset
                              │
                              ▼
                    Canonical Golden Trace
                              │
                              │
Raw Agent Trace ───────► Adapter
                              │
                              ▼
                    Normalized Observed Trace
                              │
                              ▼
                    Contract Validation
                              │
                              ▼
                 ┌──────────────────────────┐
                 │   Independent Metrics    │
                 │                          │
                 │ NTS → node alignment     │
                 │ STS → node/state        │
                 │ TIS → node/tool         │
                 │ RS  → semantic routing  │
                 │ OS  → final outcome     │
                 └────────────┬─────────────┘
                              ▼
                       ATF Aggregator
                              │
                              ▼
                       Evaluation Result
```

There is **no universal alignment score/stage**. Alignment is owned by the metric that needs it, with reusable internal sequence-alignment utilities where appropriate.

See [HLD.md](HLD.md) for the high-level architecture and [LLD.md](LLD.md) for component-level design.

## Canonical normalized trajectory

The Golden Dataset and Adapter output use the **same canonical node and tool identifiers**. The evaluator therefore does not perform semantic identifier mapping.

The canonical contract is:

`schema/normalized_trajectory.schema.json`

A normalized trajectory contains:

- `turns[]`
- ordered `nodes[]` per turn
- node output when available
- node `state_changes[]`
- node `tool_calls[]`
- turn-level `unassociated_tool_calls[]`
- routing/context where available
- final state
- outcome
- top-level availability

### State representation

The Adapter emits only actual node-level state changes:

```json
{
  "key": "customer_payment_posture",
  "old": null,
  "new": "cannot_pay"
}
```

If a node does not change state, its `state_changes` is empty. The Adapter reconstructs state when needed; the evaluator compares the resulting changes.

### Tool representation

Tools are associated with a node only when the source trace provides sufficient evidence. Otherwise they remain in `unassociated_tool_calls` at turn level. The Adapter never fabricates node-tool relationships.

## Adapter contract

The Adapter is responsible for:

- parsing the complete raw trace;
- extracting turns and nodes;
- preserving observed execution sequence;
- extracting node outputs when available;
- reconstructing node-level state changes when possible;
- extracting and ordering tool calls;
- associating tools with nodes only when supported by trace evidence;
- preserving unassociated tools;
- extracting routing/outcome evidence;
- determining availability;
- producing a schema-valid canonical trajectory.

The Adapter does **not** calculate NTS, STS, TIS, RS, OS, or ATF and does not compare against the Golden trajectory.

### Identifier rule

No separate identifier-mapping configuration is part of the core contract.

> **The Golden Dataset must use the same canonical node/tool identifiers that the Adapter produces.**

How a source trace is converted to those canonical identifiers is an implementation detail of the Adapter, not evaluator logic.

## Metric evaluation

Each metric is independently evaluated and returns a score plus diagnostics. Turn-level scores are available where meaningful; overall trajectory scores are calculated from the complete applicable trajectory rather than blindly averaging turn scores.

### NTS — Node Traversal Similarity

Measures expected versus observed node traversal.

```text
Node Coverage  = Matched Expected Nodes / Expected Nodes
Node Precision = Matched Observed Nodes / Observed Nodes
Node Recall    = Matched Expected Nodes / Expected Nodes

Node Order Similarity =
    LCS(Expected Node Sequence, Observed Node Sequence)
    / max(Expected Node Count, Observed Node Count)

NTS =
    0.40 × Coverage
  + 0.30 × Precision
  + 0.30 × Order Similarity
```

Recall remains a diagnostic because it is equivalent to Coverage under this definition. Matching is exact after Adapter normalization. Sequence alignment is position-aware and preserves missing/extra/reordered evidence without cascading penalties.

### STS — State Transition Similarity

Measures expected versus observed node-level state changes. A state transition is the tuple `(key, old, new)`.

```text
Transition Accuracy =
    Matched Complete Transitions
    / max(Expected Transitions, Observed Transitions)

Transition Order Similarity =
    LCS(Expected Transition Sequence, Observed Transition Sequence)
    / max(Expected Transition Count, Observed Transition Count)

STS =
    0.70 × Transition Accuracy
  + 0.30 × Transition Order Similarity
```

Key Accuracy, Old State Accuracy and New State Accuracy are diagnostics. Unchanged state variables are not included. Missing state information makes STS N/A rather than zero.

### TIS — Tool Invocation Similarity

Measures expected versus observed tool invocation, including node context where available.

```text
Tool Coverage   = Matched Expected Tools / Expected Tools
Tool Precision  = Matched Observed Tools / Observed Tools
Tool Identity   = Correct Tool Matches / Aligned Tool Pairs
Tool Input      = Average similarity of matched tool inputs
Tool Order      = LCS(Expected Tool Sequence, Observed Tool Sequence)
                  / max(Expected Tool Count, Observed Tool Count)

TIS =
    0.25 × Coverage
  + 0.20 × Precision
  + 0.25 × Identity
  + 0.20 × Input
  + 0.10 × Order
```

Tools are aligned within corresponding nodes when node association is supported; otherwise they are compared at turn level. The Adapter must not invent node-tool associations. No tool information means TIS is N/A.

### RS — Routing Similarity

RS is intentionally different from NTS. It is an **LLM-based semantic routing/path evaluation** using the customer input, agent response, expected path/context, and available trajectory evidence.

The LLM judge produces:

```text
Correct            = 1.0
Partially correct  = 0.5
Incorrect          = 0.0
```

```text
Semantic Routing Score =
    normalized LLM judge score across applicable routing turns

Routing Order Similarity =
    LCS(Expected Path Decisions, Observed Path Decisions)
    / max(Expected Decision Count, Observed Decision Count)

RS =
    0.70 × Semantic Routing Score
  + 0.30 × Routing Order Similarity
```

RS does not require a dedicated routing field in the source trace. The Adapter provides the evidence available to the judge. If routing cannot meaningfully be evaluated, RS is N/A.

### OS — Outcome Similarity

Measures the final outcome and its required attributes. OS is conversation-level only.

```text
Outcome Identity = 1 if identity matches, else 0

Attribute Accuracy =
    Correct Expected Attributes / Expected Attributes

Outcome Completion =
    Completed Required Outcome / Required Outcome

OS =
    0.50 × Outcome Identity
  + 0.30 × Attribute Accuracy
  + 0.20 × Outcome Completion
```

Missing outcome information means OS is N/A rather than zero.

## ATF aggregation

The frozen component weights are:

```text
NTS = 30%
STS = 30%
TIS = 15%
RS  = 10%
OS  = 15%
```

```text
ATF =
    0.30 × NTS
  + 0.30 × STS
  + 0.15 × TIS
  + 0.10 × RS
  + 0.15 × OS
```

When a metric is unavailable or not applicable, its weight is removed and the remaining applicable weights are renormalized. N/A is never treated as a failure.

The evaluation result must expose ATF **and all component scores/diagnostics** so the ATF score is never a black box.

## Applicability and coverage

The canonical trace records metric availability as:

- `available`
- `unavailable`
- `not_applicable`

Applicability is evaluated before scoring. Coverage and N/A status are reported explicitly.

## Evaluation result contract

Conceptually:

```json
{
  "evaluation_id": "EVAL_001",
  "status": "completed",
  "atf": { "score": 0.91 },
  "metrics": {
    "nts": {},
    "sts": {},
    "tis": {},
    "rs": {},
    "os": {}
  },
  "coverage": {},
  "diagnostics": {},
  "metadata": {}
}
```

The detailed metric result must retain enough evidence to explain score changes, including matched, missing, extra and order deviations where applicable.

## Deviation taxonomy

The evaluation suite covers:

- Correct answer, wrong trajectory
- Wrong node executed
- Node skipped
- Unexpected node executed
- Wrong node order
- Wrong state transition
- Missing state transition
- Wrong state progression
- Missing tool call
- Unexpected tool call
- Wrong tool
- Wrong tool input
- Wrong tool sequence
- Wrong conversational path
- Partial/incorrect outcome
- Correct trajectory but wrong final outcome
- Trajectory drift across turns
- Insufficient evidence

The first three machine-readable fixtures are already present under `tests/fixtures/scenarios/`.

## Reference Golden scenario

The current Golden scenario models:

```text
Motor Insurance
      ↓
Missed Premium
      ↓
Customer cannot pay
      ↓
Financial hardship identified
      ↓
Instalment eligibility checked
      ↓
Instalment arrangement proposed
      ↓
Customer accepts instalments
      ↓
Conversation completed
```

The canonical node vocabulary supplied by the scenario includes:

```text
initialize_call
greet_customer
verify_customer
handle_unverified_customer
classify_intent
handle_customer_outcome
confirm_outcome
execute_action
handle_exception
finalize_call
end_call
hardship_node
```

Not every node is required to occur in every trajectory. The Golden trace defines the expected path for the specific scenario.

## Repository structure

```text
agent-eval/
├── README.md
├── METRICS.md
├── HLD.md
├── LLD.md
├── schema/
│   └── normalized_trajectory.schema.json
├── golden/
│   └── motor_insurance_hardship_installment.json
└── tests/
    └── fixtures/
        └── scenarios/
            ├── correct_answer_wrong_trajectory.json
            ├── missing_tool_call.json
            └── wrong_tool_input.json
```

## Documentation

- **README.md** — project overview, architecture, concepts and repository structure.
- **METRICS.md** — metric definitions, formulas, evaluation levels, alignment behavior and aggregation.
- **HLD.md** — high-level architecture and system boundaries.
- **LLD.md** — low-level implementation architecture and component contracts.
- **schema/normalized_trajectory.schema.json** — canonical normalized trajectory JSON Schema.

## Development roadmap

The project is currently moving from specification into implementation:

1. Define and freeze the Golden trajectory model.
2. Define and freeze the normalized trajectory contract.
3. Define and freeze the Adapter contract.
4. Freeze metric definitions and formulas.
5. Define trajectory deviation scenarios.
6. Build representative Golden/Observed fixtures.
7. Implement adapters.
8. Implement metric calculation and trajectory comparison.
9. Implement ATF aggregation and explainable evaluation results.
10. Expand adapters and test coverage for additional agent architectures.

## Design principles

### Agent agnostic

The evaluation engine must not depend on a particular agent framework. Agent-specific reconstruction belongs in the Adapter.

### Evidence driven

A metric is scored only when the trace exposes the evidence required to calculate it.

### Explainable

The framework should identify the concrete deviation rather than returning only a single aggregate score.

### Modular metrics

NTS, STS, TIS, RS and OS remain independently available. ATF is an aggregation of these metric results, not a replacement for them.

### Trajectory first

The framework evaluates the path taken by the agent, including node traversal, state progression, tool usage, routing and outcome — not just the final natural-language response.

## Status

**Current stage:** Golden/Observed normalized trajectory fixtures and evaluation specification.

The next implementation step is to expand the deviation fixture set and use those fixtures to validate the metric engine before integrating additional real agent traces.
