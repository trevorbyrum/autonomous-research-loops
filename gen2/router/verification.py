"""V-5/V-2 attention for attributed verifier verdicts (flow S4 step 8).

Router collaborator: no semantic judgments, clock or transaction of its own.
Writes run in the commit's existing writer fence; 2e2 owns deadline escalation.
"""
from typing import Mapping, Protocol

from gen2.core import canonical
from gen2.router import boundary
from gen2.router.detailed_checks import DetailedChecks


class Rows(Protocol):
    def insert(self, table: str, row: Mapping[str, object]) -> None: ...
    def select(self, table: str, where: "Mapping[str, object] | None" = None) -> list[dict]: ...


class VerificationCore(Protocol):
    _store: Rows
    def _one(self, table: str, where: Mapping[str, object]) -> dict | None: ...


class Verification:
    def __init__(self, core: VerificationCore) -> None:
        self._core = core

    def hold_ids(self, payload: dict, *, admitted: bool = False) -> list[str]:
        return [self._hold_id(doc) for doc in payload["verification_receipts"] if self._needs_hold(doc, admitted=admitted)]

    def _needs_hold(self, doc: dict, *, admitted: bool = False) -> bool:
        if doc["verdict"] != "supports":
            return True
        if doc["extraction"]["method"] == "canonical_bytes":
            return False
        # Receipt effects are planned before insertion. SQL 32/33 and the
        # Router must admit each new basis later in this same transaction;
        # otherwise no operation receipt or hold survives. Same-outcome bases
        # do not exist yet. Successful admission guarantees basis membership,
        # including text references; alarms affect promotion, not membership.
        # Actual writes re-read membership, including retained history.
        if admitted:
            return False
        row = self._core._one("verification_receipts", {"verification_receipt_id": doc["verification_receipt_id"]})
        return row is None or not DetailedChecks(self._core)._basis_member(row, boundary.TIER)

    def _hold_id(self, doc: dict) -> str:
        return "hold_" + canonical.logical_hash({"verification_receipt_id": doc["verification_receipt_id"]})[7:]

    def write_holds(self, payload: dict, op_id: str, now: str) -> dict:
        for doc in payload["verification_receipts"]:
            if not self._needs_hold(doc):
                continue
            # Receipts have already passed SQL 03's claim/topic/producer binding.
            claim = self._core._one("claims", {"claim_id": doc["claim"]["claim_id"], "revision": doc["claim"]["claim_revision"]})
            producer = self._core._one("invocations", {"invocation_id": claim["producer_invocation_id"]})
            lease = self._core._one("leases", {"lease_id": producer["lease_id"]})
            missing = doc["verdict"] == "cannot_assess_at_required_tier"
            pending = doc["verdict"] == "supports" and doc["extraction"]["method"] != "canonical_bytes"
            missing = missing or pending
            self._core._store.insert("holds", {
                "hold_id": self._hold_id(doc), "topic_id": doc["topic_id"], "subject_ref": "verification:" + doc["verification_receipt_id"],
                "hold_class": "judgment", "cause": ("verification missing content: " if missing else "verification disagreement: ") +
                    ("extraction evidence not durably bound" if pending else doc["verdict"]),
                "recoverability": "needs_remediation" if missing else "needs_decision", "required_authority": "primary",
                "owner": "primary:" + lease["station_id"], "deadline_at": producer["deadline_at"],
                "clears_when": "independent verification with the required content" if missing else "primary adjudication of this verification disagreement",
                "created_at": now, "created_by_operation_id": op_id})
        return {"verification_holds": self.hold_ids(payload)} if payload["verification_receipts"] else {}
