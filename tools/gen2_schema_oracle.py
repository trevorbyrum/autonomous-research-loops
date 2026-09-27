#!/usr/bin/env python3
"""The independent JSON Schema oracle for the router's validator (task 1b).

The router validates documents with gen2/router/schemas.py, a validator for
exactly the Draft 2020-12 keywords gen2/schema/ uses (the dev-only
`jsonschema` package is granted to no gen2 module). This tool holds the
comparison against the pinned `jsonschema` 4.10.3, with the same date-time
format rule tools/check_gen2_schemas.py registers, so gen2/tests reach the
oracle the way they reach the other build tools: as a subprocess.

  differential   every committed fixture (valid and patched invalid) and
                 single-point mutations of every valid fixture: print the
                 counts and every disagreement; exit 1 on any.
  check          read [{"target", "instance"}, ...] as JSON on stdin; print
                 [{"oracle": bool, "router": bool}, ...].

--validator PATH loads the router's validator from PATH instead of
gen2/router/schemas.py (tools/gen2_mutations.py points it at mutated copies).
The schema directory is always this checkout's gen2/schema/.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

import check_gen2_schemas as checker  # noqa: E402
import jsonschema  # noqa: E402

from gen2.core.instants import is_utc_instant  # noqa: E402

SCHEMA_DIR = ROOT / "gen2" / "schema"
ID_BASE = "https://research-loops.invalid/gen2/schema/"
REPLACEMENTS = (None, True, 0, -1, 1.5, 2**53, "", "x", "2026-02-30T00:00:00Z", [], {})


def load_validator(path: Path):
    spec = importlib.util.spec_from_file_location("router_schemas_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SchemaSet(directory=SCHEMA_DIR)


def oracle():
    docs = {}
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        doc = checker.load_json(path)
        docs[doc["$id"]] = doc
    formats = jsonschema.FormatChecker(formats=())

    @formats.checks("date-time")
    def _instant(instance) -> bool:
        return not isinstance(instance, str) or is_utc_instant(instance)

    validators = {}

    def valid(instance, target: str) -> bool:
        if target not in validators:
            name, _, fragment = target.partition("#")
            sid = ID_BASE + name
            resolver = jsonschema.RefResolver(base_uri=sid, referrer=docs[sid], store=docs)
            schema = resolver.resolve(f"{sid}#{fragment}")[1] if fragment else docs[sid]
            validators[target] = jsonschema.Draft202012Validator(schema, resolver=resolver, format_checker=formats)
        return validators[target].is_valid(instance)

    return valid


def fixtures():
    for path in sorted((SCHEMA_DIR / "examples").rglob("*.json")):
        fixture = checker.load_json(path)
        meta = fixture["fixture"]
        if meta["expect"] == "valid":
            instance = fixture["instance"]
        else:
            base = checker.load_json(path.parent / meta["base"])
            instance = checker.apply_patch(base["instance"], meta["patch"])
        yield path.relative_to(SCHEMA_DIR).as_posix(), meta["schema"], meta["expect"], instance


def mutations(value, path=()):
    """Single-point mutations: drop each key, add an unknown key, duplicate or
    empty each array, and swap each leaf for values of other types and
    near-miss values (a suffix on strings, +1 and float form on integers)."""
    if isinstance(value, dict):
        yield path + ("+key",), {**value, "zz_unexpected": 1}
        for key in value:
            yield path + (key, "-"), {k: v for k, v in value.items() if k != key}
            for sub_path, sub in mutations(value[key], path + (key,)):
                yield sub_path, {**value, key: sub}
    elif isinstance(value, list):
        if value:
            yield path + ("dup",), value + [copy.deepcopy(value[0])]
            yield path + ("empty",), []
        for index, item in enumerate(value):
            for sub_path, sub in mutations(item, path + (index,)):
                yield sub_path, value[:index] + [sub] + value[index + 1:]
    else:
        for replacement in REPLACEMENTS:
            if type(replacement) is not type(value) or replacement != value:
                yield path + (repr(replacement),), replacement
        if isinstance(value, str):
            yield path + ("suffix",), value + "!"
        if isinstance(value, int) and not isinstance(value, bool):
            yield path + ("+1",), value + 1
            yield path + ("float",), float(value)


def differential(router) -> dict:
    valid = oracle()
    report = {"fixtures": 0, "fixture_disagreements": [], "compared": 0, "disagreements": []}
    for name, target, expect, instance in fixtures():
        report["fixtures"] += 1
        theirs, ours = valid(instance, target), not router.errors(instance, target)
        if theirs != (expect == "valid") or ours != theirs:
            report["fixture_disagreements"].append({"fixture": name, "expect": expect, "oracle": theirs, "router": ours})
        if expect != "valid":
            continue
        for where, mutant in mutations(instance):
            report["compared"] += 1
            theirs, ours = valid(mutant, target), not router.errors(mutant, target)
            if theirs != ours:
                report["disagreements"].append({"fixture": name, "at": [str(p) for p in where], "oracle": theirs, "router": ours})
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("differential", "check"))
    parser.add_argument("--validator", type=Path, default=ROOT / "gen2" / "router" / "schemas.py")
    args = parser.parse_args(argv)
    router = load_validator(args.validator)
    if args.mode == "differential":
        report = differential(router)
        print(json.dumps(report))
        return 1 if report["fixture_disagreements"] or report["disagreements"] else 0
    valid = oracle()
    cases = json.load(sys.stdin)
    print(json.dumps([{"oracle": valid(c["instance"], c["target"]), "router": not router.errors(c["instance"], c["target"])} for c in cases]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
