"""Brief and contract versions, and what a new version does to work pinned to
the one it supersedes (task 1d). A mixin of service.Router, with the router's
one shape: validate outside any transaction, then one short transaction that
fences and writes.

Trace: flow S1 (an unconfirmed brief cannot advance; expiry marks it overdue,
never advances it), S3 (Contract v2, hash-locked with its protocol
revision), §6.1 (an edited brief re-versions), §6.4-6.5 (a reframe versions
the facet map, marks labels and coverage stale-under-new-framing, reopens
exclusions, suspends auto-promotions); design review §4 ("An amended protocol
triggers deterministic identification of affected screening labels,
dossiers, verification, and index generations; it must not silently reuse
incompatible results"), §5 step 3 ("Reject or explicitly reconcile stale
work before mutation"); BOUNDARIES.md Router, Operator; INVARIANTS G-1, G-4,
G-6, G-7, C-10, C-12, V-10; the 1a review (G-1 impact before Phase 1
acceptance), the 1b review (bootstrap ruling: minimal router-owned brief and
amendment version commands; ruling on proposal 3: amendment_pending was an
interim fail-closed rule).

Commands (trusted surface until 1e): version_brief writes the next version
of a brief — a re-version, an owner reassignment or a deadline extension,
each a new immutable version awaiting confirmation (a version awaiting
confirmation that it replaces is superseded; a confirmed one stays confirmed
until its successor is confirmed); mark_brief_overdue marks a version
awaiting confirmation overdue once its deadline has passed on the router's
clock (expiry marks, it never advances); propose_amendment writes the next
contract revision as a draft whose parent is the approved revision, with its
facet and obligation rows. Approval stays an operator decision
(amendment_approval, reframe_approval: service.Router._approve_contract).

Compatibility, deterministic and structural: whether work, labels and claims
pinned to a superseded contract revision stay valid under the current one,
section by section of Contract v2 (flow S3), each class taken from the
governing design:
  framing   the decision record; the facet map's analytic framework, its
            facets as defined (their importance aside), its coverage
            question types and what it leaves deliberately out. G-6 and flow
            §6.5: a reframe versions the facet map; methodology §2 step 1
            (the framework is drawn from the decision, each link generating
            a key question) and §5 (decision record, framing version and
            facet map are one versioned formulation: "what changed at each
            reframe"); methodology §2's revision taxonomy (replacing the
            framing is the changed-objective boundary). Any change of these,
            or of the framing version, is `reframed`.
  protocol  the protocol revision, eligibility protocol, stopping profiles
            and applicability rules (G-1: the lock covers that protocol;
            G-7: eligibility, required access tier, stopping
            interpretation; RG-6: labels under an old protocol do not count
            under the new one), and the approved inventory (G-1): every
            obligation the two revisions share, as defined, importance aside
            (a claim answers its obligation), and anything the new one
            withdraws. An obligation it no longer carries is withdrawn,
            whether removed or issued again under another id: its id is how
            work, coverage and claims answer it. So is a coverage-matrix cell
            it does not keep in scope, covered at least as it was — dropped,
            emptied of an obligation, put deliberately out, a deliberately-out
            one brought back, or its entry otherwise changed — and a cell it
            adds deliberately out, or as a gap beside one already listed
            (methodology §2 step 4: the obligation set is approved with its
            matrix, "what we chose not to ask" recorded with the same weight
            as what we asked). Any of these is `protocol_changed`, fencing
            everything pinned to the superseded revision (Astra 1d-repair
            review finding 1: at Phase 1's revision-wide scope a conservative
            fence suffices; reconciling item by item is a later design).
  neither   `compatible`: what only adds to the inventory — an obligation
            added, a gap cell filled, an obligation added to a covered cell,
            a cell listed in scope for a pair not listed before (G-5: a
            sub-question inside an existing facet; methodology §2's taxonomy:
            filling a known gap needs no reframe) — importance ratings (G-2:
            authority for later actions, given by their own decision), the
            surveillance policy (when a completed topic reopens, flow S8) and
            the method design (how the work proceeds; its envelope bounds
            self-serve adjustment, flow S5).
The rule is conservative: an edit harmless in meaning is still
incompatible (a reworded key question is a reframe), and no edit of a
framing or protocol section is compatible. It is not symmetric: an addition
is compatible, and its revert a withdrawal. A brief version is compatible
with its successor only if they differ in lineage alone (version, parent,
creation time).

Versions name content (G-6; C-12: labels carry their framing and protocol
versions). An amendment whose framing (protocol) is the approved revision's
keeps that framing version (protocol revision); one whose framing
(protocol) changed takes a new one, above every one the topic has recorded.
So a label never names two contents and never comes back: returning to an
earlier framing is a new framing version. Compatibility compares the
content itself as well as the label, so a revision written around the
router is classed by what it contains.

An approval that supersedes a revision (or a confirmed brief version)
records, in its own transaction, its impact (DDL amendment_impacts): every
affected item and its disposition. Admitted work pinned to a superseded
version either completes under its pins within its deadline (compatible) or
is fenced: its cancellation is requested (router) wherever it can still be,
and its commit is refused as amendment_pending, the result staying retained
(C-10). Screening labels, claims and verifications under an incompatible
revision are listed stale; exclusions among them are reopened for
re-screening; a stale claim is not promoted — contract-admitted work adopts
it as a new revision (V-10); dossiers under a superseded revision are not
current (G-8); a reframe marks the old revision's coverage stale; open
reservations bound to the superseded revision close (G-5). The record lists;
it rewrites and deletes nothing it lists.

Standing (G-1: incompatible results are never silently reused). The impact
also records, for each earlier version that still stood, its class against
the new current version (`standing`). Pins are judged by those records, not
by comparing documents again: once a recorded impact has classed a version
incompatible, what is pinned to it stays incompatible — no later approval
judges it again, even one whose content matches it once more. Its work stays
fenced and its claims unpromoted; authority returns only through new work
under the current version: adoption as a new claim revision (V-10),
re-screening, a re-queue. (Phase 1 has no reconciliation record restoring
it.) A superseded version that no recorded impact lists is treated as
incompatible (`unrecorded`).
"""
from __future__ import annotations

