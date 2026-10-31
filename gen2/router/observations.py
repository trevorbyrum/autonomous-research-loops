"""C-13: refuse logical JSON while retaining failed attempted bytes.

Trace: DOSSIER 2d-4b3e1-json2; operator ruling 2026-10-13; H-5/E-2.
Raw text is the original attempted-request document, not reserialized JSON.
Refused documents are opaque: neither a request type nor a page is inferred.
"""
from __future__ import annotations

from typing import Mapping, Protocol

from gen2.core import canonical
from gen2.router import boundary
from gen2.router.boundary import Refusal
from gen2.router.protocols import Rows, Schemas


class ObservationCore(Protocol):
    _schemas: Schemas
    def _guarded(self, reason, body): ...
    _store: Rows[object]
    def _one(self, table: str, where: Mapping[str, object]) -> "dict | None": ...
    def _capability(self, capability_id: str, invocation_id: str) -> dict: ...
    def _require_current_lease(self, inv: dict, now: str, lease_ref: "Mapping | None" = None) -> dict: ...
    def _audit(self, kind: str, at: str, detail: dict, *, topic_id=None, invocation_id=None) -> str: ...


class Observations:
    def __init__(self, core: ObservationCore) -> None:
        self._core = core

    def record_observation(self, request: Mapping) -> dict:
        try:
            handoff = None
            if isinstance(request, Mapping) and isinstance(request.get("observation"), dict):
                attempted = request["observation"].get("request")
                if isinstance(attempted, dict):
                    # Validate the envelope before serializing the attempted object.
                    # Its existing JCS identity names these hand-off bytes; no earlier
                    # wire spelling is available from an already parsed object.
                    handoff = attempted
                    request = {**request, "observation": {**request["observation"], "request": ""}}
            req = boundary.normalize(request, "request_invalid", member_domain=True)
            boundary.require_schema(self._core._schemas, req, "router-commands#/$defs/observation", "request_invalid")
            obs, events = req["observation"], req["retrieval_events"]
            raw = None
            refusal_class = None
            if handoff is not None:
                try:
                    obs["request"] = canonical.canonical_bytes(handoff).decode("utf-8")
                except canonical.CanonicalizationError as exc:
                    raise Refusal("request_invalid", str(exc)) from None
            if isinstance(obs["request"], str):
                original = obs["request"].encode("utf-8")
                try:
                    obs["request"] = canonical.parse_json_strict(original, member_domain=True)
                except (ValueError, RecursionError) as exc:
                    # Includes CanonicalizationError plus the JSON decoder's
                    # own integer-digit and nesting-limit refusals.
                    if (obs["coverage_state"], obs["completeness"], obs["error_class"], obs["page_outcome"], events) != (
                            "unknown", "unobserved", "payload_invalid", "failed", []):
                        raise Refusal("request_invalid", "refused logical JSON records only a failed unobserved attempt")
                    refusal_class = "member_name_domain" if isinstance(exc, canonical.MemberNameError) else "logical_json_invalid"
                    raw = original
                    # SQL 24's historical storage tag is fixed; the actual
                    # first refusal class is recorded separately, without decoding.
                    obs["request"] = {"retained_request": {
                        "bytes_hash": canonical.bytes_digest(raw), "reason": "member_name_domain"}}
            if raw is None and isinstance(obs["request"], dict) and "retained_request" in obs["request"]:
                raise Refusal("request_invalid", "retained_request is reserved for same-row retained bytes")
            obs.update(request_bytes=raw, request_bytes_hash=None if raw is None else canonical.bytes_digest(raw))
            boundary.check_observation(obs, events, request_bytes=raw)
            result = self._core._guarded("payload_invalid", lambda now: self._record(req, now, refusal_class))
            if raw is not None:
                result["request_refusal"] = {"reason": "request_invalid", "class": refusal_class,
                    "detail": "Strict logical JSON refused; exact bytes retained"}
            return result
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}

    def _record(self, req: dict, now: str, refusal_class: str | None) -> dict:
        result = self._in_transaction(req, now)
        if result["status"] == "recorded" and refusal_class is not None:
            self._core._audit("observation_request_refused", now, {
                "observation_id": req["observation"]["observation_id"],
                "request_bytes_hash": req["observation"]["request_bytes_hash"],
                "refusal_class": refusal_class}, invocation_id=req["invocation_id"])
        return result

    def _in_transaction(self, req: dict, now: str) -> dict:
        obs, events = req["observation"], req["retrieval_events"]
        existing = self._core._one("search_observations", {"observation_id": obs["observation_id"]})
        if existing is not None:
            stored_events = self._core._store.select("retrieval_events", {"observation_id": obs["observation_id"]})
            same = (existing["invocation_id"] == req["invocation_id"] and all(existing[k] == v for k, v in obs.items())
                    and sorted((e["event_id"], e["provider_record_id"], e["rank"], e["captured_at"]) for e in stored_events)
                    == sorted((e["event_id"], e["provider_record_id"], e["rank"], e["captured_at"]) for e in events))
            if not same:
                raise Refusal("observation_id_conflict", f"{obs['observation_id']} was recorded with different content")
            return {"status": "replayed", "observation_id": obs["observation_id"], "retrieval_events": len(stored_events)}
        inv = self._core._capability(req["capability_id"], req["invocation_id"])
        if inv["state"] != "running":
            raise Refusal("invocation_state_invalid", f"observations are recorded while running, not {inv['state']}")
        if inv["cancel_requested_at"] is not None:
            raise Refusal("invocation_state_invalid", f"cancellation was requested at {inv['cancel_requested_at']}")
        self._core._require_current_lease(inv, now)
        topic = self._core._one("queue_entries", {"topic_id": inv["topic_id"]})
        if topic["paused_at"] is not None:
            raise Refusal("topic_paused", f"paused at {topic['paused_at']}")
        self._core._store.insert("search_observations", {**obs, "invocation_id": inv["invocation_id"], "topic_id": inv["topic_id"]})
        for event in events:
            self._core._store.insert("retrieval_events", {**event, "observation_id": obs["observation_id"], "topic_id": inv["topic_id"]})
        self._core._audit("observation", now, {"observation_id": obs["observation_id"], "retrieval_events": len(events)},
                    topic_id=inv["topic_id"], invocation_id=inv["invocation_id"])
        return {"status": "recorded", "observation_id": obs["observation_id"], "retrieval_events": len(events)}
