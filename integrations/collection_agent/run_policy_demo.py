"""Run ATF + Policy Compliance together against one live collection_agent
conversation, then print the combined scorecard.
"""
from __future__ import annotations

import json
from pathlib import Path

from atf_eval.aggregate import DEFAULT_WEIGHTS
from atf_eval.dataset import group_by_conversation, load_dataset
from atf_eval.policy.checker import evaluate_conversation
from atf_eval.runner import run_evaluation
from atf_eval.scorecard import render_scorecard

from collection_agent_adapter import CollectionAgentAdapter
from collection_agent_policy_rules import RULES

DATASET = Path(__file__).parent / "policy_demo_dataset.jsonl"
RAW_GOLDEN = Path(
    "/Users/janarddan/1.jana files/3.MyMacProjects/easy_agents/agents/collection_agent"
    "/eval_dataset/collection_agent_golden_dataset_v3.jsonl"
)
SCRIPT_ID = "COLL_TRAJ_0501"


def load_policy_context(script_id: str) -> dict:
    with RAW_GOLDEN.open(encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            if obj["script_id"] == script_id:
                return {"policy": obj["context"]["policy"], "category": obj["category"]}
    raise SystemExit(f"{script_id} not found in raw golden dataset")


def main() -> None:
    turns = load_dataset(str(DATASET))
    conversations = group_by_conversation(turns)
    context = load_policy_context(SCRIPT_ID)

    adapter = CollectionAgentAdapter()
    try:
        results = run_evaluation(conversations, adapter, weights=DEFAULT_WEIGHTS, concurrency=1)
    finally:
        adapter.restore_data_files()
        print("[info] live agent data files restored to original contents")

    conv = results[0]
    policy_result = evaluate_conversation(conv.observed_turns, RULES, context)

    print(f"\n[debug] policy context: {context['policy']}")
    print(f"[debug] observed tool calls across conversation: "
          f"{[tc.tool_id for t in conv.observed_turns for tc in t.tool_calls]}")

    print("\n" + render_scorecard(f"Collections — {context['category']} ({SCRIPT_ID})", conv, policy_result))


if __name__ == "__main__":
    main()
