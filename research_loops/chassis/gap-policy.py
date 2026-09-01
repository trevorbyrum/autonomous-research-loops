#!/usr/bin/env python3
"""Apply the operator's chosen gap-handling policy for one topic.

See CONTRACT-CORE.md's governance section and docs/topic-authoring.md's
"Ongoing gap-filling" section for the full rule. Default policy is always
`review`: an agent may only append a PROPOSAL row to DECISIONS-LOG.md, and an
operator promotes it by hand (or with `promote` below). `auto` is an
explicit, bounded, fully-audited opt-in an operator sets via the repo config
(see research_loops/config.py) or a queue item's agent_main/gap_policy
fields — it lets an agent self-promote up to gap_auto_limit gaps since the
last operator review before it must fall back to proposing only.

This script never decides policy; it only (a) counts how much of an already
agreed auto-budget has been used, and (b) performs the exact mechanical edit
an operator does "by hand" today (append an obligation to TOPIC.md and
SEMANTIC-STATE.json, then rehash) so both the reviewed and the auto path go
through one auditable, hash-consistent action instead of two.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SEMANTIC_STATE_PATH = Path(__file__).resolve().parent / "semantic-state.py"
_spec = importlib.util.spec_from_file_location("semantic_state", _SEMANTIC_STATE_PATH)
assert _spec is not None and _spec.loader is not None
semantic_state = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(semantic_state)

AUTO_MARKER = "AUTO-PROMOTED"
REVIEWED_MARKER = "PROMOTED"
RESET_MARKER = "GAP-REVIEW-RESET"


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _decisions_log_text(topic_dir: Path) -> str:
    try:
        return (topic_dir / "DECISIONS-LOG.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def auto_promotions_used(topic_dir: Path) -> int:
    """Count AUTO-PROMOTED rows since the most recent GAP-REVIEW-RESET row."""
    used = 0
    for line in _decisions_log_text(topic_dir).splitlines():
        if RESET_MARKER in line:
            used = 0
        elif AUTO_MARKER in line:
            used += 1
    return used


def status(topic_dir: Path, policy: str, limit: int) -> dict[str, Any]:
    used = auto_promotions_used(topic_dir)
    allowed = policy == "auto" and used < limit
    return {
        "policy": policy,
        "gap_auto_limit": limit,
        "auto_promotions_used": used,
        "auto_promotion_allowed": allowed,
        "remaining": max(limit - used, 0) if policy == "auto" else 0,
    }


def _append_decision(topic_dir: Path, row_id: str, note: str) -> None:
    path = topic_dir / "DECISIONS-LOG.md"
    row = f"| {row_id} | {_today()} | {note} |\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(row)


_RECENTLY_ACTIVE_WINDOW_SECONDS = 60


def _seconds_since_last_log_write(topic_dir: Path) -> float | None:
    """Best-effort "is an iteration probably running right now" signal.

    gap-policy.py has no queue awareness by design (it works standalone,
    same as every other chassis tool) -- it can't ask the queue whether this
    topic is claimed. The most recently modified file under logs/ is the
    only filesystem-only proxy available. Not perfect (a stale race window
    still exists), but real: an operator amending SEMANTIC-STATE.json while
    an agent is mid-iteration writing to the same file is a genuine
    conflict, and this catches the common case.
    """
    log_dir = topic_dir / "logs"
    if not log_dir.is_dir():
        return None
    mtimes = [entry.stat().st_mtime for entry in log_dir.iterdir() if entry.is_file()]
    if not mtimes:
        return None
    return time.time() - max(mtimes)


def promote(
    topic_dir: Path,
    *,
    obligation_id: str,
    text: str,
    source_ref: str,
    auto: bool,
    force: bool = False,
) -> None:
    # Only for operator-initiated amends -- an --auto self-promotion is
    # called BY the agent FROM its own iteration, so recent log activity is
    # expected there, not a race to warn about.
    if not auto and not force:
        age = _seconds_since_last_log_write(topic_dir)
        if age is not None and age < _RECENTLY_ACTIVE_WINDOW_SECONDS:
            raise SystemExit(
                f"{topic_dir} looks like it may have an iteration actively running "
                f"(a log file was modified {age:.0f}s ago) -- editing SEMANTIC-STATE.json "
                "now risks a race with that iteration's own writes. Pause the topic "
                "first (`research-loops pause <id>`), or pass --force if you're sure "
                "it's safe."
            )
    try:
        semantic_state.append_obligation(topic_dir, obligation_id, text, source_ref)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    semantic_state.rehash(topic_dir)

    tag = AUTO_MARKER if auto else REVIEWED_MARKER
    actor = "agent" if auto else "operator"
    _append_decision(
        topic_dir,
        f"GAP-{obligation_id}",
        f"[{actor}] {tag}: {text} (source: {source_ref})",
    )


def review_reset(topic_dir: Path, note: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    _append_decision(topic_dir, f"{RESET_MARKER}-{stamp}", f"[operator] {RESET_MARKER}: {note}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    status_p = sub.add_parser(
        "status", help="report how much of an auto gap-policy budget is used"
    )
    status_p.add_argument("topic_dir", type=Path)
    status_p.add_argument("--policy", choices=("review", "auto"), default="review")
    status_p.add_argument("--limit", type=int, default=0)

    promote_p = sub.add_parser(
        "promote",
        help="turn a proposed gap into a binding obligation in TOPIC.md/SEMANTIC-STATE.json and rehash",
    )
    promote_p.add_argument("topic_dir", type=Path)
    promote_p.add_argument("--id", required=True, dest="obligation_id")
    promote_p.add_argument("--text", required=True)
    promote_p.add_argument("--source-ref", required=True)
    promote_p.add_argument(
        "--auto",
        action="store_true",
        help="mark this as an agent self-promotion under an auto gap policy "
        "(requires --limit; refuses once the budget since the last "
        "review-reset is used up) instead of an operator-reviewed promotion",
    )
    promote_p.add_argument(
        "--limit", type=int, help="required with --auto: this topic's gap_auto_limit"
    )
    promote_p.add_argument(
        "--force",
        action="store_true",
        help="operator amends only (ignored with --auto): skip the check for a "
        "recently-modified log file that might mean an iteration is actively "
        "running right now (a filesystem-only best-effort signal -- this tool "
        "has no queue awareness). Pausing the topic first is the safer option",
    )

    reset_p = sub.add_parser(
        "review-reset",
        help="operator marks accumulated auto-promotions reviewed, resetting the budget",
    )
    reset_p.add_argument("topic_dir", type=Path)
    reset_p.add_argument("--note", required=True)

    args = parser.parse_args(argv)
    if args.action == "status":
        print(json.dumps(status(args.topic_dir, args.policy, args.limit), indent=2, sort_keys=True))
        return 0
    if args.action == "promote":
        if args.auto:
            if args.limit is None:
                parser.error("--auto requires --limit")
            used = auto_promotions_used(args.topic_dir)
            if used >= args.limit:
                print(
                    f"gap auto-limit reached ({used}/{args.limit}); append a PROPOSAL "
                    "row to DECISIONS-LOG.md instead and wait for an operator "
                    "review-reset",
                    file=sys.stderr,
                )
                return 1
        promote(
            args.topic_dir,
            obligation_id=args.obligation_id,
            text=args.text,
            source_ref=args.source_ref,
            auto=args.auto,
            force=args.force,
        )
        print(f"promoted {args.obligation_id}")
        return 0
    if args.action == "review-reset":
        review_reset(args.topic_dir, args.note)
        print("review reset recorded")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
