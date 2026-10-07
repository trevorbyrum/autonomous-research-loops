"""Brief and contract versions, and what a new version does to work pinned to
the one it supersedes (task 1d). A collaborator of service.Router (task 2q-b8:
"Router composition", BOUNDARIES.md), with the router's one shape: validate
outside any transaction, then one short transaction (the core's: `_guarded`)
that fences and writes.

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

Commands (the trusted surface: task 1e's authenticated operator surface):
open_brief (task 2a) writes a brief's first version (intake's hand-off, flow
S1: version 1, no parent, awaiting confirmation, created by now and reviewed
after now); version_brief writes the next version of a brief — a re-version, an owner reassignment or a deadline extension,
each a new immutable version awaiting confirmation (a version awaiting
confirmation that it replaces is superseded; a confirmed one stays confirmed
until its successor is confirmed); mark_brief_overdue marks a version
awaiting confirmation overdue once its deadline has passed on the router's
clock (expiry marks, it never advances); draft_contract (task 2a) writes
contract construction's drafts while the topic has never had an approved
contract and its brief is confirmed (flow S3): the first as revision 1 with
no parent, each later one revising the newest, so the draft carrying the
operator's ratings descends from the draft they rated (G-2) — its approval
is the existing contract_approval, which the store refuses while any facet
is unrated or a critical one uncovered (G-3); propose_amendment writes the
next contract revision as a draft whose parent is the approved revision.
Both write the facet and obligation rows, both keep a label naming one
content (below) against the revision revised, and both refuse a draft that
is not referentially consistent (references, below; task 2a's expansion); close_brief (task 1e) cancels
a version awaiting confirmation or archives a confirmed one, recording who
(the authenticated operator the surface names), when and why (G-4). Approval
stays an operator decision (contract_approval, amendment_approval,
reframe_approval: service.Router._approve_contract).

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

from typing import Callable, Mapping, Protocol

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
    "brief_close": {  # task 1e: closed_by is the authenticated operator the operator surface names, never the caller's own word
        "type": "object", "additionalProperties": False, "required": ["topic_id", "brief_id", "version", "closure", "closed_by", "reason"],
        "properties": {"topic_id": {"$ref": "common.schema.json#/$defs/topic_id"}, "brief_id": {"$ref": "common.schema.json#/$defs/short_text"},
                       "version": {"$ref": "common.schema.json#/$defs/revision"}, "closure": {"enum": ["cancelled", "archived"]},
                       "closed_by": {"$ref": "common.schema.json#/$defs/short_text"}, "reason": {"$ref": "common.schema.json#/$defs/short_text"}}},
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


def references(doc: dict, templates: dict) -> str | None:
    """The first referential defect of a contract draft, or None (task 2a;
    store README "What stays router logic"; flow S3: code checks referential
    consistency, the operator approves scientific fit). Ids are unique within
    their section; framework links join its nodes; each obligation fills
    exactly the slots of a registered template of its claim type (methodology
    §2 step 2), traces only to decision-record entries and framework links the
    contract has, and names one of its stopping profiles; each matrix cell
    names a facet and question type of the map, a covered cell only
    obligations that tag its facet, another cell none; applicability rules
    name its obligations; a templated method design is its registered
    template's combination (family, role, purpose). Structure only: whether
    the framework represents the decision is the operator's."""
    record, framework, matrix = doc["decision_record"], doc["facet_map"]["analytic_framework"], doc["facet_map"]["coverage_matrix"]
    entries = [e["entry_id"] for e in (*record["feeds"].get("alternatives", ()), *record["evidence_that_would_change_it"], *record["constraints"],
                                       *record["operator_hypotheses"], *record["surfaced_assumptions"])]
    nodes, links = [n["node_id"] for n in framework["nodes"]], [link["link_id"] for link in framework["links"]]
    facets, obligations = [f["facet_id"] for f in doc["facet_map"]["facets"]], {o["obligation_id"]: o for o in doc["obligations"]}
    profiles, design = [p["profile_id"] for p in doc["stopping_profiles"]], doc["method_design"]
    for what, ids in (("decision-record entry", entries), ("framework node", nodes), ("framework link", links), ("facet", facets), ("stopping profile", profiles),
                      ("obligation", [o["obligation_id"] for o in doc["obligations"]]), ("method family", [f["family_id"] for f in design["families"]])):
        if len(set(ids)) != len(ids):
            return f"a {what} id is used twice"
    if any(not {link["from_node"], link["to_node"]} <= set(nodes) for link in framework["links"]):
        return "a framework link joins a node the framework lacks"
    registered = {(t["template_id"], t["template_version"]): t for t in templates.get("obligation", ())}
    for oid, o in obligations.items():
        t = registered.get((o["template"]["template_id"], o["template"]["template_version"]))
        if t is None or t["claim_type"] != o["template"]["claim_type"]:
            return f"{oid}: template {o['template']['template_id']} v{o['template']['template_version']} is no registered {o['template']['claim_type']} template"
        if not set(t["required_slots"]) <= set(o["slots"]) <= set(t["required_slots"]) | set(t["optional_slots"]):
            return f"{oid}: its slots are not its template's (required {sorted(t['required_slots'])}, optional {sorted(t['optional_slots'])})"
        if not set(o["traces_to"]["decision_record_entries"]) <= set(entries) or not set(o["traces_to"]["framework_links"]) <= set(links):
            return f"{oid} traces to a decision-record entry or framework link the contract lacks"
        if o["stopping_profile_id"] not in profiles:
            return f"{oid} names stopping profile {o['stopping_profile_id']}, which the contract lacks"
    for cell in matrix["cells"]:
        at, named = f"cell ({cell['facet_id']}, {cell['question_type']})", cell.get("obligation_ids", ())
        if cell["facet_id"] not in facets or cell["question_type"] not in matrix["question_types"]:
            return f"{at} names a facet or question type the map lacks"
        if any(i not in obligations or cell["facet_id"] not in obligations[i]["facet_ids"] for i in named) or (cell["state"] != "covered" and named):
            return f"{at} names obligations that are not the contract's tagging its facet, or names any while {cell['state']}"
    if any(not set(rule["obligation_ids"]) <= set(obligations) for rule in doc["applicability_rules"]):
        return "an applicability rule names an obligation the contract lacks"
    if design["selection"] == "template":
        shape = lambda families: sorted(_key(f) for f in families)  # noqa: E731
        md = next((t for t in templates.get("method_design", ()) if (t["template_id"], t["template_version"]) == (design["template"]["template_id"], design["template"]["template_version"])), None)
        if md is None or shape(md["families"]) != shape(design["families"]):
            return "the method design is not its registered template's combination of families, roles and purposes"
    return None


