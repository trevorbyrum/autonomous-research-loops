"""Pure durable-inventory arithmetic (2c-1); see docs/gen2/ACCOUNTING.md."""
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Literal, TypeVar

from gen2.core.instants import utc_instant_ns

History = Literal["native", "legacy_unknown"]


@dataclass(frozen=True)
class SearchIdentity:
    domain: str
    commercial: bool
    accept_per_item: bool
    query: str
    kind: str | None
    year_from: int | None
    published_after: str | None
    lanes: tuple[str, ...] | None


def search_identity(request: dict) -> SearchIdentity:
    """Mirror gateway effective_request(find), excluding cursors and page size.

    Cross-service imports are forbidden; the gateway comparison test pins this
    form. Capture/replay request_identity is retained separately and unchanged.
    """
    domain = request.get("domain")
    return SearchIdentity(domain if domain in {"finance", "market", "social", "management", "ai-ml", "software", "biomed"} else "other",
                          bool(request.get("commercial")), bool(request.get("accept_per_item")), request.get("query") or "",
                          request.get("kind"), request.get("year_from"), request.get("published_after"),
                          tuple(sorted(request["lanes"])) if request.get("lanes") else None)


@dataclass(frozen=True)
class SearchPage:
    search: SearchIdentity
    number: int
    cursor: str | int | None
    continuation: str | int | None


@dataclass(frozen=True)
class Observation:
    observation_id: str
    invocation_id: str
    lane: str
    request_identity: str
    request_type: str | None  # opaque failed attempts assert no decoded type
    completeness: str
    page_outcome: str
    result_count: int | None
    page: SearchPage | None = None


@dataclass(frozen=True)
class Retrieval:
    event_id: str
    observation_id: str


@dataclass(frozen=True)
class WorkLink:
    event_id: str
    work_id: str


@dataclass(frozen=True)
class Assessment:
    work_id: str


@dataclass(frozen=True)
class Claim:
    claim_id: str
    revision: int
    status: str


@dataclass(frozen=True)
class Pass:
    invocation_id: str
    kind: str
    state: str
    parent_invocation_id: str | None = None


@dataclass(frozen=True)
class EvidenceReference:
    content_hash: str
    size_bytes: int
    media_type: str


@dataclass(frozen=True)
class SemanticAssessment:
    assessment_id: str
    work_id: str
    source_version: str
    contract_revision: int
    eligibility_protocol_version: int
    framing_version: int
    novelty: Literal["novel", "not_novel", "unknown"]
    independence: Literal["independent", "shared_origin", "unknown"]
    applicability: Literal["applicable", "not_applicable", "unknown"]
    contribution: Literal["answer", "confidence", "applicability", "options", "question_formulation", "boundary_condition", "contradiction", "unknown"]
    evidence_refs: tuple[EvidenceReference, ...]
    actor_kind: Literal["primary"]
    invocation_id: str
    recorded_by_operation_id: str
    created_at: str


@dataclass(frozen=True)
class SourceLineage:
    assessment_id: str  # attribution and work/version are the parent assessment's
    relation: Literal["shared_study_origin", "version_of", "derived_from"]
    study_origin_id: str | None
    related_work_id: str | None
    related_source_version: str | None


@dataclass(frozen=True)
class SourceDisposition:
    disposition_id: str
    work_id: str
    source_version: str
    contract_revision: int
    eligibility_protocol_version: int
    framing_version: int
    action: Literal["add", "keep", "supersede", "coexist", "quarantine", "duplicate-report"]
    related_work_id: str | None
    related_source_version: str | None
    supersedes_id: str | None
    reason_code: str
    evidence_refs: tuple[EvidenceReference, ...]
    actor_kind: Literal["primary"]
    invocation_id: str
    recorded_by_operation_id: str
    created_at: str


R = TypeVar("R", "SourceDisposition", "RegistryDisposition")


def active_records(records: tuple[R, ...]) -> tuple[R, ...]:
    """The records no other record in `records` explicitly replaces, in order."""
    replaced = {r.supersedes_id for r in records if r.supersedes_id is not None}
    return tuple(r for r in records if r.disposition_id not in replaced)


