# Agent Trajectory Fidelity — Metric Specification

This document is the frozen scoring specification for ATF Steps **7C–7H**.

## 1. Scope

ATF compares a canonical Golden trajectory with a canonical Observed trajectory. The Adapter has already normalized source-specific traces and the Golden/Observed data use the same canonical node/tool identifiers.

Each metric is independently evaluated. Alignment is **metric-owned**, not a universal scoring stage. Shared sequence-alignment utilities may be used internally.

N/A means the dimension cannot be meaningfully evaluated; it is never treated as a zero/failure.

---

## 2. NTS — Node Traversal Similarity

### Purpose

Measures how closely the observed agent traversed the expected node trajectory.

### Components

- Node Coverage
- Node Precision
- Node Recall
- Node Order Similarity

### Levels

Turn-level diagnostics and overall trajectory score.

### Alignment

Exact node matching after Adapter normalization. Position-aware sequential matching identifies missing, extra and reordered nodes without cascading all later nodes into failures.

### Formulas

```text
Coverage  = Matched Expected Nodes / Expected Nodes
Precision = Matched Observed Nodes / Observed Nodes
Recall    = Matched Expected Nodes / Expected Nodes

Order Similarity =
    LCS(Expected Node Sequence, Observed Node Sequence)
    / max(Expected Node Count, Observed Node Count)

NTS = 0.40 × Coverage
    + 0.30 × Precision
    + 0.30 × Order Similarity
```

Recall is retained as a diagnostic because it is equivalent to Coverage under the frozen definitions.

Overall NTS is calculated from the complete trajectory, not as a simple average of turn scores.

---

## 3. STS — State Transition Similarity

### Purpose

Measures whether expected node-level state changes occurred in the observed trajectory.

A state transition is:

```text
(key, old, new)
```

### Components

- State Key Accuracy
- Old State Accuracy
- New State Accuracy
- Transition Accuracy
- Transition Order Similarity

### Levels

Turn + overall.

### Alignment

Use corresponding node alignment, then compare state changes within each aligned node. Unchanged state variables are not represented as transitions.

### Formulas

```text
Transition Accuracy =
    Matched Complete Transitions
    / max(Expected Transitions, Observed Transitions)

Transition Order Similarity =
    LCS(Expected Transition Sequence, Observed Transition Sequence)
    / max(Expected Transition Count, Observed Transition Count)

STS = 0.70 × Transition Accuracy
    + 0.30 × Transition Order Similarity
```

Key, old-value and new-value accuracy remain diagnostics explaining transition mismatches.

If state information is unavailable, STS is N/A.

---

## 4. TIS — Tool Invocation Similarity

### Purpose

Measures whether the agent invoked the expected tools with appropriate inputs, identity, placement and order.

### Components

- Tool Coverage
- Tool Precision
- Tool Identity
- Tool Input Similarity
- Tool Order Similarity

### Levels

Turn + overall.

### Alignment

Tools are aligned within corresponding nodes when node association is supported by the normalized trace. If association is unavailable, tools are compared at turn level. The Adapter must never invent node-tool relationships.

### Formulas

```text
Coverage  = Matched Expected Tools / Expected Tools
Precision = Matched Observed Tools / Observed Tools
Identity  = Correct Tool Matches / Aligned Tool Pairs
Input     = Average similarity of matched tool inputs

Order Similarity =
    LCS(Expected Tool Sequence, Observed Tool Sequence)
    / max(Expected Tool Count, Observed Tool Count)

TIS = 0.25 × Coverage
    + 0.20 × Precision
    + 0.25 × Identity
    + 0.20 × Input
    + 0.10 × Order Similarity
```

Tool input similarity compares expected arguments with observed arguments and may therefore produce partial scores.

No tool information means TIS is N/A.

---

## 5. RS — Routing Similarity

### Purpose

Measures whether the agent chose the appropriate conversational/path direction given the customer input and agent response.

RS is an **LLM-based semantic evaluation**. It does not require every source trace to expose a dedicated routing field.

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

### Levels

Turn-level routing judgments plus overall routing score.

### Formula

