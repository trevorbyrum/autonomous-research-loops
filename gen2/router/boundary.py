"""The router's validation boundary: every check that needs no transaction.

Trace: design review §5 steps 1-2 (an authenticated, size-bounded envelope;
expensive validation outside the write transaction, bound to exact hashes
and validator/policy versions); gen2/store/README.md "What stays router
logic" (schema validation, hash truth RA6, timestamps A11, the A10 semantic
comparisons); EXPORT-API.md §5 (export-manifest/2 validation and extension
admission before outbox admission); BOUNDARIES.md Router (authority from
capability, never a caller-supplied label), Secondary/delegate agents (no
evidence-write capability), Verifier; INVARIANTS C-2, C-3, C-9, C-12, C-13,
RG-4, RG-5, E-2, H-5.

Everything here is a pure function of its arguments (parsed documents, rows
the caller read, a spool reader, registries). A failed check raises Refusal
with one of the response vocabulary's reasons; nothing here writes.
"""
from __future__ import annotations

from typing import Mapping, NamedTuple

from gen2.core import canonical, instants, pagination
from gen2.core.canonical import CanonicalizationError

TIER = {"bibliographic": 1, "abstract": 2, "full_text": 3, "reproduced": 4}
STAGE = {"metadata": 1, "abstract": 2, "full_text": 3}
SCOPE_OF_KIND = {"research_pass": "research", "discovery": "discovery", "verification": "verification", "checkpoint": "checkpoint"}

# Which invocation kinds may carry each outcome-document section. The kind is
# the committing invocation's stored kind, found through its capability —
# never a field of the request (BOUNDARIES.md Router). Primary-class work
# (research passes, checkpoints) proposes evidence and governance records; a
# verifier commits only its own verification receipts and the holds its
# disagreements raise (V-5); discovery and delegate work holds no
# evidence-write capability at all (BOUNDARIES.md Secondary/delegate agents)
# — its observations go through record_observation, its packets through
# result_refs.
PRIMARY = frozenset({"research_pass", "checkpoint"})
CONTRACT = frozenset({"contract/1"})
SCOPING = frozenset({"pre-contract/1"})
EITHER = frozenset({"contract/1", "pre-contract/1"})


class Record(NamedTuple):
    """One assessment-shaped record kind: its storage, predecessor rule and
    admission policy in one entry. Every field is required, so an entry that
    omits its policy cannot be built; `common` says whether the shared pin,
    topic and lineage validation covers it (a kind with its own obligation or window
    validation says False).
    `defaults` are the columns an inserted row gets when its record omits them."""
    section: str
    identity: str
    predecessor_key: tuple[str, ...]
    label: str
    kinds: frozenset[str]
    contexts: frozenset[str]
    common: bool
    defaults: Mapping[str, object]


RECORDS = (
    Record("semantic_assessments", "assessment_id", (), "", PRIMARY, CONTRACT, True, {}),
    Record("source_lifecycle", "disposition_id", ("work_id", "source_version"), "lifecycle", PRIMARY, CONTRACT, True, {}),
    Record("registry_dispositions", "disposition_id", ("registry_kind", "registry_id"), "registry", PRIMARY, CONTRACT, True, {}),
    Record("obligation_assessments", "record_id", ("obligation_id",), "obligation", PRIMARY, CONTRACT, False, {"disposition": None, "state": None}),
    Record("branch_windows", "association_id", (), "", PRIMARY, CONTRACT, False, {}),
)
# The other sections; RECORDS' sections are admitted by their own entries.
SECTION_KINDS = {
    "claims": (PRIMARY, EITHER),
    "claim_promotions": (PRIMARY, CONTRACT),
    "claim_source_links": (PRIMARY, CONTRACT),
    "decision_receipts": (PRIMARY, CONTRACT),
    "screening_assessments": (PRIMARY, CONTRACT),
    "review_triggers": (PRIMARY, EITHER),
    "review_closures": ({"checkpoint"}, CONTRACT),
    "scoping_reports": ({"research_pass"}, SCOPING),
    "source_proposals": (frozenset({"research_pass", "checkpoint", "discovery", "delegate"}), EITHER),
    "exports": (PRIMARY, CONTRACT),
    "holds": (frozenset({"research_pass", "checkpoint", "verification"}), EITHER),
    "verification_receipts": ({"verification"}, CONTRACT),
    "source_artifacts": (PRIMARY, CONTRACT),
    "quote_checks": ({"verification"}, CONTRACT),
    "detailed_check_records": ({"verification"}, CONTRACT),
    "source_extractions": (frozenset({"research_pass", "checkpoint", "verification", "discovery", "delegate"}), CONTRACT),
    "extraction_validations": ({"verification"}, CONTRACT),
    "extraction_validations_v2": ({"verification"}, CONTRACT),
}

