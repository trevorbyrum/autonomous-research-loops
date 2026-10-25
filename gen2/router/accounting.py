"""Checked capture entries and pure conversion of fixed detached operands."""
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

from gen2 import accounting as a
from gen2.accounting import views as v
from gen2.core import canonical, pagination
from gen2.router.boundary import Refusal
from gen2.store import api
from gen2.store.capture import Freshness, TopicCapture, input_hash


class Rows(Protocol):
    def capture_topic(self, topic_id: str) -> TopicCapture: ...
    def select(self, table: str, where: Mapping[str, object] | None = None) -> list[dict]: ...


class AccountingCore(Protocol):
    _store: Rows
    def _guarded(self, reason: str, body: Callable, *, freshness: Freshness | None = None) -> object: ...  # pragma: no mutate - Protocol declaration has no execution behavior
    def _audit(self, kind: str, at: str, detail: dict, *, topic_id=None) -> str: ...  # pragma: no mutate - Protocol declaration has no execution behavior


class Accounting:
    def __init__(self, core: AccountingCore) -> None:
        self._core = core

    def capture(self, topic_id: str, history: a.History) -> TopicCapture:
        if history not in ("native", "legacy_unknown"):
            raise ValueError("history must be native or legacy_unknown")
        raw = self._core._store.capture_topic(topic_id)
        if not next(t.rows for t in raw.tables if t.name == "queue_entries"):
            raise Refusal("unknown_topic", topic_id)
        return raw

    def candidate_units(self, topic_id: str, *, history: a.History) -> a.CandidateUnits:
        return a.candidate_units(convert_inventory(topic_id, self.capture(topic_id, history), history))

    def evidence_inventory(self, topic_id: str, *, history: a.History) -> a.Inventory:
        return convert_inventory(topic_id, self.capture(topic_id, history), history)

    def coverage_snapshot(self, topic_id: str, *, history: a.History) -> "CoverageSnapshot":
        return convert_coverage_snapshot(self.capture(topic_id, history), topic_id, history)

    def dossier_inputs(self, topic_id: str, *, history: a.History) -> "DossierInput":
        raw = self.capture(topic_id, history)
        if not any(r["status"] == "approved" and r["approved_by_decision_id"] is not None for r in records(raw, "contract_revisions")):
            raise Refusal("no_approved_contract", topic_id)
        return DossierInput(raw, convert_coverage_snapshot(raw, topic_id, history), input_hash(raw, history))

    def commit_dossier_inputs(self, topic_id: str, *, history: a.History, prepare: Callable, commit: Callable) -> object:
        """Compute outside the fence; caller's existing supervised job deadline applies.

        Only an effect-free generation mismatch permits up to two recaptures.
        The next slice supplies dossier preparation and its normal commit body.
        """
        for recaptures in range(3):
            def audit(now):
                return self._core._audit("dossier_input_recaptures", now, {"recaptures": recaptures}, topic_id=topic_id)
            def fenced(now):
                result = commit(prepared, now)
                audit(now)
                return result
            try:
                inputs = self.dossier_inputs(topic_id, history=history)
                prepared = prepare(inputs)
                return self._core._guarded(reason="payload_invalid", body=fenced, freshness=inputs.raw.freshness)
            except api.GenerationMismatch:
                del inputs, prepared
                continue
            except api.StaleInput as exc:
                raise Refusal("stale_inputs", str(exc)) from None
            except Refusal:
                self._core._guarded("payload_invalid", audit)
                raise
        self._core._guarded("payload_invalid", audit)
        raise Refusal("stale_inputs", "store generation changed after two recaptures")


def records(snapshot: TopicCapture, name: str):
    """Decode one fixed captured group lazily, without a Store/query interface."""
    table = next(t for t in snapshot.tables if t.name == name)
    for row in table.rows:
        record = dict(zip(table.columns, row))
        for column in table.json_columns:
            if record.get(column) is not None:
                record[column] = canonical.parse_json_strict(record[column])
        yield record


@dataclass(frozen=True)
class CoverageSnapshot:
    inventory: a.Inventory
    window_pins: tuple[v.WindowPin, ...]
    branch_links: tuple[v.BranchLink, ...]


@dataclass(frozen=True)
class DossierInput:
    """Detached inputs, content binding and Store-issued commit freshness."""
    raw: TopicCapture
    coverage: CoverageSnapshot
    input_hash: str


def read_coverage_snapshot(rows: Rows, topic_id: str, history: a.History) -> CoverageSnapshot:
    return convert_coverage_snapshot(rows.capture_topic(topic_id), topic_id, history)

def convert_coverage_snapshot(rows: TopicCapture, topic_id: str, history: a.History) -> CoverageSnapshot:
    inventory = convert_inventory(topic_id, rows, history)
    pins = convert_window_pins(rows, topic_id)
    windows = {p.invocation_id for p in pins}
    branches = {r.disposition_id: r for r in inventory.registry_dispositions if r.registry_kind == "branch"}
    links = set()
    for record in records(rows, "branch_windows"):
        branch = branches.get(record["branch_disposition_id"])
        if branch is None or branch.registry_id != record["registry_id"] or record["window_invocation_id"] not in windows:
            continue  # unverified branch/window provenance supplies no authority
        receipts = [r for r in records(rows, "operation_receipts") if r["operation_id"] == record["recorded_by_operation_id"]]
        if not receipts or (receipts[0]["topic_id"], receipts[0]["invocation_id"]) != (topic_id, record["invocation_id"]):
            continue
        links.add((branch.registry_id, record["window_invocation_id"]))
    return CoverageSnapshot(inventory, pins, tuple(v.BranchLink(*link) for link in sorted(links)))


