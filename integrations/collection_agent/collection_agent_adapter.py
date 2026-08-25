"""ATF TrajectoryAgent adapter for the real `collection_agent` in easy_agents.

This is a genuine bridge between two independently-designed systems, not a
mechanical field rename:

  - The golden dataset (collection_agent_golden_dataset_v3.jsonl) is a purely
    synthetic generator's own vocabulary (e.g. `verification_status`) that
    does not exist as a literal state key in the live agent.
  - The live agent's per-customer-turn trace spans multiple internal "hops"
    (self-routing, discount handoff, loop guard), each with its own
    hop-scoped `node_history`, so one golden turn's node sequence must be
    reconstructed by concatenating hops.
  - Tool-call evidence lives in a session-cumulative `observations` list
    (bounded to the last 40), so a turn's own tool calls are found by
    diffing the observation count before/after the turn.
  - There is no single "outcome" field in live state; it's inferred from
    which outcome-signaling tool fired combined with current state flags.

Every value derived (rather than read verbatim) is marked
`source="reconstructed"` per ATF spec §6.1.

Data seeding: the golden dataset's customer/case/policy fixtures are NOT
present in the live agent's static `data/*.json` files. This adapter backs
those files up in memory once, and before starting each new conversation,
temporarily overwrites them so that conversation's customer is `data[0]`
(the live runtime always maps the first customer row to `user_code="user_a"`).
Call `.restore_data_files()` when done (see run_live_eval.py) to put the
original fixture files back exactly as they were.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

EASY_AGENTS_ROOT = Path("/Users/janarddan/1.jana files/3.MyMacProjects/easy_agents")
COLLECTION_AGENT_DIR = EASY_AGENTS_ROOT / "agents" / "collection_agent"
DATA_DIR = COLLECTION_AGENT_DIR / "data"
RUNTIME_DIR = COLLECTION_AGENT_DIR / "runtime"

for p in (str(EASY_AGENTS_ROOT), str(EASY_AGENTS_ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from agents.collection_agent.ui.server import CollectionDebugRuntime  # noqa: E402

from atf_eval.normalized import (  # noqa: E402
    NormalizedNode,
    NormalizedTurn,
    Outcome,
    Routing,
    StateChange,
    ToolCall,
)

_DATA_FILES = {
    "customer": "customers.json",
    "case": "cases.json",
    "customer_profile": "customer_profile.json",
    "payment_history": "payment_history.json",
    "offer_history": "offer_history.json",
    "policy": "policies.json",
    "assistance_programs": "assistance_programs.json",
}

_STATE_DIRECT_KEYS = [
    "customer_payment_posture",
    "discount_stage",
    "identity_verified",
    "verified_dob",
    "verified_mobile",
    "hardship_context",
]

_OUTCOME_TOOL_MAP = {
    "payment_link_create": "payment_link_sent",
    "promise_capture": "promise_captured",
    "human_escalation": "human_escalation_requested",
    "installment_discount_apply": "discount_accepted",
    "outbound_callback_schedule": "followup_scheduled",
    "premium_hold_create": "premium_hold_created",
}


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _derive_verification_status(state: dict) -> str:
    if state.get("identity_verified"):
        return "verified"
    verified = state.get("verification_verified_fields") or []
    missing = state.get("verification_missing_fields") or []
    if verified and missing:
        return "in_progress"
    if verified and not missing:
        return "verified"
    return "not_started"


class CollectionAgentAdapter:
    def __init__(self) -> None:
        self._original_files: dict[str, str] = {
            key: (DATA_DIR / fname).read_text(encoding="utf-8") for key, fname in _DATA_FILES.items()
        }
        # runtime/ carries persistent memory keyed by user identity (user_a/b/c),
        # not by session_id -- a fresh session for a golden script's customer
        # otherwise inherits whatever history exists from *any* prior use of
        # that user_code (including cross-contamination between our own
        # conversations, since every script maps to the same "user_a"). Back
        # up the true original tree for final restore, then wipe it -- every
        # runtime/*.json store self-initializes to "[]" when missing, and the
        # memory repository self-initializes similarly, so this is safe.
        self._runtime_backup_dir = Path(tempfile.mkdtemp(prefix="atf_collection_runtime_backup_"))
        shutil.copytree(RUNTIME_DIR, self._runtime_backup_dir, dirs_exist_ok=True)
        self._reset_runtime_dir()

        self._golden_by_script: dict[str, dict] = self._load_golden_scripts()

        self.runtime = CollectionDebugRuntime.create(COLLECTION_AGENT_DIR)

        self._session_by_conversation: dict[str, str] = {}
        self._prev_state_by_conversation: dict[str, dict] = {}
        self._prev_observation_count: dict[str, int] = {}
        self._verified_seen: dict[str, bool] = {}

    def _load_golden_scripts(self) -> dict[str, dict]:
        source = (
            EASY_AGENTS_ROOT
            / "agents/collection_agent/eval_dataset/collection_agent_golden_dataset_v3.jsonl"
        )
        scripts: dict[str, dict] = {}
        with source.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                scripts[obj["script_id"]] = obj
        return scripts

    def _reset_runtime_dir(self) -> None:
        shutil.rmtree(RUNTIME_DIR, ignore_errors=True)
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    def restore_data_files(self) -> None:
        for key, fname in _DATA_FILES.items():
            (DATA_DIR / fname).write_text(self._original_files[key], encoding="utf-8")

        shutil.rmtree(RUNTIME_DIR, ignore_errors=True)
        shutil.copytree(self._runtime_backup_dir, RUNTIME_DIR)
        shutil.rmtree(self._runtime_backup_dir, ignore_errors=True)

    def _seed_for_conversation(self, conversation_id: str) -> None:
        script = self._golden_by_script[conversation_id]
        ctx = script["context"]
        for key, fname in _DATA_FILES.items():
            existing = _load(DATA_DIR / fname)
            fixture = ctx[key]
            path = DATA_DIR / fname
            # put this script's fixture first so it maps to user_code="user_a"
            path.write_text(json.dumps([fixture, *existing]), encoding="utf-8")

    def _ensure_session(self, conversation_id: str) -> str:
        if conversation_id in self._session_by_conversation:
            return self._session_by_conversation[conversation_id]

        if self._session_by_conversation:
            # a prior conversation already ran under the same fixed user_code
            # identity ("user_a") -- reset memory so this script starts clean
            self._reset_runtime_dir()
            self.runtime = CollectionDebugRuntime.create(COLLECTION_AGENT_DIR)

        self._seed_for_conversation(conversation_id)
        session_id = f"atf-{conversation_id}"
        self.runtime.start_conversation(
            SimpleNamespace(user_code="user_a", session_id=session_id, soft_cap=10, hard_cap=50)
        )
        self._session_by_conversation[conversation_id] = session_id
        self._prev_state_by_conversation[conversation_id] = {}
        self._prev_observation_count[conversation_id] = 0
        self._verified_seen[conversation_id] = False
        return session_id

    def run_turn(
        self,
        conversation_id: str,
        turn_id: int,
        user_input: str,
        history: list[NormalizedTurn],
    ) -> NormalizedTurn:
        session_id = self._ensure_session(conversation_id)

        result = self.runtime.run_turn(
            SimpleNamespace(
                message=user_input,
                session_id=session_id,
                sender="customer",
                soft_cap=10,
                hard_cap=50,
                timeout_seconds=120.0,
            )
        )

        hops = result.get("hops", [])
        node_ids: list[str] = []
        for hop in hops:
            node_ids.extend(hop.get("node_history", []))

        final_state: dict = hops[-1]["state"] if hops else result.get("final_state", {}) or {}

        prev_state = self._prev_state_by_conversation[conversation_id]
        state_changes = self._diff_state(prev_state, final_state)
        self._prev_state_by_conversation[conversation_id] = final_state
        if final_state.get("identity_verified"):
            self._verified_seen[conversation_id] = True

        # "observations" is a generic multi-purpose reasoning-checkpoint bag
        # (plan reviews, reflection feedback, tool calls all mixed together).
        # "tool_observations_history" is the properly filtered, tool-call-only
        # accumulator (agent.py:_persist_tool_observation_history only appends
        # entries with a non-empty tool_name).
        tool_history = final_state.get("tool_observations_history") or []
        prev_count = self._prev_observation_count[conversation_id]
        new_observations = tool_history[prev_count:] if len(tool_history) >= prev_count else tool_history
        self._prev_observation_count[conversation_id] = len(tool_history)
        tool_calls = [
            ToolCall(tool_id=obs.get("tool_name", ""), arguments=obs.get("input", {}) or {})
            for obs in new_observations
        ]

        # discount decisions don't go through tool_execution/tool_observations_history
        # at all -- they're a separate handoff to DiscountPlanningAgent.run(), captured
        # per-hop in hop_payload["discount_handoff"]. Surface it as a synthetic tool
        # call so TIS/Policy Compliance have something to see.
        for hop in hops:
            handoff = hop.get("discount_handoff")
            if isinstance(handoff, dict) and isinstance(handoff.get("recommendation"), dict):
                offer = handoff["recommendation"].get("recommended_offer", {}) or {}
                tool_calls.append(
                    ToolCall(
                        tool_id="discount_planning_handoff",
                        arguments={
                            "offer_type": offer.get("offer_type"),
                            "discount_pct": offer.get("waiver_pct"),
                            "tenure_months": offer.get("tenure_months"),
                        },
                    )
                )

        target = str(result.get("final_target") or (hops[-1].get("response_target") if hops else "customer"))
        path = None
        plan_proposal = final_state.get("plan_proposal")
        if isinstance(plan_proposal, dict):
            path = plan_proposal.get("conversation_objective")

        outcome = self._infer_outcome(conversation_id, final_state, new_observations)

        # this agent's trace gives a turn-level state diff, not true per-node
        # causal attribution -- attach it to the last node as a fallback, the
        # same convention the golden dataset side uses (dataset.py), so STS's
        # node-level alignment (METRICS.md §3, Frozen Rule #6) has something
        # real to compare rather than silently seeing empty node state on the
        # observed side.
        nodes = [NormalizedNode(node_id=n) for n in node_ids]
        if nodes and state_changes:
            nodes[-1].state_changes = list(state_changes)

        response_text = str(result.get("final_response") or (hops[-1].get("response") if hops else "")) or None

        return NormalizedTurn(
            conversation_id=conversation_id,
            turn_id=turn_id,
            nodes=nodes,
            state_changes=state_changes,
            tool_calls=tool_calls,
            routing=Routing(path=path, target=target),
            outcome=outcome,
            response=response_text,
        )

    def _diff_state(self, prev: dict, curr: dict) -> list[StateChange]:
        changes: list[StateChange] = []
        for key in _STATE_DIRECT_KEYS:
            old, new = prev.get(key), curr.get(key)
            if old != new:
                changes.append(StateChange(key=key, old=old, new=new, source="explicit"))

        old_status = _derive_verification_status(prev) if prev else None
        new_status = _derive_verification_status(curr)
        if old_status != new_status:
            changes.append(
                StateChange(key="verification_status", old=old_status, new=new_status, source="reconstructed")
            )
        return changes

    def _infer_outcome(
        self, conversation_id: str, state: dict, new_observations: list[dict]
    ) -> Outcome | None:
        for obs in new_observations:
            tool_name = obs.get("tool_name", "")
            if tool_name not in _OUTCOME_TOOL_MAP:
                continue
            outcome_id = _OUTCOME_TOOL_MAP[tool_name]
            if tool_name == "promise_capture" and self._verified_seen.get(conversation_id):
                outcome_id = "verification_success_promise"
            return Outcome(
                id=outcome_id,
                attributes={"response_target": str(state.get("response_target", "customer"))},
            )
        return None
