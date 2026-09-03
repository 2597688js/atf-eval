---
name: atf-dashboard
description: Score agent-eval's golden dataset(s) against their observed-scenario fixtures (NTS/STS/TIS/RS/OS, full component level, ATF composite) and produce a shareable interactive HTML dashboard plus CSVs. Use when asked to run/score agent-eval, produce ATF metrics, or build an ATF dashboard/report for golden vs. observed trajectories.
---

# ATF dashboard

Reproduces the golden-vs-observed ATF evaluation for `agent-eval`: computes
every NTS/STS/TIS/RS/OS sub-component (never re-derives a formula -- calls
`atf_eval`'s real metric functions), and renders both machine-readable CSVs and
a single-file interactive HTML dashboard, all verified against
`agent-eval/METRICS.md` (the frozen spec).

## When to use this

The user asks to run/score `agent-eval`, generate ATF metrics for the
golden dataset(s) vs. their test scenarios, or wants a dashboard/report of those
results (component-level, plain-English metric explanations, or similar to a
prior ATF dashboard in this project).

## Steps

1. **Activate the venv and run the generator** from the repo root:

   ```bash
   cd "/Users/janarddan/1.jana files/3.MyMacProjects/atf_eval"
   source .venv/bin/activate
   python .claude/skills/atf-dashboard/scripts/generate_atf_dashboard.py
   ```

   Defaults to every `*.json` file in `agent-eval/golden/` as the golden
   scenarios (e.g. `S001_motor_insurance_hardship_installment`,
   `S002_motor_insurance_promise_to_pay`, ...) and every `*.json` fixture in
   `agent-eval/tests/fixtures/scenarios/` as the observed runs (auto-discovered
   -- add a golden file or a fixture and it's picked up on the next run, no
   code change needed). Each fixture is routed to its matching golden via its
   own `golden_scenario` field, so the fixture set can mix scenarios for any
   number of goldens. Override with `--golden-dir`, `--scenarios`,
   `--output-dir` if the user points at different fixtures. Output goes to
   `results/` by default:
   - `atf_metrics_<ts>.csv` -- group-level (golden/NTS/STS/TIS/RS/OS/ATF/coverage)
   - `atf_metrics_components_<ts>.csv` -- every sub-component
   - `atf_dashboard_<ts>.html` -- the interactive dashboard (no external JS --
     radio-driven CSS tabs + native `<details>`, theme-aware light/dark),
     tabs grouped one block per golden scenario (baseline first, then that
     golden's own fixtures)

2. **Publish the dashboard** with the Artifact tool (`file_path` = the generated
   `atf_dashboard_<ts>.html`, `favicon: "📊"`, a one-line `description`). Load the
   `artifact-design` skill first only if you're materially changing the dashboard's
   design -- redeploying the generator's own output as-is doesn't need it.

3. **Send downloadable copies** of the HTML dashboard and both CSVs via
   `SendUserFile` so the user has files they can hand to someone directly,
   alongside the artifact link.

4. **Report back**: the ATF headline per scenario, and call out any auto-detected
   caveat from the dashboard's "Notes for the reader" section (e.g. an OS score
   that's really a fixture-normalization gap, not a real outcome miss) so the
   user doesn't misread a flagged number.

## What's auto-generated vs. fixed

- **Data-driven** (recomputed every run, scales to any number of golden
  scenarios and fixtures): all scores, the at-a-glance table, the tab bar +
  drill-down panels (grouped per golden), which metric groups auto-expand
  (whichever didn't score a clean 1.000/N/A), and the caveat notes (detected
  via `annotate_notes()` in the script: an observed run missing an `outcome`
  field entirely -- vs. one that carries a real `outcome` that just doesn't
  match golden's, which scores a genuine 0.000 rather than being flagged --,
  RS being N/A everywhere because no fixture carries `routing`, and a
  `wrong_tool_input`-style deviation where golden's own expected args are
  `{}` so nothing was there to get wrong).
- **Fixed** (same for any dataset, since these describe the frozen spec, not a
  particular run): the "What each metric means" glossary cards and their
  formulas, the METRICS.md §11 deviation-taxonomy → primary-metric mapping in
  `primary_metric_for()`, and the page's visual design in `dashboard_shell.html`.

## If the fixture set or schema changes

- New golden scenario dropped into `agent-eval/golden/`: nothing to do --
  `discover_goldens()` picks it up and gets its own baseline run.
- New scenario fixture dropped into the scenarios directory: nothing to do,
  as long as it sets `golden_scenario` to the matching golden's
  `metadata.scenario_id` (or `trace_id`) -- `discover_runs()` routes it
  automatically. A fixture with no `golden_scenario` field only works when
  there's exactly one golden file; with more than one it's skipped with a
  `[WARN]` on stderr.
- Golden or fixture JSON shape changes (new fields, different nesting): update
  the normalization helpers at the top of `generate_atf_dashboard.py`
  (`load_golden_turns` / `load_fixture_turns` / `_normalize_raw_turn`) --
  they intentionally mirror `tests/fixtures/reference_adapter.py` so check that
  file too if it was the one that changed. Note `load_fixture_turns` also
  attaches a trace-level `outcome` (if the fixture has one) to its last turn,
  same convention as golden -- don't drop that when touching this function.
- METRICS.md formulas/weights change: nothing here to touch -- this script
  only calls `atf_eval`'s metric functions, never reimplements a formula, so a
  spec change should land in `src/atf_eval/` first and this script picks it up
  for free. Re-verify alignment by re-reading `agent-eval/METRICS.md` §2-§7
  against `src/atf_eval/aggregate.py` and `src/atf_eval/metrics/*.py`.
