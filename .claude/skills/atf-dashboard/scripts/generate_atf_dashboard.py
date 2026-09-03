#!/usr/bin/env python3
"""Generate ATF metrics (group-level + full component-level) and an
interactive HTML dashboard for agent-eval's golden dataset(s) vs. their
observed-scenario fixtures.

Supports multiple golden scenarios at once (e.g. S001, S002, ...): every
*.json file in --golden-dir is its own golden trajectory, and each observed
fixture is routed to the golden it belongs to via its own `golden_scenario`
field (falling back to the sole golden when there's only one).

Self-contained: normalizes the two raw fixture shapes itself (mirrors
tests/fixtures/reference_adapter.py so this skill has no dependency on the
test tree), computes every NTS/STS/TIS/RS/OS sub-component via atf_eval's
real metric functions (never re-derives a formula), and renders CSVs +
a single-file HTML dashboard with no external JS (radio-driven CSS tabs +
native <details>).

Usage (from the atf_eval repo root, with .venv active):
    python .claude/skills/atf-dashboard/scripts/generate_atf_dashboard.py
    python .claude/skills/atf-dashboard/scripts/generate_atf_dashboard.py \\
        --golden-dir path/to/golden_dir --scenarios path/to/scenarios_dir \\
        --output-dir results/
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import sys
from pathlib import Path

from atf_eval.aggregate import DEFAULT_WEIGHTS, atf_score
from atf_eval.metrics.nodes import (
    node_coverage,
    node_order_similarity,
    node_precision,
    node_recall,
    nts_conversation,
)
from atf_eval.metrics.outcome import (
    last_outcome,
    os_conversation,
    outcome_attribute_accuracy,
    outcome_completion,
    outcome_identity_accuracy,
)
from atf_eval.metrics.routing import rs_conversation, routing_order_similarity
from atf_eval.metrics.state import (
    new_state_accuracy,
    old_state_accuracy,
    state_key_accuracy,
    sts_conversation,
    transition_accuracy,
    transition_order_similarity,
)
from atf_eval.metrics.tools import (
    tis_conversation,
    tool_coverage,
    tool_identity_accuracy,
    tool_input_similarity,
    tool_order_similarity,
    tool_precision,
)
from atf_eval.normalized import NormalizedNode, NormalizedTurn, Outcome, StateChange, ToolCall

REPO_ROOT = Path(__file__).resolve().parents[4]

# ---------------------------------------------------------------------------
# Fixture normalization (mirrors tests/fixtures/reference_adapter.py -- kept
# self-contained here so this skill has no dependency on the test tree).
# ---------------------------------------------------------------------------


def _state_changes(raw: list[dict]) -> list[StateChange]:
    return [StateChange(key=c["key"], old=c.get("old"), new=c.get("new")) for c in raw]


def _canonical_tool_calls(raw: list[dict]) -> list[ToolCall]:
    return [
        ToolCall(
            tool_id=tc["tool_id"],
            arguments=tc.get("input", {}),
            sequence=tc.get("sequence"),
            status=tc.get("status", "unknown"),
        )
        for tc in raw
    ]


def _raw_fixture_tool_calls(raw: list[dict]) -> list[ToolCall]:
    return [
        ToolCall(
            tool_id=tc["tool_name"],
            arguments=tc.get("input", {}),
            sequence=tc.get("sequence_index"),
            status="success",
        )
        for tc in raw
    ]


def load_golden_turns(path: Path) -> list[NormalizedTurn]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    turns = []
    for t in doc["turns"]:
        nodes = [
            NormalizedNode(
                node_id=n["node_id"],
                sequence=n.get("sequence"),
                output=n.get("output", {}),
                state_changes=_state_changes(n.get("state_changes", [])),
                tool_calls=_canonical_tool_calls(n.get("tool_calls", [])),
            )
            for n in t.get("nodes", [])
        ]
        flat_tool_calls = [tc for n in nodes for tc in n.tool_calls]
        turns.append(
            NormalizedTurn(
                conversation_id=doc["trace_id"],
                turn_id=t["turn_id"],
                nodes=nodes,
                tool_calls=flat_tool_calls,
                response=t.get("output", {}).get("agent"),
            )
        )
    raw_outcome = doc.get("outcome")
    if raw_outcome is not None and turns:
        turns[-1].outcome = Outcome(id=raw_outcome["id"], attributes=raw_outcome.get("attributes", {}))
    return turns


def _normalize_raw_turn(raw_turn: dict) -> NormalizedTurn:
    nodes = [
        NormalizedNode(
            node_id=n["node_id"],
            sequence=n.get("sequence_index"),
            state_changes=_state_changes(n.get("state_changes", [])),
            tool_calls=_raw_fixture_tool_calls(n.get("tool_calls", [])),
        )
        for n in raw_turn.get("nodes", [])
    ]
    flat_tool_calls = [tc for n in nodes for tc in n.tool_calls]
    return NormalizedTurn(
        conversation_id="_",
        turn_id=raw_turn["turn_id"],
        nodes=nodes,
        tool_calls=flat_tool_calls,
        response=raw_turn.get("conversation", {}).get("agent"),
    )


def load_fixture_turns(path: Path) -> list[NormalizedTurn]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if "turns" in doc:
        turns = [_normalize_raw_turn(t) for t in doc["turns"]]
    else:
        turns = [_normalize_raw_turn(doc["turn"])]
    # Some observed fixtures (e.g. a disconnect/drift scenario) carry a
    # trace-level `outcome`, same convention as the golden files -- attach it
    # to the last turn so OS can actually see it instead of reading N/A/0.0
    # for a fixture gap that isn't really there.
    raw_outcome = doc.get("outcome")
    if raw_outcome is not None and turns:
        turns[-1].outcome = Outcome(id=raw_outcome["id"], attributes=raw_outcome.get("attributes", {}))
    return turns


# ---------------------------------------------------------------------------
# Metric computation -- every sub-component, via atf_eval's real functions.
# ---------------------------------------------------------------------------


def score_components(expected: list[NormalizedTurn], observed: list[NormalizedTurn]) -> dict:
    exp_node_ids = [n.node_id for t in expected for n in t.nodes]
    obs_node_ids = [n.node_id for t in observed for n in t.nodes]

    combined_expected = NormalizedTurn(
        conversation_id="_", turn_id=0,
        nodes=[n for t in expected for n in t.nodes],
        state_changes=[c for t in expected for c in t.state_changes],
    )
    combined_observed = NormalizedTurn(
        conversation_id="_", turn_id=0,
        nodes=[n for t in observed for n in t.nodes],
        state_changes=[c for t in observed for c in t.state_changes],
    )

    exp_calls = [tc for t in expected for tc in t.tool_calls]
    obs_calls = [tc for t in observed for tc in t.tool_calls]
    exp_tool_names = [t.tool_id for t in exp_calls]
    obs_tool_names = [t.tool_id for t in obs_calls]

    exp_outcome = last_outcome(expected)
    obs_outcome = last_outcome(observed)

    group_scores = {
        "nts": nts_conversation(expected, observed),
        "sts": sts_conversation(expected, observed),
        "tis": tis_conversation(expected, observed),
        "rs": rs_conversation(expected, observed, per_turn_semantic_scores=[None] * len(observed)),
        "os": os_conversation(expected, observed),
    }
    atf, coverage = atf_score(group_scores, DEFAULT_WEIGHTS)

    return {
        "nts_coverage": node_coverage(exp_node_ids, obs_node_ids),
        "nts_precision": node_precision(exp_node_ids, obs_node_ids),
        "nts_recall_diag": node_recall(exp_node_ids, obs_node_ids),
        "nts_order": node_order_similarity(exp_node_ids, obs_node_ids),
        "nts_overall": group_scores["nts"],
        "sts_transition_accuracy": transition_accuracy(combined_expected, combined_observed),
        "sts_order": transition_order_similarity(combined_expected, combined_observed),
        "sts_key_accuracy_diag": state_key_accuracy(combined_expected, combined_observed),
        "sts_old_value_accuracy_diag": old_state_accuracy(combined_expected, combined_observed),
        "sts_new_value_accuracy_diag": new_state_accuracy(combined_expected, combined_observed),
        "sts_overall": group_scores["sts"],
        "tis_coverage": tool_coverage(exp_tool_names, obs_tool_names),
        "tis_precision": tool_precision(exp_tool_names, obs_tool_names),
        "tis_identity": tool_identity_accuracy(exp_calls, obs_calls),
        "tis_input_similarity": tool_input_similarity(exp_calls, obs_calls),
        "tis_order": tool_order_similarity(exp_tool_names, obs_tool_names),
        "tis_overall": group_scores["tis"],
        "rs_semantic": None,  # no judge_client wired up -- see rs_overall note below
        "rs_order": routing_order_similarity(expected, observed),
        "rs_overall": group_scores["rs"],
        "os_identity": outcome_identity_accuracy(exp_outcome, obs_outcome),
        "os_attribute": outcome_attribute_accuracy(exp_outcome, obs_outcome),
        "os_completion": outcome_completion(exp_outcome, obs_outcome),
        "os_overall": group_scores["os"],
        "atf": atf,
        "metric_coverage": coverage,
        "_exp_outcome": exp_outcome,
        "_obs_outcome": obs_outcome,
    }


def turns_compared_label(expected: list[NormalizedTurn], golden_turns: list[NormalizedTurn]) -> str:
    if len(expected) == len(golden_turns):
        return f"{len(expected)} (full conversation)"
    ids = sorted(t.turn_id for t in expected)
    if len(ids) == 1:
        return f"1 (turn {ids[0]} only)"
    return f"{len(ids)} (turns {ids[0]}-{ids[-1]})"


# ---------------------------------------------------------------------------
# Run discovery + orchestration
# ---------------------------------------------------------------------------


def discover_goldens(golden_dir: Path) -> list[dict]:
    """Every *.json golden file in golden_dir. Each is keyed by its own
    metadata.scenario_id (falling back to trace_id) -- that's the same key
    an observed fixture names in its `golden_scenario` field, so fixtures can
    be routed to the correct golden regardless of how many golden scenarios
    are in play."""
    goldens = []
    for path in sorted(golden_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        key = doc.get("metadata", {}).get("scenario_id") or doc["trace_id"]
        goldens.append({"key": key, "path": path, "turns": load_golden_turns(path)})
    return goldens


def discover_runs(goldens: list[dict], scenarios_dir: Path) -> list[dict]:
    """A golden-vs-itself baseline per golden scenario, plus every *.json
    fixture found in scenarios_dir, each routed to its matching golden via
    its own `golden_scenario` field (falling back to the sole golden when
    there's only one, for older fixtures that don't set the field). The
    matching golden slice for each fixture is whatever golden turn_ids the
    fixture itself covers -- this generalizes correctly whether a fixture is
    a full conversation or a single turn. Runs are grouped by golden -- each
    golden's baseline immediately followed by its own matching fixtures --
    so the dashboard's tab order reads as one block per golden scenario."""
    golden_by_key = {g["key"]: g for g in goldens}
    fixture_docs = []  # (path, doc_meta, matched_golden_or_None), matched once per fixture
    for path in sorted(scenarios_dir.glob("*.json")):
        doc_meta = json.loads(path.read_text(encoding="utf-8"))
        golden_key = doc_meta.get("golden_scenario")
        if golden_key and golden_key in golden_by_key:
            g = golden_by_key[golden_key]
        elif len(goldens) == 1:
            g = goldens[0]
        else:
            print(
                f"[WARN] {path.name}: golden_scenario={golden_key!r} matches no golden "
                f"file in {scenarios_dir} -- skipping", file=sys.stderr,
            )
            g = None
        fixture_docs.append((path, doc_meta, g))

    runs = []
    for g in goldens:
        short = g["key"].split("_", 1)[0] if "_" in g["key"] else g["key"]
        runs.append(
            {
                "scenario": f"{short}_golden_baseline",
                "deviation_type": "none",
                "description": f"Golden trajectory ({g['key']}) scored against itself (sanity baseline).",
                "expected": g["turns"],
                "observed": g["turns"],
                "turns_compared": turns_compared_label(g["turns"], g["turns"]),
                "doc_meta": {},
                "golden_key": g["key"],
            }
        )
        for path, doc_meta, matched in fixture_docs:
            if matched is not g:
                continue
            golden_turns = g["turns"]
            observed = load_fixture_turns(path)
            observed_ids = {t.turn_id for t in observed}
            expected = [t for t in golden_turns if t.turn_id in observed_ids] or golden_turns
            runs.append(
                {
                    "scenario": path.stem,
                    "deviation_type": doc_meta.get("deviation_type", "unknown"),
                    "description": doc_meta.get("deviation", {}).get("description", ""),
                    "expected": expected,
                    "observed": observed,
                    "turns_compared": turns_compared_label(expected, golden_turns),
                    "doc_meta": doc_meta,
                    "golden_key": g["key"],
                }
            )
    return runs