def lifecycle_view(records: tuple[SourceDisposition, ...], as_of: str) -> tuple[SourceDisposition, ...]:
    """Active dated records; explicit replacement only, competing judgments retained.

    Consumes admitted history of one topic, never chooses labels or sufficiency.
    A reversal is a later disposition replacing its predecessor, not deletion.
    """
    instant = utc_instant_ns(as_of)
    dated = tuple(r for r in records if utc_instant_ns(r.created_at) <= instant)
    return tuple(sorted(active_records(dated), key=lambda r: r.disposition_id))


@dataclass(frozen=True)
class RegistryDisposition:
    disposition_id: str
    registry_kind: Literal["contradiction", "branch"]
    registry_id: str  # scoped by topic and kind, not a global work identity
    subject: str
    disposition: Literal["unresolved", "resolved", "contested", "promote", "park", "drop"]
    contract_revision: int
    eligibility_protocol_version: int
    framing_version: int
    supersedes_id: str | None
    reason_code: str
    evidence_refs: tuple[EvidenceReference, ...]
    actor_kind: Literal["primary"]
    invocation_id: str
    recorded_by_operation_id: str
    created_at: str


Standing = Literal["current", "compatible", "stale", "unknown"]


@dataclass(frozen=True)
class RevisionStanding:
    revision: int
    classification: str


@dataclass(frozen=True)
class AmendmentImpact:
    decision_id: str
    current_revision: int
    standing: tuple[RevisionStanding, ...]
    reopened_exclusions: tuple[str, ...]
    recorded_at: str


@dataclass(frozen=True)
class ScreeningAssessment:
    assessment_id: str
    work_id: str
    contract_revision: int
    eligibility_protocol_version: int
    framing_version: int
    stage: str
    decision: str
    reason_code: str | None
    actor_kind: str
    invocation_id: str | None
    decision_receipt_id: str | None
    operator_decision_id: str | None
    supersedes_assessment_id: str | None
    recorded_by_operation_id: str
    created_at: str


@dataclass(frozen=True)
class Inventory:
    history: History
    observations: tuple[Observation, ...] = ()
    retrievals: tuple[Retrieval, ...] = ()
    links: tuple[WorkLink, ...] = ()
    assessments: tuple[Assessment, ...] = ()
    claims: tuple[Claim, ...] = ()
    passes: tuple[Pass, ...] = ()
    semantic_assessments: tuple[SemanticAssessment, ...] = ()
    source_lineage: tuple[SourceLineage, ...] = ()
    source_lifecycle: tuple[SourceDisposition, ...] = ()
    registry_dispositions: tuple[RegistryDisposition, ...] = ()
    current_contract_revision: int | None = None
    amendment_impacts: tuple[AmendmentImpact, ...] = ()
    screening_history: tuple[ScreeningAssessment, ...] = ()


def label_standing(inventory: Inventory, revision: int) -> Standing:
    """Recorded G-1 authority only; an invalidation cannot be undone by cycling."""
    listed = tuple(s.classification for impact in inventory.amendment_impacts
                   for s in impact.standing if s.revision == revision)
    if any(c not in ("compatible", "lineage_only") for c in listed):
        return "stale"
    if inventory.current_contract_revision is None:
        return "unknown"
    if revision == inventory.current_contract_revision:
        return "current"
    current = tuple(s.classification for impact in inventory.amendment_impacts
                    if impact.current_revision == inventory.current_contract_revision
                    for s in impact.standing if s.revision == revision)
    return "compatible" if current else "unknown"


@dataclass(frozen=True)
class LifecycleOperand:
    record: SourceDisposition
    standing: Standing


@dataclass(frozen=True)
class SemanticOperand:
    assessment: SemanticAssessment
    standing: Standing
    lineage: tuple[SourceLineage, ...]
    lifecycle: tuple[LifecycleOperand, ...]

    @property
    def labels(self) -> tuple[str, str, str, str]:
        if self.standing not in ("current", "compatible"):
            return ("unknown", "unknown", "unknown", "unknown")
        r = self.assessment
        return (r.novelty, r.independence, r.applicability, r.contribution)


