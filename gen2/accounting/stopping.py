"""Typed stopping signals, never scientific sufficiency (flow S7; E-6/E-7)."""
from dataclasses import dataclass
from copy import deepcopy
from fractions import Fraction
from typing import Literal

from gen2.accounting import CandidateUnits, Count, EvidenceReference, Inventory, NoveltyJudgment, SemanticOperand, Standing, WindowStanding, WindowState, candidate_units, label_standing, novelty, semantic_operands, window_search_knowledge, window_standings

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


def window_revisions(pins: tuple[WindowPin, ...]) -> dict[str, int]:
    revisions: dict[str, int] = {}
    for p in pins:
        if p.invocation_id in revisions:
            raise ValueError("duplicate window pins")
        revisions[p.invocation_id] = p.contract_revision
    return revisions


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
    lower: int
    upper: int


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
    labels = semantic_operands(inventory, as_of)
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


def _credit_risks(inventory: Inventory, standings: tuple[WindowStanding, ...], operands: dict[str, WindowOperand], scope: frozenset[str] | None) -> tuple[int, list[set[str]]]:
    """Guaranteed roots and possible earlier thieves of all their new credit."""
    roots = {p.invocation_id: p for p in inventory.passes}
    seen, earlier = set(), {}
    safe, risks = 0, []
    for w in standings:
        searches = window_search_knowledge(roots[w.invocation_id], inventory)
        if w.state == "indeterminate":
            earlier[w.invocation_id] = searches
        if w.state != "eligible":
            continue
        credit = searches - seen
        seen.update(searches)
        if operands[w.invocation_id].state != "eligible" or (scope is not None and w.invocation_id not in scope):
            continue
        possible = set().union(*(keys for keys in earlier.values() if keys is not None))
        unknown = any(keys is None for keys in earlier.values())
        if not unknown and not credit <= possible:
            safe += 1
        else:
            risks.append({i for i, keys in earlier.items() if keys is None or credit & keys})
    return safe, risks


def _coverage_lower_bound(inventory: Inventory, standings: tuple[WindowStanding, ...], operands: dict[str, WindowOperand], scope: frozenset[str] | None) -> int:
    safe, risks = _credit_risks(inventory, standings, operands, scope)
    groups: list[set[str]] = []
    for risk in risks:
        linked = [g for g in groups if g & risk]
        groups = [g for g in groups if not g & risk]
        groups.append(risk.union(*linked))
    # In each group, failed thieves retain the observed roots; a completing
    # thief earns at least one window if every possible first owner counts.
    replacements = sum(all((scope is None or i in scope) and operands[i].standing == "current"
                           for i in group) for group in groups)
    return safe + replacements


def coverage(context: Context, rule_id: str, inventory: Inventory, pins: tuple[WindowPin, ...], minimum_windows: int, *, scope: frozenset[str] | None = None) -> RuleResult:
    """A declared window-count prerequisite only; no recall/meaning guarantee."""
    if minimum_windows < 1:
        raise ValueError("minimum_windows must be positive")
    revisions = window_revisions(pins)
    standings = window_standings(inventory)
    global_operands = {w.invocation_id: _window_operand(w, inventory, revisions) for w in standings}
    windows = tuple(global_operands[w.invocation_id] for w in standings
                    if scope is None or w.invocation_id in scope)
    eligible = sum(w.state == "eligible" for w in windows)
    ineligible = sum(w.state == "ineligible" for w in windows)
    indeterminate = sum(w.state == "indeterminate" for w in windows)
    lower = _coverage_lower_bound(inventory, standings, global_operands, scope)
    upper = eligible + indeterminate
    state: State = "unknown"
    if lower >= minimum_windows:
        state = "satisfied"
    elif eligible + indeterminate < minimum_windows:
        state = "not_satisfied"
    if inventory.current_contract_revision != context.contract_revision or inventory.history == "legacy_unknown":
        state = "unknown"
    return RuleResult(context, rule_id, "coverage", state, CoverageOperands(minimum_windows, windows, inventory.history, eligible, ineligible, indeterminate, scope, lower, upper))


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