def band(score: float | None) -> str:
    if score is None:
        return "na"
    if score >= 0.95:
        return "good"
    if score >= 0.80:
        return "warning"
    if score >= 0.50:
        return "serious"
    return "critical"


def fmt(score: float | None) -> str:
    return "N/A" if score is None else f"{score:.3f}"


def pct(width: float | None) -> str:
    return "100%" if width is None else f"{width * 100:.1f}%"


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------

GROUP_FIELDS = [
    "golden", "scenario", "deviation_type", "description", "turns_compared",
    "nts", "sts", "tis", "rs", "os", "atf", "metric_coverage",
]

COMPONENT_FIELDS = [
    "golden", "scenario", "deviation_type", "description", "turns_compared",
    "nts_coverage", "nts_precision", "nts_recall_diag", "nts_order", "nts_overall",
    "sts_transition_accuracy", "sts_order", "sts_key_accuracy_diag",
    "sts_old_value_accuracy_diag", "sts_new_value_accuracy_diag", "sts_overall",
    "tis_coverage", "tis_precision", "tis_identity", "tis_input_similarity", "tis_order", "tis_overall",
    "rs_semantic", "rs_order", "rs_overall",
    "os_identity", "os_attribute", "os_completion", "os_overall",
    "atf", "metric_coverage",
]


