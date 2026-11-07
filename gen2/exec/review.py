"""Review view, builder and the operator's presentation: a fresh checkpoint reads one exact dossier revision and its
substance, records one sufficiency review, and a human reads that review and its evidence before approving.

Trace: 2e2-min design O16.3, O16.4; flow S7 (a fresh scientific review of substantive sufficiency); INVARIANTS E-6 (operands
shown), G-8 (the review and the approval bind the exact revision and hash), C-9 (the model authors no revision, hash or pin);
BOUNDARIES Primary (action-bearing evidence raw) and Operator (completion is an informed human decision). Oracle: the
persisted dossier row and the retained artifact bytes from the Router's reads; the router's own checks of the committed review.
Limits: the model gives an outcome and a summary only. Evidence appears as bounded excerpts of the retained bytes (the cut is
recorded, never silent). `present` shows what is recorded; it does not decide whether the review agrees with its own outcome.
"""
from __future__ import annotations

from typing import Callable, Mapping, Sequence

from gen2.core import canonical
from gen2.exec.common import Refused, derived_id, scaffold

FAMILIES = ("dossiers", "verification_receipts", "completion_records", "claims")
OUTCOMES = ("sufficient", "insufficient")
EXCERPT = 3000
Stage = Callable[[bytes, str], Mapping]
Read = Callable[[Mapping], "bytes | None"]   # artifact_ref -> retained bytes (the topic spool's read)


def _excerpt(read: Read, ref: Mapping) -> dict:
    data = read(ref)
    shown = {"content_hash": ref["content_hash"], "media_type": ref["media_type"], "size_bytes": ref["size_bytes"]}
    if data is None:
        return {**shown, "text": None, "cut": False}
    return {**shown, "text": data[:EXCERPT].decode("utf-8", "replace"), "cut": len(data) > EXCERPT}


def _records(records: Sequence[Mapping], read: Read) -> list[dict]:
    return [{"kind": r["kind"], "subject_ref": r["subject_ref"], "subject_revision": r["subject_revision"],
             "outcome": r["assessment"]["outcome"], "summary": r["assessment"]["summary"],
             "evidence": [_excerpt(read, ref) for ref in r["evidence_refs"]]} for r in records]


def review_view(admission: Mapping, records: Mapping[str, Sequence[Mapping]], text_of: Callable[[str], str], read: Read, *,
                invocation_id: str, dossier_revision: int) -> dict:
    """The named dossier revision (exactly one row, never the latest by guess) with its rule results, the load-bearing claims,
    the receipts behind them and every completion record with its assessment text and evidence excerpts."""
    if admission.get("context") != "contract/1":
        raise Refused("a review view needs a contract/1 admission")
    rows = [r for r in records["dossiers"] if r["dossier_revision"] == dossier_revision]
    if len(rows) != 1:
        raise Refused(f"dossier revision {dossier_revision} is not exactly one row")
    dossier = rows[0]
    if dossier["invocation_id"] == invocation_id:
        raise Refused("the reviewer produced this dossier")
    latest: dict[str, Mapping] = {}
    for c in records["claims"]:
        if c["claim_id"] not in latest or c["revision"] > latest[c["claim_id"]]["revision"]:
            latest[c["claim_id"]] = c
    return {"dossier": {"revision": dossier["dossier_revision"], "content_hash": dossier["content_hash"],
                        "contract_revision": dossier["contract_revision"], "result": dossier["document"]["result"]},
            "claims": [{"claim_ref": c["claim_id"], "revision": c["revision"], "status": c["status"], "tier": c["required_access_tier"],
                        "text": text_of(c["text_ref"])} for _, c in sorted(latest.items()) if c["load_bearing"]],
            "receipts": [{"receipt_id": r["verification_receipt_id"], "claim_ref": r["claim_id"], "claim_revision": r["claim_revision"],
                          "verdict": r["verdict"], "access_tier": r["access_tier"], "use": r["use"], "cited_spans": r["cited_spans"]}
                         for r in records["verification_receipts"]],
            "completion_records": _records([r for r in records["completion_records"] if r["kind"] != "sufficiency_review"], read)}


def present(records: Mapping[str, Sequence[Mapping]], read: Read, *, dossier_revision: int) -> dict:
    """What the operator reads before approving this exact revision: the dossier's gates, and every sufficiency review bound to
    its revision and hash with its summary (an `insufficient` one included) and the evidence it cites. Read from the Router."""
    rows = [r for r in records["dossiers"] if r["dossier_revision"] == dossier_revision]
    if len(rows) != 1:
        raise Refused(f"dossier revision {dossier_revision} is not exactly one row")
    dossier = rows[0]
    reviews = [r for r in records["completion_records"] if r["kind"] == "sufficiency_review"
               and (r["subject_revision"], r["subject_hash"]) == (dossier_revision, dossier["content_hash"])]
    result = dossier["document"]["result"]
    return {"dossier": {"revision": dossier_revision, "content_hash": dossier["content_hash"], "state": result["state"],
                        "gates": [{"gate": g["gate"], "state": g["state"]} for g in result["gates"]]},
            "reviews": _records(reviews, read),
            "approvable": bool(reviews)}


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
