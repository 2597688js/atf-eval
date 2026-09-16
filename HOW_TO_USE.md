# How to use atf-eval

You already have golden datasets and tests — you're not writing an agent adapter (we'll
cover live-agent integration later). This is the whole loop.

## 1. Clone atf-eval into your project, and install it

Run these from your own project's root (the one with your golden datasets and tests):

```bash
cd your-project
git clone https://github.com/2597688js/atf-eval.git
python3 -m venv .venv && source .venv/bin/activate
pip install -e atf-eval/
```

`atf-eval` is now installed as a normal command in this venv — everything past this
point is run from `your-project/`, not from inside the `atf-eval/` subfolder.

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

## 3. Put them in two folders, at your project root

```
your-project/
  atf-eval/                      # the framework, cloned in step 1
  golden/                        # your golden scenario files
  tests/fixtures/scenarios/      # your observed test fixtures
```

These exact names (`golden/`, `tests/fixtures/scenarios/`) are `atf-eval dashboard`'s
defaults, so using them means the command in step 5 needs zero flags. Different names
or locations work too — see step 5 for the flags to point at them directly.

## 4. (Optional) API key

Needed for RS's semantic judge and the Group 1-4 LLM metrics. Put it in a `.env` file
**at your project root** (`your-project/.env`, next to `golden/` — not inside
`atf-eval/`):
```
ANTHROPIC_API_KEY=sk-ant-...
```
`atf-eval` looks for `.env` in the current directory first (falling back to its own
package folder only if that one doesn't exist) — so this only works if you run
`atf-eval dashboard` from `your-project/`, which is what step 5 does anyway. An
exported env var (`export ANTHROPIC_API_KEY=...`) works too and takes priority over
any `.env`.

Skip this and pass `--no-routing-judge --no-llm-evals` in the next step if you only want
the deterministic trajectory scores (NTS/STS/TIS/OS) — zero network calls, zero cost.

## 5. Run it

```bash
atf-eval dashboard
```

Still from `your-project/` root (same place as steps 3-4) — `atf-eval dashboard` is a
real subcommand of the installed package, not a script you need to locate inside the
`atf-eval/` checkout. The first run makes real API calls; every judge response is cached
on disk (`.llm_cache/`), so a re-run against unchanged data/prompts is free and
near-instant.

Your golden/tests aren't at `golden/` and `tests/fixtures/scenarios/`, or you want output
somewhere other than `results/`? Point directly at them instead:

```bash
atf-eval dashboard \
  --golden-dir path/to/your/golden \
  --scenarios path/to/your/tests \
  --output-dir path/to/output
```

All three flags are independent and optional — set only the ones that differ from the
defaults. Paths can be relative (to wherever you run the command from) or absolute.

## 6. Open the result

```
results/atf_dashboard_<timestamp>.html
```

Open it in a browser — that's your scorecard: ATF per test case, plus every LLM metric
if you set the API key.
