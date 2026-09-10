"""One strict, transport-neutral intake workflow.

The controller is the authority for draft revisions, discovery history and queue
registration.  Files below ``topics/`` are a staged publication projection only.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from . import topic_authoring
from .input_schema import InterfaceError, integer, nonempty_string, strict_object


class IntakeService:
    """Application operations shared by CLI/MCP; caller identity is injected."""
    def __init__(self, control: Any, topics_root: Path, *, actor: str, publisher: Callable[..., Mapping[str, Any]] | None = None):
        self.control, self.topics_root, self.actor, self.publisher = control, Path(topics_root), actor, publisher

    @staticmethod
    def _brief(payload: Any) -> dict[str, Any]:
        item = strict_object(payload, path="$", required={"schema_version", "request_id", "topic_id", "title", "operator_brief", "mode"})
        if integer(item["schema_version"], "$.schema_version") != 1:
            raise InterfaceError("VALIDATION_ERROR", "$.schema_version", "supported schema version 1", "integer", "schema version is unsupported", "use schema_version 1")
        for field in ("request_id", "topic_id", "title", "operator_brief"):
            nonempty_string(item[field], f"$.{field}")
        if not topic_authoring._TOPIC_ID_PATTERN.fullmatch(item["topic_id"]):
            raise InterfaceError("VALIDATION_ERROR", "$.topic_id", "lowercase slug (letters, digits, hyphens)", "string", "topic_id is not a canonical topic identity", "use a lowercase topic slug")
        if item["mode"] not in ("focused", "broad"):
            raise InterfaceError("VALIDATION_ERROR", "$.mode", "focused or broad", type(item["mode"]).__name__, "mode is unsupported", "use focused or broad")
        return dict(item)

    def submit_brief(self, payload: Any) -> Mapping[str, Any]:
        brief = self._brief(payload)
        draft_dir = self.topics_root / brief["topic_id"]
        fingerprint = _fingerprint(brief)
        with self.control.transaction(actor=self.actor, operation_id=brief["request_id"], affected_ids=[brief["topic_id"]]) as state:
            requests = state["work"].setdefault("intake_requests", {})
            existing = requests.get(brief["request_id"])
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise InterfaceError("DUPLICATE_REQUEST_CONFLICT", "$.request_id", "same payload", "different payload", "request_id was already used with another payload", "use a new request_id")
                if existing.get("result"): return existing["result"]
            drafts = state["work"].setdefault("intake_drafts", {})
            prior = drafts.get(brief["topic_id"])
            if prior and not (existing and existing.get("result") is None) and prior.get("status") != "rejected":
                raise InterfaceError("VALIDATION_ERROR", "$.topic_id", "new or rejected topic id", "existing draft", "a current draft already exists", "review the existing draft or use a new topic_id")
            if draft_dir.exists() and not existing: raise InterfaceError("VALIDATION_ERROR", "$.topic_id", "unused topic directory", "existing directory", "topic directory already exists outside this request", "choose another topic_id")
            draft = {"topic_id": brief["topic_id"], "title": brief["title"], "mode": brief["mode"], "draft_revision": 1, "draft_hash": None, "status": "publishing_draft", "discovery_history": []}
            drafts[brief["topic_id"]] = draft
            requests[brief["request_id"]] = {"fingerprint": fingerprint, "result": None}
        if not draft_dir.exists(): topic_authoring.new_topic(brief["topic_id"], title=brief["title"], brief_text=brief["operator_brief"], dest=self.topics_root, mode=brief["mode"])
        digest = draft_hash(draft_dir)
        # A permission-restricted probe must fail loudly, never silently
        # downgrade a managed intake to an unprotected draft: Path.exists()
        # returns False on EACCES, so stat and re-raise instead.
        import os as _os
        try:
            _os.stat(self.topics_root.parent / "state" / "access.json")
            protected = True
        except FileNotFoundError:
            protected = False
        except PermissionError as exc:
            raise InterfaceError("VALIDATION_ERROR", "$", "readable managed access configuration",
                                 "permission denied", "cannot determine managed protection state",
                                 "run intake through the controller (socket) or as the supervisor") from exc
        if protected:
            from .access import load_access
            from .deployment import protect_topic
            access = load_access(self.topics_root.parent)
            protect_topic(draft_dir, agent_uid=access["agent_uid"], agent_gid=access["agent_gid"], draft=True)
        with self.control.transaction(actor=self.actor, operation_id=brief["request_id"], affected_ids=[brief["topic_id"]]) as state:
            draft = state["work"]["intake_drafts"][brief["topic_id"]]; task = _discovery_task(brief["topic_id"], draft_dir)
            if not any(i.get("id") == task["id"] for i in state["queue"].setdefault("items", [])):
                state["queue"]["items"].append(task); state["queue"]["revision"] = int(state["queue"].get("revision", 0)) + 1
            draft.update({"draft_hash": digest, "status": "discovery_queued"})
            result = {"topic_id": brief["topic_id"], "draft_revision": 1, "draft_hash": digest, "discovery_task_id": task["id"], "status": "discovery_queued"}
            state["work"]["intake_requests"][brief["request_id"]]["result"] = result
            return result

    def record_discovery_result(self, payload: Any) -> Mapping[str, Any]:
        result = _validate_discovery(payload)
        with self.control.transaction(actor=self.actor, operation_id=result["request_id"], affected_ids=[result["topic_id"]]) as state:
            requests = state["work"].setdefault("intake_requests", {})
            fingerprint = _fingerprint(result)
            replay = requests.get(result["request_id"])
            if replay:
                if replay["fingerprint"] != fingerprint:
                    raise InterfaceError("DUPLICATE_REQUEST_CONFLICT", "$.request_id", "same payload", "different payload", "request_id was already used with another payload", "use a new request_id")
                return replay["result"]
            if state["revision"] != result["expected_revision"]:
                raise InterfaceError("REVISION_CONFLICT", "$.expected_revision", str(state["revision"]), str(result["expected_revision"]), "controller state changed", "refresh the draft and retry")
            draft = state["work"].setdefault("intake_drafts", {}).get(result["topic_id"])
            if not draft or draft["draft_revision"] != result["draft_revision"] or draft["draft_hash"] != result["draft_hash"]:
                raise InterfaceError("DRAFT_RESULT_STALE", "$.draft_hash", "current draft revision/hash", str(result["draft_hash"]), "discovery result targets a stale draft", "run discovery against the current draft")
            required_pass = "discovery" if draft["mode"] == "broad" else "criteria"
            if result["pass_kind"] != required_pass:
                raise InterfaceError("VALIDATION_ERROR", "$.pass_kind", required_pass, result["pass_kind"], "pass kind must match the draft QA mode", "run the required pass for this draft")
            record = dict(result)
            record["result_id"] = f"discovery-result-{len(draft['discovery_history']) + 1}"
            draft["discovery_history"].append(record)
            draft["status"] = "awaiting_operator"
            response = {"topic_id": result["topic_id"], "result_id": record["result_id"], "draft_revision": draft["draft_revision"], "status": draft["status"], "history_count": len(draft["discovery_history"])}
            requests[result["request_id"]] = {"fingerprint": fingerprint, "result": response}
            return response

    def approve(self, payload: Any) -> Mapping[str, Any]:
        """Validate then recoverably publish and register once through controller."""
        decision = _validate_intake_decision(payload)
        replacements: list[tuple[str, str]] = []
        if decision["action"] == "approve_with_edits":
            edits = decision["edits"]
            required = {"draft_authority", "draft_topic", "draft_semantic_state"}
            if not isinstance(edits, Mapping) or set(edits) != required or not all(isinstance(edits[x], str) and edits[x].strip() for x in required):
                raise InterfaceError("VALIDATION_ERROR", "$.edits", "complete draft_authority, draft_topic, draft_semantic_state replacement", type(edits).__name__, "edited approval requires the whole exact contract bundle", "supply all three complete replacement values")
            # Parse before writing so malformed replacement content never
            # changes a draft.  The semantic state remains subject to the
            # ordinary approval structural check below.
            try: json.loads(edits["draft_semantic_state"])
            except json.JSONDecodeError as exc: raise InterfaceError("VALIDATION_ERROR", "$.edits.draft_semantic_state", "valid JSON", "invalid", str(exc), "supply semantic-state JSON") from exc
            replacements = [("DRAFT-AUTHORITY.md", edits["draft_authority"]), ("DRAFT-TOPIC.md", edits["draft_topic"]), ("DRAFT-SEMANTIC-STATE.json", edits["draft_semantic_state"])]
        # Publication is staged in controller state before irreversible renames.
        # A retry with the same request resumes this record instead of registering
        # a duplicate queue item.
        with self.control.transaction(actor=self.actor, operation_id=decision["request_id"], affected_ids=[decision["topic_id"]]) as state:
            requests = state["work"].setdefault("intake_requests", {})
            fingerprint = _fingerprint(decision)
            replay = requests.get(decision["request_id"])
            if replay:
                if replay["fingerprint"] != fingerprint:
                    raise InterfaceError("DUPLICATE_REQUEST_CONFLICT", "$.request_id", "same payload", "different payload", "request_id was already used with another payload", "use a new request_id")
                return replay["result"]
            pending = state["work"].setdefault("intake_publications", {}).get(decision["request_id"])
            if pending is not None and pending["decision"] != decision:
                raise InterfaceError("DUPLICATE_REQUEST_CONFLICT", "$.request_id", "same payload", "different payload", "request_id has a publication intent with different content", "retry the original request or use a new request_id")
            # Once this exact request has a durable publication intent, its
            # original expected revision remains valid for recovery; the intent
            # transaction necessarily advanced the global revision itself.
            if pending is None and state["revision"] != decision["expected_revision"]:
                raise InterfaceError("REVISION_CONFLICT", "$.expected_revision", str(state["revision"]), str(decision["expected_revision"]), "controller state changed", "refresh and resubmit")
            draft = state["work"].setdefault("intake_drafts", {}).get(decision["topic_id"])
            if not draft or draft["draft_revision"] != decision["draft_revision"]:
                raise InterfaceError("DRAFT_RESULT_STALE", "$.draft_revision", "current draft revision", str(decision["draft_revision"]), "approval targets a stale draft", "review the current draft")
            actual_hash = draft_hash(self.topics_root / decision["topic_id"]) if pending is None else draft["draft_hash"]
            if actual_hash != draft["draft_hash"] and decision["action"] != "approve_with_edits":
                raise InterfaceError("DRAFT_RESULT_STALE", "$.draft_hash", draft["draft_hash"], actual_hash, "draft files changed after the accepted discovery result", "run discovery again against the edited draft")
            if not any(r["result_id"] == decision["result_id"] for r in draft["discovery_history"]):
                raise InterfaceError("VALIDATION_ERROR", "$.result_id", "accepted discovery result id", str(decision["result_id"]), "result does not belong to this draft", "submit the reviewed result id")
            if pending is None:
                if any(p["topic_id"] == decision["topic_id"] and p["state"] == "pending" for p in state["work"]["intake_publications"].values()):
                    raise InterfaceError("PUBLICATION_PENDING", "$.topic_id", "no other pending publication", "pending publication", "another decision already owns this draft publication", "retry its original request")
                prepared = self._prepare_approval(decision, replacements) if decision["action"] != "reject" else None
                pending = {"topic_id": decision["topic_id"], "decision": decision, "state": "pending", "prepared": prepared}
                state["work"]["intake_publications"][decision["request_id"]] = pending
        if decision["action"] == "reject":
            with self.control.transaction(actor=self.actor, operation_id=decision["request_id"], affected_ids=[decision["topic_id"]]) as state:
                state["work"]["intake_drafts"][decision["topic_id"]]["status"] = "rejected"
                state["work"]["intake_publications"][decision["request_id"]]["state"] = "rejected"
                result = {"topic_id": decision["topic_id"], "status": "rejected", "registered": False}
                state["work"].setdefault("intake_requests", {})[decision["request_id"]] = {"fingerprint": _fingerprint(decision), "result": result}
                return result
        topic_dir = self.topics_root / decision["topic_id"]
        # The validated complete publication is already committed in the intent.
        # Retry overwrites the same content; it never approves whatever happens
        # to remain after a partial rename or interrupted operator request.
        from .contract_publication import _atomic_write
        prepared = pending["prepared"]
        for name, value in prepared["files"].items():
            _atomic_write(topic_dir / name, value)
        approved = {"lock": topic_authoring.compute_lock(topic_dir)}
        if approved["lock"] != prepared["lock"]:
            raise RuntimeError("published intake inventory does not match its validated intent")
        access_path = self.topics_root.parent / "state" / "access.json"
        if access_path.exists():
            from .access import load_access
            from .deployment import protect_topic
            access = load_access(self.topics_root.parent)
            protect_topic(self.topics_root / decision["topic_id"], agent_uid=access["agent_uid"], agent_gid=access["agent_gid"])
        with self.control.transaction(actor=self.actor, operation_id=decision["request_id"], affected_ids=[decision["topic_id"]]) as state:
            publications = state["work"]["intake_publications"]
            pending = publications[decision["request_id"]]
            queue = state["queue"].setdefault("items", [])
            item = next((i for i in queue if i.get("id") == decision["topic_id"]), None)
            if item is None:
                item = _research_item(decision["topic_id"], self.topics_root / decision["topic_id"], approved["lock"])
                position = decision.get("position", len(queue))
                queue.insert(position, item)
                state["queue"]["revision"] = int(state["queue"].get("revision", 0)) + 1
            self.control.ensure_topic_work(state, decision["topic_id"], inventory_version=approved["lock"])
            state["work"]["intake_drafts"][decision["topic_id"]]["status"] = "approved"
            pending["state"] = "published"
            result = {"topic_id": decision["topic_id"], "status": "approved", "registered": True, "item": item, "publication_state": "published"}
            state["work"].setdefault("intake_requests", {})[decision["request_id"]] = {"fingerprint": _fingerprint(decision), "result": result}
            return result

    def _prepare_approval(self, decision: Mapping[str, Any], replacements: list) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="intake-approval-") as temporary:
            destination = Path(temporary)
            directory = destination / str(decision["topic_id"])
            shutil.copytree(self.topics_root / str(decision["topic_id"]), directory)
            for name, value in replacements:
                (directory / name).write_text(value.rstrip() + "\n", encoding="utf-8")
            self._materialize_legacy_review(decision, directory=directory)
            approved = topic_authoring.approve_topic(str(decision["topic_id"]), dest=destination)
            names = ("TOPIC.md", "AUTHORITY.md", "SEMANTIC-STATE.json", "QA-RECORD.md", "SCOPE-PROPOSAL.md")
            return {"files": {name: (directory / name).read_text(encoding="utf-8") for name in names}, "lock": approved["lock"]}

    def _materialize_legacy_review(self, decision: Mapping[str, Any], *, directory: Path | None = None) -> None:
        directory = directory or self.topics_root / str(decision["topic_id"])
        draft = self.control.snapshot()["work"]["intake_drafts"][decision["topic_id"]]
        result = next(item for item in draft["discovery_history"] if item["result_id"] == decision["result_id"])
        qa = directory / "QA-RECORD.md"; content = qa.read_text(encoding="utf-8")
        def replace_section(name: str, value: str) -> None:
            nonlocal content
            marker = f"## {name}"; head, tail = content.split(marker, 1); parts = tail.split("\n## ", 1)
            content = head + marker + "\n\n" + value.strip() + "\n" + (("\n## " + parts[1]) if len(parts) > 1 else "")
        replace_section("Restated intent", result["restated_intent"])
        replace_section("Traceability review", "\n".join(f"- {x.get('explanation','')}" for x in result["traceability"]) or "- No traceability findings.")
        replace_section("Operator confirmation", decision["rationale"])
        if draft["mode"] == "broad": replace_section("Scope decision", decision["rationale"])
        qa.write_text(content, encoding="utf-8")
        criteria = "\n".join(f"- Criterion {x['id']}: {x['status']} — {x['explanation']}" for x in result["criteria"])
        (directory / "SCOPE-PROPOSAL.md").write_text("## Contract criteria findings\n\n" + criteria + "\n", encoding="utf-8")


def draft_hash(topic_dir: Path) -> str:
    """Stable reference for a discovery result; no result may target a different draft."""
    digest = hashlib.sha256()
    # QA answers are operator decision records, deliberately mutable after a
    # discovery result. Contract files themselves are the bound draft.
    for name in ("DRAFT-AUTHORITY.md", "DRAFT-TOPIC.md", "DRAFT-SEMANTIC-STATE.json"):
        digest.update(name.encode() + b"\0")
        digest.update((topic_dir / name).read_bytes())
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InterfaceError("VALIDATION_ERROR", "$", "valid JSON object", "invalid", str(exc), "correct the JSON and resubmit") from exc
    if not isinstance(value, dict):
        raise InterfaceError("VALIDATION_ERROR", "$", "JSON object", type(value).__name__, "top-level value must be an object", "submit a JSON object")
    return value


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _discovery_task(topic_id: str, topic_dir: Path) -> dict[str, Any]:
    return _runtime_item(f"discovery.{topic_id}", f"Discovery: {topic_id}", topic_dir, lane="intake", managed_kind="intake_discovery", command=[str(Path(__file__).parent / "chassis" / "run-discovery.sh"), str(topic_dir), "generic"])


def _research_item(topic_id: str, topic_dir: Path, lock: str) -> dict[str, Any]:
    item = _runtime_item(topic_id, topic_id, topic_dir, lane="research", managed_kind="research", command=[str(Path(__file__).parent / "chassis" / "run-topic.sh"), str(topic_dir)])
    item["completion_lock"] = lock
    item["stop_file"] = "STOP"
    item["usage_file"] = "logs/latest-usage.json"
    return item


def _runtime_item(item_id: str, title: str, topic_dir: Path, *, lane: str, managed_kind: str, command: list[str]) -> dict[str, Any]:
    """Complete queue shape for controller-created work.

    This mirrors the stable QueueStore runtime contract so ordinary runner
    controls, recovery, failure accounting and completion gates need no
    special case for intake-created records.
    """
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"id": item_id, "title": title, "cwd": str(topic_dir), "command": command, "provider": None, "usage_file": None, "stop_file": None, "completion_command": None, "depends_on": [], "progress_command": None, "on_completed_command": None, "stall_limit": 6, "gap_policy": "review", "gap_auto_limit": 0, "completion_lock": None, "internal_citations": False, "topic_refresh": "off", "topic_refresh_mode": "continue", "lane": lane, "managed_kind": managed_kind, "research_policy": None, "research_blockers": [], "refresh_due_at": None, "refresh_count": 0, "progress_signature": None, "stall_count": 0, "status": "queued", "desired_state": "running", "attempts": 0, "consecutive_failures": 0, "subscription_limit_failures": 0, "max_attempts": 8, "next_eligible_at": None, "last_error": None, "last_error_kind": None, "restart_generation": 0, "created_at": now, "updated_at": now, "started_at": None, "finished_at": None, "last_pid": None, "last_pid_fingerprint": None, "accepted_by_workers": []}


def _validate_discovery(payload: Any) -> dict[str, Any]:
    obj = strict_object(payload, path="$", required={"schema_version", "request_id", "expected_revision", "topic_id", "draft_revision", "draft_hash", "pass_kind", "restated_intent", "criteria", "traceability", "questions"}, optional={"topic_space_findings", "proposed_obligations", "proposed_exclusions"})
    if integer(obj["schema_version"], "$.schema_version") != 1: raise InterfaceError("VALIDATION_ERROR", "$.schema_version", "1", str(obj["schema_version"]), "unsupported schema", "use schema_version 1")
    for field in ("request_id", "topic_id", "draft_hash", "pass_kind", "restated_intent"): nonempty_string(obj[field], "$." + field)
    integer(obj["expected_revision"], "$.expected_revision", minimum=0); integer(obj["draft_revision"], "$.draft_revision", minimum=1)
    if obj["pass_kind"] not in ("criteria", "discovery", "contract_review"): raise InterfaceError("VALIDATION_ERROR", "$.pass_kind", "criteria, discovery, or contract_review", str(obj["pass_kind"]), "unsupported pass kind", "use a documented pass kind")
    for field in ("criteria", "traceability", "questions"):
        if not isinstance(obj[field], list): raise InterfaceError("VALIDATION_ERROR", "$." + field, "array", type(obj[field]).__name__, "field must be an array", "supply an array; use [] when empty")
    if not obj["criteria"]:
        raise InterfaceError("VALIDATION_ERROR", "$.criteria", "findings for criteria 1 through 6", "empty array", "every discovery pass must record each existing criterion", "supply six criterion findings")
    criterion_ids = {str(x.get("id")) for x in obj["criteria"] if isinstance(x, Mapping)}
    if len(obj["criteria"]) != 6 or criterion_ids != {str(i) for i in range(1, 7)}:
        raise InterfaceError("VALIDATION_ERROR", "$.criteria", "exact criterion IDs 1, 2, 3, 4, 5, 6", "invalid records", "criteria must preserve the six existing prompt criteria", "supply one pass/flagged finding for each criterion")
    for index, finding in enumerate(obj["criteria"]):
        if not isinstance(finding, Mapping) or set(finding) != {"id", "status", "explanation"} or not isinstance(finding.get("id"), str) or finding.get("status") not in ("pass", "flagged") or not isinstance(finding.get("explanation"), str) or not finding["explanation"].strip():
            raise InterfaceError("VALIDATION_ERROR", f"$.criteria[{index}]", "{id,status,explanation}; status pass|flagged", type(finding).__name__, "criterion finding is malformed", "supply a structured criterion finding")
    if obj["pass_kind"] == "discovery":
        for field in ("topic_space_findings", "proposed_obligations", "proposed_exclusions"):
            if field not in obj or not isinstance(obj[field], list): raise InterfaceError("VALIDATION_ERROR", "$." + field, "required array for discovery", type(obj.get(field)).__name__, "broad discovery requires this field", "supply the field, using [] only when no findings exist")
    for index, record in enumerate(obj["traceability"]):
        path = f"$.traceability[{index}]"
        entry = strict_object(record, path=path, required={"intent_ref", "contract_ref", "status", "explanation"})
        for key in entry: nonempty_string(entry[key], path + "." + key)
        if entry["status"] not in ("pass", "flagged"):
            raise InterfaceError("VALIDATION_ERROR", path + ".status", "pass or flagged", str(entry["status"]), "unknown traceability status", "use pass or flagged")
    for field in ("topic_space_findings", "proposed_obligations", "proposed_exclusions"):
        if field in obj and not isinstance(obj[field], list):
            raise InterfaceError("VALIDATION_ERROR", "$." + field, "array", type(obj[field]).__name__, "this field must be an array", "use an array, including [] when empty")
    for field in ("questions", "proposed_exclusions"):
        for index, value in enumerate(obj.get(field, [])):
            nonempty_string(value, f"$.{field}[{index}]")
    for field, required in (("topic_space_findings", {"finding", "source_ref"}), ("proposed_obligations", {"text", "source_ref"})):
        for index, value in enumerate(obj.get(field, [])):
            path = f"$.{field}[{index}]"
            record = strict_object(value, path=path, required=required)
            for key in required: nonempty_string(record[key], path + "." + key)
    return dict(obj)


def _validate_intake_decision(payload: Any) -> dict[str, Any]:
    obj = strict_object(payload, path="$", required={"schema_version", "request_id", "expected_revision", "topic_id", "draft_revision", "result_id", "action", "rationale"}, optional={"edits", "position"})
    if integer(obj["schema_version"], "$.schema_version") != 1: raise InterfaceError("VALIDATION_ERROR", "$.schema_version", "1", str(obj["schema_version"]), "unsupported schema", "use schema_version 1")
    for field in ("request_id", "topic_id", "result_id", "rationale"): nonempty_string(obj[field], "$." + field)
    integer(obj["expected_revision"], "$.expected_revision", minimum=0); integer(obj["draft_revision"], "$.draft_revision", minimum=1)
    if obj["action"] not in ("approve", "approve_with_edits", "reject"): raise InterfaceError("VALIDATION_ERROR", "$.action", "approve, approve_with_edits, or reject", str(obj["action"]), "unsupported intake action", "use a documented action")
    if obj["action"] == "approve_with_edits" and not isinstance(obj.get("edits"), Mapping): raise InterfaceError("VALIDATION_ERROR", "$.edits", "complete edited contract object", type(obj.get("edits")).__name__, "approve_with_edits requires complete edits", "supply edits")
    if obj["action"] != "approve_with_edits" and "edits" in obj: raise InterfaceError("VALIDATION_ERROR", "$.edits", "forbidden for this action", type(obj["edits"]).__name__, "only approve_with_edits carries edits", "remove edits")
    if "position" in obj: integer(obj["position"], "$.position", minimum=0)
    return dict(obj)


def operator_dispatch(control: Any, topics_root: Path, *, actor: str) -> dict[str, Callable[[Any], Mapping[str, Any]]]:
    """Controller routing table. ``actor`` comes from authenticated transport."""
    service = IntakeService(control, topics_root, actor=actor)
    def decide(payload: Any) -> Mapping[str, Any]:
        # The checkpoint domain owns proposal/current-version checks and
        # publication semantics.  Keep this transport adapter intentionally thin.
        from .checkpoints.service import apply_decision
        from .input_schema import validate_checkpoint_decision
        from .contract_publication import checkpoint_publisher
        return apply_decision(control, validate_checkpoint_decision(payload), actor=actor, publisher=checkpoint_publisher(topics_root.parent))
    from .control_store import ControlScheduler
    def stations_update(payload: Any) -> Mapping[str, Any]:
        if not isinstance(payload, Mapping):
            raise InterfaceError("VALIDATION_ERROR", "$", "object", type(payload).__name__, "station update must be an object", "supply station update fields")
        allowed = {"station_ids", "all_stations", "primary_profile", "secondary_profile", "intervals", "active_count", "checkpoints"}
        if set(payload) - allowed:
            raise InterfaceError("VALIDATION_ERROR", "$", "known station fields", "unknown fields", "unknown station update field", "remove unknown fields")
        return ControlScheduler(control).update_stations(**dict(payload))
    def stations_show(payload: Any) -> Mapping[str, Any]:
        if payload:
            raise InterfaceError("VALIDATION_ERROR", "$", "empty object", "nonempty object", "stations show takes no fields", "send {}")
        state = control.snapshot()
        topics = state["work"].get("topics", {})
        return {"revision": state["revision"], "configuration": state["configuration"], "effective_checkpoint_profiles": control.effective_checkpoint_profiles(state), "effective_checkpoint_pair": control.resolve_checkpoint_pair(state), "assignments": state["work"].get("assignments", {}), "topic_work": {topic_id: {"research_iterations_completed": value.get("research_iterations_completed"), "next_research_ordinal": value.get("next_research_ordinal"), "review_state": value.get("review_state"), "active_episode_id": value.get("active_episode_id"), "pacing_ready_at": value.get("pacing_ready_at"), "retry_not_before": value.get("retry_not_before")} for topic_id, value in topics.items() if isinstance(value, Mapping)}}
    def queue_reorder(payload: Any) -> Mapping[str, Any]:
        if not isinstance(payload, Mapping) or set(payload) != {"expected_queue_revision", "ordered_ids"}:
            raise InterfaceError("VALIDATION_ERROR", "$", "expected_queue_revision and ordered_ids", type(payload).__name__, "invalid reorder envelope", "supply both fields only")
        return ControlScheduler(control).reorder(payload["ordered_ids"], expected_queue_revision=payload["expected_queue_revision"])
    def profile_register(payload: Any) -> Mapping[str, Any]:
        if not isinstance(payload, Mapping) or set(payload) != {"profile_id", "adapter", "model", "executable", "argv"}:
            raise InterfaceError("VALIDATION_ERROR", "$", "profile_id, adapter, model, executable, argv", type(payload).__name__, "invalid profile envelope", "supply complete profile")
        return control.register_profile(payload["profile_id"], adapter=payload["adapter"], model=payload["model"], executable=payload["executable"], argv=payload["argv"])
    def queue_status(payload: Any) -> Mapping[str, Any]:
        if payload: raise InterfaceError("VALIDATION_ERROR", "$", "empty object", "nonempty object", "status takes no fields", "send {}")
        return control.snapshot()["queue"]
    def queue_pause(payload: Any) -> Mapping[str, Any]:
        obj = strict_object(payload, path="$", required=set(), optional={"topic_id", "reason", "graceful"})
        if "topic_id" in obj: nonempty_string(obj["topic_id"], "$.topic_id")
        if obj.get("reason") is not None: nonempty_string(obj["reason"], "$.reason")
        graceful = obj.get("graceful", True)
        if type(graceful) is not bool:
            raise InterfaceError("VALIDATION_ERROR", "$.graceful", "boolean", type(graceful).__name__, "graceful must be boolean", "supply true or false")
        from .queue import QueueStore
        store = QueueStore(control.root)
        return store.pause_item(obj["topic_id"], obj.get("reason"), graceful=graceful) if "topic_id" in obj else store.pause_all(obj.get("reason"), graceful=graceful)
    def queue_resume(payload: Any) -> Mapping[str, Any]:
        obj = strict_object(payload, path="$", required=set(), optional={"topic_id"})
        if "topic_id" in obj: nonempty_string(obj["topic_id"], "$.topic_id")
        from .queue import QueueStore
        store = QueueStore(control.root)
        return store.resume_item(obj["topic_id"]) if "topic_id" in obj else store.resume_all()
    return {"intake.submit_brief": service.submit_brief, "intake.record_discovery_result": service.record_discovery_result, "intake.approve": service.approve, "checkpoint.decide": decide, "stations.update": stations_update, "stations.show": stations_show, "queue.reorder": queue_reorder, "profiles.register": profile_register, "queue.status": queue_status, "queue.pause": queue_pause, "queue.resume": queue_resume, "queue.pause_all": queue_pause, "queue.resume_all": queue_resume}
