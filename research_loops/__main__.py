from __future__ import annotations

import argparse
import fcntl
import json
import shutil
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import doctor, topic_authoring, workers as workers_mod
from .config import load_config
from .dashboard import render_dashboard, write_dashboard
from .queue import QueueError, QueueStore
from .runner import LoopRunner, UsageLedger


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _default_root() -> Path:
    """The queue root to use when --root is omitted.

    A git clone or an editable install (`pip install -e .`) keeps __file__
    pointing at the real source tree -- recognizable because pyproject.toml
    sits next to research_loops/ there. That never happens for a real
    (non-editable) wheel install: chassis/ ships as package data either way
    (see pyproject.toml's [tool.setuptools.package-data]), so its presence
    can't be used to tell the two apart, but pyproject.toml is a source-only
    file, never installed into site-packages. When it's present, default to
    the source tree root, so `research-loops` on PATH hits the same one queue
    regardless of cwd, exactly like today's git-clone/systemd workflows. A
    real wheel install has no such repo to fall back to; there, default to
    cwd, the same convention git/npm use ("operate on the directory you're
    standing in").
    """
    source_tree_root = Path(__file__).resolve().parents[1]
    if (source_tree_root / "pyproject.toml").is_file():
        return source_tree_root
    return Path.cwd()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-loops",
        description="Durable queue for running research topics via a pluggable runner. "
        "See docs/operations.md for day-to-day use.",
    )
    parser.add_argument(
        "--root",
        default=str(_default_root()),
        help="queue root containing state/ and logs/ (defaults to this install's "
        "source tree for a git clone/editable install, or the current directory "
        "for a real pip install — see docs/operations.md)",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    new_topic = sub.add_parser(
        "new-topic",
        help="scaffold a draft topic from a brief (deterministic, no LLM call)",
    )
    new_topic.add_argument("topic_id")
    new_topic.add_argument("--title", required=True)
    new_topic.add_argument(
        "--brief", required=True, help="path to a brief text file, or '-' for stdin"
    )
    new_topic.add_argument(
        "--dest", help="directory under which <topic_id>/ is created (default: <root>/topics)"
    )

    approve_topic = sub.add_parser(
        "approve-topic",
        help="promote a reviewed draft topic to a real, queueable topic",
    )
    approve_topic.add_argument("topic_id")
    approve_topic.add_argument("--dest", help="default: <root>/topics")

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
    add.add_argument(
        "--agent-main",
        help="sets RESEARCH_LOOP_RUNNER for this item, overriding the command's "
        "positional runner-name argument for this item only",
    )
    add.add_argument(
        "--agent-secondary",
        help="named delegate agent surfaced to the runner as "
        "RESEARCH_LOOP_AGENT_SECONDARY, for legwork delegation only",
    )
    add.add_argument(
        "--gap-policy",
        choices=("review", "auto"),
        default="review",
        help="review (default): agent may only propose a gap via DECISIONS-LOG.md. "
        "auto: agent may self-promote gaps up to --gap-auto-limit before falling "
        "back to review (see docs/governance.md#the-operator-owns-scope)",
    )
    add.add_argument(
        "--gap-auto-limit",
        type=int,
        default=0,
        help="self-promotions allowed since the last operator review-reset, "
        "when --gap-policy=auto",
    )
    add.add_argument(
        "--lock-sha256",
        help="the approved completion-inventory lock from `approve-topic` or "
        "`research_loops/chassis/semantic-state.py lock` — passed into every DONE "
        "check for this item so an agent cannot pass validation by adding, removing, or renaming "
        "an obligation/deliverable directly in SEMANTIC-STATE.json. Strongly "
        "recommended for every topic; omitting it means DONE is only checked "
        "structurally, not against a pinned inventory",
    )
    add.add_argument(
        "--depends-on",
        help="comma-separated item ids this topic's research is genuinely impossible "
        "without the *completed* output of -- never for scheduling preference, use "
        "`move` for that (see docs/topic-authoring.md#dependencies-vs-order). A "
        "dependency may reference an id you haven't added yet -- it only has to "
        "exist by the time this item is actually claimed",
    )
    add.add_argument(
        "--internal-citations",
        action="store_true",
        help="allow this topic to cite a source already vetted in another topic's "
        "SOURCE-LEDGER.md instead of re-researching it (see docs/citations.md). "
        "Disabled by default",
    )
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
    pause.add_argument(
        "--now",
        action="store_true",
        help="kill an in-flight iteration immediately (SIGTERM) instead of the "
        "default: let it finish naturally, then land on paused without "
        "auto-rescheduling. A non-running item pauses immediately either way",
    )

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

    config = sub.add_parser(
        "config",
        help="declarative scheduling/agent/gap-policy config (research_loops/config.py)",
    )
    config_sub = config.add_subparsers(dest="config_action", required=True)
    config_apply = config_sub.add_parser(
        "apply",
        help="apply a TOML config's [defaults]/[topics.<id>] settings to matching "
        "existing queue items (never touches command/cwd/title; see "
        "config/research-loops.example.toml)",
    )
    config_apply.add_argument("--config", required=True, help="path to a TOML config file")
    config_show = config_sub.add_parser(
        "show", help="print the resolved settings for one topic id"
    )
    config_show.add_argument("--config", required=True)
    config_show.add_argument("topic_id")

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

    doctor = sub.add_parser(
        "doctor",
        help="portfolio-wide health audit (non-mutating): structural validity, "
        "completion-lock coverage, dependency integrity, orphaned topic dirs, "
        "source counts",
    )
    doctor.add_argument(
        "--topics-root",
        type=Path,
        help="also check for orphaned topic directories under this path "
        "(default: <root>/topics, matching new-topic/approve-topic's own default)",
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

    workers = sub.add_parser(
        "workers",
        help="start/stop N `run --worker` processes per a config's `workers` count",
    )
    workers_sub = workers.add_subparsers(dest="workers_action", required=True)
    workers_start = workers_sub.add_parser(
        "start", help="spawn `workers` background `run` processes from a config"
    )
    workers_start.add_argument("--config", required=True)
    workers_start.add_argument("--worker-prefix", default="worker-")
    workers_sub.add_parser(
        "stop", help="stop workers previously started with `workers start`"
    )
    workers_sub.add_parser(
        "status", help="show which previously-started workers are still alive"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    store = QueueStore(root)
    ledger = UsageLedger(root / "state" / "events.jsonl")
    try:
        if args.action == "new-topic":
            dest = Path(args.dest).expanduser().resolve() if args.dest else root / "topics"
            brief_text = (
                sys.stdin.read()
                if args.brief == "-"
                else Path(args.brief).read_text(encoding="utf-8")
            )
            result = topic_authoring.new_topic(
                args.topic_id, title=args.title, brief_text=brief_text, dest=dest
            )
            emit(result)
        elif args.action == "approve-topic":
            dest = Path(args.dest).expanduser().resolve() if args.dest else root / "topics"
            emit(topic_authoring.approve_topic(args.topic_id, dest=dest))
        elif args.action == "add":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            progress_command = None
            if args.progress_command:
                progress_command = json.loads(args.progress_command)
                if not isinstance(progress_command, list):
                    raise QueueError("progress_command must be a JSON array")
            depends_on = (
                [value.strip() for value in args.depends_on.split(",") if value.strip()]
                if args.depends_on
                else None
            )
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
                    agent_main=args.agent_main,
                    agent_secondary=args.agent_secondary,
                    gap_policy=args.gap_policy,
                    gap_auto_limit=args.gap_auto_limit,
                    completion_lock=args.lock_sha256,
                    depends_on=depends_on,
                    internal_citations=args.internal_citations,
                )
            )
        elif args.action in {"list", "status"}:
            emit(store.snapshot())
        elif args.action == "move":
            emit(store.move(args.item_id, args.position))
        elif args.action == "remove":
            emit(store.remove(args.item_id))
        elif args.action == "pause":
            graceful = not args.now
            emit(
                store.pause_item(args.item_id, args.reason, graceful=graceful)
                if args.item_id
                else store.pause_all(args.reason, graceful=graceful)
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
        elif args.action == "config":
            config = load_config(args.config)
            if args.config_action == "show":
                emit(asdict(config.for_topic(args.topic_id)))
            elif args.config_action == "apply":
                snapshot = store.snapshot()
                existing_ids = {item["id"] for item in snapshot["items"]}
                applied: list[str] = []
                skipped: list[str] = []
                for topic_id in config.topics:
                    if topic_id not in existing_ids:
                        skipped.append(topic_id)
                        continue
                    settings = config.for_topic(topic_id)
                    store.configure_topic(
                        topic_id,
                        repeat_seconds=settings.repeat_seconds,
                        max_attempts=settings.max_attempts,
                        stall_limit=settings.stall_limit,
                        agent_main=settings.agent_main,
                        agent_secondary=settings.agent_secondary,
                        gap_policy=settings.gap_policy,
                        gap_auto_limit=settings.gap_auto_limit,
                        internal_citations=settings.internal_citations,
                    )
                    applied.append(topic_id)
                emit({"applied": applied, "skipped_unknown_topic": skipped})
        elif args.action == "workers":
            if args.workers_action == "start":
                config = load_config(args.config)
                extra_run_args = [
                    "--idle-sleep",
                    str(config.idle_sleep),
                    "--poll-seconds",
                    str(config.poll_seconds),
                ]
                pids = workers_mod.start(
                    root,
                    config.workers,
                    worker_prefix=args.worker_prefix,
                    extra_run_args=extra_run_args,
                )
                emit({"started": pids})
            elif args.workers_action == "stop":
                emit(workers_mod.stop(root))
            elif args.workers_action == "status":
                emit(workers_mod.status(root))
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
        elif args.action == "doctor":
            topics_root = (
                Path(args.topics_root).expanduser().resolve()
                if args.topics_root
                else root / "topics"
            )
            emit(doctor.run_doctor(store.snapshot()["items"], topics_root=topics_root))
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
