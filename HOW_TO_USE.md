# How to use atf-eval

You already have golden datasets and tests — you're not writing an agent adapter (we'll
cover live-agent integration later). This is the whole loop.

## 1. Clone and install

```bash
git clone https://github.com/2597688js/atf-eval.git
cd atf-eval
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## 2. Shape your golden datasets + tests

This is the only real requirement. Two directories of JSON files, matching
`schema/normalized_trajectory.schema.json`:

- **Golden** — one file per scenario: the expected trajectory (each turn has `nodes[]`
  with `state_changes`/`tool_calls`, optional `routing`, and a trace-level `outcome`).
- **Tests** (observed fixtures) — one file per test case: same general shape, plus a
  `golden_scenario` field naming which golden file it's scored against.

If your existing golden/tests already look like this (nodes, state changes, tool calls
per turn), you're basically done — just drop them into two folders. If they're in a
different format, write a small converter (the repo's own `reference_adapter.py` is a
working example: raw shape in, canonical shape out).

## 3. Put them in two folders, inside your own project

```
your-project/
  golden/                        # your golden scenario files
  tests/fixtures/scenarios/      # your observed test fixtures
```

These exact names (`golden/`, `tests/fixtures/scenarios/`) are `atf-eval dashboard`'s
defaults, so using them means the command in step 5 needs zero flags. Different names
work too — just pass `--golden-dir` / `--scenarios`.

## 4. (Optional) API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Skip this and pass `--no-routing-judge --no-llm-evals` in the next step if you only want
the deterministic trajectory scores (NTS/STS/TIS/OS) — zero network calls, zero cost.

## 5. Run it

```bash
cd your-project
atf-eval dashboard
```

`atf-eval dashboard` is a real subcommand of the installed package (not a script you
need to locate inside the atf-eval checkout) — run it from your own project directory.
The first run makes real API calls; every judge response is cached on disk
(`.llm_cache/`), so a re-run against unchanged data/prompts is free and near-instant.

## 6. Open the result

```
results/atf_dashboard_<timestamp>.html
```

Open it in a browser — that's your scorecard: ATF per test case, plus every LLM metric
if you set the API key.