def _key(family: dict) -> bytes:
    return canonical.canonical_bytes({k: family.get(k) for k in ("family", "role", "purpose")})


def _importance(entry: dict) -> dict:
    """A facet or obligation row's importance columns, as its document entry states them (DDL binds the two)."""
    proposed, rating = entry["importance"].get("proposed") or {}, entry["importance"].get("operator_rating") or {}
    return {"proposed_importance_source": proposed.get("source"), "proposed_importance_score": proposed.get("score"),
            "proposed_decision_receipt_id": proposed.get("decision_receipt_id"), "operator_importance_band": rating.get("band"),
            "operator_importance_score": rating.get("score"), "operator_rating_decision_id": rating.get("operator_decision_id")}


class Rows(Protocol):
    """The router's store as amendments uses it (store/api.py Store): inside the core's transaction."""
    def select(self, table: str, where: Mapping[str, object] | None = None) -> list[dict]: ...
    def insert(self, table: str, row: Mapping[str, object]) -> None: ...
    def update(self, table: str, key: Mapping[str, object], changes: Mapping[str, object]) -> None: ...


class Schemas(Protocol):
    """The router's schema set as boundary.require_schema uses it (schemas.py SchemaSet)."""
    def errors(self, instance: object, target: str) -> list[str]: ...


