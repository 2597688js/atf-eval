# ATF Metrics — Step-by-Step Walkthrough (Single-Turn Scenarios)

This is the companion to `ATF_STEP_BY_STEP_WALKTHROUGH.md`, same depth and style, covering the
two **single-turn** fixtures:

- **Expected (golden), sliced to turn 5 only:** `agent-eval-main/golden/motor_insurance_hardship_installment.json`
- **Observed A:** `agent-eval-main/tests/fixtures/scenarios/missing_tool_call.json`
- **Observed B:** `agent-eval-main/tests/fixtures/scenarios/wrong_tool_input.json`

Both fixtures cover **only turn 5** — unlike the full 8-turn `correct_answer_wrong_trajectory`
example in the companion document. That single fact changes how several metrics behave, most
notably OS, which is why it's worth its own walkthrough rather than folding into the other one.

---

## 0. Turn-level vs. Conversation-level — what's different here

As before, every metric conceptually has a turn-level and/or conversation-level form (see
`ATF_STEP_BY_STEP_WALKTHROUGH.md` §0 for the full breakdown of which metric supports which
level). **Every number below is still the conversation-level computation** — nothing here
switches to turn-level scoring. But because these fixtures only contain turn 5, something
notable happens:

> **For NTS, STS, and TIS: conversation-level and turn-level numerically coincide.**
> Concatenating "all turns" produces the exact same sequence as scoring turn 5 alone, simply
> because there's only one turn in the fixture to concatenate. This is a coincidence of these
> particular fixtures, not a rule — in the other example (`correct_answer_wrong_trajectory`,
> 8 turns), conversation-level and turn-level gave very different numbers.

> **For OS, the single-turn scope changes the *outcome*, not just the arithmetic.** OS is
> conversation-level only (§0 of the companion doc), and it looks for the outcome on
> **turn 8** specifically (`last_outcome()` scans backward through the trajectory). Since these
> fixtures only cover turn 5, turn 8 is never even reached on the *expected* side either — so
> `expected_outcome` itself comes back `None`. That's a **genuine N/A** (nothing to compare
> against), which is a different situation from the full-conversation example, where the
> expected outcome *was* found (turn 8 was in scope) but the observed side just never recorded
> one, producing a real, counted `0.000` instead. Same metric, same "N/A-ish" surface
> appearance, structurally different reason.

---

## 1. The shared starting point: golden turn 5

Both fixtures are scored against this same slice of golden — turn 5 only:

```json
{
  "turn_id": 5,
  "nodes": [
    {"node_id": "classify_intent", "state_changes": [], "tool_calls": []},
    {"node_id": "hardship_node", "state_changes": [
        {"key": "installment_eligible", "old": false, "new": true}
      ],
      "tool_calls": [
        {"tool_id": "instalment_eligibility", "input": {}, "status": "success"}
      ]
    }
  ]
}
```

So: **2 expected nodes**, **1 expected state transition**, **1 expected tool call** (with
empty expected arguments `{}`) — that's the entire "E" side for both scenarios below.

---

## 2. Scenario A — `missing_tool_call`