def read_window_pins(rows: Rows, topic_id: str) -> tuple[v.WindowPin, ...]:
    return convert_window_pins(rows.capture_topic(topic_id), topic_id)

def convert_window_pins(rows: TopicCapture, topic_id: str) -> tuple[v.WindowPin, ...]:
    pins = []
    for window in (r for r in records(rows, "invocations") if r["kind"] == "research_pass" and r["admission_context"] == "contract/1"):
        contracts = [r for r in records(rows, "contract_revisions") if r["revision"] == window["contract_revision"]]
        if not contracts or contracts[0]["status"] not in ("approved", "superseded") or contracts[0]["approved_by_decision_id"] is None:
            continue
        # The exact revision's document retains protocol/framing; never use
        # the current contract or a consumer-supplied revision for this pin.
        pins.append(v.WindowPin(window["invocation_id"], contracts[0]["revision"]))
    return tuple(pins)


def read_inventory(rows: Rows, topic_id: str, history: a.History) -> a.Inventory:
    return convert_inventory(topic_id, rows.capture_topic(topic_id), history)

def convert_inventory(topic_id: str, rows: TopicCapture, history: a.History) -> a.Inventory:
    where = {"topic_id": topic_id}
    observations = tuple(a.Observation(o["observation_id"], o["invocation_id"], o["lane"], o["request_identity"],
                                       pagination.request_type(o["request"]), o["completeness"], o["page_outcome"], o["result_count"],
                                       read_page(o))
                         for o in records(rows, "search_observations"))
    retrievals = tuple(a.Retrieval(r["event_id"], r["observation_id"]) for r in records(rows, "retrieval_events"))
    events = {r.event_id for r in retrievals}
    works = {w["work_id"] for w in records(rows, "works")}
    links = tuple(a.WorkLink(l["event_id"], l["work_id"]) for l in records(rows, "record_work_links")
                  if l["event_id"] in events and l["work_id"] in works)
    assessments = tuple(a.Assessment(s["work_id"]) for s in records(rows, "screening_assessments"))
    claims = tuple(a.Claim(c["claim_id"], c["revision"], c["status"]) for c in records(rows, "claims"))
    passes = tuple(a.Pass(p["invocation_id"], p["kind"], p["state"], p["parent_invocation_id"]) for p in records(rows, "invocations"))
    semantic = tuple(a.SemanticAssessment(s["assessment_id"], s["work_id"], s["source_version"], s["contract_revision"],
        s["eligibility_protocol_version"], s["framing_version"], s["novelty"], s["independence"], s["applicability"], s["contribution"],
        tuple(a.EvidenceReference(**ref) for ref in s["evidence_refs"]), s["actor_kind"], s["invocation_id"],
        s["recorded_by_operation_id"], s["created_at"]) for s in records(rows, "semantic_assessments"))
    ids = {s.assessment_id for s in semantic}
    lineage = tuple(a.SourceLineage(**l) for l in records(rows, "source_lineage") if l["assessment_id"] in ids)
    lifecycle = tuple(read_lifecycle(r) for r in records(rows, "source_lifecycle"))
    dispositions = tuple(read_registry_disposition(r) for r in records(rows, "registry_dispositions"))
    current, impacts, screening = convert_context(rows, where)
    return a.Inventory(history, observations, retrievals, links, assessments, claims, passes, semantic, lineage, lifecycle, dispositions,
                       current, impacts, screening)


def read_context(rows: Rows, where: Mapping[str, object]) -> tuple[int | None, tuple[a.AmendmentImpact, ...], tuple[a.ScreeningAssessment, ...]]:
    approved = rows.select("contract_revisions", {**where, "status": "approved"})
    current = approved[0]["revision"] if approved else None
    impacts = tuple(read_impact(r) for r in rows.select("amendment_impacts", {**where, "kind": "contract"}))
    screening = tuple(a.ScreeningAssessment(**{k: v for k, v in r.items() if k not in {"topic_id", "criterion_results"}})
                      for r in rows.select("screening_assessments", where))
    return current, impacts, screening

def convert_context(rows: TopicCapture, where: Mapping[str, object]):
    approved = [r for r in records(rows, "contract_revisions") if r["status"] == "approved"]
    current = approved[0]["revision"] if approved else None
    impacts = tuple(read_impact(r) for r in (r for r in records(rows, "amendment_impacts") if r["kind"] == "contract"))
    screening = tuple(a.ScreeningAssessment(**{k: v for k, v in r.items() if k not in {"topic_id", "criterion_results"}})
                      for r in records(rows, "screening_assessments"))
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
    if pagination.retained_request(observation):
        return None  # retained refused bytes do not assert a decoded search/page
    request = observation["request"]["request"]
    if request["request_type"] != "find":
        return None
    continuation = observation["continuation"]
    return a.SearchPage(a.search_identity(request), observation["request"]["page"],
                        (request.get("cursors") or {}).get(observation["lane"]),
                        continuation["cursor"] if continuation is not None else None)
