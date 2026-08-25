# ATF Framework — Getting Started From Zero

Single source of truth for setting up and running the ATF (Agent Trajectory Fidelity)
evaluation framework from a completely fresh machine, including the real live-agent
integration (`collection_agent`). For metric *definitions* see `METRICS.md` (the frozen
spec, same folder as this file). For the Python API reference see `README.md`.

---

## 0. Orientation — what lives where

`atf_eval/` is now a fully standalone project (its own top-level folder, its own venv, no
longer nested inside anything else). It sits alongside `easy_agents/` (the real agents it
evaluates) and `8.eval_fw/` (a separate, unrelated framework -- `rag_eval` -- that used to
share a repo with this before the split):

```
/Users/janarddan/1.jana files/3.MyMacProjects/
  atf_eval/                    the ATF framework itself (installable Python package, own venv) -- you are here
    GETTING_STARTED.md           this file
    RUN_COLLECTION_AGENT.md      ready-to-run 3-script collection_agent example, with real reference numbers
    METRICS.md                   frozen scoring specification (read this for formulas)
    ATF_Metric_Definition_Evaluation_Specification.md   original draft spec, superseded by METRICS.md
    ATF_SESSION_NOTES.md         working history: what was built, real run results, bugs found+fixed
    README.md                    Python API reference, adapter contract, metric groups
    src/atf_eval/                 the package
    tests/                        81+ tests, no network calls
    examples/                     bundled fake agent + tiny golden dataset (no live agent, no API keys)
    integrations/
      collection_agent/            real live-agent example (talks to a real LLM via Ollama), own venv
      discount_planning_agent/     real deterministic (no-LLM) agent example, own venv

  easy_agents/                 sibling project -- the real agents ATF evaluates
    agents/collection_agent/      the rich, LLM-backed agent
    EVALUATION_PLAN.md            the original design doc this ATF work implements

  8.eval_fw/                   sibling project -- a DIFFERENT, unrelated framework (rag_eval)
                                  -- ignore for ATF work; atf_eval used to live inside this
                                  repo and was split out into its own standalone project
```

Three things you can run, in increasing order of setup required:
1. **The bundled mock example** — pure Python, zero external dependencies, sanity-checks the framework itself.
2. **`discount_planning_agent`** — a real but deterministic (no-LLM) agent. Still no API keys needed.
3. **`collection_agent`** — a real LLM-backed agent. Needs Ollama running, and optionally an Anthropic API key for one specific metric (RS).

This guide covers all three, in that order.

---

## 1. Prerequisites

