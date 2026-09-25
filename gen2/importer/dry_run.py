"""Dry-run importer skeleton: gen-1 JSON/JSONL state -> a mapping report
against the gen-2 ID and authority scheme. It reads and never writes.

Trace: task 0b (read gen-1 state read-only; report how it maps to the gen-2
ID/authority scheme without writing a gen-2 store; surface, never silently
resolve, every record that does not map cleanly); design review §10 (Phase 4:
freeze, import, reconcile; this is reconnaissance for it); INVARIANTS §12
(what migration preserves; unavailable history is unknown, never zero; host
PIDs are never adopted), RG-8, E-8, RG-U, §11 (gen-1 defects are not
compatibility targets), G-13 (the importer needs its own audited path), C-13
(identity bounds apply to every writer, the importer's generated identities
included).

Read-only, structurally: this module may import only gen2.core
(gen2/boundaries.toml), so it cannot reach the store or sqlite3. It opens
gen-1 files with mode "rb" only, and it never reads a path that resolves
outside the gen-1 root. The CLI refuses to put its report inside that root.
It does not read gen-1's managed store (state/control.sqlite3). When that
store exists, state/queue.json is a frozen pre-migration snapshot, so the
report raises a blocking issue instead of mapping stale queue state as
authority.

Every record gets an explicit status (maps / partial / unmapped). Anything
short of "maps" carries at least one issue naming what is missing and who
must supply it. Nothing is defaulted: no invented zeros, fleets, owners,
deadlines, templates, ratings, confirmations or approvals.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from gen2.core import canonical

REPORT_VERSION = "gen1-import-dry-run/1"
TOPIC_SLUG = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,95}\Z")  # common.schema.json#/$defs/topic_id, after "<fleet>:"
FLEET_ID = re.compile(r"\A[a-z][a-z0-9-]{0,31}\Z")
LOCAL_ID = re.compile(r"\A[A-Za-z][A-Za-z0-9._-]{0,63}\Z")  # common.schema.json#/$defs/local_id
LEDGER_ENTRY = re.compile(r"^## \[(SRC-\d+)\] (external|internal|local)$")
GEN2_COVERAGE = {"searched_ok", "searched_empty", "provider_unavailable", "auth_failed", "metadata_only"}

# gen-1 queue status -> (gen-2 candidate status or None, issue code, what gen-2 needs that gen-1 lacks)
STATUS_MAP = {
    "queued": ("queued", "contract-approval-unrecorded",
               "gen-2 queued needs an approved Contract v2 revision; gen-1 records no approval decision (approve-topic persists none)"),
    "backoff": ("resting", "backoff-is-two-states",
                "gen-1 backoff is both a failure retry and the normal pause between iterations (last_error_kind tells them apart); neither is a gen-2 retry budget"),
    "paused": ("held", "untyped-hold", "a gen-2 hold is typed (class, recoverability, authority), owned, deadlined and says what clears it; gen-1 has a reason string"),
    "needs_attention": ("held", "untyped-hold", "a gen-2 hold is typed (class, recoverability, authority), owned, deadlined and says what clears it; gen-1 has last_error only"),
    "running": (None, "live-execution", "work was running when the snapshot was taken: freeze gen-1 first (Phase 4); host PIDs are never adopted (L-3)"),
    "completed": (None, "completion-unapproved",
                  "gen-2 completion needs an operator completion_approval of a dossier revision under an approved contract (G-8); gen-1 has neither"),
}


class Gen1ParseError(ValueError):
    pass


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise Gen1ParseError(f"duplicate key {key!r}")
        out[key] = value
    return out


def _no_constant(name: str) -> object:
    raise Gen1ParseError(f"non-finite number {name}")


def parse_gen1_json(data: bytes) -> object:
    """gen-1 JSON as gen-1 wrote it. Duplicate keys and NaN/Infinity are
    refused, as in canonical.parse_json_strict. Integers of any size are
    kept, so that a single out-of-range identity is surfaced on its own
    record (see _bounded) instead of making the whole file unreadable. This
    parser is for reading only; what the report carries is canonicalized."""
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Gen1ParseError(str(exc)) from exc


def _issue(code: str, detail: str, needs: str) -> dict:
    return {"code": code, "detail": detail, "needs": needs}


def _record(kind: str, ref: str, target: str | None, mapping: dict, issues: list[dict], *, unmapped: bool = False) -> dict:
    for key, value in list(mapping.items()):
        try:
            canonical.canonical_bytes(value)
        except canonical.CanonicalizationError as exc:
            mapping[key] = None
            issues.append(_issue("value-unrepresentable", f"{key}: {exc}", "operator: resolve before import"))
    status = "unmapped" if unmapped or target is None else ("partial" if issues else "maps")
    return {"gen1": kind, "ref": ref, "gen2_target": target, "status": status, "mapping": mapping, "issues": issues}


class Gen1Reader:
    """Read-only access to one gen-1 root; every path must stay inside it."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.sources: dict[str, str] = {}

    def inside(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root)
            return True
        except ValueError:
            return False

    def read(self, path: Path) -> bytes | None:
        rel = str(path.relative_to(self.root)) if self.inside(path) else str(path)
        if not self.inside(path):
            self.sources[rel] = "refused: resolves outside the gen-1 root"
            return None
        if not path.is_file():
            self.sources.setdefault(rel, "absent")
            return None
        with open(path, "rb") as handle:
            data = handle.read()
        self.sources[rel] = f"read ({len(data)} bytes)"
        return data

    def json(self, path: Path) -> tuple[object | None, str | None]:
        data = self.read(path)
        if data is None:
            return None, None
        try:
            return parse_gen1_json(data), None
        except Gen1ParseError as exc:
            return None, str(exc)

    def jsonl(self, path: Path) -> tuple[list[dict], int] | None:
        """(parsed lines, malformed line count): malformed lines are counted
        and reported, never dropped silently (gen-1 defect §11.9)."""
        data = self.read(path)
        if data is None:
            return None
        good, bad = [], 0
        for line in data.splitlines():
            if not line.strip():
                continue
            try:
                value = parse_gen1_json(line)
            except Gen1ParseError:
                bad += 1
                continue
            if isinstance(value, dict):
                good.append(value)
            else:
                bad += 1
        return good, bad


