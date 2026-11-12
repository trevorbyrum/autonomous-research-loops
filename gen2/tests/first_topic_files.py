"""Generate proposed first-topic inputs from T18 helpers and PHASE2-TOPIC-DRAFT, without activating or approving anything.

Test/input preparation only (S1-S3/S7, G-2/4/8/11/13): the pending sentinel is deliberately not an inventory.
Usage: python -m gen2.tests.first_topic_files DESTINATION; the runbook instantiates runtime operands separately.
"""
import copy
import json
import re
import sys
from pathlib import Path

from gen2.app import workflow
from gen2.core import canonical
from gen2.core.instants import utc_now
from gen2.tests import children, offline_world
from gen2.tests.offline_run import prompt_pins
from gen2.tests.router_fixtures import RouterTestCase, ratings

TOPIC = "first-topic:research-to-design"
BRIEF, RATING = "brief-research-design", "opd_ft_rate01"
DECISIONS = {"brief_confirmation": "opd_ft_brief01", "scope_approval": "opd_ft_scope01", "rating_approval": RATING,
             "contract_approval": "opd_ft_cntr01", "completion_approval": "opd_ft_done01"}
SENTINEL = {"PLACEHOLDER": "OPERATOR_STOPPING_RULE_RULING_PENDING", "not_for_staging": True,
            "replace_with": "A nonempty JSON array of operator-selected canonical wrk_ ids, never bare DOIs."}
FACETS = (("frameworks", "Framework validation and failure modes", "Named research-to-design frameworks", "Empirical validation versus assertion", "EV-1"),
          ("parallel", "Boundary conditions of parallel exploration", "Parallel design exploration", "Early commitment", "EV-2"),
          ("conflicts", "Handling contradictory research inputs", "Explicit contradiction-handling methods", "Convergent-input methods", "EV-3"))


