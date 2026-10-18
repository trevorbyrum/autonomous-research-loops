#!/usr/bin/env python3
"""Compare complete engine evidence at one source SHA, including exhaustive shards.

Missing/duplicate work, failed invocations and different source pins are errors.
This checks execution equality, not oracle correctness or CI qualification.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from gen2_ci_evidence import write_json


def read(path):
    return json.loads(path.read_text())


def inventory(root: Path, filename: str) -> set[str]:
    expected, observed = None, set()
    found = list(root.rglob(filename))
    if not found:
        raise ValueError(f"missing {filename} in {root}")
    for path in found:
        report = read(path)
        full, selected = set(report["expected"]), report["selected"]
        if len(full) != len(report["expected"]) or len(set(selected)) != len(selected):
            raise ValueError(f"duplicate inventory identities in {path}")
        if expected is not None and full != expected:
            raise ValueError(f"different full inventories at {path}")
        if not set(selected) <= full or observed & set(selected):
            raise ValueError(f"unknown or repeated shard identities in {path}")
        observed.update(selected)
        expected = full
    if not expected or expected != observed:
        raise ValueError(f"incomplete shard coverage for {filename}: missing {sorted(expected - observed)}")
    return expected


def collect(root: Path, sha: str) -> dict:
    runs = list(root.rglob("run.json"))
    if not runs or any(read(path).get("checkout_sha") != sha or read(path).get("status") != "pass"
                       or read(path).get("source_dirty", True) for path in runs):
        raise ValueError(f"missing, failed or incorrectly pinned invocations in {root}")
    expected_tests = inventory(root, "engine-unit-inventory.json")
    mutants = inventory(root, "engine-mutation-inventory.json")
    outcomes = [outcome for path in root.rglob("engine-unit-outcomes.json") for outcome in read(path)]
    parents = {item["id"] for item in outcomes if item["id"] in expected_tests}
    if parents != expected_tests or any(item["outcome"] != "pass" for item in outcomes):
        raise ValueError(f"unit outcomes missing or non-passing in {root}")
    cases = [read(path) for path in root.glob("**/mutants/*.json")]
    if len(cases) != len(mutants) or {case["id"] for case in cases} != mutants:
        raise ValueError(f"mutant outcomes missing or duplicated in {root}")
    if any(case["verdict"] != "KILLED" for case in cases):
        raise ValueError(f"non-killed mutants in {root}")
    orders = list(root.rglob("trigger-order-outcomes.json"))
    if len(orders) != 1:
        raise ValueError(f"need exactly one trigger-order run in {root}")
    trigger = read(orders[0])
    if not trigger["original"] or trigger["original"] != trigger["reversed"] or set(trigger["original"].values()) != {"pass"}:
        raise ValueError(f"invalid trigger-order outcomes in {root}")
    baselines = [read(path)["baselines"] for path in root.rglob("engine-mutation-inventory.json")]
    if any(value != baselines[0] for value in baselines):
        raise ValueError(f"mutation shard baselines disagree in {root}")
    return {"unit": dict(Counter(json.dumps(item, sort_keys=True) for item in outcomes)),
            "mutants": {case["id"]: case for case in cases}, "trigger_order": trigger,
            "mutation_baselines": baselines[0]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    a, b = collect(args.reference, args.sha), collect(args.candidate, args.sha)
    differences = {key: {"reference": a[key], "candidate": b[key]} for key in a if a[key] != b[key]}
    write_json(args.out, {"sha": args.sha, "equal": not differences, "differences": differences,
                          "unit_outcomes": sum(a["unit"].values()), "mutants": len(a["mutants"])})
    print(f"engine identity comparison: {'equal' if not differences else 'DIFFERENT'}")
    return int(bool(differences))


if __name__ == "__main__":
    raise SystemExit(main())
