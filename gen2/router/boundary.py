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

from gen2.core import canonical, instants
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
SECTION_KINDS = {
    "claims": PRIMARY,
    "claim_promotions": PRIMARY,
    "decision_receipts": PRIMARY,
    "screening_assessments": PRIMARY,
    "review_triggers": PRIMARY,
    "exports": PRIMARY,
    "holds": PRIMARY | {"verification"},
    "verification_receipts": frozenset({"verification"}),
}
# C-12: pre-contract (scoping) work records scoping material only —
# provisional claims (and the holds and trigger observations of its own
# pass); nothing that needs the approved protocol.
PRE_CONTRACT_SECTIONS = frozenset({"claims", "review_triggers", "holds"})


class Refusal(Exception):
    """A request the router refuses before (or instead of) any change."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def normalize(value: object, reason: str) -> object:
    """The value as the router hashes and stores it: its RFC 8785 form parsed
    back (C-13). Refuses what JCS cannot represent faithfully (NaN, lone
    surrogates, integers beyond 2**53-1, duplicate keys in text)."""
    try:
        raw = value if isinstance(value, (bytes, str)) else canonical.canonical_bytes(value)
        return canonical.parse_json_strict(raw)
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


def check_sections(payload: dict, kind: str, admission_context: str) -> None:
    for section, kinds in SECTION_KINDS.items():
        if not payload[section]:
            continue
        if kind not in kinds:
            raise Refusal("kind_not_permitted", f"a {kind} invocation cannot commit {section}")
        if admission_context == "pre-contract/1" and section not in PRE_CONTRACT_SECTIONS:
            raise Refusal("kind_not_permitted", f"pre-contract/1 work records scoping material only, not {section} (C-12)")


def check_verification_receipt(doc: dict, invocation_id: str, capability_id: str, topic_id: str) -> None:
    """RG-5: a receipt is committed by the verifier it names, under that
    verifier's own capability, about work of its topic — so a producer can
    never certify its own claim, whatever a document says."""
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


def check_observation(observation: dict, events: list[dict]) -> None:
    """A10 and H-5: the request identity is the hash of the request (two
    different requests never share one); an observed result set's count is
    exactly the retrieval events captured with it, so no count stands without
    the identities behind it (E-2: an uncaptured count is an unknown
    denominator, and the station records the set as partial or the coverage
    as unknown instead); a set not observed carries no events and no count,
    which the store also refuses (RG-4)."""
    oid = observation["observation_id"]
    if canonical.logical_hash(observation["request"]) != observation["request_identity"]:
        raise Refusal("payload_invalid", f"{oid}: request_identity is not the hash of its request (H-5)")
    if observation["ended_at"] is not None and instant(observation["ended_at"]) < instant(observation["started_at"]):
        raise Refusal("payload_invalid", f"{oid}: it ended before it started")
    records = [event["provider_record_id"] for event in events]
    if len(set(records)) != len(records):
        raise Refusal("payload_invalid", f"{oid}: a provider record is captured twice")
    if observation["completeness"] == "unobserved":
        if events or observation["result_count"] is not None:
            raise Refusal("payload_invalid", f"{oid}: an unobserved result set has no captured records and no count; unknown is not zero (RG-U)")
        return
    if observation["result_count"] != len(events):
        raise Refusal("payload_invalid", f"{oid}: result_count {observation['result_count']} is not the {len(events)} retrieval events captured "
                                         "with it; a count without its captured identities is not a denominator (E-2)")


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


def trigger_identity(topic_id: str, trigger: dict) -> str:
    """The review-trigger identity (DDL review_triggers): a deterministic hash
    of (topic, reason, cause ref, source revision), so a replayed trigger
    collides with the first instead of opening anything new (RG-1b(e))."""
    return canonical.logical_hash({"topic_id": topic_id, "reason_code": trigger["reason_code"],
                                   "cause_ref": trigger["cause_ref"], "source_revision": trigger["source_revision"]})