# Sections only an independent (parentless) invocation may commit.
INDEPENDENT = frozenset({"detailed_check_records", "extraction_validations", "extraction_validations_v2"})


class Refusal(Exception):
    """A request the router refuses before (or instead of) any change."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def normalize(value: object, reason: str, *, member_domain: bool = True) -> object:
    """The value as the router hashes and stores it: its RFC 8785 form parsed
    back (C-13). Refuses what JCS cannot represent faithfully (NaN, lone
    surrogates, integers beyond 2**53-1, duplicate keys in text and NUL in
    decoded member names). The default covers every Router document route."""
    try:
        raw = value if isinstance(value, (bytes, str)) else canonical.canonical_bytes(value, member_domain=member_domain)
        return canonical.parse_json_strict(raw, member_domain=member_domain)
    except (CanonicalizationError, TypeError, ValueError) as exc:
        raise Refusal(reason, f"not canonical JSON (C-13): {exc}") from None


def require_schema(schemas, value: object, target: str, reason: str) -> None:
    errors = schemas.errors(value, target)
    if errors:
        raise Refusal(reason, f"{target}: {'; '.join(errors[:3])}")


def staged(spool, content_hash: str, size: int | None = None, *, topic_id: str, media_type: str | None = None) -> bytes:
    """The bytes staged for `topic_id` under `content_hash`, re-hashed here
    (hash truth): the label must be the SHA-256 of the bytes, and `size`
    their length. The spool is topic-scoped (C-9), so another topic's bytes
    are not staged for this one. With `media_type`, the spool's own record of
    the bytes' media type must be it (task 1c)."""
    raw = spool.read(content_hash, topic_id=topic_id)
    if raw is None:
        raise Refusal("payload_missing", f"nothing is staged for {topic_id} under {content_hash}")
    try:
        digest = canonical.bytes_digest(raw)
    except TypeError:
        raise Refusal("payload_digest_mismatch", f"the spool returned {type(raw).__name__}, not bytes, for {content_hash}") from None
    if digest != content_hash:
        raise Refusal("payload_digest_mismatch", f"the bytes staged under {content_hash} hash to {digest}")
    if size is not None and len(raw) != size:
        raise Refusal("payload_digest_mismatch", f"{content_hash} is {len(raw)} bytes staged, not the {size} declared")
    if media_type is not None and spool.media_type(content_hash, topic_id=topic_id) != media_type:
        raise Refusal("payload_invalid", f"{content_hash} is staged as {spool.media_type(content_hash, topic_id=topic_id)}, not {media_type}")
    return bytes(raw)


def instant(value: str) -> int:
    return instants.utc_instant_ns(value)


def check_sections(payload: dict, kind: str, admission_context: str, parent_invocation_id: str | None) -> None:
    sections = {**SECTION_KINDS, **{r.section: (r.kinds, r.contexts) for r in RECORDS}}
    for section, (kinds, contexts) in sections.items():
        if not payload.get(section):
            continue
        if kind not in kinds:
            raise Refusal("kind_not_permitted", f"a {kind} invocation cannot commit {section}")
        if admission_context not in contexts:
            if admission_context == "pre-contract/1":
                raise Refusal("kind_not_permitted", f"pre-contract/1 work records scoping material only, not {section} (C-12)")
            raise Refusal("kind_not_permitted", f"{section} are pre-contract work's (flow S2), not {admission_context}'s")
        if section in INDEPENDENT and parent_invocation_id is not None:
            raise Refusal("kind_not_permitted", f"{section} requires independent verification")