def semantic_accrual(inventory: Inventory, work_id: str, source_version: str, as_of: str) -> tuple[SemanticOperand, ...]:
    """Retain judgments and exact lineage/version joins; never infer contribution."""
    instant = utc_instant_ns(as_of)
    lifecycle = tuple(LifecycleOperand(r, label_standing(inventory, r.contract_revision)) for r in lifecycle_view(inventory.source_lifecycle, as_of)
                      if (r.work_id, r.source_version) == (work_id, source_version))
    return tuple(SemanticOperand(r, label_standing(inventory, r.contract_revision),
                                tuple(l for l in inventory.source_lineage if l.assessment_id == r.assessment_id), lifecycle)
                 for r in sorted(inventory.semantic_assessments, key=lambda r: r.assessment_id)
                 if (r.work_id, r.source_version) == (work_id, source_version) and utc_instant_ns(r.created_at) <= instant)


def rescreening_view(inventory: Inventory) -> tuple[ScreeningAssessment, ...]:
    """E-9: retain reason-coded old assessments; consume recorded reopenings."""
    reopened = {assessment_id for impact in inventory.amendment_impacts for assessment_id in impact.reopened_exclusions}
    return tuple(sorted((r for r in inventory.screening_history if r.assessment_id in reopened and r.decision == "exclude"),
                        key=lambda r: r.assessment_id))


@dataclass(frozen=True)
class Count:
    """Known identities remain inspectable even when the total is unknown."""
    known_ids: frozenset[str]
    unknown_reason: str | None = None

    @property
    def value(self) -> int | None:
        return None if self.unknown_reason is not None else len(self.known_ids)


@dataclass(frozen=True)
class CandidateUnits:
    retrieved_records: Count
    deduplicated_works: Count
    assessed_candidates: Count
    accepted_claims: Count
    saturation_passes: tuple[str, ...]


def _captured(observation: Observation, inventory: Inventory) -> bool:
    # result_count is a coherence check, never an arithmetic denominator (E-2).
    events = {r.event_id for r in inventory.retrievals if r.observation_id == observation.observation_id}
    return observation.completeness == "complete" and observation.result_count == len(events)


def _capture_reason(inventory: Inventory) -> str | None:
    if inventory.history == "legacy_unknown":
        return "legacy historical capture unknown"
    observed = {o.invocation_id for o in inventory.observations}
    if any(p.kind in ("research_pass", "discovery", "delegate") and p.invocation_id not in observed for p in inventory.passes):
        return "invocation capture missing"
    if any(not _captured(o, inventory) for o in inventory.observations):
        return "capture partial or unknown"
    if any(r.observation_id not in {o.observation_id for o in inventory.observations} for r in inventory.retrievals):
        return "retrieval observation missing"
    return None


def _descendants(root: Pass, inventory: Inventory) -> list[Pass]:
    members = {root.invocation_id}
    pending = [root.invocation_id]
    descendants = []
    while pending:
        parent = pending.pop()
        for child in inventory.passes:
            if child.parent_invocation_id == parent and child.invocation_id not in members:
                members.add(child.invocation_id)
                pending.append(child.invocation_id)
                descendants.append(child)
    return descendants


def _search_key(o: Observation) -> tuple[str, SearchIdentity]:
    """Each observation covers one lane: automatic/explicit lane selection and
    the other lanes' pagination do not change this lane's population."""
    return o.lane, replace(o.page.search, lanes=(o.lane,))


def _complete_chain(observations: list[Observation]) -> bool:
    pages = sorted(observations, key=lambda o: o.page.number)
    number, cursor = 1, None  # Full window bounds: page 1 / no cursor through exhaustion.
    for o in pages:
        if o.page.number != number or o.page.cursor != cursor:
            return False
        number += 1
        cursor = o.page.continuation
        if o is not pages[-1] and (o.page_outcome != "continuation" or cursor is None):
            return False
    return pages[-1].page_outcome == "exhausted" and cursor is None


