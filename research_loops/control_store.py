"""Canonical managed controller state.

This module deliberately does not auto-adopt the JSON queue/stations files.
An operator migration calls :meth:`ControlStore.initialize` (or the explicit
migration helper) before a workspace becomes managed.  That prevents a read or
a restarted worker from creating a second writable authority.
"""
from __future__ import annotations

import copy
import json
import re
import sqlite3
import os
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


MAX_STATIONS = 5
SCHEMA_VERSION = 1


class ControlStoreError(RuntimeError):
    pass


class ControlValidationError(ControlStoreError):
    pass


class ControlRevisionConflict(ControlStoreError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_configuration() -> dict[str, Any]:
    """A complete managed configuration; profile IDs are deployment values."""
    return {
        "schema_version": SCHEMA_VERSION,
        "active_count": 0,
        "stations": [
            {"id": number, "primary_profile": "", "secondary_profile": "", "interval_seconds": 0}
            for number in range(1, MAX_STATIONS + 1)
        ],
        "checkpoints": {
            "enabled": True,
            "every_research_iterations": 25,
            "on_deepening_entry": True,
            "agent_source": "station_1",
        },
    }


def default_work() -> dict[str, Any]:
    return {"topics": {}, "runs": {}, "triggers": {}, "episodes": {}, "proposals": {}, "decisions": {}, "assignments": {}, "capabilities": {}}


def default_topic_record(topic_id: str, inventory_version: str | None = None) -> dict[str, Any]:
    """The ONE topic work-record shape (2026-09-09 review: two creators had
    drifted — the checkpoint service's copy carried fields this one lacked)."""
    return {
        "topic_id": topic_id,
        "research_iterations_completed": 0,
        "next_research_ordinal": 1,
        "inventory_version": inventory_version,
        "lifecycle_generation": 0,
        "review_state": "eligible",
        "active_episode_id": None,
        "last_accepted_run_id": None,
        "deepening_entries": {},
        "proposal_allowance_remaining": 2,
        "row_revision": 0,
    }


# Every work-ledger map any runtime path setdefault()s. _validate_state checks
# them all: a corrupted non-dict must fail the transaction, not the next
# reader (2026-09-09 review — only the default_work() keys were validated).
RUNTIME_WORK_MAPS = (
    "topics", "runs", "triggers", "episodes", "proposals", "decisions",
    "assignments", "capabilities", "agent_profiles", "intake_drafts",
    "intake_requests", "intake_publications", "intake_assignment",
    "decision_publications", "auto_gap_intents", "auto_gap_promotions",
    "state_operations", "checkpoint_recovery_requests",
    "proposal_reset_requests",
)

# Retention bounds applied by ControlStore.compact(). Governance records
# (topics, episodes, proposals, decisions, publications, intake history) are
# deliberately never pruned.
RUNS_RETAINED_PER_TOPIC = 200
STATE_OPERATIONS_RETAINED = 500
AUDIT_RETENTION_DAYS = 90


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_configuration(configuration: dict[str, Any], *, require_profiles: bool = True) -> None:
    if not isinstance(configuration, dict):
        raise ControlValidationError("configuration must be an object")
    allowed = {"schema_version", "active_count", "stations", "checkpoints"}
    unknown = set(configuration) - allowed
    if unknown:
        raise ControlValidationError(f"configuration has unknown fields: {sorted(unknown)}")
    if not _is_int(configuration.get("schema_version")) or configuration.get("schema_version") != SCHEMA_VERSION:
        raise ControlValidationError(f"configuration.schema_version must be {SCHEMA_VERSION}")
    active_count = configuration.get("active_count")
    if not _is_int(active_count) or not 0 <= active_count <= MAX_STATIONS:
        raise ControlValidationError("configuration.active_count must be an integer from 0 through 5")
    stations = configuration.get("stations")
    if not isinstance(stations, list) or len(stations) != MAX_STATIONS:
        raise ControlValidationError("configuration.stations must contain exactly five stations")
    if any(not isinstance(station, dict) or not _is_int(station.get("id")) for station in stations):
        raise ControlValidationError("each station id must be an integer")
    ordered = sorted(stations, key=lambda station: station["id"])
    for expected, station in enumerate(ordered, 1):
        if not isinstance(station, dict) or set(station) != {"id", "primary_profile", "secondary_profile", "interval_seconds"}:
            raise ControlValidationError("each station must contain exactly id, primary_profile, secondary_profile, interval_seconds")
        if station["id"] != expected:
            raise ControlValidationError("station ids must be the unique contiguous values 1 through 5")
        for field in ("primary_profile", "secondary_profile"):
            value = station[field]
            if not isinstance(value, str) or (require_profiles and not value.strip()):
                raise ControlValidationError(f"stations[{expected}].{field} must be a non-empty profile id")
        if not _is_int(station["interval_seconds"]) or station["interval_seconds"] < 0:
            raise ControlValidationError(f"stations[{expected}].interval_seconds must be a non-negative integer")
        if expected > 1 and station["interval_seconds"] < ordered[expected - 2]["interval_seconds"]:
            raise ControlValidationError("station intervals must be non-decreasing by station id")
    checkpoints = configuration.get("checkpoints")
    if not isinstance(checkpoints, dict):
        raise ControlValidationError("configuration.checkpoints must be an object")
    allowed_checkpoint = {"enabled", "every_research_iterations", "on_deepening_entry", "agent_source", "primary_profile", "secondary_profile"}
    unknown = set(checkpoints) - allowed_checkpoint
    if unknown:
        raise ControlValidationError(f"configuration.checkpoints has unknown fields: {sorted(unknown)}")
    for field in ("enabled", "on_deepening_entry"):
        if not isinstance(checkpoints.get(field), bool):
            raise ControlValidationError(f"configuration.checkpoints.{field} must be a boolean")
    if not _is_int(checkpoints.get("every_research_iterations")) or checkpoints["every_research_iterations"] <= 0:
        raise ControlValidationError("configuration.checkpoints.every_research_iterations must be a positive integer")
    source = checkpoints.get("agent_source")
    if source not in {"station_1", "explicit"}:
        raise ControlValidationError("configuration.checkpoints.agent_source must be station_1 or explicit")
    explicit = {"primary_profile", "secondary_profile"}
    present = explicit & set(checkpoints)
    if source == "explicit":
        if present != explicit or any(not isinstance(checkpoints[k], str) or not checkpoints[k].strip() for k in explicit):
            raise ControlValidationError("explicit checkpoint agents require non-empty primary_profile and secondary_profile")
    elif present:
        raise ControlValidationError("station_1 checkpoint agents forbid explicit primary_profile and secondary_profile")


class ControlStore:
    """SQLite-backed owner of managed configuration, queue, and work records."""
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.path = self.root / "state" / "control.sqlite3"

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def _connect(self) -> sqlite3.Connection:
        if not self.exists:
            raise ControlStoreError("managed control store is not initialized; run explicit migration/initialize first")
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    @classmethod
    def initialize(cls, root: str | Path, *, configuration: dict[str, Any], queue: dict[str, Any] | None = None, work: dict[str, Any] | None = None, agent_profiles: dict[str, dict[str, Any]] | None = None) -> "ControlStore":
        store = cls(root)
        if store.exists:
            raise ControlStoreError(f"managed control store already exists: {store.path}")
        validate_configuration(configuration)
        initial_work = copy.deepcopy(work or default_work())
        if agent_profiles is not None:
            initial_work["agent_profiles"] = copy.deepcopy(agent_profiles)
        initial = {"revision": 0, "configuration": copy.deepcopy(configuration), "queue": copy.deepcopy(queue or {"version": 1, "revision": 0, "paused": False, "pause_reason": None, "stopping": False, "items": []}), "work": initial_work}
        store._validate_state(initial)
        store.path.parent.mkdir(parents=True, exist_ok=True)
        fd, staged_name = tempfile.mkstemp(prefix=".control-initialize-", dir=store.path.parent)
        os.close(fd)
        staged = Path(staged_name)
        connection = sqlite3.connect(staged)
        try:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE logical_state (name TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE control_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE control_audit (sequence INTEGER PRIMARY KEY AUTOINCREMENT, operation_id TEXT, actor TEXT NOT NULL, input_revision INTEGER NOT NULL, committed_revision INTEGER NOT NULL, timestamp TEXT NOT NULL, affected_ids TEXT NOT NULL, outcome TEXT NOT NULL);
            """)
            for name in ("configuration", "queue", "work"):
                connection.execute("INSERT INTO logical_state(name, body) VALUES (?, ?)", (name, json.dumps(initial[name], sort_keys=True)))
            connection.execute("INSERT INTO control_meta(key, value) VALUES ('revision', '0')")
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.close()
            with staged.open("rb") as handle:
                os.fsync(handle.fileno())
            # Publish complete state only, without overwriting another
            # initializer's concurrently committed database.
            os.link(staged, store.path)
            directory_fd = os.open(store.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            connection.close()
            staged.unlink(missing_ok=True)
        return store

    def snapshot(self) -> dict[str, Any]:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            rows = {row["name"]: json.loads(row["body"]) for row in connection.execute("SELECT name, body FROM logical_state")}
            revision = int(connection.execute("SELECT value FROM control_meta WHERE key='revision'").fetchone()[0])
            connection.commit()
            return {"revision": revision, "configuration": rows["configuration"], "queue": rows["queue"], "work": rows["work"]}
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, actor: str = "system", operation_id: str | None = None, affected_ids: list[str] | None = None) -> Iterator[dict[str, Any]]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = {row["name"]: json.loads(row["body"]) for row in connection.execute("SELECT name, body FROM logical_state")}
            revision = int(connection.execute("SELECT value FROM control_meta WHERE key='revision'").fetchone()[0])
            state = {"revision": revision, "configuration": rows["configuration"], "queue": rows["queue"], "work": rows["work"]}
            before = copy.deepcopy(state)
            yield state
            if state != before:
                self._validate_state(state)
                next_revision = revision + 1
                for name in ("configuration", "queue", "work"):
                    connection.execute("UPDATE logical_state SET body=? WHERE name=?", (json.dumps(state[name], sort_keys=True), name))
                connection.execute("UPDATE control_meta SET value=? WHERE key='revision'", (str(next_revision),))
                connection.execute("INSERT INTO control_audit(operation_id, actor, input_revision, committed_revision, timestamp, affected_ids, outcome) VALUES (?, ?, ?, ?, ?, ?, ?)", (operation_id, actor, revision, next_revision, utc_now(), json.dumps(affected_ids or []), "committed"))
                state["revision"] = next_revision
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _validate_state(self, state: dict[str, Any]) -> None:
        validate_configuration(state["configuration"])
        if not isinstance(state["queue"], dict) or not isinstance(state["queue"].get("items", []), list):
            raise ControlValidationError("queue.items must be a list")
        if not isinstance(state["work"], dict):
            raise ControlValidationError("work must be an object")
        for key in RUNTIME_WORK_MAPS:
            if not isinstance(state["work"].get(key, {}), dict):
                raise ControlValidationError(f"work.{key} must be an object")
        profiles = state["work"].get("agent_profiles", {})
        if not isinstance(profiles, dict):
            raise ControlValidationError("work.agent_profiles must be an object")
        for profile_id, profile in profiles.items():
            self._validate_profile(profile_id, profile)
        referenced = [field for station in state["configuration"]["stations"] for field in (station["primary_profile"], station["secondary_profile"])]
        policy = state["configuration"]["checkpoints"]
        if policy["agent_source"] == "explicit":
            referenced.extend([policy["primary_profile"], policy["secondary_profile"]])
        missing = sorted(set(referenced) - set(profiles))
        if missing:
            raise ControlValidationError(f"unregistered agent profile ids: {missing}")

    @staticmethod
    def _validate_profile(profile_id: str, profile: dict[str, Any]) -> None:
        if not isinstance(profile_id, str) or not _PROFILE_ID.fullmatch(profile_id):
            raise ControlValidationError("agent profile id must be a valid stable id")
        if not isinstance(profile, dict) or set(profile) != {"adapter", "model", "executable", "argv"}:
            raise ControlValidationError(f"agent profile {profile_id!r} must contain exactly adapter, model, executable, argv")
        for field in ("adapter", "model", "executable"):
            if not isinstance(profile[field], str) or not profile[field].strip():
                raise ControlValidationError(f"agent profile {profile_id}.{field} must be a non-empty string")
        if not isinstance(profile["argv"], list) or any(not isinstance(value, str) for value in profile["argv"]):
            raise ControlValidationError(f"agent profile {profile_id}.argv must be an array of strings")

    def register_profile(self, profile_id: str, *, adapter: str, model: str, executable: str, argv: list[str]) -> dict[str, Any]:
        profile = {"adapter": adapter, "model": model, "executable": executable, "argv": list(argv)}
        self._validate_profile(profile_id, profile)
        with self.transaction(actor="operator", affected_ids=[profile_id]) as state:
            state["work"].setdefault("agent_profiles", {})[profile_id] = profile
            return copy.deepcopy(profile)

    def resolve_profile(self, profile_id: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
        state = state or self.snapshot()
        profile = state["work"].get("agent_profiles", {}).get(profile_id)
        if profile is None:
            raise ControlValidationError(f"unregistered agent profile: {profile_id}")
        self._validate_profile(profile_id, profile)
        return {"id": profile_id, **copy.deepcopy(profile)}

    def resolve_station_pair(self, station_id: int, state: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
        state = state or self.snapshot()
        station = next((item for item in state["configuration"]["stations"] if item["id"] == station_id), None)
        if station is None:
            raise ControlValidationError(f"unknown station: {station_id}")
        return {"primary": self.resolve_profile(station["primary_profile"], state), "secondary": self.resolve_profile(station["secondary_profile"], state)}

    def resolve_checkpoint_pair(self, state: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
        state = state or self.snapshot()
        profiles = self.effective_checkpoint_profiles(state)
        return {"primary": self.resolve_profile(profiles["primary_profile"], state), "secondary": self.resolve_profile(profiles["secondary_profile"], state)}

    def effective_checkpoint_profiles(self, state: dict[str, Any] | None = None) -> dict[str, str]:
        configuration = (state or self.snapshot())["configuration"]
        policy = configuration["checkpoints"]
        if policy["agent_source"] == "explicit":
            return {"primary_profile": policy["primary_profile"], "secondary_profile": policy["secondary_profile"]}
        first = next(station for station in configuration["stations"] if station["id"] == 1)
        return {"primary_profile": first["primary_profile"], "secondary_profile": first["secondary_profile"]}

    @staticmethod
    def ensure_topic_work(state: dict[str, Any], topic_id: str, *, inventory_version: str | None = None) -> dict[str, Any]:
        topics = state["work"].setdefault("topics", {})
        if topic_id not in topics:
            topics[topic_id] = default_topic_record(topic_id, inventory_version)
        return topics[topic_id]

    def compact(self, state: dict[str, Any]) -> dict[str, int]:
        """Bound the runtime ledgers inside an already-open transaction.

        Every transaction rewrites the whole logical state, so unbounded
        per-run/per-operation records degrade every future operation
        (2026-09-09 review). Only mechanical runtime records are pruned;
        governance records are never touched. run_ids are lease UUIDs and are
        never reused, so dropping an old finished run cannot enable an
        idempotent-replay path.
        """
        work = state.get("work") or {}
        removed = {"runs": 0, "state_operations": 0, "capabilities": 0}
        runs = work.get("runs")
        if isinstance(runs, dict):
            referenced = {episode.get("run_id") for episode in work.get("episodes", {}).values()
                          if isinstance(episode, dict)}
            by_topic: dict[str, list[str]] = {}
            for run_id, run in runs.items():
                if isinstance(run, dict):
                    by_topic.setdefault(str(run.get("topic_id")), []).append(run_id)
            for run_ids in by_topic.values():
                run_ids.sort(key=lambda rid: str(runs[rid].get("started_at") or runs[rid].get("ended_at") or ""))
                for run_id in run_ids[:-RUNS_RETAINED_PER_TOPIC]:
                    run = runs[run_id]
                    if run.get("state") != "started" and run_id not in referenced:
                        del runs[run_id]
                        removed["runs"] += 1
        operations = work.get("state_operations")
        if isinstance(operations, dict) and len(operations) > STATE_OPERATIONS_RETAINED:
            # Oldest first by recorded timestamp (legacy records without one
            # sort first and are pruned before anything dated).
            def _recorded_at(key: str) -> str:
                value = operations[key]
                return str(value.get("at") or "") if isinstance(value, dict) else ""
            excess = sorted(operations, key=_recorded_at)[: len(operations) - STATE_OPERATIONS_RETAINED]
            for key in excess:
                del operations[key]
            removed["state_operations"] = len(excess)
        capabilities = work.get("capabilities")
        if isinstance(capabilities, dict):
            current_lease_ids = set()
            for record in [*work.get("assignments", {}).values(), work.get("intake_assignment", {})]:
                lease = record.get("current") if isinstance(record, dict) else None
                if isinstance(lease, dict) and lease.get("lease_id"):
                    current_lease_ids.add(lease["lease_id"])
            for digest in [d for d, c in capabilities.items()
                           if isinstance(c, dict)
                           and (c.get("revoked") or c.get("lease_id") not in current_lease_ids)]:
                del capabilities[digest]
                removed["capabilities"] += 1
        return removed

    def sweep_audit(self, *, retention_days: int = AUDIT_RETENTION_DAYS) -> int:
        """Prune audit rows older than the retention window (own connection)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat().replace("+00:00", "Z")
        connection = self._connect()
        try:
            cursor = connection.execute("DELETE FROM control_audit WHERE timestamp < ?", (cutoff,))
            connection.commit()
            return cursor.rowcount
        finally:
            connection.close()

    @classmethod
    def migration_report(cls, root: str | Path) -> dict[str, Any]:
        """Read-only legacy inventory. It never creates a managed database."""
        root = Path(root)
        state = root / "state"
        report: dict[str, Any] = {"managed_exists": (state / "control.sqlite3").exists(), "legacy_queue": None, "legacy_stations": None, "unsupported": []}
        for key, path in (("legacy_queue", state / "queue.json"), ("legacy_stations", state / "stations.json")):
            if path.exists():
                try:
                    report[key] = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    report["unsupported"].append(f"{path.name}: {exc}")
        return report

    @classmethod
    def apply_legacy_migration(cls, root: str | Path, *, configuration: dict[str, Any], agent_profiles: dict[str, dict[str, Any]], baseline_counts: dict[str, int], checkpoint_history: dict[str, dict[str, Any]] | None = None, dry_run: bool = True) -> dict[str, Any]:
        """Explicit, operator-supplied legacy adoption.

        Counts are accepted only from ``baseline_counts``; legacy ``attempts``
        are deliberately never interpreted as completed research.
        """
        report = cls.migration_report(root)
        if report["managed_exists"]:
            raise ControlStoreError("managed control store already exists")
        legacy = report.get("legacy_queue")
        if not isinstance(legacy, dict) or not isinstance(legacy.get("items"), list):
            raise ControlValidationError("migration requires a readable legacy queue.json")
        ids = [item.get("id") for item in legacy["items"] if isinstance(item, dict)]
        if len(ids) != len(legacy["items"]) or len(set(ids)) != len(ids):
            raise ControlValidationError("legacy queue has missing or duplicate item ids")
        running = [item_id for item_id, item in zip(ids, legacy["items"], strict=True) if item.get("status") == "running"]
        if running:
            raise ControlValidationError(f"migration requires explicit drain/adoption before running items: {running}")
        unknown = set(baseline_counts) - set(ids)
        if unknown or any(not _is_int(count) or count < 0 for count in baseline_counts.values()):
            raise ControlValidationError("baseline_counts must give non-negative integer counts for known ids")
        missing = set(ids) - set(baseline_counts)
        if missing:
            raise ControlValidationError(f"migration requires explicit completed-count baseline for: {sorted(missing)}")
        work = default_work()
        work["agent_profiles"] = copy.deepcopy(agent_profiles)
        checkpoint_history = checkpoint_history or {}
        if set(checkpoint_history) - set(ids):
            raise ControlValidationError("checkpoint_history contains unknown topic ids")
        by_id = {item["id"]: item for item in legacy["items"]}
        for item_id, count in baseline_counts.items():
            item = by_id[item_id]
            inventory_version = item.get("completion_lock")
            history = checkpoint_history.get(item_id, {})
            if not isinstance(history, dict) or set(history) - {"last_checkpoint_iteration", "reviewed_inventory_versions"}:
                raise ControlValidationError(f"checkpoint_history.{item_id} must contain only last_checkpoint_iteration and reviewed_inventory_versions")
            last_checkpoint = history.get("last_checkpoint_iteration")
            if last_checkpoint is not None and (not _is_int(last_checkpoint) or not 0 <= last_checkpoint <= count):
                raise ControlValidationError(f"checkpoint_history.{item_id}.last_checkpoint_iteration must be an integer from 0 through baseline count")
            reviewed = history.get("reviewed_inventory_versions", [])
            if not isinstance(reviewed, list) or any(not isinstance(value, str) or not value for value in reviewed):
                raise ControlValidationError(f"checkpoint_history.{item_id}.reviewed_inventory_versions must be an array of inventory versions")
            if item.get("deepening_seen") and inventory_version and inventory_version not in reviewed:
                raise ControlValidationError(f"migration needs explicit reviewed inventory history for deepening topic {item_id}")
            work["topics"][item_id] = {"topic_id": item_id, "research_iterations_completed": count, "next_research_ordinal": count + 1, "inventory_version": inventory_version, "lifecycle_generation": int(item.get("restart_generation", 0) or 0), "review_state": "eligible", "active_episode_id": None, "last_accepted_run_id": None, "row_revision": 0, "migration_baseline": True, "deepening_seen": bool(item.get("deepening_seen")), "last_checkpoint_iteration": last_checkpoint, "reviewed_inventory_versions": reviewed}
            work["topics"][item_id]["deepening_entries"] = {
                version: {"entered_after_ordinal": None, "triggered": True, "migration_reviewed": True}
                for version in reviewed}
            cadence = configuration["checkpoints"]["every_research_iterations"]
            due_boundary = (count // cadence) * cadence
            if item.get("status") != "completed" and configuration["checkpoints"]["enabled"] and due_boundary and (last_checkpoint is None or last_checkpoint < due_boundary):
                from .checkpoints.service import _new_episode
                trigger_id = f"migration-cadence-{item_id}-{due_boundary}"
                episode = _new_episode(work, work["topics"][item_id], [trigger_id])
                episode["migration_seed"] = True
                work["triggers"][trigger_id] = {"trigger_id": trigger_id, "topic_id": item_id, "kind": "cadence", "research_ordinal": due_boundary, "inventory_version": inventory_version, "episode_id": episode["episode_id"], "handled": False}
        candidate = {"revision": 0, "configuration": copy.deepcopy(configuration), "queue": copy.deepcopy(legacy), "work": work}
        # Dry-run and apply share the exact validation path before any DB file
        # is created, so a report cannot promise an unpublishable cutover.
        cls(root)._validate_state(candidate)
        outcome = {"dry_run": dry_run, "queue_order": ids, "baseline_counts": dict(baseline_counts), "preserved_items": len(ids), "attempts_used_for_counts": False}
        if not dry_run:
            cls.initialize(root, configuration=configuration, queue=legacy, work=work, agent_profiles=agent_profiles)
            outcome["created"] = str(Path(root) / "state" / "control.sqlite3")
        return outcome


_STATION_ID = re.compile(r"(?:station-)?([1-5])\Z")
_PROFILE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class ControlScheduler:
    """Deterministic assignment policy over a :class:`ControlStore` state.

    It only changes controller records.  The runner remains responsible for
    spawning a process after it has checked the returned lease immediately
    before launch.
    """
    def __init__(self, control: ControlStore):
        self.control = control

    @staticmethod
    def station_id(value: int | str) -> int:
        if _is_int(value) and 1 <= value <= MAX_STATIONS:
            return value
        match = _STATION_ID.fullmatch(value) if isinstance(value, str) else None
        if match:
            return int(match.group(1))
        raise ControlValidationError("station must be an id 1 through 5 or station-1 through station-5")

    @staticmethod
    def _station(configuration: dict[str, Any], station_id: int) -> dict[str, Any]:
        return next(station for station in configuration["stations"] if station["id"] == station_id)

    def update_stations(self, *, station_ids: list[int] | None = None, all_stations: bool = False, primary_profile: str | None = None, secondary_profile: str | None = None, intervals: list[int] | None = None, active_count: int | None = None, checkpoints: dict[str, Any] | None = None) -> dict[str, Any]:
        if type(all_stations) is not bool or (station_ids is not None and not isinstance(station_ids, list)):
            raise ControlValidationError("all_stations must be boolean and station_ids must be an array")
        if not all_stations and station_ids is None and (checkpoints is not None or active_count is not None or intervals is not None) and primary_profile is None and secondary_profile is None:
            all_stations = True
        if all_stations == (station_ids is not None):
            raise ControlValidationError("choose exactly one of all_stations or station_ids")
        if intervals is not None and station_ids is not None:
            raise ControlValidationError("interval updates must supply only the complete five-station interval chain")
        if intervals is not None and (not isinstance(intervals, list) or len(intervals) != MAX_STATIONS):
            raise ControlValidationError("intervals must contain five values")
        if primary_profile is not None and (not isinstance(primary_profile, str) or not primary_profile.strip()):
            raise ControlValidationError("primary_profile must be a non-empty profile id")
        if secondary_profile is not None and (not isinstance(secondary_profile, str) or not secondary_profile.strip()):
            raise ControlValidationError("secondary_profile must be a non-empty profile id")
        if active_count is not None and (not _is_int(active_count) or not 0 <= active_count <= MAX_STATIONS):
            raise ControlValidationError("active_count must be an integer from 0 through 5")
        selected = list(range(1, MAX_STATIONS + 1)) if all_stations else [self.station_id(item) for item in station_ids or []]
        if len(set(selected)) != len(selected) or not selected:
            raise ControlValidationError("station_ids must be a non-empty unique subset")
        if intervals is None and primary_profile is None and secondary_profile is None and active_count is None and checkpoints is None:
            raise ControlValidationError("station update contains no changes")
        with self.control.transaction(actor="operator", affected_ids=[str(item) for item in selected]) as state:
            configuration = state["configuration"]
            if checkpoints is not None:
                configuration["checkpoints"] = copy.deepcopy(checkpoints)
            for station_id in selected:
                station = self._station(configuration, station_id)
                if primary_profile is not None:
                    station["primary_profile"] = primary_profile.strip()
                if secondary_profile is not None:
                    station["secondary_profile"] = secondary_profile.strip()
            if intervals is not None:
                for station, interval in zip(configuration["stations"], intervals, strict=True):
                    station["interval_seconds"] = interval
            if active_count is not None:
                configuration["active_count"] = active_count
            self.reconcile_state(state)
            result = copy.deepcopy(configuration)
        return result

    def reorder(self, ordered_ids: list[str], *, expected_queue_revision: int) -> dict[str, Any]:
        with self.control.transaction(actor="operator", affected_ids=ordered_ids) as state:
            queue = state["queue"]
            if queue.get("revision") != expected_queue_revision:
                raise ControlRevisionConflict(f"queue revision conflict: expected {expected_queue_revision}, current {queue.get('revision')}")
            current_ids = [item.get("id") for item in queue["items"]]
            if len(ordered_ids) != len(current_ids) or set(ordered_ids) != set(current_ids) or len(set(ordered_ids)) != len(ordered_ids):
                raise ControlValidationError("ordered queue ids must contain every current id exactly once")
            by_id = {item["id"]: item for item in queue["items"]}
            queue["items"] = [by_id[item_id] for item_id in ordered_ids]
            queue["revision"] += 1
            self.reconcile_state(state)
            return {"order": list(ordered_ids), "queue_revision": queue["revision"], "assignments": copy.deepcopy(state["work"].get("assignments", {}))}

    def reconcile_state(self, state: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
        now = now or utc_now()
        configuration, queue, work = state["configuration"], state["queue"], state["work"]
        assignments = work.setdefault("assignments", {})
        if queue.get("paused") or queue.get("stopping"):
            for record in assignments.values():
                if isinstance(record, dict):
                    record["desired"] = None
            return assignments
        topics = work.setdefault("topics", {})
        active = configuration["active_count"]
        # Existing leases retain ownership until their safe finalization point;
        # a lowered active count marks them draining instead of revoking them.
        candidates: list[dict[str, Any]] = []
        items_by_id = {item.get("id"): item for item in queue.get("items", []) if isinstance(item, dict)}
        for item in queue.get("items", []):
            item_id = item.get("id")
            if not isinstance(item_id, str):
                continue
            if item.get("lane", "research") != "research":
                continue
            topic = self.control.ensure_topic_work(state, item_id)
            dependencies = item.get("depends_on") or []
            if any(items_by_id.get(dep, {}).get("status") != "completed" for dep in dependencies):
                continue
            # Keep a paced head in rank calculation. Claim later gates only
            # its assigned station, allowing lower stations their own ranks.
            if item.get("status", "queued") in {"queued", "backoff", "running"} and item.get("desired_state", "running") == "running" and topic.get("review_state") not in {"awaiting_operator", "publishing_decision", "checkpoint_running", "retry_wait", "needs_attention"}:
                candidates.append(item)
        iterator = iter(candidates)
        for station_id in range(1, MAX_STATIONS + 1):
            record = assignments.setdefault(str(station_id), {})
            current = record.get("current")
            if station_id > active:
                record["desired"] = None
                if current:
                    record["draining"] = True
                    record["handoff_reason"] = "active_count_decreased"
                continue
            item = next(iterator, None)
            if item is None:
                record["desired"] = None
                continue
            topic = topics[item["id"]]
            kind = "checkpoint" if topic.get("review_state") == "checkpoint_due" else "research"
            record["desired"] = {"topic_id": item["id"], "execution_kind": kind}
            if current and current.get("topic_id") != item["id"]:
                record["handoff_reason"] = "priority_reconciliation"
        return assignments

    def claim(self, station: int | str, *, now: str | None = None) -> dict[str, Any] | None:
        station_id = self.station_id(station)
        now = now or utc_now()
        with self.control.transaction(actor="worker", affected_ids=[str(station_id)]) as state:
            if station_id > state["configuration"]["active_count"]:
                return None
            assignments = self.reconcile_state(state, now=now)
            record = assignments[str(station_id)]
            current = record.get("current")
            desired = record.get("desired")
            if current:
                # A current lease is only returned while still desired.  A
                # displaced worker must finish/finalize before it can claim.
                if desired and desired.get("topic_id") == current.get("topic_id"):
                    # A restarted supervisor must adopt the durable lease;
                    # this marker is deliberately return-only and is never
                    # persisted into the controller assignment.
                    resumed = copy.deepcopy(current)
                    resumed["_resumed"] = True
                    return resumed
                return None
            if not desired:
                return None
            topic = self.control.ensure_topic_work(state, desired["topic_id"])
            for field in ("retry_not_before", "pacing_ready_at"):
                value = topic.get(field)
                if isinstance(value, str) and value > now:
                    return None
            for other_id, other in assignments.items():
                other_current = other.get("current") if isinstance(other, dict) else None
                if other_id != str(station_id) and isinstance(other_current, dict) and other_current.get("topic_id") == desired["topic_id"]:
                    return None
            topic_id = desired["topic_id"]
            lease = {**desired, "station_id": station_id, "lease_id": str(uuid.uuid4()), "lease_generation": int(record.get("lease_generation", 0)) + 1, "started_at": now, "configuration_revision": state["revision"]}
            record["lease_generation"] = lease["lease_generation"]
            record["current"] = lease
            record["draining"] = False
            # The run exists in the work ledger from the same transaction that
            # mints its lease: a crash between claim and completion accounting
            # previously left queue-visible state with no ledger counterpart
            # (2026-09-09 review). accept_research_completion finishes this
            # record; a permanently "started" run is visible evidence of a
            # lost attempt, never silence.
            state["work"].setdefault("runs", {})[lease["lease_id"]] = {
                "run_id": lease["lease_id"], "topic_id": topic_id,
                "station_id": station_id, "lease_generation": lease["lease_generation"],
                "execution_kind": lease["execution_kind"], "state": "started",
                "started_at": now, "accepted": None, "ordinal": None,
                "completion_accounted": False,
            }
            claimed = copy.deepcopy(lease)
            claimed["_resumed"] = False
            return claimed

    def finalize(self, station: int | str, lease_id: str, *, pacing_ready_at: str | None = None, retry_not_before: str | None = None) -> dict[str, Any]:
        station_id = self.station_id(station)
        with self.control.transaction(actor="worker", affected_ids=[str(station_id)]) as state:
            record = state["work"].setdefault("assignments", {}).get(str(station_id), {})
            current = record.get("current")
            if not current or current.get("lease_id") != lease_id:
                raise ControlRevisionConflict("stale or unknown station lease")
            topic = self.control.ensure_topic_work(state, current["topic_id"])
            # Handoff clears only pacing.  Failure retry remains a topic
            # restriction regardless of which station receives it next.
            if retry_not_before is not None:
                topic["retry_not_before"] = retry_not_before
            if pacing_ready_at is not None and not record.get("handoff_reason"):
                topic["pacing_ready_at"] = pacing_ready_at
            elif record.get("handoff_reason"):
                topic.pop("pacing_ready_at", None)
            if current.get("execution_kind") == "checkpoint":
                item = next(i for i in state["queue"]["items"] if i["id"] == current["topic_id"])
                paused = item.get("desired_state") in {"paused", "stopping"}
                item.update(status="paused" if paused else "queued", claimed_by=None,
                            last_pid=None, last_pid_fingerprint=None, updated_at=utc_now())
                if paused:
                    item["desired_state"] = "paused"
            record["current"] = None
            record["handoff_reason"] = None
            record["draining"] = False
            # A finalized lease's capabilities die with it, proactively —
            # authenticate_capability would fail closed anyway once the lease
            # is gone, but revocation removes even the residual window and
            # lets compaction reclaim the records.
            for capability in state["work"].get("capabilities", {}).values():
                if isinstance(capability, dict) and capability.get("lease_id") == lease_id:
                    capability["revoked"] = True
            self.control.compact(state)
            self.reconcile_state(state)
            return copy.deepcopy(state["work"]["assignments"].get(str(station_id), {}))

    def confirm_launch(self, station: int | str, lease_id: str) -> dict[str, Any]:
        """Last controller check immediately before process spawn.

        Downscales and priority handoffs may occur after claim.  Recording this
        boundary makes a stale lease non-launchable; a failed spawn is still
        finalized through the normal runner outcome path.
        """
        station_id = self.station_id(station)
        with self.control.transaction(actor="supervisor", affected_ids=[str(station_id)]) as state:
            if station_id > state["configuration"]["active_count"]:
                raise ControlRevisionConflict("station capacity was disabled before launch")
            current = state["work"].get("assignments", {}).get(str(station_id), {}).get("current")
            if not isinstance(current, dict) or current.get("lease_id") != lease_id:
                raise ControlRevisionConflict("lease was superseded before launch")
            current["launch_confirmed_at"] = utc_now()
            return copy.deepcopy(current)
