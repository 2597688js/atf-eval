"""LLM judge plumbing shared by every Group 1-5 metric.

One entry point, `judge_structured()`, that:
  - loads ANTHROPIC_API_KEY from a `.env` if it isn't already exported (dev
    convenience -- the deterministic pipeline never needs a key);
  - returns a cached response when one exists (cache.py), otherwise makes
    exactly one `client.messages.parse` structured-output call and records it;
  - raises `JudgeUnavailable` (never a bare score) when there is no client or
    the call fails, so a metric can degrade to N/A per METRICS.md §21 rather
    than to a false 0.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from atf_eval.llm_evals import cache

# Checked in order, first match wins. Current working directory first: when
# atf_eval is consumed as a dependency (pip install -e ./atf-eval from inside
# your own project), `.env` belongs at *your* project root, where you run
# `atf-eval dashboard` from -- not inside the atf-eval package checkout,
# which is wherever __file__ happens to resolve to and may not even be
# writable (an installed, non-editable package). The package-root path is
# kept as a fallback for this repo's own local dev workflow.
def _dotenv_candidates() -> list[Path]:
    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[3] / ".env"]
    seen: list[Path] = []
    for p in candidates:
        if p not in seen:
            seen.append(p)
    return seen


T = TypeVar("T", bound=BaseModel)


class JudgeUnavailable(RuntimeError):
    """No usable judge client, or the judge call failed. The caller turns
    this into an N/A metric result, not a zero."""


def _load_dotenv_key() -> None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    for env_path in _dotenv_candidates():
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name, value = name.strip(), value.strip().strip('"').strip("'")
            if name == "ANTHROPIC_API_KEY" and value:
                os.environ["ANTHROPIC_API_KEY"] = value
                return


def get_judge_client() -> anthropic.Anthropic | None:
    """An Anthropic client if a key is reachable, else None (LLM metrics then
    report N/A). Reads a `.env` in the current directory (falling back to
    the atf_eval package root) as a fallback."""
    _load_dotenv_key()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        return anthropic.Anthropic()
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] could not construct Anthropic client: {e}", file=sys.stderr)
        return None


def judge_structured(
    client: anthropic.Anthropic | None,
    *,
    system: str,
    user: str,
    output_model: type[T],
    model: str = "claude-opus-5",
    effort: str | None = None,
    max_tokens: int = 1024,
) -> T:
    schema_name = f"{output_model.__module__}.{output_model.__qualname__}"
    ck = cache.key(model=model, effort=effort, system=system, user=user, schema=schema_name)

    hit = cache.load(ck)
    if hit is not None:
        return output_model.model_validate(hit["parsed"])

    if client is None:
        raise JudgeUnavailable("no judge client (ANTHROPIC_API_KEY not set)")

    parse_kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        output_format=output_model,
        messages=[{"role": "user", "content": user}],
    )
    if effort:
        parse_kwargs["output_config"] = {"effort": effort}

    try:
        response = client.messages.parse(**parse_kwargs)
    except Exception as e:  # noqa: BLE001 - any transport/parse error -> N/A, not 0
        raise JudgeUnavailable(f"judge call failed: {e}") from e

    parsed = getattr(response, "parsed_output", None)
    if parsed is None:
        raise JudgeUnavailable("judge returned no parseable structured output")

    cache.store(ck, {"parsed": parsed.model_dump(mode="json"), "schema": schema_name})
    return parsed
