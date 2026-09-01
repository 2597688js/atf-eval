# ATF Metrics — Full Step-by-Step Walkthrough (One Worked Example)

This document works through **every ATF component metric by hand, from first principles**,
using a single pair of trajectories as the running example:

- **Expected (golden):** `agent-eval-main/golden/motor_insurance_hardship_installment.json`
- **Observed (deviation fixture):** `agent-eval-main/tests/fixtures/scenarios/correct_answer_wrong_trajectory.json`

This scenario is chosen because it exercises the most machinery: it's a full 8-turn
conversation (not a single-turn fixture), with a single, precisely-located deviation —
`hardship_node` at turn 4 is skipped — so you can watch how each metric reacts to exactly
one change instead of many at once.

For the roll-up across **all** fixtures in this dataset (including the two single-turn
scenarios), see `MANUAL_CALCULATION_VERIFICATION.md`. This document goes deeper on the *how*
for one example; that one goes wider across *all* examples.

---

## 0. Turn-level vs. Conversation-level — read this first

Every metric in ATF can conceptually be computed **per turn** (just that one turn's nodes /
transitions / tool calls) or **per conversation** (the whole trajectory, all turns combined).
These are genuinely different numbers, computed differently:

- **Turn-level**: score just one turn's data in isolation.
- **Conversation-level**: concatenate *every* turn's data (nodes, transitions, tool calls) into
  one flat sequence, in turn order, and score that combined sequence **once**. This is *not*
  the average of the per-turn scores — it's one computation over everything strung together.
  (This concatenation rule, rather than turn-averaging, is a frozen design decision in
  `src/atf_eval` — see Frozen Rule #10.)

**Every number in this document is conversation-level** — that's what the `atf-dashboard`
script reports, and what `MANUAL_CALCULATION_VERIFICATION.md` verifies. The table below shows
which level each metric actually supports, and which one we're computing here.

| Metric | Turn-level exists? | Conversation-level exists? | **What this document computes** |
|---|---|---|---|
| **NTS** | ✅ yes (`nts_turn`) | ✅ yes (`nts_conversation`) | **Conversation-level** |
| **STS** | ✅ yes (`sts_turn`) | ✅ yes (`sts_conversation`) | **Conversation-level** |
| **TIS** | ✅ yes (`tis_turn` — via node-level alignment) | ✅ yes (`tis_conversation`) | **Conversation-level** |
| **RS** | ✅ yes (one LLM judge call per turn) | ✅ yes (mean of turn judgments + order) | **Conversation-level** (N/A here either way) |
| **OS** | ❌ **no turn-level version exists** | ✅ yes — **the only level OS has** | **Conversation-level** (its only option) |
| **ATF** | — (composite of the above) | ✅ | **Conversation-level** |

The important callouts:
- **OS is structurally conversation-only.** An "outcome" is a property of the whole call (did
  the customer end up with an accepted installment plan?), not of any single turn — so
  `METRICS.md` doesn't even define a turn-level OS. There's nothing to compare it against.
- **NTS/STS/TIS *do* have turn-level versions**, but the numbers in this document are **not**
  those — they're the conversation-level concatenation. A turn-level NTS for, say, turn 4 alone
  would score very differently (see the callout box in §1).
- **RS** technically produces turn-level judge verdicts that then feed into its
  conversation-level aggregate — but since no judge client is used and no routing data exists
  in this dataset, both levels come out N/A regardless.

---

## 1. NTS — Node Trajectory Similarity

> **Level: Conversation-level.** All 8 turns' `nodes` are concatenated into one 13-item
> (expected) / 12-item (observed) sequence before anything is compared. A turn-level NTS for
> turn 4 alone would look completely different (see box at the end of this section).

### Formula (`METRICS.md` §2)

```
Coverage  = Matched Nodes / Expected Nodes
Precision = Matched Nodes / Observed Nodes
Order     = LCS(Expected Node Sequence, Observed Node Sequence) / max(Expected, Observed)

NTS = 0.40×Coverage + 0.30×Precision + 0.30×Order
```

### The two full node sequences (E = expected/golden, O = observed/fixture)

| Turn | Golden nodes | Observed nodes |
|---|---|---|
| 1 | `initialize_call`, `greet_customer` | `initialize_call`, `greet_customer` |
| 2 | `verify_customer` | `verify_customer` |
| 3 | `verify_customer` | `verify_customer` |
| 4 | `classify_intent`, **`hardship_node`** | `classify_intent` **(hardship_node missing)** |
| 5 | `classify_intent`, `hardship_node` | `classify_intent`, `hardship_node` |
| 6 | `classify_intent`, `hardship_node` | `classify_intent`, `hardship_node` |
| 7 | `classify_intent`, `hardship_node` | `classify_intent`, `hardship_node` |
| 8 | `classify_intent` | `classify_intent` |

```
E (13): initialize_call, greet_customer, verify_customer, verify_customer,
        classify_intent, hardship_node, classify_intent, hardship_node,
        classify_intent, hardship_node, classify_intent, hardship_node, classify_intent

O (12): initialize_call, greet_customer, verify_customer, verify_customer,
        classify_intent, classify_intent, hardship_node,
        classify_intent, hardship_node, classify_intent, hardship_node, classify_intent
```

### Finding LCS(E, O) — the "delete one item" shortcut

Delete row 6 of E (`hardship_node`, turn 4):

| # | E after deleting row 6 |
|---|---|
| 1 | initialize_call |
| 2 | greet_customer |
| 3 | verify_customer |
| 4 | verify_customer |
| 5 | classify_intent |
| 6 | classify_intent |
| 7 | hardship_node |
| 8 | classify_intent |
| 9 | hardship_node |
| 10 | classify_intent |
| 11 | hardship_node |
| 12 | classify_intent |

This matches O exactly, item for item. Since a common subsequence of length 12 was found, and
`LCS(E,O) ≤ min(13,12) = 12` is the mathematical ceiling (a common subsequence can never exceed
the shorter list's length), the ceiling is reached:

```
LCS(E, O) = 12
```

*(A full 9×8 dynamic-programming table proving this cell-by-cell — for readers who want the
exhaustive derivation rather than the shortcut — is worked out in the session transcript this
document is drawn from; available on request.)*

### Computing NTS

```
Coverage  = 12 / 13 = 0.923077
Precision = 12 / 12 = 1.000000
Order     = 12 / max(13,12) = 12/13 = 0.923077

NTS = 0.40×0.923077 + 0.30×1.000000 + 0.30×0.923077
    = 0.369231 + 0.300000 + 0.276923
    = 0.946154
```

> **Turn-level contrast (not what's used, but illustrative):** scored on turn 4 alone,
> expected = `[classify_intent, hardship_node]` (2 nodes) vs. observed = `[classify_intent]`
> (1 node) → Coverage = 1/2 = 0.500, Precision = 1/1 = 1.000, Order = 1/2 = 0.500 →
> turn-level NTS(T4) = 0.40×0.5+0.30×1.0+0.30×0.5 = 0.500. The conversation-level score
> (0.946) is much higher because the same single miss gets diluted across all 13 expected
> nodes instead of just 2.

---

## 2. STS — State Transition Similarity

> **Level: Conversation-level.** All state changes across all 8 turns are combined into one
> transition sequence before comparison — same concatenation rule as NTS.

### Formula (`METRICS.md` §3)

```
Transition Accuracy = Matched Complete Transitions / max(Expected Transitions, Observed Transitions)
Transition Order Similarity = LCS(Expected Transition Sequence, Observed Transition Sequence) / max(Expected, Observed)

STS = 0.70×Transition Accuracy + 0.30×Transition Order Similarity
```

Alignment rule: transitions are only compared *within nodes that already aligned* under NTS.
Since `hardship_node` (T4) has no observed partner, its transition has nowhere to pair — it's
excluded before any transition-level comparison starts.

### The two transition sequences

Turns 1–2 contribute **zero** transitions on either side (their `state_changes` are empty
arrays in golden — nothing changes yet, so nothing is recorded; `METRICS.md` explicitly says
"unchanged state variables are not represented as transitions").

| Turn | Expected transition | Present in observed? |
|---|---|---|
| T3 | `customer_verified: false→true` | ✅ |
| T4 | `customer_harship: false→true` | ❌ (node missing) |
| T5 | `installment_eligible: false→true` | ✅ |
| T6 | `customer_unable_to_pay: false→true` | ✅ |
| T7 | `customer_accept_installment: false→true` | ✅ |

```
E (5 keys): customer_verified, customer_harship, installment_eligible, customer_unable_to_pay, customer_accept_installment
O (4 keys): customer_verified,                    installment_eligible, customer_unable_to_pay, customer_accept_installment
```

### Finding LCS of the key sequences — same shortcut

Delete `customer_harship` (position 2) from E → exactly matches O. So:

```
LCS(E, O) = min(5, 4) = 4
```

### Computing STS

```
Transition Accuracy = Matched Complete Transitions / max(5,4) = 4/5 = 0.800
  (all 4 observed transitions match key + old + new exactly; customer_harship has no partner to match)

Transition Order Similarity = LCS/max(5,4) = 4/5 = 0.800

STS = 0.70×0.800 + 0.30×0.800 = 0.560 + 0.240 = 0.800
```

---

## 3. TIS — Tool Invocation Similarity

> **Level: Conversation-level.** All tool calls across all 8 turns are flattened into one
> sequence before comparison.

### Formula (`METRICS.md` §4)

```
Coverage  = Matched Expected Tools / Expected Tools
Precision = Matched Observed Tools / Observed Tools
Identity  = Correct Tool Matches / Aligned Tool Pairs
Input     = Average similarity of matched tool inputs
Order     = LCS(Expected Tool Sequence, Observed Tool Sequence) / max(Expected, Observed)

TIS = 0.25×Coverage + 0.20×Precision + 0.25×Identity + 0.20×Input + 0.10×Order
```

### The two tool-call sequences

`hardship_node` (T4) has `"tool_calls": []` in golden itself — it was never supposed to call a
tool. So the missing node costs TIS nothing:

| Turn | Tool call | Same on both sides? |
|---|---|---|
| T3 | `verify_mobile({mobile:"9944994499"})` | ✅ |
| T3 | `verify_dob({dob:"2000-06-15"})` | ✅ |
| T5 | `instalment_eligibility({})` | ✅ |
| T6 | `check_eligibility({})` | ✅ |
| T7 | `check_eligibility({})` | ✅ |

Both sequences: 5 calls, same tool_ids, same arguments, same order — **fully identical**.

### Computing TIS

```
Coverage  = 5/5 = 1.000   (multiset match: every expected tool_id appears in observed)
Precision = 5/5 = 1.000   (multiset match: every observed tool_id was expected)
Identity  = 5/5 = 1.000   (positional pairing: all 5 tool_ids match at their aligned position)
Input     = 1.000         (average similarity across 5 pairs, all arguments identical)
Order     = LCS(5,5)/max(5,5) = 5/5 = 1.000   (sequences already equal, nothing to delete)

TIS = 0.25×1+0.20×1+0.25×1+0.20×1+0.10×1 = 1.000
```

---

## 4. OS — Outcome Similarity

> **Level: Conversation-level ONLY** — `METRICS.md` §6 defines OS as "Conversation-level
> only." There is no turn-level OS at all; an outcome only makes sense as a property of the
> whole call.

### Formula (`METRICS.md` §6)

```
Outcome Identity   = 1 if identity matches, else 0
Attribute Accuracy = Correct Expected Attributes / Expected Attributes
Outcome Completion = Completed Required Outcome / Required Outcome

OS = 0.50×Outcome Identity + 0.30×Attribute Accuracy + 0.20×Outcome Completion
```

### Finding the expected/observed outcome — `last_outcome()`

`last_outcome()` scans a conversation's turns **backward** and returns the first one carrying
an `outcome` field:

- **Expected**: golden attaches its outcome only to turn 8 —
  `installment_arrangement_accepted`, with 4 attributes
  (`status`, `installment_amount`, `frequency`, `duration_months`). Turn 8 *is* in scope here
  (full 8-turn fixture) → found immediately.
- **Observed**: `correct_answer_wrong_trajectory.json` never sets `"outcome"` on *any* turn —
  the scan reaches the end and returns `None`.

### Computing each component

```python
outcome_identity_accuracy(expected, observed):
    # expected exists → skip first branch
    # observed is None → return 0.0

outcome_attribute_accuracy(expected, observed):
    # expected.attributes is non-empty → skip first branch
    # observed is None → return 0.0

outcome_completion(expected, observed):
    # expected.required_conditions is [] (never populated anywhere in this dataset)
    # → returns None (N/A) immediately, before even looking at observed
```

```
Outcome Identity   = 0.0
Attribute Accuracy = 0.0
Outcome Completion = N/A
```

### Combine with N/A renormalization

```
components = {identity: 0.0, attribute: 0.0, completion: None}
weights    = {identity: 0.50, attribute: 0.30, completion: 0.20}

completion is None → dropped from numerator AND denominator
OS = (0.50×0.0 + 0.30×0.0) / (0.50 + 0.30) = 0.0 / 0.80 = 0.000
```

> **Read this as a fixture-format gap, not a real outcome miss.** The agent's actual behavior
> at turn 8 is a reasonable close to the call — the fixture simply never records an outcome to
> compare against. Contrast with the single-turn fixtures (`missing_tool_call`,
> `wrong_tool_input`), where the scored slice is turn 5 only, so turn 8 is never even reached —
> there, `expected_outcome` itself comes back `None`, and OS is genuinely **N/A**, not a
> counted 0.

---

## 5. RS — Routing Similarity

> **Level: Turn-level judgments feeding a conversation-level aggregate.** RS is the one metric
> that produces a real per-turn number (an LLM judge verdict) *and* a conversation-level
> rollup — but in this dataset both come out N/A, for two independent reasons.

### Formula (`METRICS.md` §5)

```
Semantic Routing Score = normalized LLM judge score across applicable routing turns
Routing Order Similarity = LCS(Expected Path Decisions, Observed Path Decisions) / max(Expected, Observed)

RS = 0.70×Semantic Routing Score + 0.30×Routing Order Similarity
```

### Why Semantic Routing Score is N/A

```python
def semantic_routing_score(customer_input, expected, observed, judge_client, ...):
    if judge_client is None or (expected_path is None and expected_target is None):
        return None
```

Two independent reasons, either sufficient alone:
1. The `atf-dashboard` script never passes a `judge_client` (no LLM judge is wired up).
2. No turn on either side, golden or observed, ever has a `routing` field populated — so
   `expected_path`/`expected_target` are `None` for every turn regardless.

Result: `None` for all 8 turns → the conversation-level mean of "applicable" scores has nothing
to average → `Semantic Routing Score = N/A`.

### Why Routing Order Similarity is N/A

```python
expected_seq = [t.routing.target for t in expected_turns if t.routing and t.routing.target]
observed_seq = [t.routing.target for t in observed_turns if t.routing and t.routing.target]
```
No turn has `t.routing` set → both sequences are `[]`. `lcs.order_similarity([], [])` is
defined to return `None` for the both-empty case → `Routing Order Similarity = N/A`.

### Combine

```
components = {semantic: None, order: None}
→ total_weight stays 0.0 → weighted_composite returns None

RS = N/A
```

This is identical across **every** scenario in this dataset (including the golden-vs-itself
baseline) — it's a property of the dataset's setup (no routing data, no judge client), not of
any particular deviation.

---

## 6. ATF — Agent Trajectory Fidelity (the composite)

> **Level: Conversation-level** — it combines the conversation-level group scores computed
> above. (There is no turn-level ATF; it's defined only as the top-level composite.)

### Formula (`METRICS.md` §7 / `aggregate.py`)

```python
DEFAULT_WEIGHTS = {"nts": 0.30, "sts": 0.30, "tis": 0.15, "rs": 0.10, "os": 0.15}
ATF = 0.30×NTS + 0.30×STS + 0.15×TIS + 0.10×RS + 0.15×OS
```

### Plugging in every result from this document

| Group | Value |
|---|---|
| NTS | 0.946154 |
| STS | 0.800000 |
| TIS | 1.000000 |
| RS  | N/A |
| OS  | 0.000000 |

### N/A renormalization (RS drops out)

```
total_weight = 0.30 + 0.30 + 0.15 + 0.15 = 0.90        (rs's 0.10 excluded — it's None)

total_score = 0.30×0.946154 + 0.30×0.800000 + 0.15×1.000000 + 0.15×0.000000
            = 0.283846 + 0.240000 + 0.150000 + 0.000000
            = 0.673846

ATF = 0.673846 / 0.90 = 0.748718 ≈ 0.749
```

### Metric coverage (companion transparency figure)

```
metric_coverage = (sum of applicable weights) / (sum of all weights) = 0.90 / 1.00 = 0.900
```

---

## 7. Full summary — every metric, its level, and its number

| Metric | Level | Formula pieces | **Result** |
|---|---|---|---|
| **NTS** | Conversation (concatenated 13 vs. 12 nodes) | Coverage 0.923, Precision 1.000, Order 0.923 | **0.946** |
| **STS** | Conversation (concatenated 5 vs. 4 transitions) | Transition Accuracy 0.800, Order 0.800 | **0.800** |
| **TIS** | Conversation (concatenated 5 vs. 5 tool calls) | Coverage/Precision/Identity/Input/Order all 1.000 | **1.000** |
| **OS** | Conversation-only (no turn-level version exists) | Identity 0.0, Attribute 0.0, Completion N/A | **0.000** |
| **RS** | Turn-level judgments → conversation aggregate | Semantic N/A, Order N/A (no judge, no routing data) | **N/A** |
| **ATF** | Conversation (composite of the above) | 0.30×NTS + 0.30×STS + 0.15×TIS + 0.15×OS, renormalized over 0.90 (RS excluded) | **0.749** |

Confirmed against the live `atf-dashboard` script output:
```
correct_answer_wrong_trajectory: ATF=0.749 NTS=0.946 STS=0.800 TIS=1.000 RS=N/A OS=0.000
```

---

## 8. How to reproduce

```bash
cd "/Users/janarddan/1.jana files/3.MyMacProjects/atf_eval"
source .venv/bin/activate
python .claude/skills/atf-dashboard/scripts/generate_atf_dashboard.py
```

See also `MANUAL_CALCULATION_VERIFICATION.md` for the same style of check across all four
scenarios in this dataset (`golden_baseline`, `correct_answer_wrong_trajectory`,
`missing_tool_call`, `wrong_tool_input`).
