# Agent Eval — Low-Level Design

## 1. Scope

This document defines the component-level design for the frozen ATF architecture through **Step 7H**.

The LLD is implementation-oriented while preserving the core boundary: source-specific trace handling belongs to the Adapter; metric evaluation consumes canonical trajectories only.

---

## 2. Runtime pipeline

```text
Golden Dataset ──► Canonical Golden Trajectory ──┐
                                                  │
Raw Agent Trace ──► Adapter ──► Canonical Observed│
                                      │           │
                                      ▼           ▼
                               Schema Validation
                                      │
                                      ▼
                         ┌──────────────────────────┐
                         │ Independent Evaluators   │
                         │                          │
                         │ NTS │ STS │ TIS │ RS │ OS│
                         └────────────┬─────────────┘
                                      │
                                      ▼
                               ATF Aggregator
                                      │
                                      ▼
                              Evaluation Result
```

There is **no universal alignment stage**. Each metric owns the comparison/alignment it requires. Shared alignment algorithms may be implemented as internal utilities.

---

## 3. Target package/component structure

```text
agent_eval/
├── adapters/
│   ├── base.py
│   └── reference.py
├── schema/
│   └── normalized_trajectory.schema.json
├── validation/
│   └── contract_validator.py
├── alignment/
│   └── sequence_utils.py
├── metrics/
│   ├── base.py
│   ├── nts.py
│   ├── sts.py
│   ├── tis.py
│   ├── rs.py
│   └── os.py
├── routing/
│   └── judge.py
├── aggregation/
│   └── atf_aggregator.py
└── evaluation/
    └── evaluator.py
```

Exact package names are implementation choices; ownership boundaries are not.

---

## 4. Adapter interface

```python
class TraceAdapter(ABC):
    @abstractmethod
    def normalize(self, raw_trace: dict) -> NormalizedTrajectory:
        ...
```

The Adapter receives the complete raw trace because state and sequence reconstruction may require cross-turn context.

It returns a canonical `NormalizedTrajectory` or a normalization failure.

The Adapter does not compare against Golden data and does not calculate metrics.

---

## 5. Normalized trajectory responsibilities

The normalized trajectory is the interface between the Adapter and evaluator.

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

Schema:

`schema/normalized_trajectory.schema.json`

Golden data and normalized observed data use the same canonical node/tool identifiers. The evaluator performs exact identifier matching after normalization.

---

## 6. Adapter internals

Conceptually:

```text
normalize(raw_trace)
       │
       ├── extract_turns()
       ├── extract_nodes()
       ├── extract_node_outputs()
       ├── reconstruct_state_changes()
       ├── extract_tools()
       ├── associate_tools()
       ├── extract_routing_evidence()
       ├── extract_outcome()
       ├── determine_availability()
       └── validate()
```

A concrete Adapter may implement these differently.

### Non-negotiable rule

The Adapter must never invent nodes, state changes, tool-node relationships, routing evidence, or outcomes that cannot be reliably derived from the source trace.

---

## 7. Node extraction and sequencing

For each turn, emit only nodes that actually executed.

```json
{
  "node_id": "negotiation_classification",
  "sequence": 2,
  "output": {},
  "state_changes": [],
  "tool_calls": []
}
```

Rules:

1. Use authoritative source execution order when available.
2. Otherwise use source event ordering.
3. Preserve observed order exactly.
4. Do not add nodes that did not execute.
5. Do not reorder nodes for evaluation convenience.

---

## 8. State reconstruction

State reconstruction is an Adapter responsibility.

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

Only actual changes are emitted.

```json
{
  "key": "customer_payment_posture",
  "old": null,
  "new": "cannot_pay"
}
```

Rules:

- Unknown prior value may be represented as `old: null`.
- No change → `state_changes: []`.
- Multiple changes → multiple entries.
- State change remains attached to the node responsible for it.
- Adapter does not compare against Golden.

---

## 9. Tool extraction and association

A normalized tool call contains conceptually:

```json
{
  "tool_id": "payment_lookup",
  "sequence": 1,
  "input": {},
  "output": {},
  "status": "success"
}
```

Tools are placed in `node.tool_calls[]` only when source evidence supports the association.

If association cannot be established, preserve the tool at turn level:

```json
{
  "unassociated_tool_calls": [
    {
      "tool_id": "payment_lookup",
      "sequence": 2,
      "status": "success"
    }
  ]
}
```

The Adapter never guesses a node-tool relationship.

---

## 10. Routing evidence

