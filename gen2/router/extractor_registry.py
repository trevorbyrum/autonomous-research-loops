"""Operator-approved immutable extractor snapshots; DOSSIER 2d-4b3e2, V-3.

Recorded identity is a declaration; execution checking remains station work.
"""
from typing import Callable, Mapping, Protocol

from gen2.router import boundary
from gen2.router.boundary import Refusal

NAME = {"type": "string", "pattern": "^[a-z][a-z0-9._-]{0,99}$"}
EXTRACTOR_COMMANDS = {"extractor_registry": {
    "type": "object", "additionalProperties": False,
    "required": ["registry_version", "operator_id", "reason", "tools"],
    "properties": {
        "registry_version": {"type": "integer", "minimum": 1, "maximum": 9007199254740991},
        "operator_id": {"$ref": "common.schema.json#/$defs/short_text"},
        "reason": {"$ref": "common.schema.json#/$defs/short_text"},
        "tools": {"type": "array", "minItems": 1, "maxItems": 1000, "items": {
            "type": "object", "additionalProperties": False, "required": ["extractor_identity", "family"],
            "properties": {"extractor_identity": NAME, "family": NAME}}}}}}


class Rows(Protocol):
    def select(self, table: str, where: Mapping[str, object] | None = None) -> list[dict]: ...
    def insert(self, table: str, row: Mapping[str, object]) -> None: ...


class Schemas(Protocol):
    def errors(self, instance: object, target: str) -> list[str]: ...


class ExtractorRegistryCore(Protocol):
    _store: Rows
    _schemas: Schemas
    def _one(self, table: str, where: Mapping[str, object]) -> dict | None: ...
    def _guarded(self, reason: str, body: Callable[[str], object]) -> object: ...
    def _audit(self, kind: str, at: str, detail: dict, *, topic_id=None, invocation_id=None, operation_id=None) -> str: ...


class ExtractorRegistry:
    def __init__(self, core: ExtractorRegistryCore) -> None:
        self._core = core

    def register(self, request: Mapping) -> dict:
        try:
            doc = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._core._schemas, doc, "router-commands#/$defs/extractor_registry", "request_invalid")
            tools = doc["tools"]
            if len({t["extractor_identity"] for t in tools}) != len(tools):
                raise Refusal("request_invalid", "duplicate canonical extractor identity")
            doc["tools"] = sorted(tools, key=lambda t: t["extractor_identity"])
            return self._core._guarded("registry_refused", lambda now: self._write(doc, now))
        except Refusal as refusal:
            return {"status": "rejected", "reason": refusal.reason, "detail": refusal.detail}

    def _write(self, doc: dict, now: str) -> dict:
        version = doc["registry_version"]
        stored = self._core._one("extractor_registry_revisions", {"registry_version": version})
        if stored is not None:
            audit = self._core._one("audit_events", {"audit_event_id": stored["audit_event_id"]})
            if audit["detail"] != doc:
                raise Refusal("registry_refused", "registry revision has different approved content")
            return {"status": "replayed", "registry_version": version}
        if version <= max((r["registry_version"] for r in self._core._store.select("extractor_registry_revisions")), default=0):
            raise Refusal("registry_refused", "registry revisions must increase")
        audit_id = self._core._audit("extractor_registry_registered", now, doc)
        self._core._store.insert("extractor_registry_revisions", {"registry_version": version,
            "operator_id": doc["operator_id"], "reason": doc["reason"], "audit_event_id": audit_id, "created_at": now})
        for tool in doc["tools"]:
            self._core._store.insert("extractor_tools", {"registry_version": version, **tool})
        return {"status": "registered", "registry_version": version}

    def require_tool(self, record: dict) -> None:
        if self._core._one("extractor_tools", {"registry_version": record.get("extractor_registry_version"),
                "extractor_identity": record["extractor_identity"]}) is None:
            raise Refusal("payload_invalid", "extraction needs an exact registered tool and registry revision")
