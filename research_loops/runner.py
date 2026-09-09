from __future__ import annotations

import fcntl
import json
import math
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import refresh as refresh_mod
from .queue import QueueError, QueueStore, utc_now, validate_item_id
from .checkpoints.runner import CheckpointRunner, RegisteredCheckpointAdapter, SubprocessCheckpointAdapter
from .checkpoints.service import (
    CheckpointError,
    accept_research_completion,
    finish_checkpoint,
    start_checkpoint,
)


class FailureKind(StrEnum):
    NONE = "none"
    SUBSCRIPTION_LIMIT = "subscription_limit"
    RATE_LIMIT = "rate_limit"
    OUTAGE = "outage"
    AUTH = "auth"
    CONFIGURATION = "configuration"
    TRANSIENT = "transient"


_PATTERNS = {
    FailureKind.SUBSCRIPTION_LIMIT: re.compile(
        r"weekly usage limit|session limit|5-hour limit|(?:hit|reached) your (?:weekly|monthly|subscription|usage) limit|resets? at",
        re.IGNORECASE,
    ),
    FailureKind.RATE_LIMIT: re.compile(r"\b429\b|rate.?limit|too many requests", re.IGNORECASE),
    FailureKind.OUTAGE: re.compile(
        r"\b50[0234]\b|service unavailable|temporarily unavailable|provider outage|connection (?:reset|refused)|timed? ?out",
        re.IGNORECASE,
    ),
    FailureKind.AUTH: re.compile(
        r"\b401\b|\b403\b|unauthori[sz]ed|invalid (?:api )?key|authentication failed|token expired",
        re.IGNORECASE,
    ),
    FailureKind.CONFIGURATION: re.compile(
        r"command not found|no such file|invalid config|configuration error|permission denied",
        re.IGNORECASE,
    ),
}


# Deterministic exit-code meanings take precedence over log-text pattern scanning.
# 3/4 are loop entrypoint contracts (STOP present / PAUSED present):
# operator-attention states that must never be retried as transient failures.
# 64 (EX_USAGE) and 78 (EX_CONFIG, the adapter's NEEDS-OPERATOR) are sysexits;
# 126/127 are shell cannot-execute/not-found.
#
# Exit 5 is deliberately ABSENT: the pre-2026-09 chassis exited 5 on the first
# iteration with an unchanged semantic signature, and mapping it to
# CONFIGURATION here parked contract-compliant discovery-only iterations as
# needs_attention before the stall guard's stall_limit could ever apply
# (the 2026-08-31 psych-user-modeling-persona incident). Liveness is the
# stall guard's job (_apply_stall_guard): the chassis measures, the queue
# counts stall_limit CONSECUTIVE unchanged signatures, and only then
# escalates — without ever consuming the attempt budget. A stale chassis
# that still emits 5 falls through to tail classification (TRANSIENT),
# which retries with backoff instead of instantly parking.
_EXIT_CODE_KINDS = {
    3: FailureKind.CONFIGURATION,
    4: FailureKind.CONFIGURATION,
    64: FailureKind.CONFIGURATION,
    78: FailureKind.CONFIGURATION,
    126: FailureKind.CONFIGURATION,
    127: FailureKind.CONFIGURATION,
}

# Research iteration logs are full of LLM prose that can casually contain phrases
# like "timed out" or "429"; only the tail of the log describes why the process
# actually exited, so pattern classification never scans the whole transcript.
# 2 KB is the final stack-trace/error block; scanning further back into LLM
# summary prose risks matching "the request timed out" in a *successful* iteration.
_SCAN_TAIL_CHARS = 2000
_PROFILE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")

# The chassis shipped inside this package — used for the default completion
# validation on research topics whose items configure no completion_command.
_CHASSIS_DIR = Path(__file__).resolve().parent / "chassis"


def validate_profile_name(profile: str) -> str:
    if not _PROFILE_ID_PATTERN.fullmatch(profile):
        raise QueueError("profile must match [a-z0-9][a-z0-9_-]{0,63}")
    return profile


def saturation_decision(*, signature_changed: bool, previous_streak: int, limit: int,
                        blocked_this_pass: bool, blockers: list) -> tuple[int, str]:
    """The one saturation/completion condition (gateway docs/STATION-CONTRACT.md §2).

    Returns (new_streak, verdict) with verdict 'complete' | 'held' | 'continue'.
    A semantic change resets the streak (deepening still changes things). A pass that
    hit a blocking research-coverage failure PAUSES the streak — no semantic change
    while required research is unavailable is not evidence of stability — and can
    never be the completing pass. Reaching the limit with unresolved blockers holds
    completion (verdict 'held') until the same request succeeds or the operator
    releases the blocker explicitly with `resolve-research` (a recorded
    evidence decision — an ordinary resume never clears blockers)."""
    if signature_changed:
        streak = 0
    elif blocked_this_pass:
        streak = previous_streak
    else:
        streak = previous_streak + 1
    if streak >= limit:
        return streak, "held" if (blocked_this_pass or blockers) else "complete"
    return streak, "continue"


def classify_failure(exit_code: int, output: str) -> FailureKind:
    if exit_code == 0:
        return FailureKind.NONE
    mapped = _EXIT_CODE_KINDS.get(exit_code)
    if mapped is not None:
        return mapped
    tail = output[-_SCAN_TAIL_CHARS:]
    # SUBSCRIPTION_LIMIT before RATE_LIMIT: providers commonly wrap exhausted
    # subscription windows in an HTTP 429, and the generic rate-limit match
    # would otherwise consume the ordinary retry budget for a quota window.
    for kind in (
        FailureKind.SUBSCRIPTION_LIMIT,
        FailureKind.RATE_LIMIT,
        FailureKind.OUTAGE,
        FailureKind.AUTH,
        FailureKind.CONFIGURATION,
    ):
        if _PATTERNS[kind].search(tail):
            return kind
    return FailureKind.TRANSIENT


def retry_delay(kind: FailureKind, consecutive_failures: int) -> int | None:
    failures = max(1, consecutive_failures)
    if kind is FailureKind.SUBSCRIPTION_LIMIT:
        return 1800
    if kind is FailureKind.RATE_LIMIT:
        return min(3600, 300 * (2 ** (failures - 1)))
    if kind in {FailureKind.OUTAGE, FailureKind.TRANSIENT}:
        return min(3600, 60 * (2 ** (failures - 1)))
    return None


