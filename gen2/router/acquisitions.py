"""Trusted fixture re-access admission; no tier or extraction authority.

Flow S4 step 8, BOUNDARIES Router, V-1/V-3, C-8. Capture reads and pure
validation precede the writer fence. SQL 14 retains exact operands and lineage.
"""
from dataclasses import asdict
from typing import TYPE_CHECKING, Callable, Mapping, Protocol

from gen2.core import canonical
from gen2.core.gateway_capture import CaptureReader, RetainedExchange
from gen2.router import boundary, reaccess
from gen2.router.boundary import Refusal
from gen2.router.protocols import Rows, Schemas

if TYPE_CHECKING:
    from gen2.router.amendments import Amendments

ACQUISITION_COMMANDS = {"reaccess": {"type": "object", "additionalProperties": False,
    "required": ["capability_id", "invocation_id", "work_id", "source_version", "event_id"],
    "properties": {key: {"$ref": "common.schema.json#/$defs/short_text"}
        for key in ("capability_id", "invocation_id", "work_id", "source_version", "event_id")}}}


class AcquisitionCore(Protocol):
    _store: Rows[object]
    _schemas: Schemas
    _gateway_captures: CaptureReader | None
    def _one(self, table: str, where: Mapping[str, object]) -> dict | None: ...
    def _snapshot(self): ...
    def _capability(self, capability_id: str, invocation_id: str) -> dict: ...
    def _guarded(self, reason: str, body: Callable[[str], object]) -> object: ...
    def _require_current_lease(self, inv: dict, now: str) -> dict: ...
    _amendments: "Amendments"
    def _fault(self, point: str) -> None: ...
    def _audit(self, kind: str, at: str, detail: dict, *, topic_id=None, invocation_id=None) -> str: ...


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise Refusal("reaccess_invalid", reason)


class AcquisitionAdmission:
    def __init__(self, core: AcquisitionCore) -> None:
        self._core = core

    def _row(self, table: str, **key) -> dict:
        row = self._core._one(table, key)
        require(row is not None, "recorded acquisition operand missing: " + table)
        return row

    def _operands(self, req: dict, inv: dict) -> dict:
        source = self._row("source_artifacts", topic_id=inv["topic_id"], work_id=req["work_id"], source_version=req["source_version"])
        artifact = self._row("artifacts", content_hash=source["content_hash"])
        event = self._row("retrieval_events", event_id=req["event_id"])
        observation = self._row("search_observations", observation_id=event["observation_id"])
        link = self._row("record_work_links", event_id=event["event_id"])
        return dict(source=source, artifact=artifact, event=event, observation=observation, link=link)

    def admit(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._core._schemas, req, "router-commands#/$defs/reaccess", "request_invalid")
            with self._core._snapshot():
                inv = self._core._capability(req["capability_id"], req["invocation_id"])
                operands = self._operands(req, inv)
            obs = operands["observation"]
            require(self._core._gateway_captures is not None, "trusted capture reader unavailable")
            capture = self._core._gateway_captures.read(topic_id=inv["topic_id"], invocation_id=obs["invocation_id"],
                attempt=obs["attempt"], gateway_call_ref=obs["gateway_call_ref"])
            require(isinstance(capture, RetainedExchange), "trusted capture missing")
            require(capture.topic_id == inv["topic_id"], "trusted capture topic")
            require(capture.invocation_id == obs["invocation_id"], "trusted capture invocation")
            require(type(capture.attempt) is int and capture.attempt == obs["attempt"], "trusted capture attempt")
            require(capture.gateway_call_ref == obs["gateway_call_ref"], "trusted capture call")
            require(type(capture.request_bytes) is bytes, "trusted request bytes")
            require(capture.request_bytes == canonical.canonical_bytes(obs["request"]), "trusted capture request")
            require(type(capture.response_bytes) is bytes, "trusted response bytes")
            result = reaccess.check_reaccess(**operands, raw=capture.response_bytes)
            row = {**asdict(result), "verifier_invocation_id": inv["invocation_id"],
                "request_identity": obs["request_identity"], "request_bytes": capture.request_bytes, "response_bytes": capture.response_bytes}
            return self._core._guarded("reaccess_invalid", lambda now: self._write(req, operands, row, now))
        except reaccess.ReaccessRefused as exc:
            return {"status": "refused", "reason": "reaccess_invalid", "detail": str(exc)}
        except Refusal as exc:
            return {"status": "refused", "reason": exc.reason, "detail": exc.detail[:500]}

    def _write(self, req: dict, operands: dict, row: dict, now: str) -> dict:
        inv = self._core._capability(req["capability_id"], req["invocation_id"])
        require(self._operands(req, inv) == operands, "acquisition operands changed")
        key = {k: row[k] for k in ("topic_id", "work_id", "source_version", "event_id", "verifier_invocation_id")}
        existing = self._core._one("source_acquisitions", key)
        if existing is not None:
            require(all(existing[k] == v for k, v in row.items()), "acquisition replay conflict")
            return {"status": "replayed", **key}
        require(inv["kind"] == "verification" and inv["admission_context"] == "contract/1", "contract-admitted verifier required")
        require(inv["state"] == "running" and inv["cancel_requested_at"] is None, "live verifier required")
        self._core._require_current_lease(inv, now)
        self._core._amendments._require_current_pins(inv)
        topic = self._row("queue_entries", topic_id=inv["topic_id"])
        require(topic["paused_at"] is None, "topic paused")
        self._core._store.insert("source_acquisitions", {**row, "admitted_at": now})
        self._core._fault("reaccess_written")
        self._core._audit("reaccess", now, key, topic_id=inv["topic_id"], invocation_id=inv["invocation_id"])
        return {"status": "admitted", **key}