def write_csvs(runs: list[dict], output_dir: Path, timestamp: str) -> tuple[Path, Path]:
    group_path = output_dir / f"atf_metrics_{timestamp}.csv"
    component_path = output_dir / f"atf_metrics_components_{timestamp}.csv"

    with group_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=GROUP_FIELDS)
        writer.writeheader()
        for run in runs:
            m = run["metrics"]
            writer.writerow({
                "golden": run.get("golden_key", ""),
                "scenario": run["scenario"], "deviation_type": run["deviation_type"],
                "description": run["description"], "turns_compared": run["turns_compared"],
                "nts": m["nts_overall"], "sts": m["sts_overall"], "tis": m["tis_overall"],
                "rs": m["rs_overall"], "os": m["os_overall"],
                "atf": m["atf"], "metric_coverage": m["metric_coverage"],
            })

    with component_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COMPONENT_FIELDS)
        writer.writeheader()
        for run in runs:
            m = run["metrics"]
            row = {k: v for k, v in m.items() if not k.startswith("_")}
            row.update({
                "golden": run.get("golden_key", ""),
                "scenario": run["scenario"], "deviation_type": run["deviation_type"],
                "description": run["description"], "turns_compared": run["turns_compared"],
            })
            writer.writerow(row)

    return group_path, component_path


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

