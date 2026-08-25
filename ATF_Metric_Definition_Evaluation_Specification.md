# Agent Trajectory Fidelity (ATF)
## Metric Definition & Evaluation Specification

## 1. Purpose

Agent Trajectory Fidelity (ATF) measures how closely an agent's **observed execution trajectory** follows the **expected trajectory** defined by a Golden Dataset.

ATF evaluates:

- Node traversal
- State transitions
- Tool invocations
- Routing decisions
- Final outcome

Core comparison:

```text
Golden Dataset
(Expected Trajectory)
        │
        ▼
   Golden Adapter
        │
        ▼
Normalized Expected Trajectory
        │
        ▼
   Metric Evaluation
        ▲
        │
Normalized Observed Trajectory
        ▲
        │
   Observed Adapter
        ▲
        │
Observed Agent Trace
```

---

# 2. Core Evaluation Model

A trajectory consists of:

```text
Nodes
+
State Transitions
+
Tool Calls
+
Routing
+
Outcome
```

Primary metric groups:

| Metric Group | Abbreviation | Weight |
|---|---:|---:|
| Node Traversal Similarity | NTS | 30% |
| State Transition Similarity | STS | 30% |
| Tool Invocation Similarity | TIS | 15% |
| Routing Similarity | RS | 10% |
| Outcome Similarity | OS | 15% |

Weights are configurable, but the above are the default ATF configuration.

---

# 3. Golden Dataset vs Observed Trace

## 3.1 Golden Dataset

The Golden Dataset defines what the agent **should have done**.

For every turn, it can contain:

```text
conversation
intent
entities
tools
trace
    ├── node
    ├── details
    ├── state
    └── tools
```

The Golden Dataset is an **expected execution trace**, not simply a collection of expected answers.

## 3.2 Observed Trace

The Observed Trace represents what the actual agent did.
For example
```text
Turn 6

path_selector
    ↓
tool_resolver
    ↓
agent_reason
    ↓
tool_execution
    ↓
agent_reason
    ↓
response
```
It may contain:

- Additional nodes
- Missing nodes
- Different node ordering
- Different tools
- Different state changes
- Different routing
- Different outcomes

The ATF framework does not assume that the observed trace has exactly the same structure as the Golden Dataset.

---

# 4. Adapter Layer

Different agents can expose fundamentally different trace formats.

Example:

```text
Agent A

path_selector
tool_resolver
agent_reason
tool_execution
response
```

Another agent may expose:

```text
entity_extract
negotiation_classification
plan_proposal_state
discount_planning_agent
response
```

Another may expose little or no explicit state information.

Therefore the ATF engine must **not depend directly on a specific agent architecture**.

Instead:

```text
Agent Trace
     │
     ▼
Agent-specific Adapter
     │
     ▼
Normalized Trajectory
```

The same principle applies to the Golden Dataset if its not already in the normalized format:

```text
Golden Dataset
     │
     ▼
Golden Adapter
     │
     ▼
Normalized Expected Trajectory
```

---

# 5. Normalized Trajectory

Adapters convert Golden and Observed data into a common representation.

Conceptually:

```json
{
  "turn_id": "turn_0006",
  "nodes": [
    {
      "node_id": "path_selector",
      "node_type": "routing"
    },
    {
      "node_id": "tool_resolver",
      "node_type": "tool_resolution"
    },
    {
      "node_id": "agent_reason",
      "node_type": "reasoning"
    }
  ],
  "state_changes": [],
  "tool_calls": [],
  "routing": {},
  "outcome": {}
}
```

The Adapter maps source-specific fields into these generic primitives.

---

# 6. State Observability

State does **not** need a universal domain-specific schema.

The framework treats state keys generically.

Examples:

```text
Collections:
payment_posture
discount_stage
verification_status
```

```text
Motor Insurance:
premium_payment_status
hardship_eligibility
instalment_arrangement_status
```

The Adapter exposes:

```text
state_key
old_value
new_value
```

## 6.1 State Provenance

