"""Closed identity accounting for the architecture ratchet (task 2q-a-repair-2; one transition plan, task 2q-a-repair-3).

The registry is an index into the baseline's budgets, not another measurement. Its keys never change on a map. No current-source heuristic can retire a key.
Ledger entries are reviewed metadata under trust model B; Git cannot authenticate that a stated reason or reviewing task is true.

ONE EFFECTIVE TRANSITION PLAN (Gate D #4 R3). Checking, drafting and folding used to transform the same budgets three ways, and the drafter proposed
transitions that contradicted the author's own. They now consume one `Plan`, computed once from the baseline, the current facts and the entries already
written: (1) the author's explicit transitions apply first - a `map` or `retire` for one identity, and a `move` of a file or directory, which this module
expands deterministically (below); (2) what is still missing from the baseline is a retirement the author owes, and what is still unclaimed in the current
facts is an admission the author owes; (3) numeric budgets are derived from the plan's transported baseline. The plan is a pure value: nothing in it changes the
measurement, and a drafted entry is always something the plan still lacks (so drafting twice, before or after the reasons are filled, adds nothing).
"""
from __future__ import annotations

import collections
import copy
import re
from dataclasses import dataclass, field
from fractions import Fraction

LEDGER = "docs/gen2/metrics-ledger.md"
HEADER = """# Architecture metrics ledger

Task 2q-a-repair-2 and 2q-a-repair-3; charter Architecture metrics and Root-cause fixes, not patches.

The baseline registry owns persistent identities. Each check accounts for every
identity as present, explicitly mapped, or explicitly retired. Missing identities
fail. New files, edges, reach pairs and collaboration/function budgets require
admission. Stable-target fan-in includes every dependent, including new files.
Normalised aggregates never authorise growth. Instability is judged by direction:
taking on dependencies differs from losing dependents (Stable Dependencies Principle).

Source outside the supported-source contract (docs/gen2/SOURCE-CONTRACT.md) is
refused before any measurement. Nothing in this ledger waives a refusal: an
unresolved or unsupported form is not classified here, it is changed.

`make gen2-metrics-admit` drafts what the current plan still lacks with reason: TODO;
drafts fail. Fill each reason and reviewing task, review the diff, and commit the
ledger before checking. The tool checks commitment, not the truth of the author's
review claim. Maps preserve the old identity and compare all old budgets at the new
location. A `move` entry states one explicit file move (or one directory prefix) and
expands deterministically to a map of every baseline identity that mentions the file;
nothing is inferred from similar bodies and nothing is admitted by a move. An identity
the move cannot map (it has no counterpart at the destination) needs its own `retire`
entry; an explicit `map` or `retire` always overrides the expansion for that identity.
Retirements require absence. Budget admissions name one metric/location and a bounded
limit. Exemptions remain temporary regressions and never loosen a recorded budget.
Identity loss and new population cannot be exempted.

Rebaseline consumes admitted, mapped, moved and retired transitions only after a passing
check, keeps persistent IDs, and clears those entries. Improved functions keep their
identity and both scores even below thresholds. An edge/reach/pair that disappears
requires retirement. Git retains consumed reasons in the committed ledger history. Initial
recording is the sole bootstrap; existing baselines can migrate only at their exact
production digest.

Entries are `### ML-...` sections with fields action (map, retire, admit, budget, move),
identity/target (as applicable), metric/location/limit (for budget), from/to (for move),
reason, and task. Targets use service|kind|location; file identities own fan-out and
fan-in; function IDs own both scores; edge, reach, self_calls, cycle, smell and aggregate
IDs own their respective budgets. Cross-service imports belong to repo.

"""
ALIASES = {k: k for k in ("action", "identity", "target", "metric", "location", "limit", "reason", "task", "from", "to")}
ACTIONS = ("map", "retire", "admit", "budget", "move")
REQUIRED = {"map": {"identity", "target"}, "retire": {"identity"}, "admit": {"target"}, "budget": {"metric", "location"}, "move": {"from", "to"}}


def reference(service: str, kind: str, location: str) -> str:
    return f"{service}|{kind}|{location}"


def split(ref: str) -> tuple[str, str, str]:
    service, kind, location = ref.split("|", 2)
    return service, kind, location


