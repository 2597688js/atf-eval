from __future__ import annotations

import argparse
import json
import os
import sys

import anthropic

from atf_eval.aggregate import DEFAULT_WEIGHTS
from atf_eval.dataset import group_by_conversation, load_dataset
from atf_eval.loader import load_adapter
from atf_eval.report import aggregate, render_results_table, write_reports
from atf_eval.runner import run_evaluation


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atf-eval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Evaluate an agent against a golden dataset")
    run_parser.add_argument("--dataset", required=True, help="Golden dataset JSONL path")
    run_parser.add_argument("--adapter", required=True, help="module.path:ClassName")
    run_parser.add_argument("--output-dir", default="./results")
    run_parser.add_argument("--weights-file", default=None, help="JSON override of {nts,sts,tis,rs,os} weights")
    run_parser.add_argument("--tool-arg-tolerance", type=float, default=0.0)
    run_parser.add_argument("--limit", type=int, default=None, help="Only evaluate the first N conversations")
    run_parser.add_argument("--concurrency", type=int, default=1)
    run_parser.add_argument(
        "--judge-model",
        default="claude-opus-5",
        help="Anthropic model for RS's routing judge (METRICS.md §5)",
    )
    run_parser.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        default=None,
        help="Routing judge model effort (model-dependent)",
    )
    run_parser.add_argument(
        "--no-routing-judge",
        action="store_true",
        help="Skip the LLM routing judge entirely -- RS reports N/A for every conversation instead",
    )

    report_parser = subparsers.add_parser(
        "report", help="Print the per-conversation results table from a saved report.json"
    )
    report_parser.add_argument("path", help="Path to a report_<timestamp>.json written by `atf-eval run`")

    return parser


def _print_summary(summary: dict) -> None:
    print("=== ATF Evaluation Summary ===")
    print(f"Conversations:   {summary['total_conversations']}")
    print(f"Turns:           {summary['total_turns']}")
    atf = summary["atf"]
    atf_score_str = f"{atf['score']:.3f}" if atf["score"] is not None else "N/A"
    print(f"\nATF score:       {atf_score_str}")
    print(f"Metric coverage: {atf['coverage']:.1%}")
    print("\nMetric groups (mean):")
    for key, group in summary["groups"].items():
        score_str = f"{group['score']:.3f}" if group["score"] is not None else "N/A"
        print(f"  {key.upper():4s} {score_str:>8s}  ({group['status']})")


def cmd_run(args: argparse.Namespace) -> int:
    turns = load_dataset(args.dataset)
    conversations = group_by_conversation(turns)

    if args.limit is not None:
        conversations = dict(list(conversations.items())[: args.limit])

    adapter = load_adapter(args.adapter)

    weights = DEFAULT_WEIGHTS
    if args.weights_file:
        with open(args.weights_file, encoding="utf-8") as f:
            weights = json.load(f)

    judge_client = None
    if not args.no_routing_judge:
        if os.environ.get("ANTHROPIC_API_KEY"):
            judge_client = anthropic.Anthropic()
        else:
            print(
                "[info] ANTHROPIC_API_KEY not set -- RS will report N/A "
                "(pass --no-routing-judge to silence this, or set the key to enable it)",
                file=sys.stderr,
            )

    results = run_evaluation(
        conversations,
        adapter,
        weights=weights,
        concurrency=args.concurrency,
        tolerance=args.tool_arg_tolerance,
        judge_client=judge_client,
        judge_model=args.judge_model,
        judge_effort=args.effort,
    )

    json_path, csv_path = write_reports(results, args.output_dir)
    _print_summary(aggregate(results))
    print("\nPer-conversation results:\n")
    print(render_results_table([
        {
            "conversation_id": r.conversation_id,
            "atf": r.atf,
            "metric_coverage": r.metric_coverage,
            "nts": r.nts,
            "sts": r.sts,
            "tis": r.tis,
            "rs": r.rs,
            "os": r.os,
        }
        for r in results
    ]))
    print(f"\nReports written to:\n  {json_path}\n  {csv_path}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    with open(args.path, encoding="utf-8") as f:
        report = json.load(f)
    print(render_results_table(report["conversations"]))
    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "run":
        sys.exit(cmd_run(args))
    if args.command == "report":
        sys.exit(cmd_report(args))
    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
