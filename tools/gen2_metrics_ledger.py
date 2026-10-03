"""Closed identity accounting for the architecture ratchet (task 2q-a-repair-2).

The registry is an index into the baseline's budgets, not another measurement.
Its keys never change on a map. No current-source heuristic can retire a key.
Ledger entries are reviewed metadata under trust model B; Git cannot authenticate
that a stated reason or reviewing task is true.
"""
from __future__ import annotations

import copy
import re
from fractions import Fraction

LEDGER = "docs/gen2/metrics-ledger.md"
HEADER = """# Architecture metrics ledger

Task 2q-a-repair-2; charter Architecture metrics and Root-cause fixes, not patches.

The baseline registry owns persistent identities. Each check accounts for every
identity as present, explicitly mapped, or explicitly retired. Missing identities
fail. New files, edges, reach pairs and collaboration/function budgets require
admission. Stable-target fan-in includes every dependent, including new files.
Normalised aggregates never authorise growth. Instability is judged by direction:
taking on dependencies differs from losing dependents (Stable Dependencies Principle).

`make gen2-metrics-admit` drafts current changes with reason: TODO; drafts fail.
Fill each reason and reviewing task, review the diff, and commit the ledger before
checking. The tool checks commitment, not the truth of the author's review claim.
Maps preserve the old identity and compare all old budgets at the new location.
File moves require maps for affected function, edge, reach and collaboration
identities too; there is no guessed correspondence. Retirements require absence.
Budget admissions name one metric/location and a bounded limit. Exemptions remain
temporary regressions and never loosen a recorded budget. Identity loss and new
population cannot be exempted. Classifications of unresolved bindings remain in
this ledger while needed; they do not certify any collaboration inventory.

Rebaseline consumes admitted, mapped and retired transitions only after a passing
check, keeps persistent IDs, and clears those entries. Classifications remain.
Improved functions keep their identity and both scores even below thresholds.
An edge/reach/pair that disappears requires retirement. Git retains consumed
reasons in the committed ledger history. Initial recording is the sole bootstrap;
existing baselines can migrate only at their exact production digest.

Entries are `### ML-...` sections with fields action, identity/target (as applicable),
metric/location/limit (for budget or classify), reason, and task. Targets use
service|kind|location; file identities own fan-out and fan-in; function IDs own
both scores; edge, reach, self_calls, cycle, smell and aggregate IDs own their
respective budgets. Cross-service imports belong to repo.

"""
ALIASES = {k: k for k in ("action", "identity", "target", "metric", "location", "limit", "reason", "task")}


def reference(service: str, kind: str, location: str) -> str:
    return f"{service}|{kind}|{location}"


def inventory(body: dict) -> set[str]:
    refs = set()
    for service, s in body["services"].items():
        for path in s["fan_out"]:
            refs.add(reference(service, "file", path))
        for kind, values in (("function", s["functions"]), ("self_calls", s["self_calls"])):
            refs.update(reference(service, kind, key) for key in values)
        for kind, field in (("edge", "graph"), ("reach", "reach")):
            refs.update(reference(service, kind, f"{a}->{b}") for a, targets in s[field].items() for b in targets)
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


def read_entries(text, parse, placeholder):
    entries, errors = parse(text or "", "ML-", ALIASES)
    ids, subjects = set(), set()
    for entry in entries:
        f = entry.fields
        if entry.ident in ids:
            errors.append(f"{entry.ident}: duplicate entry ID")
        ids.add(entry.ident)
        action = f.get("action")
        required = {"reason", "task", "action"}
        required |= {"identity", "target"} if action == "map" else {"identity"} if action == "retire" else {"target"} if action == "admit" else {"metric", "location"}
        if action not in ("map", "retire", "admit", "budget", "classify"):
            errors.append(f"{entry.ident}: invalid action")
        for key in required:
            if not f.get(key) or placeholder.match(f[key]) or (key == "reason" and re.search(r"\bTODO\b", f[key], re.I)):
                errors.append(f"{entry.ident}: {key} missing or placeholder")
        if set(f) - required - ({"limit"} if action == "budget" else set()):
            errors.append(f"{entry.ident}: fields do not match action {action}")
        subject = ("transition", f.get("identity")) if action in ("map", "retire") else (action, f.get("target")) if action == "admit" else ("budget", f.get("metric"), f.get("location"))
        if subject in subjects:
            errors.append(f"{entry.ident}: duplicate/conflicting subject")
        subjects.add(subject)
    return entries, errors