Each normalized state transition should ideally contain:

```text
source = explicit
source = reconstructed
source = unavailable
```

- **Explicit:** directly provided by the trace.
- **Reconstructed:** reliably derived from available trace evidence.
- **Unavailable:** insufficient evidence to determine the state.

`Unavailable` must **not** be interpreted as score zero.

---

# 7. Metric Group 1 — Node Traversal Similarity (NTS)

## Definition

NTS measures how closely the observed execution path matches the expected node trajectory.

It evaluates:

- Node presence
- Node identity
- Node ordering
- Node sequence

## 7.1 Node Coverage

```text
Node Coverage =
Number of expected nodes observed
----------------------------------
Total expected nodes
```

Example:

```text
Expected = A B C D
Observed = A B D

Coverage = 3 / 4 = 0.75
```

**Validation Level:** Turn + Overall

## 7.2 Node Precision

```text
Node Precision =
Expected observed nodes
----------------------
Total observed nodes
```

Example:

```text
Expected = A B C D
Observed = A B D X

Precision = 3 / 4 = 0.75
```

**Validation Level:** Turn + Overall

## 7.3 Node Recall

```text
Node Recall =
Correctly observed expected nodes
---------------------------------
Total expected nodes
```

**Validation Level:** Turn + Overall

## 7.4 Node Order Similarity

Use normalized Longest Common Subsequence (LCS):

```text
Node Order Similarity =
LCS(Expected Nodes, Observed Nodes)
-----------------------------------
max(len(Expected), len(Observed))
```

**Validation Level:** Turn + Overall

## 7.5 NTS Formula

```text
NTS_turn =
0.40 × Node Coverage
+
0.30 × Node Order Similarity
+
0.30 × Node Precision
```

Overall:

```text
NTS =
Σ(NTS_turn × turn_weight)
-------------------------
Σ(turn_weight)
```

Default:

```text
turn_weight = 1
```

---

# 8. Metric Group 2 — State Transition Similarity (STS)

## Definition

STS measures whether the agent changed state in the same way as the expected trajectory.

A state transition is:

```text
State Key
+
Old Value
+
New Value
```

## 8.1 State Key Accuracy

```text
State Key Accuracy =
Correct expected state keys observed
-------------------------------------
Total expected state keys
```

**Validation Level:** Turn + Overall

## 8.2 Old-State Accuracy

```text
Old State Accuracy =
Correct old-state values
------------------------
Expected state transitions
```

**Validation Level:** Turn + Overall

## 8.3 New-State Accuracy

```text
New State Accuracy =
Correct new-state values
------------------------
Expected state transitions
```

**Validation Level:** Turn + Overall

## 8.4 State Transition Accuracy

A complete transition is correct only if:

```text
state key matches
AND
old value matches
AND
new value matches
```

Formula:

```text
State Transition Accuracy =
Fully correct transitions
-------------------------
Expected transitions
```

**Validation Level:** Turn + Overall

## 8.5 State Transition Order Similarity

```text
State Transition Order =
LCS(Expected transition sequence,
    Observed transition sequence)
-----------------------------------
max(expected_count, observed_count)
```

**Validation Level:** Turn + Overall

## 8.6 STS Formula

```text
STS_turn =
0.20 × State Key Accuracy
+
0.20 × Old State Accuracy
+
0.30 × New State Accuracy
+
0.20 × State Transition Accuracy
+
0.10 × State Transition Order
```

---

# 9. Metric Group 3 — Tool Invocation Similarity (TIS)

## Definition

TIS measures whether the agent invoked expected tools with expected parameters and order.

## 9.1 Tool Coverage

```text
Tool Coverage =
Expected tools invoked
----------------------
Total expected tools
```

**Validation Level:** Turn + Overall

## 9.2 Tool Precision

```text
Tool Precision =
Expected observed tool calls
----------------------------
Total observed tool calls
```

This penalizes unexpected tool calls.

**Validation Level:** Turn + Overall

## 9.3 Tool Identity Accuracy

