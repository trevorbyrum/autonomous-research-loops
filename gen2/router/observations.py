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


class Schemas(Protocol):
    def errors(self, instance: object, target: str) -> list[str]: ...


class ObservationCore(Protocol):
    _schemas: Schemas
    def _guarded(self, reason, body): ...
    def _observation_in_transaction(self, req: dict, now: str) -> dict: ...
    def _audit(self, kind: str, at: str, detail: dict, *, invocation_id=None) -> str: ...


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
        result = self._core._observation_in_transaction(req, now)
        if result["status"] == "recorded" and refusal_class is not None:
            self._core._audit("observation_request_refused", now, {
                "observation_id": req["observation"]["observation_id"],
                "request_bytes_hash": req["observation"]["request_bytes_hash"],
                "refusal_class": refusal_class}, invocation_id=req["invocation_id"])
        return result
