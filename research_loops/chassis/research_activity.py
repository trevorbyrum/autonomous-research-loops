"""Summarize an iteration's research-activity file (gateway STATION-CONTRACT.md §2).

The station's research tool appends one JSON line per coverage-state TRANSITION, in
order, keyed by the exact request (source + request type + query/identity) — so a
success on an unrelated query never clears a different request's failure, and a
fail → ok recovery is visible as the key's LAST state (pass-1 findings 4 and 6).
This module reduces the file to per-key FINAL states; it never raises on a missing or
mangled file, because a broken activity channel must degrade to "no signal", not a
failed run.
"""
from __future__ import annotations

import json

# coverage states that mark a request as blocked for required research; policy skips
# (not_searched) and partial retrievability (metadata_only) are reported but do not
# block completion on their own; exhausted is a healthy channel with nothing more
BLOCKING = ("provider_unavailable", "auth_failed")
DEGRADED = BLOCKING + ("not_searched", "metadata_only")
CLEARING = ("searched_ok", "searched_empty", "exhausted")


def request_key(source: str, request_type: str, subject: str) -> str:
    """The blocker key: unambiguous for any subject text (it is a JSON array)."""
    return json.dumps([source, request_type, subject], separators=(",", ":"))


def summarize(path: str | None) -> dict:
    """{"failures": [...], "ok_keys": [...], "coverage_by_source": {...}} — failures are
    the requests whose FINAL state is degraded (each with its key), ok_keys the keys
    whose final state cleared, coverage_by_source each source's last state of any kind
    (the completion-coverage stamp's raw material)."""
    final: dict[str, dict] = {}
    by_source: dict[str, str] = {}
    empty = {"failures": [], "ok_keys": [], "coverage_by_source": {}}
    if not path:
        return empty
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return empty
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
        request_type = str(entry.get("request_type") or "")
        subject = str(entry.get("query_or_identity") or "")
        key = request_key(source, request_type, subject)
        final[key] = {"key": key, "source": source, "request_type": request_type,
                      "subject": subject, "coverage": coverage}
        by_source[source] = coverage   # file order = observation order: last one speaks
    failures = sorted((f for f in final.values() if f["coverage"] in DEGRADED),
                      key=lambda f: (f["source"], f["request_type"], f["subject"]))
    ok_keys = sorted(k for k, f in final.items() if f["coverage"] in CLEARING)
    return {"failures": failures, "ok_keys": ok_keys, "coverage_by_source": by_source}
