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
    """Build a fresh, open obligation record. Used by tools/new-topic when
    promoting a draft; never called by a running research agent."""
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


def completion_errors(
    topic_dir: Path,
    state: dict[str, Any],
    approved_lock: str | None = None,
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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("validate", "signature", "lock", "rehash", "check")
    )
    parser.add_argument("topic_dir", type=Path)
    parser.add_argument("--lock-sha256")
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
        errors = completion_errors(args.topic_dir, state, args.lock_sha256)
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
    payload = json.dumps(semantic_projection(state), sort_keys=True, separators=(",", ":"))
    print(hashlib.sha256(payload.encode("utf-8")).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
