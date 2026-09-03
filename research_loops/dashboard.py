from __future__ import annotations

import html
import math
import os
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .queue import QueueError


_MARKDOWN_CONTROLS = frozenset("\\|`*_{}[]()#!+-.>")


def _cell(value: Any) -> str:
    text = " ".join(str(value if value is not None else "—").replace("\r", " ").replace("\n", " ").split())
    escaped = html.escape(text, quote=True)
    return "".join(f"\\{char}" if char in _MARKDOWN_CONTROLS else char for char in escaped)


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _metric(events: list[dict[str, Any]], key: str, *, nested: bool = False) -> tuple[float, int, int]:
    values: list[int | float] = []
    for event in events:
        source = event.get("usage") if nested else event
        if not isinstance(source, dict):
            continue
        value = _number(source.get(key))
        if value is not None:
            values.append(value)
    return float(sum(values)), len(values), len(events)


def _format_count(value: float) -> str:
    return f"{int(value):,}" if value.is_integer() else f"{value:,.2f}"


def _reported_total(total: float, covered: int, retained: int) -> str:
    if covered == 0:
        return f"unavailable (coverage 0/{retained})"
    return f"{_format_count(total)} reported (coverage {covered}/{retained})"


def _reported_average(total: float, covered: int, retained: int) -> str:
    if covered == 0:
        return f"unavailable (coverage 0/{retained})"
    return f"{_format_count(total / covered)} reported (coverage {covered}/{retained})"


def _duration_average(total: float, covered: int, retained: int) -> str:
    if covered == 0:
        return f"unavailable (coverage 0/{retained})"
    seconds = int(round(total / covered))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    duration = f"{hours}h {minutes}m {seconds}s" if hours else f"{minutes}m {seconds}s"
    return f"{duration} (coverage {covered}/{retained})"


def _table(headers: list[str], rows: Iterable[list[Any]]) -> str:
    rendered = [f"| {' | '.join(headers)} |", f"| {' | '.join('---' for _ in headers)} |"]
    count = 0
    for row in rows:
        rendered.append(f"| {' | '.join(_cell(value) for value in row)} |")
        count += 1
    if count == 0:
        rendered.append(f"| {' | '.join(['—'] + ['' for _ in headers[1:]])} |")
    return "\n".join(rendered)


def _profile_for(item: dict[str, Any], worker: str | None, events: list[dict[str, Any]]) -> str:
    if worker:
        for event in reversed(events):
            if event.get("worker") == worker and event.get("item_id") == item.get("id") and event.get("profile"):
                return str(event["profile"])
    command = item.get("command")
    if isinstance(command, list) and len(command) >= 3 and isinstance(command[2], str):
        return command[2]
    return "unavailable"


def _models(events: list[dict[str, Any]]) -> str:
    names = sorted(
        {
            str(usage["model"])
            for event in events
            if isinstance((usage := event.get("usage")), dict)
            and isinstance(usage.get("model"), str)
            and usage["model"].strip()
        }
    )
    return ", ".join(names) if names else "unavailable"


def _accepted_label(item: dict[str, Any]) -> str:
    accepted = item.get("accepted_by_workers")
    if not isinstance(accepted, list):
        return "none"
    workers = [str(worker) for worker in accepted if isinstance(worker, str)]
    return ", ".join(workers) if workers else "none"


def write_dashboard(output: str | Path, content: str) -> Path:
    """Atomically replace a dashboard file without following a target symlink."""
    path = Path(output).expanduser()
    parent = path.parent
    if path.is_symlink():
        raise QueueError("dashboard output must not be a symlink")
    if path.exists() and not path.is_file():
        raise QueueError("dashboard output must be a regular file")
    if not parent.exists() or not parent.is_dir():
        raise QueueError("dashboard output parent must be an existing directory")

    fd = -1
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=parent)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise QueueError(f"cannot write dashboard: {exc}") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    return path