```text
Tool Identity Accuracy =
Correct tool identities
-----------------------
Expected tool invocations
```

**Validation Level:** Turn + Overall

## 9.4 Tool Input Similarity

For each argument:

```text
Argument Match =
Number of correctly matched arguments
-------------------------------------
Number of expected arguments
```

Then:

```text
Tool Input Similarity =
Σ argument_match
----------------
Number of tool calls
```

Numerical arguments may use configurable tolerance.

**Validation Level:** Turn + Overall

## 9.5 Tool Invocation Order

```text
Tool Order Similarity =
LCS(Expected Tool Sequence,
    Observed Tool Sequence)
--------------------------------
max(expected_count, observed_count)
```

**Validation Level:** Turn + Overall

## 9.6 TIS Formula

```text
TIS_turn =
0.25 × Tool Coverage
+
0.20 × Tool Precision
+
0.25 × Tool Identity Accuracy
+
0.20 × Tool Input Similarity
+
0.10 × Tool Order Similarity
```

---

# 10. Metric Group 4 — Routing Similarity (RS)

## Definition

RS measures whether the agent selected the expected execution path, response target, specialist, or escalation route.

Examples:

```text
customer
hardship_team
discount_planning_agent
human
```

Routing is different from node traversal. A node can execute correctly while routing to the wrong target.

## 10.1 Routing Target Accuracy

```text
Routing Target Accuracy =
Correct routing targets
-----------------------
Expected routing targets
```

**Validation Level:** Turn + Overall

## 10.2 Path Selection Accuracy

```text
Path Selection Accuracy =
Correct path selections
-----------------------
Expected path selections
```

**Validation Level:** Turn + Overall

## 10.3 Routing Order Similarity

```text
Routing Order =
LCS(Expected routing sequence,
    Observed routing sequence)
--------------------------------
max(expected length, observed length)
```

**Validation Level:** Overall

## 10.4 RS Formula

```text
RS_turn =
0.60 × Routing Target Accuracy
+
0.30 × Path Selection Accuracy
+
0.10 × Routing Order Similarity
```

For turns where routing order is not applicable, that component is `N/A`.

---

# 11. Metric Group 5 — Outcome Similarity (OS)

## Definition

OS measures whether the agent achieved the expected business outcome.

Outcome is evaluated separately from response text.

Example:

```text
Expected Outcome:
instalment_arrangement_confirmed
```

Attributes may include:

```text
amount = 2500
frequency = monthly
number_of_payments = 2
first_payment_date = 2026-08-25
```

## 11.1 Outcome Identity Accuracy

```text
Outcome Identity Accuracy =
1 if observed outcome = expected outcome
0 otherwise
```

**Validation Level:** Overall

## 11.2 Outcome Attribute Accuracy

```text
Outcome Attribute Accuracy =
Correct outcome attributes
--------------------------
Expected outcome attributes
```

**Validation Level:** Overall

## 11.3 Outcome Completion

```text
Outcome Completion =
Satisfied required conditions
-----------------------------
Total required conditions
```

**Validation Level:** Overall

## 11.4 OS Formula

```text
OS =
0.50 × Outcome Identity Accuracy
+
0.30 × Outcome Attribute Accuracy
+
0.20 × Outcome Completion
```

OS is primarily conversation-level because the final business outcome usually cannot be determined from a single turn.

---

# 12. Metric Validation Levels

| Level | Meaning |
|---|---|
| Turn | Metric calculated independently for every turn |
| Overall | Metric calculated across the complete conversation |
| Both | Turn score calculated first, then aggregated into conversation score |

| Metric | Level |
|---|---|
| Node Coverage | Both |
| Node Precision | Both |
| Node Recall | Both |
| Node Order Similarity | Both |
| NTS | Both |
| State Key Accuracy | Both |
| Old State Accuracy | Both |
| New State Accuracy | Both |
| State Transition Accuracy | Both |
| State Transition Order | Both |
| STS | Both |
| Tool Coverage | Both |
| Tool Precision | Both |
| Tool Identity Accuracy | Both |
| Tool Input Similarity | Both |
| Tool Order Similarity | Both |
| TIS | Both |
| Routing Target Accuracy | Both |
| Path Selection Accuracy | Both |
| Routing Order Similarity | Overall |
| RS | Both |
| Outcome Identity Accuracy | Overall |
| Outcome Attribute Accuracy | Overall |
| Outcome Completion | Overall |
| OS | Overall |
| ATF | Overall |