def generate(prepared_at):
    sections = dict(part.split("\n", 1) for part in re.split(r"^## ", children.path("docs/gen2/PHASE2-TOPIC-DRAFT.md").read_text(), flags=re.M)[1:])
    bullets = lambda name: [s.strip() for s in sections[name].strip().removeprefix("- ").split("\n- ")]
    constraints = bullets("Constraints")
    constraints[2] = "First walk uses Semantic Scholar alone through the dedicated gateway; other lanes in the draft are deferred."
    assumptions = bullets("Surfaced assumptions")
    assumptions[-1] = "The decision layer remains disabled; live model dispatch still requires qualified authority, approved deployment and the present operator."
    brief = RouterTestCase.brief_document(TOPIC, brief_id=BRIEF, created_at=prepared_at,
        objective_in_operator_words=sections["Objective (operator's words)"].strip(), feeds=sections["Decision this feeds"].strip(),
        evidence_that_would_change_it=bullets("What evidence would change the operator's mind"), constraints=constraints,
        operator_hypotheses=[{"statement": h, "testable_as": h} for h in bullets("Operator hypotheses (as testables)")], surfaced_assumptions=assumptions)
    bundle = copy.deepcopy(offline_world.bundle(workflow.executor_entries(prompt_pins()), version=3))
    bundle["questions"] = []  # disabled decision layer: no invented provider answers
    method = {"template_id": "MD-scoping-initiation", "template_version": 1,
              "families": [{"family": "scoping_mapping", "role": "primary"}, {"family": "truth_discovery", "role": "added", "purpose": "initiation"}]}
    bundle["templates"]["method_design"].append(method)
    raw = (formatted(SENTINEL) + "\n").encode("utf-8")
    ref = {"content_hash": canonical.bytes_digest(raw), "size_bytes": len(raw), "media_type": "application/json"}
    doc = offline_world.contract(2, 1, sentinel=ref)
    doc.update(topic_id=TOPIC, created_at=prepared_at)
    record = doc["decision_record"]
    record.update(decision_owner="operator", objective={"operator_words": brief["objective_in_operator_words"],
        "confirmed_brief": {"brief_id": BRIEF, "version": 1, "confirmed_by": DECISIONS["brief_confirmation"]}},
        feeds={"kind": "learning_objective", "description": brief["feeds"]})
    for field in ("evidence_that_would_change_it", "constraints", "surfaced_assumptions"):
        record[field] = [{"entry_id": f"{ {'evidence_that_would_change_it': 'EV', 'constraints': 'CON', 'surfaced_assumptions': 'ASM'}[field]}-{i}", "text": text}
                         for i, text in enumerate(brief[field], 1)]
    record["operator_hypotheses"] = [{"entry_id": f"HYP-{i}", "statement": h["statement"], "as_testable": h["testable_as"]}
                                     for i, h in enumerate(brief["operator_hypotheses"], 1)]
    framework = {"nodes": [{"node_id": "N-input", "label": "Research findings", "kind": "situation"},
                           {"node_id": "N-design", "label": "Design choices and evaluated outcomes", "kind": "decision_outcome"}], "links": []}
    facets, obligations, cells = [], [], []
    for n, (name, label, intervention, comparator, evidence) in enumerate(FACETS, 1):
        fid, oid, lid = f"F-{name}", f"O-{n}", f"L-{n}"
        framework["links"].append({"link_id": lid, "from_node": "N-input", "to_node": "N-design", "key_question": label + ": what is supported and under which conditions?"})
        importance = {"proposed": None, "operator_rating": {"band": "critical", "score": 8, "operator_decision_id": RATING}}
        facets.append({"facet_id": fid, "label": label, "kind": "effect", "importance": copy.deepcopy(importance)})
        obligation = copy.deepcopy(doc["obligations"][0])
        obligation.update(obligation_id=oid, slots={"population": "Software, product and system design studies and methodological accounts",
            "intervention": intervention, "comparator": comparator, "outcome": "Evidence, limitations, context and failure cases"},
            text=label + ": distinguish evaluated outcomes from methodological assertions; retain contradictions and unvalidated proposals.",
            facet_ids=[fid], traces_to={"decision_record_entries": [evidence], "framework_links": [lid]}, importance=importance)
        obligations.append(obligation)
        cells.append({"facet_id": fid, "question_type": "effect", "state": "covered", "obligation_ids": [oid]})
    doc["facet_map"].update(analytic_framework=framework, facets=facets, coverage_matrix={"question_types": ["effect"], "cells": cells},
        deliberately_out=[{"item_id": "OUT-playbook", "description": "An applicable playbook or gen-2-specific applicability claim", "reason": "Survey/dossier only; a playbook is a separately scoped follow-on."}])
    doc["obligations"] = obligations
    doc["eligibility_protocol"].update(search_scope="Research-informed software/product/system design, including parallel paths, contradictory inputs and failures; no arbitrary date cutoff.",
        criteria=[{"criterion_id": "EC-scope", "kind": "semantic", "stage": "abstract", "description": "Connects research findings or methodological inputs to product/system design decisions."},
                  {"criterion_id": "EC-evidence", "kind": "semantic", "stage": "abstract", "description": "Describes a framework, evaluation, contradiction-handling method or failure; retain unvalidated assertions explicitly as assertions."}])
    doc["applicability_rules"][0].update(obligation_ids=[o["obligation_id"] for o in obligations], target_context="Survey of research-informed product/system design",
        support_factors=["Report each study's context and evaluated outcomes"], transportability_assumptions=["No automatic transfer to gen-2 or a general playbook"],
        uncertainty_requirement="Retrieval-only sentinel completion says nothing about unknown-remainder recall; substantive sufficiency needs fresh review and operator approval.")
    doc["surveillance_policy"]["freshness_requirement"]["description"] = "Re-check before acting on this survey; currency remains unknown until separately implemented."
    doc["confidence_scheme"]["scheme_id"] = "research-design-confidence"
    doc["method_design"]["template"] = {k: v for k, v in method.items() if k != "families"}
    doc["method_design"]["families"][0].update(family="scoping_mapping", integration_point="Survey dossier: framework validation and parallel-design boundary conditions")
    doc["method_design"]["families"][1]["integration_point"] = "Contradictory research inputs and failure cases"
    doc["content_hash"] = canonical.content_hash(doc)
    first = copy.deepcopy(doc)
    first.update(revision=1, parent_revision=None)
    for entry in first["facet_map"]["facets"] + first["obligations"]:
        entry["importance"]["operator_rating"] = None
    first["content_hash"] = canonical.content_hash(first)
    templates = {kind: {"decision_id": did, "topic_id": TOPIC, "kind": kind, "disposition": "approved",
        "subject": {"kind": {"brief_confirmation": "intake_brief", "scope_approval": "scoping_report", "completion_approval": "dossier"}.get(kind, "contract_revision"),
                    "ref": None, "revision": None, "hash": None}, "decided_at": None, "notes": None, "payload": None} for kind, did in DECISIONS.items()}
    return {"bundle": bundle, "topic": {"topic_id": TOPIC, "priority": 5},
            "brief": {"document": brief, "owner_operator_id": "REPLACE_WITH_OPERATOR_NAME", "review_deadline": None},
            "contract-r1": {"document": first}, "contract-r2": {"document": doc}, "ratings": ratings(doc), "decisions": templates, "sentinel": SENTINEL}


def formatted(value, depth=0):
    """Indent outer structure; retain nested records on one line (use json.tool for an expanded review)."""
    if depth >= 2 or not isinstance(value, (dict, list)) or not value:
        return json.dumps(value, ensure_ascii=False)
    left, right, entries = ("{", "}", [json.dumps(k) + ": " + formatted(v, depth + 1) for k, v in value.items()]) if isinstance(value, dict) else ("[", "]", [formatted(v, depth + 1) for v in value])
    return left + "\n" + ",\n".join("  " * (depth + 1) + v for v in entries) + "\n" + "  " * depth + right


if __name__ == "__main__":
    target = Path(sys.argv[1])
    target.mkdir(parents=True, exist_ok=True)
    for name, value in generate(utc_now()).items():
        (target / (name + ".json")).write_text(formatted(value) + "\n")
