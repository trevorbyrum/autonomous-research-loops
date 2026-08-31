"""Portfolio-wide health audit. Non-mutating -- one report, never writes
anything. Backs the `research-loops doctor` subcommand.

Reuses existing machinery rather than reimplementing checks: structural
validity via `semantic-state.py check`, dependency-cycle detection via
`queue.find_dependency_cycle()` (the same function `sync()` uses), source
counts via `semantic-state.py source-count`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from .queue import find_dependency_cycle

_PACKAGE_DIR = Path(__file__).resolve().parent
_SEMANTIC_STATE = _PACKAGE_DIR / "chassis" / "semantic-state.py"


def _run_chassis(action: str, topic_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SEMANTIC_STATE), action, str(topic_dir)],
        capture_output=True,
        text=True,
    )


def _source_count(topic_dir: Path) -> int:
    result = _run_chassis("source-count", topic_dir)
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def run_doctor(
    items: list[dict[str, Any]], *, topics_root: Path | None = None
) -> dict[str, Any]:
    """Audit a queue snapshot's items. `items` is `store.snapshot()["items"]`.

    `topics_root`, if given, also checks for orphaned topic directories --
    real directories under it that no queue item's `cwd` points at. This is
    optional because the queue doesn't require any single topics/ layout;
    pass it when your portfolio does use one (the convention `new-topic`/
    `approve-topic` default to).
    """
    structural_errors: dict[str, list[str]] = {}
    unlocked_items: list[str] = []
    missing_dependencies: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}

    by_id = {item["id"]: item for item in items}
    graph = {item["id"]: list(item.get("depends_on", [])) for item in items}

    for item in items:
        topic_dir = Path(item["cwd"])
        if topic_dir.is_dir() and (topic_dir / "SEMANTIC-STATE.json").is_file():
            result = _run_chassis("check", topic_dir)
            if result.returncode != 0:
                structural_errors[item["id"]] = [
                    line for line in result.stderr.splitlines() if line.strip()
                ]
            source_counts[item["id"]] = _source_count(topic_dir)
        if not item.get("completion_lock"):
            unlocked_items.append(item["id"])
        for dependency in item.get("depends_on", []):
            if dependency not in by_id:
                missing_dependencies.append({"item": item["id"], "missing": dependency})

    cycle_id = find_dependency_cycle(graph)

    orphaned_topic_dirs: list[str] = []
    if topics_root is not None and topics_root.is_dir():
        known_dirs = {Path(item["cwd"]).resolve() for item in items}
        for candidate in sorted(topics_root.iterdir()):
            if candidate.is_dir() and candidate.resolve() not in known_dirs:
                orphaned_topic_dirs.append(str(candidate))

    return {
        "item_count": len(items),
        "structural_errors": structural_errors,
        "unlocked_items": unlocked_items,
        "missing_dependencies": missing_dependencies,
        "dependency_cycle": cycle_id,
        "orphaned_topic_dirs": orphaned_topic_dirs,
        "source_counts": source_counts,
        "total_sources_cited": sum(source_counts.values()),
        "healthy": not (
            structural_errors
            or unlocked_items
            or missing_dependencies
            or cycle_id
            or orphaned_topic_dirs
        ),
    }
