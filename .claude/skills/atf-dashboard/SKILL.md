---
name: atf-dashboard
description: Score agent-eval's golden dataset(s) against their observed-scenario fixtures -- both the deterministic trajectory metrics (NTS/STS/TIS/RS/OS, full component level, ATF composite) and the METRICS.md Part B LLM/multimodal metrics (Groups 1-5) -- and produce ONE shareable interactive HTML dashboard (plus CSVs) with both tracks in it. Use when asked to run/score agent-eval, produce ATF metrics, run the LLM-based Group 1-5 metrics, or build an ATF dashboard/report for golden vs. observed trajectories.
---

# ATF dashboard

Reproduces the golden-vs-observed ATF evaluation for `agent-eval`, on two
independent tracks that both read the same normalized golden/observed
trajectories and render into **one single dashboard file** (one tab per run;
each run's panel holds both tracks, not two separate dashboards/tab systems):

- **Deterministic** (METRICS.md §1-§12): every NTS/STS/TIS/RS/OS
  sub-component, computed by calling `atf_eval`'s real metric functions --
  never re-derives a formula.
- **LLM/multimodal** (METRICS.md Part B, §13-§24, 32 metrics across Groups
  1-5): calls `atf_eval.llm_evals`'s real judge/evaluator code -- never
  reimplements a rubric here. RS's routing judge (part of the deterministic
  track but itself LLM-based) shares the same judge client and on-disk cache.
  Rendered inside each run's panel as an "LLM & Multimodal Evaluation"
  section, right after that run's NTS/STS/TIS/RS/OS meters.

Every score is verified against `agent-eval/METRICS.md`, the frozen spec.

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
   `--output-dir` if the user points at different fixtures.

   The LLM tracks (RS's routing judge + the Group 1-5 metrics) run by
   default whenever `ANTHROPIC_API_KEY` is reachable (checked in the actual
   environment, then a repo-root `.env` fallback) -- no flag needed. Every
   judge call is cached on disk (`.llm_cache/`, content-addressed by
   model+prompt), so a repeat run of the same fixtures against the same
   prompts is near-instant and makes zero new API calls; only new/changed
   (metric, turn, prompt) combinations hit the network. Useful flags:
   - `--no-routing-judge` -- RS reports N/A instead of calling the judge
   - `--no-llm-evals` -- skip Groups 1-5 entirely (each panel then has no
     "LLM & Multimodal Evaluation" section, and no `atf_llm_metrics_<ts>.csv`)
   - `--judge-model` (default `claude-opus-5`), `--effort` (default `low`)

   Output goes to `results/`:
   - `atf_metrics_<ts>.csv` -- group-level (golden/NTS/STS/TIS/RS/OS/ATF/coverage)
   - `atf_metrics_components_<ts>.csv` -- every deterministic sub-component
   - `atf_dashboard_<ts>.html` -- **the single dashboard** (no external JS --
     radio-driven CSS tabs + native `<details>`, theme-aware light/dark), one
     tab per run (grouped one block per golden scenario, baseline first, then
     that golden's own fixtures); each run's panel holds the NTS/STS/TIS/RS/OS
     component drill-down *and* (right below it) the full Group 1-5 LLM
     results for that same run -- one page, no second dashboard to open
   - `atf_llm_metrics_<ts>.csv` -- every Group 1-5 metric result, turn + overall
     (native score, 0-1 normalized display value, status, reason), one row each
   The CSV is only written when at least one run actually got LLM results
   attached (i.e. `--no-llm-evals` wasn't passed).

2. **Publish the dashboard** with the Artifact tool (`file_path` = the
   generated `atf_dashboard_<ts>.html`, `favicon: "📊"`, a one-line
   `description`). If updating a dashboard published earlier in this
   conversation, pass `url` to redeploy to the same link rather than creating
   a new artifact. Load the `artifact-design` skill first only if you're
   materially changing the dashboard's design -- redeploying the generator's
   own output as-is doesn't need it.

3. **Send downloadable copies** of the HTML dashboard and all CSVs via
   `SendUserFile` so the user has files they can hand to someone directly,
   alongside the artifact link.

4. **Report back**: the ATF headline per scenario (deterministic track), plus
   how many of the 32 LLM metrics actually scored vs. N/A per run (Group 5 is
   expected to be all-N/A on text-only fixtures -- that's correct per
   METRICS.md §18, not a gap), and call out any auto-detected caveat from the
   dashboard's "Notes for the reader" section (e.g. an OS score that's really
   a fixture-normalization gap, not a real outcome miss) so the user doesn't
   misread a flagged number.

## What's auto-generated vs. fixed

- **Data-driven** (recomputed every run, scales to any number of golden
  scenarios and fixtures): all scores, the at-a-glance table (group scores
  only -- NTS/STS/TIS/RS/OS/ATF, no `metric_coverage` column; that number is
  a coverage-of-the-formula diagnostic, easy to misread as a quality score
  sitting next to ATF, so it's kept out of the glance view and shown only
  inside each scenario's own drill-down panel, next to that scenario's ATF),
  the tab bar + drill-down panels (grouped per golden -- this is also the
  *only* place component-level sub-scores, and the *only* place Group 1-5 LLM
  results, are shown; there's deliberately no separate cross-scenario
  component table or separate LLM dashboard, to avoid saying the same numbers
  twice or splitting one run's story across two files), which deterministic
  metric groups auto-expand (whichever didn't score a clean 1.000/N/A) and
  which LLM group is open by default (Group 5 stays collapsed since it's
  always-N/A on text-only fixtures), the "LLM scored" glance-table column
  (a plain coverage count over the 19 Group 1-4 metrics, deliberately not a
  colored pill -- Group 5's 13 metrics are excluded from that denominator so
  a correct all-N/A Group 5 doesn't read as a coverage gap), and the caveat
  notes (detected via `annotate_notes()` in the script: an observed run
  missing an `outcome` field entirely -- vs. one that carries a real
  `outcome` that just doesn't match golden's, which scores a genuine 0.000
  rather than being flagged --, RS being N/A everywhere because no fixture
  carries `routing`, and a `wrong_tool_input`-style deviation where golden's
  own expected args are `{}` so nothing was there to get wrong).
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
- METRICS.md §1-§12 (deterministic) formulas/weights change: nothing here to
  touch -- this script only calls `atf_eval`'s metric functions, never
  reimplements a formula, so a spec change should land in `src/atf_eval/`
  first and this script picks it up for free. Re-verify alignment by
  re-reading `agent-eval/METRICS.md` §2-§7 against `src/atf_eval/aggregate.py`
  and `src/atf_eval/metrics/*.py`.
- METRICS.md Part B (§13-§24) metric definitions/rubrics/scoring/levels
  change: land the change in `src/atf_eval/llm_evals/registry.py`
  (`MetricSpec` rows) first -- this script only calls
  `atf_eval.llm_evals.evaluate_conversation()`, never reimplements a rubric.
  Re-verify alignment by re-reading METRICS.md §14-§18's per-group metric
  tables + rubrics against `registry.py`'s `GROUP1`-`GROUP5` lists (name,
  level, scoring type, rubric, N/A rule, overlap boundary, count-per-group),
  and the aggregation/N/A rules in §19-§23 against
  `src/atf_eval/llm_evals/evaluator.py` and `base.py`.
