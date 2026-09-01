# Manual ATF Calculation — `agent-eval-main` golden vs. `tests/fixtures/scenarios`

This document works every metric out by hand, turn by turn, for all fixtures under
`agent-eval-main/tests/` scored against `agent-eval-main/golden/motor_insurance_hardship_installment.json`,
then checks the result against the `atf-dashboard` skill's actual output. **Every number below
was independently reproduced by re-running the real script** (§6) — the two match exactly,
down to the floating-point tail, so this doubles as a correctness proof for the tooling, not
just an explanation of it.

Inputs confirmed present under `agent-eval-main/tests/` at the time of this calculation:

```
agent-eval-main/tests/fixtures/scenarios/correct_answer_wrong_trajectory.json
agent-eval-main/tests/fixtures/scenarios/missing_tool_call.json
agent-eval-main/tests/fixtures/scenarios/wrong_tool_input.json
```

Four rows are scored: those three fixtures, plus a `golden_baseline` sanity row (golden scored
against itself) that the dashboard also generates.

> **Looking for more depth on any one scenario?** This document covers all four scenarios at
> roll-up depth. Two companion documents go much deeper on individual scenarios — full LCS
> dynamic-programming tables, cell-by-cell derivations, and explicit turn-level vs.
> conversation-level annotations for every metric:
> - [`ATF_STEP_BY_STEP_WALKTHROUGH.md`](ATF_STEP_BY_STEP_WALKTHROUGH.md) — `correct_answer_wrong_trajectory` (full 8-turn conversation)
> - [`ATF_STEP_BY_STEP_WALKTHROUGH_SINGLE_TURN.md`](ATF_STEP_BY_STEP_WALKTHROUGH_SINGLE_TURN.md) — `missing_tool_call` and `wrong_tool_input` (single-turn fixtures)

---

## 1. Formulas (verbatim from `METRICS.md` / `src/atf_eval`)

| Group | Formula | Weights |
|---|---|---|
| **NTS** | `0.40×Coverage + 0.30×Precision + 0.30×Order` | node-level |
| **STS** | `0.70×TransitionAccuracy + 0.30×Order` | node-level |
| **TIS** | `0.25×Coverage + 0.20×Precision + 0.25×Identity + 0.20×Input + 0.10×Order` | node-level |
| **RS**  | `0.70×Semantic + 0.30×Order` | conversation-level |
| **OS**  | `0.50×Identity + 0.30×Attribute + 0.20×Completion` | conversation-level, last turn with an outcome |
| **ATF** | `0.30×NTS + 0.30×STS + 0.15×TIS + 0.10×RS + 0.15×OS` | composite |

