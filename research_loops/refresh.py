"""Orchestrates `chassis/refresh-policy.py` + `QueueStore.reopen_for_refresh()`.

The one place both the manual `research-loops refresh` CLI command and the
runner's automatic due-refresh scan call, so the two paths can never drift
apart (e.g. one checking completion status and the other forgetting to).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from .queue import QueueError, QueueStore

_PACKAGE_DIR = Path(__file__).resolve().parent
_REFRESH_POLICY = _PACKAGE_DIR / "chassis" / "refresh-policy.py"


def apply_refresh(store: QueueStore, item_id: str, mode: str | None = None) -> dict[str, Any]:
    """Reopen a completed item for a refresh: run `refresh-policy.py apply`
    against its topic directory, then requeue it via `reopen_for_refresh()`.

    Raises QueueError -- with the underlying chassis failure message, if
    that's what happened -- and leaves the item untouched (still completed)
    on any failure; nothing here is applied partially.
    """
    item = store.get(item_id)
    if item["status"] != "completed":
        raise QueueError(
            f"item {item_id} is not completed (status={item['status']!r}); "
            "only a completed item can be refreshed"
        )
    resolved_mode = mode or item.get("topic_refresh_mode") or "continue"
    result = subprocess.run(
        [sys.executable, str(_REFRESH_POLICY), "apply", item["cwd"], resolved_mode],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise QueueError(f"refresh-policy.py apply failed: {result.stderr.strip()}")
    return store.reopen_for_refresh(item_id)