---

# 13. Turn-Level vs Overall Evaluation

The framework should not calculate only one score at the end.

```text
Turn 1
 Expected vs Observed
       ↓
 NTS / STS / TIS / RS
       ↓
Turn Score

Turn 2
 Expected vs Observed
       ↓
 NTS / STS / TIS / RS
       ↓
Turn Score

...

Turn N
 Expected vs Observed
       ↓
 NTS / STS / TIS / RS
       ↓
Turn Score

       ↓
Conversation Aggregation
       ↓
NTS / STS / TIS / RS / OS
       ↓
ATF
```

This identifies **where** the agent deviated, not only whether it deviated.

---

# 14. Handling Missing / Non-Observable Metrics

Not every agent exposes every evaluation primitive.

Example:

```text
Agent A:
Nodes ✓
States ✓
Tools ✓
Routing ✓
Outcome ✓
```

Another:

```text
Agent B:
Nodes ✓
States N/A
Tools ✓
Routing N/A
Outcome ✓
```

The framework must distinguish:

```text
0
```

from:

```text
N/A
```

### `0`

The information was available, but the agent was incorrect.

### `N/A`

The information was not observable or applicable.

`N/A` must not be interpreted as a score of zero.

---

# 15. ATF Calculation With N/A Metrics

Default weights:

```text
NTS = 0.30
STS = 0.30
TIS = 0.15
RS  = 0.10
OS  = 0.15
```

For a fully observable agent:

```text
ATF =
0.30 × NTS
+
0.30 × STS
+
0.15 × TIS
+
0.10 × RS
+
0.15 × OS
```

If a metric is unavailable, it is excluded from both numerator and denominator:

```text
ATF =
Σ(weight_i × score_i)
---------------------
Σ(weight_i)
```

where only applicable metrics are included.

Example:

```text
NTS = 0.90
STS = N/A
TIS = 0.95
RS  = 1.00
OS  = 1.00
```

The resulting score must be accompanied by:

```text
Metric Coverage = 70%
```

---

# 16. Metric Coverage

```text
Metric Coverage =
Applicable metric weight
------------------------
Total metric weight
```

Example:

```text
NTS ✓   30%
STS —   30%
TIS ✓   15%
RS  ✓   10%
OS  ✓   15%

Coverage = 70%
```

Metric Coverage should always be returned alongside ATF.

---

# 17. Recommended ATF Output

```json
{
  "atf": {
    "score": 0.91,
    "coverage": 1.0
  },
  "groups": {
    "nts": {
      "score": 0.90,
      "status": "available"
    },
    "sts": {
      "score": 0.88,
      "status": "available"
    },
    "tis": {
      "score": 0.95,
      "status": "available"
    },
    "rs": {
      "score": 1.00,
      "status": "available"
    },
    "os": {
      "score": 0.90,
      "status": "available"
    }
  },
  "turns": {
    "turn_0001": {
      "nts": 1.0,
      "sts": 1.0,
      "tis": 1.0,
      "rs": 1.0
    },
    "turn_0002": {
      "nts": 0.83,
      "sts": 0.75,
      "tis": 1.0,
      "rs": 1.0
    }
  }
}
```

**Important:** Never collapse the evaluation into ATF alone.

ATF is the summary score. The individual metric groups and their underlying measurements are the diagnostic layer.

---

# 18. Recommended Evaluation Hierarchy