def inventory(body: dict) -> set[str]:
    refs = set()
    for service, s in body["services"].items():
        for path in s["fan_out"]:
            refs.add(reference(service, "file", path))
        for kind, values in (("function", s["functions"]), ("self_calls", s["self_calls"])):
            refs.update(reference(service, kind, key) for key in values)
        for kind, field_ in (("edge", "graph"), ("reach", "reach")):
            refs.update(reference(service, kind, f"{a}->{b}") for a, targets in s[field_].items() for b in targets)
        for metric in ("propagation_file", "propagation_component"):
            refs.add(reference(service, metric, service))
        for kind in ("file", "component"):
            refs.update(reference(service, "cycle_" + kind, ",".join(c)) for c in s["cycles_" + kind])
        for kind, items in s["smells"].items():
            refs.update(reference(service, "smell_" + kind, loc) for loc in items)
    refs.update(reference("repo", "cross_service_import", edge) for edge in body["cross_service_imports"])
    return refs


def register(body: dict) -> dict[str, str]:
    return {f"MI-{i:06}": ref for i, ref in enumerate(sorted(inventory(body)), 1)}


def validate_registry(baseline: dict) -> None:
    registry = baseline.get("identities")
    if not isinstance(registry, dict) or len(set(registry.values())) != len(registry) or set(registry.values()) != inventory(baseline):
        raise ValueError("baseline identity registry does not account exactly for its budgets")
    if any(not key.startswith("MI-") or not key[3:].isdigit() for key in registry):
        raise ValueError("invalid persistent identity")
    if baseline.get("identity_serial", -1) < max((int(k[3:]) for k in registry), default=0):
        raise ValueError("invalid identity serial")


# --- the entries ---------------------------------------------------------------------------------------------------

def subject(entry_fields: dict) -> tuple:
    """What an entry is about: two entries about one subject conflict (an identity has one transition; a target one admission; a budget one limit)."""
    f = entry_fields
    action = f.get("action")
    if action in ("map", "retire"):
        return ("transition", f.get("identity"))
    if action == "admit":
        return ("admit", f.get("target"))
    if action == "move":
        return ("move", f.get("from"))
    return ("budget", f.get("metric"), f.get("location"))


def read_entries(text, parse, placeholder):
    entries, errors = parse(text or "", "ML-", ALIASES)
    ids, subjects = set(), set()
    for entry in entries:
        f = entry.fields
        if entry.ident in ids:
            errors.append(f"{entry.ident}: duplicate entry ID")
        ids.add(entry.ident)
        action = f.get("action")
        required = {"reason", "task", "action"} | REQUIRED.get(action, {"metric", "location"})
        if action not in ACTIONS:
            errors.append(f"{entry.ident}: invalid action" + (" (classification is withdrawn: source the contract refuses is changed, not classified)" if action == "classify" else ""))
        for key in required:
            if not f.get(key) or placeholder.match(f[key]) or (key == "reason" and re.search(r"\bTODO\b", f[key], re.I)):
                errors.append(f"{entry.ident}: {key} missing or placeholder")
        if set(f) - required - ({"limit"} if action == "budget" else set()):
            errors.append(f"{entry.ident}: fields do not match action {action}")
        if subject(f) in subjects:
            errors.append(f"{entry.ident}: duplicate/conflicting subject")
        subjects.add(subject(f))
    return entries, errors


# --- explicit moves ------------------------------------------------------------------------------------------------

def _shape(kind: str, location: str):
    """(the file paths a reference names, how they are joined back into its location); no paths for references a file move does not touch."""
    if kind in ("file", "smell_hub_like"):
        return [location], lambda parts: parts[0]
    if kind == "function":
        path, _, qual = location.partition("::")
        return [path], lambda parts: f"{parts[0]}::{qual}"
    if kind in ("edge", "reach", "self_calls", "smell_unstable_dependency", "cross_service_import"):
        return location.split("->"), "->".join
    if kind == "cycle_file":
        return location.split(","), lambda parts: ",".join(sorted(parts))
    return [], None


def rewrite(ref: str, files: dict[str, str]) -> tuple[str, list[str]]:
    """(the reference after the explicit file moves `files` (old path -> new path), the moved paths it named): every path the reference names is replaced and
    nothing else. A component, a service aggregate or the far side of a cross-service edge that is not a moved file is left as it is, so the result is exactly
    the identity the moved file would have under the same rules; whether it exists is the plan's question."""
    service, kind, location = split(ref)
    parts, join = _shape(kind, location)
    if not parts:
        return ref, []
    return reference(service, kind, join([files.get(p, p) for p in parts])), [p for p in parts if p in files]