PAGE_SHELL = Path(__file__).with_name("dashboard_shell.html").read_text(encoding="utf-8")

GLOSSARY_LABELS = ["NTS", "STS", "TIS", "RS", "OS"]

GROUP_META = [
    ("nts", "NTS", "30%", [
        ("Coverage", "nts_coverage", False),
        ("Precision", "nts_precision", False),
        ("Order", "nts_order", False),
        ("Recall", "nts_recall_diag", True),
    ]),
    ("sts", "STS", "30%", [
        ("Transition accuracy", "sts_transition_accuracy", False),
        ("Order", "sts_order", False),
        ("Key accuracy", "sts_key_accuracy_diag", True),
        ("Old-value accuracy", "sts_old_value_accuracy_diag", True),
        ("New-value accuracy", "sts_new_value_accuracy_diag", True),
    ]),
    ("tis", "TIS", "15%", [
        ("Coverage", "tis_coverage", False),
        ("Precision", "tis_precision", False),
        ("Identity", "tis_identity", False),
        ("Input similarity", "tis_input_similarity", False),
        ("Order", "tis_order", False),
    ]),
    ("rs", "RS", "10%", [
        ("Semantic (LLM judge)", "rs_semantic", False),
        ("Order", "rs_order", False),
    ]),
    ("os", "OS", "15%", [
        ("Identity", "os_identity", False),
        ("Attribute", "os_attribute", False),
        ("Completion", "os_completion", False),
    ]),
]


