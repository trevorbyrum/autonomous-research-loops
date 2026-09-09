"""Station configuration — the collective config for the worker fleet.

Separation rule (operator, 2026-09-09): the QUEUE is just the queue — order,
contracts, and what a topic itself needs. EVERY mechanic lives here, on the
stations:

- per-station profiles: which harness/model pair runs an iteration
  (`agent_main`/`agent_secondary`/`agent_model`/`agent_flags`) and the
  station's cadence (`interval_seconds`, the pause between iterations;
  0 = continuous). Cadence cascades: station N+1 is never faster than
  station N, so station number is the priority tier.
- fleet policy: settings every station applies to whatever topic it holds,
  today the obligations-checkpoint schedule (`checkpoint_every` ordinary
  iterations, `checkpoint_on_deepening` for first entry into deepening).
  The station monitors the topic's counters and assigns the checkpoint;
  the topic never schedules its own.

Stored at `state/stations.json` under its own lock. Existing deployments
whose profiles still live inside `state/queue.json` (`worker_agents`) are
migrated here on first access; the queue drops its copy on its next write.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

MAX_STATIONS = 5  # operator ruling 2026-09-04: "up to 5 stations, for now"
DEFAULT_CHECKPOINT_EVERY = 25  # operator ruling 2026-09-08: 25th/50th/75th...
_STATION_NAME = re.compile(r"^(?P<prefix>.*)-(?P<number>\d+)$")
_VALID_NAME = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

_FLEET_DEFAULTS: dict[str, Any] = {
    "checkpoint_every": DEFAULT_CHECKPOINT_EVERY,
    "checkpoint_on_deepening": True,
}


class StationsError(RuntimeError):
    pass


def station_number(worker: str) -> int | None:
    m = _STATION_NAME.match(worker)
    return int(m.group("number")) if m else None


def station_prefix(worker: str) -> str | None:
    m = _STATION_NAME.match(worker)
    return m.group("prefix") if m else None


class StationsStore:
    """Durable fleet configuration, separate from the queue's state file."""

    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "stations.json"
        self.lock_path = self.state_dir / "stations.lock"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ persistence
    @contextmanager
    def _locked(self) -> Iterator[dict[str, Any]]:
        import fcntl

        with open(self.lock_path, "a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state = self._load()
            before = copy.deepcopy(state)
            yield state
            if state == before and self.path.exists():
                return
            state["revision"] = int(state.get("revision", 0)) + 1
            state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            fd, tmp = tempfile.mkstemp(dir=self.state_dir, prefix=".stations-")
            with os.fdopen(fd, "w") as fh:
                json.dump(state, fh, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp, self.path)

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            with open(self.path) as fh:
                state = json.load(fh)
            if not isinstance(state.get("stations"), dict):
                state["stations"] = {}
            if not isinstance(state.get("fleet"), dict):
                state["fleet"] = {}
            return state
        return {"revision": 0, "fleet": {}, "stations": self._migrate_from_queue()}

    def _migrate_from_queue(self) -> dict[str, Any]:
        """One-time lift of legacy `worker_agents` out of state/queue.json.
        Read-only here: the queue store strips its own copy on its next write."""
        queue_path = self.state_dir / "queue.json"
        try:
            with open(queue_path) as fh:
                legacy = json.load(fh).get("worker_agents")
        except (OSError, ValueError):
            return {}
        if not isinstance(legacy, dict):
            return {}
        return {k: dict(v) for k, v in legacy.items() if isinstance(v, dict)}

    def snapshot(self) -> dict[str, Any]:
        with self._locked() as state:  # locked so a fresh migration persists
            return copy.deepcopy(state)

    # ------------------------------------------------------------ reads
    def station(self, worker: str) -> dict[str, Any]:
        profile = self.snapshot()["stations"].get(worker)
        return dict(profile) if isinstance(profile, dict) else {}

    def interval(self, worker: str) -> int:
        value = self.station(worker).get("interval_seconds")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return 0

    def fleet(self) -> dict[str, Any]:
        """Fleet-wide policy with defaults applied for unset keys."""
        stored = self.snapshot().get("fleet") or {}
        merged = dict(_FLEET_DEFAULTS)
        for key in _FLEET_DEFAULTS:
            if key in stored:
                merged[key] = stored[key]
        return merged

    # ------------------------------------------------------------ writes
    def configure_fleet(
        self,
        *,
        checkpoint_every: int | None = None,
        checkpoint_on_deepening: bool | None = None,
    ) -> dict[str, Any]:
        """Set fleet-wide mechanics. checkpoint_every=0 disables the cadence
        trigger (deepening entry still fires unless also disabled)."""
        if checkpoint_every is not None and (
            not isinstance(checkpoint_every, int)
            or isinstance(checkpoint_every, bool)
            or checkpoint_every < 0
        ):
            raise StationsError("checkpoint_every must be a non-negative integer")
        if checkpoint_every is None and checkpoint_on_deepening is None:
            raise StationsError("fleet: pass at least one setting")
        with self._locked() as state:
            fleet = state.setdefault("fleet", {})
            if checkpoint_every is not None:
                fleet["checkpoint_every"] = checkpoint_every
            if checkpoint_on_deepening is not None:
                fleet["checkpoint_on_deepening"] = bool(checkpoint_on_deepening)
            merged = dict(_FLEET_DEFAULTS)
            merged.update(fleet)
            return merged

    def configure(
        self,
        worker: str,
        *,
        agent_main: str | None = None,
        agent_secondary: str | None = None,
        agent_model: str | None = None,
        agent_flags: str | None = None,
        interval_seconds: int | None = None,
        clear: bool = False,
    ) -> dict[str, Any]:
        """Set (merge) a station's profile. Pass "" for a string field to
        unset it; clear=True drops the whole profile. Takes effect at the
        station's next iteration launch — never disrupts one already in
        flight. Enforces the cascade: intervals non-decreasing by number."""
        if not _VALID_NAME.match(worker or ""):
            raise StationsError(f"invalid station name: {worker!r}")
        updates = {
            "agent_main": agent_main,
            "agent_secondary": agent_secondary,
            "agent_model": agent_model,
            "agent_flags": agent_flags,
        }
        if interval_seconds is not None and (
            not isinstance(interval_seconds, int)
            or isinstance(interval_seconds, bool)
            or interval_seconds < 0
        ):
            raise StationsError("interval_seconds must be a non-negative integer")
        if not clear and all(v is None for v in updates.values()) and interval_seconds is None:
            raise StationsError("stations: pass at least one field, or --clear")
        number = station_number(worker)
        if number is not None and number > MAX_STATIONS:
            raise StationsError(
                f"at most {MAX_STATIONS} stations are supported for now "
                f"({worker} is numbered {number})"
            )
        with self._locked() as state:
            stations = state["stations"]
            if clear:
                stations.pop(worker, None)
                return {"worker": worker, "profile": {}}
            profile = dict(stations.get(worker) or {})
            for field, value in updates.items():
                if value is None:
                    continue
                if not isinstance(value, str):
                    raise StationsError(f"{field} must be a string")
                if value.strip():
                    profile[field] = value.strip()
                else:
                    profile.pop(field, None)
            if interval_seconds is not None:
                # Invariant: station N+1 can never be faster than station N
                # (intervals non-decreasing by station number), so station
                # number is the priority tier and cascade order is total.
                if number is not None:
                    for other, other_profile in stations.items():
                        if other == worker or not isinstance(other_profile, dict):
                            continue
                        other_number = station_number(other)
                        if other_number is None or station_prefix(other) != station_prefix(worker):
                            continue
                        other_interval = other_profile.get("interval_seconds", 0) or 0
                        if other_number < number and interval_seconds < other_interval:
                            raise StationsError(
                                f"{worker} cannot be faster than {other} "
                                f"({interval_seconds}s < {other_interval}s): station "
                                "intervals must be non-decreasing by station number"
                            )
                        if other_number > number and interval_seconds > other_interval:
                            raise StationsError(
                                f"{worker} cannot be slower than {other} "
                                f"({interval_seconds}s > {other_interval}s): station "
                                "intervals must be non-decreasing by station number"
                            )
                profile["interval_seconds"] = interval_seconds
            if profile:
                stations[worker] = profile
            else:
                stations.pop(worker, None)
            return {"worker": worker, "profile": dict(profile)}
