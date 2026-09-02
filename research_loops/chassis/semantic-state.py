#!/usr/bin/env python3
"""Validate and fingerprint topic-owned semantic completion state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


STATE_FILE = "SEMANTIC-STATE.json"
TERMINAL_DISPOSITIONS = {"supported", "contradicted", "unresolved", "deferred"}

# ---------------------------------------------------------------------------
# Single source of truth for what counts as semantic state.
#
# completion_errors() (the DONE gate) and semantic_projection() (the liveness
# signature the queue's stall guard hashes) MUST agree on which fields carry
# semantic meaning. Any field the validator reasons over that the projection
# omits creates a whole class of contract-compliant iterations that register
# as "no progress": the 2026-08-31 incident was exactly this — CONTRACT-CORE
# requires discovery-only iterations whose only state change is new
# pending_evidence_refs, the old projection didn't carry that field, so a
# mandated evidence-discipline step tripped the stall guard.
#
# These tuples are the agreement. semantic_projection() is DERIVED from them,
# and tests/test_projection_parity.py fails the build if completion_errors()
# starts reasoning over a field that is not listed here.
#
# Identity fields (obligation text/source_ref; deliverable description/path/
# required_headings) are deliberately absent: they are pinned by the
# completion-inventory lock and the TOPIC.md contract hash — both of which
# the projection already carries via contract_sha256/authority_sha256 — so an
# identity change is a scope change, not iteration progress.
OBLIGATION_SEMANTIC_FIELDS = (
    "id",
    "disposition",
    "confidence",
    "counterevidence_reviewed",
    "acceptance_summary",
    "counterevidence_summary",
    "gap_state",
    "experiment",
    "evidence_refs",
    "adequate_search",
)
CONTRADICTION_SEMANTIC_FIELDS = ("id", "status", "resolution")
DELIVERABLE_SEMANTIC_FIELDS = (
    "id",
    "status",
    "acceptance_summary",
    "acceptance_evidence_refs",
)
TOP_LEVEL_SEMANTIC_FIELDS = (
    "schema_version",
    "topic_id",
    "contract_sha256",
    "authority_sha256",
    "pending_evidence_refs",
)


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


OBLIGATIONS_HEADING = "## Approved finite obligations"


def append_obligation(
    topic_dir: Path, obligation_id: str, text: str, source_ref: str
) -> None:
    """Append one new, open obligation to both TOPIC.md (the bullet an operator
    or `gap-policy.py promote` would otherwise type by hand under the approved
    obligations heading) and SEMANTIC-STATE.json, in lockstep -- the exact
    mechanical edit `gap-policy.py promote()` and `refresh-policy.py`'s light
    mode both need, factored out once so they can't drift apart. Does not
    rehash(); call that separately once all of a caller's edits are done.
    """
    topic_md_path = topic_dir / "TOPIC.md"
    state_path = topic_dir / STATE_FILE
    contents = topic_md_path.read_text(encoding="utf-8")
    if f"**{obligation_id}**" in contents:
        raise ValueError(f"obligation id already present in TOPIC.md: {obligation_id}")
    if OBLIGATIONS_HEADING not in contents:
        raise ValueError(f"TOPIC.md has no '{OBLIGATIONS_HEADING}' section to append to")
    bullet = f"- **{obligation_id}** — {text}\n"
    heading_at = contents.index(OBLIGATIONS_HEADING)
    next_heading = contents.find("\n## ", heading_at + len(OBLIGATIONS_HEADING))
    insert_at = next_heading if next_heading != -1 else len(contents)
    updated = contents[:insert_at].rstrip("\n") + "\n" + bullet + contents[insert_at:]
    topic_md_path.write_text(updated, encoding="utf-8")

    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.setdefault("obligations", []).append(obligation(obligation_id, text, source_ref))
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


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


def _verification_errors(block_id: str, fields: dict[str, str], label: str) -> list[str]:
    """A citation's *shape* (real URL, real path, real pointer) proves
    nothing about whether the cited location actually contains what's being
    claimed -- that's a content question, not a format question, and format
    validation alone can't catch a well-formed hallucinated citation. This
    is the structural half of closing that gap: `verified: true` must be
    explicitly set by a pass that actually visited the cited location (see
    CONTRACT-CORE.md's evidence-handling section for the "not the same
    agent that cited it" discipline this can't itself enforce). A
    `flagged: hallucination` block is refused outright regardless of
    `verified`, and stays refused until an operator clears the flag --
    finding a hallucination doesn't un-find it.
    """
    if fields.get("flagged", "").strip().lower() == "hallucination":
        return [
            f"citation {block_id} ({label}) is flagged as a hallucination -- the "
            "cited location does not support this claim; it may not back any "
            "disposition until an operator clears the flag"
        ]
    if fields.get("verified", "").strip().lower() != "true":
        return [
            f"citation {block_id} ({label}) is not yet independently verified -- "
            "someone must actually visit the cited location and confirm it supports "
            "the claim, then set `verified: true` (see docs/citations.md)"
        ]
    return []


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
        errors.extend(_verification_errors(block_id, fields, "external"))
    elif block_type == "local":
        path = fields.get("path", "")
        if not path or not reference_exists(topic_dir, path):
            errors.append(f"citation {block_id} (local) path does not resolve: {path!r}")
        errors.extend(_verification_errors(block_id, fields, "local"))
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
                    # Verification is transitive: an internal pointer inherits
                    # the target's own verified/flagged status rather than
                    # needing its own -- the target is what was actually
                    # visited and confirmed.
                    if _verification_errors(ref, target.get("fields", {}), target.get("type", "?")):
                        errors.append(
                            f"citation {block_id} (internal) points at "
                            f"{other_topic}#{ref}, which is not yet independently "
                            "verified or is flagged as a hallucination -- an internal "
                            "citation inherits its target's verification status"
                        )
    else:
        errors.append(f"citation {block_id} has unrecognized type {block_type!r}")
    return errors


def resolve_citation_id(topic_dir: Path, reference: str) -> str | None:
    """Resolve one evidence_ref to the SRC-NNN id it cites, or None if
    uncited. Handles both forms: direct (`SOURCE-LEDGER.md#SRC-NNN`) and
    indirect (an inline `[SRC-NNN]` tag inside the referenced file/line
    range). Public (not chassis-internal) because both `completion_errors()`
    here and `citation-index.py`'s portfolio-wide scan need the exact same
    resolution logic -- duplicating it would let the two drift apart.
    """
    relative, start, end = _split_reference(reference)
    if relative == "SOURCE-LEDGER.md" and "#" in reference:
        fragment = reference.split("#", 1)[1]
        if _SRC_ID_RE.match(fragment):
            return fragment
    target = (topic_dir / relative).resolve()
    try:
        target_text = target.read_text(encoding="utf-8")
    except OSError:
        return None
    tags = citation_tags_in(target_text, start, end)
    return tags[0] if tags else None


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
        src_id = resolve_citation_id(topic_dir, reference)
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


def obligation_terminal_errors(
    topic_dir: Path,
    state: dict[str, Any],
    obligation: dict[str, Any],
    *,
    topics_root: Path | None = None,
    allow_internal_citations: bool = False,
) -> list[str]:
    """Everything one obligation must satisfy to stand as recorded.

    The SINGLE implementation of per-obligation rules, used by BOTH the DONE
    gate (completion_errors) and the write path (`transition`), so a terminal
    disposition can never be written that the completion gate would later
    reject — and the two rule sets cannot drift. tests/test_projection_parity.py
    introspects this function alongside completion_errors.
    """
    errors: list[str] = []
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
        errors.extend(
            obligation_terminal_errors(
                topic_dir,
                state,
                obligation,
                topics_root=topics_root,
                allow_internal_citations=allow_internal_citations,
            )
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


def _normalized_semantic_value(value: Any) -> Any:
    """Normalize a projected field so only meaningful change moves the signature.

    Reference lists (evidence_refs, pending_evidence_refs, ...) are sorted:
    adding or removing a reference is progress, reordering the same set is not.
    Everything else projects verbatim.
    """
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return sorted(value)
    return value


def semantic_projection(state: dict[str, Any]) -> dict[str, Any]:
    """Return only state transitions that qualify as semantic progress.

    Derived from the *_SEMANTIC_FIELDS tuples above — the same field sets the
    completion validator reasons over — so the liveness signature and the DONE
    gate can never disagree about what counts as semantic state.
    """
    obligations = []
    for value in state.get("obligations", []):
        if not isinstance(value, dict):
            continue
        obligations.append(
            {
                field: _normalized_semantic_value(value.get(field))
                for field in OBLIGATION_SEMANTIC_FIELDS
            }
        )
    contradictions = []
    for value in state.get("contradictions", []):
        if not isinstance(value, dict):
            continue
        contradictions.append(
            {
                field: _normalized_semantic_value(value.get(field))
                for field in CONTRADICTION_SEMANTIC_FIELDS
            }
        )
    deliverables = []
    for value in state.get("deliverables", []):
        if not isinstance(value, dict):
            continue
        deliverables.append(
            {
                field: _normalized_semantic_value(value.get(field))
                for field in DELIVERABLE_SEMANTIC_FIELDS
            }
        )
    projection = {
        field: _normalized_semantic_value(state.get(field))
        for field in TOP_LEVEL_SEMANTIC_FIELDS
    }
    projection.update(
        {
            "obligations": sorted(obligations, key=lambda value: str(value["id"])),
            "contradictions": sorted(
                contradictions, key=lambda value: str(value["id"])
            ),
            "deliverables": sorted(deliverables, key=lambda value: str(value["id"])),
        }
    )
    return projection


# ---------------------------------------------------------------------------
# Accessor / write-through layer (docs/state-access.md)
#
# The state file is the source of truth, but agents should neither read it
# whole (49 obligations of terminal prose re-enter the context every turn)
# nor rewrite it whole with ad-hoc scripts (one bad script bricks the topic).
# `select` and `get` are the scoped read paths; `transition`/`pending`/
# `deliverable`/`contradiction` are the guarded write paths, validating at
# write time with the SAME rule implementations the DONE gate uses.
# ---------------------------------------------------------------------------


def _flag_needs_operator(topic_dir: Path, flag: str, detail: str) -> None:
    """Escalate to the operator through the loop's own STOP contract.

    Deferral is a scope decision, and scope belongs to the operator: a loop
    may record that it chose not to pursue an obligation, but that choice
    must surface for review instead of silently counting toward DONE.
    Writing STOP parks the topic as needs_attention at the queue layer; the
    `flag:` lines tell the operator exactly where to look.
    """
    stop = topic_dir / "STOP"
    lines: list[str] = []
    if stop.exists():
        lines = [l for l in stop.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines or lines[0].split(None, 1)[0].rstrip(":.,;") != "NEEDS-OPERATOR":
        lines.insert(0, "NEEDS-OPERATOR")
    entry = f"flag: {flag}"
    if entry not in lines:
        lines.append(entry)
        if detail:
            lines.append(f"  {detail}")
    stop.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_state(topic_dir: Path, state: dict[str, Any]) -> None:
    """The single atomic write path for every mutating subcommand."""
    path = topic_dir / STATE_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)


def work_selection_view(state: dict[str, Any]) -> dict[str, Any]:
    """Everything work selection needs, nothing it doesn't.

    Open (non-terminal) obligations in full — selection judgment needs their
    complete records. Terminal obligations as skeletons — they are done; a
    revalidation pass that needs one fetches it via `get`. Open
    contradictions in full, resolved ones as skeletons. This is a read
    projection: the file is untouched and remains authoritative.
    """
    open_obligations: list[dict[str, Any]] = []
    terminal: list[dict[str, Any]] = []
    for value in state.get("obligations", []):
        if not isinstance(value, dict):
            continue
        if value.get("disposition") in TERMINAL_DISPOSITIONS:
            terminal.append(
                {
                    "id": value.get("id"),
                    "disposition": value.get("disposition"),
                    "confidence": value.get("confidence"),
                }
            )
        else:
            open_obligations.append(value)
    contradictions = [
        value
        if value.get("status") == "open"
        else {"id": value.get("id"), "status": value.get("status")}
        for value in state.get("contradictions", [])
        if isinstance(value, dict)
    ]
    deliverables = [
        {"id": value.get("id"), "status": value.get("status"), "path": value.get("path")}
        for value in state.get("deliverables", [])
        if isinstance(value, dict)
    ]
    return {
        "topic_id": state.get("topic_id"),
        "schema_version": state.get("schema_version"),
        "counts": {
            "obligations_open": len(open_obligations),
            "obligations_terminal": len(terminal),
            "pending_evidence_refs": len(state.get("pending_evidence_refs") or []),
        },
        "open_obligations": open_obligations,
        "terminal_obligations": terminal,
        "pending_evidence_refs": state.get("pending_evidence_refs", []),
        "contradictions": contradictions,
        "deliverables": deliverables,
    }


def find_record(state: dict[str, Any], record_id: str) -> tuple[str, dict[str, Any]] | None:
    """Locate one record by id across obligations/deliverables/contradictions."""
    for kind, key in (
        ("obligation", "obligations"),
        ("deliverable", "deliverables"),
        ("contradiction", "contradictions"),
    ):
        for value in state.get(key, []):
            if isinstance(value, dict) and value.get("id") == record_id:
                return kind, value
    return None


_OBLIGATION_WRITABLE_FIELDS = {
    "disposition",
    "confidence",
    "gap_state",
    "acceptance_summary",
    "counterevidence_summary",
    "counterevidence_reviewed",
    "adequate_search",
    "experiment",
}


def apply_obligation_transition(
    topic_dir: Path,
    state: dict[str, Any],
    obligation_id: str,
    updates: dict[str, Any],
    add_evidence_refs: list[str],
    *,
    topics_root: Path | None = None,
    allow_internal_citations: bool = False,
) -> list[str]:
    """Apply a guarded update to one obligation, in place. Returns errors.

    Identity fields (id/text/source_ref) are operator-owned and not writable
    here. A transition to a terminal disposition must be complete in one
    call: the updated record is checked against obligation_terminal_errors —
    the exact DONE-gate rules — and NOTHING is written if it fails, so a
    terminal state the completion gate would reject can never land on disk.
    """
    found = find_record(state, obligation_id)
    if found is None or found[0] != "obligation":
        return [f"unknown obligation: {obligation_id}"]
    obligation = found[1]
    illegal = set(updates) - _OBLIGATION_WRITABLE_FIELDS
    if illegal:
        return [
            f"field(s) {sorted(illegal)} are not writable via transition "
            "(identity fields are operator-owned; see rehash/relock for scope changes)"
        ]
    errors: list[str] = []
    for reference in add_evidence_refs:
        if not reference_exists(topic_dir, reference):
            errors.append(f"evidence reference does not exist: {reference}")
    if errors:
        return errors
    candidate = dict(obligation)
    candidate.update(updates)
    refs = list(candidate.get("evidence_refs") or [])
    for reference in add_evidence_refs:
        if reference not in refs:
            refs.append(reference)
    candidate["evidence_refs"] = refs
    disposition = candidate.get("disposition")
    if disposition not in TERMINAL_DISPOSITIONS and disposition != "open":
        return [f"invalid disposition {disposition!r}"]
    if disposition in TERMINAL_DISPOSITIONS:
        errors = obligation_terminal_errors(
            topic_dir,
            state,
            candidate,
            topics_root=topics_root,
            allow_internal_citations=allow_internal_citations,
        )
        if errors:
            return [
                "terminal transition refused (a terminal disposition must be "
                "complete in one call; nothing was written):",
                *errors,
            ]
    obligation.clear()
    obligation.update(candidate)
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate, fingerprint, and access one topic's executable completion "
            "state (SEMANTIC-STATE.json). Agents: read via `select`/`get`, write "
            "via `transition`/`pending`/`deliverable`/`contradiction` — never "
            "read or rewrite the whole file. See docs/topic-authoring.md and "
            "docs/state-access.md."
        )
    )
    sub = parser.add_subparsers(dest="action", required=True)

    def _topic(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("topic_dir", type=Path, help="path to the topic's directory")
        return p

    validate = _topic(sub.add_parser(
        "validate",
        help="the DONE gate -- exit 0 only if every obligation/deliverable is terminal",
    ))
    validate.add_argument(
        "--lock-sha256",
        help="also require the completion inventory to match this hash",
    )
    validate.add_argument(
        "--topics-root",
        type=Path,
        help="on a schema_version >= 2 topic, the directory containing every topic "
        "(for resolving `internal` citations); default: topic_dir's parent",
    )
    validate.add_argument(
        "--allow-internal-citations",
        action="store_true",
        help="accept well-formed `internal` citation blocks (see docs/citations.md)",
    )
    _topic(sub.add_parser(
        "check", help="structural sanity for a freshly approved topic"
    ))
    _topic(sub.add_parser(
        "signature",
        help="deterministic digest of qualifying semantic progress (stall guard)",
    ))
    _topic(sub.add_parser(
        "lock", help="print the completion-inventory hash for --lock-sha256 pinning"
    ))
    _topic(sub.add_parser(
        "rehash",
        help="recompute contract/authority hashes after YOU edit TOPIC.md or "
        "AUTHORITY.md -- never run by a research agent",
    ))
    _topic(sub.add_parser(
        "source-count",
        help="print the number of [SRC-NNN] citation blocks in SOURCE-LEDGER.md",
    ))

    _topic(sub.add_parser(
        "select",
        help="work-selection view: open obligations in full, terminal ones as "
        "skeletons, pending refs, open contradictions, deliverable statuses -- "
        "the read path for orientation (never read the whole state file)",
    ))
    get_parser = _topic(sub.add_parser(
        "get", help="one full record (obligation/deliverable/contradiction) by id"
    ))
    get_parser.add_argument("record_id")

    transition = _topic(sub.add_parser(
        "transition",
        help="guarded update to one obligation; a terminal disposition must be "
        "complete in one call and is checked with the DONE gate's own rules "
        "before anything is written",
    ))
    transition.add_argument("obligation_id")
    transition.add_argument("--disposition")
    transition.add_argument("--confidence")
    transition.add_argument("--gap-state")
    transition.add_argument("--acceptance-summary")
    transition.add_argument("--counterevidence-summary")
    transition.add_argument("--counterevidence-reviewed", choices=("true", "false"))
    transition.add_argument(
        "--add-evidence-ref",
        action="append",
        default=[],
        help="repeatable; each must resolve inside the topic directory",
    )
    transition.add_argument(
        "--adequate-search", help="JSON object: summary/queries/source_lanes/retrieval_failures"
    )
    transition.add_argument(
        "--experiment", help="JSON object: question/method/success_measure"
    )
    transition.add_argument(
        "--topics-root", type=Path, help="as for validate (internal citations)"
    )
    transition.add_argument("--allow-internal-citations", action="store_true")

    pending = _topic(sub.add_parser(
        "pending", help="add or remove one pending evidence reference"
    ))
    pending_action = pending.add_mutually_exclusive_group(required=True)
    pending_action.add_argument("--add", metavar="REF")
    pending_action.add_argument("--remove", metavar="REF")

    deliverable_parser = _topic(sub.add_parser(
        "deliverable",
        help="update one deliverable's status/acceptance (required-heading "
        "checks stay at the DONE gate, which reads the artifact itself)",
    ))
    deliverable_parser.add_argument("deliverable_id")
    deliverable_parser.add_argument("--status", choices=("missing", "complete"))
    deliverable_parser.add_argument("--acceptance-summary")
    deliverable_parser.add_argument(
        "--add-acceptance-ref", action="append", default=[]
    )

    contradiction_parser = _topic(sub.add_parser(
        "contradiction", help="open a new contradiction or resolve an existing one"
    ))
    contradiction_action = contradiction_parser.add_mutually_exclusive_group(required=True)
    contradiction_action.add_argument("--open", metavar="ID", dest="open_id")
    contradiction_action.add_argument("--resolve", metavar="ID", dest="resolve_id")
    contradiction_parser.add_argument("--resolution")

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
    if args.action == "select":
        print(json.dumps(work_selection_view(state), indent=2, sort_keys=True))
        return 0
    if args.action == "get":
        found = find_record(state, args.record_id)
        if found is None:
            print(f"no record with id {args.record_id!r}", file=sys.stderr)
            return 1
        kind, record = found
        print(json.dumps({"kind": kind, "record": record}, indent=2, sort_keys=True))
        return 0
    if args.action == "transition":
        updates: dict[str, Any] = {}
        for field, value in (
            ("disposition", args.disposition),
            ("confidence", args.confidence),
            ("gap_state", args.gap_state),
            ("acceptance_summary", args.acceptance_summary),
            ("counterevidence_summary", args.counterevidence_summary),
        ):
            if value is not None:
                updates[field] = value
        if args.counterevidence_reviewed is not None:
            updates["counterevidence_reviewed"] = args.counterevidence_reviewed == "true"
        for field, raw in (
            ("adequate_search", args.adequate_search),
            ("experiment", args.experiment),
        ):
            if raw is not None:
                try:
                    updates[field] = json.loads(raw)
                except json.JSONDecodeError as exc:
                    print(f"--{field.replace('_', '-')} is not valid JSON: {exc}", file=sys.stderr)
                    return 2
        if not updates and not args.add_evidence_ref:
            print("transition: nothing to change", file=sys.stderr)
            return 2
        errors = apply_obligation_transition(
            args.topic_dir,
            state,
            args.obligation_id,
            updates,
            args.add_evidence_ref,
            topics_root=args.topics_root,
            allow_internal_citations=args.allow_internal_citations,
        )
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        _write_state(args.topic_dir, state)
        found = find_record(state, args.obligation_id)
        assert found is not None
        if found[1].get("disposition") == "deferred":
            summary = (found[1].get("acceptance_summary") or found[1].get("gap_state") or "").strip()
            _flag_needs_operator(
                args.topic_dir,
                f"deferred-obligation {args.obligation_id}",
                summary[:300],
            )
        print(json.dumps(
            {
                "id": args.obligation_id,
                "disposition": found[1].get("disposition"),
                "changed": sorted(updates) + (["evidence_refs"] if args.add_evidence_ref else []),
            },
            sort_keys=True,
        ))
        return 0
    if args.action == "pending":
        refs = state.setdefault("pending_evidence_refs", [])
        if not isinstance(refs, list):
            print("pending_evidence_refs is malformed", file=sys.stderr)
            return 1
        if args.add is not None:
            if not reference_exists(args.topic_dir, args.add):
                print(f"pending reference does not exist: {args.add}", file=sys.stderr)
                return 1
            if args.add not in refs:
                refs.append(args.add)
        else:
            if args.remove not in refs:
                print(f"not a pending reference: {args.remove}", file=sys.stderr)
                return 1
            refs.remove(args.remove)
        _write_state(args.topic_dir, state)
        print(json.dumps({"pending_evidence_refs": len(refs)}, sort_keys=True))
        return 0
    if args.action == "deliverable":
        found = find_record(state, args.deliverable_id)
        if found is None or found[0] != "deliverable":
            print(f"unknown deliverable: {args.deliverable_id}", file=sys.stderr)
            return 1
        record = found[1]
        candidate = dict(record)
        if args.status is not None:
            candidate["status"] = args.status
        if args.acceptance_summary is not None:
            candidate["acceptance_summary"] = args.acceptance_summary
        refs = list(candidate.get("acceptance_evidence_refs") or [])
        for reference in args.add_acceptance_ref:
            if not reference_exists(args.topic_dir, reference):
                print(f"acceptance reference does not exist: {reference}", file=sys.stderr)
                return 1
            if reference not in refs:
                refs.append(reference)
        candidate["acceptance_evidence_refs"] = refs
        if candidate.get("status") == "complete":
            summary = candidate.get("acceptance_summary")
            if not isinstance(summary, str) or not summary.strip():
                print(
                    "completing a deliverable requires --acceptance-summary "
                    "(nothing was written)",
                    file=sys.stderr,
                )
                return 1
            if not refs:
                print(
                    "completing a deliverable requires at least one "
                    "--add-acceptance-ref (nothing was written)",
                    file=sys.stderr,
                )
                return 1
        record.clear()
        record.update(candidate)
        _write_state(args.topic_dir, state)
        print(json.dumps({"id": args.deliverable_id, "status": record.get("status")}, sort_keys=True))
        return 0
    if args.action == "contradiction":
        contradictions = state.setdefault("contradictions", [])
        if args.open_id is not None:
            if find_record(state, args.open_id) is not None:
                print(f"id already exists: {args.open_id}", file=sys.stderr)
                return 1
            contradictions.append(
                {"id": args.open_id, "status": "open", "resolution": None}
            )
            _write_state(args.topic_dir, state)
            print(json.dumps({"id": args.open_id, "status": "open"}, sort_keys=True))
            return 0
        found = find_record(state, args.resolve_id)
        if found is None or found[0] != "contradiction":
            print(f"unknown contradiction: {args.resolve_id}", file=sys.stderr)
            return 1
        if not args.resolution or not args.resolution.strip():
            print("--resolution is required to resolve a contradiction", file=sys.stderr)
            return 1
        found[1]["status"] = "resolved"
        found[1]["resolution"] = args.resolution
        _write_state(args.topic_dir, state)
        print(json.dumps({"id": args.resolve_id, "status": "resolved"}, sort_keys=True))
        return 0
    payload = json.dumps(semantic_projection(state), sort_keys=True, separators=(",", ":"))
    print(hashlib.sha256(payload.encode("utf-8")).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