def render_pill(score: float | None, flagged: bool = False) -> str:
    b = band(score)
    flag = "&nbsp;&#9888;" if flagged else ""
    return f'<span class="pill {b}">{fmt(score)}{flag}</span>'


def render_glance_row(run: dict, baseline: bool) -> str:
    m = run["metrics"]
    row_class = ' class="baseline"' if baseline else ""
    flag_os = m.get("_os_flag", False)
    return f"""
          <tr{row_class}>
            <td class="scenario-cell"><span class="name">{run['scenario']}</span><span class="dev">{run['description'][:60]}</span></td>
            <td class="num">{render_pill(m['nts_overall'])}</td>
            <td class="num">{render_pill(m['sts_overall'])}</td>
            <td class="num">{render_pill(m['tis_overall'])}</td>
            <td class="num">{render_pill(m['rs_overall'])}</td>
            <td class="num">{render_pill(m['os_overall'], flagged=flag_os)}</td>
            <td class="num">{render_pill(m['atf'], flagged=flag_os)}</td>
          </tr>"""


def render_component_row(label: str, score: float | None, diag: bool) -> str:
    b = band(score)
    diag_tag = '<span class="diag">diagnostic</span>' if diag else ""
    color = "" if score is not None else f' style="color:var(--na)"'
    return f"""
              <div class="component-row"><span class="c-label">{label}{diag_tag}</span><span class="c-track"><span class="c-fill {b}" style="width:{pct(score)}"></span></span><span class="c-score"{color}>{fmt(score)}</span></div>"""


def render_group_meter(key: str, label: str, weight: str, components: list, m: dict, open_default: bool) -> str:
    score = m[f"{key}_overall"]
    b = band(score)
    open_attr = " open" if open_default else ""
    rows = "".join(render_component_row(c_label, m[c_key], diag) for c_label, c_key, diag in components)
    return f"""
          <details class="group-meter"{open_attr}>
            <summary>
              <span class="g-label">{label}<span class="weight">{weight}</span></span>
              <span class="meter-track"><span class="meter-fill {b}" style="width:{pct(score)}"></span></span>
              <span class="g-score" style="color:var(--{b})">{fmt(score)}</span>
            </summary>
            <div class="component-list">{rows}
            </div>
          </details>"""


def primary_metric_for(deviation_type: str) -> str | None:
    """METRICS.md S11's deviation-taxonomy -> primary-metric mapping, for the
    deviation_type values this project's own fixtures actually use."""
    taxonomy = {
        "correct_answer_wrong_trajectory": "NTS",
        "wrong_node_executed": "NTS",
        "node_skipped": "NTS",
        "unexpected_node_executed": "NTS",
        "wrong_node_order": "NTS",
        "wrong_state_transition": "STS",
        "missing_state_transition": "STS",
        "wrong_state_progression": "STS",
        "missing_tool_call": "TIS",
        "unexpected_tool_call": "TIS",
        "wrong_tool": "TIS",
        "wrong_tool_input": "TIS",
        "wrong_tool_sequence": "TIS",
        "wrong_conversational_path": "RS",
        "partial_incorrect_outcome": "OS",
        "correct_trajectory_wrong_outcome": "OS",
        "trajectory_drift": "NTS / RS",
        # Not a literal METRICS.md §11 row -- closest official bucket is
        # "Trajectory drift across turns", same NTS / RS mapping.
        "trajectory_drift_customer_disconnection": "NTS / RS",
    }
    return taxonomy.get(deviation_type)


