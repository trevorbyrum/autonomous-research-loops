"""Pure snapshot views (flow S7; E-7): recorded operands, no sufficiency verdict."""
from dataclasses import dataclass

from gen2 import accounting as a
from gen2.accounting.stopping import WindowPin
from gen2.core.instants import utc_instant_ns


@dataclass(frozen=True)
class CoverageWindow:
    capture: a.WindowStanding
    contract_revision: int | None
    standing: a.Standing
    searches: frozenset[tuple[str, a.SearchIdentity]] | None


@dataclass(frozen=True)
class BranchLink:
    """An explicit recorded branch/window association supplied with the snapshot."""
    registry_id: str
    invocation_id: str


@dataclass(frozen=True)
class BranchCoverage:
    registry_id: str
    links: tuple[BranchLink, ...]
    windows: tuple[CoverageWindow, ...]
    unknown_reason: str | None


@dataclass(frozen=True)
class CoverageView:
    history: a.History
    units: a.CandidateUnits
    observations: tuple[a.Observation, ...]
    windows: tuple[CoverageWindow, ...]
    branches: tuple[BranchCoverage, ...]


def coverage_view(inventory: a.Inventory, pins: tuple[WindowPin, ...],
                  branch_links: tuple[BranchLink, ...] = ()) -> CoverageView:
    """Capture standing and G-1 shown independently; never infer branch links."""
    revisions = {p.invocation_id: p.contract_revision for p in pins}
    if len(revisions) != len(pins):
        raise ValueError("duplicate window pins")
    roots = {p.invocation_id: p for p in inventory.passes}
    windows = tuple(CoverageWindow(w, revisions.get(w.invocation_id),
        a.label_standing(inventory, revisions[w.invocation_id]) if w.invocation_id in revisions else "unknown",
        a.window_search_knowledge(roots[w.invocation_id], inventory)) for w in a.window_standings(inventory))
    branch_ids = {r.registry_id for r in inventory.registry_dispositions if r.registry_kind == "branch"}
    branch_ids.update(link.registry_id for link in branch_links)
    branches = tuple(_branch_coverage(i, branch_links, windows) for i in sorted(branch_ids))
    return CoverageView(inventory.history, a.candidate_units(inventory), inventory.observations, windows, branches)


def _branch_coverage(registry_id: str, links: tuple[BranchLink, ...], windows: tuple[CoverageWindow, ...]) -> BranchCoverage:
    recorded = tuple(link for link in links if link.registry_id == registry_id)
    ids = {link.invocation_id for link in recorded}
    selected = tuple(w for w in windows if w.capture.invocation_id in ids)
    reason = None
    if not recorded:
        reason = "branch search links not recorded"
    elif ids - {w.capture.invocation_id for w in selected}:
        reason = "linked research window missing"
    return BranchCoverage(registry_id, recorded, selected, reason)


@dataclass(frozen=True)
class RegistryOperand:
    record: a.RegistryDisposition
    standing: a.Standing


@dataclass(frozen=True)
class RegistryHistory:
    registry_kind: str
    registry_id: str
    history: tuple[a.RegistryDisposition, ...]
    active: tuple[RegistryOperand, ...]

    @property
    def dispositions(self) -> tuple[str, ...] | None:
        if not self.active or any(o.standing not in ("current", "compatible") for o in self.active):
            return None
        return tuple(o.record.disposition for o in self.active)


@dataclass(frozen=True)
class DepthView:
    as_of: str
    semantic: tuple[a.SemanticOperand, ...]
    lifecycle_history: tuple[a.LifecycleOperand, ...]
    lifecycle_active: tuple[a.LifecycleOperand, ...]
    registries: tuple[RegistryHistory, ...]
    amendment_impacts: tuple[a.AmendmentImpact, ...]
    reopenings: tuple[a.ScreeningAssessment, ...]


def depth_view(inventory: a.Inventory, as_of: str) -> DepthView:
    """Dated records with the supplied snapshot's G-1 standing, not a past contract."""
    instant = utc_instant_ns(as_of)
    subjects = sorted({(r.work_id, r.source_version) for r in inventory.semantic_assessments})
    semantic = tuple(o for work, version in subjects for o in a.semantic_accrual(inventory, work, version, as_of))
    lifecycle = tuple(a.LifecycleOperand(r, a.label_standing(inventory, r.contract_revision))
        for r in sorted(inventory.source_lifecycle, key=lambda r: (utc_instant_ns(r.created_at), r.disposition_id))
        if utc_instant_ns(r.created_at) <= instant)
    active = tuple(a.LifecycleOperand(r, a.label_standing(inventory, r.contract_revision))
                   for r in a.lifecycle_view(inventory.source_lifecycle, as_of))
    records = tuple(r for r in inventory.registry_dispositions if utc_instant_ns(r.created_at) <= instant)
    identities = sorted({(r.registry_kind, r.registry_id) for r in records})
    registries = tuple(_registry_history(inventory, records, kind, i) for kind, i in identities)
    impacts = tuple(sorted((r for r in inventory.amendment_impacts if utc_instant_ns(r.recorded_at) <= instant),
                           key=lambda r: (utc_instant_ns(r.recorded_at), r.decision_id)))
    reopened = {i for r in impacts for i in r.reopened_exclusions}
    reopenings = tuple(r for r in a.rescreening_view(inventory)
                      if r.assessment_id in reopened and utc_instant_ns(r.created_at) <= instant)
    return DepthView(as_of, semantic, lifecycle, active, registries, impacts, reopenings)


def _registry_history(inventory: a.Inventory, records: tuple[a.RegistryDisposition, ...], kind: str, registry_id: str) -> RegistryHistory:
    history = tuple(sorted((r for r in records if (r.registry_kind, r.registry_id) == (kind, registry_id)),
                           key=lambda r: (utc_instant_ns(r.created_at), r.disposition_id)))
    replaced = {r.supersedes_id for r in history if r.supersedes_id is not None}
    active = tuple(RegistryOperand(r, a.label_standing(inventory, r.contract_revision))
                   for r in history if r.disposition_id not in replaced)
    return RegistryHistory(kind, registry_id, history, active)
