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
from atf_eval.normalized import (
    NormalizedNode,
    NormalizedTurn,
    Outcome,
    Routing,
    StateChange,
    ToolCall,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

# ---------------------------------------------------------------------------
# Fixture normalization (mirrors tests/fixtures/reference_adapter.py -- kept
# self-contained here so this skill has no dependency on the test tree).
# ---------------------------------------------------------------------------


def _state_changes(raw: list[dict]) -> list[StateChange]:
    return [StateChange(key=c["key"], old=c.get("old"), new=c.get("new")) for c in raw]


def _routing(raw_turn: dict) -> Routing | None:
    raw = raw_turn.get("routing")
    if not raw:
        return None
    return Routing(path=raw.get("path"), target=raw.get("target"))


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
                routing=_routing(t),
                response=t.get("output", {}).get("agent"),
                customer_input=t.get("input", {}).get("customer"),
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
        routing=_routing(raw_turn),
        response=raw_turn.get("conversation", {}).get("agent"),
        customer_input=raw_turn.get("conversation", {}).get("customer"),
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


def _routing_semantic_scores(
    expected: list[NormalizedTurn],
    observed: list[NormalizedTurn],
    judge_client,
    judge_model: str,
    judge_effort: str | None,
) -> list[float | None]:
    """One RS routing-judge verdict per observed turn (METRICS.md §5), aligned
    to the golden turn with the same turn_id. None (N/A) for any turn with no
    judge client, no expected routing, or a judge-call failure -- never 0.
    Turn calls run concurrently; a cache hit resolves instantly."""
    from concurrent.futures import ThreadPoolExecutor

    from atf_eval.metrics.routing import semantic_routing_score

    ref_by_id = {t.turn_id: t for t in expected}

    def _one(obs: NormalizedTurn) -> float | None:
        ref = ref_by_id.get(obs.turn_id)
        if ref is None:
            return None
        return semantic_routing_score(
            obs.customer_input or ref.customer_input or "",
            ref, obs, judge_client, judge_model, judge_effort,
        )

    if judge_client is None or len(observed) <= 1:
        return [_one(o) for o in observed]
    with ThreadPoolExecutor(max_workers=min(8, len(observed))) as pool:
        return list(pool.map(_one, observed))


def score_components(
    expected: list[NormalizedTurn],
    observed: list[NormalizedTurn],
    judge_client=None,
    judge_model: str = "claude-opus-5",
    judge_effort: str | None = None,
) -> dict:
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

    per_turn_semantic = _routing_semantic_scores(
        expected, observed, judge_client, judge_model, judge_effort
    )
    applicable_semantic = [s for s in per_turn_semantic if s is not None]
    rs_semantic = sum(applicable_semantic) / len(applicable_semantic) if applicable_semantic else None

    group_scores = {
        "nts": nts_conversation(expected, observed),
        "sts": sts_conversation(expected, observed),
        "tis": tis_conversation(expected, observed),
        "rs": rs_conversation(expected, observed, per_turn_semantic_scores=per_turn_semantic),
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
        "rs_semantic": rs_semantic,  # mean LLM routing-judge verdict across applicable turns
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
# LLM / multimodal evaluation (METRICS.md Part B, Groups 1-5)
# ---------------------------------------------------------------------------


def run_llm_evals(runs: list[dict], client, model: str, effort: str | None) -> None:
    """Attach a ConversationLLMReport to each run under run['llm']. Runs are
    processed a few at a time and each conversation fans its own judge calls
    out to a thread pool, so the first full build is I/O-bound rather than
    serial; every subsequent build is served from the on-disk cache."""
    from concurrent.futures import ThreadPoolExecutor

    from atf_eval.llm_evals import build_context, evaluate_conversation

    def _one(run: dict) -> None:
        ctx = build_context(run["scenario"], run["expected"], run["observed"])
        run["llm"] = evaluate_conversation(
            ctx, client, model=model, effort=effort, concurrency=6
        )

    if client is None or len(runs) <= 1:
        for run in runs:
            _one(run)
        return
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(_one, runs))


_LLM_GROUP_TITLES = {
    1: "Group 1 - Response Quality",
    2: "Group 2 - Grounding & Knowledge",
    3: "Group 3 - Safety, Policy & Compliance",
    4: "Group 4 - Conversation Quality",
    5: "Group 5 - Voice / Multimodal",
}


def llm_native_str(scoring_type: str, score) -> str:
    if score is None:
        return "N/A"
    if scoring_type in ("ordinal_1_5", "ordinal_1_5_na"):
        return f"{score}/5"
    if scoring_type == "pass_fail":
        return str(score)
    if scoring_type == "sentiment":
        return f"{score:+d}" if isinstance(score, int) else str(score)
    if scoring_type == "count_severity":
        return f"{score.get('severity','?')} ({score.get('count','?')})" if isinstance(score, dict) else str(score)
    if scoring_type == "count":
        return str(score)
    if scoring_type == "categorical_confidence":
        if isinstance(score, dict):
            conf = score.get("confidence")
            return f"{score.get('category','?')}" + (f" ({conf:.2f})" if isinstance(conf, (int, float)) else "")
        return str(score)
    return str(score)


def _llm_band(normalized: float | None, status: str) -> str:
    if status != "available" or normalized is None:
        return "na"
    if normalized >= 0.95:
        return "good"
    if normalized >= 0.80:
        return "warning"
    if normalized >= 0.50:
        return "serious"
    return "critical"


def write_llm_csv(runs: list[dict], output_dir: Path, timestamp: str) -> Path | None:
    if not any("llm" in r for r in runs):
        return None
    path = output_dir / f"atf_llm_metrics_{timestamp}.csv"
    fields = [
        "golden", "scenario", "deviation_type", "group", "metric_id", "metric_name",
        "level", "scoring_type", "native_score", "normalized_0_1", "status", "reason",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for run in runs:
            report = run.get("llm")
            if report is None:
                continue
            rows = []
            for mid, results in report.turn_results.items():
                rows.extend(results)
            rows.extend(report.overall_results.values())
            for r in rows:
                writer.writerow({
                    "golden": run.get("golden_key", ""),
                    "scenario": run["scenario"],
                    "deviation_type": run["deviation_type"],
                    "group": r.group,
                    "metric_id": r.metric_id + (f"@turn{r.turn_id}" if r.turn_id is not None else ""),
                    "metric_name": r.metric_name,
                    "level": r.level,
                    "scoring_type": r.scoring_type,
                    "native_score": "" if r.score is None else json.dumps(r.score) if isinstance(r.score, dict) else r.score,
                    "normalized_0_1": "" if r.normalized is None else round(r.normalized, 4),
                    "status": r.status,
                    "reason": r.reason,
                })
    return path


def render_llm_metric_row(overall, per_turn: list) -> str:
    native = llm_native_str(overall.scoring_type, overall.score)
    band = _llm_band(overall.normalized, overall.status)
    status_tag = "" if overall.status == "available" else f'<span class="l-status">{overall.status.replace("_", " ")}</span>'
    turn_rows = ""
    shown_turns = [t for t in per_turn if t.turn_id is not None]
    if shown_turns:
        items = "".join(
            f'<div class="l-turn"><span class="l-turn-id">turn {t.turn_id}</span>'
            f'<span class="l-turn-score {_llm_band(t.normalized, t.status)}">{llm_native_str(t.scoring_type, t.score)}</span>'
            f'<span class="l-turn-reason">{(t.reason or "")[:400]}</span></div>'
            for t in shown_turns
        )
        turn_rows = f'<div class="l-turns">{items}</div>'
    return f"""
            <details class="l-metric">
              <summary>
                <span class="l-name">{overall.metric_name}<span class="l-level">{overall.level}</span></span>
                <span class="l-score {band}">{native}</span>
                {status_tag}
              </summary>
              <p class="l-reason">{(overall.reason or "")[:600]}</p>
              {turn_rows}
            </details>"""


def render_llm_panel(idx: int, run: dict) -> str:
    report = run["llm"]
    groups_html = ""
    for g in (1, 2, 3, 4, 5):
        specs = [s for s in _llm_all_specs() if s.group == g]
        rows = ""
        scored_ct = 0
        for spec in specs:
            overall = report.overall_results.get(spec.metric_id)
            if overall is None:
                continue
            per_turn = report.turn_results.get(spec.metric_id, [])
            rows += render_llm_metric_row(overall, per_turn)
            if overall.status == "available":
                scored_ct += 1
        na_note = ""
        if g == 5 and scored_ct == 0:
            na_note = ('<p class="l-group-note">All Group 5 metrics are N/A for these fixtures: the '
                       'canonical trajectory carries no audio or timing evidence (METRICS.md &sect;18). '
                       'The evaluators are implemented and will score the moment an audio-bearing trace is supplied.</p>')
        groups_html += f"""
          <details class="l-group"{' open' if g != 5 else ''}>
            <summary><span class="l-group-title">{_LLM_GROUP_TITLES[g]}</span><span class="l-group-count">{scored_ct}/{len(specs)} scored</span></summary>
            {na_note}{rows}
          </details>"""
    return f"""
      <section id="lpanel-{idx}" class="l-panel">
        <div class="l-panel-card">
          <h3>{run['scenario']}</h3>
          <p class="desc">{run['description'] or 'Golden trajectory scored against itself.'}</p>
          {groups_html}
        </div>
      </section>"""


def _llm_all_specs():
    from atf_eval.llm_evals import ALL_METRICS
    return ALL_METRICS


def render_llm_dashboard(runs: list[dict], golden_summary: str, run_date: str, model: str) -> str:
    runs_with = [r for r in runs if "llm" in r]
    tab_inputs = "".join(
        f'\n      <input type="radio" name="ltabs" id="ltab-{i}" class="l-tab-input"{" checked" if i == 1 else ""}>'
        for i in range(1, len(runs_with) + 1)
    )
    tab_labels = "".join(
        f'\n        <label for="ltab-{i}" class="l-tab-label">{r["scenario"].replace("_", " ").title()}</label>'
        for i, r in enumerate(runs_with, start=1)
    )
    tab_css = "\n  ".join(
        f'#ltab-{i}:checked ~ .l-tab-bar label[for="ltab-{i}"],' for i in range(1, len(runs_with) + 1)
    ).rstrip(",") + " { background: var(--accent); border-color: var(--accent); color: #fff; }"
    panel_css = "\n  ".join(
        f'#ltab-{i}:checked ~ #lpanel-{i},' for i in range(1, len(runs_with) + 1)
    ).rstrip(",") + " { display: block; }"
    panels = "".join(render_llm_panel(i, r) for i, r in enumerate(runs_with, start=1))

    return _LLM_SHELL.replace("{{RUN_DATE}}", run_date).replace("{{MODEL}}", model).replace(
        "{{GOLDEN}}", golden_summary
    ).replace("{{TAB_INPUTS}}", tab_inputs).replace("{{TAB_LABELS}}", tab_labels).replace(
        "{{TAB_ACTIVE_CSS}}", tab_css
    ).replace("{{PANEL_ACTIVE_CSS}}", panel_css).replace("{{PANELS}}", panels)


_LLM_SHELL = """<title>ATF LLM Metrics</title>
<style>
  :root {
    --bg:#f5f7fa; --surface:#fff; --surface-2:#eef1f6; --text:#1b2430; --text-muted:#5b6672;
    --border:#d9dee6; --accent:#3b5bdb;
    --good:#2f9e44; --warning:#f08c00; --serious:#e8590c; --critical:#c92a2a; --na:#868e96;
    --good-bg:#ebfbee; --warning-bg:#fff4e6; --serious-bg:#fff0e6; --critical-bg:#fff5f5; --na-bg:#f1f3f5;
  }
  :root:not([data-theme="light"]) { color-scheme: light dark; }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg:#12151a; --surface:#1b2027; --surface-2:#232a33; --text:#e6e9ee; --text-muted:#9aa4b0;
      --border:#333c47; --accent:#5c7cfa;
      --good-bg:#1e2a1f; --warning-bg:#2b2417; --serious-bg:#2c2017; --critical-bg:#2c1a1a; --na-bg:#232a33;
    }
  }
  :root[data-theme="dark"] {
    --bg:#12151a; --surface:#1b2027; --surface-2:#232a33; --text:#e6e9ee; --text-muted:#9aa4b0;
    --border:#333c47; --accent:#5c7cfa;
    --good-bg:#1e2a1f; --warning-bg:#2b2417; --serious-bg:#2c2017; --critical-bg:#2c1a1a; --na-bg:#232a33;
  }
  body { background:var(--bg); color:var(--text); font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; margin:0; }
  .wrap { max-width:1100px; margin:0 auto; padding:2rem 1.25rem 4rem; }
  h1 { font-size:1.5rem; margin:0 0 .3rem; }
  h3 { font-size:1.1rem; margin:0 0 .2rem; }
  .sub { color:var(--text-muted); font-size:.9rem; margin:0 0 1.5rem; }
  .sub code { background:var(--surface-2); padding:.1rem .35rem; border-radius:4px; }
  .l-tab-input { position:absolute; opacity:0; pointer-events:none; }
  .l-tab-bar { display:flex; flex-wrap:wrap; gap:.4rem; margin-bottom:1.2rem; }
  .l-tab-label { padding:.4rem .8rem; border:1px solid var(--border); border-radius:999px; background:var(--surface);
    font-size:.82rem; cursor:pointer; user-select:none; }
  {{TAB_ACTIVE_CSS}}
  .l-panel { display:none; }
  {{PANEL_ACTIVE_CSS}}
  .l-panel-card { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:1.4rem; }
  .desc { color:var(--text-muted); margin:.2rem 0 1.1rem; }
  .l-group { border:1px solid var(--border); border-radius:9px; margin:.6rem 0; background:var(--surface-2); }
  .l-group > summary { cursor:pointer; padding:.7rem .9rem; display:flex; justify-content:space-between; align-items:center; font-weight:600; }
  .l-group-count { font-weight:400; font-size:.8rem; color:var(--text-muted); }
  .l-group-note { margin:.2rem .9rem .8rem; font-size:.84rem; color:var(--text-muted); }
  .l-metric { border-top:1px solid var(--border); }
  .l-metric > summary { cursor:pointer; padding:.55rem .9rem; display:flex; align-items:center; gap:.6rem; list-style:none; }
  .l-metric > summary::-webkit-details-marker { display:none; }
  .l-name { flex:1; font-weight:500; }
  .l-level { color:var(--text-muted); font-size:.72rem; margin-left:.5rem; text-transform:uppercase; letter-spacing:.03em; }
  .l-score { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.8rem; padding:.15rem .5rem; border-radius:5px; border:1px solid var(--border); }
  .l-score.good{background:var(--good-bg);color:var(--good)} .l-score.warning{background:var(--warning-bg);color:var(--warning)}
  .l-score.serious{background:var(--serious-bg);color:var(--serious)} .l-score.critical{background:var(--critical-bg);color:var(--critical)}
  .l-score.na{background:var(--na-bg);color:var(--na)}
  .l-status { font-size:.72rem; color:var(--na); text-transform:uppercase; letter-spacing:.03em; }
  .l-reason { margin:.1rem .9rem .7rem; font-size:.86rem; color:var(--text-muted); }
  .l-turns { margin:0 .9rem .8rem; display:flex; flex-direction:column; gap:.3rem; }
  .l-turn { display:grid; grid-template-columns:4rem 4rem 1fr; gap:.5rem; align-items:start; font-size:.82rem; }
  .l-turn-id { color:var(--text-muted); }
  .l-turn-score { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
  .l-turn-score.good{color:var(--good)} .l-turn-score.warning{color:var(--warning)}
  .l-turn-score.serious{color:var(--serious)} .l-turn-score.critical{color:var(--critical)} .l-turn-score.na{color:var(--na)}
  .l-turn-reason { color:var(--text-muted); }
  footer { margin-top:2rem; color:var(--text-muted); font-size:.8rem; border-top:1px solid var(--border); padding-top:1rem; }
</style>
<div class="wrap">
  <h1>ATF - LLM &amp; Multimodal Metrics</h1>
  <p class="sub">METRICS.md Part B, Groups 1-5 &middot; judge model <code>{{MODEL}}</code> &middot; {{RUN_DATE}}<br>
  golden: <code>{{GOLDEN}}</code> &middot; native per-metric scoring preserved (METRICS.md &sect;19); the 0-1 colour band is a display aid only.</p>
  {{TAB_INPUTS}}
  <div class="l-tab-bar">{{TAB_LABELS}}</div>
  {{PANELS}}
  <footer>N/A means insufficient evidence for that metric, never a zero (METRICS.md &sect;21). Group 5 is N/A across these
  fixtures because the traces carry no audio/timing evidence. LLM rationale supports auditability but is not itself authoritative (METRICS.md &sect;23).</footer>
</div>
"""


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
    parser.add_argument("--judge-model", default="claude-opus-5",
                        help="Anthropic model for RS's routing judge and the Group 1-5 LLM metrics.")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], default="low",
                        help="Judge model effort (default: low -- fine for rubric scoring).")
    parser.add_argument("--no-routing-judge", action="store_true",
                        help="Skip RS's LLM routing judge -- RS reports N/A instead.")
    parser.add_argument("--no-llm-evals", action="store_true",
                        help="Skip the Group 1-5 LLM/multimodal metrics and their dashboard.")
    args = parser.parse_args()

    golden_dir = Path(args.golden_dir)
    scenarios_dir = Path(args.scenarios)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # One judge client for both RS and the Group 1-5 metrics. None -> those
    # dimensions report N/A (never 0); every deterministic metric is unaffected.
    judge_client = None
    if not (args.no_routing_judge and args.no_llm_evals):
        from atf_eval.llm_evals import get_judge_client
        judge_client = get_judge_client()
        if judge_client is None:
            print("[info] no ANTHROPIC_API_KEY (checked env + repo .env) -- RS and Group 1-5 "
                  "LLM metrics will report N/A", file=sys.stderr)

    rs_client = None if args.no_routing_judge else judge_client

    goldens = discover_goldens(golden_dir)
    if not goldens:
        raise SystemExit(f"No golden *.json files found in {golden_dir}")
    runs = discover_runs(goldens, scenarios_dir)
    for run in runs:
        run["metrics"] = score_components(
            run["expected"], run["observed"], rs_client, args.judge_model, args.effort
        )
    annotate_notes(runs)

    if not args.no_llm_evals:
        print("[info] running Group 1-5 LLM/multimodal metrics "
              f"({'judge=' + args.judge_model if judge_client else 'no client -> all N/A'}) ...",
              file=sys.stderr)
        run_llm_evals(runs, judge_client, args.judge_model, args.effort)

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

    llm_csv = write_llm_csv(runs, output_dir, timestamp)
    if llm_csv is not None:
        llm_dashboard_html = render_llm_dashboard(runs, golden_summary, run_date, args.judge_model)
        llm_dashboard_path = output_dir / f"atf_llm_dashboard_{timestamp}.html"
        llm_dashboard_path.write_text(llm_dashboard_html, encoding="utf-8")
        print(f"  {llm_csv}")
        print(f"  {llm_dashboard_path}")

    for run in runs:
        m = run["metrics"]
        print(f"[{run.get('golden_key', '')}] {run['scenario']}: ATF={fmt(m['atf'])} NTS={fmt(m['nts_overall'])} "
              f"STS={fmt(m['sts_overall'])} TIS={fmt(m['tis_overall'])} "
              f"RS={fmt(m['rs_overall'])} OS={fmt(m['os_overall'])}")
        if "llm" in run:
            report = run["llm"]
            avail = sum(1 for r in report.all_results() if r.status == "available")
            print(f"    LLM: {avail} metric-results scored, "
                  f"{sum(1 for r in report.overall_results.values() if r.status == 'available')}/"
                  f"{len(report.overall_results)} overall metrics")


if __name__ == "__main__":
    main()
