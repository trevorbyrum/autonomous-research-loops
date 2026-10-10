"""2c-2a/2d-1 admission/recording, not judgment production (2e) or arithmetic.

Flow S4/S4.5, methodology §4, E-3/E-7; see ACCOUNTING.md. Runs in the
existing commit transaction; capability, fencing, artifacts and clock belong
to the Router. Only its primary-class invocations supply semantic labels.
"""
from typing import Callable, Mapping, Protocol

from gen2.core.instants import utc_instant_ns
from gen2.router.boundary import PRIMARY, Refusal


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
        for record in payload.get("obligation_assessments", []):
            for ref in record["evidence_refs"]:
                bind(ref, f"{record['record_id']}: its evidence")
        for record in payload.get("semantic_assessments", []):
            for ref in record["evidence_refs"]:
                bind(ref, f"{record['assessment_id']}: its evidence")
        for record in payload.get("source_lifecycle", []):
            for ref in record["evidence_refs"]:
                bind(ref, f"{record['disposition_id']}: its evidence")
        for record in payload.get("registry_dispositions", []):
            for ref in record["evidence_refs"]:
                bind(ref, f"registry {record['disposition_id']}: its evidence")

    def validate(self, payload: dict, inv: dict) -> None:
        self._validate_obligations(payload, inv)
        records = payload.get("semantic_assessments", []) + payload.get("source_lifecycle", []) + payload.get("registry_dispositions", [])
        if not records:
            return
        if inv["kind"] not in PRIMARY or inv["admission_context"] != "contract/1":
            raise Refusal("kind_not_permitted", "semantic assessments require contract-admitted primary work")
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

    def write_lifecycle(self, payload: dict, inv: dict, operation_id: str, now: str) -> dict:
        self.validate(payload, inv)
        written = []
        for record in payload.get("source_lifecycle", []):
            if record["related_work_id"] is not None and not self._core._work_of_topic(record["related_work_id"], inv["topic_id"]):
                raise Refusal("cross_topic", "related lifecycle work was not retrieved by this topic")
            if record["supersedes_id"] is not None:
                prior = self._core._one("source_lifecycle", {"disposition_id": record["supersedes_id"]})
                if prior is None or (prior["topic_id"], prior["work_id"], prior["source_version"]) != (inv["topic_id"], record["work_id"], record["source_version"]):
                    raise Refusal("payload_invalid", "lifecycle predecessor must exist for this topic and source version")
                if utc_instant_ns(prior["created_at"]) >= utc_instant_ns(now):
                    raise Refusal("payload_invalid", "lifecycle successor must be dated after its predecessor")
            self._core._store.insert("source_lifecycle", {**record, "topic_id": inv["topic_id"], "actor_kind": "primary",
                "invocation_id": inv["invocation_id"], "recorded_by_operation_id": operation_id, "created_at": now})
            written.append(record["disposition_id"])
        return {"source_lifecycle": written} if written else {}

    def write_dispositions(self, payload: dict, inv: dict, operation_id: str, now: str) -> dict:
        self.validate(payload, inv)
        written = []
        for record in payload.get("registry_dispositions", []):
            if record["supersedes_id"] is not None:
                prior = self._core._one("registry_dispositions", {"disposition_id": record["supersedes_id"]})
                if prior is None or (prior["topic_id"], prior["registry_kind"], prior["registry_id"]) != (inv["topic_id"], record["registry_kind"], record["registry_id"]):
                    raise Refusal("payload_invalid", "registry predecessor must exist for this topic, kind and identity")
                if utc_instant_ns(now) <= utc_instant_ns(prior["created_at"]):
                    raise Refusal("payload_invalid", "registry successor must be dated after its predecessor")
            self._core._store.insert("registry_dispositions", {**record, "topic_id": inv["topic_id"], "actor_kind": "primary",
                "invocation_id": inv["invocation_id"], "recorded_by_operation_id": operation_id, "created_at": now})
            written.append(record["disposition_id"])
        result = self._write_obligations(payload, inv, operation_id, now)
        if written:
            result["registry_dispositions"] = written
        return result

    def write(self, payload: dict, inv: dict, operation_id: str, now: str) -> list[str]:
        self.validate(payload, inv)
        written = []
        for record in payload.get("semantic_assessments", []):
            row = {k: v for k, v in record.items() if k != "lineage"}
            self._core._store.insert("semantic_assessments", {**row, "topic_id": inv["topic_id"], "actor_kind": "primary",
                "invocation_id": inv["invocation_id"], "recorded_by_operation_id": operation_id, "created_at": now})
            if record["lineage"] is not None:
                self._core._store.insert("source_lineage", {"assessment_id": record["assessment_id"], **record["lineage"]})
            written.append(record["assessment_id"])
        return written

    def _validate_obligations(self, payload: dict, inv: dict) -> None:
        records = payload.get("obligation_assessments", [])
        if not records:
            return
        if inv["kind"] not in PRIMARY or inv["admission_context"] != "contract/1":
            raise Refusal("kind_not_permitted", "obligation judgments require contract-admitted primary work")
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

    def _write_obligations(self, payload: dict, inv: dict, operation_id: str, now: str) -> dict:
        self._validate_obligations(payload, inv)  # repeat under the writer fence
        written = []
        for record in payload.get("obligation_assessments", []):
            if record["supersedes_id"] is not None:
                prior = self._core._one("obligation_assessments", {"record_id": record["supersedes_id"]})
                if prior is None or (prior["topic_id"], prior["obligation_id"]) != (inv["topic_id"], record["obligation_id"]):
                    raise Refusal("payload_invalid", "obligation predecessor must exist for this topic and obligation")
                prior_instant = utc_instant_ns(prior["created_at"])
                if prior_instant >= utc_instant_ns(now):
                    raise Refusal("payload_invalid", "obligation successor must be dated after its predecessor")
            confidence = dict(record["confidence"])
            if confidence["basis"] == "recorded_assessment":
                confidence["assessed_by_invocation_id"] = inv["invocation_id"]
            self._core._store.insert("obligation_assessments", {"disposition": None, "state": None, **record,
                "confidence": confidence, "topic_id": inv["topic_id"], "actor_kind": "primary", "invocation_id": inv["invocation_id"],
                "recorded_by_operation_id": operation_id, "created_at": now})
            written.append(record["record_id"])
        return {"obligation_assessments": written} if written else {}