def check_span_offsets(spans: list[dict]) -> None:
    """Operator ruling 2026-10-18: exact integer values, never rounded."""
    for span in spans:
        for name, minimum in (("start", 0), ("end", 1)):
            try:
                canonical.identity_integer(span[name], minimum=minimum)
            except CanonicalizationError:
                raise Refusal("payload_invalid", f"span {name} must be an integer in [{minimum}, 9007199254740991]") from None


def check_verification_receipt(doc: dict, invocation_id: str, capability_id: str, topic_id: str) -> None:
    """RG-5: a receipt is committed by the verifier it names, under that
    verifier's own capability, about work of its topic — so a producer can
    never certify its own claim, whatever a document says."""
    check_span_offsets(doc["cited_spans"])
    rid = doc["verification_receipt_id"]
    if doc["topic_id"] != topic_id:
        raise Refusal("cross_topic", f"{rid} is about topic {doc['topic_id']}")
    if doc["verifier_invocation_id"] != invocation_id or doc["verifier_capability_id"] != capability_id:
        raise Refusal("capability_invocation_mismatch", f"{rid} names verifier {doc['verifier_invocation_id']}; only that verifier's own capability commits it")
    if doc["producer_invocation_id"] == invocation_id:
        raise Refusal("kind_not_permitted", f"{rid}: a producer never verifies its own claim (RG-5)")


def check_decision_receipt(doc: dict, spec_document: dict | None, *, invocation_id: str, topic_id: str, operation_id: str,
                           qualifications, questions: set) -> None:
    """D-1, D-4, D-5: a receipt of the committing invocation, of its topic,
    under a stored spec whose hash is true and whose pinned question is one
    the invocation's pinned bundle carries (`questions`: (id, version, hash)
    triples; an unknown or altered question is neither); qualified authority
    only under a live qualification of exactly its provider, class and spec."""
    rid = doc["decision_receipt_id"]
    if doc["topic_id"] != topic_id:
        raise Refusal("cross_topic", f"{rid} is about topic {doc['topic_id']}")
    if doc["invocation_id"] != invocation_id:
        raise Refusal("capability_invocation_mismatch", f"{rid} records a call of {doc['invocation_id']}, not of the committing invocation")
    if spec_document is None:
        raise Refusal("payload_invalid", f"{rid}: no stored DecisionSpec has hash {doc['spec']['spec_hash']}")
    if canonical.logical_hash(spec_document) != doc["spec"]["spec_hash"]:
        raise Refusal("payload_invalid", f"{rid}: the stored DecisionSpec does not hash to {doc['spec']['spec_hash']} (hash truth)")
    question = spec_document["question"]
    if (question["question_id"], question["version"], question["content_hash"]) not in questions:
        raise Refusal("payload_invalid", f"{rid}: its spec's question {question['question_id']} v{question['version']} is not in the invocation's "
                                         "pinned question registry under that hash (D-1)")
    authorization = doc["authorization"]
    if authorization["authority_level"] == "qualified" and not qualifications.is_qualified(
            provider=doc["provider"], decision_class=doc["decision_class"], spec_hash=doc["spec"]["spec_hash"],
            qualification_ref=authorization["qualification_ref"]):
        raise Refusal("payload_invalid", f"{rid}: no live qualification record qualifies {doc['provider']}/{doc['decision_class']} for this spec; "
                                         "a qualification reference alone is not qualification (D-4, INVARIANTS §13)")
    if doc["outcome"]["commit_operation_id"] not in (None, operation_id):
        raise Refusal("payload_invalid", f"{rid}: its committed action is recorded by {doc['outcome']['commit_operation_id']}, not by this operation (D-2)")


