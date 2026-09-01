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
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import refresh as refresh_mod
from .queue import QueueError, QueueStore, utc_now, validate_item_id


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

    def _progress_signature(self, item: dict[str, Any]) -> str | None:
        """Run the item's progress_command to capture a qualifying-progress signature.

        The command prints a deterministic digest of ledger state that counts
        as real progress (e.g. unit states + admitted-source count), excluding
        refinement noise. None when unconfigured or the probe fails — the
        guard only accuses on positive evidence.
        """
        command = item.get("progress_command")
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
        stall_limit = item.get("stall_limit")
        if not stall_limit or not item.get("progress_command"):
            return outcome, None
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
            item["id"], exit_code=0, error_kind="stalled", message=message
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
        self._process_due_refreshes()
        self._process_auto_resumes()
        item = self.store.claim_next(worker=self.worker)
        if item is None:
            return None
        if item.get("resumed"):
            return self._resume_running_item(item)
        item_id = item["id"]
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
        child_env = os.environ.copy()
        if self.profile is not None:
            child_env["RESEARCH_LOOP_PROFILE"] = self.profile
        else:
            child_env.pop("RESEARCH_LOOP_PROFILE", None)
        agent_main = item.get("agent_main")
        if agent_main:
            # chassis/run-topic.sh already resolves this same variable to pick
            # a runner adapter; a config-assigned "main agent" just sets it.
            child_env["RESEARCH_LOOP_RUNNER"] = agent_main
        else:
            child_env.pop("RESEARCH_LOOP_RUNNER", None)
        agent_secondary = item.get("agent_secondary")
        if agent_secondary:
            child_env["RESEARCH_LOOP_AGENT_SECONDARY"] = agent_secondary
        else:
            child_env.pop("RESEARCH_LOOP_AGENT_SECONDARY", None)
        child_env["RESEARCH_LOOP_GAP_POLICY"] = item.get("gap_policy") or "review"
        child_env["RESEARCH_LOOP_GAP_AUTO_LIMIT"] = str(item.get("gap_auto_limit") or 0)
        completion_lock = item.get("completion_lock")
        if completion_lock:
            child_env["RESEARCH_LOOP_COMPLETION_LOCK"] = completion_lock
        else:
            child_env.pop("RESEARCH_LOOP_COMPLETION_LOCK", None)
        child_env["RESEARCH_LOOP_INTERNAL_CITATIONS"] = (
            "1" if item.get("internal_citations") else "0"
        )
        try:
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    item["command"],
                    cwd=item["cwd"],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                    env=child_env,
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
                )
            }

        error_kind = None
        message = None
        next_eligible_at = None
        consume_failure = True
        if control_outcome is not None:
            # The worker itself terminated the child to honor an operator
            # control (pause/restart); the nonzero exit is not a failure and
            # must not be classified or recorded as one.
            intended_outcome = control_outcome
        elif exit_code == 0:
            repeat_seconds = item.get("repeat_seconds")
            stop_signal = self._check_stop_file(item, stop_signature_before)
            if stop_signal is not None:
                # The loop wrote its own terminal STOP file during this
                # iteration (e.g. "DONE" or "NEEDS-OPERATOR: …").  For recurring
                # items this prevents a wasted rescheduled cycle; for bounded
                # items it is equivalent to the normal completed path but
                # carries the operator's terminal intent.
                if stop_signal == "done":
                    completion_error = self._completion_error(item)
                    if completion_error is None:
                        intended_outcome = "completed"
                    else:
                        intended_outcome = "needs_attention"
                        error_kind = FailureKind.CONFIGURATION.value
                        message = completion_error
                else:
                    intended_outcome = "needs_attention"
                    error_kind = FailureKind.CONFIGURATION.value
                    message = stop_signal
            elif repeat_seconds is None:
                intended_outcome = "completed"
            else:
                intended_outcome = "scheduled"
                next_at = datetime.now(timezone.utc) + timedelta(seconds=repeat_seconds)
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
        outcome, stall_event = self._apply_stall_guard(item, outcome)
        event = {**base_event, "outcome": outcome}
        if error_kind is not None:
            event["failure_kind"] = error_kind
        self.ledger.append(event)
        if stall_event is not None:
            self.ledger.append(stall_event)
        return {"item_id": item_id, "outcome": outcome, "exit_code": exit_code}

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