from typing import Mapping

from gen2.core import canonical
from gen2.router import boundary
from gen2.router.boundary import Refusal, instant

PROTOCOL_SECTIONS = ("eligibility_protocol", "stopping_profiles", "applicability_rules")
BRIEF_LINEAGE = ("version", "parent_version", "created_at", "content_hash")
COMPATIBLE = ("current", "compatible", "lineage_only")
ENDED = ("committed", "failed", "cancelled")
DISPOSITION = {"compatible": "valid", "lineage_only": "valid", "reframed": "stale_under_new_framing",
               "protocol_changed": "stale_under_new_protocol", "content_changed": "stale_under_new_brief"}

_TS = {"$ref": "common.schema.json#/$defs/timestamp"}
AMENDMENT_COMMANDS = {
    "brief_version": {
        "type": "object", "additionalProperties": False, "required": ["document", "owner_operator_id", "review_deadline"],
        "properties": {"document": {"type": "object"}, "owner_operator_id": {"$ref": "common.schema.json#/$defs/short_text"}, "review_deadline": _TS}},
    "brief_overdue": {
        "type": "object", "additionalProperties": False, "required": ["topic_id", "brief_id", "version"],
        "properties": {"topic_id": {"$ref": "common.schema.json#/$defs/topic_id"}, "brief_id": {"$ref": "common.schema.json#/$defs/short_text"},
                       "version": {"$ref": "common.schema.json#/$defs/revision"}}},
    "amendment": {"type": "object", "additionalProperties": False, "required": ["document"], "properties": {"document": {"type": "object"}}},
}


def _same(a: object, b: object) -> bool:
    return canonical.canonical_bytes(a) == canonical.canonical_bytes(b)


def _obligations(doc: dict) -> dict:
    return {o["obligation_id"]: {k: v for k, v in o.items() if k != "importance"} for o in doc["obligations"]}