def check_screening(assessment: dict, protocol: dict, receipt: dict | None, spec_document: dict | None, admitted: dict) -> None:
    """A10: an assessment's criterion results are the pinned eligibility
    protocol's criteria, each assessed no earlier than its stage allows;
    an exclusion rests on a criterion not met (missing information is
    unknown, never excluded — the protocol's `unknown_not_excluded`); an
    inclusion has none not met. A provider-written assessment is exactly the
    answer of its screening receipt, about this work, under a spec whose
    protocol context is the committing invocation's admission: its topic,
    its contract revision and that revision's content hash (`admitted`:
    {"topic_id", "contract": {"revision", "content_hash"}}), and this
    protocol version. Qualification makes a provider an authority for one
    spec; it does not make that spec apply to another contract (C-12, D-1,
    D-4; Astra 1b review A3)."""
    aid = assessment["assessment_id"]
    criteria = {c["criterion_id"]: c for c in protocol["criteria"]}
    version = protocol["protocol_version"]
    results = assessment["criterion_results"]
    foreign = sorted(set(results) - set(criteria))
    if foreign:
        raise Refusal("payload_invalid", f"{aid}: criteria {foreign} are not in eligibility protocol version {version}")
    for cid, result in results.items():
        if result != "unknown" and STAGE[criteria[cid]["stage"]] > STAGE[assessment["stage"]]:
            raise Refusal("payload_invalid", f"{aid}: {cid} is a {criteria[cid]['stage']} criterion and cannot be {result} at the {assessment['stage']} stage")
    not_met = [cid for cid, result in results.items() if result == "not_met"]
    if assessment["decision"] == "exclude" and not not_met:
        raise Refusal("payload_invalid", f"{aid}: an exclusion needs a criterion not met; missing information is unknown, not excluded")
    if assessment["decision"] == "include" and not_met:
        raise Refusal("payload_invalid", f"{aid}: an inclusion cannot have criteria not met ({not_met})")
    if assessment["actor_kind"] != "decision_provider":
        return
    if receipt is None:
        raise Refusal("payload_invalid", f"{aid}: its decision receipt {assessment['decision_receipt_id']} is not in this commit")
    answer = receipt["provider_response"]["answer"] or {}
    if (receipt["decision_class"] != "screening" or receipt["subject"] != {"kind": "work", "ref": assessment["work_id"]}
            or answer.get("selected_option_id") != assessment["decision"] or receipt["action"] != "commit_reversible_action"):
        raise Refusal("payload_invalid", f"{aid}: the assessment is not its screening receipt's committed answer about this work (A10)")
    spec_protocol = (spec_document or {}).get("protocol") or {}
    if spec_protocol.get("topic_id") != admitted["topic_id"]:
        raise Refusal("payload_invalid", f"{aid}: its receipt's spec is for topic {spec_protocol.get('topic_id')}, not {admitted['topic_id']} (A10)")
    contract = spec_protocol.get("contract") or {}
    if contract.get("revision") != admitted["contract"]["revision"]:
        raise Refusal("payload_invalid", f"{aid}: its receipt's spec is for contract revision {contract.get('revision')}, "
                                         f"not the admitted revision {admitted['contract']['revision']} (A10)")
    if contract.get("content_hash") != admitted["contract"]["content_hash"]:
        raise Refusal("payload_invalid", f"{aid}: its receipt's spec pins contract hash {contract.get('content_hash')}, "
                                         f"not the admitted revision's {admitted['contract']['content_hash']} (A10)")
    if spec_protocol.get("eligibility_protocol_version") != version:
        raise Refusal("payload_invalid", f"{aid}: its receipt's spec is not for eligibility protocol version {version} (A10)")


