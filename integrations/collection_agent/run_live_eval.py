"""Run atf_eval against the real collection_agent for a golden-dataset
subset, one conversation at a time with incremental checkpointing (so a long
run survives interruption and progress is visible in the log), then restore
the live agent's data files no matter what happens.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from atf_eval.aggregate import DEFAULT_WEIGHTS
from atf_eval.dataset import group_by_conversation, load_dataset
from atf_eval.report import aggregate, write_reports
from atf_eval.runner import run_evaluation

from collection_agent_adapter import CollectionAgentAdapter

DATASET = Path(__file__).parent / "golden_subset.jsonl"
OUTPUT_DIR = Path(__file__).parent / "results"


def main() -> None:
    turns = load_dataset(str(DATASET))
    conversations = group_by_conversation(turns)
    total = len(conversations)
    print(f"[info] {total} conversations to evaluate", flush=True)

    adapter = CollectionAgentAdapter()
    results = []
    try:
        for i, (conversation_id, conv_turns) in enumerate(conversations.items(), start=1):
            start = time.monotonic()
            try:
                conv_results = run_evaluation(
                    {conversation_id: conv_turns}, adapter, weights=DEFAULT_WEIGHTS, concurrency=1
                )
            except Exception as e:  # noqa: BLE001 - keep going, one bad conversation shouldn't kill the batch
                print(f"[ERROR] {conversation_id} crashed: {e}", flush=True)
                continue
            elapsed = time.monotonic() - start
            results.extend(conv_results)
            r = conv_results[0]
            print(
                f"[{i}/{total}] {conversation_id} ({elapsed:.0f}s) atf={r.atf} "
                f"coverage={r.metric_coverage:.0%} nts={r.nts} sts={r.sts} tis={r.tis} rs={r.rs} os={r.os}",
                flush=True,
            )
            # checkpoint after every conversation
            write_reports(results, str(OUTPUT_DIR))
    finally:
        adapter.restore_data_files()
        print("[info] live agent data files restored to original contents", flush=True)

    json_path, csv_path = write_reports(results, str(OUTPUT_DIR))
    summary = aggregate(results)

    print("\n=== ATF Evaluation Summary (live collection_agent) ===")
    print(f"Conversations: {summary['total_conversations']}  Turns: {summary['total_turns']}")
    print(f"ATF score: {summary['atf']['score']}  coverage: {summary['atf']['coverage']:.1%}")
    for key, group in summary["groups"].items():
        print(f"  {key.upper():4s} {group['score']}  ({group['status']})")

    print(f"\nReports written to:\n  {json_path}\n  {csv_path}")


if __name__ == "__main__":
    main()
