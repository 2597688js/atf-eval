"""One-off converter: collection_agent_golden_dataset_v3.jsonl (synthetic,
scripted schema) -> atf_eval's GoldenTurn JSONL (normalized schema).

Selects the first N script_ids per category (broad coverage across all 22
categories) rather than converting the full 1000-script dataset.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

SOURCE = Path(
    "/Users/janarddan/1.jana files/3.MyMacProjects/easy_agents/agents/collection_agent"
    "/eval_dataset/collection_agent_golden_dataset_v3.jsonl"
)
OUTPUT = Path(__file__).parent / "golden_subset.jsonl"

PER_CATEGORY = 1


def _routing_from_nodes(nodes_traversed: list[dict]) -> dict | None:
    for node in nodes_traversed:
        if node["node"] == "plan_proposal_directive":
            out = node.get("expected_output", {})
            return {"path": out.get("conversation_objective"), "target": out.get("response_target")}
    for node in nodes_traversed:
        if node["node"] == "relevant_response":
            out = node.get("expected_output", {})
            return {"path": None, "target": out.get("response_target")}
    return None


def convert_script(script: dict) -> list[dict]:
    conversation_id = script["script_id"]
    turns = script["conversation"]
    out_rows = []
    for i, turn in enumerate(turns):
        is_last = i == len(turns) - 1
        row = {
            "conversation_id": conversation_id,
            "turn_id": turn["turn_id"],
            "user_input": turn.get("customer", ""),
            "nodes": [{"node_id": n["node"]} for n in turn.get("nodes_traversed", [])],
            "state_changes": [
                {"key": key, "old": change.get("old"), "new": change.get("new")}
                for key, change in turn.get("state_transitions", {}).items()
            ],
            "tool_calls": [
                {"tool_id": tc["tool"], "arguments": tc.get("input", {})}
                for tc in turn.get("tool_calls", [])
            ],
            "routing": _routing_from_nodes(turn.get("nodes_traversed", [])),
            "outcome": None,
            "metadata": {"category": script.get("category"), "difficulty": script.get("difficulty")},
        }
        if is_last:
            row["outcome"] = {
                "id": script.get("expected_outcome"),
                "attributes": {"response_target": script.get("expected_response_target")},
                "required_conditions": [],
            }
        out_rows.append(row)
    return out_rows


def select_scripts(per_category: int, categories: set[str] | None = None) -> list[dict]:
    seen_per_category: dict[str, int] = defaultdict(int)
    selected: list[dict] = []
    with SOURCE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            script = json.loads(line)
            category = script.get("category", "")
            if categories is not None and category not in categories:
                continue
            if seen_per_category[category] < per_category:
                selected.append(script)
                seen_per_category[category] += 1
    return selected


def list_categories() -> None:
    counts: dict[str, int] = defaultdict(int)
    with SOURCE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                counts[json.loads(line).get("category", "")] += 1
    for category, count in sorted(counts.items()):
        print(f"{count:4d}  {category}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-category", type=int, default=PER_CATEGORY)
    parser.add_argument(
        "--categories",
        type=str,
        default=None,
        help="Comma-separated category names to include (default: all 22). "
        'e.g. --categories "Pay Now,Bad Actor,Human Escalation"',
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="Print all category names + counts and exit (don't convert anything).",
    )
    args = parser.parse_args()

    if args.list_categories:
        list_categories()
        return

    requested_categories = None
    if args.categories:
        requested_categories = {c.strip() for c in args.categories.split(",")}

    scripts = select_scripts(args.per_category, requested_categories)

    found_categories = {s["category"] for s in scripts}
    if requested_categories is not None:
        missing = requested_categories - found_categories
        if missing:
            raise SystemExit(f"category name(s) not found in the dataset: {sorted(missing)}")

    rows: list[dict] = []
    for script in scripts:
        rows.extend(convert_script(script))

    with OUTPUT.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    print(
        f"wrote {len(rows)} turns across {len(scripts)} conversations "
        f"({len(found_categories)} categories, {args.per_category}/category) -> {OUTPUT}"
    )
    print("script_ids:", [s["script_id"] for s in scripts])


if __name__ == "__main__":
    main()
