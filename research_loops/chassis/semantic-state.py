#!/usr/bin/env python3
"""Validate and fingerprint topic-owned semantic completion state."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


STATE_FILE = "SEMANTIC-STATE.json"
TERMINAL_DISPOSITIONS = {"supported", "contradicted", "unresolved", "deferred"}


def obligation(identifier: str, text: str, source_ref: str) -> dict[str, object]:
    """Build a fresh, open obligation record. Used by `new-topic`/`approve-topic`
    when promoting a draft; never called by a running research agent."""
    return {
        "id": identifier,
        "text": text,
        "source_ref": source_ref,
        "disposition": "open",
        "confidence": None,
        "evidence_refs": [],
        "counterevidence_reviewed": False,
        "acceptance_summary": None,
        "counterevidence_summary": None,
        "gap_state": f"unaddressed: {identifier}",
        "adequate_search": None,
        "experiment": None,
    }


def deliverable(
    identifier: str, path: str, headings: list[str], description: str
) -> dict[str, object]:
    return {
        "id": identifier,
        "description": description,
        "path": path,
        "required_headings": list(headings),
        "status": "missing",
        "acceptance_summary": None,
        "acceptance_evidence_refs": [],
    }


def compute_contract_hashes(topic_dir: Path) -> tuple[str, str]:
    contract_hash = hashlib.sha256((topic_dir / "TOPIC.md").read_bytes()).hexdigest()
    authority_hash = hashlib.sha256((topic_dir / "AUTHORITY.md").read_bytes()).hexdigest()
    return contract_hash, authority_hash


def rehash(topic_dir: Path) -> dict[str, Any]:
    """Recompute contract/authority hashes after an operator edits TOPIC.md or
    AUTHORITY.md. This is the operator's explicit "yes, I changed the scope"
    action -- a research agent must never call this itself; CONTRACT-CORE.md
    forbids it from rewriting operator-owned scope in the first place."""
    state = _load(topic_dir)
    contract_hash, authority_hash = compute_contract_hashes(topic_dir)
    state["contract_sha256"] = contract_hash
    state["authority_sha256"] = authority_hash
    path = topic_dir / STATE_FILE
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state


def structural_errors(topic_dir: Path, state: dict[str, Any]) -> list[str]:
    """Pre-queue sanity check: well-formed enough to run, not yet complete.

    Same shape checks as completion_errors() minus the "is every obligation
    already terminal" requirement -- this is what `check` runs on a freshly
    approved topic, before it has done any research at all.
    """
    errors: list[str] = []
    contract_hash, authority_hash = compute_contract_hashes(topic_dir)
    if state.get("contract_sha256") != contract_hash:
        errors.append(
            "contract hash mismatch -- run `semantic-state.py rehash` after "
            "editing TOPIC.md, or the queue will refuse this topic's completion later"
        )
    if state.get("authority_sha256") != authority_hash:
        errors.append(
            "authority hash mismatch -- run `semantic-state.py rehash` after "
            "editing AUTHORITY.md"
        )
    obligations = state.get("obligations")
    if not isinstance(obligations, list) or not obligations:
        errors.append("at least one obligation is required")
    else:
        ids = [str(o.get("id")) for o in obligations if isinstance(o, dict)]
        if len(ids) != len(set(ids)):
            errors.append("obligation IDs must be unique")
        for o in obligations:
            if not isinstance(o, dict):
                errors.append("every obligation must be an object")
                continue
            for field in ("id", "text", "source_ref"):
                if not isinstance(o.get(field), str) or not o[field].strip():
                    errors.append(f"obligation {o.get('id', '?')} missing {field}")
    deliverables = state.get("deliverables")
    if not isinstance(deliverables, list) or not deliverables:
        errors.append("at least one deliverable is required")
    else:
        ids = [str(d.get("id")) for d in deliverables if isinstance(d, dict)]
        if len(ids) != len(set(ids)):
            errors.append("deliverable IDs must be unique")
        for d in deliverables:
            if not isinstance(d, dict):
                errors.append("every deliverable must be an object")
                continue
            for field in ("id", "description", "path"):
                if not isinstance(d.get(field), str) or not d[field].strip():
                    errors.append(f"deliverable {d.get('id', '?')} missing {field}")
    return errors


def _load(topic_dir: Path) -> dict[str, Any]:
    path = topic_dir / STATE_FILE
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def inventory_projection(state: dict[str, Any]) -> dict[str, Any]:
    obligations = [
        {
            "id": value.get("id"),
            "text": value.get("text"),
            "source_ref": value.get("source_ref"),
        }
        for value in state.get("obligations", [])
        if isinstance(value, dict)
    ]
    deliverables = [
        {
            "id": value.get("id"),
            "description": value.get("description"),
            "path": value.get("path"),
            "required_headings": value.get("required_headings"),
        }
        for value in state.get("deliverables", [])
        if isinstance(value, dict)
    ]
    return {
        "schema_version": state.get("schema_version"),
        "topic_id": state.get("topic_id"),
        "contract_sha256": state.get("contract_sha256"),
        "authority_sha256": state.get("authority_sha256"),
        "obligations": sorted(obligations, key=lambda value: str(value["id"])),
        "deliverables": sorted(deliverables, key=lambda value: str(value["id"])),
    }


def inventory_lock(state: dict[str, Any]) -> str:
    payload = json.dumps(
        inventory_projection(state), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reference_exists(topic_dir: Path, reference: object) -> bool:
    if not isinstance(reference, str) or not reference.strip():
        return False
    relative = reference.split("#", 1)[0]
    relative = re.sub(r":L\d+(?:-L?\d+)?$", "", relative)
    topic_root = topic_dir.resolve()
    target = (topic_root / relative).resolve()
    return target.is_relative_to(topic_root) and target.is_file() and target.stat().st_size > 0


# --- Citation format (see docs/citations.md) -------------------------------

_SRC_HEADING_RE = re.compile(r"^## \[(SRC-\d+)\] (external|internal|local)\s*$")
_FIELD_RE = re.compile(r"^- ([a-z_]+):\s*(.+?)\s*$")
_LINE_RANGE_RE = re.compile(r":L(\d+)(?:-L?(\d+))?$")
_TAG_RE = re.compile(r"\[(SRC-\d+)\]")
_URL_RE = re.compile(r"^https?://\S+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TOPIC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SRC_ID_RE = re.compile(r"^SRC-\d+$")


def parse_source_ledger(text: str) -> dict[str, dict[str, Any]]:
    """Parse '## [SRC-NNN] <type>' blocks + their '- key: value' fields.

    A strict key/value record, not free text -- unrecognized lines inside a
    block (prose, blank lines) are silently ignored, matching this project's
    existing philosophy of deterministic parsing over cleverness (see
    topic_authoring.split_brief()).
    """
    blocks: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        heading = _SRC_HEADING_RE.match(line)
        if heading:
            current = {"type": heading.group(2), "fields": {}}
            blocks[heading.group(1)] = current
            continue
        if line.startswith("## "):
            current = None
            continue
        if current is not None:
            field = _FIELD_RE.match(line)
            if field:
                current["fields"][field.group(1)] = field.group(2)
    return blocks


def _split_reference(reference: str) -> tuple[str, int | None, int | None]:
    """Split 'path#fragment' / 'path:Lstart-Lend' into (relative_path, start, end).

    Line numbers are 1-indexed and inclusive; a bare ':L42' form returns
    (42, 42). Mirrors the stripping order reference_exists() already used
    (fragment first, then line range), just returning the parsed pieces
    instead of discarding them.
    """
    relative = reference.split("#", 1)[0]
    match = _LINE_RANGE_RE.search(relative)
    if not match:
        return relative, None, None
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else start
    return relative[: match.start()], start, end


def citation_tags_in(text: str, start: int | None, end: int | None) -> list[str]:
    """Extract [SRC-NNN] tags from the given 1-indexed inclusive line range
    (or the whole text if no range given)."""
    if start is not None:
        lines = text.splitlines()
        scope = "\n".join(lines[start - 1 : end])
    else:
        scope = text
    return _TAG_RE.findall(scope)


def internal_citation_exists(
    topics_root: Path, other_topic_id: str, ref: str
) -> dict[str, Any] | None:
    """Read-only lookup of another topic's SOURCE-LEDGER.md citation block.

    Deliberately narrow: only ever reads topics_root/<other_topic_id>/
    SOURCE-LEDGER.md (never an arbitrary path -- an `internal` block only
    ever names a topic id + SRC ref, never a raw path), never writes
    anything. This doesn't violate CONTRACT-CORE.md's "write only the
    current topic directory" boundary -- reading isn't writing.
    """
    other_ledger = topics_root / other_topic_id / "SOURCE-LEDGER.md"
    try:
        text = other_ledger.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_source_ledger(text).get(ref)


def citation_errors_for_block(
    block_id: str,
    block: dict[str, Any],
    *,
    topic_dir: Path,
    topics_root: Path,
    allow_internal: bool,
) -> list[str]:
    errors: list[str] = []
    fields = block.get("fields", {})
    block_type = block.get("type")
    if block_type == "external":
        if not _URL_RE.match(fields.get("url", "")):
            errors.append(f"citation {block_id} (external) requires a valid url")
        if not fields.get("title", "").strip():
            errors.append(f"citation {block_id} (external) requires a title")
        if not _DATE_RE.match(fields.get("retrieved", "")):
            errors.append(
                f"citation {block_id} (external) requires retrieved as YYYY-MM-DD"
            )
    elif block_type == "local":
        path = fields.get("path", "")
        if not path or not reference_exists(topic_dir, path):
            errors.append(f"citation {block_id} (local) path does not resolve: {path!r}")
    elif block_type == "internal":
        if not allow_internal:
            errors.append(
                f"citation {block_id} is internal but internal citations are not "
                "enabled for this topic (see docs/citations.md)"
            )
        else:
            other_topic = fields.get("topic", "")
            ref = fields.get("ref", "")
            if not _TOPIC_ID_RE.match(other_topic) or not _SRC_ID_RE.match(ref):
                errors.append(f"citation {block_id} (internal) has a malformed topic/ref")
            else:
                target = internal_citation_exists(topics_root, other_topic, ref)
                if target is None:
                    errors.append(
                        f"citation {block_id} (internal) points at "
                        f"{other_topic}#{ref} which does not exist"
                    )
                elif target.get("type") == "internal":
                    errors.append(
                        f"citation {block_id} (internal) points at another internal "
                        f"citation ({other_topic}#{ref}) -- must point at external or local"
                    )
    else:
        errors.append(f"citation {block_id} has unrecognized type {block_type!r}")
    return errors


def evidence_citation_errors(
    topic_dir: Path,
    topics_root: Path,
    obligation_id: str,
    evidence_refs: list[str],
    *,
    allow_internal: bool,
) -> list[str]:
    errors: list[str] = []
    try:
        ledger_text = (topic_dir / "SOURCE-LEDGER.md").read_text(encoding="utf-8")
    except OSError:
        ledger_text = ""
    blocks = parse_source_ledger(ledger_text)
    for reference in evidence_refs:
        relative, start, end = _split_reference(reference)
        src_id = None
        if relative == "SOURCE-LEDGER.md" and "#" in reference:
            fragment = reference.split("#", 1)[1]
            if _SRC_ID_RE.match(fragment):
                src_id = fragment
        if src_id is None:
            target = (topic_dir / relative).resolve()
            try:
                target_text = target.read_text(encoding="utf-8")
            except OSError:
                target_text = ""
            tags = citation_tags_in(target_text, start, end)
            src_id = tags[0] if tags else None
        if src_id is None:
            errors.append(
                f"obligation {obligation_id} evidence at {reference} is uncited: "
                "no [SRC-NNN] citation tag found (see docs/citations.md)"
            )
            continue
        block = blocks.get(src_id)
        if block is None:
            errors.append(
                f"obligation {obligation_id} evidence at {reference} cites {src_id} "
                "which is not defined in SOURCE-LEDGER.md"
            )
            continue
        errors.extend(
            citation_errors_for_block(
                src_id,
                block,
                topic_dir=topic_dir,
                topics_root=topics_root,
                allow_internal=allow_internal,
            )
        )
    return errors


def completion_errors(
    topic_dir: Path,
    state: dict[str, Any],
    approved_lock: str | None = None,
    *,
    topics_root: Path | None = None,
    allow_internal_citations: bool = False,
) -> list[str]:
    errors: list[str] = []
    if approved_lock is not None and inventory_lock(state) != approved_lock:
        errors.append("approved completion inventory lock mismatch")
    contract_path = topic_dir / "TOPIC.md"
    try:
        contract_hash = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    except OSError as exc:
        errors.append(f"cannot read topic contract {contract_path}: {exc}")
    else:
        if state.get("contract_sha256") != contract_hash:
            errors.append("contract hash mismatch; operator must reconcile semantic state")
    authority = topic_dir / "AUTHORITY.md"
    try:
        authority_hash = hashlib.sha256(authority.read_bytes()).hexdigest()
    except OSError:
        errors.append("AUTHORITY.md missing")
    else:
        if state.get("authority_sha256") != authority_hash:
            errors.append("authority hash mismatch; operator must reconcile semantic state")
    pending_evidence = state.get("pending_evidence_refs", [])
    if not isinstance(pending_evidence, list) or any(
        not isinstance(reference, str) for reference in pending_evidence
    ):
        errors.append("pending_evidence_refs must be an array of references")
    elif pending_evidence:
        errors.append(f"pending evidence remains: {len(pending_evidence)} reference(s)")
    contradictions = state.get("contradictions", [])
    if not isinstance(contradictions, list):
        errors.append("contradictions must be an array")
    else:
        for contradiction in contradictions:
            if not isinstance(contradiction, dict):
                errors.append("every contradiction must be an object")
                continue
            contradiction_id = str(contradiction.get("id", "<missing-id>"))
            if contradiction.get("status") == "open":
                errors.append(f"open contradiction {contradiction_id}")
    obligations = state.get("obligations")
    if not isinstance(obligations, list) or not obligations:
        return ["semantic state must contain at least one obligation"]
    obligation_ids = [
        str(value.get("id")) for value in obligations if isinstance(value, dict)
    ]
    if len(obligation_ids) != len(set(obligation_ids)):
        errors.append("obligation IDs must be unique")
    for obligation in obligations:
        if not isinstance(obligation, dict):
            errors.append("every obligation must be an object")
            continue
        obligation_id = str(obligation.get("id", "<missing-id>"))
        for field in ("id", "text", "source_ref"):
            if not isinstance(obligation.get(field), str) or not obligation[field].strip():
                errors.append(f"obligation {obligation_id} requires immutable {field}")
        disposition = obligation.get("disposition")
        if disposition == "open":
            errors.append(f"open obligation {obligation_id}")
        elif disposition not in TERMINAL_DISPOSITIONS:
            errors.append(
                f"obligation {obligation_id} has invalid disposition {disposition!r}"
            )
        else:
            if obligation.get("counterevidence_reviewed") is not True:
                errors.append(
                    f"obligation {obligation_id} requires counterevidence review"
                )
            acceptance_summary = obligation.get("acceptance_summary")
            if not isinstance(acceptance_summary, str) or not acceptance_summary.strip():
                errors.append(f"obligation {obligation_id} requires an acceptance summary")
            counterevidence_summary = obligation.get("counterevidence_summary")
            if not (
                isinstance(counterevidence_summary, str)
                and counterevidence_summary.strip()
            ):
                errors.append(
                    f"obligation {obligation_id} requires a counterevidence summary"
                )
            if disposition in {"supported", "contradicted"}:
                evidence_refs = obligation.get("evidence_refs")
                if not isinstance(evidence_refs, list) or not evidence_refs:
                    errors.append(f"obligation {obligation_id} requires evidence_refs")
                elif any(
                    not reference_exists(topic_dir, reference)
                    for reference in evidence_refs
                ):
                    errors.append(
                        f"obligation {obligation_id} evidence reference does not exist"
                    )
                elif state.get("schema_version", 1) >= 2:
                    # Citation enforcement (docs/citations.md) only applies from
                    # schema_version 2 on -- topics approved before this existed
                    # keep validating exactly as they did, unchanged.
                    errors.extend(
                        evidence_citation_errors(
                            topic_dir,
                            topics_root or topic_dir.resolve().parent,
                            obligation_id,
                            evidence_refs,
                            allow_internal=allow_internal_citations,
                        )
                    )
                confidence = obligation.get("confidence")
                if not isinstance(confidence, str) or not confidence.strip():
                    errors.append(f"obligation {obligation_id} requires confidence")
            elif disposition == "unresolved":
                search = obligation.get("adequate_search")
                if not (
                    isinstance(search, dict)
                    and isinstance(search.get("summary"), str)
                    and search["summary"].strip()
                    and isinstance(search.get("queries"), list)
                    and search["queries"]
                    and isinstance(search.get("source_lanes"), list)
                    and search["source_lanes"]
                    and isinstance(search.get("retrieval_failures"), list)
                ):
                    errors.append(
                        f"obligation {obligation_id} requires an adequate-search record"
                    )
            elif disposition == "deferred":
                experiment = obligation.get("experiment")
                if not (
                    isinstance(experiment, dict)
                    and all(
                        isinstance(experiment.get(field), str)
                        and experiment[field].strip()
                        for field in ("question", "method", "success_measure")
                    )
                ):
                    errors.append(
                        f"obligation {obligation_id} requires a precise experiment"
                    )
    deliverables = state.get("deliverables")
    if not isinstance(deliverables, list) or not deliverables:
        errors.append("semantic state must contain at least one deliverable")
    else:
        deliverable_ids = [
            str(value.get("id")) for value in deliverables if isinstance(value, dict)
        ]
        if len(deliverable_ids) != len(set(deliverable_ids)):
            errors.append("deliverable IDs must be unique")
        for deliverable in deliverables:
            if not isinstance(deliverable, dict):
                errors.append("every deliverable must be an object")
                continue
            deliverable_id = str(deliverable.get("id", "<missing-id>"))
            for field in ("id", "description", "path"):
                if not isinstance(deliverable.get(field), str) or not deliverable[field].strip():
                    errors.append(f"deliverable {deliverable_id} requires immutable {field}")
            if deliverable.get("status") != "complete":
                errors.append(f"missing deliverable {deliverable_id}")
                continue
            relative_path = deliverable.get("path")
            if not isinstance(relative_path, str) or not relative_path.strip():
                errors.append(f"deliverable {deliverable_id} requires a path")
                continue
            topic_root = topic_dir.resolve()
            artifact = (topic_root / relative_path).resolve()
            if not artifact.is_relative_to(topic_root):
                errors.append(f"deliverable {deliverable_id} path escapes topic directory")
                continue
            try:
                content = artifact.read_text(encoding="utf-8")
            except OSError:
                content = ""
            if not content.strip():
                errors.append(
                    f"deliverable {deliverable_id} file is missing or empty: {relative_path}"
                )
                continue
            required_headings = deliverable.get("required_headings", [])
            if not isinstance(required_headings, list) or any(
                not isinstance(heading, str) or not heading.strip()
                for heading in required_headings
            ):
                errors.append(
                    f"deliverable {deliverable_id} required_headings must be strings"
                )
                continue
            for heading in required_headings:
                if heading not in content:
                    errors.append(
                        f"deliverable {deliverable_id} missing required heading {heading}"
                    )
            acceptance_summary = deliverable.get("acceptance_summary")
            if not isinstance(acceptance_summary, str) or not acceptance_summary.strip():
                errors.append(f"deliverable {deliverable_id} acceptance summary is required")
            acceptance_refs = deliverable.get("acceptance_evidence_refs")
            if not isinstance(acceptance_refs, list) or not acceptance_refs:
                errors.append(f"deliverable {deliverable_id} acceptance evidence is required")
            elif any(
                not reference_exists(topic_dir, reference)
                for reference in acceptance_refs
            ):
                errors.append(
                    f"deliverable {deliverable_id} acceptance evidence reference does not exist"
                )
    return errors


def semantic_projection(state: dict[str, Any]) -> dict[str, Any]:
    """Return only state transitions that qualify as semantic progress."""
    obligations = []
    for value in state.get("obligations", []):
        if not isinstance(value, dict):
            continue
        obligations.append(
            {
                "id": value.get("id"),
                "disposition": value.get("disposition"),
                "confidence": value.get("confidence"),
                "counterevidence_reviewed": value.get("counterevidence_reviewed"),
                "acceptance_summary": value.get("acceptance_summary"),
                "counterevidence_summary": value.get("counterevidence_summary"),
                "gap_state": value.get("gap_state"),
                "experiment": value.get("experiment"),
            }
        )
    contradictions = []
    for value in state.get("contradictions", []):
        if not isinstance(value, dict):
            continue
        contradictions.append(
            {
                "id": value.get("id"),
                "status": value.get("status"),
                "resolution": value.get("resolution"),
            }
        )
    deliverables = []
    for value in state.get("deliverables", []):
        if not isinstance(value, dict):
            continue
        deliverables.append(
            {
                "id": value.get("id"),
                "status": value.get("status"),
                "acceptance_summary": value.get("acceptance_summary"),
            }
        )
    return {
        "schema_version": state.get("schema_version"),
        "topic_id": state.get("topic_id"),
        "contract_sha256": state.get("contract_sha256"),
        "authority_sha256": state.get("authority_sha256"),
        "obligations": sorted(obligations, key=lambda value: str(value["id"])),
        "contradictions": sorted(
            contradictions, key=lambda value: str(value["id"])
        ),
        "deliverables": sorted(deliverables, key=lambda value: str(value["id"])),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and fingerprint one topic's executable completion state "
            "(SEMANTIC-STATE.json). See docs/topic-authoring.md."
        )
    )
    parser.add_argument(
        "action",
        choices=("validate", "signature", "lock", "rehash", "check", "source-count"),
        help=(
            "validate: the DONE gate -- exit 0 only if every obligation/deliverable "
            "is terminal. "
            "check: structural sanity for a freshly approved topic, before any "
            "research has happened. "
            "signature: deterministic digest of qualifying semantic progress, used "
            "by the queue's stall guard. "
            "lock: print the completion-inventory hash for --lock-sha256 pinning. "
            "rehash: recompute contract/authority hashes after YOU edit TOPIC.md or "
            "AUTHORITY.md -- never run by a research agent. "
            "source-count: print the number of [SRC-NNN] citation blocks in "
            "SOURCE-LEDGER.md (see docs/citations.md)."
        ),
    )
    parser.add_argument("topic_dir", type=Path, help="path to the topic's directory")
    parser.add_argument(
        "--lock-sha256",
        help="with `validate`, also require the completion inventory to match this hash",
    )
    parser.add_argument(
        "--topics-root",
        type=Path,
        help="with `validate` on a schema_version >= 2 topic, the directory containing "
        "every topic (for resolving `internal` citations); default: topic_dir's parent",
    )
    parser.add_argument(
        "--allow-internal-citations",
        action="store_true",
        help="with `validate`, accept well-formed `internal` citation blocks for this "
        "topic (see docs/citations.md) -- rejected by default",
    )
    args = parser.parse_args(argv)
    if args.action == "rehash":
        try:
            state = rehash(args.topic_dir)
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(
            f"rehashed: contract_sha256={state['contract_sha256'][:12]}... "
            f"authority_sha256={state['authority_sha256'][:12]}..."
        )
        return 0
    try:
        state = _load(args.topic_dir)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.action == "validate":
        errors = completion_errors(
            args.topic_dir,
            state,
            args.lock_sha256,
            topics_root=args.topics_root,
            allow_internal_citations=args.allow_internal_citations,
        )
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        print("semantic completion valid")
        return 0
    if args.action == "check":
        errors = structural_errors(args.topic_dir, state)
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        print(f"structurally valid: {len(state.get('obligations', []))} obligations, "
              f"{len(state.get('deliverables', []))} deliverables, ready to queue")
        return 0
    if args.action == "lock":
        print(inventory_lock(state))
        return 0
    if args.action == "source-count":
        try:
            ledger_text = (args.topic_dir / "SOURCE-LEDGER.md").read_text(encoding="utf-8")
        except OSError:
            ledger_text = ""
        print(len(parse_source_ledger(ledger_text)))
        return 0
    payload = json.dumps(semantic_projection(state), sort_keys=True, separators=(",", ":"))
    print(hashlib.sha256(payload.encode("utf-8")).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
