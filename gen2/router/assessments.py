"""2c-2a admission/recording, not judgment production (2e) or arithmetic.

Flow S4/S4.5, methodology §4, E-3/E-7; see ACCOUNTING.md. Runs in the
existing commit transaction; capability, fencing, artifacts and clock belong
to the Router. Only its primary-class invocations supply semantic labels.
"""
from typing import Callable, Mapping, Protocol

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
        for record in payload.get("semantic_assessments", []):
            for ref in record["evidence_refs"]:
                bind(ref, f"{record['assessment_id']}: its evidence")

    def validate(self, payload: dict, inv: dict) -> None:
        records = payload.get("semantic_assessments", [])
        if not records:
            return
        if inv["kind"] not in PRIMARY or inv["admission_context"] != "contract/1":
            raise Refusal("kind_not_permitted", "semantic assessments require contract-admitted primary work")
        contract = self._core._one("contract_revisions", {"topic_id": inv["topic_id"], "revision": inv["contract_revision"]})
        for record in records:
            pins = (record["contract_revision"], record["framing_version"], record["eligibility_protocol_version"])
            if pins != (inv["contract_revision"], contract["framing_version"], contract["document"]["eligibility_protocol"]["protocol_version"]):
                raise Refusal("payload_invalid", "semantic assessment protocol/framing differs from the invocation's pins")
            if not self._core._work_of_topic(record["work_id"], inv["topic_id"]):
                raise Refusal("cross_topic", "semantic assessment subject was not retrieved by this topic")
            lineage = record["lineage"]
            if lineage is not None and lineage["related_work_id"] is not None:
                if not self._core._work_of_topic(lineage["related_work_id"], inv["topic_id"]):
                    raise Refusal("cross_topic", "related lineage work was not retrieved by this topic")

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
