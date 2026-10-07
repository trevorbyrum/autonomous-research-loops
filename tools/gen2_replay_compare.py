#!/usr/bin/env python3
"""Exact comparison of Router replays (task 2q-b3b), the other half of tools/gen2_replay.py.

    python tools/gen2_replay_compare.py --before BASE_1.json.gz BASE_2.json.gz [BASE_n ...] --after AFTER_1.json.gz [AFTER_n ...] [--report OUT.json]

BASE_* are runs of the tree before the change (at least two: one run cannot show whether the replay is stable), AFTER_* runs of the changed tree. One equivalence relation and no
weaker one: records are the same only if equal as the recorder wrote them, value for value and type for type (an id's namespace, the duration between two instants, a list's
order, a hash, every `invocation_status` poll and every store observation included). A test is
  same        every run before equals the first, every run after equals it, and the first run after equals the first before;
  different   no run of either tree disagrees with its own first run, and the first run after differs from the first before;
  unresolved  some run disagrees with its own tree's first run, whatever the trees show: nothing is concluded, the sources are named (a test missing from a run differs). Where the
              first run after also differs from the first before at a place no run disagreed at, `outside_noise` lists it for the reader; the verdict does not change.
Exit 0 only when every test is `same`, 1 when any is `different`, 2 when none is but any is unresolved (or fewer than two baselines were given). Unresolved is not a pass: the
source it names is to be fixed at its seam in the recorder and the runs repeated.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import sys


def load(path: str) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)["tests"]


def differences(x, y, path: tuple, out: collections.Counter) -> None:
    """Every place two JSON values differ: a path, counted; a list of another length differs as a whole, an int is not a float and not a bool, a NaN equals a NaN."""
    if type(x) is not type(y):
        out[path] += 1
    elif isinstance(x, dict):
        for key in x.keys() | y.keys():
            if key in x and key in y:
                differences(x[key], y[key], path + (key,), out)
            else:
                out[path + (key,)] += 1
    elif isinstance(x, list):
        if len(x) != len(y):
            out[path + ("[length]",)] += 1
        else:
            for index, (p, q) in enumerate(zip(x, y)):
                differences(p, q, path + (index,), out)
    elif x != y and not (x != x and y != y):  # a NaN is the same value as a NaN: the recorder wrote the same text for both
        out[path] += 1


def named(x: dict, y: dict) -> collections.Counter:
    """Where two records of one test disagree, by name: a call by its method and the field path inside it, the k-th call of a method against the k-th of the same method in the
    other run (so a run with one more poll still shows what else differs), and the count or order of the calls by method; a count is not part of a name."""
    out: collections.Counter = collections.Counter()
    differences({k: v for k, v in x.items() if k != "calls"}, {k: v for k, v in y.items() if k != "calls"}, (), out)
    names = collections.Counter(".".join(str(p) for p in path if not isinstance(p, int)) for path in out)
    methods = lambda r: [c["method"] for c in r.get("calls", [])]  # a skipped test has no calls
    for method in sorted(set(methods(x)) | set(methods(y))):
        found = collections.Counter()
        a, b = [c for c in x.get("calls", []) if c["method"] == method], [c for c in y.get("calls", []) if c["method"] == method]
        if len(a) != len(b):
            names[f"calls: the number of {method} calls differs"] += 1
        for p, q in zip(a, b):
            differences(p, q, (), found)
        names.update({f"{method} " + ".".join(str(k) for k in path if not isinstance(k, int)): n for path, n in found.items()})
    if methods(x) != methods(y) and sorted(methods(x)) == sorted(methods(y)):
        names["calls: the order of the calls differs"] += 1
    return names


def sources(x: dict | None, y: dict | None) -> collections.Counter:
    """Empty when the records are equal; otherwise the places they differ, named."""
    if x is None or y is None:
        return collections.Counter({} if x is y else {"test missing from one run": 1})
    out: collections.Counter = collections.Counter()
    differences(x, y, (), out)
    return (named(x, y) or collections.Counter({"calls differ": 1})) if out else out


def compare(before: list[dict], after: list[dict]) -> dict:
    """before, after: the {test: record} of each run of the tree before and of the changed tree. Returns {'result', 'tests': {name: {'verdict', 'sources'}}, 'counts', 'observed'}."""
    verdicts, observed = {}, collections.Counter()
    for name in sorted(set().union(*before, *after)):
        first, new = before[0].get(name), after[0].get(name)
        noise = collections.Counter()
        for runs in (before, after):
            for run in runs[1:]:
                noise.update(sources(runs[0].get(name), run.get(name)))
        delta = sources(first, new)
        verdict = "unresolved" if noise else "different" if delta else "same"
        verdicts[name] = {"verdict": verdict, "sources": dict(noise or delta)}
        if noise and set(delta) - set(noise):
            verdicts[name]["outside_noise"] = sorted(set(delta) - set(noise))
        if verdict == "same":
            observed["tests"] += 1
            for call in first.get("calls", []):
                observed["calls"] += 1
                observed[call["method"]] += 1
                observed["store observations after a call"] += "store" in call
            observed["end-of-test observations"] += len(first.get("end", []))
    counts = collections.Counter(v["verdict"] for v in verdicts.values())
    result = "DIFFERENT" if counts["different"] else "UNRESOLVED" if counts["unresolved"] else "EQUIVALENT"
    return {"result": result, "tests": verdicts, "counts": dict(counts), "observed": dict(observed)}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--before", nargs="+", required=True), parser.add_argument("--after", nargs="+", required=True), parser.add_argument("--report")
    args = parser.parse_args(argv)
    if len(args.before) < 2:
        print("UNRESOLVED: one baseline run cannot show whether the replay is stable; give at least two", file=sys.stderr)
        return 2
    report = compare([load(p) for p in args.before], [load(p) for p in args.after])
    report["inputs"] = {p: hashlib.sha256(open(p, "rb").read()).hexdigest() for p in [*args.before, *args.after]}
    if args.report:
        json.dump(report, open(args.report, "w"), indent=1, sort_keys=True)
    print(f"{report['result']}: {len(report['tests'])} tests: " + ", ".join(f"{n} {v}" for v, n in sorted(report["counts"].items())))
    print("compared exactly, in the tests that are the same: " + ", ".join(f"{k} {n}" for k, n in sorted(report["observed"].items())))
    for name, verdict in report["tests"].items():
        if verdict["verdict"] != "same":
            print(f"  {verdict['verdict'].upper()} {name}: " + "; ".join(f"{k} ({n})" for k, n in sorted(verdict["sources"].items())[:6]))
    return {"EQUIVALENT": 0, "DIFFERENT": 1, "UNRESOLVED": 2}[report["result"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
