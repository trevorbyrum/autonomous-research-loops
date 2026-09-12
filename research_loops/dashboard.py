from __future__ import annotations

import html
import re
import math
import os
import statistics
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


def _station_models(state: dict[str, Any], worker: Any, item: dict[str, Any],
                    events: list[dict[str, Any]]) -> str:
    """`1st: x, 2nd: y` from the claiming station's profile.

    The profile is what actually runs the iteration (queue items carry no
    binding). The secondary is stored as a full delegate command line, so its
    model is extracted from the --model/-m flag; a delegate with no model flag
    falls back to its first token (the bare CLI name).
    """
    profile = (state.get("station_profiles") or {}).get(str(worker)) or {}
    primary = profile.get("agent_model") or profile.get("agent_main") or _profile_for(
        item, str(worker) if worker else None, events
    )
    secondary = "—"
    raw = profile.get("agent_secondary") or ""
    if raw:
        match = re.search(r"(?:--model|-m)[ =](\S+)", raw)
        secondary = match.group(1) if match else raw.split()[0]
    return f"1st: {primary}, 2nd: {secondary}"


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


# The moment the saturation regime went live (workers restarted onto the
# saturation-gate runner, 2026-09-03). Iteration economics deliberately
# ignores everything before it: pre-saturation iterations ran under exit
# semantics the operator ruled inadequate, so they would poison any
# planning ballpark for what topics cost under the current engine.
SATURATION_EPOCH = "2026-09-03T13:51:51"