def _rule_reusable(original: Context, current: Context, inventory: Inventory | None) -> bool:
    if inventory is None:
        return original == current
    return (inventory.current_contract_revision == current.contract_revision
            and original.topic_id == current.topic_id and original.protocol_revision == current.protocol_revision
            and label_standing(inventory, original.contract_revision) in ("current", "compatible"))


def evaluate_profile(context: Context, profile: Profile, rules: tuple[RuleResult, ...], gates: tuple[GateResult, ...], *, inventory: Inventory | None = None) -> ProfileResult:
    """Reuse recorded-compatible rules with original provenance; never reuse gates."""
    gate_states = {g.gate: g.state if g.context == context else "unknown" for g in gates}
    if len({r.rule_id for r in rules}) != len(rules) or len(gate_states) != len(gates):
        raise ValueError("duplicate rule or gate results")
    rules = tuple(r for r in rules if _rule_reusable(r.context, context, inventory))
    states = {r.rule_id: r.state for r in rules}
    rules_state = expression_state(profile.completion_condition, states)
    state = combine("all", (rules_state, *(gate_states.get(g, "unknown") for g in profile.conjunctive_gates)))
    return ProfileResult(context, profile, rules, gates, state)


@dataclass(frozen=True)
class RuleBinding:
    rule_id: str
    family: str
    evaluation: str
    params: dict
    prerequisites: tuple[str, ...]
    evaluator: Literal["descriptive", "coverage", "known_item"] | None


@dataclass(frozen=True)
class ProfileBinding:
    profile: Profile
    rules: tuple[RuleBinding, ...]


def bind_rule(rule: dict) -> RuleBinding:
    """Evaluator support, after schema validation; never reinterpret a family."""
    family, mode = rule["family"], rule["evaluation"]
    name = f"stopping rule {rule['rule_id']} ({family})"
    if family not in ("diminishing_returns", "known_item", "counterevidence_pass", "statistical_target_recall",
                      "capture_recapture", "voi_evpi", "safe", "code_meaning_saturation", "descriptive", "coverage"):
        raise ValueError(f"{name}: unknown family")
    evaluator = None
    if mode == "automatic":
        if family not in ("known_item", "descriptive", "coverage"):
            raise ValueError(f"{name}: no automatic evaluator implements its declared operands (G-11)")
        if family == "known_item" and rule["params"]["tests"] != "retrieval":
            raise ValueError(f"{name}: {rule['params']['tests']} sentinel checks require an unimplemented screening evaluator (G-11)")
        evaluator = family
    elif mode != "reviewed_judgment":
        raise ValueError(f"{name}: unknown evaluation mode {mode}")
    return RuleBinding(rule["rule_id"], family, mode, deepcopy(rule["params"]), tuple(rule.get("prerequisites", ())), evaluator)


def _bind_expression(document: dict) -> Expression:
    if "rule" in document:
        return Expression(rule=document["rule"])
    return Expression(op=document["op"], operands=tuple(_bind_expression(e) for e in document["operands"]))


def bind_profile(document: dict) -> ProfileBinding:
    return ProfileBinding(Profile(document["profile_id"], _bind_expression(document["completion_condition"]),
                                  tuple(document["conjunctive_gates"])), tuple(bind_rule(r) for r in document["rules"]))


def evaluate_binding(binding: RuleBinding, context: Context, inventory: Inventory, declared: KnownItems | None = None, *, pins: tuple[WindowPin, ...] = (), as_of: str | None = None) -> RuleResult:
    """Dispatch declared operands; a sentinel reference must match exactly."""
    if binding.evaluator == "descriptive":
        if as_of is None:
            raise ValueError(f"{binding.rule_id}: descriptive reporting requires an explicit as_of")
        return descriptive(context, binding.rule_id, inventory, as_of)
    if binding.evaluator == "coverage":
        return coverage(context, binding.rule_id, inventory, pins, binding.params["minimum_windows"], scope=frozenset(binding.params["scope"]))
    if binding.evaluator != "known_item":
        raise ValueError(f"{binding.rule_id}: no automatic evaluator binding")
    if declared is None:
        raise ValueError(f"{binding.rule_id}: sentinel inventory required")
    if declared.reference != EvidenceReference(**binding.params["sentinel_set"]):
        raise ValueError(f"{binding.rule_id}: sentinel inventory does not match the declared reference")
    return known_item(context, binding.rule_id, inventory, declared)
