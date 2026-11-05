"""F5/L-6, v7 §2: serialized intent, first result, fixed-U stop (DEBT-052).

Audit facts are append-only authority; no lifecycle/scientific writes. Late
safety retention and provider rejection are 3b. No productive reader is wired.
"""
from typing import Callable, Mapping, Protocol, TYPE_CHECKING

from gen2.core import canonical
from gen2.core.control import DispatchAuthority
from gen2.router import boundary
from gen2.router.boundary import Refusal, instant
from gen2.router.protocols import Rows, Schemas, Spool

if TYPE_CHECKING:
    from gen2.router.amendments import Amendments

TEXT = {"$ref": "common.schema.json#/$defs/short_text"}
HASH = {"$ref": "common.schema.json#/$defs/sha256"}
FIELDS = {"capability_id": TEXT, "invocation_id": TEXT, "run_id": TEXT,
          "attempt": {"$ref": "live-vocabulary.schema.json#/$defs/positive_count"}}
DISPATCH_COMMANDS = {name: {"type": "object", "additionalProperties": False,
    "required": list(fields), "properties": fields} for name, fields in (
        ("dispatch_authorize", FIELDS),
        ("dispatch_result", {**FIELDS, "admission_ref": TEXT, "evidence_ref": HASH}))}
PINS = ("invocation_id", "topic_id", "config_bundle_hash", "job_handle")
RUNTIME_PINS = ("epoch", "manifest_ref", "credential_ref", "route", "backend", "evidence_generation")


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise Refusal(reason, "dispatch authority or admission predicate failed")


class DispatchCore(Protocol):
    _store: Rows[object]
    _schemas: Schemas
    _spool: Spool
    _dispatch_authority: DispatchAuthority | None
    _amendments: "Amendments"
    def _guarded(self, reason: str, body: Callable) -> object: ...
    def _capability(self, capability_id: str, invocation_id: str) -> dict: ...
    def _lease_of(self, inv: dict) -> dict: ...
    def _require_current_lease(self, inv: dict, now: str) -> dict: ...
    def _launch_refusal(self, inv: dict, now: str) -> Refusal | None: ...
    def _one(self, table: str, where: Mapping) -> dict | None: ...
    def _authorize_artifact(self, content_hash: str, inv: dict, now: str) -> None: ...
    def _audit(self, kind: str, at: str, detail: dict, *, topic_id=None, invocation_id=None) -> str: ...