def _iteration_economics(
    items: list[Any], by_item: dict[str, list[dict[str, Any]]]
) -> list[list[Any]] | None:
    """Fleet-global iteration economics, saturation-era + productive only.

    Productive = the chassis-measured semantic signature changed during the
    run. Only events at or after SATURATION_EPOCH count at all. The
    per-obligation ratio is stricter still: it includes only topics whose
    ENTIRE recorded history is post-epoch, so no obligation resolved under
    the old exit semantics (or inherited from migration) is priced in.
    """
    import json as _json
    all_durations: list[float] = []
    total_classified = 0
    total_productive = 0
    per_topic_ratios: list[float] = []
    ratio_productive = 0
    ratio_resolved = 0
    pre_era_topics = 0
    for item in items:
        if not isinstance(item, dict) or item.get("lane") == "intake":
            continue
        cwd = item.get("cwd")
        if not isinstance(cwd, str):
            continue
        state_path = Path(cwd) / "SEMANTIC-STATE.json"
        if not state_path.is_file():
            continue
        try:
            state = _json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        obligations = [o for o in state.get("obligations", []) if isinstance(o, dict)]
        if not obligations:
            continue
        events = by_item.get(str(item.get("id")), [])
        stamped = [e for e in events if isinstance(e.get("ts"), str)]
        era = [e for e in stamped if e["ts"] >= SATURATION_EPOCH]
        classified = [
            e for e in era
            if isinstance(e.get("iteration_result"), dict)
            and isinstance(e["iteration_result"].get("signature_changed"), bool)
        ]
        productive = [e for e in classified if e["iteration_result"]["signature_changed"]]
        total_classified += len(classified)
        total_productive += len(productive)
        all_durations.extend(
            d for e in productive
            if (d := _number(e.get("duration_seconds"))) is not None
        )
        fully_post_epoch = bool(era) and len(era) == len(stamped)
        if not fully_post_epoch:
            if stamped:
                pre_era_topics += 1
            continue
        terminal = sum(
            1 for o in obligations
            if o.get("disposition") in ("supported", "contradicted", "unresolved", "deferred")
        )
        if terminal and productive:
            per_topic_ratios.append(len(productive) / terminal)
            ratio_productive += len(productive)
            ratio_resolved += terminal
    if not all_durations and not per_topic_ratios:
        return None

    def _fmt(seconds: float) -> str:
        m, s = divmod(int(round(seconds)), 60)
        return f"{m}m {s}s"

    rows: list[list[Any]] = []
    if all_durations:
        srt = sorted(all_durations)
        rows.append([
            "Productive iteration duration",
            f"{_fmt(srt[0])} min / {_fmt(statistics.median(srt))} median / "
            f"{_fmt(srt[-1])} max / {_fmt(sum(srt) / len(srt))} avg (n={len(srt)})",
        ])
    if total_classified:
        rows.append([
            "Productive share of iterations",
            f"{total_productive}/{total_classified} ({total_productive / total_classified:.0%})",
        ])
    if per_topic_ratios:
        srt = sorted(per_topic_ratios)
        rows.append([
            "Productive iterations per resolved obligation",
            f"{ratio_productive / ratio_resolved:.1f} overall / "
            f"{srt[0]:.1f} min / {statistics.median(srt):.1f} median / {srt[-1]:.1f} max "
            f"(over {len(per_topic_ratios)} fully-saturation-era topics)",
        ])
    else:
        rows.append([
            "Productive iterations per resolved obligation",
            "no fully-saturation-era topic has resolved obligations yet "
            "(populates as the current queue front completes)",
        ])
    rows.append([
        "Scope",
        f"iterations since {SATURATION_EPOCH}Z only; earlier eras excluded; "
        f"{pre_era_topics} topics with pre-era history excluded from the ratio",
    ])
    return rows


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
    full: bool = False,
) -> str:
    """Default output is an operator STATUS page: what runs, what awaits a
    decision, what owes a checkpoint, what needs attention. History and
    telemetry (paused/completed enumerations, economics, ledger aggregates,
    metric definitions) render only with full=True — the 2026-09-09 operator
    ruling: the per-minute page must lead with the actionable sections."""
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
    managed = state.get("managed_control")
    # ONE normalization point for managed control data (Astra F11/R2-4):
    # every consumer below reads these validated maps, and any malformed
    # piece degrades to a visible notice instead of an AttributeError that
    # stops the refresh exactly when control state needs inspection.
    managed_malformed: list[str] = []

    def _note_malformed(label: str) -> None:
        if label not in managed_malformed:
            managed_malformed.append(label)

    def _managed_map(container: Any, name: str) -> dict[str, Any]:
        # A key that is PRESENT but not a mapping — including an explicit
        # null — is malformed and noticed; a genuinely absent key is quiet.
        if not isinstance(container, dict) or name not in container:
            return {}
        value = container[name]
        if not isinstance(value, dict):
            _note_malformed(name)
            return {}
        if any(not isinstance(row, dict) for row in value.values()):
            # Row consumers skip non-dict rows; a corrupt proposal or episode
            # must not silently vanish from an actionable section (R3-2).
            _note_malformed(f"{name} rows")
        return value

    if isinstance(managed, dict):
        work_raw = managed.get("work")
        if "work" in managed and not isinstance(work_raw, dict):
            _note_malformed("work")
        managed_work: dict[str, Any] = work_raw if isinstance(work_raw, dict) else {}
        managed_topics_map = _managed_map(managed_work, "topics")
        managed_episodes_map = _managed_map(managed_work, "episodes")
        managed_proposals_map = _managed_map(managed_work, "proposals")
    else:
        managed_work = {}
        managed_topics_map = managed_episodes_map = managed_proposals_map = {}
    if isinstance(managed, dict):
        config = managed.get("configuration") if isinstance(managed.get("configuration"), dict) else {}
        policy = config.get("checkpoints") or {}
        # executing_station: reviews use the claiming station's own pair;
        # station 1's is shown as the representative default.
        pair = (next((row for row in config.get("stations", []) if row.get("id") == 1), {})
                if policy.get("agent_source") in {"station_1", "executing_station"} else policy)
        checkpoint_summary = "off"
        if policy.get("enabled"):
            checkpoint_summary = f"every {policy.get('every_research_iterations', '—')} completed iterations"
            if policy.get("on_deepening_entry"):
                checkpoint_summary += " + deepening"
        lines.extend(["", f"**Stations:** {_cell(config.get('active_count', '—'))}/5 enabled · "
            f"**Checkpoints:** {_cell(checkpoint_summary)} · "
            f"**Review agents:** {_cell(pair.get('primary_profile', '—'))} / {_cell(pair.get('secondary_profile', '—'))}"])
        # Keep actionable review holds visible without dumping the work ledger.
        topics = managed_topics_map
        episodes = managed_episodes_map
        for item in items:
            if not isinstance(item, dict) or item.get("lane") == "intake" or item.get("status") in {"paused", "completed"}:
                continue
            topic = topics.get(item.get("id"))
            topic = topic if isinstance(topic, dict) else {}
            episode = episodes.get(topic.get("active_episode_id"))
            episode = episode if isinstance(episode, dict) else {}
            if episode.get("state") in {"awaiting_operator", "needs_attention", "publishing_decision"}:
                label = {"awaiting_operator": "checkpoint decision needed", "needs_attention": "checkpoint needs attention", "publishing_decision": "checkpoint decision applying"}[episode["state"]]
                lines.extend(["", f"**{_cell(item.get('title', item.get('id')))}:** {label}."])
    overview_lines = [
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

    active_rows = []
    managed_topics = managed_topics_map
    for _, item in categories["active"]:
        attempts = item.get("attempts") if isinstance(item.get("attempts"), int) and not isinstance(item.get("attempts"), bool) else "unavailable"
        ledger = managed_topics.get(item.get("id")) if isinstance(managed_topics, dict) else None
        if isinstance(ledger, dict):
            episode_id = ledger.get("active_episode_id")
            episode = managed_episodes_map.get(episode_id) if episode_id else None
            episode = episode if isinstance(episode, dict) else None
            if isinstance(episode, dict) and episode.get("state") in {"due", "checkpoint_running", "retry_wait", "awaiting_operator", "publishing_decision"}:
                iteration = f"Checkpoint after {ledger.get('research_iterations_completed', '—')}"
            else:
                suffix = "" if item.get("status") == "running" else " (next)"
                iteration = f"{ledger.get('next_research_ordinal', '—')}{suffix}"
        elif isinstance(managed, dict):
            iteration = "research accounting unavailable"
        else:
            iteration = f"current {attempts}" if item.get("status") == "running" else (f"last {attempts}; next {attempts + 1}" if isinstance(attempts, int) else "unavailable")
        worker = item.get("claimed_by")
        active_row = [
            item.get("title", item.get("id")),
            worker,
            iteration,
        ]
        if isinstance(managed, dict):
            reviewed = [episode.get("triggered_after_research_iteration")
                        for episode in managed_episodes_map.values()
                        if isinstance(episode, dict)
                        and episode.get("topic_id") == item.get("id")
                        and episode.get("state") in {"complete_without_proposals", "complete_with_decisions"}
                        and isinstance(episode.get("triggered_after_research_iteration"), int)]
            active_row.append(max(reviewed) if reviewed else "—")
        active_row.append(_station_models(state, worker, item, events))
        active_rows.append(active_row)
    active_label = "Iteration" if isinstance(managed, dict) else "Queue iteration"
    active_headers = ["Topic", "Station" if isinstance(managed, dict) else "Worker", active_label]
    if isinstance(managed, dict):
        active_headers.append("Last checkpoint")
    active_headers.append("Models")
    lines.extend(["", "## Active topics", "", _table(active_headers, active_rows)])
    if isinstance(managed, dict):
        # The status page must render precisely when control state most needs
        # inspection (Astra F11/R2-4): every malformed piece collected by the
        # one normalization point becomes a visible notice, never a crash.
        if managed_malformed:
            lines.extend(["", "> **Managed work data malformed/unavailable** "
                              f"({', '.join(managed_malformed)}): the sections below may be incomplete; "
                              "inspect the controller state directly."])
        proposals_map = managed_proposals_map
        topics_map = managed_topics_map
        titles = {str(item.get("id")): str(item.get("title") or item.get("id"))
                  for item in items if isinstance(item, dict)}
        # THE actionable section: proposals a checkpoint issued that only the
        # operator can resolve. Always rendered, even when empty.
        pending_rows = [[titles.get(str(p.get("topic_id")), str(p.get("topic_id"))),
                         p.get("proposal_id"), p.get("kind"), p.get("proposal_version"),
                         p.get("episode_id")]
                        for p in proposals_map.values()
                        if isinstance(p, dict) and p.get("status") == "pending"]
        lines.extend(["", "## Pending checkpoint proposals (awaiting your decision)", "",
                      _table(["Topic", "Proposal", "Kind", "Version", "Episode"], pending_rows)])
        if pending_rows:
            lines.append("Resolve with `research-loops checkpoint-decide --file decision.json` "
                         "(see docs/managed-stations.md).")
        # Deliberately no "checkpoint debt" table (operator request 2026-09-11):
        # a topic owing a review is routine, automatic, and self-resolving —
        # not an operator decision, and listing it here read as one. The only
        # actionable checkpoint state is a pending proposal, above.
    lines.extend(overview_lines)

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

    queued_rows = [
        [position, item.get("title", item.get("id")), item.get("attempts", "unavailable")]
        for position, item in categories["queued"]
    ]
    lines.extend(["", "## Queued topics", "", _table(["Queue position", "Topic", "Attempts"], queued_rows)])

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
        _, _, run_count = _metric(retained, "api_calls", nested=True)
        # Interactions/duration/token/model detail belongs in STATS.md
        # (operator ruling 2026-09-04) -- STATUS.md keeps the identity row.
        completed_rows.append([
            item.get("title", item.get("id")),
            item.get("attempts", "unavailable"),
            run_count,
            item.get("finished_at") or "unavailable",
        ])
    lines.extend(["", "## Completed topics", "", _table(["Topic", "Queue attempts", "Retained runs", "Finished"], completed_rows)])
    if full:
        lines.extend(["", "## Paused topics", "", _table(["Topic", "Stale/current owner", "Attempts", "Reason class"], paused_rows)])
    else:
        lines.extend(["", f"_History elided: {len(paused_rows)} paused topics, "
                          "plus economics/ledger telemetry — regenerate with `dashboard --full` to include them._"])
    if unclassified_rows:
        # A catch-all for malformed/unexpected queue states -- rendered only
        # when it actually caught something; an always-empty table is noise.
        lines.extend(["", "## Unclassified items", "", _table(["Queue position", "ID", "Title", "Status", "Desired state", "Owner"], unclassified_rows)])

    economics_rows = _iteration_economics(items, by_item) if full else []
    if economics_rows:
        lines.extend([
            "",
            "## Iteration economics (saturation era, productive iterations only)",
            "",
            _table(["Metric", "Value"], economics_rows),
        ])

    calls_total, calls_covered, retained_count = _metric(finished, "api_calls", nested=True)
    duration_total, duration_covered, _ = _metric(finished, "duration_seconds")
    token_total, token_covered, _ = _metric(finished, "total_tokens", nested=True)
    timestamps = sorted(str(event["ts"]) for event in finished if isinstance(event.get("ts"), str))
    current_ids = {str(item.get("id")) for item in items if isinstance(item, dict)}
    historical_only = sum(1 for event in finished if event["item_id"] not in current_ids)
    if full:
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
            "- **Productive iteration:** the chassis-measured semantic signature changed during the run (`iteration_result.signature_changed`). Iteration economics counts only events since the saturation regime went live; idle passes and pre-instrumentation events are excluded, and the per-obligation ratio uses only topics whose entire history is saturation-era.",
            "- **Retention:** the event ledger has a maximum retention age of 90 days; the actual oldest/newest timestamps above define this dashboard's observed window.",
            "- **Identity limitation:** retained events are grouped by current `item_id`; IDs and attempt numbers are not immutable run-incarnation keys and can be reused or reset.",
            "- **Consistency limitation:** queue state is finalized before the corresponding event is appended. A refresh may temporarily show newer queue state or newer event data than the other source.",
        ]
        )
    lines.extend([
        "",
        "_Generated file. Manual edits are replaced by the next dashboard refresh._",
        "",
    ])
    return "\n".join(lines)