def render_panel(idx: int, run: dict) -> str:
    m = run["metrics"]
    atf_band = band(m["atf"])
    chips = f'<span class="chip">{run["turns_compared"]}</span>'
    if run["deviation_type"] != "none":
        chips += f'<span class="chip">deviation: {run["deviation_type"]}</span>'
        primary = primary_metric_for(run["deviation_type"])
        if primary:
            chips += f'<span class="chip primary">METRICS.md &sect;11 primary metric: {primary}</span>'

    flag_os = m.get("_os_flag", False)
    atf_flag = "&nbsp;&#9888;" if flag_os else ""

    open_flags = {key: False for key, *_ in GROUP_META}
    # Auto-open whichever groups are not a clean 1.000 / N/A, so the reader's
    # eye lands on what actually moved for this run.
    for key, *_ in GROUP_META:
        s = m[f"{key}_overall"]
        if s is not None and s < 0.999:
            open_flags[key] = True
    if not any(open_flags.values()):
        open_flags["nts"] = True  # baseline run: open something by default

    meters = "".join(
        render_group_meter(key, label, weight, components, m, open_flags[key])
        for key, label, weight, components in GROUP_META
    )

    note = m.get("_note", "")
    note_html = f'\n          <p class="panel-note">{note}</p>' if note else ""

    desc = run["description"] or "Golden trajectory scored against itself."
    return f"""
      <section id="panel-{idx}" class="panel">
        <div class="panel-card">
          <div class="panel-header">
            <div>
              <h3>{run['scenario']}</h3>
              <p class="desc">{desc}</p>
              <div class="chips">{chips}</div>
            </div>
            <div class="atf-headline">
              <div class="label">ATF</div>
              <div class="value" style="color:var(--{atf_band})">{fmt(m['atf'])}{atf_flag}</div>
              <div class="coverage">{pct(m['metric_coverage'])} metric coverage</div>
            </div>
          </div>
          {meters}{note_html}
        </div>
      </section>"""


def annotate_notes(runs: list[dict]) -> None:
    """Attach auto-detected caveats so the dashboard explains itself rather
    than silently showing a misleading number."""
    for run in runs:
        m = run["metrics"]
        exp_outcome, obs_outcome = m["_exp_outcome"], m["_obs_outcome"]
        m["_os_flag"] = (
            exp_outcome is not None and obs_outcome is None and m["os_overall"] is not None
        )
        if m["_os_flag"]:
            run["callout"] = (
                f"the observed fixture <code>{run['scenario']}.json</code> never records an "
                f"<code>outcome</code> field at all, so it can't match golden's "
                f"<code>{exp_outcome.id}</code> &mdash; that reads as OS&nbsp;=&nbsp;0.000 and pulls "
                f"this run's ATF down to {fmt(m['atf'])}. That's a gap in how the raw fixture is "
                f"shaped, not evidence the agent failed to reach the outcome."
            )
            m["_note"] = (
                "<strong>&#9888; Read this OS score as a fixture gap, not a real miss.</strong> "
                "This observed fixture never records an <code>outcome</code> field, so it can't "
                f"match golden's <code>{exp_outcome.id}</code>. See \"Notes for the reader\" below."
            )
        elif run["deviation_type"] == "missing_tool_call" and m["tis_overall"] == 0.0 and (
            m["nts_overall"] or 0 >= 0.999
        ) and (m["sts_overall"] or 0) >= 0.999:
            m["_note"] = (
                "<strong>This one is a clean, isolated TIS failure.</strong> NTS and STS both stay "
                "perfect &mdash; only the tool call itself is missing, matching METRICS.md's "
                "\"Missing tool call\" deviation definition in &sect;11."
            )
        elif run["doc_meta"].get("deviation", {}).get("expected_input") == {} and m["tis_overall"] == 1.0:
            m["_note"] = (
                "<strong>Named a tool-input deviation, scores perfect &mdash; and that's correct "
                "behavior.</strong> Golden's own call here expects no arguments (<code>{}</code>). "
                "Per METRICS.md &sect;4, Tool Input Similarity is \"average similarity of matched "
                "tool inputs\" &mdash; when nothing was required, there is nothing to get wrong, so "
                "this fixture's argument mismatch never surfaces in TIS."
            )