def _window_searches(root: Pass, inventory: Inventory) -> set[tuple[str, SearchIdentity]]:
    descendants = _descendants(root, inventory)
    members = {root.invocation_id} | {p.invocation_id for p in descendants}
    observations = [o for o in inventory.observations if o.invocation_id in members]
    observed = {o.invocation_id for o in observations}
    if any(p.state != "committed" or p.invocation_id not in observed for p in descendants):
        return set()
    if any(not _captured(o, inventory) or o.page_outcome == "failed" for o in observations):
        return set()
    chains: dict[tuple[str, SearchIdentity], list[Observation]] = {}
    for o in observations:
        if o.request_type != "find":
            continue  # Non-paging success adds no window; its failures were checked above.
        if o.page is None:
            return set()
        chains.setdefault(_search_key(o), []).append(o)
    if any(not _complete_chain(chain) for chain in chains.values()):
        return set()
    return set(chains)


def saturation_passes(inventory: Inventory) -> tuple[str, ...]:
    """Completed distinct search windows only; eligibility, never sufficiency (E-4)."""
    if inventory.history == "legacy_unknown":
        return ()
    seen: set[tuple[str, SearchIdentity]] = set()
    eligible = []
    for p in inventory.passes:
        if p.kind != "research_pass" or p.state != "committed":
            continue
        requests = _window_searches(p, inventory)
        if requests - seen:
            eligible.append(p.invocation_id)
        seen.update(requests)
    return tuple(eligible)


WindowState = Literal["eligible", "ineligible", "indeterminate"]


@dataclass(frozen=True)
class WindowStanding:
    invocation_id: str
    state: WindowState
    reason: str


def window_search_knowledge(root: Pass, inventory: Inventory) -> frozenset[tuple[str, SearchIdentity]] | None:
    """Recorded populations, or unknown when a member's searches are missing."""
    children = _descendants(root, inventory)
    ids = {root.invocation_id} | {p.invocation_id for p in children}
    observations = tuple(o for o in inventory.observations if o.invocation_id in ids)
    observed = {o.invocation_id for o in observations}
    if not observations or any(p.invocation_id not in observed for p in children):
        return None
    finds = tuple(o for o in observations if o.request_type in ("find",))
    if any(o.page is None for o in finds):
        return None
    return frozenset(_search_key(o) for o in finds)


ChainState = Literal["invalid", "recoverable", "complete"]


def _chain_knowledge(chain: list[Observation]) -> ChainState:
    """Contradictions cannot be repaired by adding consistent missing pages."""
    pages = sorted(chain, key=lambda o: o.page.number)
    if len({o.page.number for o in pages}) != len(pages):
        return "invalid"
    for o in pages:
        if o.page.number < 1 or (o.page.cursor is None) != (o.page.number == 1):
            return "invalid"
        if o.page_outcome == "exhausted" and o.page.continuation is not None:
            return "invalid"
        if o.page_outcome == "continuation" and o.page.continuation is None:
            return "invalid"
    for previous, following in zip(pages, pages[1:]):
        if previous.page_outcome == "exhausted":
            return "invalid"
        adjacent = following.page.number == previous.page.number + 1
        if adjacent and previous.page.continuation is not None and previous.page.continuation != following.page.cursor:
            return "invalid"
    if pages[0].page.number != 1 or any(b.page.number != a.page.number + 1 for a, b in zip(pages, pages[1:])):
        return "recoverable"
    return "complete"  # Structural completeness; terminal knowledge is checked below.


def _excluded_window(root: Pass, inventory: Inventory) -> WindowStanding:
    members = (root, *_descendants(root, inventory))
    member_ids = {p.invocation_id for p in members}
    observations = tuple(o for o in inventory.observations if o.invocation_id in member_ids)
    state: WindowState = "ineligible"
    if any(p.state in ("failed", "cancelled") for p in members):
        reason = "invocation failed or cancelled"
    elif any(o.page_outcome in ("failed", "limit_reached") for o in observations):
        reason = "request failed or capped"
    else:
        state, reason = _window_uncertainty(members, observations, inventory)
    return WindowStanding(root.invocation_id, state, reason)