def file_moves(entries: list, baseline: dict, present: set[str]) -> tuple[dict[str, str], dict[str, str]]:
    """({old file: new file}, {old file: the entry that stated the move}) from the `move` entries. A directory prefix (ending `/`) moves every baseline file under
    it whose rewritten path is a current production file; a file is moved as stated. No wildcard, no inference from content or similar names."""
    files: dict[str, str] = {}
    origin: dict[str, str] = {}
    baseline_files = {split(ref)[2] for ref in baseline["identities"].values() if split(ref)[1] == "file"}
    present_files = {split(ref)[2] for ref in present if split(ref)[1] == "file"}
    for entry in entries:
        f = entry.fields
        if f.get("action") != "move":
            continue
        old, new = f.get("from", ""), f.get("to", "")
        if old.endswith("/") and new.endswith("/"):
            for path in sorted(p for p in baseline_files if p.startswith(old)):
                if new + path[len(old):] in present_files:
                    files[path], origin[path] = new + path[len(old):], entry.ident
        elif old and new and not old.endswith("/") and not new.endswith("/"):
            files[old], origin[old] = new, entry.ident
    return files, origin


# --- the plan ------------------------------------------------------------------------------------------------------

@dataclass
class Step:
    """A transition the plan applies that no entry spells out: a move's expansion for one identity (named by the move entry that stated it)."""
    ident: str
    fields: dict


@dataclass
class Plan:
    moves: dict[str, str] = field(default_factory=dict)        # old reference -> new reference (explicit maps and expanded moves)
    retired: set[str] = field(default_factory=set)
    used: set[str] = field(default_factory=set)                # the entries the plan consumed
    failures: list = field(default_factory=list)               # identity and admission failures
    required: list[str] = field(default_factory=list)          # current references nothing claims: each needs an admission
    pending_retire: list[str] = field(default_factory=list)    # identities missing with no entry (drafting only: otherwise a failure)
    admitted: dict = field(default_factory=dict)
    registry: dict[str, str] = field(default_factory=dict)
    serial: int = 0
    expanded: dict[str, list[str]] = field(default_factory=lambda: collections.defaultdict(list))   # move entry -> the references it mapped


def present_refs(current: dict) -> set[str]:
    """Every reference the current facts contain, with every measured function (also those below both thresholds, which can be a map's destination)."""
    present = inventory(current)
    present |= {reference(service, "function", k) for service, s in current["services"].items() for k in s["all_functions"]}
    return present


def make_plan(baseline: dict, current: dict, entries: list, violation, drafting: bool = False) -> Plan:
    """The effective transition plan (module docstring). With `drafting` the owed retirements and admissions are listed instead of failing, so the drafter and the
    check read one set of transitions."""
    present = present_refs(current)
    plan = Plan(admitted={e.fields.get("target"): e for e in entries if e.fields.get("action") == "admit"})
    explicit = {e.fields.get("identity"): e for e in entries if e.fields.get("action") in ("map", "retire")}
    files, origin = file_moves(entries, baseline, present)
    claimed: dict[str, list[str]] = collections.defaultdict(list)
    for ident, ref in baseline["identities"].items():
        entry, moved_by = explicit.get(ident), None
        if entry is None:
            entry, moved_by = expansion(plan, ref, files, origin)
        dest = place(plan, (ident, ref), entry, moved_by, present, violation, drafting)
        if dest is not None:
            claimed[dest].append(ident)
    for dest, idents in claimed.items():
        plan.failures += [violation("identity", dest, "two identities map to one location", ident) for ident in idents[1:]]
    admissions(plan, baseline, current, claimed, violation, drafting)
    return plan


def expansion(plan: Plan, ref: str, files: dict[str, str], origin: dict[str, str]):
    """(the map a move entry makes of one identity, the move that made it), or (None, None) when no move touches the reference."""
    moved, paths = rewrite(ref, files)
    if not paths:
        return None, None
    plan.expanded[origin[paths[0]]].append(ref)
    return Step(origin[paths[0]], {"action": "map", "target": moved}), origin[paths[0]]


def place(plan: Plan, identity: tuple[str, str], entry, moved_by, present: set[str], violation, drafting: bool):
    """Where one identity ends up under its entry: its destination, or None when it is retired or (drafting) owed a retirement. An entry that does not hold (a map
    whose old location is still present or whose destination is not there or of another kind, a retirement of something present) is a failure naming the identity."""
    ident, ref = identity
    dest = ref
    if entry is not None:
        plan.used.add(entry.ident)
        if entry.fields["action"] == "retire":
            if ref in present:
                plan.failures.append(violation("identity", ref, "retirement requires absence", ident))
            plan.retired.add(ref)
            return None
        dest = entry.fields.get("target", "")
        if ref in present or dest not in present or split(dest)[:2] != split(ref)[:2] or dest == ref:
            plan.failures.append(violation("identity", ref, "invalid map: old must be absent, target present in same service/kind"
                                           + (f" (expanded from {moved_by})" if moved_by else ""), ident))
            dest = ref
        else:
            plan.moves[ref] = dest
    if dest not in present:
        if drafting and entry is None:
            plan.pending_retire.append(ident)
            plan.retired.add(ref)
            return None
        plan.failures.append(violation("identity", ref, "missing; map or retire in committed ledger", ident))
    return dest