The Adapter reports routing evidence when the source exposes it, but RS does not require a dedicated routing field.

The normalized turn may contain:

```json
{
  "routing_evidence": {}
}
```

RS combines this evidence with customer input, agent response, expected path/context, and other available normalized evidence for an LLM-based semantic routing judgment.

---

## 11. Outcome extraction

The Adapter extracts the final observable outcome without judging correctness.

```json
{
  "outcome": {
    "id": "instalment_arrangement_confirmed",
    "attributes": {
      "amount": 3000,
      "frequency": "monthly"
    }
  }
}
```

Outcome correctness belongs to OS.

---

## 12. Availability and validation

Top-level availability uses:

```text
available
unavailable
not_applicable
```

Interpretation:

- `available`: sufficient evidence exists for evaluation.
- `unavailable`: dimension may matter but source trace does not expose enough evidence.
- `not_applicable`: dimension does not conceptually apply.

A normalized trajectory must pass structural validation before evaluation.

Normalization failure stops evaluation. Normalization with limitations can proceed for applicable dimensions.

---

## 13. Shared sequence-alignment utility

Although alignment is not a separate evaluation stage, shared sequence utilities can avoid duplicated code.

Conceptually:

```python
align_sequences(expected, observed) -> SequenceAlignment
```

The utility should preserve:

- matched elements;
- missing expected elements;
- extra observed elements;
- order/reordering evidence;
- expected positions;
- observed positions.

### Frozen sequence behavior

```text
1. Compare expected and observed in order.
2. Exact match → match.
3. On mismatch, look ahead for the next matching expected item.
4. Identify missing/extra/reordered elements.
5. Continue from the matched position.
6. Preserve diagnostics.
```

Node identifiers are matched exactly after normalization.

Metrics decide how this alignment evidence contributes to their own scores.

---

## 14. Metric interface

Each metric should expose a conceptual interface such as:

```python
class MetricEvaluator(ABC):
    @abstractmethod
    def evaluate(
        self,
        golden: NormalizedTrajectory,
        observed: NormalizedTrajectory,
    ) -> MetricResult:
        ...
```

A `MetricResult` must contain at least:

```text
metric_id
score
status
coverage
applicability
diagnostics
```

Metric-specific diagnostics are allowed and expected.

---

## 15. NTS implementation contract

### Purpose

Measure expected versus observed node traversal.

### Scope

Turn-level diagnostics and overall trajectory score.

### Alignment

Exact node matching with position-aware sequence handling.

```text
Coverage  = Matched Expected Nodes / Expected Nodes
Precision = Matched Observed Nodes / Observed Nodes
Recall    = Matched Expected Nodes / Expected Nodes
Order     = LCS(Expected Sequence, Observed Sequence)
           / max(Expected Count, Observed Count)
```

### Composite

```text
NTS = 0.40 × Coverage
    + 0.30 × Precision
    + 0.30 × Order
```

Overall NTS is computed from the complete trajectory rather than blindly averaging turn scores.

Recall remains a diagnostic because it is equivalent to Coverage under the frozen definitions.

---

## 16. STS implementation contract

### Purpose

Measure expected versus observed node-level state changes.

A transition is:

```text
(key, old, new)
```

### Alignment

Use corresponding node alignment, then compare state transitions within each aligned node.

```text
Transition Accuracy =
Matched Complete Transitions
/ max(Expected Transitions, Observed Transitions)

Transition Order =
LCS(Expected Transition Sequence, Observed Transition Sequence)
/ max(Expected Count, Observed Count)
```

### Composite

```text
STS = 0.70 × Transition Accuracy
    + 0.30 × Transition Order
```

Key Accuracy, Old State Accuracy and New State Accuracy are diagnostics.

No state information means STS is N/A, not zero.

---

## 17. TIS implementation contract

### Purpose

Measure correct tool invocation, input, sequence, and node context.

### Alignment

- Align tools within corresponding nodes when node association exists.
- If tool association is unavailable, compare tools at turn level.
- Never invent node-tool association.

```text
Coverage  = Matched Expected Tools / Expected Tools
Precision = Matched Observed Tools / Observed Tools
Identity  = Correct Tool Matches / Aligned Tool Pairs
Input     = Average similarity of matched tool inputs
Order     = LCS(Expected Tool Sequence, Observed Tool Sequence)
            / max(Expected Count, Observed Count)
```

### Composite

```text
TIS = 0.25 × Coverage
    + 0.20 × Precision
    + 0.25 × Identity
    + 0.20 × Input
    + 0.10 × Order
```

No tool information means TIS is N/A.