def _window_uncertainty(members: tuple[Pass, ...], observations: tuple[Observation, ...], inventory: Inventory) -> tuple[WindowState, str]:
    if any(p.state != "committed" for p in members):
        return "indeterminate", "invocation unfinished"
    if inventory.history == "legacy_unknown":
        return "indeterminate", "legacy historical capture unknown"
    observed = {o.invocation_id for o in observations}
    missing = tuple(p.invocation_id for p in members[1:] if p.invocation_id not in observed)
    if missing or not observations:
        return "indeterminate", "invocation capture missing: " + ", ".join(missing or (members[0].invocation_id,))
    if any(o.completeness == "unobserved" for o in observations):
        return "indeterminate", "request unobserved"
    if any(not _captured(o, inventory) for o in observations):
        return "indeterminate", "capture partial or unknown"
    finds = tuple(o for o in observations if o.request_type == "find")
    return _search_completion(finds)


def _search_completion(finds: tuple[Observation, ...]) -> tuple[WindowState, str]:
    if any(o.page is None for o in finds):
        return "indeterminate", "search page metadata missing"
    chains: dict[tuple[str, SearchIdentity], list[Observation]] = {}
    for o in finds:
        chains.setdefault(_search_key(o), []).append(o)
    classes = tuple(_chain_knowledge(chain) for chain in chains.values())
    if "invalid" in classes:
        return "ineligible", "no complete distinct search"
    if any(o.page_outcome == "end_unknown" for o in finds) or any(max(chain, key=lambda o: o.page.number).page_outcome == "continuation" for chain in chains.values()):
        return "indeterminate", "pagination end unknown"
    if "recoverable" in classes:
        return "indeterminate", "pagination pages missing"
    return "ineligible", "no complete distinct search"


def window_standings(inventory: Inventory) -> tuple[WindowStanding, ...]:
    """Every attempted research window, with transitive delegates in its standing.

    E-4 eligibility is unchanged; exclusions retain whether completion is known.
    Contract standing and each rule's scope are applied by the coverage consumer.
    """
    eligible = frozenset(saturation_passes(inventory))
    return tuple(WindowStanding(p.invocation_id, "eligible", "completed distinct search")
                 if p.invocation_id in eligible else _excluded_window(p, inventory)
                 for p in inventory.passes if p.kind == "research_pass")


def candidate_units(inventory: Inventory) -> CandidateUnits:
    """Four distinct units; identity deduplication establishes no study independence."""
    reason = _capture_reason(inventory)
    records = frozenset(r.event_id for r in inventory.retrievals)
    links = {link.event_id: link.work_id for link in inventory.links}
    works = frozenset(links[r] for r in records if r in links)
    work_reason = reason or ("record identity not linked" if records - links.keys() else None)
    assessed = frozenset(a.work_id for a in inventory.assessments)  # E-5: absence stays unassessed.
    latest: dict[str, Claim] = {}
    for claim in inventory.claims:
        if claim.claim_id not in latest or claim.revision > latest[claim.claim_id].revision:
            latest[claim.claim_id] = claim
    accepted = frozenset(c.claim_id for c in latest.values() if c.status == "accepted_support")
    historical = "legacy historical capture unknown" if inventory.history == "legacy_unknown" else None
    return CandidateUnits(Count(records, reason), Count(works, work_reason), Count(assessed, historical),
                          Count(accepted, historical), saturation_passes(inventory))


def semantic_operands(inventory: Inventory, as_of: str) -> tuple[SemanticOperand, ...]:
    subjects = sorted({(r.work_id, r.source_version) for r in inventory.semantic_assessments})
    return tuple(o for work, version in subjects for o in semantic_accrual(inventory, work, version, as_of))


@dataclass(frozen=True)
class NoveltyJudgment:
    work_id: str
    novel: bool | None


def novelty(assessed: Count, judgments: tuple[NoveltyJudgment, ...]) -> Fraction | None:
    """Aggregate explicit judgments only (E-7); unknown has no value (E-1)."""
    if assessed.value is None or assessed.value == 0:
        return None
    labels = {j.work_id: j.novel for j in judgments}
    if len(labels) != len(judgments) or labels.keys() != assessed.known_ids or any(v is None for v in labels.values()):
        return None
    return Fraction(sum(v is True for v in labels.values()), assessed.value)
