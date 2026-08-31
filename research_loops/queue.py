from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class QueueError(RuntimeError):
    pass


class QueueConflict(QueueError):
    pass


_ITEM_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

GAP_POLICIES = ("review", "auto")


def validate_item_id(item_id: str) -> str:
    if not _ITEM_ID_PATTERN.fullmatch(item_id):
        raise QueueError(
            "item id must be 1-128 characters using only letters, numbers, '.', '_' or '-' "
            "and must start with a letter or number"
        )
    return item_id


def _validate_agent_name(value: str | None, field: str) -> str | None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise QueueError(f"{field} must be a non-empty string")
    return value


def _validate_gap_policy(value: str) -> str:
    if value not in GAP_POLICIES:
        raise QueueError(f"gap_policy must be one of {list(GAP_POLICIES)}")
    return value


def _validate_gap_auto_limit(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise QueueError("gap_auto_limit must be a non-negative integer")
    return value


_LOCK_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def _validate_completion_lock(value: str | None) -> str | None:
    if value is not None and not _LOCK_PATTERN.fullmatch(value):
        raise QueueError(
            "completion_lock must be a 64-character lowercase hex SHA-256, as printed "
            "by `chassis/semantic-state.py lock` or `tools/approve-topic`"
        )
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class QueueStore:
    """Atomic, process-safe JSON queue storage."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.state_dir = self.root / "state"
        self.path = self.state_dir / "queue.json"
        self.lock_path = self.state_dir / "queue.lock"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            if not self.path.exists():
                self._write_unlocked(self._empty_state())
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        now = utc_now()
        return {
            "version": 1,
            "revision": 0,
            "paused": False,
            "pause_reason": None,
            "created_at": now,
            "updated_at": now,
            "worker_policies": {},
            "items": [],
        }

    @contextmanager
    def _locked(self) -> Iterator[dict[str, Any]]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state = json.loads(self.path.read_text(encoding="utf-8"))
            before = copy.deepcopy(state)
            yield state
            if state != before:
                state["revision"] += 1
                state["updated_at"] = utc_now()
                self._write_unlocked(state)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _write_unlocked(self, state: dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="queue-", suffix=".json", dir=self.state_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def snapshot(self) -> dict[str, Any]:
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
            state = json.loads(self.path.read_text(encoding="utf-8"))
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return copy.deepcopy(state)

    def get(self, item_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._find(self.snapshot(), item_id))

    @staticmethod
    def _find(state: dict[str, Any], item_id: str) -> dict[str, Any]:
        for item in state["items"]:
            if item["id"] == item_id:
                return item
        raise QueueError(f"unknown queue item: {item_id}")

    def add(
        self,
        *,
        title: str,
        cwd: str,
        command: list[str],
        item_id: str | None = None,
        provider: str | None = None,
        usage_file: str | None = None,
        max_attempts: int = 5,
        repeat_seconds: int | None = None,
        stop_file: str | None = None,
        completion_command: list[str] | None = None,
        progress_command: list[str] | None = None,
        stall_limit: int | None = None,
        depends_on: list[str] | None = None,
        agent_main: str | None = None,
        agent_secondary: str | None = None,
        gap_policy: str = "review",
        gap_auto_limit: int = 0,
        completion_lock: str | None = None,
    ) -> dict[str, Any]:
        if not title.strip() or not command:
            raise QueueError("title and command are required")
        if max_attempts < 1:
            raise QueueError("max_attempts must be at least 1")
        if repeat_seconds is not None and repeat_seconds <= 0:
            raise QueueError("repeat_seconds must be positive")
        if stall_limit is not None and stall_limit < 1:
            raise QueueError("stall_limit must be at least 1")
        _validate_agent_name(agent_main, "agent_main")
        _validate_agent_name(agent_secondary, "agent_secondary")
        _validate_gap_policy(gap_policy)
        _validate_gap_auto_limit(gap_auto_limit)
        _validate_completion_lock(completion_lock)
        resolved_item_id = validate_item_id(
            item_id if item_id is not None else f"loop-{uuid.uuid4().hex[:10]}"
        )
        resolved_dependencies = [validate_item_id(value) for value in (depends_on or [])]
        if resolved_item_id in resolved_dependencies:
            raise QueueError("an item cannot depend on itself")
        if len(resolved_dependencies) != len(set(resolved_dependencies)):
            raise QueueError("depends_on must not contain duplicates")
        now = utc_now()
        item = {
            "id": resolved_item_id,
            "title": title.strip(),
            "cwd": str(Path(cwd).expanduser().resolve()),
            "command": list(command),
            "provider": provider,
            "usage_file": usage_file,
            "stop_file": stop_file,
            "completion_command": (
                list(completion_command) if completion_command else None
            ),
            "depends_on": resolved_dependencies,
            "progress_command": list(progress_command) if progress_command else None,
            "stall_limit": stall_limit,
            "agent_main": agent_main,
            "agent_secondary": agent_secondary,
            "gap_policy": gap_policy,
            "gap_auto_limit": gap_auto_limit,
            "completion_lock": completion_lock,
            "progress_signature": None,
            "stall_count": 0,
            "status": "queued",
            "desired_state": "running",
            "attempts": 0,
            "consecutive_failures": 0,
            "subscription_limit_failures": 0,
            "max_attempts": max_attempts,
            "repeat_seconds": repeat_seconds,
            "next_eligible_at": None,
            "last_error": None,
            "last_error_kind": None,
            "restart_generation": 0,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
            "last_pid": None,
            "last_pid_fingerprint": None,
            "accepted_by_workers": [],
        }
        with self._locked() as state:
            if any(existing["id"] == item["id"] for existing in state["items"]):
                raise QueueConflict(f"duplicate queue item: {item['id']}")
            state["items"].append(item)
        return copy.deepcopy(item)

    def move(self, item_id: str, position: int) -> dict[str, Any]:
        with self._locked() as state:
            item = self._find(state, item_id)
            state["items"].remove(item)
            bounded = max(0, min(position, len(state["items"])))
            state["items"].insert(bounded, item)
            item["updated_at"] = utc_now()
        return copy.deepcopy(item)

    # Fields an operator manifest is allowed to (re)define. Everything else —
    # status, attempts, failure counters, timestamps, error history — is runtime
    # history and is NEVER touched by sync.
    _DEFINITION_FIELDS = (
        "title",
        "cwd",
        "command",
        "provider",
        "usage_file",
        "max_attempts",
        "repeat_seconds",
        "stop_file",
        "completion_command",
        "depends_on",
        "progress_command",
        "stall_limit",
        "agent_main",
        "agent_secondary",
        "gap_policy",
        "gap_auto_limit",
        "completion_lock",
    )

    # completion_lock is deliberately absent from _TOPIC_CONFIG_FIELDS: it's an
    # approval-time decision from `approve-topic`/`semantic-state.py lock`, not
    # a scheduling knob — changing it goes through `add` or `sync` (both of
    # which the item's own history-preserving discipline already covers), not
    # casual config-apply reconfiguration. sync() also protects it exactly like
    # `command`: never silently changed under a running item.

    # Fields configure_topic() may adjust on an existing item without ever
    # touching command/cwd/title/depends_on — these only affect the NEXT
    # iteration's environment, never an in-flight subprocess, so they're safe
    # to change regardless of the item's current status.
    _TOPIC_CONFIG_FIELDS = (
        "repeat_seconds",
        "max_attempts",
        "stall_limit",
        "agent_main",
        "agent_secondary",
        "gap_policy",
        "gap_auto_limit",
    )

    def sync(
        self, manifest_items: list[dict[str, Any]], *, prune: bool = False
    ) -> dict[str, Any]:
        """Reconcile the queue with a manifest without destroying history.

        This is the ONLY sanctioned way to bulk-reshape the queue. Unlike
        remove+re-add (which wipes attempts, timestamps, and error history —
        the failure mode this method exists to prevent), sync:

        - updates definition fields of existing items in place;
        - refuses to change the command of a currently RUNNING item
          (reported under ``skipped``, everything else still applies);
        - appends unknown manifest ids as new queued items;
        - reorders items to manifest order (non-manifest items keep their
          relative order after the manifest block);
        - with ``prune=True``, removes non-running items absent from the
          manifest (running items are never pruned; reported as skipped).

        Returns a report: {added, updated, reordered, pruned, skipped}.
        """
        manifest_ids: list[str] = []
        by_id: dict[str, dict[str, Any]] = {}
        definitions: dict[str, dict[str, Any]] = {}
        for entry in manifest_items:
            if not isinstance(entry, dict):
                raise QueueError("every manifest item must be a JSON object")
            entry_id = validate_item_id(str(entry.get("id", "")))
            if entry_id in by_id:
                raise QueueError(f"duplicate manifest item: {entry_id}")
            if not str(entry.get("title", "")).strip():
                raise QueueError(f"manifest item {entry_id} needs a non-empty title")
            # Validate the full definition up front so a malformed later entry
            # cannot leave the queue partially synced.
            try:
                definitions[entry_id] = self._definition_from(entry)
            except QueueError as exc:
                raise QueueError(f"manifest item {entry_id}: {exc}") from exc
            manifest_ids.append(entry_id)
            by_id[entry_id] = entry

        report: dict[str, Any] = {
            "added": [],
            "updated": [],
            "reordered": False,
            "pruned": [],
            "skipped": [],
        }
        with self._locked() as state:
            existing_ids = {item["id"] for item in state["items"]}
            available_ids = existing_ids | set(manifest_ids)
            for entry_id, definition in definitions.items():
                for dependency in definition["depends_on"]:
                    if dependency not in available_ids:
                        raise QueueError(
                            f"manifest item {entry_id} depends on missing item {dependency}"
                        )
            graph = {
                item["id"]: list(
                    definitions.get(item["id"], {}).get(
                        "depends_on", item.get("depends_on", [])
                    )
                )
                for item in state["items"]
            }
            graph.update(
                {
                    entry_id: list(definition["depends_on"])
                    for entry_id, definition in definitions.items()
                }
            )
            visiting: set[str] = set()
            visited: set[str] = set()

            def visit(item_id: str) -> None:
                if item_id in visiting:
                    raise QueueError(f"dependency cycle includes {item_id}")
                if item_id in visited:
                    return
                visiting.add(item_id)
                for dependency in graph.get(item_id, []):
                    visit(dependency)
                visiting.remove(item_id)
                visited.add(item_id)

            for entry_id in graph:
                visit(entry_id)
            now = utc_now()

            for item in state["items"]:
                entry = by_id.get(item["id"])
                if entry is None:
                    continue
                desired = dict(definitions[item["id"]])
                current = {field: item.get(field) for field in self._DEFINITION_FIELDS}
                if desired == current:
                    continue
                protected_changes = []
                if desired["command"] != current["command"]:
                    protected_changes.append(("command", "command"))
                if desired["depends_on"] != current["depends_on"]:
                    protected_changes.append(("depends_on", "dependencies"))
                if desired["completion_lock"] != current["completion_lock"]:
                    protected_changes.append(("completion_lock", "completion lock"))
                if item["status"] == "running" and protected_changes:
                    labels = " and ".join(label for _, label in protected_changes)
                    report["skipped"].append(
                        {
                            "id": item["id"],
                            "reason": (
                                f"running; {labels} NOT changed. To apply: wait for or "
                                "pause/stop this item, then run sync again — restart alone "
                                "does not apply the new definition."
                            ),
                        }
                    )
                    for field, _ in protected_changes:
                        desired[field] = current[field]
                    if desired == current:
                        continue
                item.update(desired)
                item["updated_at"] = now
                report["updated"].append(item["id"])

            for entry_id in manifest_ids:
                if entry_id in existing_ids:
                    continue
                definition = definitions[entry_id]
                item = {
                    "id": entry_id,
                    **definition,
                    "status": "queued",
                    "desired_state": "running",
                    "attempts": 0,
                    "consecutive_failures": 0,
                    "subscription_limit_failures": 0,
                    "next_eligible_at": None,
                    "last_error": None,
                    "last_error_kind": None,
                    "restart_generation": 0,
                    "created_at": now,
                    "updated_at": now,
                    "started_at": None,
                    "finished_at": None,
                    "last_pid": None,
                    "last_pid_fingerprint": None,
                    "progress_signature": None,
                    "stall_count": 0,
                }
                state["items"].append(item)
                report["added"].append(entry_id)

            if prune:
                kept = []
                for item in state["items"]:
                    if item["id"] in by_id:
                        kept.append(item)
                    elif item["status"] == "running":
                        report["skipped"].append(
                            {"id": item["id"], "reason": "running; never pruned"}
                        )
                        kept.append(item)
                    else:
                        report["pruned"].append(item["id"])
                state["items"] = kept

            order = {entry_id: index for index, entry_id in enumerate(manifest_ids)}
            before_order = [item["id"] for item in state["items"]]
            before_index = {item_id: idx for idx, item_id in enumerate(before_order)}
            state["items"].sort(
                key=lambda item: (
                    order.get(item["id"], len(order)),
                    before_index.get(item["id"], len(before_index)),
                )
            )
            report["reordered"] = [item["id"] for item in state["items"]] != before_order
        return report

    @staticmethod
    def _definition_from(entry: dict[str, Any]) -> dict[str, Any]:
        command = entry.get("command")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part.strip() for part in command)
        ):
            raise QueueError(
                "command must be a non-empty JSON array of non-empty strings "
                "(a bare string would be split into characters)"
            )
        max_attempts = entry.get("max_attempts", 5)
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts < 1:
            raise QueueError("max_attempts must be an integer of at least 1")
        repeat_seconds = entry.get("repeat_seconds")
        if repeat_seconds is not None and (
            not isinstance(repeat_seconds, int)
            or isinstance(repeat_seconds, bool)
            or repeat_seconds <= 0
        ):
            raise QueueError("repeat_seconds must be a positive integer")
        progress_command = entry.get("progress_command")
        if progress_command is not None and (
            not isinstance(progress_command, list)
            or not progress_command
            or not all(isinstance(part, str) and part.strip() for part in progress_command)
        ):
            raise QueueError(
                "progress_command must be a non-empty JSON array of non-empty strings"
            )
        completion_command = entry.get("completion_command")
        if completion_command is not None and (
            not isinstance(completion_command, list)
            or not completion_command
            or not all(
                isinstance(part, str) and part.strip()
                for part in completion_command
            )
        ):
            raise QueueError(
                "completion_command must be a non-empty JSON array of non-empty strings"
            )
        depends_on = entry.get("depends_on", [])
        if not isinstance(depends_on, list) or any(
            not isinstance(dependency, str) for dependency in depends_on
        ):
            raise QueueError("depends_on must be an array of item ids")
        resolved_dependencies = [validate_item_id(value) for value in depends_on]
        if entry["id"] in resolved_dependencies:
            raise QueueError("an item cannot depend on itself")
        if len(resolved_dependencies) != len(set(resolved_dependencies)):
            raise QueueError("depends_on must not contain duplicates")
        stall_limit = entry.get("stall_limit")
        if stall_limit is not None and (
            not isinstance(stall_limit, int)
            or isinstance(stall_limit, bool)
            or stall_limit < 1
        ):
            raise QueueError("stall_limit must be an integer of at least 1")
        agent_main = _validate_agent_name(entry.get("agent_main"), "agent_main")
        agent_secondary = _validate_agent_name(
            entry.get("agent_secondary"), "agent_secondary"
        )
        gap_policy = _validate_gap_policy(entry.get("gap_policy", "review"))
        gap_auto_limit = _validate_gap_auto_limit(entry.get("gap_auto_limit", 0))
        completion_lock = _validate_completion_lock(entry.get("completion_lock"))
        return {
            "title": str(entry["title"]).strip(),
            "cwd": str(Path(str(entry["cwd"])).expanduser().resolve()),
            "command": list(command),
            "provider": entry.get("provider"),
            "usage_file": entry.get("usage_file"),
            "max_attempts": max_attempts,
            "repeat_seconds": repeat_seconds,
            "stop_file": entry.get("stop_file"),
            "completion_command": (
                list(completion_command) if completion_command else None
            ),
            "depends_on": resolved_dependencies,
            "progress_command": list(progress_command) if progress_command else None,
            "stall_limit": stall_limit,
            "agent_main": agent_main,
            "agent_secondary": agent_secondary,
            "gap_policy": gap_policy,
            "gap_auto_limit": gap_auto_limit,
            "completion_lock": completion_lock,
        }

    def configure_topic(self, item_id: str, **settings: Any) -> dict[str, Any]:
        """Apply a partial scheduling/agent/gap-policy update to one item.

        Unlike sync(), this never requires or touches command/cwd/title/
        depends_on, and never refuses a running item — every field here only
        takes effect on the item's NEXT iteration, never an in-flight one.
        Used by `research-loops config apply` (see research_loops/config.py)
        and by the `config topic` CLI verb for one-off changes.
        """
        unknown = set(settings) - set(self._TOPIC_CONFIG_FIELDS)
        if unknown:
            raise QueueError(f"unknown topic config field(s): {sorted(unknown)}")
        with self._locked() as state:
            item = self._find(state, item_id)
            candidate = {**item, **settings}
            validated = self._definition_from({**candidate, "id": item_id})
            changed = False
            for field in self._TOPIC_CONFIG_FIELDS:
                if field in settings and item.get(field) != validated[field]:
                    item[field] = validated[field]
                    changed = True
            if changed:
                item["updated_at"] = utc_now()
            return copy.deepcopy(item)

    def record_progress_signature(
        self, item_id: str, signature: str | None
    ) -> tuple[int, dict[str, Any]]:
        """Update the stall guard after a successful run.

        Same signature as last time -> increment stall_count; changed/new
        signature -> reset to 0. Returns (stall_count, item). Runs where the
        signature could not be computed (None) reset the counter — the guard
        only accuses on positive evidence of no qualifying progress.
        """
        with self._locked() as state:
            item = self._find(state, item_id)
            if signature is not None and signature == item.get("progress_signature"):
                item["stall_count"] = item.get("stall_count", 0) + 1
            else:
                item["stall_count"] = 0
            item["progress_signature"] = signature
            item["updated_at"] = utc_now()
            return item["stall_count"], copy.deepcopy(item)

    @staticmethod
    def _accepted_workers(item: dict[str, Any]) -> list[str]:
        accepted = item.get("accepted_by_workers", [])
        if not isinstance(accepted, list) or any(
            not isinstance(worker, str) for worker in accepted
        ):
            raise QueueError("accepted_by_workers must be a list of worker ids")
        for worker in accepted:
            validate_item_id(worker)
        if len(accepted) != len(set(accepted)):
            raise QueueError("accepted_by_workers must not contain duplicates")
        return accepted

    @staticmethod
    def _worker_policy(state: dict[str, Any], worker: str) -> dict[str, Any]:
        if "worker_policies" not in state:
            return {"claim_limit": None, "claims_used": 0}
        policies = state["worker_policies"]
        if not isinstance(policies, dict):
            raise QueueError("worker_policies must be an object")
        if worker not in policies:
            return {"claim_limit": None, "claims_used": 0}
        policy = policies[worker]
        if not isinstance(policy, dict) or set(policy) != {"claim_limit", "claims_used"}:
            raise QueueError(
                "worker policy must contain exactly claim_limit and claims_used"
            )
        claim_limit = policy["claim_limit"]
        claims_used = policy["claims_used"]
        if claim_limit is not None and (
            not isinstance(claim_limit, int)
            or isinstance(claim_limit, bool)
            or claim_limit < 0
        ):
            raise QueueError("worker claim limit must be a non-negative integer or null")
        if (
            not isinstance(claims_used, int)
            or isinstance(claims_used, bool)
            or claims_used < 0
        ):
            raise QueueError("worker claims_used must be a non-negative integer")
        return policy

    def configure_worker_policy(
        self, worker: str, *, claim_limit: int | None
    ) -> dict[str, Any]:
        worker = validate_item_id(worker)
        if claim_limit is not None and (
            not isinstance(claim_limit, int)
            or isinstance(claim_limit, bool)
            or claim_limit < 0
        ):
            raise QueueError("claim limit must be a non-negative integer")
        policy = {"claim_limit": claim_limit, "claims_used": 0}
        with self._locked() as state:
            policies = state.setdefault("worker_policies", {})
            if not isinstance(policies, dict):
                raise QueueError("worker_policies must be an object")
            policies[worker] = policy
        return copy.deepcopy(policy)

    def claim_next(self, *, worker: str = "worker-1") -> dict[str, Any] | None:
        """Claim the next eligible item for `worker`.

        Sequential-per-topic contract: a worker OWNS its claimed item through
        cadence (scheduled/backoff) cycles until the item reaches a terminal
        state — it never starts a second topic while its own is mid-flight,
        and other workers never touch an owned item. A second worker is purely
        additive: it skips owned items and claims the next unclaimed one.
        """
        with self._locked() as state:
            if state["paused"]:
                return None
            # Missing is the legacy continuous-mode default; an explicitly
            # persisted malformed policy must fail before every claim path,
            # including running resume and prior-topic reacquisition.
            policy = self._worker_policy(state, worker)
            own_running = next(
                (
                    i
                    for i in state["items"]
                    if i["status"] == "running"
                    and i.get("claimed_by", "worker-1") == worker
                ),
                None,
            )
            if own_running:
                accepted = self._accepted_workers(own_running)
                if worker not in accepted:
                    accepted.append(worker)
                    own_running["accepted_by_workers"] = accepted
                result = copy.deepcopy(own_running)
                result["resumed"] = True
                return result
            now = datetime.now(timezone.utc)
            by_id = {candidate["id"]: candidate for candidate in state["items"]}

            def dependencies_satisfied(i: dict[str, Any]) -> bool:
                dependencies = i.get("depends_on", [])
                if not isinstance(dependencies, list) or any(
                    not isinstance(dependency, str) for dependency in dependencies
                ):
                    raise QueueError(f"item {i['id']} has malformed depends_on")
                for dependency in dependencies:
                    validate_item_id(dependency)
                    if dependency == i["id"]:
                        raise QueueError(f"item {i['id']} cannot depend on itself")
                    prerequisite = by_id.get(dependency)
                    if prerequisite is None:
                        raise QueueError(
                            f"item {i['id']} depends on missing item {dependency}"
                        )
                    if prerequisite["status"] != "completed":
                        return False
                return True

            def eligible(i: dict[str, Any]) -> bool:
                return (
                    i["status"] in {"queued", "backoff"}
                    and i["desired_state"] == "running"
                    and dependencies_satisfied(i)
                    and (
                        not i.get("next_eligible_at")
                        or datetime.fromisoformat(
                            i["next_eligible_at"].replace("Z", "+00:00")
                        )
                        <= now
                    )
                )

            # Sticky ownership: if this worker owns a non-terminal item, wait
            # for it (return it when eligible, None during its cadence gap)
            # instead of starting another topic.
            own = next(
                (
                    i
                    for i in state["items"]
                    if i.get("claimed_by") == worker
                    and i["status"] in {"queued", "backoff"}
                    and i["desired_state"] == "running"
                ),
                None,
            )
            if own is not None:
                item = own if eligible(own) else None
            else:
                # A previously accepted topic is continuation, not new intake.
                # Reacquire the first such topic before considering any new
                # candidate, even if an unaccepted head item precedes it.
                prior = next(
                    (
                        i
                        for i in state["items"]
                        if not i.get("claimed_by")
                        and i["status"] in {"queued", "backoff"}
                        and i["desired_state"] == "running"
                        and dependencies_satisfied(i)
                        and worker in self._accepted_workers(i)
                    ),
                    None,
                )
                if prior is not None:
                    item = prior if eligible(prior) else None
                else:
                # Strict queue order: the candidate is the FIRST unclaimed
                # non-terminal item, full stop. If it is mid-cadence/backoff,
                # WAIT — never skip ahead to a later topic (that would run two
                # topics in parallel on one worker; parallelism is only ever
                # added by starting another worker). Items owned by other
                # workers are skipped: they are already being handled.
                    candidate = next(
                        (
                            i
                            for i in state["items"]
                            if not i.get("claimed_by")
                            and i["status"] in {"queued", "backoff"}
                            and i["desired_state"] == "running"
                            and dependencies_satisfied(i)
                        ),
                        None,
                    )
                    item = (
                        candidate
                        if candidate is not None and eligible(candidate)
                        else None
                    )
            if item is None:
                return None
            accepted = self._accepted_workers(item)
            continuing = item.get("claimed_by") == worker
            previously_accepted = worker in accepted
            if not continuing and not previously_accepted:
                claim_limit = policy["claim_limit"]
                if claim_limit is not None and policy["claims_used"] >= claim_limit:
                    return None
                if claim_limit is not None:
                    policy["claims_used"] += 1
                policies = state.setdefault("worker_policies", {})
                if not isinstance(policies, dict):
                    raise QueueError("worker_policies must be an object")
                if worker in policies:
                    policies[worker] = policy
                accepted.append(worker)
                item["accepted_by_workers"] = accepted
            elif continuing and not previously_accepted:
                accepted.append(worker)
                item["accepted_by_workers"] = accepted
            item["status"] = "running"
            item["claimed_by"] = worker
            item["attempts"] += 1
            item["started_at"] = utc_now()
            item["finished_at"] = None
            item["updated_at"] = item["started_at"]
            result = copy.deepcopy(item)
            result["resumed"] = False
            return result

    def pause_all(self, reason: str | None = None) -> dict[str, Any]:
        with self._locked() as state:
            state["paused"] = True
            state["pause_reason"] = reason or "paused by operator"
        return self.snapshot()

    def resume_all(self) -> dict[str, Any]:
        with self._locked() as state:
            state["paused"] = False
            state["pause_reason"] = None
        return self.snapshot()

    def pause_item(self, item_id: str, reason: str | None = None) -> dict[str, Any]:
        with self._locked() as state:
            item = self._find(state, item_id)
            item["desired_state"] = "paused"
            if item["status"] != "running":
                item["status"] = "paused"
            item["last_error"] = reason or "paused by operator"
            item["last_error_kind"] = "operator_pause"
            item["updated_at"] = utc_now()
        return copy.deepcopy(item)

    def resume_item(self, item_id: str) -> dict[str, Any]:
        with self._locked() as state:
            item = self._find(state, item_id)
            item["desired_state"] = "running"
            if item["status"] in {"paused", "needs_attention", "backoff"}:
                item["status"] = "queued"
            item["next_eligible_at"] = None
            item["consecutive_failures"] = 0
            item["last_error"] = None
            item["last_error_kind"] = None
            item["claimed_by"] = None
            item["updated_at"] = utc_now()
        return copy.deepcopy(item)

    def request_restart(self, item_id: str) -> dict[str, Any]:
        with self._locked() as state:
            item = self._find(state, item_id)
            item["restart_generation"] += 1
            item["desired_state"] = "running"
            if item["status"] != "running":
                item["status"] = "queued"
            item["next_eligible_at"] = None
            item["consecutive_failures"] = 0
            item["last_error"] = None
            item["last_error_kind"] = None
            item["claimed_by"] = None
            item["updated_at"] = utc_now()
        return copy.deepcopy(item)

    def mark_completed(self, item_id: str, *, exit_code: int) -> dict[str, Any]:
        with self._locked() as state:
            item = self._find(state, item_id)
            item["status"] = "completed"
            item["desired_state"] = "paused"
            item["finished_at"] = utc_now()
            item["last_exit_code"] = exit_code
            item["last_pid"] = None
            item["last_pid_fingerprint"] = None
            item["updated_at"] = item["finished_at"]
        return copy.deepcopy(item)

    def remove(self, item_id: str) -> dict[str, Any]:
        with self._locked() as state:
            item = self._find(state, item_id)
            if item["status"] == "running":
                raise QueueConflict("cannot remove a running loop; pause it first")
            state["items"].remove(item)
        return copy.deepcopy(item)

    def mark_pid(
        self,
        item_id: str,
        pid: int | None,
        *,
        fingerprint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._locked() as state:
            item = self._find(state, item_id)
            item["last_pid"] = pid
            item["last_pid_fingerprint"] = fingerprint if pid is not None else None
            item["updated_at"] = utc_now()
        return copy.deepcopy(item)

    def mark_paused_after_stop(self, item_id: str) -> dict[str, Any]:
        with self._locked() as state:
            item = self._find(state, item_id)
            item["status"] = "paused"
            item["last_pid"] = None
            item["last_pid_fingerprint"] = None
            item["finished_at"] = utc_now()
            item["updated_at"] = item["finished_at"]
        return copy.deepcopy(item)

    def mark_queued_after_global_pause(self, item_id: str) -> dict[str, Any]:
        with self._locked() as state:
            item = self._find(state, item_id)
            item["status"] = "queued"
            item["last_pid"] = None
            item["last_pid_fingerprint"] = None
            item["finished_at"] = utc_now()
            item["updated_at"] = item["finished_at"]
        return copy.deepcopy(item)

    def mark_restarted_after_stop(self, item_id: str) -> dict[str, Any]:
        with self._locked() as state:
            item = self._find(state, item_id)
            item["status"] = "queued"
            item["last_pid"] = None
            item["last_pid_fingerprint"] = None
            item["next_eligible_at"] = None
            item["finished_at"] = utc_now()
            item["updated_at"] = item["finished_at"]
        return copy.deepcopy(item)

    def mark_scheduled(self, item_id: str, *, next_eligible_at: str) -> dict[str, Any]:
        with self._locked() as state:
            item = self._find(state, item_id)
            item["status"] = "backoff"
            item["consecutive_failures"] = 0
            item["last_exit_code"] = 0
            item["last_error_kind"] = None
            item["last_error"] = None
            item["next_eligible_at"] = next_eligible_at
            item["last_pid"] = None
            item["last_pid_fingerprint"] = None
            item["finished_at"] = utc_now()
            item["updated_at"] = item["finished_at"]
        return copy.deepcopy(item)

    def mark_backoff(
        self,
        item_id: str,
        *,
        exit_code: int,
        error_kind: str,
        message: str,
        next_eligible_at: str,
    ) -> dict[str, Any]:
        with self._locked() as state:
            item = self._find(state, item_id)
            item["status"] = "backoff"
            item["consecutive_failures"] += 1
            item["last_exit_code"] = exit_code
            item["last_error_kind"] = error_kind
            item["last_error"] = message[-4000:]
            item["next_eligible_at"] = next_eligible_at
            item["last_pid"] = None
            item["last_pid_fingerprint"] = None
            item["finished_at"] = utc_now()
            item["updated_at"] = item["finished_at"]
        return copy.deepcopy(item)

    def mark_needs_attention(
        self, item_id: str, *, exit_code: int, error_kind: str, message: str
    ) -> dict[str, Any]:
        with self._locked() as state:
            item = self._find(state, item_id)
            item["status"] = "needs_attention"
            item["desired_state"] = "paused"
            item["consecutive_failures"] += 1
            item["last_exit_code"] = exit_code
            item["last_error_kind"] = error_kind
            item["last_error"] = message[-4000:]
            item["next_eligible_at"] = None
            item["last_pid"] = None
            item["last_pid_fingerprint"] = None
            item["finished_at"] = utc_now()
            item["updated_at"] = item["finished_at"]
        return copy.deepcopy(item)

    def finalize_run(
        self,
        item_id: str,
        *,
        expected_restart_generation: int,
        requested_control: str | None,
        outcome: str,
        exit_code: int,
        error_kind: str | None = None,
        message: str | None = None,
        next_eligible_at: str | None = None,
        consume_failure: bool = True,
    ) -> tuple[str, dict[str, Any]]:
        """Atomically honor current controls and commit a terminal transition."""
        with self._locked() as state:
            item = self._find(state, item_id)
            if state["paused"]:
                actual_outcome = "global_paused"
            elif item["desired_state"] == "paused":
                actual_outcome = "paused"
            elif item["restart_generation"] != expected_restart_generation:
                actual_outcome = "restarted"
            elif requested_control == "paused":
                # The child was stopped for an item pause, but the operator resumed
                # it before finalization. Requeue instead of restoring a stale pause.
                actual_outcome = "restarted"
            else:
                actual_outcome = requested_control or outcome

            now = utc_now()
            if actual_outcome == "global_paused":
                item["status"] = "queued"
            elif actual_outcome == "paused":
                item["status"] = "paused"
            elif actual_outcome == "restarted":
                item["status"] = "queued"
                item["next_eligible_at"] = None
            elif actual_outcome == "completed":
                item["status"] = "completed"
                item["desired_state"] = "paused"
                item["last_exit_code"] = exit_code
            elif actual_outcome == "scheduled":
                item["status"] = "backoff"
                item["consecutive_failures"] = 0
                item["last_exit_code"] = exit_code
                item["last_error_kind"] = None
                item["last_error"] = None
                item["next_eligible_at"] = next_eligible_at
            elif actual_outcome in {"backoff", "needs_attention"}:
                item["status"] = actual_outcome
                if actual_outcome == "needs_attention":
                    item["desired_state"] = "paused"
                    item["next_eligible_at"] = None
                else:
                    item["next_eligible_at"] = next_eligible_at
                if consume_failure:
                    item["consecutive_failures"] += 1
                else:
                    item["subscription_limit_failures"] = (
                        item.get("subscription_limit_failures", 0) + 1
                    )
                item["last_exit_code"] = exit_code
                item["last_error_kind"] = error_kind
                item["last_error"] = (message or "")[-4000:]
            else:
                raise QueueError(f"unknown terminal outcome: {actual_outcome}")

            item["last_pid"] = None
            item["last_pid_fingerprint"] = None
            # Ownership persists across cadence (scheduled) and retry (backoff)
            # cycles so one worker finishes a topic before starting another;
            # terminal and operator outcomes release the item for any worker.
            if actual_outcome not in {"scheduled", "backoff"}:
                item["claimed_by"] = None
            item["finished_at"] = now
            item["updated_at"] = now
        return actual_outcome, copy.deepcopy(item)
