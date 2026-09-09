"""Strict, transport-independent validation for controller input envelopes.

The JSON schemas are the public contract.  This small validator deliberately
keeps errors JSON-able so CLI and MCP can return the identical diagnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass
class InterfaceError(ValueError):
    code: str
    path: str
    expected: str
    received: str
    explanation: str
    next_operation: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "expected": self.expected,
                "received": self.received, "explanation": self.explanation,
                "next_operation": self.next_operation}

    def __str__(self) -> str:
        return f"{self.code} at {self.path}: {self.explanation}"


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def _error(path: str, expected: str, value: Any, explanation: str, next_operation: str) -> None:
    raise InterfaceError("VALIDATION_ERROR", path, expected, _kind(value), explanation, next_operation)


def strict_object(value: Any, *, path: str, required: set[str], optional: set[str] = frozenset()) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _error(path, "object", value, "a JSON object is required", "submit a JSON object matching the schema")
    unknown = sorted(set(value) - required - optional)
    if unknown:
        _error(f"{path}.{unknown[0]}", "no unknown fields", value[unknown[0]], "unknown fields are rejected", "remove the unknown field")
    missing = sorted(required - set(value))
    if missing:
        _error(f"{path}.{missing[0]}", "required field", None, "the field is required", "supply the missing field")
    return value


def nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _error(path, "non-empty string", value, "a non-empty string is required", "supply a non-empty string")
    return value.strip()


def integer(value: Any, path: str, *, minimum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _error(path, "integer", value, "booleans are not integers", "supply an integer")
    if minimum is not None and value < minimum:
        _error(path, f"integer >= {minimum}", value, "value is below the allowed minimum", "increase the value")
    return value


def validate_envelope(value: Any, *, editable: bool) -> Mapping[str, Any]:
    required = {"schema_version", "request_id"}
    if editable:
        required.add("expected_revision")
    obj = strict_object(value, path="$", required=required, optional=set(value.keys()) - required if isinstance(value, Mapping) else set())
    if integer(obj["schema_version"], "$.schema_version") != 1:
        _error("$.schema_version", "supported schema version 1", obj["schema_version"], "schema version is unsupported", "use schema_version 1")
    nonempty_string(obj["request_id"], "$.request_id")
    if editable:
        integer(obj["expected_revision"], "$.expected_revision", minimum=0)
    return obj


DECISION_ACTIONS = frozenset(("approve", "approve_with_edits", "reject"))


def validate_checkpoint_decision(value: Any) -> dict[str, Any]:
    obj = strict_object(value, path="$", required={"schema_version", "request_id", "expected_revision", "topic_id", "episode_id", "decisions"})
    if integer(obj["schema_version"], "$.schema_version") != 1:
        _error("$.schema_version", "supported schema version 1", obj["schema_version"], "schema version is unsupported", "use schema_version 1")
    nonempty_string(obj["request_id"], "$.request_id")
    integer(obj["expected_revision"], "$.expected_revision", minimum=0)
    nonempty_string(obj["topic_id"], "$.topic_id")
    nonempty_string(obj["episode_id"], "$.episode_id")
    decisions = obj["decisions"]
    if not isinstance(decisions, list) or not decisions:
        _error("$.decisions", "non-empty array", decisions, "at least one proposal decision is required", "supply one decision per proposal to resolve")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(decisions):
        path = f"$.decisions[{index}]"
        decision = strict_object(item, path=path, required={"proposal_id", "proposal_version", "action", "reason"}, optional={"edits"})
        proposal_id = nonempty_string(decision["proposal_id"], path + ".proposal_id")
        if proposal_id in seen:
            _error(path + ".proposal_id", "unique proposal id", proposal_id, "a proposal may appear once", "remove the duplicate decision")
        seen.add(proposal_id)
        integer(decision["proposal_version"], path + ".proposal_version", minimum=1)
        action = decision["action"]
        if action not in DECISION_ACTIONS:
            _error(path + ".action", "approve, approve_with_edits, or reject", action, "unsupported decision action", "use one of the documented actions")
        nonempty_string(decision["reason"], path + ".reason")
        edits = decision.get("edits")
        if action == "approve_with_edits" and not isinstance(edits, Mapping):
            _error(path + ".edits", "complete change object", edits, "approve_with_edits requires structured final edits", "supply the complete edited change object")
        if action != "approve_with_edits" and "edits" in decision:
            _error(path + ".edits", "field forbidden for this action", edits, "only approve_with_edits may carry edits", "remove edits or use approve_with_edits")
        normalized.append(dict(decision))
    return {key: obj[key] for key in ("schema_version", "request_id", "expected_revision", "topic_id", "episode_id")} | {"decisions": normalized}
