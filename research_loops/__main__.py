from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import doctor, refresh as refresh_mod, topic_authoring, workers as workers_mod
from .config import load_config
from .dashboard import render_dashboard, write_dashboard
from .queue import QueueError, QueueStore
from .runner import LoopRunner, UsageLedger
from .control_store import ControlStore
from .intake import IntakeService, load_json
from .access import load_access
from .controller_client import call as controller_call, ControllerClientError


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _parse_research_policy(raw: str | None) -> dict | None:
    """CLI string → research_policy dict (validated again by the store). 'clear'
    unbinds; None passes through for items that never set one."""
    if raw is None or raw == "":
        return None
    if raw.strip().lower() == "clear":
        return None
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise QueueError(f"research policy must be a JSON object: {exc}") from None
    if not isinstance(value, dict):
        raise QueueError("research policy must be a JSON object")
    return value


def _stations_topic_view(result: Any, topic_id: str | None) -> Any:
    """Reduce a stations --show result to one topic's work-ledger record.

    Client-side so it works identically over the socket and against a local
    supervisor read; the operator's routine per-topic inspection then never
    needs raw access to the protected state directory."""
    if not topic_id:
        return result
    work = (result or {}).get("topic_work") if isinstance(result, dict) else None
    record = (work or {}).get(topic_id)
    if record is None:
        raise QueueError(f"stations view has no work record for topic: {topic_id}")
    return {"revision": result.get("revision"), "topic_id": topic_id, "topic_work": record}


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
    new_topic.add_argument(
        "--mode",
        choices=("focused", "broad", "scoped"),
        default="broad",
        help="QA mode. broad (default): assumptions are surfaced and a "
        "discovery pass maps the topic space before scoping. focused (formerly scoped): the "
        "operator's stated frame is fixed -- QA clarifies within it, never "
        "questions premises",
    )

    discover = sub.add_parser(
        "discover",
        help="queue a bounded discovery pass for a DRAFT topic on the intake "
        "lane (parallel to research workers): maps the topic space, writes "
        "SCOPE-PROPOSAL.md, appends surfaced assumptions to QA-RECORD.md",
    )
    discover.add_argument("topic_id")
    discover.add_argument("--dest", help="drafts directory (default: <root>/topics)")
    discover.add_argument(
        "--agent-main", default="claude",
        help="runner adapter for the discovery pass (a command argument, not an "
        "item binding — stations own all runtime agent mechanics)",
    )

    approve_topic = sub.add_parser(
        "approve-topic",
        help="promote a reviewed draft topic to a real, queueable topic",
    )
    approve_topic.add_argument("topic_id")
    approve_topic.add_argument("--dest", help="default: <root>/topics")

    for action, help_text in (("intake-submit", "submit a strict intake brief JSON"), ("intake-result", "record a strict discovery result JSON"), ("intake-approve", "apply a strict intake operator decision JSON")):
        command = sub.add_parser(action, help=help_text)
        command.add_argument("--file", required=True, help="schema-versioned JSON payload")
    checkpoint_decide = sub.add_parser("checkpoint-decide", help="apply a strict checkpoint decision JSON")
    checkpoint_decide.add_argument("--file", required=True)
    checkpoint_reset = sub.add_parser("checkpoint-reset", help="explicitly reset a topic's proposal issuance allowance")
    checkpoint_reset.add_argument("--file", required=True)
    checkpoint_retry = sub.add_parser("checkpoint-retry", help="return a failed checkpoint episode to its bounded retry state")
    checkpoint_retry.add_argument("--file", required=True)
    reorder = sub.add_parser("queue-reorder", help="replace managed queue order atomically")
    reorder.add_argument("--file", required=True, help="{expected_queue_revision, ordered_ids}")
    stations = sub.add_parser("stations", help="managed station configuration")
    stations.add_argument("--show", action="store_true")
    stations.add_argument("--all", action="store_true")
    stations.add_argument("--ids", help="comma-separated station IDs")
    stations.add_argument("--primary")
    stations.add_argument("--secondary")
    stations.add_argument("--active-count", type=int)
    stations.add_argument("--intervals", help="five comma-separated nondecreasing seconds")
    stations.add_argument("--file", help="full station/checkpoint update JSON")
    stations.add_argument(
        "--topic", dest="topic_filter",
        help="with --show: reduce the view to one topic's work-ledger record "
        "(counts, ordinals, review state, active episode)")
    profile_register = sub.add_parser("profile-register", help="register a managed executable profile")
    profile_register.add_argument("--file", required=True)
    migrate = sub.add_parser("control-migrate", help="explicitly validate or apply legacy queue migration")
    migrate.add_argument("--file", required=True, help="{configuration,agent_profiles,baseline_counts,checkpoint_history?}")
    migrate.add_argument("--apply", action="store_true", help="create state/control.sqlite3 after validation; default is dry run")

    add = sub.add_parser("add", help="add a loop command")
    add.add_argument("--id")
    add.add_argument("--title", required=True)
    add.add_argument("--cwd", required=True)
    add.add_argument("--provider")
    add.add_argument("--usage-file")
    add.add_argument("--stop-file")
    add.add_argument(
        "--on-completed",
        help=(
            "shell-free argv (JSON array) run once when the item lands "
            "completed (e.g. a corpus ingest); failure is ledgered, never "
            "un-completes the item"
        ),
    )
    add.add_argument(
        "--progress-command",
        help=(
            "shell-free argv (JSON array) printing a qualifying-progress digest; "
            "used with --stall-limit to flag successful-but-stalled loops"
        ),
    )
    add.add_argument("--stall-limit", type=int)
    add.add_argument("--max-attempts", type=int, default=5)
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
    add.add_argument(
        "--research-policy",
        help="JSON object binding the topic's research posture for the gateway tool, "
        "e.g. '{\"commercial\": true, \"domain\": \"finance\"}' (fields: commercial, "
        "accept_per_item, domain). Injected into every research call; conflicting "
        "agent arguments are rejected (gateway docs/STATION-CONTRACT.md)",
    )
    add.add_argument(
        "--topic-refresh",
        choices=("off", "weekly", "monthly"),
        default="off",
        help="off (default): a completed topic never automatically reruns -- "
        "use `research-loops refresh` to trigger one by hand. weekly/monthly: "
        "once completed, this topic is automatically requeued that often to "
        "check for new information (see docs/operations.md#topic_refresh)",
    )
    add.add_argument(
        "--topic-refresh-mode",
        choices=("light", "continue", "full"),
        default="continue",
        help="what a refresh actually reopens: light (one new check obligation "
        "only), continue (reopens previously-supported obligations, the "
        "default), full (reopens every obligation). Only matters once "
        "--topic-refresh is not off, or when `research-loops refresh` is run "
        "without --mode",
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

    relock = sub.add_parser(
        "relock",
        help=(
            "recompute an item's completion lock from its topic's current "
            "SEMANTIC-STATE.json after an operator-approved scope change — the "
            "sanctioned alternative to hand-editing hashes (sync deliberately "
            "refuses completion_lock changes, and a stale lock rejects every "
            "future DONE with no remedy)"
        ),
    )
    relock.add_argument("item_id")

    research_policy = sub.add_parser(
        "research-policy",
        help="bind (or clear) an item's research policy — the operator migration "
        "path for items that predate --research-policy on add. Takes effect on the "
        "item's next iteration",
    )
    research_policy.add_argument("item_id")
    research_policy.add_argument(
        "policy",
        help="JSON object (fields: commercial, accept_per_item, domain) or the "
        "literal 'clear' to unbind",
    )

    resolve_research = sub.add_parser(
        "resolve-research",
        help="explicitly release an item's research blockers on sufficient-alternative "
        "grounds — an evidence decision recorded with its reason (an ordinary resume "
        "never clears blockers)",
    )
    resolve_research.add_argument("item_id")
    resolve_research.add_argument("--reason", required=True,
                                  help="why the blocked research is satisfied without that retrieval")
    resolve_research.add_argument("--source", action="append", dest="sources",
                                  help="release only this source's blockers (repeatable; default: all)")

    swap_active = sub.add_parser(
        "swap-active",
        help="move a worker from whatever it currently owns to a specific queued "
        "item, without killing an in-flight iteration",
    )
    swap_active.add_argument("worker")
    swap_active.add_argument("target_item_id")

    refresh = sub.add_parser(
        "refresh",
        help="manually trigger a refresh on a completed item, regardless of its "
        "--topic-refresh schedule (the 'manual' half of off/weekly/monthly -- "
        "see docs/operations.md#topic_refresh)",
    )
    refresh.add_argument("item_id")
    refresh.add_argument(
        "--mode",
        choices=("light", "continue", "full"),
        help="defaults to the item's configured --topic-refresh-mode "
        "(or 'continue' if never set)",
    )

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

    agents = sub.add_parser(
        "agents",
        help="DEPRECATED: agents are a worker (station) property now -- use "
        "`worker-agents`",
    )
    agents.add_argument("item_id")
    agents.add_argument("--main", dest="agent_main")
    agents.add_argument("--secondary", dest="agent_secondary")
    worker_agents = sub.add_parser(
        "worker-agents",
        help="set a worker's agent profile (which harness/model pair the station "
        "runs) -- durable, takes effect at that worker's next iteration launch; "
        "the queue itself carries no agent binding",
    )
    worker_agents.add_argument("worker")
    worker_agents.add_argument(
        "--main", dest="agent_main",
        help="runner adapter name (claude|codex|hermes|generic); '' to unset",
    )
    worker_agents.add_argument(
        "--secondary", dest="agent_secondary",
        help="delegation command the primary runs for legwork; '' to unset",
    )
    worker_agents.add_argument(
        "--model", dest="agent_model",
        help="model id for the main adapter (sets RESEARCH_LOOP_<RUNNER>_MODEL); '' to unset",
    )
    worker_agents.add_argument(
        "--flags", dest="agent_flags",
        help="extra CLI flags for the main adapter (sets RESEARCH_LOOP_<RUNNER>_FLAGS); '' to unset",
    )
    worker_agents.add_argument(
        "--interval", dest="interval_seconds", type=int,
        help="station cadence: seconds to pause between iterations (0 = continuous)",
    )
    worker_agents.add_argument("--clear", action="store_true", help="drop the profile")
    fleet = sub.add_parser(
        "fleet",
        help="show or set fleet-wide station mechanics (the stations' collective "
        "config in state/stations.json): the obligations-checkpoint schedule "
        "every station applies to whatever topic it holds",
    )
    fleet.add_argument(
        "--checkpoint-every", dest="checkpoint_every", type=int,
        help="assign an obligations checkpoint every N ordinary iterations "
        "(0 disables the cadence trigger)",
    )
    fleet.add_argument(
        "--checkpoint-on-deepening", dest="checkpoint_on_deepening",
        choices=("on", "off"),
        help="assign a checkpoint once a topic first enters deepening",
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
    dashboard.add_argument(
        "--full", action="store_true",
        help="include history/telemetry (paused/completed enumerations, "
        "economics, ledger aggregates, metric definitions); the default is "
        "the compact actionable status page",
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
    run.add_argument(
        "--lanes",
        default="research",
        help="comma-separated lanes this worker claims from (research, intake). "
        "A dedicated intake worker (--lanes intake) runs discovery passes in "
        "parallel with the research fleet without competing for it",
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
    remote_socket = os.environ.get("RESEARCH_LOOP_CONTROLLER_SOCKET")
    protected_actions = {"intake-submit", "intake-result", "intake-approve", "checkpoint-decide", "checkpoint-reset", "checkpoint-retry", "queue-reorder", "stations", "profile-register"}
    # An operator may intentionally lack permission even to stat the protected
    # root.  An explicitly supplied controller socket is therefore checked
    # before any ControlStore/QueueStore construction or filesystem probe.
    if remote_socket and args.action in protected_actions:
        try:
            if args.action == "queue-reorder":
                result = controller_call(remote_socket, "queue.reorder", load_json(Path(args.file)))
            elif args.action == "stations":
                payload = {} if args.show else (load_json(Path(args.file)) if args.file else {"station_ids": [int(x) for x in args.ids.split(",")] if args.ids else None, "all_stations": args.all, "primary_profile": args.primary, "secondary_profile": args.secondary, "intervals": [int(x) for x in args.intervals.split(",")] if args.intervals else None, "active_count": args.active_count})
                result = controller_call(remote_socket, "stations.show" if args.show else "stations.update", payload)
                if args.show:
                    result = _stations_topic_view(result, args.topic_filter)
            elif args.action == "profile-register":
                result = controller_call(remote_socket, "profiles.register", load_json(Path(args.file)))
            else:
                method = {"intake-submit": "intake.submit_brief", "intake-result": "intake.record_discovery_result", "intake-approve": "intake.approve", "checkpoint-decide": "checkpoint.decide", "checkpoint-reset": "checkpoint.reset_allowance", "checkpoint-retry": "checkpoint.retry"}[args.action]
                result = controller_call(remote_socket, method, load_json(Path(args.file)))
            emit(result); return 0
        except (OSError, ControllerClientError, QueueError) as exc:
            print(f"error: {exc}", file=sys.stderr); return 2
    if remote_socket and args.action in {"status", "pause", "resume"}:
        try:
            if args.action == "status": result = controller_call(remote_socket, "queue.status", {})
            elif args.action == "pause": result = controller_call(remote_socket, "queue.pause" if args.item_id else "queue.pause_all", ({"topic_id": args.item_id, "reason": args.reason} if args.item_id else {"reason": args.reason}))
            else: result = controller_call(remote_socket, "queue.resume" if args.item_id else "queue.resume_all", ({"topic_id": args.item_id} if args.item_id else {}))
            emit(result); return 0
        except (OSError, ControllerClientError) as exc:
            print(f"error: {exc}", file=sys.stderr); return 2
    managed = ControlStore(root).exists
    if args.action == "control-migrate":
        try:
            payload = load_json(Path(args.file))
            allowed = {"configuration", "agent_profiles", "baseline_counts", "checkpoint_history"}
            if set(payload) - allowed or not {"configuration", "agent_profiles", "baseline_counts"} <= set(payload):
                raise QueueError("migration file requires configuration, agent_profiles, baseline_counts and optional checkpoint_history only")
            emit(ControlStore.apply_legacy_migration(root, configuration=payload["configuration"], agent_profiles=payload["agent_profiles"], baseline_counts=payload["baseline_counts"], checkpoint_history=payload.get("checkpoint_history"), dry_run=not args.apply))
            return 0
        except (OSError, QueueError, RuntimeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    # Operator mutations in a managed deployment travel through the trusted
    # controller before a QueueStore is constructed.
    if args.action in protected_actions and managed:
        try:
            socket_path = load_access(root)["socket_path"]
            if args.action == "queue-reorder":
                result = controller_call(socket_path, "queue.reorder", load_json(Path(args.file)))
            elif args.action == "stations":
                payload = load_json(Path(args.file)) if args.file else ({} if args.show else {"station_ids": [int(x) for x in args.ids.split(",")] if args.ids else None, "all_stations": args.all, "primary_profile": args.primary, "secondary_profile": args.secondary, "intervals": [int(x) for x in args.intervals.split(",")] if args.intervals else None, "active_count": args.active_count})
                result = controller_call(socket_path, "stations.show" if args.show else "stations.update", payload)
                if args.show:
                    result = _stations_topic_view(result, args.topic_filter)
            elif args.action == "profile-register":
                result = controller_call(socket_path, "profiles.register", load_json(Path(args.file)))
            else:
                method = {"intake-submit": "intake.submit_brief", "intake-result": "intake.record_discovery_result", "intake-approve": "intake.approve", "checkpoint-decide": "checkpoint.decide", "checkpoint-reset": "checkpoint.reset_allowance", "checkpoint-retry": "checkpoint.retry"}[args.action]
                result = controller_call(socket_path, method, load_json(Path(args.file)))
            emit(result)
            return 0
        except (OSError, ControllerClientError, QueueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    store = QueueStore(root)
    ledger = UsageLedger(root / "state" / "events.jsonl")
    try:
        if managed and args.action in {"add", "sync", "relock", "move", "remove", "swap-active", "worker-agents", "fleet", "config"}:
            raise QueueError(f"managed roots require controller operations; legacy {args.action} cannot bypass managed admission/configuration")
        if args.action in protected_actions:
            control = ControlStore(root)
            if not control.exists:
                raise QueueError("managed intake requires initialized controller state; this root is explicitly unmanaged")
            service = IntakeService(control, root / "topics", actor="cli-operator")
            if args.action == "queue-reorder":
                from .control_store import ControlScheduler
                payload = load_json(Path(args.file))
                if set(payload) != {"expected_queue_revision", "ordered_ids"} or not isinstance(payload["ordered_ids"], list):
                    raise QueueError("queue reorder requires exactly expected_queue_revision and ordered_ids")
                emit(ControlScheduler(control).reorder(payload["ordered_ids"], expected_queue_revision=payload["expected_queue_revision"]))
            elif args.action == "stations":
                from .control_store import ControlScheduler
                if args.show:
                    # Same shape as the socket route (topic_work included) so
                    # the documented view is transport-independent.
                    state = control.snapshot()
                    view = {"revision": state["revision"], "configuration": state["configuration"], "effective_checkpoint_profiles": control.effective_checkpoint_profiles(state), "assignments": state["work"].get("assignments", {}), "topic_work": state["work"].get("topics", {})}
                    emit(_stations_topic_view(view, args.topic_filter))
                else:
                    ids = [int(x) for x in args.ids.split(",")] if args.ids else None
                    intervals = [int(x) for x in args.intervals.split(",")] if args.intervals else None
                    emit(ControlScheduler(control).update_stations(station_ids=ids, all_stations=args.all, primary_profile=args.primary, secondary_profile=args.secondary, intervals=intervals, active_count=args.active_count))
            else:
                payload = load_json(Path(args.file))
                if args.action == "intake-submit": emit(service.submit_brief(payload))
                elif args.action == "intake-result": emit(service.record_discovery_result(payload))
                elif args.action == "intake-approve": emit(service.approve(payload))
                else:
                    from .checkpoints.service import apply_decision
                    from .input_schema import validate_checkpoint_decision
                    from .contract_publication import checkpoint_publisher
                    emit(apply_decision(control, validate_checkpoint_decision(payload), actor="cli-operator", publisher=checkpoint_publisher(root)))
        elif args.action == "new-topic":
            if ControlStore(root).exists:
                raise QueueError("managed roots require intake-submit; legacy new-topic cannot bypass controller admission")
            dest = Path(args.dest).expanduser().resolve() if args.dest else root / "topics"
            brief_text = (
                sys.stdin.read()
                if args.brief == "-"
                else Path(args.brief).read_text(encoding="utf-8")
            )
            result = topic_authoring.new_topic(
                args.topic_id,
                title=args.title,
                brief_text=brief_text,
                dest=dest,
                mode=args.mode,
            )
            emit(result)
        elif args.action == "discover":
            if ControlStore(root).exists:
                raise QueueError("managed roots require controller discovery registration; legacy discover cannot bypass admission")
            dest = Path(args.dest).expanduser().resolve() if args.dest else root / "topics"
            draft_dir = dest / args.topic_id
            if (draft_dir / "DRAFT-TOPIC.md").is_file():
                pass_title = f"Discovery: {args.topic_id}"
            elif (draft_dir / "TOPIC.md").is_file():
                # Approved contract: the chassis runs an operator-ordered
                # contract review pass (criteria check, propose-only) instead
                # of intake discovery.
                pass_title = f"Contract review: {args.topic_id}"
            else:
                raise QueueError(
                    f"{draft_dir} has neither DRAFT-TOPIC.md nor TOPIC.md -- "
                    "run `new-topic` first"
                )
            run_discovery = (
                Path(__file__).resolve().parent / "chassis" / "run-discovery.sh"
            )
            # Re-queueing a pass for the same topic is normal (a draft can be
            # re-discovered after edits; a contract can be re-reviewed) -- a
            # prior non-running pass item is replaced, never a blocker.
            try:
                existing = store.get(f"discovery.{args.topic_id}")
            except QueueError:
                existing = None
            if existing is not None and existing.get("status") != "running":
                store.remove(f"discovery.{args.topic_id}")
            emit(
                store.add(
                    title=pass_title,
                    cwd=str(draft_dir),
                    command=[str(run_discovery), str(draft_dir), args.agent_main],
                    item_id=f"discovery.{args.topic_id}",
                    usage_file="logs/latest-usage.json",
                    max_attempts=3,
                    lane="intake",
                )
            )
        elif args.action == "approve-topic":
            if ControlStore(root).exists:
                raise QueueError("managed roots require intake-approve; legacy approve-topic cannot bypass registration")
            dest = Path(args.dest).expanduser().resolve() if args.dest else root / "topics"
            emit(topic_authoring.approve_topic(args.topic_id, dest=dest))
        elif args.action == "add":
            if ControlStore(root).exists:
                raise QueueError("managed roots do not accept generic research add; submit an intake brief")
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            progress_command = None
            if args.progress_command:
                progress_command = json.loads(args.progress_command)
                if not isinstance(progress_command, list):
                    raise QueueError("progress_command must be a JSON array")
            on_completed_command = None
            if args.on_completed:
                on_completed_command = json.loads(args.on_completed)
                if not isinstance(on_completed_command, list):
                    raise QueueError("on_completed must be a JSON array")
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
                    on_completed_command=on_completed_command,
                    stall_limit=args.stall_limit,
                    max_attempts=args.max_attempts,
                    gap_policy=args.gap_policy,
                    gap_auto_limit=args.gap_auto_limit,
                    completion_lock=args.lock_sha256,
                    depends_on=depends_on,
                    internal_citations=args.internal_citations,
                    topic_refresh=args.topic_refresh,
                    topic_refresh_mode=args.topic_refresh_mode,
                    research_policy=_parse_research_policy(args.research_policy),
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
        elif args.action == "relock":
            item = store.get(args.item_id)
            lock = topic_authoring.compute_lock(Path(item["cwd"]))
            emit(store.set_completion_lock(args.item_id, lock))
        elif args.action == "research-policy":
            emit(store.set_research_policy(args.item_id, _parse_research_policy(args.policy)))
        elif args.action == "resolve-research":
            emit(store.resolve_research_blockers(args.item_id, reason=args.reason, sources=args.sources))
        elif args.action == "swap-active":
            emit(store.reassign_worker(args.worker, args.target_item_id))
        elif args.action == "refresh":
            emit(refresh_mod.apply_refresh(store, args.item_id, args.mode))
        elif args.action == "worker-policy":
            emit(
                store.configure_worker_policy(
                    args.worker,
                    claim_limit=None if args.continuous else args.claim_limit,
                )
            )
        elif args.action == "agents":
            raise QueueError(
                "`agents` is deprecated: agents are a worker (station) property, "
                "not a queue-item property. Use `worker-agents <worker> --main ... "
                "--secondary ... --model ... --flags ...` instead."
            )
        elif args.action == "worker-agents":
            emit(
                store.configure_worker_agents(
                    args.worker,
                    agent_main=args.agent_main,
                    agent_secondary=args.agent_secondary,
                    agent_model=args.agent_model,
                    agent_flags=args.agent_flags,
                    interval_seconds=args.interval_seconds,
                    clear=args.clear,
                )
            )
        elif args.action == "fleet":
            from .stations import StationsError

            try:
                if args.checkpoint_every is None and args.checkpoint_on_deepening is None:
                    emit(store.stations.fleet())
                else:
                    emit(
                        store.stations.configure_fleet(
                            checkpoint_every=args.checkpoint_every,
                            checkpoint_on_deepening=(
                                None
                                if args.checkpoint_on_deepening is None
                                else args.checkpoint_on_deepening == "on"
                            ),
                        )
                    )
            except StationsError as exc:
                raise QueueError(str(exc)) from exc
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
                store.set_lane_limit("intake", config.intake_max_active)
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
                        max_attempts=settings.max_attempts,
                        stall_limit=settings.stall_limit,
                        gap_policy=settings.gap_policy,
                        gap_auto_limit=settings.gap_auto_limit,
                        on_completed_command=settings.on_completed_command,
                        internal_citations=settings.internal_citations,
                        topic_refresh=settings.topic_refresh,
                        topic_refresh_mode=settings.topic_refresh_mode,
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
            dashboard_state = store.snapshot()
            # Station profiles live in the stations' own collective config,
            # not in queue state — attach them for the Models column.
            dashboard_state["station_profiles"] = store.stations.snapshot()["stations"]
            if store.control is not None:
                dashboard_state["managed_control"] = store.control.snapshot()
            content = render_dashboard(dashboard_state, ledger.events(), full=args.full)
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
            lanes = tuple(
                lane.strip() for lane in args.lanes.split(",") if lane.strip()
            )
            runner = LoopRunner(
                store,
                ledger,
                poll_seconds=args.poll_seconds,
                usage_command=usage_command,
                worker=args.worker,
                profile=args.profile,
                lanes=lanes,
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
