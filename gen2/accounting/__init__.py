"""Pure durable-inventory arithmetic (2c-1); see docs/gen2/ACCOUNTING.md."""
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

History = Literal["native", "legacy_unknown"]


@dataclass(frozen=True)
class Observation:
    observation_id: str
    invocation_id: str
    lane: str
    request_identity: str
    request_type: str
    completeness: str
    page_outcome: str
    result_count: int | None


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


@dataclass(frozen=True)
class Inventory:
    history: History
    observations: tuple[Observation, ...] = ()
    retrievals: tuple[Retrieval, ...] = ()
    links: tuple[WorkLink, ...] = ()
    assessments: tuple[Assessment, ...] = ()
    claims: tuple[Claim, ...] = ()
    passes: tuple[Pass, ...] = ()


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


def saturation_passes(inventory: Inventory) -> tuple[str, ...]:
    """Completed distinct search windows only; eligibility, never sufficiency (E-4)."""
    if inventory.history == "legacy_unknown":
        return ()
    seen: set[tuple[str, str]] = set()
    eligible = []
    for p in inventory.passes:
        observations = [o for o in inventory.observations if o.invocation_id == p.invocation_id]
        if p.kind != "research_pass" or p.state != "committed" or not observations:
            continue
        if any(not _captured(o, inventory) or o.request_type != "find" or o.page_outcome != "exhausted" for o in observations):
            continue
        requests = {(o.lane, o.request_identity) for o in observations}
        if requests - seen:
            eligible.append(p.invocation_id)
        seen.update(requests)
    return tuple(eligible)


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