def check_observation(observation: dict, events: list[dict], *, request_bytes: bytes | None = None) -> None:
    """A10 and H-5: the request identity is the hash of the request (two
    different requests never share one); an observed result set's count is
    exactly the retrieval events captured with it, so no count stands without
    the identities behind it (E-2: an uncaptured count is an unknown
    denominator, and the station records the set as partial or the coverage
    as unknown instead); a set not observed carries no events and no count,
    which the store also refuses (RG-4). And the admission contract
    (check_page_outcome): what an observation must carry to assert how a
    search ended."""
    oid = observation["observation_id"]
    identity = canonical.logical_hash(observation["request"]) if request_bytes is None else canonical.bytes_digest(request_bytes)
    if identity != observation["request_identity"]:
        raise Refusal("payload_invalid", f"{oid}: request_identity is not the hash of its request (H-5)")
    if observation["ended_at"] is not None and instant(observation["ended_at"]) < instant(observation["started_at"]):
        raise Refusal("payload_invalid", f"{oid}: it ended before it started")
    records = [event["provider_record_id"] for event in events]
    if len(set(records)) != len(records):
        raise Refusal("payload_invalid", f"{oid}: a provider record is captured twice")
    try:
        opaque = pagination.retained_request(observation)
    except ValueError as exc:
        raise Refusal("payload_invalid", str(exc)) from None
    if not opaque:
        check_page_outcome(observation)
    if observation["completeness"] == "unobserved":
        if events or observation["result_count"] is not None:
            raise Refusal("payload_invalid", f"{oid}: an unobserved result set has no captured records and no count; unknown is not zero (RG-U)")
        return
    if observation["result_count"] != len(events):
        raise Refusal("payload_invalid", f"{oid}: result_count {observation['result_count']} is not the {len(events)} retrieval events captured "
                                         "with it; a count without its captured identities is not a denominator (E-2)")


def check_page_outcome(observation: dict) -> None:
    """The admission contract of one observation (Gate D #3; task 2b-repair-13d, Astra R13B-2) — what it must carry to say how its
    search ended or continued. The store's CHECKs say the same (a test holds the two equal, case by case).

    * COHERENCE. A page that could not be read FAILED, and only such a page; a cursor is carried by a continuation or a page cap and
      by nothing else, and only from a page that was read; an end is reported by a page read whole, and a page nothing was read from
      reports none (a lane restating an end it reported earlier included). Whether THIS PAGE was read whole (`completeness`) never
      stands for the population being exhausted (`page_outcome`), so a partial page or an unknown end never establishes exhaustion (RG-4).
    * THE REQUEST DISCRIMINATOR. The request names its type, from a closed set (core/pagination.py), and what `end_unknown` means
      depends on it: for a `find`, a paged request, that its end is not known; for any other type, which does not page, there is no end
      to know. Only a find's page can be an `exhausted`, a `continuation` or a `limit_reached`.
    * THE CAPTURE ACKNOWLEDGEMENT. A page read `complete`, and so every `exhausted` end, names the gateway's durable row of the request
      (`gateway_call_ref`): an answer the gateway did not durably capture is at most a partial lower bound (INVARIANTS RG-4, E-2). The
      reference acknowledges a durable call row, not a retained response artifact.
    * THE CURSOR DOMAIN. A continuation's cursor is an integer from 0 to the JSON bound, or a string of 1..8000 characters, none of them
      NUL, other than the finished-lane sentinel (gen2/core/pagination.py; the command schema holds only the shape).

    What this does NOT establish: that an outcome the observation asserts is the one the gateway's answer implied. The router sees the
    command, never the reply. A coherent false claim by trusted station code is outside router semantic enforcement; sampled
    independent re-derivation can detect it when retained evidence supports that check, and missing required evidence is itself an
    audit failure (INVARIANTS E-2; gen2/router/README.md, "What an observation command is trusted for"; the retrieval-audit evidence
    requirement is task 2e2's)."""
    oid, outcome, completeness, coverage = observation["observation_id"], observation["page_outcome"], observation["completeness"], observation["coverage_state"]
    if (coverage in ("provider_unavailable", "auth_failed", "unknown")) != (outcome == "failed"):
        raise Refusal("payload_invalid", f"{oid}: coverage {coverage} with page outcome {outcome}; a page nothing could be read from is failed, and only it is")
    if (outcome in ("continuation", "limit_reached")) != (observation["continuation"] is not None):
        raise Refusal("payload_invalid", f"{oid}: page outcome {outcome} with continuation {observation['continuation']!r}; a cursor belongs to a continuation or a page cap, and they carry one")
    if outcome in ("continuation", "limit_reached") and completeness == "unobserved":
        raise Refusal("payload_invalid", f"{oid}: a page nothing was read from has no continuation")
    if outcome == "exhausted" and completeness != "complete":
        raise Refusal("payload_invalid", f"{oid}: an exhausted end is reported by a page read whole, not a {completeness} one (RG-4)")
    kind = pagination.request_type(observation["request"])
    if kind is None:
        raise Refusal("payload_invalid", f"{oid}: its request names no type from {list(pagination.REQUEST_TYPES)}; what an end means depends on the request")
    if outcome in pagination.PAGING_OUTCOMES and kind not in pagination.PAGED_REQUEST_TYPES:
        raise Refusal("payload_invalid", f"{oid}: a {kind} request does not page, so its answer cannot be {outcome}; its only outcome is end_unknown")
    if completeness == "complete" and not observation["gateway_call_ref"]:
        raise Refusal("payload_invalid", f"{oid}: a page read whole, an exhausted end among them, names the gateway's durable row of its request; "
                                         "an answer the gateway did not capture is at most a partial lower bound (RG-4, E-2)")
    if observation["continuation"] is not None and (problem := pagination.cursor_problem(observation["continuation"]["cursor"])):
        raise Refusal("payload_invalid", f"{oid}: {problem}")