class AmendmentsCore(Protocol):
    """What amendments takes of the router core, and nothing else; service.Router
    implements it without inheriting it. Every member is the core's own (service.py:
    `_templates` and `_cancel_in_transaction` delegate to the registries and the
    lifecycle). Amendments' own members the rest of the Router reads
    (`_open_topic`, `_pin_status`, `_brief_standing`, `_record_impact`,
    `_record_replacements`, `_recorded_references`, `_require_current_pins`) are the
    core's delegating members, so no other collaborator reaches amendments but through the core."""
    _store: Rows
    _schemas: Schemas
    def _one(self, table: str, where: Mapping[str, object]) -> dict | None: ...
    def _guarded(self, reason: str, body: Callable[[str], object]) -> object: ...  # the one transaction an operation runs in
    def _audit(self, kind: str, at: str, detail: dict, *, topic_id=None, invocation_id=None, operation_id=None) -> str: ...
    def _templates(self) -> dict: ...
    def _cancel_in_transaction(self, req: dict, now: str) -> dict: ...


class Amendments:
    def __init__(self, core: AmendmentsCore) -> None:
        self._core = core

    # -- commands ----------------------------------------------------------------
    def version_brief(self, request: Mapping) -> dict:
        return self._amendment_command(request, "brief_version", "intake-brief.schema.json", self._version_brief_in_transaction)

    def open_brief(self, request: Mapping) -> dict:
        """Task 2a: a brief's first version (intake's, flow S1), in version_brief's shape."""
        return self._amendment_command(request, "brief_version", "intake-brief.schema.json", lambda req, now: self._version_brief_in_transaction(req, now, first=True))

    def mark_brief_overdue(self, request: Mapping) -> dict:
        return self._amendment_command(request, "brief_overdue", None, self._overdue_in_transaction)

    def propose_amendment(self, request: Mapping) -> dict:
        return self._amendment_command(request, "amendment", "contract-v2.schema.json", self._amendment_in_transaction)

    def draft_contract(self, request: Mapping) -> dict:
        """Task 2a: contract construction's drafts before any approval (flow S3), in propose_amendment's shape."""
        return self._amendment_command(request, "amendment", "contract-v2.schema.json", lambda req, now: self._amendment_in_transaction(req, now, draft=True))

    def close_brief(self, request: Mapping) -> dict:
        return self._amendment_command(request, "brief_close", None, self._close_in_transaction)

    def _amendment_command(self, request: Mapping, shape: str, document_schema: str | None, body) -> dict:
        try:
            req = boundary.normalize(request, "request_invalid")
            boundary.require_schema(self._core._schemas, req, f"router-commands#/$defs/{shape}", "request_invalid")
            if document_schema is not None:
                boundary.require_schema(self._core._schemas, req["document"], document_schema, "request_invalid")
                if canonical.content_hash(req["document"]) != req["document"]["content_hash"]:
                    raise Refusal("request_invalid", "the document does not hash to its content hash (C-13, RA6)")
            return self._core._guarded("request_invalid", lambda now: body(req, now))
        except Refusal as refusal:
            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}

    def _open_topic(self, topic_id: str) -> dict:
        topic = self._core._one("queue_entries", {"topic_id": topic_id})
        if topic is None:
            raise Refusal("unknown_topic", topic_id)
        if topic["status"] == "retired":
            raise Refusal("topic_retired", f"{topic_id} is retired")
        return topic

    def _version_brief_in_transaction(self, req: dict, now: str, first: bool = False) -> dict:
        doc = req["document"]
        key = {"topic_id": doc["topic_id"], "brief_id": doc["brief_id"]}
        stored = self._core._one("intake_briefs", {**key, "version": doc["version"]})
        if stored is not None:  # the key is (topic, brief, version); only the identical version replays
            if not _same(stored["document"], doc) or (stored["owner_operator_id"], stored["review_deadline"]) != (req["owner_operator_id"], req["review_deadline"]):
                raise Refusal("brief_version_conflict", f"{doc['brief_id']} v{doc['version']} was written otherwise")
            return {"status": "replayed", **key, "version": doc["version"]}
        self._open_topic(doc["topic_id"])
        latest = max(self._core._store.select("intake_briefs", key), key=lambda b: b["version"], default=None)
        if first and latest is not None:  # task 2a: open_brief writes a brief not yet recorded, version_brief every later version
            raise Refusal("brief_exists", f"{doc['brief_id']} is recorded (v{latest['version']}); its next version is version_brief's")
        if latest is None and not first:
            raise Refusal("unknown_brief", "a brief's first version is open_brief's (intake); this writes the next version of a recorded brief")
        lineage = (1, None) if latest is None else (latest["version"] + 1, latest["version"])
        if (doc["version"], doc["parent_version"]) != lineage:
            raise Refusal("request_invalid", f"the next version of {doc['brief_id']} is {lineage[0]}, with parent {lineage[1]}")
        if latest is not None and latest["status"] in ("cancelled", "archived"):
            raise Refusal("brief_closed", f"{doc['brief_id']} v{latest['version']} is {latest['status']}")
        if instant(doc["created_at"]) > instant(now) or instant(req["review_deadline"]) <= instant(now):
            raise Refusal("request_invalid", f"a version is created by now and reviewed after now ({now})")
        self._core._store.insert("intake_briefs", {**key, "version": doc["version"], "parent_version": doc["parent_version"], "content_hash": doc["content_hash"],
                                             "document": doc, "owner_operator_id": req["owner_operator_id"], "status": "awaiting_confirmation",
                                             "created_at": doc["created_at"], "review_deadline": req["review_deadline"]})
        superseded = None
        if latest is not None and latest["status"] == "awaiting_confirmation":  # it can no longer be confirmed; a confirmed one waits for its successor's confirmation
            self._core._store.update("intake_briefs", {**key, "version": latest["version"]}, {"status": "superseded"})
            superseded = latest["version"]
        self._core._audit("brief_versioned", now, {**key, "version": doc["version"], "superseded": superseded}, topic_id=doc["topic_id"])
        return {"status": "recorded", **key, "version": doc["version"], "superseded": superseded}

    def _overdue_in_transaction(self, req: dict, now: str) -> dict:
        row = self._core._one("intake_briefs", {"topic_id": req["topic_id"], "brief_id": req["brief_id"], "version": req["version"]})
        if row is None:
            raise Refusal("unknown_brief", f"{req['brief_id']} v{req['version']}")
        if row["overdue_since"] is not None:
            return {"status": "replayed", "overdue_since": row["overdue_since"]}
        if row["status"] != "awaiting_confirmation":
            raise Refusal("brief_not_awaiting", f"{req['brief_id']} v{req['version']} is {row['status']}")
        if instant(now) < instant(row["review_deadline"]):
            raise Refusal("not_overdue", f"its review deadline {row['review_deadline']} has not passed ({now})")
        self._core._store.update("intake_briefs", {k: req[k] for k in ("topic_id", "brief_id", "version")}, {"overdue_since": now})
        self._core._audit("brief_overdue", now, {"brief_id": req["brief_id"], "version": req["version"]}, topic_id=req["topic_id"])
        return {"status": "marked", "overdue_since": now}

    def _close_in_transaction(self, req: dict, now: str) -> dict:
        """G-4: cancellation (of a version awaiting confirmation) and archival
        (of a confirmed one) are explicit acts, with who, when and why (task
        1e: who is the authenticated operator). Key: (topic, brief, version);
        the closure is write-once, and only the identical one replays. Work
        pinned to a closed version is fenced at its commit (_pin_status: a
        closed brief carries no work)."""
        key = {k: req[k] for k in ("topic_id", "brief_id", "version")}
        row = self._core._one("intake_briefs", key)
        if row is None:
            raise Refusal("unknown_brief", f"{req['brief_id']} v{req['version']}")
        if row["closed_at"] is not None:
            if (row["status"], row["closed_by"], row["close_reason"]) != (req["closure"], req["closed_by"], req["reason"]):
                raise Refusal("brief_close_conflict", f"{req['brief_id']} v{req['version']} was {row['status']} by {row['closed_by']} at {row['closed_at']}")
            return {"status": "replayed", **key, "closure": row["status"], "closed_at": row["closed_at"]}
        if {"awaiting_confirmation": "cancelled", "confirmed": "archived"}.get(row["status"]) != req["closure"]:
            raise Refusal("brief_not_closable", f"{req['brief_id']} v{req['version']} is {row['status']}: a version awaiting confirmation is "
                                                "cancelled, a confirmed one archived (G-4)")
        self._core._store.update("intake_briefs", key, {"status": req["closure"], "closed_by": req["closed_by"], "closed_at": now, "close_reason": req["reason"]})
        self._core._audit("brief_closed", now, {**key, "closure": req["closure"], "by": req["closed_by"]}, topic_id=req["topic_id"])
        return {"status": "closed", **key, "closure": req["closure"], "closed_at": now}

    def _amendment_in_transaction(self, req: dict, now: str, draft: bool = False) -> dict:
        doc = req["document"]
        tid = doc["topic_id"]
        stored = self._core._one("contract_revisions", {"topic_id": tid, "revision": doc["revision"]})
        if stored is not None:
            if not _same(stored["document"], doc):
                raise Refusal("amendment_conflict", f"revision {doc['revision']} of {tid} was written otherwise")
            return {"status": "replayed", "topic_id": tid, "revision": doc["revision"]}
        topic = self._open_topic(tid)
        revisions = self._core._store.select("contract_revisions", {"topic_id": tid})
        approved = next((c for c in revisions if c["status"] == "approved"), None)
        if draft:  # task 2a: before any approval, each draft revises the newest (the first none), so a rated draft descends from the draft rated (G-2)
            if any(c["status"] != "draft" for c in revisions):
                raise Refusal("contract_approved", "the topic has had an approved contract; a revision of it is propose_amendment's")
            if topic["status"] == "awaiting_brief_confirmation":
                raise Refusal("brief_unconfirmed", "a contract is drafted once the topic's brief is confirmed (G-4: an unconfirmed brief does not advance)")
            base = max(revisions, key=lambda c: c["revision"], default=None)
            lineage = (1, None) if base is None else (base["revision"] + 1, base["revision"])
        elif approved is None:
            raise Refusal("no_approved_contract", "an amendment revises the approved contract; a draft before any approval is draft_contract's")
        else:
            base, lineage = approved, (max(c["revision"] for c in revisions) + 1, approved["revision"])
        if (doc["revision"], doc["parent_revision"]) != lineage:
            raise Refusal("request_invalid", f"this draft is revision {lineage[0]}, with parent {lineage[1]}" if draft else
                          f"an amendment is revision {lineage[0]}, with the approved revision {lineage[1]} as its parent")
        for what, name, label, content in VERSIONED if base is not None else ():  # a label names one content (module docstring)
            kept, recorded = label(base["document"]), max(label(c["document"]) for c in revisions)
            if _same(content(doc), content(base["document"])):
                if label(doc) != kept:
                    raise Refusal("request_invalid", f"the {what} is the {'revised' if draft else 'approved'} revision's, so it keeps {name} {kept} (G-6)")
            elif label(doc) <= recorded:
                raise Refusal("request_invalid", f"a changed {what} takes a new {name}, above every recorded one ({recorded}): a label never names two (G-6)")
        defect = references(doc, self._core._templates()) or self._recorded_references(doc)
        if defect is not None:  # task 2a: every draft the router writes, a first one or an amendment
            raise Refusal("contract_inconsistent", defect)
        self._core._store.insert("contract_revisions", {"topic_id": tid, "revision": doc["revision"], "parent_revision": doc["parent_revision"],
                                                  "protocol_revision": doc["protocol_revision"], "framing_version": doc["facet_map"]["framing_version"],
                                                  "content_hash": doc["content_hash"], "document": doc, "status": "draft", "created_at": doc["created_at"]})
        for facet in doc["facet_map"]["facets"]:
            self._core._store.insert("facets", {"topic_id": tid, "contract_revision": doc["revision"], "facet_id": facet["facet_id"], **_importance(facet)})
        for o in doc["obligations"]:
            self._core._store.insert("obligations", {
                "topic_id": tid, "contract_revision": doc["revision"], "obligation_id": o["obligation_id"], "template_id": o["template"]["template_id"],
                "template_version": o["template"]["template_version"], "claim_type": o["template"]["claim_type"], "facet_ids": o["facet_ids"],
                "stopping_profile_id": o["stopping_profile_id"], "exploratory": o["exploratory"], **_importance(o)})
        against = None if approved is None else contract_compatibility(approved["document"], doc)
        self._core._audit("contract_drafted" if draft else "amendment_proposed", now, {"revision": doc["revision"], "against_approved": against}, topic_id=tid)
        return {"status": "recorded", "topic_id": tid, "revision": doc["revision"], "against_approved": against}

    def _recorded_references(self, doc: dict) -> str | None:
        """The references a draft makes to the topic's record (task 2a), checked
        when it is written and again when it is approved: the confirmed brief
        its decision record names was confirmed by exactly the decision it
        names and, until the first approval, still stands — current, or
        superseded only by a compatible version (flow S1, S3; task 2a-repair
        F1); after it, no later confirmation replaced it (_record_replacements;
        archived, or succeeded in lineage alone, it still serves): neither a
        contract approval's impact nor its work sees briefs, so an amendment
        names the replacement, a reframe (F1-R, task 2a-repair-3; G-6); a
        proposed method design is a document its proposer, a primary
        invocation of the topic, committed — its bytes among what one of its
        own commit receipts validated (F3)."""
        brief, tid = doc["decision_record"]["objective"]["confirmed_brief"], doc["topic_id"]
        row = self._core._one("intake_briefs", {"topic_id": tid, "brief_id": brief["brief_id"], "version": brief["version"]})
        if row is None or row["confirmed_by_decision_id"] != brief["confirmed_by"]:
            return f"the decision record names brief {brief['brief_id']} v{brief['version']} as confirmed by {brief['confirmed_by']}, which the topic's record does not"
        if self._core._one("contract_revisions", {"topic_id": tid, "status": "approved"}) is None:
            lapsed = self._brief_standing(tid, brief["brief_id"], brief["version"])
            lapsed = None if lapsed in COMPATIBLE else lapsed
        else:
            replaced = self._core._one("brief_replacements", {"topic_id": tid, "brief_id": brief["brief_id"], "version": brief["version"]})
            lapsed = replaced and f"replaced by the confirmation {replaced['replaced_by_decision_id']}"
        if lapsed:
            return f"the decision record names brief {brief['brief_id']} v{brief['version']}, which no longer stands ({lapsed})"
        proposal = doc["method_design"].get("proposal")
        if proposal is not None:
            ref, inv = proposal["document"], self._core._one("invocations", {"invocation_id": proposal["proposed_by"]})
            if inv is None or inv["topic_id"] != tid or inv["kind"] not in boundary.PRIMARY or not any(
                    ref["content_hash"] in r["receipt"]["validation"]["validated_hashes"] for r in self._core._store.select("operation_receipts", {"invocation_id": inv["invocation_id"]})):
                return f"the method-design proposal is not a document {proposal['proposed_by']}, a primary invocation of this topic, committed"
            stored = self._core._one("artifacts", {"content_hash": ref["content_hash"]})  # recorded by that commit
            if (stored["size_bytes"], stored["media_type"]) != (ref["size_bytes"], ref["media_type"]):
                return "the method-design proposal is not the document recorded: another size or media type"
        return None

    # -- pins ----------------------------------------------------------------------
    def _pin_status(self, inv: dict) -> str:
        """`current`, or how the invocation's pinned contract revision (or,
        before any contract, brief version) stands now, as the recorded
        impacts say (_standing); a closed brief carries no work, nor does a
        brief whose lineage is no longer the topic's confirmed one."""
        if inv["admission_context"] == "contract/1":
            pinned = self._core._one("contract_revisions", {"topic_id": inv["topic_id"], "revision": inv["contract_revision"]})
            if pinned["status"] == "approved":
                return "current"
            return self._standing("contract", inv["topic_id"], inv["contract_revision"]) or "compatible"
        return self._brief_standing(inv["topic_id"], inv["brief_ref"], inv["brief_version"])

    def _brief_standing(self, topic_id: str, brief_id: str, version: int) -> str:
        """How a brief version stands now, for work pinned to it and for what
        names it (a draft, a scoping report; task 2a-repair F1)."""
        pinned = self._core._one("intake_briefs", {"topic_id": topic_id, "brief_id": brief_id, "version": version})
        current = self._core._one("intake_briefs", {"topic_id": topic_id, "status": "confirmed"})
        if pinned["status"] == "confirmed":
            return "current"
        if pinned["status"] == "superseded" and current is not None and current["brief_id"] == brief_id:  # its own lineage is current
            return self._standing("brief", topic_id, version, brief_id) or "lineage_only"
        return pinned["status"]

    def _record_replacements(self, d: dict, current: dict, now: str) -> None:
        """In the confirmation `d` of `current`: every version of the topic
        confirmed before it, of any brief, that it does not succeed in
        lineage alone is replaced, once and for good (DDL brief_replacements;
        task 2a-repair-3) — no archival or later confirmation undoes it."""
        for row in self._core._store.select("intake_briefs", {"topic_id": d["topic_id"]}):
            if row["confirmed_by_decision_id"] not in (None, d["decision_id"]) and brief_compatibility(row["document"], current["document"]) not in COMPATIBLE \
                    and self._core._one("brief_replacements", {"topic_id": d["topic_id"], "brief_id": row["brief_id"], "version": row["version"]}) is None:
                self._core._store.insert("brief_replacements", {"topic_id": d["topic_id"], "brief_id": row["brief_id"], "version": row["version"],
                                                          "replaced_by_decision_id": d["decision_id"], "recorded_at": now})

    def _standing(self, kind: str, topic_id: str, version: int, brief_id: str | None = None) -> str | None:
        """How what is pinned to a superseded `version` stands, as the impacts
        recorded since its supersession list it (module docstring): None
        while every one classed it compatible; otherwise the first
        incompatible class one gave it, which no later approval undoes; or
        `unrecorded` if none lists it."""
        key = "revision" if kind == "contract" else "version"
        listed = [entry["classification"] for impact in self._core._store.select("amendment_impacts", {"topic_id": topic_id, "kind": kind})
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
            key, compat, brief_id, rows = "revision", contract_compatibility, None, [c for c in self._core._store.select("contract_revisions", {"topic_id": tid}) if c["approved_by_decision_id"]]
            pin = lambda inv: inv["contract_revision"] if inv["admission_context"] == "contract/1" else None  # noqa: E731
        else:
            key, compat, brief_id = "version", brief_compatibility, superseded["brief_id"]
            rows = [b for b in self._core._store.select("intake_briefs", {"topic_id": tid, "brief_id": brief_id}) if b["confirmed_by_decision_id"]]
            pin = lambda inv: inv["brief_version"] if inv["brief_ref"] == brief_id else None  # noqa: E731
        # how each earlier version stood until now: the superseded one stood; any other as the recorded impacts say — what one made stale stays stale
        prior = {r[key]: None if r[key] == superseded[key] else self._standing(kind, tid, r[key], brief_id) for r in rows if r[key] != current[key]}
        status = {r[key]: prior[r[key]] or compat(r["document"], current["document"]) for r in rows if r[key] in prior}
        stood = {v for v, was in prior.items() if was is None}
        invocations = self._core._store.select("invocations", {"topic_id": tid})
        pinned = {i["invocation_id"]: pin(i) for i in invocations}
        doc = {"impact_version": "amendment-impact/1", "decision_id": d["decision_id"], "topic_id": tid, "kind": kind, "classification": status[superseded[key]],
               "superseded": {key: superseded[key], "content_hash": superseded["content_hash"]}, "current": {key: current[key], "content_hash": current["content_hash"]},
               "standing": [{key: v, "classification": status[v]} for v in sorted(stood)],
               "work": [self._fence(i, status[pinned[i["invocation_id"]]], d, now) for i in invocations
                        if i["state"] not in ENDED and pinned[i["invocation_id"]] in status],
               "coverage": [{"observation_id": o["observation_id"], "disposition": DISPOSITION[status[pinned[o["invocation_id"]]]]}
                            for o in self._core._store.select("search_observations", {"topic_id": tid}) if pinned[o["invocation_id"]] in stood]}
        if kind == "brief":
            doc["brief_id"] = brief_id  # the brief its standing is of
        if kind == "contract":
            listed = lambda rev: rev in stood  # noqa: E731
            doc["screening_labels"] = [{"assessment_id": a["assessment_id"], "contract_revision": a["contract_revision"], "decision": a["decision"],
                                        "disposition": DISPOSITION[status[a["contract_revision"]]]}
                                       for a in self._core._store.select("screening_assessments", {"topic_id": tid}) if listed(a["contract_revision"])]
            doc["reopened_exclusions"] = [a["assessment_id"] for a in doc["screening_labels"] if a["decision"] == "exclude" and a["disposition"] != "valid"]
            doc["claims"] = [{"claim_id": c["claim_id"], "revision": c["revision"], "status": c["status"], "disposition": DISPOSITION[status[pinned[c["producer_invocation_id"]]]]}
                             for c in self._core._store.select("claims", {"topic_id": tid}) if listed(pinned[c["producer_invocation_id"]]) and c["status"] != "superseded"]
            doc["verifications"] = [{"verification_receipt_id": v["verification_receipt_id"], "disposition": DISPOSITION[status[pinned[v["verifier_invocation_id"]]]]}
                                    for v in self._core._store.select("verification_receipts", {"topic_id": tid}) if listed(pinned[v["verifier_invocation_id"]])]
            doc["dossiers"] = [{"dossier_revision": x["dossier_revision"], "contract_revision": x["contract_revision"], "disposition": "not_current"}
                               for x in self._core._store.select("dossiers", {"topic_id": tid}) if listed(x["contract_revision"])]
            doc["reservations_closed"] = []
            for r in self._core._store.select("reservations", {"topic_id": tid}):
                if r["closed_at"] is None and r["contract_revision"] != current["revision"]:
                    self._core._store.update("reservations", {"reservation_id": r["reservation_id"]}, {"closed_at": now, "close_reason": f"revision superseded by {d['decision_id']}"})
                    doc["reservations_closed"].append(r["reservation_id"])
            doc["export_generations"] = [{"manifest_id": e["manifest_id"], "generation": e["generation"], "options_revision": e["options_revision"]}
                                         for e in self._core._store.select("outbox_events", {"topic_id": tid})]
        self._core._store.insert("amendment_impacts", {"decision_id": d["decision_id"], "topic_id": tid, "kind": kind, "classification": doc["classification"],
                                                 "document": doc, "recorded_at": now})
        return {"impact": {"classification": doc["classification"], "work": doc["work"]}}

    def _fence(self, inv: dict, status: str, d: dict, now: str) -> dict:
        """Admitted work pinned to a superseded version: it completes under its
        pins, or it is fenced — its cancellation requested (router) while it can
        still be; a staged result is refused at commit instead."""
        entry = {"invocation_id": inv["invocation_id"], "state": inv["state"], "disposition": "completes_under_pins" if status in COMPATIBLE else "fenced",
                 "cancel_requested": False}
        if entry["disposition"] == "fenced" and inv["cancel_requested_at"] is None and inv["state"] in ("admitted", "launching", "running", "outcome_unknown"):
            self._core._cancel_in_transaction({"invocation_id": inv["invocation_id"], "requested_by": "router", "reason": f"pins superseded by {d['decision_id']}"}, now)
            entry["cancel_requested"] = True
        return entry