---

## 18. RS implementation contract

### Purpose

Measure whether the agent selected the appropriate conversational/path direction given the customer input and agent response.

RS is **LLM-based semantic evaluation** rather than a requirement for an explicit routing field.

### Judge inputs

```text
Customer input
Agent response
Expected path/context
Available normalized trajectory evidence
```

### Judge output

```text
Correct           = 1.0
Partially correct = 0.5
Incorrect         = 0.0
```

### Composite

```text
Semantic Routing Score = normalized LLM judge score

Routing Order =
LCS(Expected Path Decisions, Observed Path Decisions)
/ max(Expected Count, Observed Count)

RS = 0.70 × Semantic Routing Score
   + 0.30 × Routing Order
```

If routing cannot meaningfully be evaluated, RS is N/A.

### Distinction from NTS

```text
NTS → Did the agent execute the expected nodes?
RS  → Given the conversation context, did it choose the appropriate direction/path?
```

---

## 19. OS implementation contract

### Purpose

Measure final outcome correctness.

OS is conversation-level only.

```text
Outcome Identity = 1 if identity matches, else 0
Attribute Accuracy = Correct Expected Attributes / Expected Attributes
Outcome Completion = Completed Required Outcome / Required Outcome
```

### Composite

```text
OS = 0.50 × Outcome Identity
   + 0.30 × Attribute Accuracy
   + 0.20 × Outcome Completion
```

Missing outcome information means OS is N/A.

---

## 20. Metric applicability

Before a metric scores, its applicability/availability must be checked.

Examples:

```text
Nodes available, tools unavailable
→ NTS evaluated
→ TIS N/A
```

```text
No state observability
→ STS N/A
```

```text
Routing cannot be meaningfully judged
→ RS N/A
```

N/A is not a failure score.

---

## 21. ATF aggregator contract

Conceptually:

```python
atf = aggregate(metric_results)
```

Frozen weights:

```text
NTS = 0.30
STS = 0.30
TIS = 0.15
RS  = 0.10
OS  = 0.15
```

Base formula:

```text
ATF = 0.30×NTS + 0.30×STS + 0.15×TIS + 0.10×RS + 0.15×OS
```

If one or more metrics are N/A, remove their weights and renormalize over applicable metrics.

The aggregator must return:

```text
ATF score
component scores
applicable metrics
excluded metrics
coverage
aggregation details
```

ATF must never hide component scores.

---

## 22. Evaluation result contract

Conceptually:

```json
{
  "evaluation_id": "EVAL_001",
  "status": "completed",
  "atf": {
    "score": 0.91
  },
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

The final contract should retain enough evidence to explain score changes:

- matched elements;
- missing elements;
- extra elements;
- order deviations;
- state deviations;
- tool deviations;
- routing judge results;
- outcome deviations;
- applicability/coverage.

---

## 23. Error handling

```text
Source limitation
      ↓
unavailable / not_applicable
      ↓
evaluate applicable dimensions

Adapter uncertainty
      ↓
do not invent evidence
      ↓
preserve limitations

Adapter failure
      ↓
normalization_failed
      ↓
stop evaluation
```

---

## 24. Testing strategy

### Adapter tests

Cover different raw architectures and normalization edge cases.

### Metric tests

Each metric requires fixtures for:

- perfect match;
- missing element;
- extra element;
- wrong identity;
- reordering;
- partial input/state/attribute match;
- unavailable dimension;
- multi-node turns;
- multi-tool nodes;
- multiple state changes;
- cross-turn trajectory deviations.

### Integration tests

Verify:

```text
Raw Trace
→ Adapter
→ Normalized Trace
→ Individual Metrics
→ ATF
→ Explainable Evaluation Result
```

### Golden fixture tests

Use the frozen canonical fixtures to ensure formulas and diagnostics remain stable.

---

## 25. Frozen status

Steps **1–7H are frozen**:

- 1 — Normalized Trajectory Contract
- 2 — Matching Semantics
- 3 — State Reconstruction Rules
- 4 — Applicability, N/A & Coverage
- 5A — Exact Scoring Algorithms
- 5B — Canonical Evaluation Fixtures
- 6A — High-Level ATF Architecture
- 6B — Canonical Normalized Trajectory Schema
- 6C — Adapter Contract
- 6D — Reference Adapter Contract
- 7A — Evaluation Engine Contract
- 7C — NTS
- 7D — STS
- 7E — TIS
- 7F — RS
- 7G — OS
- 7H — ATF Aggregation

The next phase is implementation.
