"""The registries the router keeps (task 1d): engine configuration bundles, the
question registry they carry, and qualification records. A collaborator of
service.Router (task 2q-b3: "Router composition", BOUNDARIES.md), with the
router's one shape: validate outside any transaction, then one short
transaction (the core's: `_guarded`) that fences and writes.

Trace: design review §4 (execution policy is the engine's mounted policy
bundle, owned apart from the scientific protocol), §6 ("mounted, validated
and activated as versioned bundles. In-flight work retains its pinned
bundle"); DEPLOYMENT-CONTRACT.md §2 (an invalid bundle is refused with a
dated capability fact and the previous bundle stays active); flow §2, §3
step 6, §5 (the versioned question registry; qualification per provider,
class and DecisionSpec, re-derived from its records); BOUNDARIES.md Router,
Decision layer; INVARIANTS G-10, RG-9, C-12, D-1, D-4, D-5, D-7, D-11, H-2,
§13 (Phase 1: loading, pinning and restart retention of the question
registry with fake or disabled providers; fake qualification and revocation
records exercising the authority fences).

Config bundles (config-bundle/1): activation validates the document, takes
its JCS hash as its identity (computed here, never a caller's label),
registers the questions it carries, and makes it the one active bundle,
superseding the last. New work pins the active bundle (the claim names it);
admitted work keeps the bundle it was admitted under, which stays recorded
and resolvable, so its policy survives a restart and a later activation
(RG-9). A refused bundle leaves the active one as it was and raises a dated
capability fact, on the transition only (H-2); the next activation that
succeeds — a new bundle, or the active one mounted again (a replay) — or a
start with nothing mounted restoring the active one records the recovery,
the failure staying in the fact history.

Templates (task 2a): the obligation and method-design templates contract
drafts are checked against (amendments.py). As with questions, a (template
id, version) has one content forever: a bundle naming a recorded one with
other content is refused (template_altered).

Questions: a (question id, version) has one content forever, the entry's
content hash (C-13). A DecisionSpec resolves against the registry when it is
stored (DDL decision_specs_question_registered) and, when a decision is
committed under it, against the committing invocation's pinned bundle: an
unknown question, another version's hash, or a question the pinned bundle
does not carry is refused.

Qualifications: a record qualifies exactly one (provider, decision class,
DecisionSpec). Revocation is recorded once and is final, and takes effect
for every commit after it: a qualified decision is checked against the live
record when validated and again under the commit's write lock, and the DDL
refuses it a third time (decision_receipts_qualification_live). Receipts
already committed are never reinterpreted (D-4). Phase 1 records are fakes:
nothing here runs a provider or an evaluation (D-7); real evaluations,
population provenance and the qualification-change audit are Phase 3.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Callable, Mapping, Protocol

from gen2.core import canonical
from gen2.router import boundary
from gen2.router.boundary import Refusal

ROUTER_DEFAULTS = {"hold_window_s": 3600.0}  # the router's shipped policy (G-10); a bundle's router section overrides it
BUNDLE_CAPABILITY = "config-bundle"

_ID = {"$ref": "common.schema.json#/$defs/short_text"}
_QUAL = {"type": "string", "pattern": "^qual_[A-Za-z0-9_-]{8,64}$"}
REGISTRY_COMMANDS = {
    "qualification": {
        "type": "object", "additionalProperties": False,
        "required": ["qualification_id", "provider", "decision_class", "spec_hash", "evaluation_ref", "operator_id"],
        "properties": {"qualification_id": _QUAL, "provider": {"enum": ["jev", "llm_fallback"]},
                       "decision_class": {"$ref": "common.schema.json#/$defs/decision_class"},
                       "spec_hash": {"$ref": "common.schema.json#/$defs/sha256"}, "evaluation_ref": _ID, "operator_id": _ID}},
    "revocation": {
        "type": "object", "additionalProperties": False, "required": ["qualification_id", "operator_id", "reason"],
        "properties": {"qualification_id": _QUAL, "operator_id": _ID, "reason": _ID}},
}


class Rows(Protocol):
    """The router's store as the registries use it (store/api.py Store): inside the core's transaction."""
    def select(self, table: str, where: Mapping[str, object] | None = None) -> list[dict]: ...
    def insert(self, table: str, row: Mapping[str, object]) -> None: ...
    def update(self, table: str, key: Mapping[str, object], changes: Mapping[str, object]) -> None: ...


class Schemas(Protocol):
    """The router's schema set as boundary.require_schema uses it (schemas.py SchemaSet)."""
    def errors(self, instance: object, target: str) -> list[str]: ...


