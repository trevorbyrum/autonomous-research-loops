"""Research builder: the research judgment plus recorded facts become the pass's outcome sections.

Trace: 2e2-min design O14.8; flow S4 steps 1-7; Astra T11 F3 (source_artifacts committed here, bound to the retained
response bytes and the retrieval lineage, before re-access); INVARIANTS C-9 (no model-authored id, hash, pin or
attribution), V-9 (evidence origin recorded apart from the method), V-10 (production is the commit's). Oracle: the
closed outcome/1 sections (outcome-document.schema.json) and the router's own checks, which stay the authority
(cross-topic works, obligation existence, confidence scheme, protocol criteria). Limits: ids are derived from
(invocation, kind, index); a `not_satisfied` or `unknown` obligation outcome both record as `unresolved`, the
verbatim outcome being kept in `subject`; a tier-less load-bearing claim is refused, not defaulted.
"""
from __future__ import annotations

from typing import Callable, Mapping

from gen2.exec import artifacts
from gen2.exec.common import Refused, derived_id, scaffold

PROPOSER = "research_pass.research"
CONTRIBUTIONS = ("answer", "confidence", "applicability", "options", "question_formulation", "boundary_condition", "contradiction")
DISPOSITION = {"satisfied": "supported", "not_satisfied": "unresolved", "unknown": "unresolved"}
CAPS = {"claim_source_links": 256, "source_artifacts": 64}


def _confidence(contract: Mapping, label: str) -> dict:
    scheme = contract["confidence_scheme"]
    if scheme is not None and label in scheme["labels"]:
        return {"basis": "recorded_assessment", "scheme": {"scheme_id": scheme["scheme_id"], "version": scheme["version"]}, "label": label}
    return {"basis": "unknown", "reason": f"the pinned contract's scheme does not name the label {label!r}"}


def build_research(work: Mapping, judgment: Mapping, stage: artifacts.Stage) -> dict:
    """work-input/1 + judgment-research/1 -> outcome/1. Pure: the retained lineage of each work is in the view (`artifact_ref`, `lane`,
    `provider_record_id`), read and digest-checked by the parent; a work the view does not list cannot be cited."""
    inv, contract = work["invocation_id"], work["view"]["contract"]
    listed = {w["work_id"]: w for w in work["view"]["works"]}
    claims, drafts = [], []
    for n, claim in enumerate(judgment["claims"]):
        if claim["load_bearing"] and claim["required_access_tier"] is None:
            raise Refused(f"claim {claim['local_id']} is load-bearing without a required access tier")
        claim_id = derived_id("clm", inv, "claim", n)
        claims.append({"claim_id": claim_id, "revision": 1, "text_ref": artifacts.text_ref(stage, claim["text"]),
                       "load_bearing": claim["load_bearing"], "required_access_tier": claim["required_access_tier"]})
        for source in claim["sources"]:
            if source["contribution"] not in CONTRIBUTIONS:
                raise Refused(f"claim {claim['local_id']}: contribution {source['contribution']!r} is not one of {CONTRIBUTIONS}")
            if source["work_id"] not in listed:
                raise Refused(f"claim {claim['local_id']}: {source['work_id']} is not a work with a retained response in the view")
            drafts.append((claim_id, source))
    work_ids = sorted({source["work_id"] for _, source in drafts})
    if len(drafts) > CAPS["claim_source_links"] or len(work_ids) > CAPS["source_artifacts"]:
        raise Refused("this pass cites more links or sources than one commit carries")
    links = [{"claim_id": claim_id, "claim_revision": 1, "work_id": source["work_id"], "source_version": listed[source["work_id"]]["artifact_ref"]["content_hash"],
              "obligation_id": source["obligation_id"], "spans": source.get("spans", []), "contribution": source["contribution"],
              "evidence_origin_lineage": f"{listed[source['work_id']]['lane']}:{listed[source['work_id']]['provider_record_id']}"[:500],
              "analytical_method": None} for claim_id, source in drafts]
    pin = contract["revision"], contract["content_hash"], contract["framing_version"], contract["eligibility_protocol"]["protocol_version"]
    assessments = []
    for n, item in enumerate(judgment["obligations"]):
        evidence = [dict(listed[s["work_id"]]["artifact_ref"]) for _, s in drafts if s["obligation_id"] == item["obligation_id"]]
        unique = list({ref["content_hash"]: ref for ref in evidence}.values()) or [artifacts.text_ref(stage, item["summary"])]
        assessments.append({"record_id": derived_id("oa", inv, "obligation", n), "obligation_id": item["obligation_id"],
                            "subject": f"{item['obligation_id']}: {item['outcome']}", "contract_revision": pin[0], "contract_content_hash": pin[1],
                            "eligibility_protocol_version": pin[3], "framing_version": pin[2], "evidence_refs": unique,
                            "reason": item["summary"], "supersedes_id": None, "disposition": DISPOSITION[item["outcome"]],
                            "confidence": _confidence(contract, item["confidence"])})
    screening = [{"assessment_id": derived_id("asm", inv, "screening", n), "work_id": s["work_id"], "stage": s["stage"], "decision": s["decision"],
                  "reason_code": s["reason_code"], "criterion_results": s["criteria"], "actor_kind": "primary",
                  "decision_receipt_id": None, "supersedes_assessment_id": None} for n, s in enumerate(judgment["screening"])]
    triggers = [{"reason_code": code, "cause_ref": inv, "source_revision": work["view"]["state_revision"], "observed_at": work["view"]["as_of"]}
                for code in judgment["triggers"]]
    proposals = [{**p, "proposer": PROPOSER} for p in judgment["search_proposals"]]
    return scaffold(inv, work["topic_id"], next_queue_state=judgment["next_queue_state"], claims=claims, claim_source_links=links,
                    screening_assessments=screening, review_triggers=triggers, source_artifacts=[{"work_id": w, "source_version": listed[w]["artifact_ref"]["content_hash"], "artifact_ref": dict(listed[w]["artifact_ref"])} for w in work_ids],
                    obligation_assessments=assessments, search_proposals=proposals)


def research_builder(stage: artifacts.Stage) -> Callable[[Mapping, Mapping], dict]:
    """The job's Builder for the research purpose, closed over the child's stage."""
    return lambda work, judgment: build_research(work, judgment, stage)
