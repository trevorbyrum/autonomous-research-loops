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
  --check          exit 1 on either size rule (charter "Size rules", the
                   operator's ruling of 2026-09-29, task 2r):
                   * a hand-written tracked file in the gen-2 surface (gen2/,
                     gateway/, tools/gen2*, tools/check_*, tools/gen_*,
                     deploy/, Makefile, .github/) over 1,500 physical lines —
                     each one
                     named with its count. A generated file is exempt only by
                     an entry in GENERATED, which names the tool that writes
                     it and why; an entry whose file is not tracked, or whose
                     tool is not a tracked file naming that file's path,
                     fails the check too;
                   * production reaching 15,000 lines: the growth-review
                     trigger. The build stops for a review with the operator
                     of what made it grow before building further.
                   The gateway service is its own budget (task 2b's split):
                   its production (gateway/research_gateway/) and tests are
                   reported on their own lines and never count toward the
                   engine's trigger; its files are under the per-file limit
                   like any other in the surface (task 2b-repair A8).

What the allowlist check shows: that the named tool exists and names the
file. It does not show the committed bytes are that tool's output (for the
catalog pair, gen2-catalog-check does; the controls file is rewritten by
its tool's trace and choose steps, outside the build).

Trace: task 0a deliverable 5; task 2r; charter "Size rules"; design review
§10; docs/gen2/INVARIANTS.md B-3.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath

GROWTH_REVIEW = 15_000  # production lines: reaching it stops the build for a growth review with the operator
FILE_LIMIT = 1_500  # physical lines per hand-written file in the gen-2 surface; exactly 1,500 passes
# The gen-2 surface the per-file limit covers: tracked files under these
# prefixes, and these files.
SURFACE_PREFIXES = ("gen2/", "gateway/", "tools/gen2", "tools/check_", "tools/gen_", "deploy/", ".github/")
SURFACE_FILES = ("Makefile",)
# Generated files, exempt from the per-file limit by this list alone:
# repo-relative path -> (the tracked tool that writes it, why it is exempt).
GENERATED = {
    "tools/gen2_mutation_controls.json": (
        "tools/gen2_mutation_controls.py",
        "each mutant's paired controls, chosen by the tool from a traced run of the whole suite; one entry per mutant, so it grows with the "
        "inventory, and it is rewritten by the tool, never edited by hand"),
    "deploy/gen2.env.example": (
        "tools/gen_source_catalog.py",
        "every secret name the gen-2 stack reads, rendered from the gateway source registry; gen2-catalog-check fails on a hand edit"),
}
CODE_SUFFIXES = {".py", ".sh"}
# Gen-2 build tooling: these files, plus every tracked `tools/gen2_*` and
# `tools/check_gen2_*` file of any type — by rule rather than by list, so a new
# tool cannot silently drop out of the report (Astra re-review: the old fixed
# list omitted tools/gen2_mutations.py and tools/gen2_jcs_cross_vectors.js).
BUILD_TOOLING = {
    "tools/check_boundaries.py",
    "tools/gen_source_catalog.py",
    "Makefile",
    ".github/workflows/gen2-check.yml",
}
BUILD_TOOLING_PREFIXES = ("tools/gen2_", "tools/check_gen2_")
# Gen-2 deployment artifacts outside gen2/ (task 0c): generated or hand-written
# deployment config the gen-2 build owns. Counted as `config` so a generated
# artifact cannot grow unreported.
GEN2_DEPLOY_PREFIXES = ("deploy/gen2",)
DR_BASELINE = {"research_loops": 14_333, "gateway/research_gateway": 7_894}
# The gateway service's own budget, reported beside the engine's and never in it.
GATEWAY_PRODUCTION, GATEWAY_TESTS = "gateway/research_gateway/", "gateway/tests/"


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
    if rel.startswith(GEN2_DEPLOY_PREFIXES):
        return "config"
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


def in_surface(rel: str) -> bool:
    return rel in SURFACE_FILES or rel.startswith(SURFACE_PREFIXES)


def size_problems(root: Path, files: list[str]) -> tuple[list[tuple[str, int]], list[str]]:
    """The hand-written files in the gen-2 surface over FILE_LIMIT (path,
    lines), and why any GENERATED entry does not hold."""
    tracked = set(files)
    over = []
    for rel in files:
        if not in_surface(rel) or rel in GENERATED or not (root / rel).is_file():
            continue
        n = physical_lines(root / rel)
        if n > FILE_LIMIT:
            over.append((rel, n))
    bad = []
    for rel, (tool, _why) in GENERATED.items():
        if rel not in tracked:
            bad.append(f"{rel}: listed as generated, but it is not a tracked file")
        elif tool not in tracked or not (root / tool).is_file():
            bad.append(f"{rel}: listed as generated by {tool}, which is not a tracked file")
        elif rel not in (root / tool).read_text(encoding="utf-8", errors="replace"):
            bad.append(f"{rel}: listed as generated by {tool}, which does not name it")
    return over, bad


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
    gateway = {"production": 0, "tests": 0}
    for rel in files:
        if not (root / rel).is_file():
            continue
        if rel.startswith(GATEWAY_PRODUCTION) and PurePosixPath(rel).suffix in CODE_SUFFIXES:
            gateway["production"] += physical_lines(root / rel)
        elif rel.startswith(GATEWAY_TESTS) and PurePosixPath(rel).suffix in CODE_SUFFIXES:
            gateway["tests"] += physical_lines(root / rel)
    return {"categories": cats, "production_by_module": dict(sorted(per_module.items())), "gateway": gateway}


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
    report["budget"] = {"growth_review": GROWTH_REVIEW, "production": production, "file_limit": FILE_LIMIT}
    over, bad = size_problems(root, files)
    report["files_over_limit"] = dict(over)
    report["generated_exempt"] = {rel: {"tool": tool, "why": why} for rel, (tool, why) in GENERATED.items()}
    if args.gen1_baseline:
        report["gen1"] = {"recount": gen1_report(root, files), "design_review_baseline": DR_BASELINE}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"gen2 size (physical lines of tracked files; production growth-review trigger {GROWTH_REVIEW:,}; "
              f"per-file limit {FILE_LIMIT:,}, generated files exempt: {', '.join(GENERATED)})")
        for cat, entry in report["categories"].items():
            print(f"  {cat:16} {entry['lines']:>7,} lines in {entry['files']:>3} file(s)")
        for module, n in report["production_by_module"].items():
            print(f"    production/{module:12} {n:>7,}")
        print(f"  gateway service (its own budget, not in the trigger): production {report['gateway']['production']:,}, "
              f"tests {report['gateway']['tests']:,}")
        if args.gen1_baseline:
            for prefix, n in report["gen1"]["recount"].items():
                expected = DR_BASELINE[prefix]
                note = "matches" if n == expected else f"differs from {expected:,}"
                print(f"  gen-1 {prefix:25} {n:>7,} (design review §10 baseline: {note})")
    if report["categories"]["other"]["files"]:
        print(f"note: {report['categories']['other']['files']} tracked gen2 file(s) fit no category and are listed as other", file=sys.stderr)
    if args.check:
        for rel, n in over:
            print(f"FILE SIZE LIMIT EXCEEDED: {rel} has {n:,} lines > {FILE_LIMIT:,} (charter \"Size rules\": split it; a file a tool "
                  f"writes is exempt only by a GENERATED entry naming that tool)", file=sys.stderr)
        for problem in bad:
            print(f"GENERATED ALLOWLIST ENTRY DOES NOT HOLD: {problem}", file=sys.stderr)
        if production >= GROWTH_REVIEW:
            print(f"GROWTH REVIEW REQUIRED: {production:,} production lines reach the {GROWTH_REVIEW:,}-line trigger — stop and review with "
                  f"the operator what made it grow before building further (charter \"Size rules\")", file=sys.stderr)
        if over or bad or production >= GROWTH_REVIEW:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