```text
Semantic Routing Score = normalized LLM judge score across applicable routing turns

Routing Order Similarity =
    LCS(Expected Path Decisions, Observed Path Decisions)
    / max(Expected Decision Count, Observed Decision Count)

RS = 0.70 × Semantic Routing Score
   + 0.30 × Routing Order Similarity
```

RS is intentionally distinct from NTS:

```text
NTS → Did the agent execute the expected nodes?
RS  → Given the conversational context, did the agent choose the appropriate direction/path?
```

If routing cannot meaningfully be evaluated, RS is N/A.

---

## 6. OS — Outcome Similarity

### Purpose

Measures whether the conversation reached the expected final outcome and whether required outcome attributes are correct.

### Components

- Outcome Identity
- Outcome Attribute Accuracy
- Outcome Completion

### Level

Conversation-level only.

### Formulas

```text
Outcome Identity = 1 if identity matches, else 0

Attribute Accuracy =
    Correct Expected Attributes / Expected Attributes

Outcome Completion =
    Completed Required Outcome / Required Outcome

OS = 0.50 × Outcome Identity
   + 0.30 × Attribute Accuracy
   + 0.20 × Outcome Completion
```

Only attributes defined in the Golden Dataset are evaluated. Missing outcome information means OS is N/A.

---

## 7. ATF — Agent Trajectory Fidelity

### Component weights

```text
NTS = 30%
STS = 30%
TIS = 15%
RS  = 10%
OS  = 15%
```

### Formula

```text
ATF = 0.30 × NTS
    + 0.30 × STS
    + 0.15 × TIS
    + 0.10 × RS
    + 0.15 × OS
```

### N/A handling

If one or more metrics are N/A, their weights are removed and the remaining applicable weights are renormalized.

Example:

```text
NTS = 0.90
STS = 0.80
TIS = N/A
RS  = 0.70
OS  = 1.00
```

Applicable weight = `0.30 + 0.30 + 0.10 + 0.15 = 0.85`.

```text
ATF =
(0.30×NTS + 0.30×STS + 0.10×RS + 0.15×OS)
/ 0.85
```

N/A is never converted to zero.

---

## 8. Metric result requirements

Every metric result must expose at least:

```text
metric_id
score
status
applicability
coverage
diagnostics
```

Diagnostics should retain the evidence needed to explain score changes, including where applicable:

- matched elements;
- missing elements;
- extra elements;
- order deviations;
- state deviations;
- tool deviations;
- routing judge results;
- outcome deviations.

---

## 9. Frozen rules

1. Golden and Observed trajectories are canonical before metric evaluation.
2. Node identifiers are matched exactly after Adapter normalization.
3. Alignment is metric-owned; there is no universal alignment score.
4. Sequence matters for trajectory evaluation.
5. Missing/extra/reordered evidence is preserved for diagnostics.
6. State is evaluated from node-level `state_changes[]`.
7. Tool-node association is used only when supported by trace evidence.
8. RS uses an LLM-based semantic routing judgment.
9. OS is conversation-level.
10. Overall metric scores are calculated from the complete applicable trajectory rather than blindly averaging turn scores.
11. N/A means not evaluable, not failure.
12. ATF always exposes component metric scores and diagnostics; it is never a black-box score.

---

## 10. Golden Scenario Reference

The first canonical Golden trajectory fixture is the ideal Motor Insurance scenario:

**Missed Premium → Financial Hardship → Instalment Arrangement**

Fixture:

```text
golden/motor_insurance_hardship_installment.json
```

The fixture uses the canonical normalized trajectory contract. It preserves the supplied scenario exactly as the ideal trajectory, including the observed node/tool/state structure. Nodes from the broader domain node catalogue that are not traversed by this scenario are not artificially inserted into the Golden trajectory.

The scenario contains:

```text
Turn 1 → initialize_call → greet_customer
Turn 2 → verify_customer
Turn 3 → verify_customer → verify_mobile + verify_dob
Turn 4 → classify_intent → hardship_node
Turn 5 → classify_intent → hardship_node → instalment_eligibility
Turn 6 → classify_intent → hardship_node → check_eligibility
Turn 7 → classify_intent → hardship_node → check_eligibility
Turn 8 → classify_intent
```