def transport(baseline: dict, moves: dict[str, str], retired: set[str]) -> dict:
    """Transport budgets by explicit identity; never substitute a current score."""
    old = copy.deepcopy(baseline)
    for service, s in old["services"].items():
        original = baseline["services"][service]
        s.update(functions={}, self_calls={}, fan_out={}, fan_in={}, graph={}, reach={})
        for kind, field in (("function", "functions"), ("self_calls", "self_calls"), ("file", "fan_out")):
            for location, value in original[field].items():
                ref = reference(service, kind, location)
                if ref in retired:
                    continue
                dest = moves.get(ref, ref).split("|", 2)[2]
                s[field][dest] = value
                if kind == "file":
                    s["fan_in"][dest] = original["fan_in"][location]
                    s["graph"][dest], s["reach"][dest] = [], []
        for kind, field in (("edge", "graph"), ("reach", "reach")):
            for a, targets in original[field].items():
                for b in targets:
                    ref = reference(service, kind, f"{a}->{b}")
                    if ref not in retired:
                        dest = moves.get(ref, ref).split("|", 2)[2]
                        x, y = dest.split("->")
                        s[field].setdefault(x, []).append(y)
        for kind in ("file", "component"):
            s["cycles_" + kind] = [moves.get(reference(service, "cycle_" + kind, ",".join(c)), reference(service, "cycle_" + kind, ",".join(c))).split("|", 2)[2].split(",")
                                     for c in original["cycles_" + kind] if reference(service, "cycle_" + kind, ",".join(c)) not in retired]
        for kind, items in original["smells"].items():
            s["smells"][kind] = [moves.get(reference(service, "smell_" + kind, loc), reference(service, "smell_" + kind, loc)).split("|", 2)[2]
                                  for loc in items if reference(service, "smell_" + kind, loc) not in retired]
    old["cross_service_imports"] = [moves.get(reference("repo", "cross_service_import", loc), reference("repo", "cross_service_import", loc)).split("|", 2)[2]
                                    for loc in baseline["cross_service_imports"] if reference("repo", "cross_service_import", loc) not in retired]
    return old


def account(baseline, current, entries, violation):
    """Closed accounting before score comparisons; returns transported budgets,
    persistent registry, accounting violations, and used transition entries."""
    present = inventory(current)
    # Every measured function is available for a map, even below both thresholds.
    present |= {reference(service, "function", k) for service, s in current["services"].items() for k in s["all_functions"]}
    moves, retired, used, failures = {}, set(), set(), []
    registry = dict(baseline["identities"])
    transitions = {e.fields.get("identity"): e for e in entries if e.fields.get("action") in ("map", "retire")}
    destinations = set()
    for ident, ref in registry.items():
        entry = transitions.get(ident)
        dest = ref
        if entry:
            f = entry.fields
            used.add(entry.ident)
            if f["action"] == "retire":
                if ref in present:
                    failures.append(violation("identity", ref, "retirement requires absence", ident))
                retired.add(ref)
                continue
            dest = f.get("target", "")
            if ref in present or dest not in present or dest.split("|")[:2] != ref.split("|")[:2] or dest == ref:
                failures.append(violation("identity", ref, "invalid map: old must be absent, target present in same service/kind", ident))
            else:
                moves[ref] = dest
            if ref not in moves:
                dest = ref
        if dest not in present:
            failures.append(violation("identity", ref, "missing; map or retire in committed ledger", ident))
        if dest in destinations:
            failures.append(violation("identity", dest, "two identities map to one location", ident))
        destinations.add(dest)
        if dest in present and dest.split("|", 2)[1] == "function":
            service, _, key = dest.split("|", 2)
            current["services"][service]["functions"][key] = current["services"][service]["all_functions"][key]
    required = inventory(current) - destinations
    admitted = {e.fields.get("target"): e for e in entries if e.fields.get("action") == "admit"}
    for ref in sorted(required):
        if ref not in admitted:
            failures.append(violation("admission", ref, "new budget needs reasoned ledger admission", 0))
        else:
            used.add(admitted[ref].ident)
    registry = {ident: moves.get(ref, ref) for ident, ref in registry.items() if ref not in retired}
    serial = baseline["identity_serial"]
    for ref in sorted(required & set(admitted)):
        serial += 1
        registry[f"MI-{serial:06}"] = ref
    return transport(baseline, moves, retired), registry, serial, failures, used