class Dispatch:
    def __init__(self, core: DispatchCore) -> None:
        self._core = core

    def _facts(self, kind: str) -> list[dict]:
        return self._core._store.select("audit_events", {"kind": kind})

    def _intent(self, invocation_id: str) -> dict | None:
        return next((r for r in self._facts("dispatch_authorized") if r["invocation_id"] == invocation_id), None)

    def _read(self, request: Mapping, result: bool = False) -> tuple[dict, dict, dict]:
        req = boundary.normalize(request, "request_invalid")
        target = "dispatch_result" if result else "dispatch_authorize"
        boundary.require_schema(self._core._schemas, req, "router-commands#/$defs/" + target, "request_invalid")
        inv = self._core._capability(req["capability_id"], req["invocation_id"])
        authority = self._core._dispatch_authority
        require(authority is not None, "spend_unbounded")
        supplied = (authority.result(req["admission_ref"], req["evidence_ref"]) if result else
                    authority.admission(inv["invocation_id"], req["run_id"], req["attempt"]))
        require(supplied is not None, "dispatch_origin_invalid" if result else "spend_unbounded")
        doc = boundary.normalize(supplied, "dispatch_origin_invalid")
        require(isinstance(doc, dict) and isinstance(doc.get("origin"), dict), "dispatch_origin_invalid")
        return req, inv, doc

    def _artifacts(self, inv: dict, doc: dict, required: str) -> list[dict]:
        refs = doc.get("artifacts")
        require(isinstance(refs, list) and 0 < len(refs) <= 32, "dispatch_origin_invalid")
        for ref in refs:
            boundary.require_schema(self._core._schemas, ref, "common.schema.json#/$defs/artifact_ref", "dispatch_origin_invalid")
            boundary.staged(self._core._spool, ref["content_hash"], ref["size_bytes"], topic_id=inv["topic_id"], media_type=ref["media_type"])
        require(required in {r["content_hash"] for r in refs}, "dispatch_origin_invalid")
        return refs

    def _register(self, inv: dict, refs: list[dict], now: str) -> None:
        for ref in refs:
            stored = self._core._one("artifacts", {"content_hash": ref["content_hash"]})
            if stored is None:
                self._core._store.insert("artifacts", {**ref, "topic_id": inv["topic_id"], "staged_by_invocation_id": inv["invocation_id"], "staged_at": now})
            else:
                require(all(stored[k] == ref[k] for k in ("size_bytes", "media_type")), "dispatch_origin_invalid")
            self._core._authorize_artifact(ref["content_hash"], inv, now)

    def _predicate(self, doc: dict, now: str, own: str | None = None) -> None:
        require(not self._facts("dispatch_stopped"), "dispatch_trial_stopped")
        policy = doc["policy"]
        require(instant(now) < instant(policy["deadline_at"]), "dispatch_policy_expired")
        results = {r["detail"]["admission_ref"]: r["detail"] for r in self._facts("dispatch_result")}
        require(not any(r["trial_stopped"] for r in results.values()), "dispatch_trial_stopped")
        intents = self._facts("dispatch_authorized")
        require(not any(r["audit_event_id"] != own and r["audit_event_id"] not in results for r in intents), "dispatch_slot_occupied")
        require(all(r["detail"]["policy"]["currency"] == policy["currency"] for r in intents), "spend_unbounded")
        spent = sum(r["charge_minor_units"] for r in results.values())
        require(spent + doc["upper_minor_units"] <= policy["ceiling_minor_units"], "dispatch_ceiling_exceeded")
        require(len(intents) - (own is not None) < policy["max_attempts"], "dispatch_attempts_exhausted")

    def authorize(self, request: Mapping) -> dict:
        try:
            req, inv, doc = self._read(request)
            boundary.require_schema(self._core._schemas, doc.get("policy"), "live-vocabulary.schema.json#/$defs/policy_accounting", "spend_unbounded")
            boundary.require_schema(self._core._schemas, doc.get("upper_minor_units"), "live-vocabulary.schema.json#/$defs/count", "spend_unbounded")
            origin, policy = doc["origin"], doc["policy"]
            require(all(isinstance(origin.get(k), str) and origin[k] for k in RUNTIME_PINS), "dispatch_origin_invalid")
            refs = self._artifacts(inv, doc, origin["manifest_ref"])
            def write(now):
                current = self._core._capability(req["capability_id"], req["invocation_id"])
                lease = self._core._lease_of(current)
                expected = {**{k: current[k] for k in PINS}, "lease_id": lease["lease_id"], "generation": lease["generation"]}
                require(all(origin.get(k) == v for k, v in expected.items()) and current["job_handle"] is not None, "dispatch_origin_invalid")
                require((policy["topic_id"], policy["run_id"], policy["max_concurrent_attempts"]) == (inv["topic_id"], req["run_id"], 1), "spend_unbounded")
                detail = {**doc, "run_id": req["run_id"], "attempt": req["attempt"]}
                prior = self._intent(inv["invocation_id"])
                if prior is not None:
                    require(prior["detail"] == detail, "dispatch_authorization_conflict")
                    return self._authorization(prior, "replayed")
                require(origin["epoch"] == self._core._dispatch_authority.epoch, "dispatch_origin_invalid")
                require(self._core._dispatch_authority.is_current(origin), "spend_unbounded")
                refusal = self._core._launch_refusal(current, now)
                if refusal is not None:
                    raise refusal
                require(current["state"] == "launching", "dispatch_not_startable")
                self._core._amendments._require_current_pins(current)
                self._predicate(doc, now)
                self._register(current, refs, now)
                ref = self._core._audit("dispatch_authorized", now, detail, topic_id=inv["topic_id"], invocation_id=inv["invocation_id"])
                return self._authorization({"audit_event_id": ref, "detail": detail}, "authorized")
            return self._core._guarded("dispatch_refused", write)
        except Refusal as exc:
            return {"status": "refused", "reason": exc.reason, "detail": exc.detail[:500]}

    @staticmethod
    def _authorization(row: dict, status: str) -> dict:
        doc = row["detail"]
        return {"status": status, "admission_ref": row["audit_event_id"], "upper_minor_units": doc["upper_minor_units"],
                "policy_hash": canonical.content_hash(doc["policy"])}

    def stop_uncertain(self, inv: dict, now: str) -> None:
        intent = self._intent(inv["invocation_id"])
        if intent is not None and not any(r["invocation_id"] == inv["invocation_id"] for r in self._facts("dispatch_result") + self._facts("dispatch_stopped")):
            self._core._audit("dispatch_stopped", now, {"admission_ref": intent["audit_event_id"],
                "charge_minor_units": intent["detail"]["upper_minor_units"]}, topic_id=inv["topic_id"], invocation_id=inv["invocation_id"])

    def start_refusal(self, inv: dict, now: str) -> Refusal | None:
        try:
            prior = self._intent(inv["invocation_id"])
            if prior is None:
                return None  # existing non-live lifecycle; isolation gate remains closed
            require(self._core._dispatch_authority is not None, "dispatch_origin_invalid")
            require(prior["detail"]["origin"]["epoch"] == self._core._dispatch_authority.epoch, "dispatch_origin_invalid")
            require(self._core._dispatch_authority.is_current(prior["detail"]["origin"]), "spend_unbounded")
            require(not any(r["invocation_id"] == inv["invocation_id"] for r in self._facts("dispatch_result")), "dispatch_already_ended")
            self._predicate(prior["detail"], now, own=prior["audit_event_id"])
        except Refusal as exc:
            return exc
        return None

    def record(self, request: Mapping) -> dict:
        try:
            req, inv, doc = self._read(request, result=True)
            require(doc.get("admission_ref") == req["admission_ref"] and doc.get("evidence_ref") == req["evidence_ref"], "dispatch_origin_invalid")
            require(type(doc.get("confirmed_end")) is bool, "dispatch_origin_invalid")
            actual = doc.get("actual_minor_units")
            if actual is not None:
                boundary.require_schema(self._core._schemas, actual, "live-vocabulary.schema.json#/$defs/count", "dispatch_origin_invalid")
            refs = self._artifacts(inv, doc, req["evidence_ref"])
            def write(now):
                current = self._core._capability(req["capability_id"], req["invocation_id"])
                intent = self._intent(inv["invocation_id"])
                require(intent is not None and intent["audit_event_id"] == req["admission_ref"], "dispatch_origin_invalid")
                original = intent["detail"]
                require((req["run_id"], req["attempt"], doc["origin"]) == (original["run_id"], original["attempt"], original["origin"]), "dispatch_origin_invalid")
                prior = next((r for r in self._facts("dispatch_result") if r["invocation_id"] == inv["invocation_id"]), None)
                if prior is not None:
                    require(prior["detail"]["evidence"] == doc, "dispatch_result_conflict")
                    return {"status": "replayed", **prior["detail"]["response"]}
                require(not any(r["invocation_id"] == inv["invocation_id"] for r in self._facts("dispatch_stopped")), "dispatch_result_not_current")
                # 3a accepts only the current first-result branch. 3b adds late safety retention.
                self._core._require_current_lease(current, now)
                require(current["state"] in ("launching", "running", "result_ready"), "dispatch_result_not_current")
                require(original["origin"]["epoch"] == self._core._dispatch_authority.epoch, "dispatch_result_not_current")
                self._core._amendments._require_current_pins(current)
                known = doc["confirmed_end"] and actual is not None
                charge = actual if known else original["upper_minor_units"]
                stopped = not known or charge > original["upper_minor_units"]
                response = {"charge_state": "actual" if known else "worst_case", "trial_stopped": stopped}
                self._register(current, refs, now)
                self._core._audit("dispatch_result", now, {"admission_ref": req["admission_ref"], "evidence": doc,
                    "charge_minor_units": charge, "trial_stopped": stopped, "response": response},
                    topic_id=inv["topic_id"], invocation_id=inv["invocation_id"])
                return {"status": "recorded", **response}
            return self._core._guarded("dispatch_refused", write)
        except Refusal as exc:
            return {"status": "refused", "reason": exc.reason, "detail": exc.detail[:500]}