- Python 3.10+
- For `collection_agent` only: [Ollama](https://ollama.com) installed, with network access to its cloud model proxy (the agent's `config.yml` targets `gemma4:31b-cloud`).
- For RS's semantic routing judge (optional, applies to any agent): an `ANTHROPIC_API_KEY`.

---

## 2. Install the core framework

```bash
cd "/Users/janarddan/1.jana files/3.MyMacProjects/atf_eval"
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Verify:
```bash
pytest tests/ -v
```
Should show `95 passed`. No network calls, no API keys — this is pure Python.

---

## 3. Run the bundled example (sanity check)

Still in the same venv:

```bash
python -m atf_eval run \
  --dataset examples/golden_dataset.jsonl \
  --adapter examples.mock_adapter:MockTrajectoryAgent \
  --output-dir results/ \
  --no-routing-judge
```

`--no-routing-judge` skips RS's LLM call so this runs with **zero API keys, zero network
calls**. You should see an ATF summary print with 2 conversations, 4 turns. If you want to
see the real RS judge work (needs `ANTHROPIC_API_KEY`), drop `--no-routing-judge`:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
python -m atf_eval run \
  --dataset examples/golden_dataset.jsonl \
  --adapter examples.mock_adapter:MockTrajectoryAgent \
  --output-dir results/
```

If this works, the framework itself is confirmed working. Everything past this point is
about evaluating a *real* agent.

---

## 4. Real example #1: `discount_planning_agent` (no LLM, no Ollama needed)

A tiny deterministic function-based agent — good next step since it needs no external
services at all.

```bash
cd "/Users/janarddan/1.jana files/3.MyMacProjects/atf_eval/integrations/discount_planning_agent"
python3 -m venv .venv && source .venv/bin/activate
pip install -e "/Users/janarddan/1.jana files/3.MyMacProjects/atf_eval"

export PYTHONPATH="/Users/janarddan/1.jana files/3.MyMacProjects/easy_agents:/Users/janarddan/1.jana files/3.MyMacProjects/easy_agents/src"
python -m atf_eval run \
  --dataset golden_dataset.jsonl \
  --adapter discount_planning_adapter:DiscountPlanningAgentAdapter \
  --output-dir results/ \
  --no-routing-judge
```

Expect `ATF score: 1.000`, `coverage: 15.0%` — this agent is stateless (no nodes, no
tools, no routing), so only Outcome Similarity applies; everything else is correctly `N/A`,
not a bug.

---

## 5. Real example #2: `collection_agent` (real LLM, the full pipeline)

This is the one that exercises every part of the framework, including live agent
invocation through a real model. For a ready-to-run 3-script example with real reference
numbers (once you've done the setup below), see `RUN_COLLECTION_AGENT.md` in this folder.

### 5.1 Set up the integration environment

```bash
cd "/Users/janarddan/1.jana files/3.MyMacProjects/atf_eval/integrations/collection_agent"
python3 -m venv .venv
source .venv/bin/activate
pip install -r "/Users/janarddan/1.jana files/3.MyMacProjects/easy_agents/requirements.txt"
pip install -e "/Users/janarddan/1.jana files/3.MyMacProjects/atf_eval"
```

### 5.2 Start Ollama and confirm it's reachable

```bash
# if not already running:
open -a Ollama            # macOS; otherwise run `ollama serve` directly

# confirm the server is up:
curl -s http://localhost:11434/api/tags

# confirm the specific cloud model the agent uses actually responds:
curl -s http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gemma4:31b-cloud","messages":[{"role":"user","content":"Say OK"}],"max_tokens":5}'
```
Both must return valid JSON before continuing. If Ollama was just started, give it a few
seconds and retry — it can be unreachable for a moment right after launch.

### 5.3 (Optional) Enable the real RS judge

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```
Without this, RS still runs but only its deterministic order-similarity component
contributes — the semantic half reports N/A. Nothing else in the framework needs this key.

### 5.4 See what test scenarios exist

The raw dataset has 1000 scripts across 22 categories:
```bash
python3 convert_golden_dataset.py --list-categories
```

### 5.5 Build a golden dataset from the categories you want

```bash
# specific categories:
python3 convert_golden_dataset.py --categories "Wrong Contact,Suspicious Customer,Debt Dispute"

# or 1 script from every category (22 total):
python3 convert_golden_dataset.py --per-category 1

# or N scripts from a specific set:
python3 convert_golden_dataset.py --categories "Pay Now,Bad Actor" --per-category 2
```
This writes/overwrites `golden_subset.jsonl` and prints exactly which `script_id`s it
picked.

### 5.6 Run it

```bash
export PYTHONPATH="/Users/janarddan/1.jana files/3.MyMacProjects/easy_agents:/Users/janarddan/1.jana files/3.MyMacProjects/easy_agents/src"
python3 -u run_live_eval.py
```

**Timing**: real measured pace is roughly **20-90 seconds per conversation turn**
(variance is real — Ollama cloud endpoint speed fluctuates). A script has 8-9 turns.
For more than 2-3 scripts, run it detached so it survives your terminal closing:

```bash
nohup env PYTHONPATH="$PYTHONPATH" ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  python3 -u run_live_eval.py > my_run.log 2>&1 &
disown
echo "PID: $!"
```

Check on it any time with:
```bash
tail -f my_run.log
grep -E "^\[[0-9]+/" my_run.log        # just the per-script progress lines
ps -p <PID> -o pid,etime               # confirm it's still alive, and for how long
```

### 5.7 Read the results

Written after **every conversation**, not just at the end — safe to check mid-run:
```
results/report_<timestamp>.json    # full detail: per-conversation + per-turn, never just the ATF number
results/report_<timestamp>.csv     # same data, flattened for a spreadsheet
```

JSON shape:
```
summary.atf.score / summary.atf.coverage
summary.groups.{nts,sts,tis,rs,os}.{score,status}
conversations[].{conversation_id, nts, sts, tis, rs, os, atf, metric_coverage, turns[]}
```

### 5.8 Optional: Policy Compliance + scorecard

Separate from ATF — checks business-rule violations (e.g. a discount granted outside
policy limits) against the same captured trace, no second agent run needed:

```bash
python3 -u run_policy_demo.py
```
Edit `SCRIPT_ID` near the top of that file and `collection_agent_policy_rules.py`'s
`RULES` list to point at a different script/rule set.

---

## 6. Troubleshooting

- **`HTTP Error 429: Too Many Requests`** in the log — Ollama cloud rate-limited a
  request. That one script is marked failed (`atf=0.0`, most metrics `None`) and the run
  continues automatically to the next script — it does not stop the batch. Usually
  transient; check later lines in the log to see if it recovered.
- **A script seems stuck** (no new log lines for a long time, process still alive) —
  check `ps -p <PID> -o pid,%cpu,etime`. Near-0% CPU + large elapsed time means it's
  blocked waiting on a network response, not computing — there's no enforced timeout on a
  single agent turn currently. If you need to bail: `kill -9 <PID>`.
- **Cleaning up after a killed run** — `run_live_eval.py` restores the live agent's
  `data/*.json` and `runtime/` in a `finally` block, but a `kill -9` skips that. Check:
  ```bash
  cd "/Users/janarddan/1.jana files/3.MyMacProjects/easy_agents"
  git status --porcelain -- agents/collection_agent/data agents/collection_agent/runtime
  ```
  If it shows changes: `git checkout -- agents/collection_agent/data agents/collection_agent/runtime`
  (safe — that's disposable scratch/fixture state, not anything hand-edited).
- **Ollama unreachable** — `open -a Ollama` (macOS) or `ollama serve`, wait a few
  seconds, retry the curl checks in §5.2.
- **RS scores look identical/deterministic across runs** — you're missing
  `ANTHROPIC_API_KEY`, or passed `--no-routing-judge`; check for
  `[info] ANTHROPIC_API_KEY not set -- RS will report N/A` in the output.

---

## 7. CLI flag reference

```
atf-eval run
  --dataset PATH              golden dataset JSONL (required)
  --adapter MODULE:CLASS      your TrajectoryAgent adapter (required)
  --output-dir DIR            default ./results
  --weights-file PATH         optional JSON override of {nts,sts,tis,rs,os} weights
  --tool-arg-tolerance FLOAT  numeric tolerance for tool-arg / outcome-attribute matching (default 0.0)
  --limit N                   only evaluate the first N conversations
  --concurrency N              per-conversation parallelism (default 1)
  --judge-model NAME           Anthropic model for RS's routing judge (default claude-opus-5)
  --effort LEVEL                routing judge model effort: low|medium|high|xhigh|max
  --no-routing-judge            skip the LLM call entirely -- RS's semantic half is N/A

atf-eval report PATH            print the per-conversation results table from a saved report.json
                                 (same table `run` prints automatically -- use this to re-view a
                                 past run without re-executing it)
```

`integrations/collection_agent/convert_golden_dataset.py`:
```
--list-categories             print all 22 category names + counts, do nothing else
--categories "A,B,C"          only include these categories (must match names exactly)
--per-category N              how many scripts per included category (default 1)
```
