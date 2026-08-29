# Evaluating `agent-eval-main` with `atf-eval`

Step-by-step for scoring `agent-eval-main`'s golden trajectory against its observed-scenario
fixtures using this repo's `atf-dashboard` skill. This is the fixture-comparison workflow
(component-level NTS/STS/TIS/RS/OS + ATF) — see the note at the bottom for how it differs
from the `atf-eval run` CLI in the main README.

## Prerequisites

- Python 3.10+
- This repo (`atf-eval`) cloned
- `agent-eval-main` present **inside** the clone, at `<repo>/agent-eval-main/` — alongside
  `src/`, `.claude/`, etc. It's intentionally gitignored here (it's a separate, standalone
  repo — see the `.gitignore` note), so it has to reach you through some other channel: your
  own clone of it, a zip, whatever your team uses.

No API key is required. The dashboard script never makes a live LLM call — Routing
Similarity (RS) reports N/A rather than calling a judge.

## Steps

### 1. Set up the environment (one-time)

```bash
cd /path/to/atf-eval
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Confirm `agent-eval-main` is in the right spot

```bash
ls agent-eval-main/golden/motor_insurance_hardship_installment.json
ls agent-eval-main/tests/fixtures/scenarios/
```

Both should list files. If not, that's the only real failure point — move or symlink
`agent-eval-main` to `<repo>/agent-eval-main`.

### 3. (Optional) Sanity-check the framework itself

Runs this project's own conformance suite against these exact fixtures:

```bash
python -m pytest tests/fixtures/test_deviation_scenarios.py -v
```

4 passed = the scoring engine agrees with `agent-eval-main`'s own fixtures.

### 4. Run the evaluation

```bash
python .claude/skills/atf-dashboard/scripts/generate_atf_dashboard.py
```

This is the actual "evaluate `agent-eval-main`" step. It:

- auto-discovers every `*.json` fixture in `agent-eval-main/tests/fixtures/scenarios/`
  (no code change needed when a new deviation fixture is added)
- scores each one against the matching slice of the golden trajectory via `atf_eval`'s real
  metric functions (never re-derives a formula, so it stays aligned with
  `agent-eval-main/METRICS.md` by construction)
- writes three files into `results/`:
  - `agent_eval_main_metrics_<timestamp>.csv` — group-level scores (NTS/STS/TIS/RS/OS/ATF)
  - `agent_eval_main_metrics_components_<timestamp>.csv` — every sub-component
  - `atf_dashboard_<timestamp>.html` — the interactive dashboard

Optional flags if you're pointing it at a different golden dataset or scenarios folder:

```bash
python .claude/skills/atf-dashboard/scripts/generate_atf_dashboard.py \
  --golden path/to/golden.json \
  --scenarios path/to/scenarios_dir \
  --output-dir results/
```

### 5. Open the dashboard

```bash
open results/atf_dashboard_*.html   # macOS; double-click on other OSes
```

It's a self-contained HTML file (no external JS, radio-driven CSS tabs + native
`<details>`) — opens in any browser, no server needed.

## Using Claude Code instead of the raw terminal

If you're in a Claude Code session opened in this repo, just ask it to **"run the
atf-dashboard skill"** — it will do steps 4–5 for you and can also publish a shareable
Artifact link.

## `atf-dashboard` skill vs. the `atf-eval run` CLI

Two separate entry points live in this repo — don't mix them up:

| | `atf-eval run --dataset ... --adapter ...` | `atf-dashboard` skill |
|---|---|---|
| Purpose | Score a **live agent** (via an adapter you write) against a JSONL golden dataset | Score `agent-eval-main`'s canonical golden trajectory against its pre-recorded observed-scenario fixtures |
| Golden format | Normalized JSONL (`agent_eval.normalized` schema) | `agent-eval-main`'s raw canonical JSON |
| Where it's documented | `README.md`, `GETTING_STARTED.md` | `.claude/skills/atf-dashboard/SKILL.md`, this file |

This file covers the second one.