def budgets(violations, entries, numeric, used, violation):
    """Admit bounded growth or classify unresolved bindings; identity failures
    cannot be bypassed by a numeric budget or an exemption."""
    left, errors = [], []
    for v in violations:
        e = next((e for e in entries if e.fields.get("action") in ("budget", "classify") and
                  (e.fields.get("metric"), e.fields.get("location")) == (v.metric, v.where)), None)
        if e is None or v.metric in ("identity", "admission"):
            left.append(v)
            continue
        used.add(e.ident)
        f = e.fields
        if v.metric == "unresolved_base":
            if f["action"] != "classify":
                errors.append(f"{e.ident}: unresolved binding requires classify")
        elif f["action"] != "budget":
            errors.append(f"{e.ident}: only unresolved_base may be classified")
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


def draft_fields(baseline, current, violations):
    refs = inventory(current)
    fields = []
    for ident, ref in baseline["identities"].items():
        if ref not in refs:
            fields.append(dict(action="retire", identity=ident))
    for ref in sorted(refs - set(baseline["identities"].values())):
        fields.append(dict(action="admit", target=ref))
    for v in violations:
        if v.metric not in ("identity", "admission"):
            f = dict(action="classify" if v.metric == "unresolved_base" else "budget", metric=v.metric, location=v.where)
            if isinstance(v.value, (int, Fraction)) and v.metric not in ("unresolved_base", "cycle_file", "cycle_component", "cross_service_import") and not v.metric.startswith("smell_"):
                f["limit"] = str(v.value)
            fields.append(f)
    return fields


def render(entries):
    return HEADER + "".join(f"### {ident}\n" + "".join(f"- {k}: {v}\n" for k, v in fields.items()) + "\n" for ident, fields in entries)


def fold(old, current, entries, violations):
    """Add only explicitly admitted budgets before the ordinary tightening pass."""
    out = copy.deepcopy(old)
    for e in entries:
        f = e.fields
        if f.get("action") != "admit":
            continue
        service, kind, location = f["target"].split("|", 2)
        if kind == "cross_service_import":
            out["cross_service_imports"].append(location)
            continue
        s, now = out["services"][service], current["services"][service]
        if kind.startswith("cycle_"):
            s["cycles_" + kind.removeprefix("cycle_")].append(location.split(","))
        elif kind.startswith("smell_"):
            s["smells"][kind.removeprefix("smell_")].append(location)
        elif kind == "file":
            for field in ("fan_out", "fan_in"):
                s[field][location] = now[field][location]
            s["graph"].setdefault(location, [])
            s["reach"].setdefault(location, [])
        elif kind in ("function", "self_calls"):
            field = "functions" if kind == "function" else kind
            s[field][location] = now[field][location]
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
            field = v.metric.removeprefix("function_")
            s["functions"].setdefault(location, dict(now["functions"][location]))[field] = v.value
        elif v.metric == "self_calls":
            s["self_calls"][location] = v.value
        elif v.metric.startswith("smell_"):
            s["smells"][v.metric.removeprefix("smell_")].append(location)
        elif v.metric in ("cycle_file", "cycle_component"):
            s["cycles_" + v.metric.removeprefix("cycle_")].append(location.split(","))
        elif v.metric == "cross_service_import":
            out["cross_service_imports"].append(location)
    return out