def check_manifest(manifest: dict, topic_id: str, extensions, bundle_raw: bytes, schemas) -> str:
    """EXPORT-API.md §5, §7: a manifest names only admitted extensions, and
    its bundle is the staged export-bundle/1 document, canonical, of this
    topic, whose JCS hash is the manifest's. Returns the manifest hash (JCS
    over the whole manifest: it carries no hash of its own)."""
    mid = manifest["manifest_id"]
    if manifest["topic_id"] != topic_id:
        raise Refusal("cross_topic", f"{mid} exports topic {manifest['topic_id']}")
    for connector_id, connector in sorted(manifest["expected_connectors"].items()):
        if connector["connector_type"] == "extension":
            impl = connector["implementation"]
            if not extensions.is_admitted(module=impl["module"], review_ref=impl["review_ref"]):
                raise Refusal("payload_invalid", f"{mid}: extension connector {connector_id} ({impl['module']}) is not admitted; "
                                                 "a module and review name establish neither (EXPORT-API.md §7)")
    bundle = normalize(bundle_raw, "payload_invalid")
    if canonical.canonical_bytes(bundle) != bundle_raw:
        raise Refusal("payload_invalid", f"{mid}: its bundle is not staged in its canonical (JCS) form")
    require_schema(schemas, bundle, "export-bundle.schema.json", "payload_invalid")
    if bundle["bundle_id"] != manifest["bundle"]["bundle_id"] or bundle["topic_id"] != topic_id:
        raise Refusal("payload_invalid", f"{mid}: the staged bundle is {bundle['bundle_id']} of {bundle['topic_id']}")
    return canonical.logical_hash(manifest)


def work_id(identity_scheme: str, identity_value: str) -> str:
    """A new work's id (task 2a): derived from its identity, so topics that
    retrieve the same record register one work without coordinating (E-3:
    identity duplicates only; normalizing an identity is the dedup method's)."""
    return "wrk_" + canonical.logical_hash({"identity_scheme": identity_scheme, "identity_value": identity_value}).split(":", 1)[1]


def trigger_identity(topic_id: str, trigger: dict) -> str:
    """The review-trigger identity (DDL review_triggers): a deterministic hash
    of (topic, reason, cause ref, source revision), so a replayed trigger
    collides with the first instead of opening anything new (RG-1b(e))."""
    return canonical.logical_hash({"topic_id": topic_id, "reason_code": trigger["reason_code"],
                                   "cause_ref": trigger["cause_ref"], "source_revision": trigger["source_revision"]})


def hold_row(*, hold_id: str, topic_id: str | None, subject_ref: str, hold_class: str,
             cause: str, recoverability: str, required_authority: str, owner: str,
             deadline_at: str, clears_when: str, created_at: str,
             capability_fact_id: str | None = None, created_by_operation_id: str | None = None) -> dict:
    return {"hold_id": hold_id, "topic_id": topic_id, "subject_ref": subject_ref, "hold_class": hold_class,
        "cause": cause, "recoverability": recoverability, "required_authority": required_authority, "owner": owner,
        "deadline_at": deadline_at, "clears_when": clears_when, "created_at": created_at,
        "capability_fact_id": capability_fact_id, "created_by_operation_id": created_by_operation_id}