def _sections(markdown: str) -> dict[str, str]:
    out, current, lines = {}, None, []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if current is not None:
                out[current] = "\n".join(lines).strip()
            current, lines = line[3:].strip(), []
        elif current is not None:
            lines.append(line)
    if current is not None:
        out[current] = "\n".join(lines).strip()
    return out


def gen2_topic_id(gen1_id: str, fleet: str | None) -> tuple[str | None, list[dict]]:
    issues = []
    if fleet is None:
        issues.append(_issue("fleet-unassigned", "gen-2 topic ids are fleet-prefixed ('<fleet>:<slug>'); gen-1 has no fleet", "operator: name the fleet (--fleet)"))
    elif not FLEET_ID.match(fleet):
        issues.append(_issue("fleet-invalid", f"{fleet!r} is not a gen-2 fleet id", "operator: a valid fleet id"))
    if not TOPIC_SLUG.match(gen1_id):
        issues.append(_issue("topic-id-not-a-gen2-slug", f"{gen1_id!r} is not a gen-2 topic slug (lower-case, at most 96 characters)",
                             "operator: an explicit rename (lower-casing could merge distinct topics)"))
    if issues:
        return None, issues
    return f"{fleet}:{gen1_id}", []


def _bounded(value: object, what: str, issues: list[dict]) -> int | None:
    """Apply the RA8 identity bound to a value the import would write as an
    identity; an out-of-range value is surfaced, never truncated."""
    try:
        return canonical.identity_integer(value)
    except canonical.CanonicalizationError as exc:
        issues.append(_issue("identity-out-of-range", f"{what}: {exc}", "operator: resolve before import (identities past 2**53-1 travel as strings)"))
        return None