**N/A rule (Frozen Rule #11, `aggregate.weighted_composite`):** a component that is `None`
(not computable — e.g. no tool calls on either side, or no outcome recorded) is dropped from
*both* the numerator and denominator, so the remaining weights renormalize. N/A is never
scored as 0. `metric_coverage = (sum of weights of applicable groups) / (sum of all weights)`.

**Node/state alignment (`lcs.align`):** expected and observed ID sequences are aligned with a
position-aware LCS (longest common subsequence) — not a bag-of-words count and not a naive
zip. This is what lets a single missing/extra/reordered node get flagged without cascading
every later node into a false mismatch. `order_similarity = lcs_length / max(len(expected), len(observed))`,
and `coverage`'s numerator (`matched_count`) is the *same* LCS length — the two components only
differ when `len(expected) ≠ len(observed)`, since they divide by different denominators.

**Tool/state pairing:** state changes are paired *within each aligned node*, by key, in
occurrence order (`_pair_by_key`) — not across the whole conversation. Tool calls are paired by
raw position (`zip`), since "invocation" implies order, distinct from the multiset-based
coverage/precision.

---

## 2. The golden trajectory (expected side)

`MOTOR_INSURANCE_HARDSHIP_001`, 8 turns. Concatenated node sequence, state changes, and flat
tool-call sequence (the shape every metric actually operates on):

| Turn | Nodes (in order) | State changes | Tool calls |
|---|---|---|---|
| 1 | `initialize_call`, `greet_customer` | — | — |
| 2 | `verify_customer` | — | — |
| 3 | `verify_customer` | `customer_verified: false→true` | `verify_mobile({mobile:"9944994499"})`, `verify_dob({dob:"2000-06-15"})` |
| 4 | `classify_intent`, `hardship_node` | `customer_harship: false→true` | — |
| 5 | `classify_intent`, `hardship_node` | `installment_eligible: false→true` | `instalment_eligibility({})` |
| 6 | `classify_intent`, `hardship_node` | `customer_unable_to_pay: false→true` | `check_eligibility({})` |
| 7 | `classify_intent`, `hardship_node` | `customer_accept_installment: false→true` | `check_eligibility({})` |
| 8 | `classify_intent` | — | — |

- Concatenated node count: **13**. Total state changes: **5**. Total tool calls: **5**.
- Final outcome (attached to turn 8 only): `installment_arrangement_accepted`, attributes
  `{status: accepted, installment_amount: 3000, frequency: monthly, duration_months: 3}`.
  `required_conditions` is never populated in this dataset → `Completion` is **always N/A**,
  for every scenario, including the baseline.
- No turn on either side ever carries a `routing` field in this dataset → `RS` is **always N/A**
  for every scenario (both the semantic and order components have nothing to compute from).

---

## 3. Scenario walkthroughs

### 3.0 `golden_baseline` — golden vs. itself

Expected = observed = the full 8-turn trajectory above. Every node, state change, and tool call
lines up 1:1, so:

- **NTS** = 0.40·1 + 0.30·1 + 0.30·1 = **1.000**
- **STS** = 0.70·1 + 0.30·1 = **1.000**
- **TIS** = 0.25·1 + 0.20·1 + 0.25·1 + 0.20·1 + 0.10·1 = **1.000**
- **RS** = N/A (no routing data anywhere)
- **OS**: identity = 1.0 (same outcome id), attribute = 4/4 = 1.0 (all 4 attributes match),
  completion = N/A → `weighted_composite({0.50:1.0, 0.30:1.0, completion:None})` renormalizes
  over 0.50+0.30=0.80 → **OS = 1.000**
- **ATF**: applicable weights = 0.30+0.30+0.15+0.15 = 0.90 (RS's 0.10 excluded) →
  `(0.30·1+0.30·1+0.15·1+0.15·1)/0.90` = **1.000**, `metric_coverage = 0.90/1.00 = 0.900`

### 3.1 `correct_answer_wrong_trajectory` — full 8-turn conversation

*(Full DP-table-level derivation of this scenario: [`ATF_STEP_BY_STEP_WALKTHROUGH.md`](ATF_STEP_BY_STEP_WALKTHROUGH.md).)*

**Deviation:** turn 4 skips `hardship_node`; the agent's reply is still an appropriate hardship
response (`classify_intent` only, per the fixture's own `deviation` block).

**Node sequences** (13 expected vs. 12 observed):

```
Expected (E, 13): initialize_call, greet_customer, verify_customer, verify_customer,
                   classify_intent, hardship_node, classify_intent, hardship_node,
                   classify_intent, hardship_node, classify_intent, hardship_node, classify_intent
Observed (O, 12): initialize_call, greet_customer, verify_customer, verify_customer,
                   classify_intent,               classify_intent, hardship_node,
                   classify_intent, hardship_node, classify_intent, hardship_node, classify_intent
```

**LCS alignment** (computed via the DP recurrence in `lcs.align`; full table available on
request — worked by hand and cross-checked against the script): the first 4 nodes align
trivially (identical prefix). From index 4 on, the alignment is:

| E idx | Node | Aligned O idx | Status |
|---|---|---|---|
| 4 | `classify_intent` (T4) | 4 | matched |
| 5 | `hardship_node` (T4) | — | **missing** |
| 6 | `classify_intent` (T5) | 5 | matched |
| 7 | `hardship_node` (T5) | 6 | matched |
| 8 | `classify_intent` (T6) | 7 | matched |
| 9 | `hardship_node` (T6) | 8 | matched |
| 10 | `classify_intent` (T7) | 9 | matched |
| 11 | `hardship_node` (T7) | 10 | matched |
| 12 | `classify_intent` (T8) | 11 | matched |

Only `hardship_node` (T4) is unmatched — exactly the deviation the fixture describes. LCS
length = 4 (prefix) + 8 (post-prefix) = **12**. No observed nodes are unmatched extras.

- **NTS**: coverage = 12/13 = 0.923077, precision = 12/12 = 1.000000, order = 12/13 = 0.923077
  → `0.40·0.923077 + 0.30·1.0 + 0.30·0.923077` = **0.946154**
- **STS**: state changes are paired *inside* each aligned node pair. All 5 expected transitions
  are found and correctly-valued **except** `customer_harship` (its node, `hardship_node` T4,
  has no observed counterpart, so its pair is `(change, None)` — unmatched).

  | Key | Expected | Observed | Matched? |
  |---|---|---|---|
  | `customer_verified` | false→true | false→true | ✅ |
  | `customer_harship` | false→true | — (node missing) | ❌ |
  | `installment_eligible` | false→true | false→true | ✅ |
  | `customer_unable_to_pay` | false→true | false→true | ✅ |
  | `customer_accept_installment` | false→true | false→true | ✅ |

  `transition_accuracy` denom = max(5 expected, 4 observed) = 5; matched = 4 → 4/5 = 0.800.
  `order` = LCS of key sequences `[cv, ch, ie, cup, cai]` vs `[cv, ie, cup, cai]` = 4/5 = 0.800.
  → **STS** = 0.70·0.8 + 0.30·0.8 = **0.800**
- **TIS**: `hardship_node` (T4) carries no tool calls in golden either, so the deviation costs
  nothing here — the flattened tool-call sequence is **identical** on both sides
  (`verify_mobile`, `verify_dob`, `instalment_eligibility`, `check_eligibility`×2, same args,
  same order) → every component = 1.0 → **TIS = 1.000**
- **RS** = N/A
- **OS**: expected outcome comes from turn 8 (included, since this is the full conversation) =
  `installment_arrangement_accepted`. The *observed* fixture never populates an `outcome` field
  on any turn (this is a property of every scenario fixture in this repo, not specific to this
  one) → `last_outcome(observed) = None` → identity = 0.0, attribute = 0.0, completion = N/A
  (renormalized over identity 0.50 + attribute 0.30 = 0.80) → **OS = 0.000**

  > ⚠️ **Read this as a fixture-format gap, not a real outcome miss.** The agent's trajectory
  > never diverges from reaching the correct outcome — the fixture simply never records one to
  > compare against. See §5's note on this.
- **ATF**: applicable weights = 0.30(NTS)+0.30(STS)+0.15(TIS)+0.15(OS) = 0.90 (RS excluded)

  ```
  0.30×0.946154 + 0.30×0.800000 + 0.15×1.000000 + 0.15×0.000000
    = 0.283846 + 0.240000 + 0.150000 + 0
    = 0.673846
  ATF = 0.673846 / 0.90 = 0.748718
  ```
  **ATF = 0.749**, `metric_coverage = 0.900`

### 3.2 `missing_tool_call` — single turn (turn 5 only)

*(Full derivation of this scenario: [`ATF_STEP_BY_STEP_WALKTHROUGH_SINGLE_TURN.md`](ATF_STEP_BY_STEP_WALKTHROUGH_SINGLE_TURN.md).)*

**Deviation:** the fixture covers only turn 5; `instalment_eligibility` is never invoked, but
the `installment_eligible` state change is still recorded.

Expected slice = golden's turn 5 only (the dashboard/test harness matches the golden slice to
whichever turn IDs the observed fixture actually covers — here just `{5}`).

- **Nodes**: expected `[classify_intent, hardship_node]`, observed — identical. → coverage =
  precision = order = 1.0 → **NTS = 1.000**
- **State changes**: `installment_eligible: false→true` present and correct on both sides
  (state changes live on the node, independent of whether its tool call fired) →
  transition_accuracy = 1/1 = 1.0, order = 1/1 = 1.0 → **STS = 1.000**
- **Tool calls**: expected `[instalment_eligibility({})]` (1 call), observed `[]` (0 calls).

  | Component | Calc | Result |
  |---|---|---|
  | coverage | overlap(1,0)/1 | 0.000 |
  | precision | observed empty → | **N/A** |
  | identity | `zip(1,0)` empty → | **N/A** |
  | input | `zip(1,0)` empty → | **N/A** |
  | order | LCS(1,0)/max(1,0) | 0.000 |

  Only coverage (0.25) and order (0.10) are applicable → renormalized weight = 0.35 →
  `(0.25·0 + 0.10·0)/0.35` = **TIS = 0.000**
- **RS** = N/A
- **OS**: expected slice is turn 5 *only* — and the golden outcome lives on turn 8, which isn't
  in this slice at all → `last_outcome(expected) = None` → all three OS components are N/A →
  **OS = N/A** (genuinely inapplicable here, unlike §3.1's full-conversation case)
- **ATF**: applicable weights = 0.30(NTS)+0.30(STS)+0.15(TIS) = 0.75 (RS and OS both excluded)

  ```
  ATF = (0.30×1.000 + 0.30×1.000 + 0.15×0.000) / 0.75 = 0.600 / 0.75 = 0.800
  ```
  **ATF = 0.800**, `metric_coverage = 0.750`

### 3.3 `wrong_tool_input` — single turn (turn 5 only)

*(Full derivation of this scenario: [`ATF_STEP_BY_STEP_WALKTHROUGH_SINGLE_TURN.md`](ATF_STEP_BY_STEP_WALKTHROUGH_SINGLE_TURN.md).)*

**Deviation:** `instalment_eligibility` *is* called, but with `{policy_id: "POL_001",
requested_amount: 5000}` instead of golden's expected `{}`.

- **Nodes / state changes**: identical to golden (`classify_intent`, `hardship_node`,
  `installment_eligible: false→true`) → **NTS = 1.000**, **STS = 1.000** (same derivation as
  §3.2)
- **Tool calls**: expected `[instalment_eligibility({})]`, observed
  `[instalment_eligibility({policy_id:"POL_001", requested_amount:5000})]` — same tool, same
  position, 1 pair.

  | Component | Calc | Result |
  |---|---|---|
  | coverage | overlap(1,1)/1 | 1.000 |
  | precision | overlap(1,1)/1 | 1.000 |
  | identity | tool_id matches | 1.000 |
  | input | `argument_match({}, {...})`: expected_args is `{}` → *"nothing was required, so nothing to get wrong"* → | **1.000** |
  | order | LCS(1,1)/1 | 1.000 |

  → **TIS = 1.000**. The wrong arguments are invisible to `Input` because golden's own expected
  arguments for this call are empty — there was nothing to compare against.
- **RS** = N/A
- **OS** = N/A (same single-turn-slice reasoning as §3.2)
- **ATF**: `(0.30×1.000 + 0.30×1.000 + 0.15×1.000) / 0.75 = 0.75/0.75` = **1.000**,
  `metric_coverage = 0.750`

---

## 4. Roll-up: manual vs. script

| Scenario | | NTS | STS | TIS | RS | OS | **ATF** | Coverage |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `golden_baseline` | manual | 1.000 | 1.000 | 1.000 | N/A | 1.000 | **1.000** | 0.900 |
| | script | 1.000 | 1.000 | 1.000 | N/A | 1.000 | **1.000** | 0.900 |
| `correct_answer_wrong_trajectory` | manual | 0.946 | 0.800 | 1.000 | N/A | 0.000 | **0.749** | 0.900 |
| | script | 0.946 | 0.800 | 1.000 | N/A | 0.000 | **0.749** | 0.900 |
| `missing_tool_call` | manual | 1.000 | 1.000 | 0.000 | N/A | N/A | **0.800** | 0.750 |
| | script | 1.000 | 1.000 | 0.000 | N/A | N/A | **0.800** | 0.750 |
| `wrong_tool_input` | manual | 1.000 | 1.000 | 1.000 | N/A | N/A | **1.000** | 0.750 |
| | script | 1.000 | 1.000 | 1.000 | N/A | N/A | **1.000** | 0.750 |

**Every row matches exactly.** The script's console output, reproduced verbatim:

```
golden_baseline: ATF=1.000 NTS=1.000 STS=1.000 TIS=1.000 RS=N/A OS=1.000
correct_answer_wrong_trajectory: ATF=0.749 NTS=0.946 STS=0.800 TIS=1.000 RS=N/A OS=0.000
missing_tool_call: ATF=0.800 NTS=1.000 STS=1.000 TIS=0.000 RS=N/A OS=N/A
wrong_tool_input: ATF=1.000 NTS=1.000 STS=1.000 TIS=1.000 RS=N/A OS=N/A
```

### Component-level cross-check

Every sub-component from the generated `agent_eval_main_metrics_components_*.csv` was diffed
against the hand-derived value above (raw values, unrounded):

| Scenario | nts_coverage | nts_precision | nts_order | sts_transition_accuracy | sts_order | tis_coverage | tis_input_similarity | os_identity | os_attribute |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `golden_baseline` | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| `correct_answer_wrong_trajectory` | 0.9230769230769231 | 1.0 | 0.9230769230769231 | 0.8 | 0.8 | 1.0 | 1.0 | 0.0 | 0.0 |
| `missing_tool_call` | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 | *(N/A)* | *(N/A)* | *(N/A)* |
| `wrong_tool_input` | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | *(N/A)* | *(N/A)* |

`0.9230769230769231` is `12/13` exactly, as derived in §3.1 — floating point, not rounding
error. No discrepancy anywhere.

---

## 5. Notes for the reader

- **OS behaves differently for full-conversation vs. single-turn fixtures**, and this is a
  fixture-format property, not a scoring inconsistency: `correct_answer_wrong_trajectory`
  covers all 8 turns (including turn 8, where golden's outcome lives) so OS resolves to a real
  — if fixture-degraded — **0.000** (the observed side never records *any* outcome field).
  `missing_tool_call` and `wrong_tool_input` cover only turn 5, so the outcome-bearing turn
  isn't even in scope → OS is genuinely **N/A** there, correctly excluded from the ATF
  denominator instead of silently dragging the score down.
- **RS is N/A everywhere** because no fixture in this dataset — golden or observed — ever
  populates a `routing` field. This is expected, not a defect: RS needs an LLM judge and
  `judge_client` is never passed (no API key is used by this workflow).
- **`wrong_tool_input`'s TIS still hits 1.000`** because golden's own expected arguments for
  `instalment_eligibility` are `{}` — there is nothing in the expected side for the wrong
  arguments to disagree with. `argument_match` explicitly returns `1.0` when
  `expected_args` is empty ("nothing was required, so nothing to get wrong" —
  `src/atf_eval/metrics/tools.py`). If you want this deviation to actually move TIS, the
  golden fixture's expected input needs to be non-empty.

---

## 6. How to reproduce this yourself

```bash
cd "/Users/janarddan/1.jana files/3.MyMacProjects/atf_eval"
source .venv/bin/activate
python .claude/skills/atf-dashboard/scripts/generate_atf_dashboard.py
```

This prints the same 4 summary lines shown in §4 to stdout, and writes:
- `results/agent_eval_main_metrics_<timestamp>.csv` — group-level (compare against §4's roll-up table)
- `results/agent_eval_main_metrics_components_<timestamp>.csv` — every sub-component (compare against §4's cross-check table)
- `results/atf_dashboard_<timestamp>.html` — interactive dashboard with the same numbers

Optionally, `python -m pytest tests/fixtures/test_deviation_scenarios.py -v` runs this
project's own conformance suite against the same three fixtures (4 tests, independent of this
document, all passing) as a second line of evidence.
