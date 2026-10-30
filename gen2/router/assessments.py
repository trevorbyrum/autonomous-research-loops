"""2c-2a/2d-1 admission/recording, not judgment production (2e) or arithmetic.

Flow S4/S4.5, methodology §4, E-3/E-7; see ACCOUNTING.md. Runs in the
existing commit transaction; capability, fencing, artifacts and clock belong
to the Router. Only its primary-class invocations supply semantic labels.
"""
from typing import Callable, Mapping, Protocol

from gen2.core.instants import utc_instant_ns
from gen2.router.boundary import Refusal


# section/table, identity, predecessor identity, predecessor description
RECORDS = (
    ("semantic_assessments", "assessment_id", (), ""),
    ("source_lifecycle", "disposition_id", ("work_id", "source_version"), "lifecycle"),
    ("registry_dispositions", "disposition_id", ("registry_kind", "registry_id"), "registry"),
    ("obligation_assessments", "record_id", ("obligation_id",), "obligation"),
    ("branch_windows", "association_id", (), ""),
)


class Rows(Protocol):
    def insert(self, table: str, row: Mapping[str, object]) -> None: ...


class AssessmentCore(Protocol):
    _store: Rows
    def _one(self, table: str, where: Mapping[str, object]) -> dict | None: ...
    def _work_of_topic(self, work_id: str, topic_id: str) -> bool: ...


class Assessments:
    def __init__(self, core: AssessmentCore) -> None:
        self._core = core

    def bind_evidence(self, payload: dict, bind: Callable[[dict, str], None]) -> None:
        for section, identity, _, _ in RECORDS:
            for record in payload.get(section, []):
                for ref in record.get("evidence_refs", []):
                    bind(ref, f"{record[identity]}: its evidence")

    def validate(self, payload: dict, inv: dict) -> None:
        self._validate_branch_windows(payload, inv)
        self._validate_obligations(payload, inv)
        records = payload.get("semantic_assessments", []) + payload.get("source_lifecycle", []) + payload.get("registry_dispositions", [])
        if not records:
            return
        contract = self._core._one("contract_revisions", {"topic_id": inv["topic_id"], "revision": inv["contract_revision"]})
        for record in records:
            pins = (record["contract_revision"], record["framing_version"], record["eligibility_protocol_version"])
            if pins != (inv["contract_revision"], contract["framing_version"], contract["document"]["eligibility_protocol"]["protocol_version"]):
                raise Refusal("payload_invalid", "semantic assessment protocol/framing differs from the invocation's pins")
            if "work_id" in record:
                if not self._core._work_of_topic(record["work_id"], inv["topic_id"]):
                    raise Refusal("cross_topic", "semantic assessment subject was not retrieved by this topic")
            lineage = record.get("lineage")
            if lineage is not None and lineage["related_work_id"] is not None:
                if not self._core._work_of_topic(lineage["related_work_id"], inv["topic_id"]):
                    raise Refusal("cross_topic", "related lineage work was not retrieved by this topic")

    def write(self, payload: dict, inv: dict, operation_id: str, now: str) -> dict:
        # One validation of retained operands, under the existing writer fence.
        self.validate(payload, inv)
        written = {}
        for table, identity, predecessor_key, label in RECORDS:
            records = payload.get(table, [])
            for record in records:
                if predecessor_key and record["supersedes_id"] is not None:
                    prior = self._core._one(table, {identity: record["supersedes_id"]})
                    if prior is None or any(prior[k] != v for k, v in
                            {"topic_id": inv["topic_id"], **{k: record[k] for k in predecessor_key}}.items()):
                        raise Refusal("payload_invalid", f"{label} predecessor must exist for this topic and identity")
                    if utc_instant_ns(prior["created_at"]) >= utc_instant_ns(now):
                        raise Refusal("payload_invalid", f"{label} successor must be dated after its predecessor")
                row = {k: v for k, v in record.items() if k != "lineage"}
                if table == "source_lifecycle" and record["related_work_id"] is not None and not self._core._work_of_topic(record["related_work_id"], inv["topic_id"]):
                    raise Refusal("cross_topic", "related lifecycle work was not retrieved by this topic")
                if table == "obligation_assessments":
                    row = {"disposition": None, "state": None, **row, "confidence": dict(record["confidence"])}
                    if row["confidence"]["basis"] == "recorded_assessment":
                        row["confidence"]["assessed_by_invocation_id"] = inv["invocation_id"]
                self._core._store.insert(table, {**row, "topic_id": inv["topic_id"], "actor_kind": "primary",
                    "invocation_id": inv["invocation_id"], "recorded_by_operation_id": operation_id, "created_at": now})
                if record.get("lineage") is not None:
                    self._core._store.insert("source_lineage", {"assessment_id": record["assessment_id"], **record["lineage"]})
            if records:
                written[table] = [r[identity] for r in records]
        return written

    def _validate_branch_windows(self, payload: dict, inv: dict) -> None:
        records = payload.get("branch_windows", [])
        if not records:
            return
        for record in records:
            branch = self._core._one("registry_dispositions", {"disposition_id": record["branch_disposition_id"]})
            if branch is None or (branch["topic_id"], branch["registry_kind"], branch["registry_id"]) != (inv["topic_id"], "branch", record["registry_id"]):
                raise Refusal("payload_invalid", "association differs from its same-topic registered branch identity")
            window = self._core._one("invocations", {"invocation_id": record["window_invocation_id"]})
            if window is None or (window["topic_id"], window["kind"], window["admission_context"]) != (inv["topic_id"], "research_pass", "contract/1"):
                raise Refusal("payload_invalid", "association needs a same-topic contract-admitted research window")
            contract = self._core._one("contract_revisions", {"topic_id": inv["topic_id"], "revision": window["contract_revision"]})
            if contract is None or contract["status"] not in ("approved", "superseded") or contract["approved_by_decision_id"] is None:
                raise Refusal("payload_invalid", "research window's exact approved contract provenance is missing")

    def _validate_obligations(self, payload: dict, inv: dict) -> None:
        records = payload.get("obligation_assessments", [])
        if not records:
            return
        contract = self._core._one("contract_revisions", {"topic_id": inv["topic_id"], "revision": inv["contract_revision"]})
        doc = contract["document"]
        for record in records:
            pins = (record["contract_revision"], record["contract_content_hash"], record["framing_version"], record["eligibility_protocol_version"])
            if pins != (inv["contract_revision"], contract["content_hash"], contract["framing_version"], doc["eligibility_protocol"]["protocol_version"]):
                raise Refusal("payload_invalid", "obligation record differs from its invocation's exact contract pins")
            if self._core._one("obligations", {"topic_id": inv["topic_id"], "contract_revision": inv["contract_revision"], "obligation_id": record["obligation_id"]}) is None:
                raise Refusal("payload_invalid", "obligation does not exist in this topic's pinned contract")
            confidence = record["confidence"]
            if confidence["basis"] == "recorded_assessment":
                scheme = doc.get("confidence_scheme")
                if scheme is None or confidence["scheme"] != {"scheme_id": scheme["scheme_id"], "version": scheme["version"]} or confidence["label"] not in scheme["labels"]:
                    raise Refusal("payload_invalid", "confidence differs from the approved contract scheme")
            elif not confidence["reason"].strip():
                raise Refusal("payload_invalid", "unknown confidence requires its reason")