def map_queue_item(item: dict, index: int, fleet: str | None) -> list[dict]:
    gen1_id = str(item.get("id"))
    topic, issues = gen2_topic_id(gen1_id, fleet)
    records = [_record("queue item", gen1_id, "queue_entries" if topic else None, {"topic_id": topic, "priority": _bounded(index + 1, "priority (queue position)", issues)},
                       issues, unmapped=topic is None)]
    status = item.get("status")
    target, code, detail = STATUS_MAP.get(status, (None, "unknown-status", f"gen-1 status {status!r} has no gen-2 counterpart"))
    status_issues = [_issue(code, detail, "operator decision, or the Phase 4 audited import path (ordinary writes create topics at intake only)")]
    if item.get("lane") == "intake" or str(item.get("managed_kind")) == "intake_discovery":
        target, status_issues = None, [_issue("intake-discovery-item", "a gen-1 intake discovery item is live pre-contract work, not a topic state", "freeze gen-1 first (Phase 4)")]
    records.append(_record("queue status", f"{gen1_id}.status={status}", "queue_entries.status" if target else None, {"status": target}, status_issues))
    lock = item.get("completion_lock")
    records.append(_record("completion lock", f"{gen1_id}.completion_lock", None, {"legacy_lock": lock},
                           [_issue("legacy-lock-is-not-a-gen2-hash" if lock else "no-lock",
                                   "gen-1's lock is SHA-256 of its own projection of obligation identity, not a JCS content hash (jcs-rfc8785/1)"
                                   if lock else "no completion lock was recorded (add was run without --lock-sha256)",
                                   "keep as legacy provenance; the gen-2 contract hash is computed on import")], unmapped=True))
    if "iterations_completed" in item:
        count_issues: list[dict] = []
        count = _bounded(item["iterations_completed"], "iterations_completed", count_issues)
        count_issues.append(_issue("ordinals-without-history", "gen-2 research ordinals are one per research_pass invocation with its final receipt; gen-1 kept a count, not that history",
                                   "Phase 4: import the count as provenance, not as ordinal rows (§12: unavailable history is unknown)"))
        records.append(_record("accepted iterations", f"{gen1_id}.iterations_completed", "research_ordinals", {"accepted_count": count}, count_issues))
    else:
        records.append(_record("accepted iterations", f"{gen1_id}.iterations_completed", None, {"accepted_count": None},
                               [_issue("count-unknown", "no iteration count recorded: unknown, not zero (RG-U, E-8)", "nothing to invent")], unmapped=True))
    return records


def map_brief(reader: Gen1Reader, topic_dir: Path, gen1_id: str) -> dict:
    raw = reader.read(topic_dir / "AUTHORITY.md")
    draft = (topic_dir / "DRAFT-AUTHORITY.md").is_file() if reader.inside(topic_dir / "DRAFT-AUTHORITY.md") else False
    if raw is None:
        return _record("intake brief", f"{gen1_id}/AUTHORITY.md", None, {}, [_issue("no-brief", "no AUTHORITY.md" + (" (a DRAFT-AUTHORITY.md exists: still in gen-1 intake)" if draft else ""),
                                                                                   "operator: a brief to confirm")], unmapped=True)
    sections = _sections(raw.decode("utf-8", errors="replace"))
    verbatim = sections.get("Operator brief (verbatim)")
    assumptions = [line[2:].strip() for line in sections.get("Assumptions", "").splitlines() if line.startswith("- ")]
    qa = reader.read(topic_dir / "QA-RECORD.md")
    confirmation_evidence = bool(qa) and bool(_sections(qa.decode("utf-8", errors="replace")).get("Operator confirmation"))
    issues = [_issue("brief-slot-missing", f"gen-1 has no {slot!r} slot", "operator, at re-confirmation") for slot in ("feeds", "evidence_that_would_change_it", "constraints", "operator_hypotheses")]
    if verbatim is None:
        issues.append(_issue("brief-slot-missing", "AUTHORITY.md has no 'Operator brief (verbatim)' section", "operator"))
    issues.append(_issue("owner-unknown", "gen-1 records no brief owner", "operator: an owner"))
    issues.append(_issue("deadline-unknown", "gen-1 records no review deadline", "operator: a deadline"))
    issues.append(_issue("confirmation-unrecorded",
                         "QA-RECORD.md has a non-empty 'Operator confirmation' section, but no actor, time or decision record" if confirmation_evidence
                         else "no durable confirmation evidence in gen-1",
                         "operator: a brief_confirmation decision on the imported version (it imports awaiting_confirmation)"))
    mapping = {"brief_id": "brief-1", "version": 1, "parent_version": None, "status": "awaiting_confirmation",
               "objective_in_operator_words": verbatim, "surfaced_assumptions": assumptions, "legacy_confirmation_evidence": confirmation_evidence}
    return _record("intake brief", f"{gen1_id}/AUTHORITY.md", "intake_briefs", mapping, issues)


