"""Review view and builder: a fresh checkpoint reads one exact dossier revision and records one sufficiency review.

Trace: 2e2-min design O16.3, O16.4; flow S7; INVARIANTS G-8 (the review and the operator's approval bind the exact
revision and hash), C-9 (the model authors no revision, hash or pin). Oracle: the persisted dossier row from
`topic_records`, and the router's own checks (hash equals the dossier's, reviewer is not the dossier's producer).
Limits: the view shows gate states, not gate proof (the gates read records, never this text); it passes the document's
`result` through unchanged apart from dropping the rule bodies. The model gives an outcome and a summary only.
"""
from __future__ import annotations

from typing import Callable, Mapping, Sequence

from gen2.core import canonical
from gen2.exec.common import Refused, derived_id, scaffold

FAMILIES = ("dossiers", "verification_receipts", "completion_records")
OUTCOMES = ("sufficient", "insufficient")
Stage = Callable[[bytes, str], Mapping]


def review_view(admission: Mapping, records: Mapping[str, Sequence[Mapping]], *, invocation_id: str, dossier_revision: int) -> dict:
    """The named dossier revision (exactly one row, never the latest by guess), its gates, the receipts and records behind them."""
    if admission.get("context") != "contract/1":
        raise Refused("a review view needs a contract/1 admission")
    rows = [r for r in records["dossiers"] if r["dossier_revision"] == dossier_revision]
    if len(rows) != 1:
        raise Refused(f"dossier revision {dossier_revision} is not exactly one row")
    dossier = rows[0]
    if dossier["invocation_id"] == invocation_id:
        raise Refused("the reviewer produced this dossier")
    result = dossier["document"]["result"]
    return {"dossier": {"revision": dossier["dossier_revision"], "content_hash": dossier["content_hash"],
                        "contract_revision": dossier["contract_revision"], "state": result["state"],
                        "gates": [{"gate": g["gate"], "state": g["state"]} for g in result["gates"]]},
            "receipts": [{"receipt_id": r["verification_receipt_id"], "claim_ref": r["claim_id"], "claim_revision": r["claim_revision"],
                          "verdict": r["verdict"], "access_tier": r["access_tier"]} for r in records["verification_receipts"]],
            "completion_records": [{"kind": r["kind"], "subject_ref": r["subject_ref"], "outcome": r["assessment"]["outcome"]}
                                   for r in records["completion_records"]]}


def make_builder(stage: Stage) -> Callable[[Mapping, Mapping], dict]:
    """work-input/1 + judgment-review/1 -> outcome/1 with one `sufficiency_review` bound to the viewed revision and hash."""

    def build(work: Mapping, judgment: Mapping) -> dict:
        view = work["view"]["dossier"]
        if judgment["outcome"] not in OUTCOMES:
            raise Refused("a review is sufficient or insufficient")
        evidence = dict(stage(canonical.canonical_bytes(judgment), "application/json"))
        record = {"record_id": derived_id("cpl", work["invocation_id"], "sufficiency_review", 0), "kind": "sufficiency_review",
                  "contract_revision": view["contract_revision"], "subject_ref": work["topic_id"], "subject_revision": view["revision"],
                  "subject_hash": view["content_hash"], "assessment": {"outcome": judgment["outcome"], "summary": judgment["summary"]},
                  "evidence_refs": [evidence]}
        return scaffold(work["invocation_id"], work["topic_id"], completion_records=[record])
    return build
