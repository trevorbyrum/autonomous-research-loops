"""Finite completion oracle independent of standing, chain and bound helpers.

Run in the attested child tree so Hypothesis also exercises accounting mutants.
Abstract roots prescribe possible completions; fixture construction only encodes
their observations. The oracle assigns first-owner credit directly from sets.
"""
from dataclasses import replace
from itertools import combinations, product

from gen2 import accounting as a
from gen2.accounting import stopping as s
from gen2.tests.test_coverage_dependencies import history, page
from gen2.tests.test_stopping import CTX, DATE

MODES = ("complete", "failed", "invalid", "nonpaging", "missing", "partial", "unobserved",
         "end_unknown", "prefix", "interior", "metadata", "running", "missing_delegate")
PINS = ("current", "compatible", "stale", "unknown", "missing_pin")
COUNTS = dict(inventories=0, completions=0, verdicts=0, approximations=0)


def observed_inventory(specs):
    observations, delegates, pins, passes = [], [], [], []
    for i, (mode, searches, pin, depth) in enumerate(specs):
        identity, owner = f"p{i}", f"p{i}"
        passes.append(a.Pass(identity, "research_pass", "failed" if mode == "failed" else "running" if mode == "running" else "committed"))
        for d in range(depth):
            child = f"p{i}-d{d}"
            delegates.append(a.Pass(child, "delegate", "committed", owner))
            if d:
                observations.append(replace(page(owner, "nonpaging"), request_type="resolve", page=None))
            owner = child
        if mode not in ("missing", "missing_delegate"):
            for q in sorted(searches):
                query = f"q{q}"
                obs = page(owner, query)
                if mode == "prefix":
                    captures = (page(owner, query, 2, "next"),)
                elif mode == "interior":
                    captures = (page(owner, query, 1, None, "a", "continuation"), page(owner, query, 3, "b"))
                elif mode == "invalid":
                    captures = (page(owner, query, 2),)
                else:
                    if mode in ("partial", "unobserved"):
                        obs = replace(obs, completeness=mode, page_outcome="end_unknown", result_count=None if mode == "unobserved" else 0)
                    elif mode == "end_unknown":
                        obs = replace(obs, page_outcome="end_unknown")
                    elif mode == "metadata":
                        obs = replace(obs, page=None)
                    elif mode == "nonpaging":
                        obs = replace(obs, request_type="resolve", page=None)
                    captures = (obs,)
                observations.extend(captures)
        if mode == "missing_delegate":
            # Recorded parent searches cannot bound a missing delegate's searches.
            observations.append(page(identity, f"q{min(searches)}"))
            delegates.append(a.Pass(f"p{i}-missing", "delegate", "committed", owner))
        if pin != "missing_pin":
            pins.append(s.WindowPin(identity, {"current": 1, "stale": 2, "compatible": 3, "unknown": 4}[pin]))
    impact = a.AmendmentImpact("impact", 1, (a.RevisionStanding(2, "protocol_changed"), a.RevisionStanding(3, "compatible")), (), DATE)
    inv = history((), observations)
    return replace(inv, passes=tuple(passes + delegates), amendment_impacts=(impact,)), tuple(pins)


def completion_options(spec, universe):
    mode, searches, pin, _ = spec
    if mode in ("failed", "invalid", "nonpaging"):
        captures = (frozenset(),)
    elif mode == "complete":
        captures = (searches,)
    elif mode in ("missing", "missing_delegate", "metadata"):
        captures = tuple(frozenset(c) for n in range(len(universe) + 1) for c in combinations(universe, n))
        if mode == "missing_delegate":
            captures = tuple(c for c in captures if not c or min(searches) in c)
    else:
        captures = (frozenset(), searches)  # Failed/uncompleted, or repaired capture.
    standing = (False, True) if pin in ("unknown", "missing_pin") else (pin != "stale",)
    return tuple(product(captures, standing))


def certain_counts(specs, scope):
    universe = sorted(set().union(*(r[1] for r in specs)) | {3})  # Exactly one fresh search.
    counts = set()
    for completion in product(*(completion_options(r, universe) for r in specs)):
        seen, total = set(), 0
        for i, (searches, current) in enumerate(completion):
            if searches - seen and current and (scope is None or f"p{i}" in scope):
                total += 1
            seen.update(searches)  # Global E-4 allocation precedes scope and G-1 reuse.
        counts.add(total)
        COUNTS["completions"] += 1
    return counts


def reference_model(specs, mask, unscoped):
    scope = None if unscoped else frozenset(f"p{i}" for i in range(len(specs)) if mask & (1 << i))
    inv, pins = observed_inventory(specs)
    possible = certain_counts(specs, scope)
    for minimum in range(1, len(specs) + 2):
        result = s.coverage(CTX, "coverage", inv, pins, minimum, scope=scope)
        outcomes = {count >= minimum for count in possible}
        assert result.operands.lower <= min(possible), (specs, scope, result, possible)
        assert result.operands.upper >= max(possible), (specs, scope, result, possible)
        if result.state == "satisfied":
            assert outcomes == {True}, (specs, scope, minimum, result, possible)
        elif result.state == "not_satisfied":
            assert outcomes == {False}, (specs, scope, minimum, result, possible)
        else:
            COUNTS["approximations"] += len(outcomes) == 1
        COUNTS["verdicts"] += 1
    COUNTS["inventories"] += 1