def map_semantic_state(reader: Gen1Reader, topic_dir: Path, gen1_id: str) -> list[dict]:
    state, error = reader.json(topic_dir / "SEMANTIC-STATE.json")
    ref = f"{gen1_id}/SEMANTIC-STATE.json"
    if state is None:
        return [_record("semantic state", ref, None, {}, [_issue("unparseable" if error else "absent", error or "no SEMANTIC-STATE.json", "operator")], unmapped=True)]
    if not isinstance(state, dict):
        return [_record("semantic state", ref, None, {}, [_issue("unparseable", "not a JSON object", "operator")], unmapped=True)]
    records = []
    for obl in state.get("obligations") or []:
        oid = str(obl.get("id")) if isinstance(obl, dict) else "?"
        issues = [_issue("obligation-contract-fields-missing", "Contract v2 obligations need a template, facet tags, a stopping profile and an operator importance rating; gen-1 has text only",
                         "S3 contract construction on import (operator approves)")]
        if not LOCAL_ID.match(oid):
            issues.append(_issue("obligation-id-not-a-local-id", f"{oid!r} is not a gen-2 local id", "operator: a rename"))
        disposition = obl.get("disposition") if isinstance(obl, dict) else None
        if disposition not in (None, "open"):
            issues.append(_issue("disposition-is-not-verification", f"gen-1 disposition {disposition!r} is an agent-written state; gen-2 accepted support needs a verification receipt (V-4)",
                                 "import claims provisional at most; re-verify"))
        records.append(_record("obligation", f"{gen1_id}#{oid}", "obligations", {"obligation_id": oid, "text": obl.get("text") if isinstance(obl, dict) else None}, issues))
    for key, why in (("deliverables", "Contract v2 has no deliverables list"), ("contradictions", "the contradiction ledger is built before Phase 2 stopping"),
                     ("pending_evidence_refs", "no gen-2 pending-evidence record")):
        if state.get(key):
            records.append(_record(key, f"{gen1_id}#{key}", None, {"count": len(state[key])}, [_issue("no-gen2-target", why, "Phase 2/4 decision")], unmapped=True))
    return records


def map_source_ledger(reader: Gen1Reader, topic_dir: Path, gen1_id: str) -> list[dict]:
    raw = reader.read(topic_dir / "SOURCE-LEDGER.md")
    if raw is None:
        return []
    records, current = [], None
    for line in raw.decode("utf-8", errors="replace").splitlines() + ["## [END] local"]:
        match = LEDGER_ENTRY.match(line)
        if match or line == "## [END] local":
            if current is not None:
                sid, kind, fields = current
                url = fields.get("url")
                if kind == "external" and url:
                    scheme = "doi" if re.match(r"https?://(dx\.)?doi\.org/", url) else "url"
                    value = re.sub(r"https?://(dx\.)?doi\.org/", "", url) if scheme == "doi" else url
                    records.append(_record("source", f"{gen1_id}#{sid}", "works", {"identity_scheme": scheme, "identity_value": value},
                                           [_issue("work-identity-unverified", "a gen-1 ledger URL is an agent-written citation, not a gateway-captured record", "Phase 4: re-resolve through the gateway")]))
                else:
                    records.append(_record("source", f"{gen1_id}#{sid}", None, {"kind": kind},
                                           [_issue("no-work-identity", f"a {kind} ledger entry has no external identity for works", "Phase 4 decision")], unmapped=True))
            current = (match.group(1), match.group(2), {}) if match else None
        elif current is not None and line.startswith("- ") and ":" in line:
            key, _, value = line[2:].partition(":")
            current[2][key.strip()] = value.strip()
    return records