```text
ATF
│
├── NTS — Node Traversal Similarity
│   ├── Node Coverage
│   ├── Node Precision
│   ├── Node Recall
│   └── Node Order Similarity
│
├── STS — State Transition Similarity
│   ├── State Key Accuracy
│   ├── Old State Accuracy
│   ├── New State Accuracy
│   ├── State Transition Accuracy
│   └── State Transition Order
│
├── TIS — Tool Invocation Similarity
│   ├── Tool Coverage
│   ├── Tool Precision
│   ├── Tool Identity Accuracy
│   ├── Tool Input Similarity
│   └── Tool Order Similarity
│
├── RS — Routing Similarity
│   ├── Routing Target Accuracy
│   ├── Path Selection Accuracy
│   └── Routing Order Similarity
│
└── OS — Outcome Similarity
    ├── Outcome Identity Accuracy
    ├── Outcome Attribute Accuracy
    └── Outcome Completion
```

---

# 19. End-to-End Evaluation Flow

```text
                 GOLDEN DATASET
                       │
                       ▼
                Golden Adapter
                       │
                       ▼
              Expected Trajectory
                       │
                       ▼
                ┌─────────────┐
                │   COMPARE   │
                └─────────────┘
                       ▲
                       │
              Observed Trajectory
                       ▲
                       │
                Observed Adapter
                       ▲
                       │
                 AGENT TRACE
```

Then:

```text
Expected Trajectory
        │
        ├──────────────┐
        │              │
        ▼              ▼
     Turn 1          Turn N
        │              │
        ▼              ▼
   NTS/STS/TIS/RS  NTS/STS/TIS/RS
        │              │
        └───────┬──────┘
                ▼
        Conversation Metrics
                │
        ┌───────┼────────┐
        ▼       ▼        ▼
       NTS     STS      TIS
        │       │        │
        └───────┼────────┘
                ▼
              RS / OS
                │
                ▼
               ATF
```

---

# 20. Adapter Contract

Every adapter should produce the same normalized objects:

```text
NormalizedTurn
    ├── turn_id
    ├── nodes[]
    ├── state_changes[]
    ├── tool_calls[]
    ├── routing
    └── outcome
```

Each node:

```text
NormalizedNode
    ├── node_id
    ├── node_type
    ├── sequence_index
    ├── details
    └── state_changes[]
```

Each state change:

```text
StateChange
    ├── key
    ├── old_value
    ├── new_value
    └── source
```

Each tool call:

```text
ToolCall
    ├── tool_name
    ├── arguments
    ├── result
    └── sequence_index
```

Routing:

```text
Routing
    ├── path
    ├── target
    └── sequence
```

Outcome:

```text
Outcome
    ├── outcome_id
    └── attributes
```

---

# 21. Most Important Design Rule

The ATF evaluator should **never directly understand an individual agent's trace format**.

Bad architecture:

```text
ATF
 │
 ├── if collections trace
 ├── if insurance trace
 ├── if agent-X trace
 └── if agent-Y trace
```

Preferred architecture:

```text
                   ATF Engine
                       │
              Normalized Contract
                       ▲
                       │
       ┌───────────────┼────────────────┐
       │               │                │
Collections Adapter  Insurance       Agent-X
       │             Adapter          Adapter
       │               │                │
       ▼               ▼                ▼
 Collections       Insurance        Agent-X
 Trace             Trace            Trace
```

This makes the framework **domain-independent and agent-architecture-independent**.

- Domain-specific knowledge belongs in the **Golden Dataset**.
- Source-specific knowledge belongs in the **Adapter**.
- Evaluation logic belongs in the **ATF Metric Engine**.

---

# 22. Final Architecture Principle

```text
DOMAIN
  │
  └── Golden Dataset
       └── What should happen?

AGENT
  │
  └── Runtime Trace
       └── What actually happened?

ADAPTER
  │
  └── How do we represent either one
      in a common structure?

METRIC ENGINE
  │
  ├── NTS
  ├── STS
  ├── TIS
  ├── RS
  └── OS

ATF AGGREGATOR
  │
  └── Overall Agent Trajectory Fidelity
```

**This separation should be treated as the core contract of the ATF framework.**
