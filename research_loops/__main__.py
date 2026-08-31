from __future__ import annotations

import argparse
import fcntl
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dashboard import render_dashboard, write_dashboard
from .queue import QueueError, QueueStore
from .runner import LoopRunner, UsageLedger


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-loops")
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[1]),
        help="queue root containing state/ and logs/",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    add = sub.add_parser("add", help="add a loop command")
    add.add_argument("--id")
    add.add_argument("--title", required=True)
    add.add_argument("--cwd", required=True)
    add.add_argument("--provider")
    add.add_argument("--usage-file")
    add.add_argument("--stop-file")
    add.add_argument(
        "--progress-command",
        help=(
            "shell-free argv (JSON array) printing a qualifying-progress digest; "
            "used with --stall-limit to flag successful-but-stalled loops"
        ),
    )
    add.add_argument("--stall-limit", type=int)
    add.add_argument("--max-attempts", type=int, default=5)
    add.add_argument("--repeat-seconds", type=int)
    add.add_argument("command", nargs=argparse.REMAINDER)

    listing = sub.add_parser("list", help="show queue state")
    listing.add_argument("--json", action="store_true")
    sub.add_parser("status", help="show queue state")

    move = sub.add_parser("move", help="move an item to a zero-based position")
    move.add_argument("item_id")
    move.add_argument("position", type=int)

    remove = sub.add_parser("remove", help="remove a non-running item")
    remove.add_argument("item_id")

    pause = sub.add_parser("pause", help="pause one item or the whole queue")
    pause.add_argument("item_id", nargs="?")
    pause.add_argument("--reason")

    resume = sub.add_parser("resume", help="resume one item or the whole queue")
    resume.add_argument("item_id", nargs="?")

    restart = sub.add_parser("restart", help="restart an item safely")
    restart.add_argument("item_id")

    worker_policy = sub.add_parser(
        "worker-policy", help="set a worker's durable new-topic intake policy"
    )
    worker_policy.add_argument("worker")
    policy_mode = worker_policy.add_mutually_exclusive_group(required=True)
    policy_mode.add_argument(
        "--continuous", action="store_true", help="accept new topics without a limit"
    )
    policy_mode.add_argument(
        "--claim-limit",
        type=int,
        help="accept this many new topics, then only continue prior topics",
    )

    sync = sub.add_parser(
        "sync",
        help=(
            "reconcile the queue with a manifest, preserving runtime history "
            "(the ONLY sanctioned way to bulk-reshape the queue)"
        ),
    )
    sync.add_argument(
        "--manifest",
        required=True,
        help="JSON file with an 'items' array (or a bare array) of item definitions",
    )
    sync.add_argument(
        "--prune",
        action="store_true",
        help="remove non-running queue items absent from the manifest",
    )

    usage = sub.add_parser("usage", help="summarize recorded usage")
    usage.add_argument("--json", action="store_true")
    usage.add_argument(
        "--include-snapshots",
        action="store_true",
        help="also emit raw subscription-window snapshots (not additive across runs)",
    )
    usage.add_argument(
        "--since",
        help="only include events at or after this ISO-8601 timestamp (e.g. 2026-08-01T00:00:00Z)",
    )

    dashboard = sub.add_parser(
        "dashboard", help="generate the operator-facing Markdown queue status"
    )
    dashboard.add_argument(
        "--output",
        help="output Markdown path (default: parent of queue root/STATUS.md)",
    )

    run = sub.add_parser("run", help="run the queue worker")
    run.add_argument(
        "--worker",
        default="worker-1",
        help="worker slot name; each slot has its own lock and only ever "
        "resumes/supervises its own claimed item (parallel workers are additive)",
    )
    run.add_argument(
        "--profile",
        help=(
            "optional runner-interpreted profile override for this worker; omission preserves "
            "each queue item's positional profile"
        ),
    )
    run.add_argument("--once", action="store_true")
    run.add_argument("--idle-sleep", type=float, default=5.0)
    run.add_argument("--poll-seconds", type=float, default=1.0)
    run.add_argument("--no-usage-snapshot", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    store = QueueStore(root)
    ledger = UsageLedger(root / "state" / "events.jsonl")
    try:
        if args.action == "add":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            progress_command = None
            if args.progress_command:
                progress_command = json.loads(args.progress_command)
                if not isinstance(progress_command, list):
                    raise QueueError("progress_command must be a JSON array")
            emit(
                store.add(
                    title=args.title,
                    cwd=args.cwd,
                    command=command,
                    item_id=args.id,
                    provider=args.provider,
                    usage_file=args.usage_file,
                    stop_file=args.stop_file,
                    progress_command=progress_command,
                    stall_limit=args.stall_limit,
                    max_attempts=args.max_attempts,
                    repeat_seconds=args.repeat_seconds,
                )
            )
        elif args.action in {"list", "status"}:
            emit(store.snapshot())
        elif args.action == "move":
            emit(store.move(args.item_id, args.position))
        elif args.action == "remove":
            emit(store.remove(args.item_id))
        elif args.action == "pause":
            emit(
                store.pause_item(args.item_id, args.reason)
                if args.item_id
                else store.pause_all(args.reason)
            )
        elif args.action == "resume":
            emit(store.resume_item(args.item_id) if args.item_id else store.resume_all())
        elif args.action == "restart":
            emit(store.request_restart(args.item_id))
        elif args.action == "worker-policy":
            emit(
                store.configure_worker_policy(
                    args.worker,
                    claim_limit=None if args.continuous else args.claim_limit,
                )
            )
        elif args.action == "sync":
            manifest_path = Path(args.manifest).expanduser()
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except OSError as exc:
                raise QueueError(f"cannot read manifest: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise QueueError(f"manifest is not valid JSON: {exc}") from exc
            items = payload.get("items") if isinstance(payload, dict) else payload
            if not isinstance(items, list):
                raise QueueError("manifest must be a JSON array or an object with 'items'")
            emit(store.sync(items, prune=args.prune))
        elif args.action == "usage":
            since = None
            if args.since:
                if not args.include_snapshots:
                    raise QueueError(
                        "--since only filters snapshots; pass --include-snapshots with it"
                    )
                try:
                    since = datetime.fromisoformat(args.since)
                except ValueError as exc:
                    raise QueueError(f"invalid --since timestamp: {exc}") from exc
                if since.tzinfo is None:
                    # A naive datetime would silently compare unequal against
                    # aware event timestamps and disable the filter; assume UTC.
                    since = since.replace(tzinfo=timezone.utc)
            result: dict[str, Any] = {"summary": ledger.summary()}
            if args.include_snapshots:
                result["snapshots"] = ledger.snapshots(since=since)
            emit(result)
        elif args.action == "dashboard":
            output = (
                Path(args.output).expanduser().absolute()
                if args.output
                else root.parent / "STATUS.md"
            )
            content = render_dashboard(store.snapshot(), ledger.events())
            written = write_dashboard(output, content)
            emit({"output": str(written)})
        elif args.action == "run":
            # Per-worker lock: worker-1 keeps the legacy lock filename so an
            # in-place upgrade cannot race a still-running old worker.
            lock_name = (
                "worker.lock"
                if args.worker == "worker-1"
                else f"worker-{args.worker}.lock"
            )
            worker_lock_path = root / "state" / lock_name
            worker_lock = worker_lock_path.open("a+", encoding="utf-8")
            try:
                fcntl.flock(worker_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                worker_lock.close()
                raise QueueError(
                    f"queue worker '{args.worker}' is already running"
                ) from exc
            usage_command = None
            llm_usage = shutil.which("llm-usage")
            if llm_usage and not args.no_usage_snapshot:
                usage_command = [llm_usage, "--json"]
            runner = LoopRunner(
                store,
                ledger,
                poll_seconds=args.poll_seconds,
                usage_command=usage_command,
                worker=args.worker,
                profile=args.profile,
            )
            try:
                if args.once:
                    emit(runner.run_once())
                else:
                    runner.run_forever(idle_sleep=args.idle_sleep)
            finally:
                fcntl.flock(worker_lock.fileno(), fcntl.LOCK_UN)
                worker_lock.close()
        return 0
    except (QueueError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except TypeError as exc:
        # Malformed manifest/argument shapes must fail cleanly, not traceback.
        print(f"error: invalid input shape: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
