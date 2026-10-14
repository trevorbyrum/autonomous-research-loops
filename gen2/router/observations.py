"""C-13: refuse logical member names while retaining failed attempted bytes.

Trace: DOSSIER 2d-4b3e1-json2; operator ruling 2026-10-13; H-5/E-2.
Raw text is the original attempted-request document, not reserialized JSON.
Only its request-type label is decoded for the failed observation descriptor;
that label confers no acquisition, content or support authority.
"""
from __future__ import annotations

import json
from typing import Mapping, Protocol

from gen2.core import canonical, pagination
from gen2.router import boundary
from gen2.router.boundary import Refusal


class Schemas(Protocol):
    def errors(self, instance: object, target: str) -> list[str]: ...


class ObservationCore(Protocol):
    _schemas: Schemas
    def _guarded(self, reason, body): ...
    def _observation_in_transaction(self, req: dict, now: str) -> dict: ...


class Observations:
    def __init__(self, core: ObservationCore) -> None:
        self._core = core

    def record_observation(self, request: Mapping) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid", member_domain=True)
            boundary.require_schema(self._core._schemas, req, "router-commands#/$defs/observation", "request_invalid")
            obs, events = req["observation"], req["retrieval_events"]
            raw = None
            if isinstance(obs["request"], str):
                original = obs["request"].encode("utf-8")
                try:
                    obs["request"] = canonical.parse_json_strict(original, member_domain=True)
                except canonical.MemberNameError:
                    kind = pagination.request_type(json.loads(original))
                    if kind is None:
                        raise Refusal("request_invalid", "retained request needs a known request type")
                    if (obs["coverage_state"], obs["completeness"], obs["error_class"], obs["page_outcome"], events) != (
                            "unknown", "unobserved", "payload_invalid", "failed", []):
                        raise Refusal("request_invalid", "a refused member domain records only a failed unobserved attempt")
                    raw = original
                    obs["request"] = {"request": {"request_type": kind}, "retained_request": {
                        "bytes_hash": canonical.bytes_digest(raw), "reason": "member_name_domain"}}
                except canonical.CanonicalizationError as exc:
                    raise Refusal("request_invalid", str(exc)) from None
            boundary.check_observation(obs, events, request_bytes=raw)
            obs.update(request_bytes=raw, request_bytes_hash=None if raw is None else canonical.bytes_digest(raw))
            result = self._core._guarded("payload_invalid", lambda now: self._core._observation_in_transaction(req, now))
            if raw is not None:
                result["request_refusal"] = {"reason": "request_invalid", "detail": "JSON member-name domain refused; exact bytes retained"}
            return result
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}
