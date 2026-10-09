"""Typed stopping signals, never scientific sufficiency (flow S7; E-6/E-7)."""
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from gen2.accounting import CandidateUnits, Count, EvidenceReference, Inventory, NoveltyJudgment, SemanticOperand, Standing, WindowStanding, WindowState, candidate_units, label_standing, novelty, semantic_accrual, window_standings

State = Literal["satisfied", "not_satisfied", "unknown"]
Operator = Literal["all", "any"]
Gate = Literal["challenge_pass_completed", "coverage_integrity", "load_bearing_verification_tiers"]


@dataclass(frozen=True)
class Context:
    topic_id: str
    contract_revision: int
    protocol_revision: int


@dataclass(frozen=True)
class DescriptiveOperands:
    units: CandidateUnits
    labels: tuple[SemanticOperand, ...]
    new_fraction: Fraction | None


@dataclass(frozen=True)
class WindowPin:
    invocation_id: str
    contract_revision: int


@dataclass(frozen=True)
class WindowOperand:
    invocation_id: str
    contract_revision: int | None
    standing: Standing
    state: WindowState = "eligible"
    reason: str = "completed distinct search"


@dataclass(frozen=True)
class CoverageOperands:
    minimum_windows: int
    windows: tuple[WindowOperand, ...]
    history: str
    eligible: int
    ineligible: int
    indeterminate: int
    scope: frozenset[str] | None


@dataclass(frozen=True)
class KnownItems:
    reference: EvidenceReference
    work_ids: frozenset[str]


@dataclass(frozen=True)
class KnownItemOperands:
    declared: KnownItems
    retrieved: Count
    found: frozenset[str]
    missing: frozenset[str]


@dataclass(frozen=True)
class RuleResult:
    context: Context
    rule_id: str
    evaluator: Literal["descriptive", "coverage", "known_item"]
    state: State
    operands: DescriptiveOperands | CoverageOperands | KnownItemOperands
    schema_version: Literal["stopping-result/1"] = "stopping-result/1"


def descriptive(context: Context, rule_id: str, inventory: Inventory, as_of: str) -> RuleResult:
    subjects = sorted({(r.work_id, r.source_version) for r in inventory.semantic_assessments})
    labels = tuple(o for work, version in subjects for o in semantic_accrual(inventory, work, version, as_of))
    judgments = tuple(NoveltyJudgment(o.assessment.work_id, {"novel": True, "not_novel": False, "unknown": None}[o.labels[0]]) for o in labels)
    units = candidate_units(inventory)
    fraction = novelty(units.assessed_candidates, judgments) if inventory.current_contract_revision == context.contract_revision else None
    return RuleResult(context, rule_id, "descriptive", "unknown", DescriptiveOperands(units, labels, fraction))


def _window_operand(window: WindowStanding, inventory: Inventory, revisions: dict[str, int]) -> WindowOperand:
    i = window.invocation_id
    standing = label_standing(inventory, revisions[i]) if i in revisions else "unknown"
    state, reason = window.state, window.reason
    if state != "ineligible":
        if standing == "stale":
            state, reason = "ineligible", "contract revision stale"
        elif standing == "unknown":
            state, reason = "indeterminate", "contract standing unknown; " + reason
    return WindowOperand(i, revisions.get(i), standing, state, reason)


def coverage(context: Context, rule_id: str, inventory: Inventory, pins: tuple[WindowPin, ...], minimum_windows: int, *, scope: frozenset[str] | None = None) -> RuleResult:
    """A declared window-count prerequisite only; no recall/meaning guarantee."""
    if minimum_windows < 1:
        raise ValueError("minimum_windows must be positive")
    revisions = {p.invocation_id: p.contract_revision for p in pins}
    if len(revisions) != len(pins):
        raise ValueError("duplicate window pins")
    windows = tuple(_window_operand(w, inventory, revisions) for w in window_standings(inventory)
                    if scope is None or w.invocation_id in scope)
    eligible = sum(w.state == "eligible" for w in windows)
    ineligible = sum(w.state == "ineligible" for w in windows)
    indeterminate = sum(w.state == "indeterminate" for w in windows)
    state: State = "unknown"
    if eligible >= minimum_windows:
        state = "satisfied"
    elif eligible + indeterminate < minimum_windows:
        state = "not_satisfied"
    if inventory.current_contract_revision != context.contract_revision or inventory.history == "legacy_unknown":
        state = "unknown"
    return RuleResult(context, rule_id, "coverage", state, CoverageOperands(minimum_windows, windows, inventory.history, eligible, ineligible, indeterminate, scope))


def known_item(context: Context, rule_id: str, inventory: Inventory, declared: KnownItems) -> RuleResult:
    """Retrieval membership only; no screening or unknown-remainder claim."""
    retrieved = candidate_units(inventory).deduplicated_works
    found = declared.work_ids & retrieved.known_ids
    missing = declared.work_ids - found
    state: State = "not_satisfied" if missing else "satisfied"
    if not declared.work_ids or retrieved.value is None or inventory.current_contract_revision != context.contract_revision:
        state = "unknown"
    return RuleResult(context, rule_id, "known_item", state, KnownItemOperands(declared, retrieved, found, missing))


def combine(op: Operator, states: tuple[State, ...]) -> State:
    if op not in ("all", "any") or any(s not in ("satisfied", "not_satisfied", "unknown") for s in states):
        raise ValueError("only all/any over three-valued states")
    if not states:
        return "unknown"
    decisive = "not_satisfied" if op == "all" else "satisfied"
    if decisive in states:
        return decisive
    if "unknown" in states:
        return "unknown"
    return "satisfied" if op == "all" else "not_satisfied"


@dataclass(frozen=True)
class Expression:
    rule: str | None = None
    op: Operator | None = None
    operands: tuple["Expression", ...] = ()

    def __post_init__(self) -> None:
        leaf = bool(self.rule) and self.op is None and not self.operands
        branch = self.rule is None and self.op in ("all", "any") and bool(self.operands)
        if not (leaf or branch):
            raise ValueError("expression requires a rule or nonempty all/any")


def expression_state(expression: Expression, states: dict[str, State]) -> State:
    if expression.rule is not None:
        return states.get(expression.rule, "unknown")
    return combine(expression.op, tuple(expression_state(e, states) for e in expression.operands))


@dataclass(frozen=True)
class GateResult:
    context: Context
    gate: Gate
    state: State
    evidence_refs: tuple[EvidenceReference, ...]


@dataclass(frozen=True)
class Profile:
    profile_id: str
    completion_condition: Expression
    conjunctive_gates: tuple[Gate, ...]


@dataclass(frozen=True)
class ProfileResult:
    context: Context
    profile: Profile
    rules: tuple[RuleResult, ...]
    gates: tuple[GateResult, ...]
    state: State
    schema_version: Literal["stopping-result/1"] = "stopping-result/1"


def evaluate_profile(context: Context, profile: Profile, rules: tuple[RuleResult, ...], gates: tuple[GateResult, ...]) -> ProfileResult:
    states = {r.rule_id: r.state if r.context == context else "unknown" for r in rules}
    gate_states = {g.gate: g.state if g.context == context else "unknown" for g in gates}
    if len(states) != len(rules) or len(gate_states) != len(gates):
        raise ValueError("duplicate rule or gate results")
    rules_state = expression_state(profile.completion_condition, states)
    state = combine("all", (rules_state, *(gate_states.get(g, "unknown") for g in profile.conjunctive_gates)))
    return ProfileResult(context, profile, rules, gates, state)