def _cells(doc: dict) -> dict:
    """The coverage matrix's cells, by (facet, question type)."""
    cells: dict = {}
    for cell in (doc["facet_map"].get("coverage_matrix") or {}).get("cells", ()):
        cells.setdefault((cell["facet_id"], cell["question_type"]), []).append(cell)
    return cells


def _kept(was: dict, cell: dict) -> bool:
    """Whether `cell` keeps the earlier cell `was` in scope, covered at least
    as it was: the same cell, its gap filled, or its obligations added to."""
    rest = lambda c: {k: v for k, v in c.items() if k != "obligation_ids"}  # noqa: E731
    return _same(was, cell) or cell["state"] == "covered" and (
        was["state"] == "gap" or was["state"] == "covered" and _same(rest(was), rest(cell))
        and set(was.get("obligation_ids", ())) <= set(cell.get("obligation_ids", ())))


def _withdrawn(pinned: dict, current: dict) -> bool:
    """Whether `current` withdraws anything of the inventory `pinned` approved
    (module docstring): an obligation it no longer carries, removed or issued
    again under another id; a cell it does not keep (_kept); or a cell it adds
    out of scope, deliberately out or a gap beside one the pinned listed."""
    old, new = _cells(pinned), _cells(current)
    if _obligations(pinned).keys() - _obligations(current).keys():
        return True
    if any(not any(_kept(was, cell) for cell in new.get(pair, ())) for pair, cells in old.items() for was in cells):
        return True
    return any(cell["state"] != "covered" and not any(_same(was, cell) for was in old.get(pair, ())) and (cell["state"] != "gap" or pair in old)
               for pair, cells in new.items() for cell in cells)


def framing(doc: dict) -> dict:
    """What a framing version names (module docstring): the decision record
    and the facet map, but for the version label itself, the facets'
    importance and the coverage matrix's cells (the inventory's: _withdrawn).
    (A section a document written around the router lacks is compared as
    absent.)"""
    facet_map = doc["facet_map"]
    return {"decision_record": doc.get("decision_record"), "analytic_framework": facet_map.get("analytic_framework"),
            "facets": [{k: v for k, v in facet.items() if k != "importance"} for facet in facet_map.get("facets", ())],
            "question_types": (facet_map.get("coverage_matrix") or {}).get("question_types"), "deliberately_out": facet_map.get("deliberately_out")}


def protocol(doc: dict) -> dict:
    """What a protocol revision names: the eligibility protocol, stopping profiles and applicability rules."""
    return {k: doc.get(k) for k in PROTOCOL_SECTIONS}


# (what, its label's name, the label, the content it names): a label names one content (module docstring)
VERSIONED = (("framing", "framing version", lambda doc: doc["facet_map"]["framing_version"], framing),
             ("protocol", "protocol revision", lambda doc: doc["protocol_revision"], protocol))


def contract_compatibility(pinned: dict, current: dict) -> str:
    """Whether results produced under the `pinned` contract document stay
    valid under the `current` one (G-1, G-6): compatible, reframed or
    protocol_changed (module docstring). Labels and content both count, and
    so does what `current` withdraws from `pinned`'s inventory."""
    if pinned["facet_map"]["framing_version"] != current["facet_map"]["framing_version"] or not _same(framing(pinned), framing(current)):
        return "reframed"
    old, new = _obligations(pinned), _obligations(current)
    if pinned["protocol_revision"] != current["protocol_revision"] or not _same(protocol(pinned), protocol(current)) \
            or any(not _same(old[o], new[o]) for o in old.keys() & new.keys()) \
            or _withdrawn(pinned, current):
        return "protocol_changed"
    return "compatible"


def brief_compatibility(pinned: dict, current: dict) -> str:
    strip = lambda doc: {k: v for k, v in doc.items() if k not in BRIEF_LINEAGE}  # noqa: E731
    return "lineage_only" if _same(strip(pinned), strip(current)) else "content_changed"


def _importance(entry: dict) -> dict:
    """A facet or obligation row's importance columns, as its document entry states them (DDL binds the two)."""
    proposed, rating = entry["importance"].get("proposed") or {}, entry["importance"].get("operator_rating") or {}
    return {"proposed_importance_source": proposed.get("source"), "proposed_importance_score": proposed.get("score"),
            "proposed_decision_receipt_id": proposed.get("decision_receipt_id"), "operator_importance_band": rating.get("band"),
            "operator_importance_score": rating.get("score"), "operator_rating_decision_id": rating.get("operator_decision_id")}


