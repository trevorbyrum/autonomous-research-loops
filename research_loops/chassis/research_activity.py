"""Summarize an iteration's research-activity file (gateway STATION-CONTRACT.md §2).

The station's research tool appends one JSON line per distinct (source, coverage)
state it observed — successes included, so the queue can clear a blocker when a
previously failed source answers again. This module reduces that file to the two
fields the iteration result carries; it never raises on a missing or mangled file,
because a broken activity channel must degrade to "no signal", not a failed run.
"""
from __future__ import annotations

import json

# coverage states that mark a source as blocked for required research; policy skips
# (not_searched) and partial retrievability (metadata_only) are reported but do not
# block completion on their own
BLOCKING = ("provider_unavailable", "auth_failed")
DEGRADED = BLOCKING + ("not_searched", "metadata_only")
CLEARING = ("searched_ok", "searched_empty")


def summarize(path: str | None) -> tuple[list[dict], list[str]]:
    """(research_failures, research_ok): distinct degraded (source, coverage) pairs and
    the distinct sources that answered successfully during the iteration."""
    failures: dict[tuple[str, str], dict] = {}
    ok: set[str] = set()
    if not path:
        return [], []
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return [], []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        source, coverage = entry.get("source"), entry.get("coverage")
        if not source or not coverage:
            continue
        if coverage in DEGRADED:
            failures.setdefault((source, coverage), {"source": source, "coverage": coverage})
        elif coverage in CLEARING:
            ok.add(source)
    return sorted(failures.values(), key=lambda f: (f["source"], f["coverage"])), sorted(ok)
