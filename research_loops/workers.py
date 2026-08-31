"""Spawn/stop the N `run --worker` processes a config's `workers` count asks for.

Each worker is still its own independent `research-loops run --worker <name>`
process with its own lock file, exactly as if you'd started them by hand or
via separate systemd units (see deploy/systemd/ and docs/operations.md) --
this module is only a convenience for turning one config number into that
many processes, not a new execution model.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from .queue import QueueError

_STATE_FILENAME = "workers.json"
# The queue root (`root` below) and the directory containing the research_loops
# package are independent -- a systemd unit typically sets WorkingDirectory to
# the package root and passes a separate --root for the queue. Spawned workers
# must run with THIS directory as cwd regardless of where the queue root is,
# or `-m research_loops` fails to resolve.
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _state_path(root: Path) -> Path:
    return root / "state" / _STATE_FILENAME


def start(
    root: Path,
    count: int,
    *,
    worker_prefix: str = "worker-",
    extra_run_args: list[str] | None = None,
) -> dict[str, int]:
    if count < 1:
        raise QueueError("workers count must be at least 1")
    state_path = _state_path(root)
    if state_path.exists():
        existing = json.loads(state_path.read_text(encoding="utf-8"))
        raise QueueError(
            f"workers already recorded as started ({existing}); run "
            "`research-loops workers stop` first"
        )
    pids: dict[str, int] = {}
    try:
        for index in range(1, count + 1):
            worker_name = f"{worker_prefix}{index}"
            args = [
                sys.executable,
                "-m",
                "research_loops",
                "--root",
                str(root),
                "run",
                "--worker",
                worker_name,
                *(extra_run_args or []),
            ]
            process = subprocess.Popen(
                args, start_new_session=True, cwd=str(_PACKAGE_ROOT)
            )
            pids[worker_name] = process.pid
    finally:
        if pids:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(pids, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    return pids


def stop(root: Path) -> dict[str, list[str]]:
    state_path = _state_path(root)
    if not state_path.exists():
        return {"stopped": [], "not_running": []}
    pids: dict[str, int] = json.loads(state_path.read_text(encoding="utf-8"))
    stopped: list[str] = []
    not_running: list[str] = []
    for worker_name, pid in pids.items():
        try:
            os.kill(pid, signal.SIGTERM)
            stopped.append(worker_name)
        except ProcessLookupError:
            not_running.append(worker_name)
    state_path.unlink()
    return {"stopped": stopped, "not_running": not_running}


def status(root: Path) -> dict[str, Any]:
    state_path = _state_path(root)
    if not state_path.exists():
        return {"running": {}}
    pids: dict[str, int] = json.loads(state_path.read_text(encoding="utf-8"))
    alive: dict[str, int] = {}
    for worker_name, pid in pids.items():
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        alive[worker_name] = pid
    return {"running": alive}