def admissions(plan: Plan, baseline: dict, current: dict, claimed: dict, violation, drafting: bool) -> None:
    """What the current facts hold that no identity claims needs an admission; the registry after the plan keeps every id and gives each admission a new one."""
    plan.required = sorted(inventory(effective_current(current, plan)) - set(claimed))
    for ref in plan.required:
        if ref in plan.admitted:
            plan.used.add(plan.admitted[ref].ident)
        elif not drafting:
            plan.failures.append(violation("admission", ref, "new budget needs reasoned ledger admission", 0))
    plan.registry = {ident: plan.moves.get(ref, ref) for ident, ref in baseline["identities"].items() if ref not in plan.retired}
    plan.serial = baseline["identity_serial"]
    for ref in plan.required:
        if ref in plan.admitted:
            plan.serial += 1
            plan.registry[f"MI-{plan.serial:06}"] = ref


def effective_current(current: dict, plan: Plan) -> dict:
    """The current facts with each mapped function's destination in the compared population (a destination below both thresholds is not an offender, but
    it is the function the old budget follows). A copy: no consumer's view of the measurement changes."""
    out = copy.deepcopy(current)
    for dest in plan.moves.values():
        service, kind, key = split(dest)
        if kind == "function":
            out["services"][service]["functions"][key] = out["services"][service]["all_functions"][key]
    return out


def transport(baseline: dict, plan: Plan) -> dict:
    """The baseline's budgets at the locations the plan gives them; never substitutes a current score."""
    moves, retired = plan.moves, plan.retired
    old = copy.deepcopy(baseline)
    for service, s in old["services"].items():
        original = baseline["services"][service]
        s.update(functions={}, self_calls={}, fan_out={}, fan_in={}, graph={}, reach={})
        for kind, field_ in (("function", "functions"), ("self_calls", "self_calls"), ("file", "fan_out")):
            for location, value in original[field_].items():
                ref = reference(service, kind, location)
                if ref in retired:
                    continue
                dest = split(moves.get(ref, ref))[2]
                s[field_][dest] = value
                if kind == "file":
                    s["fan_in"][dest] = original["fan_in"][location]
                    s["graph"][dest], s["reach"][dest] = [], []
        for kind, field_ in (("edge", "graph"), ("reach", "reach")):
            for a, targets in original[field_].items():
                for b in targets:
                    ref = reference(service, kind, f"{a}->{b}")
                    if ref not in retired:
                        x, y = split(moves.get(ref, ref))[2].split("->")
                        s[field_].setdefault(x, []).append(y)
        for kind in ("file", "component"):
            s["cycles_" + kind] = [split(moves.get(reference(service, "cycle_" + kind, ",".join(c)), reference(service, "cycle_" + kind, ",".join(c))))[2].split(",")
                                   for c in original["cycles_" + kind] if reference(service, "cycle_" + kind, ",".join(c)) not in retired]
        for kind, items in original["smells"].items():
            s["smells"][kind] = [split(moves.get(reference(service, "smell_" + kind, loc), reference(service, "smell_" + kind, loc)))[2]
                                 for loc in items if reference(service, "smell_" + kind, loc) not in retired]
    old["cross_service_imports"] = [split(moves.get(reference("repo", "cross_service_import", loc), reference("repo", "cross_service_import", loc)))[2]
                                    for loc in baseline["cross_service_imports"] if reference("repo", "cross_service_import", loc) not in retired]
    return old


def budgets(violations, entries, numeric, used, violation):
    """Admit bounded growth; identity and admission failures cannot be bypassed by a numeric budget or an exemption."""
    left, errors = [], []
    for v in violations:
        e = next((e for e in entries if e.fields.get("action") == "budget" and (e.fields.get("metric"), e.fields.get("location")) == (v.metric, v.where)), None)
        if e is None or v.metric in ("identity", "admission"):
            left.append(v)
            continue
        used.add(e.ident)
        f = e.fields
        if v.metric in numeric:
            try:
                limit = Fraction(f.get("limit", ""))
                if v.value > limit:
                    left.append(v)
            except (ValueError, ZeroDivisionError):
                errors.append(f"{e.ident}: numeric budget requires a valid limit")
        elif f.get("limit"):
            errors.append(f"{e.ident}: instance budget takes no limit")
    errors += [f"{e.ident}: unused ledger entry" for e in entries if e.ident not in used]
    return left, errors