def map_jsonl_history(reader: Gen1Reader, path: Path, ref: str, what: str) -> dict | None:
    result = reader.jsonl(path)
    if result is None:
        return None
    lines, bad = result
    issues = [_issue("no-gen2-target", f"{what}: no gen-2 table yet", "Phase 4 (§12: available usage history is preserved)")]
    if bad:
        issues.append(_issue("malformed-lines", f"{bad} line(s) are not JSON objects: reported, not dropped (gen-1 defect §11.9)", "operator review"))
    return _record("history", ref, None, {"lines": len(lines), "malformed_lines": bad}, issues, unmapped=True)


def dry_run(root: str | Path, fleet: str | None = None) -> dict:
    """The mapping report for the gen-1 root. Reads only."""
    reader = Gen1Reader(Path(root))
    blocking: list[dict] = []
    if not reader.root.is_dir():
        blocking.append(_issue("no-gen1-root", f"{reader.root} is not a directory", "operator: the gen-1 root"))
        return _report(reader, fleet, blocking, [], [])
    managed = reader.inside(reader.root / "state" / "control.sqlite3") and (reader.root / "state" / "control.sqlite3").exists()
    if managed:
        reader.sources["state/control.sqlite3"] = "present, not read"
        blocking.append(_issue("managed-store-not-read",
                               "state/control.sqlite3 exists: gen-1's authoritative queue and work state live there, and state/queue.json is a frozen pre-migration snapshot",
                               "a read path for the managed store (a boundary amendment: this module has no sqlite3 grant), or an export from it"))
    queue, error = reader.json(reader.root / "state" / "queue.json")
    topics, other = [], []
    if error:
        blocking.append(_issue("queue-unparseable", error, "operator"))
    elif queue is None and not managed:
        blocking.append(_issue("queue-absent", "no state/queue.json: no gen-1 queue to map (is this a gen-1 root?)", "operator: the gen-1 root"))
    items = queue.get("items") if isinstance(queue, dict) else None
    if queue is not None and not isinstance(items, list):
        blocking.append(_issue("queue-shape", "state/queue.json has no items list", "operator"))
        items = None
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            other.append(_record("queue item", f"items[{index}]", None, {}, [_issue("queue-shape", "not an object", "operator")], unmapped=True))
            continue
        gen1_id = str(item.get("id"))
        records = map_queue_item(item, index, fleet)
        if managed:
            for record in records:
                record["issues"].append(_issue("stale-snapshot", "from state/queue.json, which a managed deployment no longer updates", "the managed store's state"))
                record["status"] = "unmapped" if record["status"] == "unmapped" else "partial"
        topic_dir = _topic_dir(reader, item, gen1_id)
        cwd = item.get("cwd")
        if topic_dir is not None and isinstance(cwd, str) and Path(cwd).resolve() != topic_dir.resolve():
            records.append(_record("topic directory", gen1_id, None, {"cwd": cwd, "read_from": str(topic_dir.relative_to(reader.root))},
                                   [_issue("cwd-not-used", "the item's cwd is not inside the gen-1 root; its files were read from topics/<id>, which gen-1 may not keep in step",
                                           "operator: confirm which directory is the topic's")], unmapped=True))
        if topic_dir is None:
            records.append(_record("topic directory", gen1_id, None, {"cwd": item.get("cwd")},
                                   [_issue("topic-dir-not-found", "neither the item's cwd nor topics/<id> is a directory inside the gen-1 root", "operator: the topic's files")], unmapped=True))
        else:
            records.append(map_brief(reader, topic_dir, gen1_id))
            records += map_semantic_state(reader, topic_dir, gen1_id)
            records += map_source_ledger(reader, topic_dir, gen1_id)
            for path in sorted((topic_dir / "logs").glob("*.jsonl")) if reader.inside(topic_dir / "logs") else []:
                record = map_jsonl_history(reader, path, f"{gen1_id}/logs/{path.name}", "topic log history")
                if record:
                    records.append(record)
        topics.append({"gen1_id": gen1_id, "gen2_topic_id": records[0]["mapping"]["topic_id"], "records": records})
    events = map_jsonl_history(reader, reader.root / "state" / "events.jsonl", "state/events.jsonl", "usage ledger")
    if events:
        other.append(events)
    stations, s_error = reader.json(reader.root / "state" / "stations.json")
    if stations is not None or s_error:
        other.append(_record("station configuration", "state/stations.json", None, {},
                             [_issue("no-gen2-target", s_error or "station profiles map to the Phase 1 config bundle registry", "Phase 1")], unmapped=True))
    return _report(reader, fleet, blocking, topics, other)