class Amendments:
    # -- commands ----------------------------------------------------------------
    def version_brief(self, request: Mapping) -> dict:
        return self._amendment_command(request, "brief_version", "intake-brief.schema.json", self._version_brief_in_transaction)

    def mark_brief_overdue(self, request: Mapping) -> dict:
        return self._amendment_command(request, "brief_overdue", None, self._overdue_in_transaction)

    def propose_amendment(self, request: Mapping) -> dict:
        return self._amendment_command(request, "amendment", "contract-v2.schema.json", self._amendment_in_transaction)

    def _amendment_command(self, request: Mapping, shape: str, document_schema: str | None, body) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._schemas, req, f"router-commands#/$defs/{shape}", "request_invalid")
            if document_schema is not None:
                boundary.require_schema(self._schemas, req["document"], document_schema, "request_invalid")
                if canonical.content_hash(req["document"]) != req["document"]["content_hash"]:
                    raise Refusal("request_invalid", "the document does not hash to its content hash (C-13, RA6)")
            return self._guarded("request_invalid", lambda now: body(req, now))
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}

    def _open_topic(self, topic_id: str) -> dict:
        topic = self._one("queue_entries", {"topic_id": topic_id})
        if topic is None:
            raise Refusal("unknown_topic", topic_id)
        if topic["status"] == "retired":
            raise Refusal("topic_retired", f"{topic_id} is retired")
        return topic

    def _version_brief_in_transaction(self, req: dict, now: str) -> dict:
        doc = req["document"]
        key = {"topic_id": doc["topic_id"], "brief_id": doc["brief_id"]}
        stored = self._one("intake_briefs", {**key, "version": doc["version"]})
        if stored is not None:  # the key is (topic, brief, version); only the identical version replays
            if not _same(stored["document"], doc) or (stored["owner_operator_id"], stored["review_deadline"]) != (req["owner_operator_id"], req["review_deadline"]):
                raise Refusal("brief_version_conflict", f"{doc['brief_id']} v{doc['version']} was written otherwise")
            return {"status": "replayed", **key, "version": doc["version"]}
        self._open_topic(doc["topic_id"])
        latest = max(self._store.select("intake_briefs", key), key=lambda b: b["version"], default=None)
        if latest is None:
            raise Refusal("unknown_brief", "a brief's first version is intake's (Phase 2); this writes the next version of a recorded brief")
        if (doc["version"], doc["parent_version"]) != (latest["version"] + 1, latest["version"]):
            raise Refusal("request_invalid", f"the next version of {doc['brief_id']} is {latest['version'] + 1}, with parent {latest['version']}")
        if latest["status"] in ("cancelled", "archived"):
            raise Refusal("brief_closed", f"{doc['brief_id']} v{latest['version']} is {latest['status']}")
        if instant(doc["created_at"]) > instant(now) or instant(req["review_deadline"]) <= instant(now):
            raise Refusal("request_invalid", f"a version is created by now and reviewed after now ({now})")
        self._store.insert("intake_briefs", {**key, "version": doc["version"], "parent_version": doc["parent_version"], "content_hash": doc["content_hash"],
                                             "document": doc, "owner_operator_id": req["owner_operator_id"], "status": "awaiting_confirmation",
                                             "created_at": doc["created_at"], "review_deadline": req["review_deadline"]})
        superseded = None
        if latest["status"] == "awaiting_confirmation":  # it can no longer be confirmed; a confirmed one waits for its successor's confirmation
            self._store.update("intake_briefs", {**key, "version": latest["version"]}, {"status": "superseded"})
            superseded = latest["version"]
        self._audit("brief_versioned", now, {**key, "version": doc["version"], "superseded": superseded}, topic_id=doc["topic_id"])
        return {"status": "recorded", **key, "version": doc["version"], "superseded": superseded}

    def _overdue_in_transaction(self, req: dict, now: str) -> dict:
        row = self._one("intake_briefs", {"topic_id": req["topic_id"], "brief_id": req["brief_id"], "version": req["version"]})
        if row is None:
            raise Refusal("unknown_brief", f"{req['brief_id']} v{req['version']}")
        if row["overdue_since"] is not None:
            return {"status": "replayed", "overdue_since": row["overdue_since"]}
        if row["status"] != "awaiting_confirmation":
            raise Refusal("brief_not_awaiting", f"{req['brief_id']} v{req['version']} is {row['status']}")
        if instant(now) < instant(row["review_deadline"]):
            raise Refusal("not_overdue", f"its review deadline {row['review_deadline']} has not passed ({now})")
        self._store.update("intake_briefs", {k: req[k] for k in ("topic_id", "brief_id", "version")}, {"overdue_since": now})
        self._audit("brief_overdue", now, {"brief_id": req["brief_id"], "version": req["version"]}, topic_id=req["topic_id"])
        return {"status": "marked", "overdue_since": now}

    def _amendment_in_transaction(self, req: dict, now: str) -> dict:
        doc = req["document"]
        tid = doc["topic_id"]
        stored = self._one("contract_revisions", {"topic_id": tid, "revision": doc["revision"]})
        if stored is not None:
            if not _same(stored["document"], doc):
                raise Refusal("amendment_conflict", f"revision {doc['revision']} of {tid} was written otherwise")
            return {"status": "replayed", "topic_id": tid, "revision": doc["revision"]}
        self._open_topic(tid)
        revisions = self._store.select("contract_revisions", {"topic_id": tid})
        approved = next((c for c in revisions if c["status"] == "approved"), None)
        if approved is None:
            raise Refusal("no_approved_contract", "an amendment revises the approved contract; a first draft is contract construction's (Phase 2)")
        newest = max(c["revision"] for c in revisions)
        if (doc["revision"], doc["parent_revision"]) != (newest + 1, approved["revision"]):
            raise Refusal("request_invalid", f"an amendment is revision {newest + 1}, with the approved revision {approved['revision']} as its parent")
        for what, name, label, content in VERSIONED:  # a label names one content (module docstring)
            kept, recorded = label(approved["document"]), max(label(c["document"]) for c in revisions)
            if _same(content(doc), content(approved["document"])):
                if label(doc) != kept:
                    raise Refusal("request_invalid", f"the {what} is the approved revision's, so it keeps {name} {kept} (G-6)")
            elif label(doc) <= recorded:
                raise Refusal("request_invalid", f"a changed {what} takes a new {name}, above every recorded one ({recorded}): a label never names two (G-6)")
        self._store.insert("contract_revisions", {"topic_id": tid, "revision": doc["revision"], "parent_revision": doc["parent_revision"],
                                                  "protocol_revision": doc["protocol_revision"], "framing_version": doc["facet_map"]["framing_version"],
                                                  "content_hash": doc["content_hash"], "document": doc, "status": "draft", "created_at": doc["created_at"]})
        for facet in doc["facet_map"]["facets"]:
            self._store.insert("facets", {"topic_id": tid, "contract_revision": doc["revision"], "facet_id": facet["facet_id"], **_importance(facet)})
        for o in doc["obligations"]:
            self._store.insert("obligations", {
                "topic_id": tid, "contract_revision": doc["revision"], "obligation_id": o["obligation_id"], "template_id": o["template"]["template_id"],
                "template_version": o["template"]["template_version"], "claim_type": o["template"]["claim_type"], "facet_ids": o["facet_ids"],
                "stopping_profile_id": o["stopping_profile_id"], "exploratory": o["exploratory"], **_importance(o)})
        against = contract_compatibility(approved["document"], doc)
        self._audit("amendment_proposed", now, {"revision": doc["revision"], "against_approved": against}, topic_id=tid)
        return {"status": "recorded", "topic_id": tid, "revision": doc["revision"], "against_approved": against}

    # -- pins ----------------------------------------------------------------------
    def _pin_status(self, inv: dict) -> str:
        """`current`, or how the invocation's pinned contract revision (or,
        before any contract, brief version) stands now, as the recorded
        impacts say (_standing); a closed brief carries no work, nor does a
        brief whose lineage is no longer the topic's confirmed one."""
        if inv["admission_context"] == "contract/1":
            pinned = self._one("contract_revisions", {"topic_id": inv["topic_id"], "revision": inv["contract_revision"]})
            if pinned["status"] == "approved":
                return "current"
            return self._standing("contract", inv["topic_id"], inv["contract_revision"]) or "compatible"
        pinned = self._one("intake_briefs", {"topic_id": inv["topic_id"], "brief_id": inv["brief_ref"], "version": inv["brief_version"]})
        current = self._one("intake_briefs", {"topic_id": inv["topic_id"], "status": "confirmed"})
        if pinned["status"] == "confirmed":
            return "current"
        if pinned["status"] == "superseded" and current is not None and current["brief_id"] == inv["brief_ref"]:  # its own lineage is current
            return self._standing("brief", inv["topic_id"], inv["brief_version"], inv["brief_ref"]) or "lineage_only"
        return pinned["status"]

    def _standing(self, kind: str, topic_id: str, version: int, brief_id: str | None = None) -> str | None:
        """How what is pinned to a superseded `version` stands, as the impacts
        recorded since its supersession list it (module docstring): None
        while every one classed it compatible; otherwise the first
        incompatible class one gave it, which no later approval undoes; or
        `unrecorded` if none lists it."""
        key = "revision" if kind == "contract" else "version"
        listed = [entry["classification"] for impact in self._store.select("amendment_impacts", {"topic_id": topic_id, "kind": kind})
                  if impact["document"].get("brief_id") == brief_id for entry in impact["document"].get("standing", ()) if entry[key] == version]
        if not listed:
            return "unrecorded"
        return next((c for c in listed if c not in COMPATIBLE), None)

    def _require_current_pins(self, inv: dict) -> None:
        """A commit of work whose pins an approval has since superseded lands
        under those pins only if they are compatible with the current ones;
        otherwise it is fenced (amendment_pending) and the result stays
        retained, unreused (G-1, C-10, C-12)."""
        status = self._pin_status(inv)
        if status not in COMPATIBLE:
            pinned = f"contract revision {inv['contract_revision']}" if inv["contract_revision"] is not None else f"brief {inv['brief_ref']} v{inv['brief_version']}"
            raise Refusal("amendment_pending", f"pinned {pinned} was superseded ({status}); its result is not reused under the current one and stays retained")

    # -- impact ----------------------------------------------------------------------
    def _record_impact(self, d: dict, kind: str, superseded: dict, current: dict, now: str) -> dict:
        """G-1: what the approval `d` of `current`, superseding `superseded`,
        does to what was pinned to it; recorded in the approval's transaction,
        after the approval itself (module docstring)."""
        tid = d["topic_id"]
        if kind == "contract":
            key, compat, brief_id, rows = "revision", contract_compatibility, None, [c for c in self._store.select("contract_revisions", {"topic_id": tid}) if c["approved_by_decision_id"]]
            pin = lambda inv: inv["contract_revision"] if inv["admission_context"] == "contract/1" else None  # noqa: E731
        else:
            key, compat, brief_id = "version", brief_compatibility, superseded["brief_id"]
            rows = [b for b in self._store.select("intake_briefs", {"topic_id": tid, "brief_id": brief_id}) if b["confirmed_by_decision_id"]]
            pin = lambda inv: inv["brief_version"] if inv["brief_ref"] == brief_id else None  # noqa: E731
        # how each earlier version stood until now: the superseded one stood; any other as the recorded impacts say — what one made stale stays stale
        prior = {r[key]: None if r[key] == superseded[key] else self._standing(kind, tid, r[key], brief_id) for r in rows if r[key] != current[key]}
        status = {r[key]: prior[r[key]] or compat(r["document"], current["document"]) for r in rows if r[key] in prior}
        stood = {v for v, was in prior.items() if was is None}
        invocations = self._store.select("invocations", {"topic_id": tid})
        pinned = {i["invocation_id"]: pin(i) for i in invocations}
        doc = {"impact_version": "amendment-impact/1", "decision_id": d["decision_id"], "topic_id": tid, "kind": kind, "classification": status[superseded[key]],
               "superseded": {key: superseded[key], "content_hash": superseded["content_hash"]}, "current": {key: current[key], "content_hash": current["content_hash"]},
               "standing": [{key: v, "classification": status[v]} for v in sorted(stood)],
               "work": [self._fence(i, status[pinned[i["invocation_id"]]], d, now) for i in invocations
                        if i["state"] not in ENDED and pinned[i["invocation_id"]] in status],
               "coverage": [{"observation_id": o["observation_id"], "disposition": DISPOSITION[status[pinned[o["invocation_id"]]]]}
                            for o in self._store.select("search_observations", {"topic_id": tid}) if pinned[o["invocation_id"]] in stood]}
        if kind == "brief":
            doc["brief_id"] = brief_id  # the brief its standing is of
        if kind == "contract":
            listed = lambda rev: rev in stood  # noqa: E731
            doc["screening_labels"] = [{"assessment_id": a["assessment_id"], "contract_revision": a["contract_revision"], "decision": a["decision"],
                                        "disposition": DISPOSITION[status[a["contract_revision"]]]}
                                       for a in self._store.select("screening_assessments", {"topic_id": tid}) if listed(a["contract_revision"])]
            doc["reopened_exclusions"] = [a["assessment_id"] for a in doc["screening_labels"] if a["decision"] == "exclude" and a["disposition"] != "valid"]
            doc["claims"] = [{"claim_id": c["claim_id"], "revision": c["revision"], "status": c["status"], "disposition": DISPOSITION[status[pinned[c["producer_invocation_id"]]]]}
                             for c in self._store.select("claims", {"topic_id": tid}) if listed(pinned[c["producer_invocation_id"]]) and c["status"] != "superseded"]
            doc["verifications"] = [{"verification_receipt_id": v["verification_receipt_id"], "disposition": DISPOSITION[status[pinned[v["verifier_invocation_id"]]]]}
                                    for v in self._store.select("verification_receipts", {"topic_id": tid}) if listed(pinned[v["verifier_invocation_id"]])]
            doc["dossiers"] = [{"dossier_revision": x["dossier_revision"], "contract_revision": x["contract_revision"], "disposition": "not_current"}
                               for x in self._store.select("dossiers", {"topic_id": tid}) if listed(x["contract_revision"])]
            doc["reservations_closed"] = []
            for r in self._store.select("reservations", {"topic_id": tid}):
                if r["closed_at"] is None and r["contract_revision"] != current["revision"]:
                    self._store.update("reservations", {"reservation_id": r["reservation_id"]}, {"closed_at": now, "close_reason": f"revision superseded by {d['decision_id']}"})
                    doc["reservations_closed"].append(r["reservation_id"])
            doc["export_generations"] = [{"manifest_id": e["manifest_id"], "generation": e["generation"], "options_revision": e["options_revision"]}
                                         for e in self._store.select("outbox_events", {"topic_id": tid})]
        self._store.insert("amendment_impacts", {"decision_id": d["decision_id"], "topic_id": tid, "kind": kind, "classification": doc["classification"],
                                                 "document": doc, "recorded_at": now})
        return {"impact": {"classification": doc["classification"], "work": doc["work"]}}

    def _fence(self, inv: dict, status: str, d: dict, now: str) -> dict:
        """Admitted work pinned to a superseded version: it completes under its
        pins, or it is fenced — its cancellation requested (router) while it can
        still be; a staged result is refused at commit instead."""
        entry = {"invocation_id": inv["invocation_id"], "state": inv["state"], "disposition": "completes_under_pins" if status in COMPATIBLE else "fenced",
                 "cancel_requested": False}
        if entry["disposition"] == "fenced" and inv["cancel_requested_at"] is None and inv["state"] in ("admitted", "launching", "running", "outcome_unknown"):
            self._cancel_in_transaction({"invocation_id": inv["invocation_id"], "requested_by": "router", "reason": f"pins superseded by {d['decision_id']}"}, now)
            entry["cancel_requested"] = True
        return entry
