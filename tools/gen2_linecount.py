#!/usr/bin/env python3
"""Gen-2 size accounting, like-for-like with the design review §10 baseline.

Method (same as the baseline): physical lines — newline count, blanks and
comments included, i.e. what `cat FILES | wc -l` prints — over files tracked
by git. Production is tracked .py/.sh under gen2/ outside gen2/tests/. Tests,
schemas, schema fixtures, SQL, prompts, config, docs and gen-2 build tooling
are reported separately so functionality cannot hide in an excluded file type
(design review §10). Anything tracked under gen2/ that fits no category is
reported as `other`, never dropped.

  --gen1-baseline  recount gen-1 the same way; at gen-1 commit 7c84325 this
                   reproduces the review's 14,333 (research_loops/) and 7,894
                   (gateway/research_gateway/) exactly.
  --check          exit 1 above the 12,000-line hard ceiling (charter: scope
                   reconsideration); warn above the 10,000-line allocation.

Trace: task 0a deliverable 5; charter "Standing rules" (size budget);
design review §10; docs/gen2/INVARIANTS.md B-3.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath

ALLOCATION = 10_000
CEILING = 12_000
CODE_SUFFIXES = {".py", ".sh"}
# Gen-2 build tooling: these files, plus every tracked `tools/gen2_*` and
# `tools/check_gen2_*` file of any type — by rule rather than by list, so a new
# tool cannot silently drop out of the report (Astra re-review: the old fixed
# list omitted tools/gen2_mutations.py and tools/gen2_jcs_cross_vectors.js).
BUILD_TOOLING = {
    "tools/check_boundaries.py",
    "Makefile",
    ".github/workflows/gen2-check.yml",
}
BUILD_TOOLING_PREFIXES = ("tools/gen2_", "tools/check_gen2_")
DR_BASELINE = {"research_loops": 14_333, "gateway/research_gateway": 7_894}


def tracked_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"LINECOUNT ERROR: cannot list tracked files (git ls-files): {exc}", file=sys.stderr)
        sys.exit(2)
    return [p for p in out.decode("utf-8").split("\0") if p]


def physical_lines(path: Path) -> int:
    return path.read_bytes().count(b"\n")


def category(rel: str) -> str | None:
    p = PurePosixPath(rel)
    if rel in BUILD_TOOLING or rel.startswith(BUILD_TOOLING_PREFIXES):
        return "build_tooling"
    if rel.startswith("docs/gen2/"):
        return "docs"
    if not rel.startswith("gen2/"):
        return None
    if rel.startswith("gen2/tests/"):
        return "tests"
    if "prompts" in p.parts[:-1]:
        return "prompts"
    if rel.startswith("gen2/schema/examples/"):
        return "schema_fixtures"
    if p.name.endswith(".schema.json"):
        return "schemas"
    if p.suffix in CODE_SUFFIXES:
        return "production"
    if p.suffix == ".sql":
        return "sql"
    if p.suffix in {".toml", ".txt", ".yml", ".yaml", ".json"}:
        return "config"
    if p.suffix == ".md":
        return "docs"
    return "other"


def module_paths(root: Path) -> dict[str, str]:
    try:
        cfg = tomllib.loads((root / "gen2" / "boundaries.toml").read_text(encoding="utf-8"))
        return {name: spec["path"] for name, spec in cfg.get("modules", {}).items()}
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError):
        return {}


def gen2_report(root: Path, files: list[str]) -> dict:
    order = ("production", "tests", "schemas", "schema_fixtures", "sql", "prompts", "config", "docs", "build_tooling", "other")
    cats: dict[str, dict[str, int]] = {cat: {"files": 0, "lines": 0} for cat in order}
    per_module: dict[str, int] = {}
    modules = module_paths(root)
    for rel in files:
        cat = category(rel)
        if cat is None:
            continue
        path = root / rel
        if not path.is_file():
            continue
        n = physical_lines(path)
        entry = cats[cat]
        entry["files"] += 1
        entry["lines"] += n
        if cat == "production":
            owner = next((m for m, mp in modules.items() if rel == mp or rel.startswith(mp.rstrip("/") + "/")), "(undeclared)")
            per_module[owner] = per_module.get(owner, 0) + n
    return {"categories": cats, "production_by_module": dict(sorted(per_module.items()))}


def gen1_report(root: Path, files: list[str]) -> dict[str, int]:
    result = {}
    for prefix in DR_BASELINE:
        result[prefix] = sum(
            physical_lines(root / rel)
            for rel in files
            if rel.startswith(prefix + "/") and PurePosixPath(rel).suffix in CODE_SUFFIXES and (root / rel).is_file()
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--check", action="store_true", help="fail above the hard ceiling")
    parser.add_argument("--gen1-baseline", action="store_true", help="also recount gen-1 like-for-like")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    files = tracked_files(root)
    report = gen2_report(root, files)
    production = report["categories"]["production"]["lines"]
    report["budget"] = {"allocation": ALLOCATION, "ceiling": CEILING, "production": production}
    if args.gen1_baseline:
        report["gen1"] = {"recount": gen1_report(root, files), "design_review_baseline": DR_BASELINE}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"gen2 size (physical lines of tracked files; production budget {ALLOCATION:,}, ceiling {CEILING:,})")
        for cat, entry in report["categories"].items():
            print(f"  {cat:16} {entry['lines']:>7,} lines in {entry['files']:>3} file(s)")
        for module, n in report["production_by_module"].items():
            print(f"    production/{module:12} {n:>7,}")
        if args.gen1_baseline:
            for prefix, n in report["gen1"]["recount"].items():
                expected = DR_BASELINE[prefix]
                note = "matches" if n == expected else f"differs from {expected:,}"
                print(f"  gen-1 {prefix:25} {n:>7,} (design review §10 baseline: {note})")
    if report["categories"]["other"]["files"]:
        print(f"note: {report['categories']['other']['files']} tracked gen2 file(s) fit no category and are listed as other", file=sys.stderr)
    if args.check:
        if production > CEILING:
            print(f"SIZE CEILING EXCEEDED: {production:,} production lines > {CEILING:,} hard ceiling — scope reconsideration required (charter)", file=sys.stderr)
            return 1
        if production > ALLOCATION:
            print(f"size warning: {production:,} production lines exceed the {ALLOCATION:,} allocation (ceiling {CEILING:,})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
