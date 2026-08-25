# Agent Eval — High-Level Design

## 1. Purpose

Agent Eval is a universal agent-evaluation framework focused initially on **Agent Trajectory Fidelity (ATF)**.

ATF evaluates whether an agent followed the expected execution trajectory rather than only whether its final response was correct.

The framework compares a Golden trajectory with an Observed trajectory across the dimensions exposed by the trace:

- Node Traversal Similarity (NTS)
- State Transition Similarity (STS)
- Tool Invocation Similarity (TIS)
- Routing Similarity (RS)
- Outcome Similarity (OS)

Not every agent exposes every dimension. The framework therefore evaluates only applicable dimensions and reports observability/coverage explicitly.

---

## 2. Core architectural principle

> **The evaluator is agent-framework agnostic. The Adapter is the only agent-specific layer.**

Different agents may have fundamentally different execution architectures. For example:

```text
Agent A
path_selector → tool_resolver → agent_reason → tool_execution → response
```

or:

```text
Agent B
entity_extract → negotiation_classification → plan_proposal_state → response
```

Both are converted into the same canonical normalized trajectory. No source-specific logic belongs in the evaluator.

---

## 3. High-level architecture

```text
                         ┌─────────────────────┐
                         │   Golden Dataset    │
                         │ Expected Trajectory │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │ Canonical Golden    │
                         │ Trajectory          │
                         └──────────┬──────────┘
                                    │
                                    │
┌──────────────────┐                │
│ Raw Agent Trace  │                │
└────────┬─────────┘                │
         │                          │
         ▼                          │
┌─────────────────────────────┐     │
│       Adapter Layer         │     │
│ Extract • Reconstruct       │     │
│ Associate • Preserve        │     │
│ Sequence • Availability     │     │
└──────────────┬──────────────┘     │
               │                    │
               ▼                    │
┌─────────────────────────────┐     │
│ Normalized Observed Trace   │◄────┘
│ Canonical Trajectory        │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ Contract Validation         │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│             Independent Metric Evaluators            │
│                                                     │
│ NTS │ STS │ TIS │ RS (LLM) │ OS                    │
│                                                     │
│ Each metric owns the alignment it requires.         │
└──────────────────────────┬──────────────────────────┘
                           │
                           ▼
                 ┌─────────────────────┐
                 │   ATF Aggregator    │
                 │ applicable metrics │
                 │ + coverage         │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Evaluation Result   │
                 │ Score + Diagnostics │
                 └─────────────────────┘
```

**There is no universal alignment score/stage.** Metric evaluators may use shared sequence-alignment utilities internally, but alignment remains part of the metric that needs it.

---

## 4. Major components

### 4.1 Golden Dataset

Contains the expected trajectory for a scenario, including expected nodes, node outputs, state changes, tool calls, routing context, and final outcome where applicable.

The Golden Dataset is the source of truth for trajectory evaluation.

### 4.2 Canonical Golden Trajectory

The Golden Dataset is represented using the same canonical normalized trajectory contract consumed by the evaluator. This avoids evaluator-specific parsing of Golden data.

### 4.3 Adapter Layer

The Adapter translates a specific raw agent trace into the canonical normalized trajectory.

Responsibilities:

- Parse the complete raw trace.
- Extract turns and nodes.
- Preserve observed execution sequence.
- Extract node outputs when available.
- Reconstruct node-level state changes when required and reliably derivable.
- Emit only actual state changes as `state_changes[]`.
- Extract and order tool calls.
- Associate tools with nodes only when trace evidence supports the association.
- Preserve unassociated tool calls at turn level.
- Extract routing/outcome evidence.
- Determine availability.
- Produce a schema-valid normalized trajectory.

The Adapter must never invent a node, state transition, tool-node relationship, routing evidence, or outcome that cannot be reliably derived.

The Adapter does not calculate metrics or compare with Golden data.

### 4.4 Canonical Normalized Trajectory

The canonical trajectory is the interface between adapters and the evaluation engine.

Schema:

```text
schema/normalized_trajectory.schema.json
```

Conceptually:

```text
Trajectory
├── metadata
├── availability
├── turns[]
│   ├── input
│   ├── output
│   ├── nodes[]
│   │   ├── node_id
│   │   ├── sequence
│   │   ├── output
│   │   ├── state_changes[]
│   │   └── tool_calls[]
│   ├── unassociated_tool_calls[]
│   └── routing_evidence
├── final_state
└── outcome
```

### 4.5 Contract Validation

Every normalized trajectory is validated against the canonical JSON Schema before evaluation.

### 4.6 Independent Metric Evaluators

Each metric owns its required comparison/alignment logic:

- **NTS:** exact node sequence matching with position-aware sequence handling.
- **STS:** uses corresponding node alignment and compares state changes within aligned nodes.
- **TIS:** uses corresponding node context where available and aligns tools within those nodes; otherwise uses turn-level tools.
- **RS:** uses an LLM judge to evaluate whether the conversational/path decision was appropriate from customer input, agent response, expected path/context, and available evidence.
- **OS:** compares the final expected and observed outcome and attributes.

A shared alignment utility may be used internally, but there is no separate universal alignment score.

### 4.7 ATF Aggregator

Combines applicable component scores using the frozen weights:

```text
NTS = 30%
STS = 30%
TIS = 15%
RS  = 10%
OS  = 15%
```

If a metric is unavailable or not applicable, its weight is removed and the remaining applicable weights are renormalized.

### 4.8 Evaluation Result

The result contains more than a single ATF score:

```text
ATF score
Component scores
Metric applicability
Coverage
Metric-specific alignment diagnostics
Missing/extra/reordered nodes
State deviations
Tool deviations
Routing judge results
Outcome deviations
Diagnostics
```

---

## 5. Universal agent support

The framework supports different source execution architectures by placing all source-specific knowledge in the Adapter.

```text
Agent A raw trace ─┐
                   ├──► appropriate Adapter ───► canonical trace
Agent B raw trace ─┘                                  │
                                                      ▼
                                                  same evaluator
```

### Identifier contract

There is no separate core identifier-mapping configuration.

> **The Golden Dataset and normalized Observed trace must use the same canonical node and tool identifiers.**

How an Adapter converts source-specific names/structures into those canonical identifiers is an Adapter implementation concern. The evaluator performs exact matching after normalization.

---

## 6. Observability and applicability

The canonical trace exposes top-level availability:

```json
{
  "nodes": "available",
  "state": "available",
  "tools": "available",
  "routing": "available",
  "outcome": "available"
}
```

Values:

- `available` — information is exposed and can be evaluated.
- `unavailable` — information is conceptually relevant but not exposed sufficiently by the source trace.
- `not_applicable` — the dimension does not apply to the agent.

This prevents missing trace observability from being confused with agent failure.

---

## 7. State architecture

State reconstruction belongs to the Adapter.

For each observed node:

```text
State before node
       ↓
Node execution
       ↓
State after node
       ↓
Diff
       ↓
state_changes[]
```

Only actual changes are emitted. If a node changes nothing, `state_changes` is empty. If a previous value is not present, `old` may be `null`.

The evaluator compares the resulting state changes against the Golden trajectory.

---

## 8. Tool architecture

Tools are represented at node level when association is supported by the source trace.

```text
Node
 ├── Tool A
 ├── Tool B
 └── Tool C
```

If association cannot be reliably determined:

```text
Turn
 └── unassociated_tool_calls[]
```

The Adapter preserves execution sequence and never fabricates a node-tool relationship.

---

## 9. Routing architecture

Routing is intentionally not dependent on a dedicated routing field being present in every source trace.

For applicable turns, RS uses an LLM judge over evidence such as:

```text
Customer input
      +
Agent response
      +
Expected path/context
      +
Available normalized trajectory evidence
      ↓
LLM routing judge
      ↓
Correct / Partially Correct / Incorrect
```

This keeps RS distinct from NTS:

- **NTS:** did the agent execute the expected nodes?
- **RS:** given the conversational context, did the agent choose the appropriate direction/path?

---

## 10. Architectural boundaries

### Adapter owns

- Raw trace parsing
- Source-specific extraction
- State reconstruction
- Canonicalization required by the Adapter
- Tool-node association
- Availability determination

### Core evaluator owns

- Contract validation
- Metric-specific alignment/comparison
- Metric calculation
- Applicability and coverage
- RS judge orchestration/interface
- ATF aggregation
- Diagnostics

### Golden/domain layer owns

- Scenarios
- Expected trajectories
- Expected outcomes
- Domain-specific expected behavior

This separation is a core design constraint.

---

## 11. Frozen metric specifications

### NTS

```text
Coverage  = Matched Expected Nodes / Expected Nodes
Precision = Matched Observed Nodes / Observed Nodes
Recall    = Matched Expected Nodes / Expected Nodes
Order     = LCS(Expected Node Sequence, Observed Node Sequence)
           / max(Expected Count, Observed Count)

NTS = 0.40 × Coverage + 0.30 × Precision + 0.30 × Order
```

Turn and overall diagnostics are supported; overall scoring uses the complete trajectory.

### STS

```text
Transition Accuracy = Matched Complete Transitions
                      / max(Expected Transitions, Observed Transitions)

Transition Order = LCS(Expected Transition Sequence, Observed Transition Sequence)
                   / max(Expected Count, Observed Count)

STS = 0.70 × Transition Accuracy + 0.30 × Transition Order
```

A transition is `(key, old, new)`. Key/old/new accuracies are diagnostics.

### TIS

```text
Coverage  = Matched Expected Tools / Expected Tools
Precision = Matched Observed Tools / Observed Tools
Identity  = Correct Tool Matches / Aligned Tool Pairs
Input     = Average similarity of matched tool inputs
Order     = LCS(Expected Tool Sequence, Observed Tool Sequence)
            / max(Expected Count, Observed Count)

TIS = 0.25 × Coverage + 0.20 × Precision + 0.25 × Identity
    + 0.20 × Input + 0.10 × Order
```

### RS

```text
Semantic Routing Score = normalized LLM judge score
Routing Order = LCS(Expected Path Decisions, Observed Path Decisions)
                / max(Expected Count, Observed Count)

RS = 0.70 × Semantic Routing Score + 0.30 × Routing Order
```

LLM labels: Correct = 1.0, Partially Correct = 0.5, Incorrect = 0.0.

### OS

```text
Outcome Identity = 1 if identity matches, else 0
Attribute Accuracy = Correct Expected Attributes / Expected Attributes
Outcome Completion = Completed Required Outcome / Required Outcome

OS = 0.50 × Identity + 0.30 × Attributes + 0.20 × Completion
```

OS is conversation-level only.

### ATF

```text
ATF = 0.30 × NTS + 0.30 × STS + 0.15 × TIS + 0.10 × RS + 0.15 × OS
```

N/A metrics are excluded and remaining weights are renormalized.

---

## 12. Current development status

### Frozen

- ATF metric groups and component separation
- Metric formulas and weighting through 7H
- Metric-specific alignment ownership
- Exact node matching after normalization
- Adapter-based normalization
- Node-level state reconstruction in Adapter
- State represented as `state_changes[]`
- Node-level tool association where supported
- Unassociated turn-level tool calls
- LLM-based semantic routing evaluation
- Outcome evaluation at conversation level
- Canonical Golden/Observed schema
- Top-level availability
- Canonical normalized trajectory JSON Schema
- High-level architecture (6A)
- Adapter Contract (6C)
- Reference Adapter Contract (6D)
- Evaluation Engine Contract (7A)
- NTS (7C)
- STS (7D)
- TIS (7E)
- RS (7F)
- OS (7G)
- ATF Aggregation (7H)

### Next

Implementation of the Adapter, metric evaluators, RS judge interface, ATF aggregator, evaluation result contract, and tests against canonical fixtures.