def render_dashboard(runs: list[dict], golden_summary: str, scenarios_dir: Path, run_date: str) -> str:
    glance_rows = "".join(
        render_glance_row(run, baseline=(run["deviation_type"] == "none")) for run in runs
    )
    tab_inputs = "".join(
        f'\n      <input type="radio" name="stabs" id="tab-{i}" class="tab-input"{" checked" if i == 1 else ""}>'
        for i in range(1, len(runs) + 1)
    )
    tab_labels = "".join(
        f'\n        <label for="tab-{i}" class="tab-label">{run["scenario"].replace("_", " ").title()}</label>'
        for i, run in enumerate(runs, start=1)
    )
    tab_css = "\n  ".join(
        f'#tab-{i}:checked ~ .tab-bar label[for="tab-{i}"],' for i in range(1, len(runs) + 1)
    ).rstrip(",") + " { background: var(--accent); border-color: var(--accent); color: #fff; }"
    panel_css = "\n  ".join(
        f'#tab-{i}:checked ~ #panel-{i},' for i in range(1, len(runs) + 1)
    ).rstrip(",") + " { display: block; }"
    focus_css = "\n  ".join(
        f'#tab-{i}:focus-visible ~ .tab-bar label[for="tab-{i}"],' for i in range(1, len(runs) + 1)
    ).rstrip(",") + " { outline: 2px solid var(--accent); outline-offset: 2px; }"

    panels = "".join(render_panel(i, run) for i, run in enumerate(runs, start=1))

    any_os_flag = any(r["metrics"].get("_os_flag") for r in runs)
    any_routing = any(r["metrics"]["rs_overall"] is not None for r in runs)
    notes_parts = []
    if any_os_flag:
        for r in runs:
            if r["metrics"].get("_os_flag"):
                notes_parts.append(f"<p>For <code>{r['scenario']}</code>, {r['callout']}</p>")
    if not any_routing:
        notes_parts.append(
            "<p><strong>Routing Similarity (RS)</strong> is N/A across every run: none of these "
            "fixtures record a <code>routing</code> block, so per METRICS.md &sect;5 there is nothing "
            "for the LLM routing judge to evaluate.</p>"
        )
    notes_html = "".join(notes_parts) or "<p>No scoring caveats detected for this run set.</p>"

    html = PAGE_SHELL
    html = html.replace("{{GOLDEN_PATH}}", golden_summary)
    html = html.replace("{{SCENARIOS_PATH}}", str(scenarios_dir))
    html = html.replace("{{RUN_DATE}}", run_date)
    html = html.replace("{{TAB_INPUTS}}", tab_inputs)
    html = html.replace("{{TAB_LABELS}}", tab_labels)
    html = html.replace("{{TAB_ACTIVE_CSS}}", tab_css)
    html = html.replace("{{PANEL_ACTIVE_CSS}}", panel_css)
    html = html.replace("{{TAB_FOCUS_CSS}}", focus_css)
    html = html.replace("{{GLANCE_ROWS}}", glance_rows)
    html = html.replace("{{PANELS}}", panels)
    html = html.replace("{{NOTES}}", notes_html)
    return html


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--golden-dir",
        default=str(REPO_ROOT / "agent-eval" / "golden"),
        help="Directory of golden *.json files (one per golden scenario, e.g. S001/S002).",
    )
    parser.add_argument(
        "--scenarios",
        default=str(REPO_ROOT / "agent-eval" / "tests" / "fixtures" / "scenarios"),
    )
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "results"))
    args = parser.parse_args()

    golden_dir = Path(args.golden_dir)
    scenarios_dir = Path(args.scenarios)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    goldens = discover_goldens(golden_dir)
    if not goldens:
        raise SystemExit(f"No golden *.json files found in {golden_dir}")
    runs = discover_runs(goldens, scenarios_dir)
    for run in runs:
        run["metrics"] = score_components(run["expected"], run["observed"])
    annotate_notes(runs)

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    group_csv, component_csv = write_csvs(runs, output_dir, timestamp)
    golden_summary = ", ".join(f"{g['key']} ({g['path'].name})" for g in goldens)
    dashboard_html = render_dashboard(runs, golden_summary, scenarios_dir, run_date)
    dashboard_path = output_dir / f"atf_dashboard_{timestamp}.html"
    dashboard_path.write_text(dashboard_html, encoding="utf-8")

    print("Wrote:")
    print(f"  {group_csv}")
    print(f"  {component_csv}")
    print(f"  {dashboard_path}")
    for run in runs:
        m = run["metrics"]
        print(f"[{run.get('golden_key', '')}] {run['scenario']}: ATF={fmt(m['atf'])} NTS={fmt(m['nts_overall'])} "
              f"STS={fmt(m['sts_overall'])} TIS={fmt(m['tis_overall'])} "
              f"RS={fmt(m['rs_overall'])} OS={fmt(m['os_overall'])}")


if __name__ == "__main__":
    main()