The Golden trajectory therefore becomes the baseline against which the planned Observed test fixtures are evaluated.

---

## 11. Evaluation Deviation Taxonomy

The test suite will intentionally introduce controlled deviations from the Golden trajectory. These are the canonical evaluation scenarios.

| Deviation | Primary metric | Definition |
|---|---|---|
| Correct answer, wrong trajectory | NTS | Surface response is correct but required trajectory execution is missing or different. |
| Wrong node executed | NTS | Expected node is replaced by another node. |
| Node skipped | NTS | Required node is not traversed. |
| Unexpected node executed | NTS | An unnecessary or incorrect node is traversed. |
| Wrong node order | NTS | Expected nodes occur but in the wrong sequence. |
| Wrong state transition | STS | A state changes to an incorrect value. |
| Missing state transition | STS | Expected state change does not occur. |
| Wrong state progression | STS | Correct states occur but expected transition sequence is violated. |
| Missing tool call | TIS | Required tool invocation is absent. |
| Unexpected tool call | TIS | Tool is invoked when it is not required. |
| Wrong tool | TIS | Different tool is invoked instead of the expected tool. |
| Wrong tool input | TIS | Correct tool is invoked with incorrect arguments. |
| Wrong tool sequence | TIS | Correct tools are invoked in the wrong order. |
| Wrong conversational path | RS | Agent response may be superficially appropriate but the conversational/path decision is inappropriate for the customer context. |
| Partial/incorrect outcome | OS | Final outcome is incomplete or required outcome attributes are incorrect. |
| Correct trajectory, wrong final outcome | OS | Execution trajectory is otherwise correct but the required business outcome is not achieved. |
| Trajectory drift across turns | NTS / RS | Agent progressively diverges from the expected trajectory across turns. |
| Insufficient evidence | Applicability / N/A | Trace does not expose enough information to evaluate a metric; result is N/A rather than a false failure. |

### Reference examples

```text
Correct answer, wrong trajectory:
Agent says "We can arrange monthly instalments" but skips a required execution step.

Node skipped:
Expected confirm_outcome is absent before execute_action.

Unexpected node:
Agent invokes handle_exception even though no exception occurred.

Wrong node order:
execute_action → confirm_outcome instead of confirm_outcome → execute_action.

Wrong state transition:
instalment_status: proposed → rejected instead of proposed → agreed.

Missing state transition:
Agent reaches agreement but never changes instalment_status to agreed.

Wrong state progression:
none → confirmed without the expected intermediate states.

Missing tool call:
create_instalment_plan is never invoked.

Unexpected tool call:
Agent calls cancel_instalment_plan even though the customer agreed.

Wrong tool:
check_policy_payment_status is called instead of create_instalment_plan.

Wrong tool input:
create_instalment_plan receives instalment_amount = 5000 instead of 3000.

Wrong tool sequence:
The instalment plan is created before customer agreement.

Wrong conversational path:
Customer expresses hardship, but the agent continues requesting full payment instead of moving to hardship handling.

Partial/incorrect outcome:
Instalment arrangement is created, but frequency or number of instalments is incorrect.

Correct trajectory, wrong outcome:
Expected nodes/tools/states occur, but the final arrangement is not confirmed.

Trajectory drift:
Agent starts correctly, then moves from hardship → instalment → an unrelated payment flow.

Insufficient evidence:
The source trace does not expose state transitions, so STS is N/A rather than scored as a failure.
```

These scenarios will be implemented as Golden-vs-Observed test fixtures after the canonical Golden trajectory is frozen.

---

## 12. Adapter and fixture relationship

The Golden fixture is already canonical and therefore does not require an Adapter transformation. Observed traces from different agent frameworks are passed through the appropriate Adapter first.

```text
Golden canonical fixture
          │
          │
          ├──────────────┐
          │              │
          ▼              ▼
      Golden Trace   Raw Observed Trace
                         │
                         ▼
                      Adapter
                         │
                         ▼
                Normalized Observed
                         │
                         ▼
                Metric Evaluators
```

The evaluator compares Golden and Observed trajectories only after both satisfy the canonical contract.