def render_dashboard(
    state: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
) -> str:
    now = generated_at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    generated = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raw_items = state.get("items")
    items: list[Any] = raw_items if isinstance(raw_items, list) else []
    finished = [
        event
        for event in events
        if isinstance(event, dict)
        and event.get("type") == "process_finished"
        and isinstance(event.get("item_id"), str)
    ]
    by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in finished:
        by_item[event["item_id"]].append(event)

    categories: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            categories["unclassified"].append((position, {"id": "malformed item", "title": repr(item)}))
            continue
        status = item.get("status")
        desired = item.get("desired_state")
        owned = bool(item.get("claimed_by"))
        if item.get("lane") == "intake":
            # Intake work (discovery passes) is pipeline machinery, not
            # research output -- it never sits in the research tables.
            # "Intake" means work still waiting on the operator: a pass in
            # flight, or a finished pass whose topic is still an unapproved
            # draft. A finished pass whose topic got approved is history and
            # moves to the Completed-intakes table at the end of the doc.
            if item.get("status") == "completed" and not (
                isinstance(item.get("cwd"), str)
                and (Path(item["cwd"]) / "DRAFT-TOPIC.md").is_file()
            ):
                categories["intake_done"].append((position, item))
            else:
                categories["intake"].append((position, item))
            continue
        if status == "completed":
            category = "completed"
        elif status == "needs_attention":
            category = "needs_attention"
        elif status == "paused" or desired == "paused":
            category = "paused"
        elif status in {"running", "backoff"} and owned and desired in {"running", "stopping"}:
            # desired == "stopping": a graceful pause/swap was requested but
            # this iteration hasn't finished yet -- still genuinely active
            # until it lands (at which point desired becomes "paused").
            category = "active"
        elif status in {"queued", "backoff"} and not owned and desired == "running":
            category = "queued"
        else:
            category = "unclassified"
        categories[category].append((position, item))

    lines = [
        "# Research Loops Status",
        "",
        f"Generated: **{_cell(generated)}**  ",
        f"Queue revision: **{_cell(state.get('revision', 'unavailable'))}**  ",
        f"Queue globally paused: **{'yes' if state.get('paused') is True else 'no'}**",
        f"Queue globally stopping (graceful, in-flight iterations finishing first): "
        f"**{'yes' if state.get('stopping') is True else 'no'}**",
    ]
    if state.get("paused") is True or state.get("stopping") is True:
        lines.append(f"Pause reason: **{_cell(state.get('pause_reason') or 'not recorded')}**")
    lines.extend(
        [
            "",
            "> Queue state and event metrics are read under separate locks and are eventually consistent. "
            "Metrics are observations from the retained event ledger, not synchronized lifetime totals.",
            "",
            "## Overview",
            "",
            _table(
                ["Category", "Topics"],
                [[name.replace("_", " ").title(), len(categories[name])] for name in ("active", "queued", "completed", "needs_attention", "paused", "intake", "unclassified")],
            ),
        ]
    )

    worker_ids = {"worker-1"}
    policies = state.get("worker_policies")
    if isinstance(policies, dict):
        worker_ids.update(str(worker) for worker in policies)
    for _, item in enumerate(items):
        if isinstance(item, dict):
            if item.get("claimed_by"):
                worker_ids.add(str(item["claimed_by"]))
            accepted = item.get("accepted_by_workers")
            if isinstance(accepted, list):
                worker_ids.update(str(worker) for worker in accepted if isinstance(worker, str))
    for event in events:
        if isinstance(event, dict) and event.get("worker"):
            worker_ids.add(str(event["worker"]))

    worker_rows = []
    for worker in sorted(worker_ids):
        owned_items = [
            item
            for item in items
            if isinstance(item, dict) and item.get("claimed_by") == worker
        ]
        owned_item = next(
            (
                item
                for item in owned_items
                if item.get("status") in {"running", "backoff"}
                and item.get("desired_state") == "running"
            ),
            owned_items[0] if owned_items else None,
        )
        policy = policies.get(worker) if isinstance(policies, dict) and isinstance(policies.get(worker), dict) else {}
        limit = policy.get("claim_limit")
        intake = "continuous" if limit is None else f"finite {policy.get('claims_used', 0)}/{limit}"
        if owned_item is None:
            activity = "idle / no ownership"
            profile = "unavailable"
            topic = "—"
        else:
            activity = str(owned_item.get("status", "unclassified"))
            profile = _profile_for(owned_item, worker, events)
            topic = owned_item.get("title", owned_item.get("id", "unavailable"))
        worker_rows.append([worker, activity, topic, profile, intake])
    lines.extend(["", "## Workers", "", _table(["Worker", "Queue activity", "Owned topic", "Profile", "New-topic intake"], worker_rows)])

    active_rows = []
    for _, item in categories["active"]:
        attempts = item.get("attempts") if isinstance(item.get("attempts"), int) and not isinstance(item.get("attempts"), bool) else "unavailable"
        iteration = f"current {attempts}" if item.get("status") == "running" else (f"last {attempts}; next {attempts + 1}" if isinstance(attempts, int) else "unavailable")
        worker = item.get("claimed_by")
        active_rows.append([
            item.get("title", item.get("id")),
            worker,
            item.get("status"),
            iteration,
            _profile_for(item, str(worker) if worker else None, events),
            "running now"
            if item.get("status") == "running"
            else item.get("next_eligible_at") or "eligible now",
        ])
    lines.extend(["", "## Active topics", "", _table(["Topic", "Worker", "State", "Queue iteration", "Profile", "Next eligible"], active_rows)])

    queued_rows = [
        [position, item.get("title", item.get("id")), item.get("status"), item.get("attempts", "unavailable"), _accepted_label(item)]
        for position, item in categories["queued"]
    ]
    lines.extend(["", "## Queued topics", "", _table(["Queue position", "Topic", "State", "Attempts", "Previously accepted by"], queued_rows)])

    def _intake_rows(entries):
        return [
            [
                item.get("title", item.get("id")),
                item.get("status"),
                item.get("attempts", "unavailable"),
                item.get("claimed_by") or "—",
                item.get("finished_at") or "—",
            ]
            for _, item in entries
        ]

    lines.extend(["", "## Intake (awaiting the operator)", "", _table(["Item", "State", "Attempts", "Owner", "Finished"], _intake_rows(categories["intake"]))])

    completed_rows = []
    for _, item in categories["completed"]:
        retained = by_item.get(str(item.get("id")), [])
        calls_total, calls_covered, run_count = _metric(retained, "api_calls", nested=True)
        duration_total, duration_covered, _ = _metric(retained, "duration_seconds")
        token_total, token_covered, _ = _metric(retained, "total_tokens", nested=True)
        completed_rows.append([
            item.get("title", item.get("id")),
            item.get("attempts", "unavailable"),
            run_count,
            _reported_total(calls_total, calls_covered, run_count),
            _duration_average(duration_total, duration_covered, run_count),
            _reported_total(token_total, token_covered, run_count),
            _reported_average(token_total, token_covered, run_count),
            _models(retained),
            item.get("finished_at") or "unavailable",
        ])
    lines.extend(["", "## Completed topics", "", _table(["Topic", "Queue attempts", "Retained runs", "Interactions", "Avg duration / retained run", "Reported tokens", "Avg reported tokens / covered run", "Models observed", "Finished"], completed_rows)])

    def _attention_flags(item: dict[str, Any]) -> str:
        # Structured `flag:` lines (e.g. from a deferred-obligation STOP)
        # say exactly where to look; fall back to the error's first line.
        error = str(item.get("last_error") or "")
        flags = [line.strip()[5:].strip() for line in error.splitlines() if line.strip().startswith("flag:")]
        if flags:
            return "; ".join(flags)
        first = next((line.strip() for line in error.splitlines() if line.strip()), "")
        return first or "unavailable"

    attention_rows = [[item.get("title", item.get("id")), item.get("attempts", "unavailable"), item.get("last_error_kind") or "unavailable", _attention_flags(item), item.get("finished_at") or "unavailable"] for _, item in categories["needs_attention"]]
    paused_rows = [[item.get("title", item.get("id")), item.get("claimed_by") or "none", item.get("attempts", "unavailable"), item.get("last_error_kind") or "operator / unspecified"] for _, item in categories["paused"]]
    unclassified_rows = [[position, item.get("id", "unavailable"), item.get("title", "unavailable"), item.get("status", "unavailable"), item.get("desired_state", "unavailable"), item.get("claimed_by") or "none"] for position, item in categories["unclassified"]]
    lines.extend(["", "## Needs attention", "", _table(["Topic", "Attempts", "Reason class", "Flags (where to look)", "Finished"], attention_rows)])
    lines.extend(["", "## Paused topics", "", _table(["Topic", "Stale/current owner", "Attempts", "Reason class"], paused_rows)])
    if unclassified_rows:
        # A catch-all for malformed/unexpected queue states -- rendered only
        # when it actually caught something; an always-empty table is noise.
        lines.extend(["", "## Unclassified items", "", _table(["Queue position", "ID", "Title", "Status", "Desired state", "Owner"], unclassified_rows)])

    calls_total, calls_covered, retained_count = _metric(finished, "api_calls", nested=True)
    duration_total, duration_covered, _ = _metric(finished, "duration_seconds")
    token_total, token_covered, _ = _metric(finished, "total_tokens", nested=True)
    timestamps = sorted(str(event["ts"]) for event in finished if isinstance(event.get("ts"), str))
    current_ids = {str(item.get("id")) for item in items if isinstance(item, dict)}
    historical_only = sum(1 for event in finished if event["item_id"] not in current_ids)
    lines.extend(
        [
            "",
            "## Retained-ledger aggregate",
            "",
            _table(
                ["Metric", "Value"],
                [
                    ["Retained process_finished records", retained_count],
                    ["Recorded runner/API interactions", _reported_total(calls_total, calls_covered, retained_count)],
                    ["Average duration per retained run", _duration_average(duration_total, duration_covered, retained_count)],
                    ["Reported tokens", _reported_total(token_total, token_covered, retained_count)],
                    ["Average reported tokens per covered run", _reported_average(token_total, token_covered, retained_count)],
                    ["Events for IDs absent from current queue", historical_only],
                    ["Oldest retained process_finished", timestamps[0] if timestamps else "unavailable"],
                    ["Newest retained process_finished", timestamps[-1] if timestamps else "unavailable"],
                ],
            ),
            "",
            "## Completed intakes",
            "",
            _table(["Item", "Attempts", "Finished"], [
                [item.get("title", item.get("id")), item.get("attempts", "unavailable"), item.get("finished_at") or "unavailable"]
                for _, item in categories["intake_done"]
            ]),
            "",
            "## Metric definitions and coverage",
            "",
            "- **Queue iteration:** the queue-owned `attempts` counter. A running topic is on `attempts`; an owned cadence/backoff topic completed `attempts` and will next run `attempts + 1`.",
            "- **Interactions:** the sum of valid, non-negative `usage.api_calls` values. These are recorded runner/API calls, not messages or conversational turns.",
            "- **Duration:** elapsed process time from valid, non-negative `duration_seconds`, displayed in seconds-derived wall-clock units.",
            "- **Reported tokens:** valid, non-negative `usage.total_tokens`. Provider semantics can include input, output, cache, and delegated work; this is not a dollar charge.",
            "- **Coverage:** `covered/retained runs`. Missing or invalid metrics are unavailable and are never silently counted as zero.",
            "- **Retention:** the event ledger has a maximum retention age of 90 days; the actual oldest/newest timestamps above define this dashboard's observed window.",
            "- **Identity limitation:** retained events are grouped by current `item_id`; IDs and attempt numbers are not immutable run-incarnation keys and can be reused or reset.",
            "- **Consistency limitation:** queue state is finalized before the corresponding event is appended. A refresh may temporarily show newer queue state or newer event data than the other source.",
            "",
            "_Generated file. Manual edits are replaced by the next dashboard refresh._",
            "",
        ]
    )
    return "\n".join(lines)