class RegistriesCore(Protocol):
    """What the registries take of the router core, and nothing else; service.Router
    implements it without inheriting it. Every member is the core's own (service.py).
    The registries' own members the rest of the Router reads (`_active_bundle`,
    `_bundle`, `_router_policy`, `_templates`, `is_qualified`) are the core's delegating
    members, so no other mixin or collaborator reaches the registries but through the core."""
    _store: Rows
    _schemas: Schemas
    _new_id: Callable[[str], str]
    def _now(self) -> str: ...
    def _one(self, table: str, where: Mapping[str, object]) -> dict | None: ...
    def _guarded(self, reason: str, body: Callable[[str], object]) -> object: ...  # the one transaction an operation runs in
    def _audit(self, kind: str, at: str, detail: dict, *, topic_id=None, invocation_id=None, operation_id=None) -> str: ...
    def _transaction(self) -> AbstractContextManager: ...  # the two writes that are not _guarded's: see the note on Registries


class Registries:
    """Two writes here are not made inside `_guarded` but in a transaction of their own, as they were when this was a mixin, now the one the core hands out
    (`_core._transaction()`): the dated fact a refused bundle leaves (a store error there propagates as it is; it is not a second refusal) and a start's
    recovery fact (the clock is read only when there is an active bundle). Every other write is inside `_guarded`."""

    def __init__(self, core: RegistriesCore) -> None:
        self._core = core

    # -- config bundles --------------------------------------------------------
    def activate_config_bundle(self, document: Mapping) -> dict:
        """Record and activate one config-bundle/1 document (trusted surface:
        the composition root at start, 1e's operator surface later). The same
        active bundle again is a replay."""
        try:
            doc = boundary.normalize(document, "bundle_invalid")
            boundary.require_schema(self._core._schemas, doc, "config-bundle.schema.json", "bundle_invalid")
            keys = [(q["question_id"], q["version"]) for q in doc["questions"]]
            if len(set(keys)) != len(keys):
                raise Refusal("bundle_invalid", "a question version appears twice")
            for q in doc["questions"]:
                if canonical.content_hash(q) != q["content_hash"]:
                    raise Refusal("bundle_invalid", f"question {q['question_id']} v{q['version']} does not hash to its content hash (C-13)")
            for kind, entries in doc.get("templates", {}).items():  # task 2a: the template registry
                if len({(t["template_id"], t["template_version"]) for t in entries}) != len(entries):
                    raise Refusal("bundle_invalid", f"a {kind} template version appears twice")
            bundle_hash = canonical.logical_hash(doc)
            return self._core._guarded("bundle_invalid", lambda now: self._activate_in_transaction(doc, bundle_hash, now))
        except Refusal as refusal:
            with self._core._transaction():  # the active bundle stays; the refusal is a dated fact, on the transition (H-2)
                self._fact(BUNDLE_CAPABILITY, "failing", f"{refusal.reason}: {refusal.detail}"[:500], self._core._now())
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}

    def _activate_in_transaction(self, doc: dict, bundle_hash: str, now: str) -> dict:
        stored = self._core._one("config_bundles", {"bundle_hash": bundle_hash})
        if stored is not None:
            if stored["status"] != "active":
                raise Refusal("bundle_superseded", f"version {doc['version']} was superseded; a superseded bundle is never reactivated")
            # the usable bundle mounted again: a failure since is recovered from (a transition only, H-2; the failure stays history)
            self._fact(BUNDLE_CAPABILITY, "healthy", f"bundle version {doc['version']} active", now)
            return {"status": "replayed", "bundle_hash": bundle_hash, "version": doc["version"]}
        recorded = self._core._store.select("config_bundles", {})
        newest = max((b["version"] for b in recorded), default=0)
        if doc["version"] <= newest:
            raise Refusal("bundle_invalid", f"version {doc['version']} is not above the newest recorded bundle's {newest}")
        for q in doc["questions"]:
            row = self._core._one("questions", {"question_id": q["question_id"], "version": q["version"]})
            if row is not None and row["content_hash"] != q["content_hash"]:
                raise Refusal("question_altered", f"{q['question_id']} v{q['version']} is registered with another content; a rewording is a new version (D-4)")
        for kind, entries in doc.get("templates", {}).items():  # a template version has one content forever, as a question version does
            for t, b in ((t, b) for t in entries for b in recorded):
                was = next((x for x in b["document"].get("templates", {}).get(kind, ()) if (x["template_id"], x["template_version"]) == (t["template_id"], t["template_version"])), t)
                if canonical.canonical_bytes(was) != canonical.canonical_bytes(t):
                    raise Refusal("template_altered", f"{kind} template {t['template_id']} v{t['template_version']} is registered with another content; a change is a new version")
        active = next((b for b in recorded if b["status"] == "active"), None)
        if active is not None:
            self._core._store.update("config_bundles", {"bundle_hash": active["bundle_hash"]}, {"status": "superseded"})
        self._core._store.insert("config_bundles", {"bundle_hash": bundle_hash, "version": doc["version"], "document": doc, "status": "active", "activated_at": now})
        for q in doc["questions"]:
            if self._core._one("questions", {"question_id": q["question_id"], "version": q["version"]}) is None:
                self._core._store.insert("questions", {"question_id": q["question_id"], "version": q["version"], "content_hash": q["content_hash"],
                                                       "document": q, "registered_by_bundle_hash": bundle_hash, "registered_at": now})
        self._fact(BUNDLE_CAPABILITY, "healthy", f"bundle version {doc['version']} active", now)
        superseded = None if active is None else active["bundle_hash"]
        self._core._audit("config_bundle_activated", now, {"bundle_hash": bundle_hash, "version": doc["version"], "superseded": superseded})
        return {"status": "activated", "bundle_hash": bundle_hash, "version": doc["version"], "superseded": superseded}

    def config_bundle(self, bundle_hash: str) -> dict | None:
        """A recorded bundle's document (a pin resolves, whether active or not).
        Reading it authorizes nothing."""
        row = self._core._one("config_bundles", {"bundle_hash": bundle_hash})
        return None if row is None else row["document"]

    def restore_config_bundle(self) -> str | None:
        """What a start with nothing mounted runs under (trusted surface: the
        composition root): the active bundle's hash, None before any is
        activated. Restoring the usable active bundle, like mounting it again,
        records the recovery from a refusal since, once (H-2; Astra 1d-repair
        review finding 2): the failure stays history."""
        with self._core._transaction():
            active = self._active_bundle()
            if active is not None:
                self._fact(BUNDLE_CAPABILITY, "healthy", f"bundle version {active['version']} active (restored)", self._core._now())
        return None if active is None else active["bundle_hash"]

    def _bundle(self, bundle_hash: str) -> dict:
        return self._core._one("config_bundles", {"bundle_hash": bundle_hash})["document"]

    def _router_policy(self, bundle_hash: str) -> dict:
        """The router's policy under a pinned bundle: its router section over the shipped defaults (G-10)."""
        return {**ROUTER_DEFAULTS, **self._bundle(bundle_hash)["policy"].get("router", {})}

    def _active_bundle(self) -> dict | None:
        return self._core._one("config_bundles", {"status": "active"})

    def _templates(self) -> dict:
        """The active bundle's template registry (task 2a); none registered while no bundle names any."""
        active = self._active_bundle()
        return {} if active is None else active["document"].get("templates", {})

    def _fact(self, capability: str, state: str, detail: str, now: str) -> None:
        """A dated capability fact, recorded on a transition only (H-2): a state
        other than the current one; healthy only as a recovery from another."""
        current = next((f for f in self._core._store.select("capability_facts", {"capability": capability}) if f["superseded_by_fact_id"] is None), None)
        if (current["state"] if current is not None else "healthy") == state:
            return
        fact_id = self._core._new_id("fact_")
        if current is not None:
            self._core._store.update("capability_facts", {"fact_id": current["fact_id"]}, {"superseded_by_fact_id": fact_id})
        self._core._store.insert("capability_facts", {"fact_id": fact_id, "capability": capability, "state": state, "detail": detail, "since": now,
                                                      "affected_lanes": [], "recorded_at": now})

    # -- qualifications --------------------------------------------------------
    def record_qualification(self, request: Mapping) -> dict:
        return self._registry_command(request, "qualification", self._qualify_in_transaction)

    def revoke_qualification(self, request: Mapping) -> dict:
        return self._registry_command(request, "revocation", self._revoke_in_transaction)

    def _registry_command(self, request: Mapping, shape: str, body) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._core._schemas, req, f"router-commands#/$defs/{shape}", "request_invalid")
            return self._core._guarded("request_invalid", lambda now: body(req, now))
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}

    def _qualify_in_transaction(self, req: dict, now: str) -> dict:
        grant = {k: req[k] for k in ("provider", "decision_class", "spec_hash", "evaluation_ref")}
        row = self._core._one("qualifications", {"qualification_id": req["qualification_id"]})
        if row is not None:
            if {k: row[k] for k in grant} != grant or row["granted_by"] != req["operator_id"]:
                raise Refusal("qualification_conflict", f"{req['qualification_id']} was recorded for another grant")
            return {"status": "replayed", "qualification_id": req["qualification_id"]}
        spec = self._core._one("decision_specs", {"spec_hash": req["spec_hash"]})
        if spec is None or (spec["provider"], spec["decision_class"]) != (req["provider"], req["decision_class"]):
            raise Refusal("qualification_invalid", "a qualification is of a stored DecisionSpec, for exactly its provider and class (D-4)")
        self._core._store.insert("qualifications", {"qualification_id": req["qualification_id"], **grant, "granted_by": req["operator_id"], "granted_at": now})
        self._core._audit("qualification_recorded", now, {"qualification_id": req["qualification_id"], **grant})
        return {"status": "recorded", "qualification_id": req["qualification_id"]}

    def _revoke_in_transaction(self, req: dict, now: str) -> dict:
        row = self._core._one("qualifications", {"qualification_id": req["qualification_id"]})
        if row is None:
            raise Refusal("unknown_qualification", req["qualification_id"])
        if row["revoked_at"] is not None:
            if (row["revoked_by"], row["revoke_reason"]) != (req["operator_id"], req["reason"]):
                raise Refusal("qualification_conflict", f"{req['qualification_id']} was revoked at {row['revoked_at']} otherwise")
            return {"status": "replayed", "qualification_id": req["qualification_id"]}
        self._core._store.update("qualifications", {"qualification_id": req["qualification_id"]},
                                 {"revoked_by": req["operator_id"], "revoked_at": now, "revoke_reason": req["reason"]})
        self._core._audit("qualification_revoked", now, {"qualification_id": req["qualification_id"], "reason": req["reason"]})
        return {"status": "revoked", "qualification_id": req["qualification_id"]}

    def is_qualified(self, *, provider: str, decision_class: str, spec_hash: str, qualification_ref: str | None) -> bool:
        """A live record of exactly this provider, class and spec (D-4, D-5):
        a reference naming anything else, or a revoked record, is not."""
        row = self._core._one("qualifications", {"qualification_id": qualification_ref}) if isinstance(qualification_ref, str) else None
        return row is not None and row["revoked_at"] is None and (row["provider"], row["decision_class"], row["spec_hash"]) == (provider, decision_class, spec_hash)