# --- drafting and presentation --------------------------------------------------------------------------------------

def draft_fields(plan: Plan, violations) -> list[dict]:
    """Every entry the plan still lacks: the retirements and admissions it owes, and a bounded budget for each numeric growth. Always entries the ledger does
    not already hold, so a repeated draft changes nothing."""
    fields = [dict(action="retire", identity=ident) for ident in plan.pending_retire]
    fields += [dict(action="admit", target=ref) for ref in plan.required if ref not in plan.admitted]
    for v in violations:
        if v.metric not in ("identity", "admission"):
            f = dict(action="budget", metric=v.metric, location=v.where)
            if isinstance(v.value, (int, Fraction)) and v.metric not in ("cycle_file", "cycle_component", "cross_service_import") and not v.metric.startswith("smell_"):
                f["limit"] = str(v.value)
            fields.append(f)
    return fields


def render(entries):
    return HEADER + "".join(f"### {ident}\n" + "".join(f"- {k}: {v}\n" for k, v in fields.items()) + "\n" for ident, fields in entries)


def grouped(refs: list[str]) -> list[str]:
    """A review presentation of references: one line per file (or per service and kind when no file anchors them) with the count of each kind, so that a move or
    an addition of many identities is read as a few statements. The entries themselves stay one per identity."""
    groups: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for ref in refs:
        service, kind, location = split(ref)
        anchor = location.partition("::")[0].partition("->")[0] if kind in ("file", "function", "edge", "reach", "self_calls") else f"{service} ({kind})"
        groups[anchor][kind] += 1
    return [f"{anchor}: " + ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items())) for anchor, counts in sorted(groups.items())]


def describe(plan: Plan, entries: list) -> list[str]:
    lines = []
    for entry in entries:
        f = entry.fields
        if f.get("action") == "move":
            mapped = plan.expanded.get(entry.ident, [])
            lines.append(f"{entry.ident} move {f.get('from')} -> {f.get('to')} maps {len(mapped)} identities: " + "; ".join(grouped(mapped)))
    if plan.required:
        lines.append(f"{len(plan.required)} identities need admission: " + "; ".join(grouped(plan.required)))
    return lines


def fold(old, current, entries, violations):
    """Add only explicitly admitted budgets before the ordinary tightening pass."""
    out = copy.deepcopy(old)
    for e in entries:
        f = e.fields
        if f.get("action") != "admit":
            continue
        service, kind, location = split(f["target"])
        if kind == "cross_service_import":
            out["cross_service_imports"].append(location)
            continue
        s, now = out["services"][service], current["services"][service]
        if kind.startswith("cycle_"):
            s["cycles_" + kind.removeprefix("cycle_")].append(location.split(","))
        elif kind.startswith("smell_"):
            s["smells"][kind.removeprefix("smell_")].append(location)
        elif kind == "file":
            for field_ in ("fan_out", "fan_in"):
                s[field_][location] = now[field_][location]
            s["graph"].setdefault(location, [])
            s["reach"].setdefault(location, [])
        elif kind in ("function", "self_calls"):
            field_ = "functions" if kind == "function" else kind
            s[field_][location] = now[field_][location]
        else:
            a, b = location.split("->")
            s["graph" if kind == "edge" else "reach"].setdefault(a, []).append(b)
    admitted = {(e.fields.get("metric"), e.fields.get("location")) for e in entries if e.fields.get("action") == "budget"}
    for v in violations:
        if (v.metric, v.where) not in admitted:
            continue
        service, _, location = v.where.partition(":")
        s, now = out["services"].get(service), current["services"].get(service)
        if v.metric.startswith("propagation_"):
            s[v.metric] = now[v.metric]
        elif v.metric in ("fan_out", "fan_in"):
            s[v.metric][location] = v.value
        elif v.metric in ("function_cyclomatic", "function_cognitive"):
            field_ = v.metric.removeprefix("function_")
            s["functions"].setdefault(location, dict(now["functions"][location]))[field_] = v.value
        elif v.metric == "self_calls":
            s["self_calls"][location] = v.value
        elif v.metric.startswith("smell_"):
            s["smells"][v.metric.removeprefix("smell_")].append(location)
        elif v.metric in ("cycle_file", "cycle_component"):
            s["cycles_" + v.metric.removeprefix("cycle_")].append(location.split(","))
        elif v.metric == "cross_service_import":
            out["cross_service_imports"].append(location)
    return out