**Deviation** (from the fixture's own `deviation` block): *"Expected instalment eligibility
tool is not invoked."* The `instalment_eligibility` tool call simply never happens — but the
state change it was supposed to cause (`installment_eligible: false→true`) is still recorded,
as if it happened anyway.

```json
"nodes": [
  {"node_id": "classify_intent", "state_changes": []},
  {"node_id": "hardship_node", "state_changes": [
      {"key": "installment_eligible", "old": false, "new": true}
    ],
    "tool_calls": []
  }
]
```

### 2a. NTS — Conversation-level (= turn-level here)

```
E nodes: [classify_intent, hardship_node]   (2)
O nodes: [classify_intent, hardship_node]   (2)   — identical
```
Both sequences are identical, so LCS = 2 trivially (no deletion needed at all).
```
Coverage  = 2/2 = 1.000
Precision = 2/2 = 1.000
Order     = 2/max(2,2) = 1.000

NTS = 0.40×1.0 + 0.30×1.0 + 0.30×1.0 = 1.000
```

### 2b. STS — Conversation-level (= turn-level here)

```
E transitions: [installment_eligible: false→true]   (1)
O transitions: [installment_eligible: false→true]   (1)   — identical, and present
```
This is the subtle part of this fixture: **state changes live on the node, independent of
whether the node's tool call fired.** The fixture records the state transition even though the
tool that (in golden) causes it was skipped — so STS sees nothing wrong.
```
Transition Accuracy = 1/max(1,1) = 1.000
Transition Order Similarity = LCS(1,1)/max(1,1) = 1.000

STS = 0.70×1.0 + 0.30×1.0 = 1.000
```

### 2c. TIS — Conversation-level (= turn-level here) — this is where the deviation shows up

```
E tool calls: [instalment_eligibility({})]   (1)
O tool calls: []                              (0)
```

| Component | Computation | Result |
|---|---|---|
| Coverage | Matched Expected Tools / Expected Tools = 0/1 | **0.000** |
| Precision | Matched Observed Tools / Observed Tools — but Observed Tools = 0 → nothing to divide by | **N/A** |
| Identity | positional pairing `zip([1 call], [])` produces 0 aligned pairs — nothing to score | **N/A** |
| Input | same empty pairing — no matched pair to average | **N/A** |
| Order | LCS(1,0)/max(1,0) = 0/1 | **0.000** |

Only Coverage (weight 0.25) and Order (weight 0.10) are applicable — everything else drops out
of both numerator and denominator:
```
applicable weight = 0.25 + 0.10 = 0.35
TIS = (0.25×0.000 + 0.10×0.000) / 0.35 = 0.000 / 0.35 = 0.000
```

### 2d. OS — Conversation-level only

`last_outcome(expected_turns)`: the expected slice for this fixture is turn 5 only — turn 8
(where golden's outcome lives) is never part of it. Scanning turn 5 backward finds no outcome
→ **`expected_outcome = None`**.

```python
outcome_identity_accuracy(expected=None, observed=...):
    if expected is None or expected.id is None:
        return None   # <- hits here immediately
```
All three OS sub-functions hit this same first branch (`expected is None`) → all return `None`
→ `weighted_composite` gets `{identity: None, attribute: None, completion: None}` → total
weight stays 0.0 → **OS = N/A**.

This is a genuinely different code path than the full-conversation example, where
`expected_outcome` *was* found and `observed=None` was what forced the zero — here, `expected`
itself is `None`, so the comparison never even starts.

### 2e. RS — N/A (same reasons as always: no judge client, no routing data)

### 2f. ATF

```
components = {nts: 1.000, sts: 1.000, tis: 0.000, rs: None, os: None}
weights    = {nts: 0.30,  sts: 0.30,  tis: 0.15,  rs: 0.10, os: 0.15}

applicable weight = 0.30 + 0.30 + 0.15 = 0.75      (rs and os both excluded, N/A)

ATF = (0.30×1.000 + 0.30×1.000 + 0.15×0.000) / 0.75
    = (0.300 + 0.300 + 0.000) / 0.75
    = 0.600 / 0.75
    = 0.800

metric_coverage = 0.75 / 1.00 = 0.750
```

---

## 3. Scenario B — `wrong_tool_input`

**Deviation:** *"Correct tool is invoked but with incorrect arguments."* Same tool,
`instalment_eligibility`, is called — but with `{policy_id: "POL_001", requested_amount: 5000}`
instead of golden's expected `{}`.

```json
"nodes": [
  {"node_id": "classify_intent", "state_changes": []},
  {"node_id": "hardship_node", "state_changes": [
      {"key": "installment_eligible", "old": false, "new": true}
    ],
    "tool_calls": [
      {"tool_name": "instalment_eligibility", "input": {"policy_id": "POL_001", "requested_amount": 5000}}
    ]
  }
]
```

### 3a. NTS — identical derivation to Scenario A

Same node list, same result:
```
NTS = 1.000
```

### 3b. STS — identical derivation to Scenario A

Same single transition, present and correct on both sides:
```
STS = 1.000
```

### 3c. TIS — this is where the two scenarios diverge

```
E tool calls: [instalment_eligibility({})]                                        (1)
O tool calls: [instalment_eligibility({policy_id:"POL_001", requested_amount:5000})]  (1)
```
Same tool_id, same position — 1 aligned pair this time (unlike Scenario A's empty pairing):

| Component | Computation | Result |
|---|---|---|
| Coverage | 1 matched / 1 expected | **1.000** |
| Precision | 1 matched / 1 observed | **1.000** |
| Identity | tool_id `instalment_eligibility` == `instalment_eligibility` | **1.000** |
| Input | `argument_match(expected_args={}, observed_args={policy_id:..., requested_amount:...})` | **1.000** — see below |
| Order | LCS(1,1)/max(1,1) | **1.000** |

**Why Input scores a perfect 1.000 despite the arguments being clearly different:**
```python
def argument_match(expected_args, observed_args, tolerance=0.0):
    if not expected_args:
        return 1.0   # nothing was required, so nothing to get wrong
    ...
```
Golden's own expected arguments for this call are `{}` — empty. The function's very first check
short-circuits to `1.0` whenever nothing was required, on the reasoning that there's nothing in
the expected side for the wrong arguments to disagree *with*. The comparison against the
observed `{policy_id:..., requested_amount:...}` dict never actually runs.

```
TIS = 0.25×1.000 + 0.20×1.000 + 0.25×1.000 + 0.20×1.000 + 0.10×1.000 = 1.000
```

> **This is a fixture-authoring gap, not a scoring bug.** If you want this specific deviation
> (`wrong_tool_input`) to actually move TIS, golden's `expected_input` for
> `instalment_eligibility` needs to be non-empty — e.g. if golden expected
> `{policy_id: "POL_001"}` and the observed call sent something different, `argument_match`
> would then have something concrete to compare and could genuinely fail.

### 3d. OS — identical derivation to Scenario A

Same single-turn slice, same reasoning: `expected_outcome = None` (turn 8 out of scope) →
**OS = N/A**.

### 3e. RS — N/A (same reasons as always)

### 3f. ATF

```
components = {nts: 1.000, sts: 1.000, tis: 1.000, rs: None, os: None}
applicable weight = 0.30 + 0.30 + 0.15 = 0.75

ATF = (0.30×1.000 + 0.30×1.000 + 0.15×1.000) / 0.75
    = 0.750 / 0.75
    = 1.000

metric_coverage = 0.75 / 1.00 = 0.750
```

---

## 4. Summary — both scenarios, side by side, with level annotations

| Metric | Level | `missing_tool_call` | `wrong_tool_input` |
|---|---|---|---|
| **NTS** | Conversation (= turn-level here, single-turn fixture) | **1.000** | **1.000** |
| **STS** | Conversation (= turn-level here) | **1.000** | **1.000** |
| **TIS** | Conversation (= turn-level here) | **0.000** (tool never called → coverage & order both 0; precision/identity/input all N/A from empty pairing) | **1.000** (tool called, wrong args invisible because expected args are `{}`) |
| **OS** | Conversation-only, and genuinely N/A here | **N/A** (turn 8 never in scope → `expected_outcome=None`) | **N/A** (same reason) |
| **RS** | Turn-level judgments → conversation aggregate | **N/A** (no judge, no routing data) | **N/A** (same) |
| **ATF** | Conversation (composite) | **0.800** (renormalized over NTS+STS+TIS = 0.75 weight) | **1.000** (same renormalization, but TIS is perfect) |

Confirmed against the live `atf-dashboard` script output:
```
missing_tool_call: ATF=0.800 NTS=1.000 STS=1.000 TIS=0.000 RS=N/A OS=N/A
wrong_tool_input:  ATF=1.000 NTS=1.000 STS=1.000 TIS=1.000 RS=N/A OS=N/A
```

**The one-sentence takeaway for each:**
- `missing_tool_call` — the *only* metric that reacts is TIS, because a tool call is the only
  thing actually missing; the state change survives independently of the tool call that would
  normally cause it.
- `wrong_tool_input` — **nothing** reacts, not even TIS, because golden's expected arguments for
  this call happen to be empty, so `argument_match` has nothing to compare the wrong arguments
  against and defaults to a perfect score.

---

## 5. How to reproduce

```bash
cd "/Users/janarddan/1.jana files/3.MyMacProjects/atf_eval"
source .venv/bin/activate
python .claude/skills/atf-dashboard/scripts/generate_atf_dashboard.py
```

See also:
- `ATF_STEP_BY_STEP_WALKTHROUGH.md` — same depth, for the full 8-turn `correct_answer_wrong_trajectory` example.
- `MANUAL_CALCULATION_VERIFICATION.md` — wider roll-up across all four scenarios (including the golden baseline) at less depth.