class UsageLedger:
    # Events older than this are pruned by sweep_old_events().  90 days is
    # enough to reconstruct a multi-month usage/cost history without keeping
    # years of per-iteration JSONL around.
    EVENT_RETENTION_DAYS = 90

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def append(self, event: dict[str, Any]) -> None:
        record = {"ts": utc_now(), **event}
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def events(self, *, since: datetime | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
            lines = self.path.read_text(encoding="utf-8").splitlines()
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        events = []
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # A torn/corrupt line must not take down readers; skip it.
                continue
            if since is not None:
                ts = event.get("ts")
                if ts:
                    try:
                        event_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if event_dt < since:
                            continue
                    except (ValueError, TypeError):
                        pass
            events.append(event)
        return events

    def sweep_old_events(
        self, *, retention_days: int = EVENT_RETENTION_DAYS
    ) -> int:
        """Prune events older than *retention_days*. Returns count removed."""
        if not self.path.exists():
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            lines = self.path.read_text(encoding="utf-8").splitlines()
            kept = []
            removed = 0
            for line in lines:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    # Keep corrupt lines verbatim rather than crashing the
                    # worker loop or silently discarding evidence.
                    kept.append(line)
                    continue
                ts = event.get("ts")
                if ts:
                    try:
                        event_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if event_dt < cutoff:
                            removed += 1
                            continue
                    except (ValueError, TypeError):
                        pass
                kept.append(line)
            if removed:
                fd, tmp = tempfile.mkstemp(
                    prefix="events-", suffix=".jsonl", dir=str(self.path.parent)
                )
                try:
                    # mkstemp creates 0600; keep the original file's mode so
                    # other tooling reading the ledger is unaffected.
                    os.fchmod(fd, self.path.stat().st_mode & 0o7777)
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        handle.write("\n".join(kept) + "\n")
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(tmp, self.path)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return removed

    def summary(self) -> dict[str, Any]:
        totals: dict[str, Any] = {
            "runs": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cost_usd": 0.0,
            "by_provider": {},
        }
        for event in self.events():
            if event.get("type") != "process_finished":
                continue
            totals["runs"] += 1
            usage = event.get("usage") or {}
            provider = event.get("provider") or "unknown"
            provider_totals = totals["by_provider"].setdefault(
                provider,
                {
                    "runs": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cost_usd": 0.0,
                },
            )
            provider_totals["runs"] += 1
            for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                value = _numeric_usage(usage, key)
                totals[key] += value
                if key in provider_totals:
                    provider_totals[key] += value
            cost = _numeric_usage(usage, "cost_usd") or _numeric_usage(usage, "total_cost_usd")
            totals["cost_usd"] += cost
            provider_totals["cost_usd"] += cost
        return totals

    def snapshots(self, *, since: datetime | None = None) -> list[dict[str, Any]]:
        """Return raw subscription-window snapshots from process events.

        Each entry carries the ``ts``, ``item_id``, ``provider``, and the
        before/after quota snapshots captured around the run.  These are raw
        evidence: provider quota windows are not safely additive, so callers
        must not sum across entries.
        """
        results: list[dict[str, Any]] = []
        for event in self.events(since=since):
            before = event.get("quota_snapshot_before")
            after = event.get("quota_snapshot_after")
            if before is None and after is None:
                continue
            results.append(
                {
                    "ts": event.get("ts"),
                    "item_id": event.get("item_id"),
                    "provider": event.get("provider"),
                    "attempt": event.get("attempt"),
                    "quota_snapshot_before": before,
                    "quota_snapshot_after": after,
                }
            )
        return results


def _numeric_usage(data: Any, key: str) -> float | int:
    if not isinstance(data, dict):
        return 0
    aliases = {
        "cache_read_input_tokens": ("cache_read_input_tokens", "cache_read_tokens"),
        "cache_creation_input_tokens": (
            "cache_creation_input_tokens",
            "cache_write_tokens",
        ),
        "cost_usd": ("cost_usd", "estimated_cost_usd"),
    }
    for candidate in aliases.get(key, (key,)):
        value = data.get(candidate)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    nested = data.get("usage")
    if isinstance(nested, dict):
        return _numeric_usage(nested, key)
    return 0


class LoopRunner:
    # Cooldown before an externally-caused needs_attention park (transient/
    # outage/rate_limit) returns to the queue on its own. Long enough that a
    # dependency gets a real chance to recover, short enough that a healed
    # gateway doesn't leave research parked for hours awaiting a human.
    AUTO_RESUME_COOLDOWN_SECONDS = 1800

    def __init__(
        self,
        store: QueueStore,
        ledger: UsageLedger,
        *,
        poll_seconds: float = 1.0,
        usage_command: list[str] | None = None,
        worker: str = "worker-1",
        profile: str | None = None,
        auto_resume_cooldown_seconds: int | None = None,
        lanes: tuple[str, ...] = ("research",),
        checkpoint_adapter: Any | None = None,
        discovery_adapter: Any | None = None,
    ):
        self.store = store
        self.ledger = ledger
        if not math.isfinite(poll_seconds) or poll_seconds <= 0:
            raise QueueError("poll_seconds must be finite and positive")
        self.poll_seconds = poll_seconds
        self.usage_command = usage_command
        self.worker = validate_item_id(worker)
        self.profile = validate_profile_name(profile) if profile is not None else None
        if auto_resume_cooldown_seconds is None:
            auto_resume_cooldown_seconds = self.AUTO_RESUME_COOLDOWN_SECONDS
        if auto_resume_cooldown_seconds < 0:
            raise QueueError("auto_resume_cooldown_seconds must not be negative")
        self.auto_resume_cooldown_seconds = auto_resume_cooldown_seconds
        from .queue import _validate_lane

        for lane in lanes:
            _validate_lane(lane)  # fail at startup, not on the first claim
        if not lanes:
            raise QueueError("a worker needs at least one lane")
        self.lanes = tuple(lanes)
        # Checkpoints have a separate structured adapter entry point.  It is
        # intentionally not synthesized from the ordinary topic command.
        self.checkpoint_adapter = checkpoint_adapter
        self.discovery_adapter = discovery_adapter
        self.log_dir = store.root / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    # --- systemd notify / watchdog ---
    # Implemented directly against $NOTIFY_SOCKET with a stdlib unix datagram
    # socket instead of importing python3-systemd: the service unit is
    # Type=notify, so a silently missing binding (e.g. a venv interpreter
    # without systemd bindings) would mean READY=1 is never sent and systemd
    # would kill the worker at every start. Stdlib-only removes that failure
    # mode entirely. No-op when NOTIFY_SOCKET is unset (tests, manual runs).
    @staticmethod
    def _notify(message: str) -> bool:
        addr = os.environ.get("NOTIFY_SOCKET")
        if not addr:
            return False
        if addr.startswith("@"):
            # Abstract-namespace socket: leading NUL replaces '@'.
            addr = "\0" + addr[1:]
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
                sock.sendto(message.encode("utf-8"), addr)
            return True
        except OSError:
            return False

    @classmethod
    def _notify_watchdog(cls) -> bool:
        return cls._notify("WATCHDOG=1")

    # --- log retention ---
    # Per-attempt logs accumulate without bound: a recurring 15-minute item
    # produces ~96 logs/day.  Sweep logs older than the retention window on
    # every worker cycle so the directory stays bounded.
    LOG_RETENTION_DAYS = 90

    def _sweep_old_logs(self, *, retention_days: int = LOG_RETENTION_DAYS) -> int:
        """Delete attempt logs older than *retention_days*. Returns count removed."""
        cutoff = time.time() - retention_days * 86400
        removed = 0
        for entry in self.log_dir.iterdir():
            if not entry.is_file() or not entry.name.endswith(".log"):
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    entry.unlink()
                    removed += 1
            except OSError:
                pass
        return removed

    def _log_path(self, item_id: str, attempts: int, stamp: str) -> Path:
        validate_item_id(item_id)
        log_root = self.log_dir.resolve()
        candidate = self.log_dir / f"{item_id}-attempt-{attempts}-{stamp}.log"
        resolved = candidate.resolve()
        if resolved.parent != log_root:
            raise QueueError("log path must resolve inside the queue log directory")
        return resolved

    def _usage_snapshot(self) -> dict[str, Any] | None:
        if not self.usage_command:
            return None
        try:
            result = subprocess.run(
                self.usage_command,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return None
        return None

    @staticmethod
    def _terminate(process: subprocess.Popen[Any]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        # A zombie still answers signal 0 but is already dead for supervision
        # purposes (its real parent will reap it; waiting on it would hang).
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            state = stat.rsplit(")", 1)[1].split()[0]
            return state != "Z"
        except (OSError, IndexError):
            return True

    @staticmethod
    def _pid_start_epoch(pid: int) -> float | None:
        """Best-effort process start time (epoch seconds) from /proc."""
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            boot_line = Path("/proc/stat").read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            btime = None
            for line in boot_line.splitlines():
                if line.startswith("btime "):
                    btime = int(line.split()[1])
                    break
            if btime is None:
                return None
            # Field 22 (1-indexed) is starttime in clock ticks; the comm field
            # may contain spaces, so parse after the closing paren.
            after_comm = stat.rsplit(")", 1)[1].split()
            start_ticks = int(after_comm[19])
            ticks = os.sysconf("SC_CLK_TCK")
            return btime + start_ticks / ticks
        except (IndexError, ValueError, OSError):
            return None

    @staticmethod
    def _boot_id() -> str | None:
        try:
            return (
                Path("/proc/sys/kernel/random/boot_id")
                .read_text(encoding="utf-8")
                .strip()
            )
        except OSError:
            return None

    @staticmethod
    def _pid_start_ticks(pid: int) -> int | None:
        """Immutable per-boot process identity: starttime in clock ticks."""
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            return int(stat.rsplit(")", 1)[1].split()[19])
        except (OSError, IndexError, ValueError):
            return None

    @staticmethod
    def _pid_cmdline(pid: int) -> list[str] | None:
        try:
            raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            return None
        return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]

    def _fingerprint(self, pid: int) -> dict[str, Any]:
        """Capture the launched child's identity for restart-safe adoption."""
        return {
            "boot_id": self._boot_id(),
            "start_ticks": self._pid_start_ticks(pid),
            "cmdline": self._pid_cmdline(pid),
        }

    @staticmethod
    def _stop_file_path(item: dict[str, Any]) -> Path | None:
        stop_file = item.get("stop_file")
        if not stop_file:
            return None
        path = Path(stop_file)
        if not path.is_absolute():
            path = Path(item["cwd"]) / path
        return path

    @classmethod
    def _stop_file_signature(cls, item: dict[str, Any]) -> tuple[int, int] | None:
        """(mtime_ns, size) of the declared stop file, or None if absent."""
        path = cls._stop_file_path(item)
        if path is None:
            return None
        try:
            stat = path.stat()
            return (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return None

    @classmethod
    def _check_stop_file(
        cls, item: dict[str, Any], signature_before: tuple[int, int] | None
    ) -> str | None:
        """Inspect a loop-declared stop file for terminal intent.

        Only counts the file if THIS run created or modified it (same
        freshness rule as usage_file): a stale STOP surviving from an earlier
        attempt must not re-trigger a terminal transition after the operator
        resumed or restarted the item.

        Returns ``"done"`` when the fresh file begins with ``DONE``, the
        trimmed body (typically ``NEEDS-OPERATOR: …``) when it signals manual
        attention, or ``None`` when no stop file is declared, absent, empty,
        or unchanged since before the run.
        """
        path = cls._stop_file_path(item)
        if path is None:
            return None
        signature_after = cls._stop_file_signature(item)
        if signature_after is None or signature_after == signature_before:
            return None
        try:
            body = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return None
        if not body:
            return None
        # First token, punctuation-tolerant ("DONE", "DONE:", "DONE — …")
        # without the false prefix match of startswith ("DONEXYZ").
        first_token = body.split(None, 1)[0].rstrip(":.,;!").upper()
        if first_token == "DONE":
            return "done"
        return body

    @staticmethod
    def _contract_topic(item: dict[str, Any]) -> bool:
        """True for a contract-bearing research topic — recurring by nature,
        and the SATURATION GATE (not the agent) decides its completion.

        Recurrence is intrinsic to the contract, never a per-item setting:
        a topic with SEMANTIC-STATE.json iterates until saturated, paced
        solely by its station's interval; anything else is a bounded command
        that completes on success (operator ruling 2026-09-09 — mechanics
        live on stations, the queue holds only order/contracts/substance).
        Coverage (every obligation terminal, validator green) is what an
        agent can see and self-certify; saturation is a property of
        consecutive iterations that only the queue can observe. Where both
        exist, the measured signal wins and the self-declared one is
        discarded.
        """
        return (Path(item["cwd"]) / "SEMANTIC-STATE.json").is_file()

    def _checkpoint_due(self, item: dict[str, Any]) -> str | None:
        """Fleet obligations-checkpoint trigger — STATION mechanics.

        The station monitors the topic's recorded history (ordinary
        iterations completed, deepening entry) against the fleet policy in
        the stations' collective config and assigns the checkpoint iteration;
        a topic never schedules its own (operator design 2026-09-08/09:
        every 25th iteration, or once it first enters deepening). Returns the
        assignment reason, or None when no checkpoint is due.
        """
        if not self._contract_topic(item):
            return None
        fleet = self.store.stations.fleet()
        if (
            fleet.get("checkpoint_on_deepening")
            and item.get("deepening_seen")
            and not item.get("deepening_checkpoint_done")
        ):
            return "deepening"
        every = int(fleet.get("checkpoint_every") or 0)
        done = int(item.get("iterations_completed") or 0)
        last = item.get("last_checkpoint_iteration")
        # ">= every since the last checkpoint" rather than a modulo match:
        # a topic whose counter was backfilled from history (or whose fleet
        # cadence changed) must owe at most one checkpoint, immediately —
        # never wait for the next exact multiple.
        base = last if isinstance(last, int) and not isinstance(last, bool) else 0
        if every > 0 and done - base >= every:
            return f"iteration-{done}"
        return None

    @classmethod
    def _discard_stop_file(cls, item: dict[str, Any]) -> None:
        """Remove a STOP file whose terminal intent this run refuses to honor.

        Leaving it on disk would park the topic anyway: the chassis exits 3
        on ANY STOP present at the next iteration's start, so an ignored DONE
        would silently become a stall instead of the deepening pass the gate
        just asked for.
        """
        path = cls._stop_file_path(item)
        if path is None:
            return
        try:
            path.unlink()
        except OSError:
            pass

    @staticmethod
    def _completion_error(item: dict[str, Any]) -> str | None:
        """Return why a fresh DONE is semantically invalid, or None if valid.

        A configured completion_command is authoritative. Without one, a
        research topic (any item whose cwd carries SEMANTIC-STATE.json) gets
        the chassis validator BY DEFAULT — completion validation must never
        depend on optional per-item configuration, or a topic that
        self-declares `STOP DONE` completes with open obligations, the exact
        failure class this engine exists to prevent. Items with no semantic
        state (generic loop commands) keep the previous accept-on-DONE
        behavior: there is nothing semantic to validate.
        """
        command = item.get("completion_command")
        if not command:
            if not (Path(item["cwd"]) / "SEMANTIC-STATE.json").is_file():
                return None
            command = [
                sys.executable,
                str(_CHASSIS_DIR / "semantic-state.py"),
                "validate",
                item["cwd"],
            ]
            completion_lock = item.get("completion_lock")
            if completion_lock:
                command += ["--lock-sha256", completion_lock]
            if item.get("internal_citations"):
                command += ["--allow-internal-citations"]
            # Mirror the chassis's own DONE validation exactly: it honors
            # RESEARCH_LOOP_TOPICS_ROOT for resolving internal citations, and
            # this re-validation must never reject a DONE the chassis just
            # accepted because the two resolved different topics roots.
            topics_root = os.environ.get("RESEARCH_LOOP_TOPICS_ROOT")
            if topics_root:
                command += ["--topics-root", topics_root]
        try:
            result = subprocess.run(
                command,
                cwd=item["cwd"],
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "completion validation timed out after 60 seconds"
        except OSError as exc:
            return f"completion validation could not run: {exc}"
        if result.returncode == 0:
            return None
        output = (result.stdout + result.stderr).strip()
        return output[-4000:] or (
            f"completion validation failed with exit code {result.returncode}"
        )

    def _pid_belongs_to_item(self, item: dict[str, Any]) -> bool:
        """Is the recorded PID still the exact process this claim launched?

        Primary check: the fingerprint captured at launch — (boot_id,
        /proc start_ticks) is immutable and unique per PID per boot, so a
        recycled PID can never match. Legacy items without a fingerprint fall
        back to cmdline comparison against the item command plus a start-time
        window; on any unverifiable mismatch we refuse adoption, because
        adopting an unrelated process means later pause/restart would SIGTERM
        an innocent process group.
        """
        pid = item.get("last_pid")
        if not pid or not self._pid_alive(pid):
            return False
        fingerprint = item.get("last_pid_fingerprint")
        if fingerprint:
            if fingerprint.get("boot_id") != self._boot_id():
                return False
            recorded_ticks = fingerprint.get("start_ticks")
            if recorded_ticks is None:
                return False
            return self._pid_start_ticks(pid) == recorded_ticks
        # Legacy state without a fingerprint: require the live cmdline to
        # reference the item's recorded command before considering timing.
        cmdline = self._pid_cmdline(pid)
        if not cmdline:
            return False
        command = item.get("command") or []
        if not command or not any(command[0] in part for part in cmdline):
            return False
        started_at = item.get("started_at")
        if not started_at:
            return False
        pid_start = self._pid_start_epoch(pid)
        if pid_start is None:
            return False
        claim_epoch = datetime.fromisoformat(
            started_at.replace("Z", "+00:00")
        ).timestamp()
        return pid_start >= claim_epoch - 120

    def _terminate_pid(self, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not self._pid_alive(pid):
                return
            time.sleep(0.1)
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _resume_running_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Handle an item found `running` after a worker restart.

        Never launches a second copy. If the recorded process is gone, requeue
        the item (loops checkpoint their ledgers, so re-running is safe). If it
        is still alive, adopt supervision: honor pause/restart controls, and on
        natural exit fail closed to needs_attention because a reparented
        orphan's exit status is unobservable.
        """
        item_id = item["id"]
        generation = item["restart_generation"]
        pid = item.get("last_pid")
        if pid is None or not self._pid_belongs_to_item(item):
            outcome, _ = self.store.finalize_run(
                item_id,
                expected_restart_generation=generation,
                requested_control="restarted",
                outcome="restarted",
                exit_code=-1,
            )
            self.ledger.append(
                {
                    "type": "process_reclaimed",
                    "item_id": item_id,
                    "title": item["title"],
                    "provider": item.get("provider"),
                    "worker": self.worker,
                    "profile": self.profile,
                    "attempt": item["attempts"],
                    "stale_pid": pid,
                    "outcome": outcome,
                    "note": "worker restarted; recorded process not found — requeued",
                }
            )
            return {"item_id": item_id, "outcome": outcome, "exit_code": None}

        self.ledger.append(
            {
                "type": "process_adopted",
                "item_id": item_id,
                "title": item["title"],
                "provider": item.get("provider"),
                "worker": self.worker,
                "profile": self.profile,
                "attempt": item["attempts"],
                "pid": pid,
                "note": "worker restarted; supervising still-running process instead of relaunching",
            }
        )
        control_outcome = None
        while self._pid_alive(pid):
            # Same watchdog rule as the launch path: adoption supervision can
            # also run for hours and must keep systemd's watchdog fed.
            self._notify_watchdog()
            current = self.store.get(item_id)
            state = self.store.snapshot()
            if state["paused"]:
                control_outcome = "global_paused"
                self._terminate_pid(pid)
                break
            if current["desired_state"] == "paused":
                control_outcome = "paused"
                self._terminate_pid(pid)
                break
            if current["restart_generation"] != generation:
                control_outcome = "restarted"
                self._terminate_pid(pid)
                break
            time.sleep(self.poll_seconds)

        if control_outcome is not None:
            outcome, _ = self.store.finalize_run(
                item_id,
                expected_restart_generation=generation,
                requested_control=control_outcome,
                outcome=control_outcome,
                exit_code=-int(signal.SIGTERM),
            )
            exit_code: int | None = -int(signal.SIGTERM)
        else:
            outcome, _ = self.store.finalize_run(
                item_id,
                expected_restart_generation=generation,
                requested_control=None,
                outcome="needs_attention",
                exit_code=-1,
                error_kind=FailureKind.CONFIGURATION.value,
                message=(
                    f"adopted process {pid} (started before a queue-worker restart) "
                    "exited; its exit status and log are not observable by the new "
                    "worker. Verify the loop's own ledgers, then resume or restart "
                    "this item."
                ),
            )
            exit_code = None
        self.ledger.append(
            {
                "type": "process_finished",
                "item_id": item_id,
                "title": item["title"],
                "provider": item.get("provider"),
                "worker": self.worker,
                "profile": self.profile,
                "attempt": item["attempts"],
                "exit_code": exit_code,
                "adopted": True,
                "outcome": outcome,
                "usage": None,
            }
        )
        return {"item_id": item_id, "outcome": outcome, "exit_code": exit_code}

    def _park_managed_orphan(self, item: dict[str, Any], lease: dict[str, Any]) -> dict[str, Any]:
        """Fail closed for a restarted non-ordinary lease.

        Checkpoint and discovery adapters do not expose a durable child PID to
        a new supervisor.  Treating their durable lease as permission to run
        another adapter could duplicate an operator-facing review, so atomically
        park the item and release the assignment instead.
        """
        assert self.store.control is not None and self.store.scheduler is not None
        item_id, kind = item["id"], lease.get("execution_kind")
        reason = f"supervisor restarted with unknown {kind} child; operator review required"
        with self.store.control.transaction(actor="runner", operation_id=f"managed-orphan:{lease['lease_id']}") as state:
            entry = next((entry for entry in state["queue"].get("items", []) if entry.get("id") == item_id), None)
            if isinstance(entry, dict):
                entry.update({"status": "needs_attention", "desired_state": "paused", "last_error": reason, "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
            if kind == "checkpoint":
                topic = state["work"].get("topics", {}).get(item_id)
                if isinstance(topic, dict):
                    topic["review_state"] = "needs_attention"
                    episode = state["work"].get("episodes", {}).get(topic.get("active_episode_id"))
                    if isinstance(episode, dict):
                        episode.update({"state": "needs_attention", "failure_reason": reason})
            record = state["work"].setdefault("assignments", {}).get(str(lease.get("station_id")))
            if isinstance(record, dict) and isinstance(record.get("current"), dict) and record["current"].get("lease_id") == lease.get("lease_id"):
                record["current"] = None
                record["handoff_reason"] = None
                record["draining"] = False
                self.store.scheduler.reconcile_state(state)
        self.store._managed_leases.pop(item_id, None)
        self.ledger.append({"type": "managed_orphan_parked", "item_id": item_id, "worker": self.worker,
                            "execution_kind": kind, "lease_id": lease.get("lease_id"), "note": reason})
        return {"item_id": item_id, "outcome": "needs_attention", "exit_code": None, "execution_kind": kind}

    @staticmethod
    def _read_iteration_result(
        result_path: Path, signature_before: tuple[int, int] | None
    ) -> dict[str, Any] | None:
        """Read the chassis's structured result record for THIS run, or None.

        The chassis→queue interface (chassis/run-topic.sh write_result):
        chassis-level facts about the iteration, preferred over scraping
        transcript prose. Freshness-checked exactly like usage_file so a
        stale record from an earlier attempt is never misattributed.
        """
        try:
            stat = result_path.stat()
        except OSError:
            return None
        if (stat.st_mtime_ns, stat.st_size) == signature_before:
            return None
        try:
            value = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _structured_failure_kind(
        result: dict[str, Any] | None,
    ) -> FailureKind | None:
        """FailureKind from the result record's error_class, if it names one.

        When the chassis records a valid kind it is authoritative — it saw
        the actual failure; the queue only sees transcript prose. Absent or
        unrecognized values fall back to tail-pattern classification.
        """
        if not result:
            return None
        hint = result.get("error_class")
        if not isinstance(hint, str):
            return None
        try:
            kind = FailureKind(hint)
        except ValueError:
            return None
        return None if kind is FailureKind.NONE else kind

    # Applied when a research topic configures no stall_limit of its own.
    # Matches the value the current deployments pin explicitly.
    DEFAULT_STALL_LIMIT = 6
    # Saturation gate: consecutive semantically-valid runs with an unchanged
    # semantic signature required before a recurring research topic completes.
    # Must stay below DEFAULT_STALL_LIMIT so saturation wins before the stall
    # guard would park a genuinely finished topic.
    DEFAULT_SATURATION_LIMIT = 3

    @staticmethod
    def _default_progress_command(item: dict[str, Any]) -> list[str] | None:
        """The chassis signature probe for research topics with no
        progress_command configured.

        Liveness detection must not depend on optional per-item
        configuration any more than completion validation may (see
        _completion_error): with the chassis's first-miss exit-5 gone, an
        unconfigured research topic would otherwise have NO stall detection
        at all and could loop forever without converging. Items with no
        SEMANTIC-STATE.json (generic loop commands) have no semantic
        signature to probe and keep their explicit-config-only behavior.
        """
        if item.get("progress_command"):
            return item["progress_command"]
        if not (Path(item["cwd"]) / "SEMANTIC-STATE.json").is_file():
            return None
        return [
            sys.executable,
            str(_CHASSIS_DIR / "semantic-state.py"),
            "signature",
            item["cwd"],
        ]

    def _progress_signature(self, item: dict[str, Any]) -> str | None:
        """Run the item's progress probe to capture a qualifying-progress signature.

        The command prints a deterministic digest of ledger state that counts
        as real progress (e.g. unit states + admitted-source count), excluding
        refinement noise. None when unconfigured or the probe fails — the
        guard only accuses on positive evidence.
        """
        command = self._default_progress_command(item)
        if not command:
            return None
        try:
            result = subprocess.run(
                command,
                cwd=item["cwd"],
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return result.stdout.strip()[:4000]

    def _apply_stall_guard(
        self, item: dict[str, Any], outcome: str
    ) -> tuple[str, dict[str, Any] | None]:
        """Independent auditor for successful-but-non-converging loops.

        After a successful run (completed/scheduled), compare the item's
        progress signature with the previous run's. stall_limit consecutive
        unchanged signatures escalate a recurring item to needs_attention —
        the queue does not trust the loop's own convergence bookkeeping.
        Returns (possibly overridden outcome, stall event or None).
        """
        if outcome not in {"scheduled", "completed"}:
            return outcome, None
        if self._default_progress_command(item) is None:
            return outcome, None
        stall_limit = item.get("stall_limit") or self.DEFAULT_STALL_LIMIT
        signature = self._progress_signature(item)
        stall_count, _ = self.store.record_progress_signature(item["id"], signature)
        event = {
            "type": "stall_guard",
            "item_id": item["id"],
            "worker": self.worker,
            "profile": self.profile,
            "stall_count": stall_count,
            "stall_limit": stall_limit,
            "signature_present": signature is not None,
        }
        if stall_count < stall_limit or outcome != "scheduled":
            return outcome, event
        message = (
            f"stall guard: {stall_count} consecutive successful runs with no "
            "qualifying ledger progress (progress_command signature unchanged). "
            "The loop reports success but is not converging — review its "
            "ledgers, then resume or remove this item."
        )
        self.store.mark_needs_attention(
            item["id"],
            exit_code=0,
            error_kind="stalled",
            message=message,
            consume_failure=False,
        )
        event["escalated"] = True
        return "needs_attention", event

    def _process_due_refreshes(self) -> None:
        """Requeue any completed item whose topic_refresh schedule has come
        due. Runs before claim_next() on every tick so a freshly-reopened
        item is immediately eligible for this same call to claim. Silently
        skips an item another worker already reopened in the meantime (a
        normal multi-worker race, not a failure); only a genuine
        refresh-policy.py failure escalates to needs_attention.
        """
        for due in self.store.due_refreshes():
            item = self.store.get(due["id"])
            if item["status"] != "completed":
                continue
            try:
                refresh_mod.apply_refresh(self.store, due["id"], due["mode"])
            except QueueError as exc:
                self.store.mark_needs_attention(
                    due["id"], exit_code=1, error_kind="refresh_failed", message=str(exc)
                )

    def _process_auto_resumes(self) -> None:
        """Return externally-parked items to the queue once their cooldown passes.

        Runs before claim_next() on every tick (like _process_due_refreshes)
        so a freshly recovered item is immediately eligible for this same
        claim call. Each resume is a ledger event — the park-and-recover
        history stays queryable even though the item's own error fields are
        cleared by its next successful run.
        """
        for item in self.store.auto_resume_transient(
            cooldown_seconds=self.auto_resume_cooldown_seconds
        ):
            self.ledger.append(
                {
                    "type": "auto_resume",
                    "item_id": item["id"],
                    "title": item.get("title"),
                    "worker": self.worker,
                    "resumed_from_kind": item.get("resumed_from_kind"),
                    "cooldown_seconds": self.auto_resume_cooldown_seconds,
                }
            )

    def run_once(self) -> dict[str, Any] | None:
        if self.store.control is not None and self.lanes == ("intake",):
            return self._run_managed_discovery_once()
        self._process_due_refreshes()
        self._process_auto_resumes()
        item = self.store.claim_next(worker=self.worker, lanes=self.lanes)
        if item is None:
            return None
        managed_lease = item.get("_control_lease") if self.store.control is not None else None
        if item.get("resumed"):
            if isinstance(managed_lease, dict) and managed_lease.get("execution_kind") != "research":
                return self._park_managed_orphan(item, managed_lease)
            return self._resume_running_item(item)
        item_id = item["id"]
        if isinstance(managed_lease, dict) and managed_lease.get("execution_kind") == "checkpoint":
            return self._run_managed_checkpoint(item, managed_lease)
        generation = item["restart_generation"]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_path = self._log_path(item_id, item["attempts"], stamp)
        usage_path = None
        usage_signature_before = None
        if item.get("usage_file"):
            usage_path = Path(item["usage_file"])
            if not usage_path.is_absolute():
                usage_path = Path(item["cwd"]) / usage_path
            try:
                usage_stat = usage_path.stat()
                usage_signature_before = (usage_stat.st_mtime_ns, usage_stat.st_size)
            except OSError:
                usage_signature_before = None
        # Same freshness rule as usage_file: only a stop file that THIS run
        # created or modified counts as a signal. A stale STOP left over from
        # an earlier attempt is ignored here — the loop's own entrypoint
        # already refuses to run while STOP is present (exit 3 →
        # needs_attention), so pre-existing files stay the loop's contract.
        stop_signature_before = self._stop_file_signature(item)
        # The chassis's structured result record (chassis/run-topic.sh
        # write_result) — the chassis→queue interface, preferred over
        # scraping transcript prose. Freshness-checked like usage_file.
        result_path = Path(item["cwd"]) / "logs" / "latest-result.json"
        try:
            result_stat = result_path.stat()
            result_signature_before = (result_stat.st_mtime_ns, result_stat.st_size)
        except OSError:
            result_signature_before = None
        before_usage = self._usage_snapshot()
        started = time.monotonic()
        self.ledger.append(
            {
                "type": "process_started",
                "item_id": item_id,
                "title": item["title"],
                "provider": item.get("provider"),
                "worker": self.worker,
                "profile": self.profile,
                "attempt": item["attempts"],
                "quota_snapshot": before_usage,
            }
        )
        startup_error = None
        checkpoint_boundary_episode: str | None = None
        child_env = os.environ.copy()
        if self.profile is not None:
            child_env["RESEARCH_LOOP_PROFILE"] = self.profile
        else:
            child_env.pop("RESEARCH_LOOP_PROFILE", None)
        # Station configuration: the WORKER's agent profile decides which
        # harness/model pair runs this iteration. Items carry no binding at
        # all — mechanics live exclusively in the stations' collective config
        # (operator ruling 2026-09-09); with no profile, the chassis defaults
        # apply.
        profile = self.store.worker_agents(self.worker)
        if self.store.control is not None:
            station_id = self.store.scheduler.station_id(self.worker) if self.store.scheduler else None
            pair = self.store.control.resolve_station_pair(station_id)
            primary, secondary = pair["primary"], pair["secondary"]
            # A registered profile, not a friendly profile ID or agent payload,
            # is the only managed launch authority. The chassis accepts this
            # JSON envelope only for its packaged adapters.
            child_env["RESEARCH_LOOP_MANAGED_PRIMARY_PROFILE"] = json.dumps(primary, sort_keys=True)
            child_env["RESEARCH_LOOP_MANAGED_SECONDARY_PROFILE"] = json.dumps(secondary, sort_keys=True)
            profile = {"agent_main": primary["adapter"], "agent_secondary": secondary["id"],
                       "agent_model": primary["model"], "agent_executable": primary["executable"],
                       "agent_argv": primary["argv"]}
            if primary["adapter"] not in {"codex", "claude", "hermes"}:
                raise QueueError(f"managed profile adapter {primary['adapter']!r} has no packaged trusted runner")
        agent_main = profile.get("agent_main")
        if agent_main:
            # chassis/run-topic.sh already resolves this same variable to pick
            # a runner adapter.
            child_env["RESEARCH_LOOP_RUNNER"] = agent_main
        else:
            child_env.pop("RESEARCH_LOOP_RUNNER", None)
        agent_secondary = profile.get("agent_secondary")
        if agent_secondary:
            child_env["RESEARCH_LOOP_AGENT_SECONDARY"] = agent_secondary
        else:
            child_env.pop("RESEARCH_LOOP_AGENT_SECONDARY", None)
        child_env["RESEARCH_LOOP_WORKER"] = self.worker   # 9·0: iteration context names its worker
        # Model/flags are per-adapter env vars (RESEARCH_LOOP_<RUNNER>_MODEL /
        # _FLAGS); the profile sets them for whichever adapter it names.
        runner_key = (agent_main or "").upper().replace("-", "_")
        if runner_key:
            if profile.get("agent_model"):
                child_env[f"RESEARCH_LOOP_{runner_key}_MODEL"] = profile["agent_model"]
            if profile.get("agent_executable"):
                child_env[f"RESEARCH_LOOP_{runner_key}_BIN"] = profile["agent_executable"]
            if isinstance(profile.get("agent_argv"), list):
                child_env[f"RESEARCH_LOOP_{runner_key}_ARGV_JSON"] = json.dumps(profile["agent_argv"])
            if profile.get("agent_flags"):
                child_env[f"RESEARCH_LOOP_{runner_key}_FLAGS"] = profile["agent_flags"]
        child_env["RESEARCH_LOOP_GAP_POLICY"] = item.get("gap_policy") or "review"
        child_env["RESEARCH_LOOP_GAP_AUTO_LIMIT"] = str(item.get("gap_auto_limit") or 0)
        # Fleet checkpoint assignment: the station decides, the chassis
        # relays it into the prompt, and the finalize path below excludes the
        # pass from saturation accounting.
        # Controller state is the sole checkpoint scheduler.  Legacy queues
        # retain their historical behavior until explicitly migrated.
        checkpoint_reason = None if self.store.control is not None else self._checkpoint_due(item)
        if checkpoint_reason:
            child_env["RESEARCH_LOOP_ITERATION_TYPE"] = "checkpoint"
            child_env["RESEARCH_LOOP_CHECKPOINT_REASON"] = checkpoint_reason
        else:
            child_env.pop("RESEARCH_LOOP_ITERATION_TYPE", None)
            child_env.pop("RESEARCH_LOOP_CHECKPOINT_REASON", None)
        completion_lock = item.get("completion_lock")
        if completion_lock:
            child_env["RESEARCH_LOOP_COMPLETION_LOCK"] = completion_lock
        else:
            child_env.pop("RESEARCH_LOOP_COMPLETION_LOCK", None)
        child_env["RESEARCH_LOOP_INTERNAL_CITATIONS"] = (
            "1" if item.get("internal_citations") else "0"
        )
        # Topic research policy (gateway docs/STATION-CONTRACT.md §1): the queue item is
        # the single writer; the research tool's dispatcher injects these into every call
        # and rejects conflicting agent arguments. Items without a policy bind only the
        # topic id — the gateway's personal baseline applies.
        child_env["RESEARCH_TOPIC_ID"] = item["id"]
        research_policy = item.get("research_policy") or {}
        for env_name, key, as_bool in (
            ("RESEARCH_TOPIC_COMMERCIAL", "commercial", True),
            ("RESEARCH_TOPIC_ACCEPT_PER_ITEM", "accept_per_item", True),
            ("RESEARCH_TOPIC_DOMAIN", "domain", False),
        ):
            if key in research_policy:
                value = research_policy[key]
                child_env[env_name] = ("1" if value else "0") if as_bool else str(value)
            else:
                child_env.pop(env_name, None)
        try:
            with log_path.open("w", encoding="utf-8") as log:
                popen_identity: dict[str, Any] = {}
                if isinstance(managed_lease, dict):
                    from .access import prepare_agent_launch
                    additions, popen_identity = prepare_agent_launch(
                        self.store.root, item_id, managed_lease["lease_id"]
                    )
                    child_env.update(additions)
                process = subprocess.Popen(
                    item["command"],
                    cwd=item["cwd"],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                    env=child_env,
                    **popen_identity,
                )
                self.store.mark_pid(
                    item_id, process.pid, fingerprint=self._fingerprint(process.pid)
                )
                control_outcome = None
                while process.poll() is None:
                    # Keep the systemd watchdog fed for the entire child
                    # runtime: run_once() blocks here for hours on long
                    # research phases, and pinging only between runs would
                    # get the worker killed WatchdogSec into every long
                    # iteration.
                    self._notify_watchdog()
                    current = self.store.get(item_id)
                    state = self.store.snapshot()
                    if state["paused"]:
                        control_outcome = "global_paused"
                        self._terminate(process)
                        break
                    if current["desired_state"] == "paused":
                        control_outcome = "paused"
                        self._terminate(process)
                        break
                    if current["restart_generation"] != generation:
                        control_outcome = "restarted"
                        self._terminate(process)
                        break
                    time.sleep(self.poll_seconds)
                exit_code = process.wait()
        except OSError as exc:
            exit_code = 127
            startup_error = str(exc)
            try:
                log_path.write_text(startup_error + "\n", encoding="utf-8")
            except OSError:
                pass
            control_outcome = None

        duration = time.monotonic() - started
        try:
            output = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            output = startup_error or f"process exited {exit_code}"
        after_usage = self._usage_snapshot()
        usage = None
        if usage_path is not None:
            try:
                usage_stat = usage_path.stat()
                usage_signature_after = (usage_stat.st_mtime_ns, usage_stat.st_size)
                if usage_signature_after != usage_signature_before:
                    usage = json.loads(usage_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                usage = None

        iteration_result = self._read_iteration_result(
            result_path, result_signature_before
        )

        base_event = {
            "type": "process_finished",
            "item_id": item_id,
            "title": item["title"],
            "provider": item.get("provider"),
            "worker": self.worker,
            "profile": self.profile,
            "attempt": item["attempts"],
            "exit_code": exit_code,
            "duration_seconds": round(duration, 3),
            "log_path": str(log_path),
            "usage": usage,
            "quota_snapshot_before": before_usage,
            "quota_snapshot_after": after_usage,
        }
        if iteration_result is not None:
            # Capability degradation and progress facts become queryable queue
            # history instead of living only inside agent transcript prose.
            base_event["iteration_result"] = {
                key: iteration_result.get(key)
                for key in (
                    "outcome",
                    "signature_changed",
                    "sources_cited",
                    "stop_written",
                    "degraded_capabilities",
                    "research_failures",
                    "research_ok",
                )
            }

        # Research coverage from the iteration (STATION-CONTRACT.md §2): blockers are
        # per-item queue state keyed by the exact request; a request that ended blocked
        # stays a blocker until the same request succeeds or the operator resolves it
        # with a recorded reason (`resolve-research`).
        research_failures: list[dict] = []
        research_ok: list[str] = []
        research_coverage: dict = {}
        if isinstance(iteration_result, dict):
            research_failures = [f for f in (iteration_result.get("research_failures") or [])
                                 if isinstance(f, dict) and f.get("key") and f.get("source")]
            research_ok = [k for k in (iteration_result.get("research_ok") or []) if isinstance(k, str)]
            research_coverage = {s: c for s, c in (iteration_result.get("research_coverage") or {}).items()
                                 if isinstance(s, str) and isinstance(c, str)}
        research_blockers = self.store.update_research_blockers(
            item_id, failures=research_failures, cleared=research_ok, coverage=research_coverage
        )
        blocker_sources = sorted({b["source"] for b in research_blockers if b.get("source")})
        blocked_this_pass = any(
            f.get("coverage") in ("provider_unavailable", "auth_failed") for f in research_failures
        )

        error_kind = None
        message = None
        next_eligible_at = None
        consume_failure = True
        ignored_stop_done = False
        if control_outcome is not None:
            # The worker itself terminated the child to honor an operator
            # control (pause/restart); the nonzero exit is not a failure and
            # must not be classified or recorded as one.
            intended_outcome = control_outcome
        elif exit_code == 0:
            # Cadence is a station property, full stop: the pause between
            # iterations is the WORKER's interval (0 = continuous). Whether
            # the item recurs at all is intrinsic to its contract.
            recurring = self._contract_topic(item)
            pause_seconds = self.store.station_interval(self.worker)
            # Read the terminal signal before ledger accounting.  A zero exit
            # only means the subprocess returned normally; it does not make a
            # NEEDS-OPERATOR/configuration outcome successful research.
            stop_signal = self._check_stop_file(item, stop_signature_before)
            if stop_signal == "done" and recurring:
                # A contract-bearing research topic does not get to declare
                # itself finished (operator ruling 2026-09-04). The agent can
                # only observe coverage, and coverage is explicitly NOT
                # sufficient for DONE; three consecutive semantically-valid
                # passes with an unchanged signature are. Discard the claim
                # and let the gate below rule on the measured evidence.
                # NEEDS-OPERATOR keeps full authority: being blocked is a
                # fact only the agent holds, not a completion claim.
                self._discard_stop_file(item)
                stop_signal = None
                ignored_stop_done = True
            degraded_result = bool(
                isinstance(iteration_result, dict)
                and (
                    iteration_result.get("degraded_capabilities")
                    or iteration_result.get("outcome") in {"degraded_capability", "degraded_capabilities"}
                )
            )
            accepted_research = stop_signal is None and not blocked_this_pass and not degraded_result
            if isinstance(managed_lease, dict):
                accounting = accept_research_completion(
                    self.store.control, topic_id=item_id, run_id=managed_lease["lease_id"],
                    station_id=managed_lease["station_id"],
                    inventory_version=str(item.get("completion_lock") or item.get("inventory_version") or "unknown"), accepted=accepted_research,
                    deepening_entry=bool(accepted_research and isinstance(iteration_result, dict) and iteration_result.get("semantic_valid") is True),
                )
                checkpoint_boundary_episode = accounting.get("episode_id")
            else:
                self.store.record_iteration_accounting(
                    item_id, iteration_type="checkpoint" if checkpoint_reason else "ordinary",
                    deepening=bool(isinstance(iteration_result, dict) and iteration_result.get("semantic_valid") is True),
                    checkpoint_reason=checkpoint_reason,
                )
            if stop_signal is not None:
                # The loop wrote its own terminal STOP file during this
                # iteration (e.g. "DONE" or "NEEDS-OPERATOR: …").  For recurring
                # items this prevents a wasted rescheduled cycle; for bounded
                # items it is equivalent to the normal completed path but
                # carries the operator's terminal intent.
                if stop_signal == "done":
                    completion_error = self._completion_error(item)
                    if completion_error is None and research_blockers:
                        # Same condition as the saturation gate: unresolved required-research
                        # blockers prevent EVERY automatic completion branch, not just one.
                        completion_error = ("research blocked on " + ", ".join(blocker_sources)
                                            + " (unresolved capability failure; the same request "
                                            "succeeding or `resolve-research` clears it)")
                    if completion_error is None:
                        intended_outcome = "completed"
                        self.store.record_completion_coverage(item_id, {
                            "at": utc_now(),
                            "policy": item.get("research_policy"),
                            "coverage": self.store.get(item_id).get("research_coverage") or {},
                            "blockers": [],
                        })
                    else:
                        intended_outcome = "needs_attention"
                        error_kind = FailureKind.CONFIGURATION.value
                        message = completion_error
                else:
                    intended_outcome = "needs_attention"
                    error_kind = FailureKind.CONFIGURATION.value
                    message = stop_signal
            elif not recurring:
                if research_blockers:
                    intended_outcome = "needs_attention"
                    error_kind = FailureKind.CONFIGURATION.value
                    message = ("research blocked on " + ", ".join(blocker_sources)
                               + " (unresolved capability failure; the same request "
                               "succeeding or `resolve-research` clears it)")
                else:
                    intended_outcome = "completed"
                    if research_failures or research_ok or research_coverage:
                        self.store.record_completion_coverage(item_id, {
                            "at": utc_now(),
                            "policy": item.get("research_policy"),
                            "coverage": self.store.get(item_id).get("research_coverage") or {},
                            "blockers": [],
                        })
            elif checkpoint_reason:
                # An assigned obligations checkpoint is NEVER an ordinary
                # completion-accounted pass (CONTRACT-CORE / checkpoint
                # reference): its review work must neither advance the
                # saturation streak (a valid unchanged checkpoint is not
                # deepening evidence) nor void it (checkpoint card/proposal
                # writes are not reopened research). Leave the streak exactly
                # as it stands and schedule the next ordinary iteration.
                intended_outcome = "scheduled"
                next_at = datetime.now(timezone.utc) + timedelta(seconds=pause_seconds)
                next_eligible_at = next_at.isoformat().replace("+00:00", "Z")
            elif (
                isinstance(iteration_result, dict)
                and iteration_result.get("semantic_valid") is True
            ):
                # SATURATION GATE (operator ruling 2026-09-03: "saturation per
                # branch"). Coverage — every obligation terminal, gate valid —
                # is necessary but NOT sufficient for DONE. Once valid, the
                # loop's iterations become deepening passes (chase logged
                # leads, add evidence, elevate confidence on the weakest
                # terminal obligations); any pass that changes the semantic
                # signature resets the streak. Only saturation_limit
                # consecutive valid passes with an UNCHANGED signature —
                # positive evidence that deepening no longer changes anything
                # — completes the topic. The chassis measures; the queue
                # decides — re-validate with the pinned lock before acting.
                streak, verdict = saturation_decision(
                    signature_changed=bool(iteration_result.get("signature_changed")),
                    previous_streak=int(item.get("saturation_streak") or 0),
                    limit=int(item.get("saturation_limit") or self.DEFAULT_SATURATION_LIMIT),
                    blocked_this_pass=blocked_this_pass,
                    blockers=research_blockers,
                )
                if verdict == "complete":
                    completion_error = self._completion_error(item)
                    if completion_error is None:
                        intended_outcome = "completed"
                        self.store.record_completion_coverage(item_id, {
                            "at": utc_now(),
                            "policy": item.get("research_policy"),
                            "coverage": self.store.get(item_id).get("research_coverage") or {},
                            "blockers": [],
                        })
                        message = (
                            f"saturated: {streak} consecutive semantically-valid "
                            "deepening passes with an unchanged semantic signature "
                            "and no unresolved research blockers"
                        )
                    else:
                        intended_outcome = "needs_attention"
                        error_kind = FailureKind.CONFIGURATION.value
                        message = (
                            "chassis reports the semantic gate passing but the "
                            f"lock-pinned validation disagrees: {completion_error}"
                        )
                elif verdict == "held":
                    # Saturation reached but required research is blocked: completion is
                    # HELD, never granted on evidence gathered under a degraded channel
                    # (STATION-CONTRACT.md §2; the acceptance case of plan phase 8d).
                    self.store.record_saturation_streak(item_id, streak)
                    held_on = blocker_sources or sorted(
                        {f["source"] for f in research_failures if f.get("source")}
                    )
                    message = ("saturation held: research blocked on " + ", ".join(held_on)
                               + " — clears when the same request succeeds, or via `resolve-research`")
                    intended_outcome = "scheduled"
                    next_at = datetime.now(timezone.utc) + timedelta(seconds=pause_seconds)
                    next_eligible_at = next_at.isoformat().replace("+00:00", "Z")
                else:
                    self.store.record_saturation_streak(item_id, streak)
                    intended_outcome = "scheduled"
                    next_at = datetime.now(timezone.utc) + timedelta(seconds=pause_seconds)
                    next_eligible_at = next_at.isoformat().replace("+00:00", "Z")
            else:
                if int(item.get("saturation_streak") or 0):
                    # The gate stopped validating (an obligation reopened):
                    # saturation evidence is void.
                    self.store.record_saturation_streak(item_id, 0)
                intended_outcome = "scheduled"
                next_at = datetime.now(timezone.utc) + timedelta(seconds=pause_seconds)
                next_eligible_at = next_at.isoformat().replace("+00:00", "Z")
        else:
            kind = self._structured_failure_kind(iteration_result)
            if kind is None:
                kind = classify_failure(exit_code, output)
            error_kind = kind.value
            current = self.store.get(item_id)
            consume_failure = kind is not FailureKind.SUBSCRIPTION_LIMIT
            failure_number = current["consecutive_failures"] + (
                1 if consume_failure else 0
            )
            delay = retry_delay(kind, failure_number)
            message = output[-4000:] or f"process exited {exit_code}"
            if delay is not None and (
                kind is FailureKind.SUBSCRIPTION_LIMIT
                or failure_number < current["max_attempts"]
            ):
                intended_outcome = "backoff"
                next_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                next_eligible_at = next_at.isoformat().replace("+00:00", "Z")
            else:
                intended_outcome = "needs_attention"

        if checkpoint_boundary_episode and intended_outcome == "completed":
            # A same-boundary completion disposition is held until the due
            # separate checkpoint runs; research completion criteria itself is
            # unchanged and will be re-evaluated at the next ordinary ordinal.
            intended_outcome = "scheduled"
            next_eligible_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        outcome, _ = self.store.finalize_run(
            item_id,
            expected_restart_generation=generation,
            requested_control=control_outcome,
            outcome=intended_outcome,
            exit_code=exit_code,
            error_kind=error_kind,
            message=message,
            next_eligible_at=next_eligible_at,
            consume_failure=consume_failure,
        )
        if checkpoint_reason and exit_code == 0:
            # An assigned checkpoint legitimately leaves the progress
            # signature unchanged; ticking the stall guard for it would let
            # review passes accuse a healthy topic.
            stall_event = None
        else:
            outcome, stall_event = self._apply_stall_guard(item, outcome)
        event = {**base_event, "outcome": outcome}
        if ignored_stop_done:
            event["ignored_stop_done"] = True
        if error_kind is not None:
            event["failure_kind"] = error_kind
        self.ledger.append(event)
        if stall_event is not None:
            self.ledger.append(stall_event)
        if outcome == "completed":
            hook_event = self._run_completion_hook(item)
            if hook_event is not None:
                self.ledger.append(hook_event)
        return {"item_id": item_id, "outcome": outcome, "exit_code": exit_code}

    def _run_managed_discovery_once(self) -> dict[str, Any] | None:
        """Capped, independent managed intake lane; never research accounting."""
        assert self.store.control is not None
        control = self.store.control
        with control.transaction(actor="intake-worker") as state:
            work = state["work"]; current = work.setdefault("intake_assignment", {}).get("current")
            if current:
                # A prior intake worker may still own an unobservable provider
                # child.  Do not mint a second discovery pass from its lease.
                item_id = current.get("item_id") if isinstance(current, dict) else None
                entry = next((entry for entry in state["queue"].get("items", []) if entry.get("id") == item_id), None)
                if isinstance(entry, dict):
                    entry.update({"status": "needs_attention", "desired_state": "paused",
                                  "last_error": "supervisor restarted with unknown intake discovery child", "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
                if isinstance(item_id, str):
                    draft = work.get("intake_drafts", {}).get(item_id.removeprefix("discovery."))
                    if isinstance(draft, dict):
                        draft["status"] = "needs_attention"
                work["intake_assignment"].pop("current", None)
                return {"item_id": item_id, "outcome": "needs_attention", "execution_kind": "intake_discovery"}
            item = next((entry for entry in state["queue"].get("items", []) if entry.get("lane") == "intake" and entry.get("status") == "queued" and entry.get("desired_state", "queued") in {"queued", "running"}), None)
            if item is None: return None
            draft = work.get("intake_drafts", {}).get(item["id"].removeprefix("discovery."))
            if not isinstance(draft, dict) or draft.get("status") != "discovery_queued": return None
            lease_id = f"intake-{uuid.uuid4()}"
            work["intake_assignment"]["current"] = {"lease_id": lease_id, "lease_generation": 1,
                                                       "item_id": item["id"], "topic_id": item["id"],
                                                       "execution_kind": "intake_discovery"}
            item["status"] = "running"
            context = {"topic_id": draft["topic_id"], "draft_revision": draft["draft_revision"], "draft_hash": draft["draft_hash"], "mode": draft["mode"], "request_id": lease_id}
        try:
            adapter = self.discovery_adapter
            if adapter is None:
                from .access import prepare_agent_launch
                pair = control.resolve_station_pair(1)
                adapter = RegisteredCheckpointAdapter(pair["primary"])
                additions, identity = prepare_agent_launch(self.store.root, f"discovery.{context['topic_id']}", lease_id)
                prompt = (Path(__file__).parent / "chassis" / "DISCOVERY-PROMPT.md").read_text(encoding="utf-8").replace("${TOPIC_DIR}", str(self.store.root / "topics" / context["topic_id"])).replace("${QA_MODE}", context["mode"]).replace("${AGENT_NOTE}", "")
                context.update({"_launch_env": additions, "_popen_identity": identity,
                                "_cwd": str(self.store.root / "topics" / context["topic_id"]), "_prompt_text": prompt})
            result = adapter(dict(context))
            if not isinstance(result, dict): raise QueueError("discovery adapter must return an object")
            allowed = {"pass_kind", "restated_intent", "criteria", "traceability", "questions", "topic_space_findings", "proposed_obligations", "proposed_exclusions"}
            if set(result) - allowed: raise QueueError("discovery adapter returned unknown fields")
            payload = {"schema_version": 1, "request_id": context["request_id"], "expected_revision": control.snapshot()["revision"], "topic_id": context["topic_id"], "draft_revision": context["draft_revision"], "draft_hash": context["draft_hash"], **result}
            from .intake import IntakeService
            IntakeService(control, self.store.root / "topics", actor="intake-worker").record_discovery_result(payload)
            outcome = "awaiting_operator"
        except Exception as exc:
            outcome = "needs_attention"; error = str(exc)
        with control.transaction(actor="intake-worker") as state:
            work = state["work"]; work.setdefault("intake_assignment", {}).pop("current", None)
            entry = next(item for item in state["queue"]["items"] if item["id"] == f"discovery.{context['topic_id']}" )
            entry["status"] = "completed" if outcome == "awaiting_operator" else "needs_attention"
            if outcome != "awaiting_operator": entry["last_error"] = error
        return {"item_id": "discovery." + context["topic_id"], "outcome": outcome, "execution_kind": "intake_discovery"}

    def _run_managed_checkpoint(self, item: dict[str, Any], lease: dict[str, Any]) -> dict[str, Any]:
        assert self.store.control is not None and self.store.scheduler is not None
        topic = self.store.control.snapshot()["work"]["topics"].get(item["id"], {})
        episode_id = topic.get("active_episode_id")
        if not isinstance(episode_id, str):
            self.store.scheduler.finalize(lease["station_id"], lease["lease_id"])
            raise QueueError("checkpoint lease has no active episode")
        episode = start_checkpoint(self.store.control, episode_id=episode_id,
                                   station_id=lease["station_id"], run_id=lease["lease_id"])
        adapter = self.checkpoint_adapter
        if adapter is None:
            # The resolved primary profile is the production checkpoint
            # adapter authority.  It receives the structured task over stdin;
            # no ordinary topic command or user-supplied JSON executable is
            # consulted.
            primary = episode.get("resolved_agent_pair", {}).get("primary")
            if not isinstance(primary, dict) or not isinstance(primary.get("executable"), str) or not isinstance(primary.get("argv"), list):
                raise QueueError("checkpoint primary profile is not a runnable registered adapter")
            adapter = RegisteredCheckpointAdapter(primary, timeout_seconds=3600)
        context = {**episode, "run_id": lease["lease_id"], "topic": dict(item)}
        if isinstance(adapter, (SubprocessCheckpointAdapter, RegisteredCheckpointAdapter)):
            from .access import prepare_agent_launch
            additions, identity = prepare_agent_launch(self.store.root, item["id"], lease["lease_id"])
            context.update({"_launch_env": additions, "_popen_identity": identity, "_cwd": item["cwd"]})
        try:
            result = CheckpointRunner(adapter).run(context)
            final = finish_checkpoint(self.store.control, result)
            self.store.scheduler.finalize(lease["station_id"], lease["lease_id"])
            return {"item_id": item["id"], "outcome": final["state"], "exit_code": 0, "execution_kind": "checkpoint"}
        except (CheckpointError, ValueError) as exc:
            with self.store.control.transaction(actor="runner", operation_id=f"checkpoint-failed:{lease['lease_id']}") as state:
                current = state["work"]["episodes"].get(episode_id)
                if isinstance(current, dict):
                    current["state"] = "needs_attention"; current["failure_reason"] = str(exc)
                    state["work"]["topics"][item["id"]]["review_state"] = "needs_attention"
            self.store.scheduler.finalize(lease["station_id"], lease["lease_id"])
            return {"item_id": item["id"], "outcome": "needs_attention", "exit_code": 78, "execution_kind": "checkpoint"}

    # Completion hooks are given generous room (a corpus ingest embeds every
    # record) but never unbounded: a hung hook must not wedge the worker.
    COMPLETION_HOOK_TIMEOUT_SECONDS = 1800

    def _run_completion_hook(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Run the item's on_completed_command exactly once, after it lands
        completed.

        Operator ruling 2026-09-04: derived stores (e.g. a knowledge graph)
        are fed by a mechanical backfill at topic completion, never by the
        research agent writing per-source mid-loop. The hook is therefore a
        plain subprocess with the topic dir in its environment -- no LLM in
        the write path.

        The hook is derivative by definition: the completed research already
        exists in the topic's own ledgers. So a hook failure is recorded as a
        completion_hook event (ok=false) and NEVER changes the item's
        completed status -- re-run the command by hand after fixing whatever
        broke; it must be idempotent.
        """
        command = item.get("on_completed_command")
        if not command:
            return None
        env = {
            **os.environ,
            "RESEARCH_LOOP_TOPIC_DIR": item["cwd"],
            "RESEARCH_LOOP_ITEM_ID": item["id"],
        }
        started = datetime.now(timezone.utc)
        try:
            proc = subprocess.run(
                command,
                cwd=item["cwd"],
                env=env,
                capture_output=True,
                text=True,
                timeout=self.COMPLETION_HOOK_TIMEOUT_SECONDS,
            )
            exit_code: int | None = proc.returncode
            tail = ((proc.stdout or "") + (proc.stderr or ""))[-2000:]
        except subprocess.TimeoutExpired:
            exit_code = None
            tail = (
                f"completion hook timed out after "
                f"{self.COMPLETION_HOOK_TIMEOUT_SECONDS}s"
            )
        except OSError as error:
            exit_code = None
            tail = f"completion hook failed to start: {error}"
        return {
            "type": "completion_hook",
            "item_id": item["id"],
            "worker": self.worker,
            "command": list(command),
            "exit_code": exit_code,
            "ok": exit_code == 0,
            "duration_seconds": round(
                (datetime.now(timezone.utc) - started).total_seconds(), 3
            ),
            "output_tail": tail,
            "ts": started.isoformat().replace("+00:00", "Z"),
        }

    # Retention sweeps are daily housekeeping, not per-run work: the events
    # sweep re-reads the whole ledger, so running it every cycle would add
    # pointless I/O for a recurring 15-minute item.
    SWEEP_INTERVAL_SECONDS = 86400

    def run_forever(self, *, idle_sleep: float = 5.0) -> None:
        if not math.isfinite(idle_sleep) or idle_sleep <= 0:
            raise QueueError("idle_sleep must be finite and positive")
        self._notify("READY=1")
        next_sweep = time.monotonic()
        while True:
            result = self.run_once()
            self._notify_watchdog()
            if result is None:
                time.sleep(idle_sleep)
            if time.monotonic() >= next_sweep:
                # Best-effort housekeeping: must never take the worker down.
                # Runs during idle too, so a quiet queue still prunes.
                try:
                    self._sweep_old_logs()
                    self.ledger.sweep_old_events()
                except OSError:
                    pass
                next_sweep = time.monotonic() + self.SWEEP_INTERVAL_SECONDS
