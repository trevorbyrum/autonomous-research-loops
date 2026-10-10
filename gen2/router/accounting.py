"""Minimal read adapter; called inside the Router's snapshot, no arithmetic."""
from dataclasses import dataclass
from typing import Mapping, Protocol

from gen2 import accounting as a
from gen2.accounting import views as v


class Rows(Protocol):
    def select(self, table: str, where: Mapping[str, object] | None = None) -> list[dict]: ...


@dataclass(frozen=True)
class CoverageSnapshot:
    inventory: a.Inventory
    window_pins: tuple[v.WindowPin, ...]
    branch_links: tuple[v.BranchLink, ...]


def read_coverage_snapshot(rows: Rows, topic_id: str, history: a.History) -> CoverageSnapshot:
    inventory = read_inventory(rows, topic_id, history)
    pins = read_window_pins(rows, topic_id)
    windows = {p.invocation_id for p in pins}
    branches = {r.disposition_id: r for r in inventory.registry_dispositions if r.registry_kind == "branch"}
    links = set()
    for record in rows.select("branch_windows", {"topic_id": topic_id}):
        branch = branches.get(record["branch_disposition_id"])
        if branch is None or branch.registry_id != record["registry_id"] or record["window_invocation_id"] not in windows:
            continue  # unverified branch/window provenance supplies no authority
        receipts = rows.select("operation_receipts", {"operation_id": record["recorded_by_operation_id"]})
        if not receipts or (receipts[0]["topic_id"], receipts[0]["invocation_id"]) != (topic_id, record["invocation_id"]):
            continue
        links.add((branch.registry_id, record["window_invocation_id"]))
    return CoverageSnapshot(inventory, pins, tuple(v.BranchLink(*link) for link in sorted(links)))


def read_window_pins(rows: Rows, topic_id: str) -> tuple[v.WindowPin, ...]:
    pins = []
    for window in rows.select("invocations", {"topic_id": topic_id, "kind": "research_pass", "admission_context": "contract/1"}):
        contracts = rows.select("contract_revisions", {"topic_id": topic_id, "revision": window["contract_revision"]})
        if not contracts or contracts[0]["status"] not in ("approved", "superseded") or contracts[0]["approved_by_decision_id"] is None:
            continue
        # The exact revision's document retains protocol/framing; never use
        # the current contract or a consumer-supplied revision for this pin.
        pins.append(v.WindowPin(window["invocation_id"], contracts[0]["revision"]))
    return tuple(pins)


def read_inventory(rows: Rows, topic_id: str, history: a.History) -> a.Inventory:
    where = {"topic_id": topic_id}
    observations = tuple(a.Observation(o["observation_id"], o["invocation_id"], o["lane"], o["request_identity"],
                                       o["request"]["request"]["request_type"], o["completeness"], o["page_outcome"], o["result_count"],
                                       read_page(o))
                         for o in rows.select("search_observations", where))
    retrievals = tuple(a.Retrieval(r["event_id"], r["observation_id"]) for r in rows.select("retrieval_events", where))
    events = {r.event_id for r in retrievals}
    works = {w["work_id"] for w in rows.select("works")}
    links = tuple(a.WorkLink(l["event_id"], l["work_id"]) for l in rows.select("record_work_links")
                  if l["event_id"] in events and l["work_id"] in works)
    assessments = tuple(a.Assessment(s["work_id"]) for s in rows.select("screening_assessments", where))
    claims = tuple(a.Claim(c["claim_id"], c["revision"], c["status"]) for c in rows.select("claims", where))
    passes = tuple(a.Pass(p["invocation_id"], p["kind"], p["state"], p["parent_invocation_id"]) for p in rows.select("invocations", where))
    semantic = tuple(a.SemanticAssessment(s["assessment_id"], s["work_id"], s["source_version"], s["contract_revision"],
        s["eligibility_protocol_version"], s["framing_version"], s["novelty"], s["independence"], s["applicability"], s["contribution"],
        tuple(a.EvidenceReference(**ref) for ref in s["evidence_refs"]), s["actor_kind"], s["invocation_id"],
        s["recorded_by_operation_id"], s["created_at"]) for s in rows.select("semantic_assessments", where))
    ids = {s.assessment_id for s in semantic}
    lineage = tuple(a.SourceLineage(**l) for l in rows.select("source_lineage") if l["assessment_id"] in ids)
    lifecycle = tuple(read_lifecycle(r) for r in rows.select("source_lifecycle", where))
    dispositions = tuple(read_registry_disposition(r) for r in rows.select("registry_dispositions", where))
    current, impacts, screening = read_context(rows, where)
    return a.Inventory(history, observations, retrievals, links, assessments, claims, passes, semantic, lineage, lifecycle, dispositions,
                       current, impacts, screening)


def read_context(rows: Rows, where: Mapping[str, object]) -> tuple[int | None, tuple[a.AmendmentImpact, ...], tuple[a.ScreeningAssessment, ...]]:
    approved = rows.select("contract_revisions", {**where, "status": "approved"})
    current = approved[0]["revision"] if approved else None
    impacts = tuple(read_impact(r) for r in rows.select("amendment_impacts", {**where, "kind": "contract"}))
    screening = tuple(a.ScreeningAssessment(**{k: v for k, v in r.items() if k not in {"topic_id", "criterion_results"}})
                      for r in rows.select("screening_assessments", where))
    return current, impacts, screening


def read_impact(record: dict) -> a.AmendmentImpact:
    doc = record["document"]
    return a.AmendmentImpact(record["decision_id"], doc["current"]["revision"],
                             tuple(a.RevisionStanding(**s) for s in doc.get("standing", ())),
                             tuple(doc.get("reopened_exclusions", ())), record["recorded_at"])


def read_registry_disposition(record: dict) -> a.RegistryDisposition:
    fields = {k: v for k, v in record.items() if k not in {"topic_id", "evidence_refs"}}
    return a.RegistryDisposition(**fields, evidence_refs=tuple(a.EvidenceReference(**ref) for ref in record["evidence_refs"]))


def read_lifecycle(record: dict) -> a.SourceDisposition:
    fields = {k: v for k, v in record.items() if k not in {"topic_id", "evidence_refs"}}
    return a.SourceDisposition(**fields, evidence_refs=tuple(a.EvidenceReference(**ref) for ref in record["evidence_refs"]))


def read_page(observation: dict) -> a.SearchPage | None:
    request = observation["request"]["request"]
    if request["request_type"] != "find":
        return None
    continuation = observation["continuation"]
    return a.SearchPage(a.search_identity(request), observation["request"]["page"],
                        (request.get("cursors") or {}).get(observation["lane"]),
                        continuation["cursor"] if continuation is not None else None)
