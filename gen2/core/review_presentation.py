"""The operator's view of a dossier's review: the one pure builder, shared by the Router's status and the executors' driver.

Trace: flow S7; BOUNDARIES Operator (completion is an informed human decision); INVARIANTS G-8, E-6; 2e1/2e2 carried
obligation: the operator sees the actual sufficiency review, an `insufficient` one included, and the evidence it cites, never a
boolean. Oracle: the persisted dossier row, the completion rows and the retained bytes the caller read. Limits: pure over rows
and a byte reader the caller supplies, so it reads no store itself; evidence appears as bounded excerpts, the cut marked, and
bytes not retained shown as missing. It does not judge whether a review agrees with its own outcome.
"""
from __future__ import annotations

from typing import Callable, Mapping, Sequence

EXCERPT = 3000
Read = Callable[[Mapping], "bytes | None"]   # artifact_ref -> retained bytes (the topic spool's read)


def excerpt(read: Read, ref: Mapping) -> dict:
    data = read(ref)
    shown = {"content_hash": ref["content_hash"], "media_type": ref["media_type"], "size_bytes": ref["size_bytes"]}
    if data is None:
        return {**shown, "text": None, "cut": False}
    return {**shown, "text": data[:EXCERPT].decode("utf-8", "replace"), "cut": len(data) > EXCERPT}


def assessments(records: Sequence[Mapping], read: Read) -> list[dict]:
    return [{"kind": r["kind"], "subject_ref": r["subject_ref"], "subject_revision": r["subject_revision"],
             "outcome": r["assessment"]["outcome"], "summary": r["assessment"]["summary"],
             "evidence": [excerpt(read, ref) for ref in r["evidence_refs"]]} for r in records]


def present(records: Mapping[str, Sequence[Mapping]], read: Read, *, dossier_revision: int) -> dict:
    """The dossier's gates, and every sufficiency review bound to its exact revision and hash with its outcome, summary and the
    evidence it cites. `approvable` is whether any such review exists; it says nothing of what the review concluded."""
    rows = [r for r in records["dossiers"] if r["dossier_revision"] == dossier_revision]
    if len(rows) != 1:
        raise ValueError(f"dossier revision {dossier_revision} is not exactly one row")
    dossier = rows[0]
    reviews = [r for r in records["completion_records"] if r["kind"] == "sufficiency_review"
               and (r["subject_revision"], r["subject_hash"]) == (dossier_revision, dossier["content_hash"])]
    result = dossier["document"]["result"]
    return {"dossier": {"revision": dossier_revision, "content_hash": dossier["content_hash"], "state": result["state"],
                        "gates": [{"gate": g["gate"], "state": g["state"]} for g in result["gates"]]},
            "reviews": assessments(reviews, read), "approvable": bool(reviews)}
