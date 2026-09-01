#!/usr/bin/env python3
"""Reopen a COMPLETED topic for a scheduled or manually-triggered refresh
(see docs/operations.md's `topic_refresh` entry and `research-loops refresh`).

Completion here is a hard, obligation-based gate (see `semantic-state.py`'s
`TERMINAL_DISPOSITIONS`) -- leaving every obligation untouched on reopen
would let an agent trivially re-declare DONE on the very next check without
looking at anything. So every mode below actually reopens or adds at least
one obligation; they differ only in how much of the topic's existing
obligation set gets re-examined:

  light    -- appends exactly one new, system-generated obligation asking
              the agent to check for new information/material since the
              last completion. Nothing existing is touched.
  continue -- resets every obligation whose disposition is "supported" back
              to "open" (these are the claims that could plausibly have
              gone stale); "contradicted"/"unresolved"/"deferred"
              obligations are settled non-findings and are left alone.
              evidence_refs are left in place so the agent reviews prior
              citations first rather than re-researching from zero. Falls
              back to `light`'s single-obligation append if the topic has
              no "supported" obligations, so this mode never degenerates
              into a no-op.
  full     -- the same reset as `continue`, applied to every obligation
              regardless of disposition -- a genuine do-over of the whole
              contract.

This script never decides *whether* a topic should refresh (that's the
queue's `topic_refresh`/`refresh_due_at` scheduling, or an operator running
`research-loops refresh` by hand) -- it only performs the mechanical edit
once that decision has already been made, the same division of
responsibility `gap-policy.py` has for scope growth.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SEMANTIC_STATE_PATH = Path(__file__).resolve().parent / "semantic-state.py"
_spec = importlib.util.spec_from_file_location("semantic_state", _SEMANTIC_STATE_PATH)
assert _spec is not None and _spec.loader is not None
semantic_state = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(semantic_state)

MODES = ("light", "continue", "full")
LIGHT_CHECK_TEXT = (
    "Check for new information or material relevant to this topic that did "
    "not exist as of the previous completion (see PROGRESS.md and "
    "SOURCE-LEDGER.md for what's already covered); report new findings "
    "with proper citations, or confirm nothing material has changed."
)
LIGHT_CHECK_SOURCE_REF = "scheduled-refresh"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _append_decision(topic_dir: Path, row_id: str, note: str) -> None:
    path = topic_dir / "DECISIONS-LOG.md"
    row = f"| {row_id} | {datetime.now(timezone.utc).date().isoformat()} | {note} |\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(row)


def _reset_obligation(ob: dict[str, Any]) -> None:
    ob["disposition"] = "open"
    ob["confidence"] = None
    ob["counterevidence_reviewed"] = False
    ob["acceptance_summary"] = None
    ob["counterevidence_summary"] = None
    ob["gap_state"] = f"reopened for refresh: {ob['id']}"


def _append_light_check(topic_dir: Path, stamp: str) -> int:
    semantic_state.append_obligation(
        topic_dir, f"refresh-{stamp}", LIGHT_CHECK_TEXT, LIGHT_CHECK_SOURCE_REF
    )
    return 1


def apply(topic_dir: Path, mode: str) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"unknown refresh mode {mode!r}, expected one of {MODES}")
    stamp = _stamp()
    fell_back_to_light = False

    if mode == "light":
        touched = _append_light_check(topic_dir, stamp)
    else:
        state_path = topic_dir / "SEMANTIC-STATE.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        obligations = state.get("obligations", [])
        touched = 0
        for ob in obligations:
            if mode == "full" or ob.get("disposition") == "supported":
                _reset_obligation(ob)
                touched += 1
        if touched:
            state_path.write_text(
                json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        else:
            touched = _append_light_check(topic_dir, stamp)
            fell_back_to_light = True

    semantic_state.rehash(topic_dir)

    # The STOP file records the completion this refresh is deliberately
    # reopening -- leave it and run-topic.sh refuses the very next iteration
    # (exit 3 -> needs_attention), making every refreshed topic dead on
    # arrival. Removing it is part of the reopen edit itself, not cleanup.
    stop_path = topic_dir / "STOP"
    stop_removed = stop_path.exists()
    if stop_removed:
        stop_path.unlink()

    note = f"[system] REFRESH-{mode}: reopened/added {touched} obligation(s)"
    if fell_back_to_light:
        note += " (fell back to light: no supported obligations to reopen)"
    if stop_removed:
        note += "; cleared prior STOP"
    _append_decision(topic_dir, f"REFRESH-{mode}-{stamp}", note)

    return {
        "mode": mode,
        "obligations_touched": touched,
        "fell_back_to_light": fell_back_to_light,
        "stop_removed": stop_removed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    apply_p = sub.add_parser(
        "apply", help="reopen a completed topic's obligations for a scheduled refresh"
    )
    apply_p.add_argument("topic_dir", type=Path)
    apply_p.add_argument("mode", choices=MODES)

    args = parser.parse_args(argv)
    if args.action == "apply":
        try:
            summary = apply(args.topic_dir, args.mode)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"refresh-policy: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