def _topic_dir(reader: Gen1Reader, item: dict, gen1_id: str) -> Path | None:
    """The item's cwd if it is inside the root, else topics/<id> (gen-1's
    checkpoint publication hardcodes that layout); never a path outside."""
    for candidate in ((Path(item["cwd"]) if isinstance(item.get("cwd"), str) else None), reader.root / "topics" / gen1_id):
        if candidate is not None and reader.inside(candidate) and candidate.is_dir():
            return candidate
    return None


def _report(reader: Gen1Reader, fleet: str | None, blocking: list[dict], topics: list[dict], other: list[dict]) -> dict:
    records = [r for t in topics for r in t["records"]] + other
    summary = {status: sum(1 for r in records if r["status"] == status) for status in ("maps", "partial", "unmapped")}
    summary["records"] = len(records)
    summary["issues"] = sum(len(r["issues"]) for r in records) + len(blocking)
    summary["blocking"] = len(blocking)
    return {"report_version": REPORT_VERSION, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "gen1_root": str(reader.root), "fleet_id": fleet, "writes": "none: dry run (no gen-2 store, no gen-1 file)",
            "sources": dict(sorted(reader.sources.items())), "blocking": blocking, "topics": topics, "other": other, "summary": summary}


def render(report: dict) -> str:
    """The report as canonical JSON text (deterministic for a given input)."""
    return json.dumps(canonical.parse_json_strict(canonical.canonical_bytes(report)), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """python -m gen2.importer --gen1-root PATH [--fleet ID] [--report PATH].
    Exit 0: report produced, no blocking issue; 1: report produced with
    blocking issues; 2: refused (the report would land inside the gen-1 root,
    or over an existing file)."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="gen-2 dry-run importer: map gen-1 JSON/JSONL state, write nothing")
    parser.add_argument("--gen1-root", required=True, type=Path)
    parser.add_argument("--fleet", help="the gen-2 fleet these topics belong to (gen-1 has none; nothing is assumed)")
    parser.add_argument("--report", type=Path, help="write the report to this new file (never inside the gen-1 root); default: stdout")
    args = parser.parse_args(argv)
    root = args.gen1_root.resolve()
    target = args.report.resolve() if args.report is not None else None
    if target is not None and (target == root or root in target.parents):
        print(f"refused: {target} is inside the gen-1 root; the importer never writes gen-1", file=sys.stderr)
        return 2
    if target is not None and target.exists():
        print(f"refused: {target} exists; the report goes to a new file", file=sys.stderr)
        return 2
    report = dry_run(root, args.fleet)
    text = render(report)
    if target is None:
        sys.stdout.write(text)
    else:
        with open(target, "x", encoding="utf-8") as handle:
            handle.write(text)
    s = report["summary"]
    print(f"gen2 import dry run: {s['records']} records ({s['maps']} map, {s['partial']} partial, {s['unmapped']} unmapped), "
          f"{s['issues']} issues, {s['blocking']} blocking; nothing written to gen-1 or a gen-2 store", file=sys.stderr)
    return 1 if report["blocking"] else 0
