"""Scope builder: the scoping judgment plus recorded facts become one `scoping_reports` entry.

Trace: 2e2-min design O14.7; flow S2; INVARIANTS C-9 (no model-authored id, hash or pin), C-12 (the brief pin is
the admission's), RG-4 (coverage and mechanisms restate recorded observations), C-13 (content_hash is the JCS
hash). Oracle: scoping-report.schema.json and the router's own checks (brief pin, hash, gap map within facets,
coverage equal to the cited observations). Limits: the judgment gives one territory text and bare strings, so
fields the schema requires but the model was not asked for carry a fixed "not stated" text, never an invention;
the gap map restates every facet as `unknown`, because no observation is tied to a facet (RG-U).
"""
from __future__ import annotations

from typing import Mapping

from gen2.core import canonical
from gen2.exec.common import Refused, derived_id, scaffold

NOT_STATED = "Not stated by the scoping pass."
SEARCHED = ("searched_ok", "searched_empty", "exhausted", "metadata_only")
FAILED = ("provider_unavailable", "auth_failed")
PROPOSER = "research_pass.scope"


def _mechanism(observations: list[Mapping]) -> dict:
    states = {row["coverage_state"] for row in observations}
    status = "ran" if states & set(SEARCHED) else "unavailable" if states & set(FAILED) else "not_run"
    return {"mechanism": "database_search", "status": status}


def scoping_report(work: Mapping, judgment: Mapping) -> dict:
    view = work["view"]
    if not (judgment["traditions"] and judgment["candidate_facets"]):
        raise Refused("a scoping report needs at least one tradition and one candidate facet")
    latest = view["latest_report"]
    facets = [{"facet_id": f"f{n}", "label": label, "rationale": NOT_STATED} for n, label in enumerate(judgment["candidate_facets"], 1)]
    by_lane: dict[tuple[str, str], list[str]] = {}
    for row in view["observations"]:
        by_lane.setdefault((row["lane"], row["coverage_state"]), []).append(row["observation_id"])
    report = {
        "report_version": "scoping-report/1", "report_id": latest["report_id"] if latest else "scope",
        "topic_id": work["topic_id"], "version": latest["version"] + 1 if latest else 1,
        "parent_version": latest["version"] if latest else None, "created_at": view["as_of"],
        "brief": {k: view["brief"][k] for k in ("brief_id", "version", "content_hash")},
        "territory_map": {"extent": NOT_STATED, "range": NOT_STATED, "nature": judgment["territory"]},
        "traditions": [{"tradition_id": f"t{n}", "community": text, "names": [text], "assumptions": NOT_STATED}
                       for n, text in enumerate(judgment["traditions"], 1)],
        "candidate_facets": facets,
        "gap_map": [{"facet_id": f["facet_id"], "question_type": "coverage", "state": "unknown",
                     **({"note": judgment["gap_skeleton"]} if n == 0 else {})} for n, f in enumerate(facets)],
        "deliberately_out": [{"item_id": f"o{n}", "description": text, "reason": NOT_STATED}
                             for n, text in enumerate(judgment["deliberately_out"], 1)],
        "discovery_mechanisms": [_mechanism(view["observations"]),
                                 {"mechanism": "backward_citation_chaining", "status": "not_run"},
                                 {"mechanism": "forward_citation_chaining", "status": "not_run"}],
        "coverage": [{"lane": lane, "coverage_state": state, "observation_ids": sorted(ids)}
                     for (lane, state), ids in sorted(by_lane.items())],
    }
    return {**report, "content_hash": canonical.content_hash(report)}


def build_scope(work: Mapping, judgment: Mapping) -> dict:
    """work-input/1 + judgment-scope/1 -> outcome/1. The proposals keep the model's content and lose its
    attribution: the proposer is the purpose, set here (C-9)."""
    proposals = [{**p, "proposer": PROPOSER} for p in judgment["search_proposals"]]
    return scaffold(work["invocation_id"], work["topic_id"], scoping_reports=[scoping_report(work, judgment)],
                    search_proposals=proposals)
