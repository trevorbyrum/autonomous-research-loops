#!/usr/bin/env python3
"""Blocking cyclomatic ceilings over engine and gateway production functions."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from radon.complexity import add_inner_blocks, cc_rank, cc_visit
from radon.visitors import Function


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-function", type=int, required=True)
    parser.add_argument("--max-average", type=float, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    files = subprocess.check_output(["git", "ls-files", "--", "gen2", "gateway/research_gateway"], cwd=args.root, text=True).splitlines()
    functions = []
    try:
        for path in files:
            if not path.endswith(".py") or path.startswith("gen2/tests/") or not (args.root / path).is_file():
                continue
            for block in add_inner_blocks(cc_visit((args.root / path).read_text(encoding="utf-8"))):
                if isinstance(block, Function):
                    functions.append((block.complexity, path, block.lineno, block.name))
    except (OSError, SyntaxError) as error:
        parser.exit(2, f"gen2-complexity: {error}\n")
    if not functions:
        parser.exit(2, "gen2-complexity: no production functions found\n")
    average = sum(score for score, *_ in functions) / len(functions)
    worst = max(functions)
    print(f"gen2-complexity: {len(functions)} functions; worst {worst[0]} ({cc_rank(worst[0])}) at {worst[1]}:{worst[2]}::{worst[3]}; "
          f"average {average:.6f} ({cc_rank(average)}); ceilings {args.max_function}/{args.max_average:g}")
    for score, path, line, name in sorted(functions, reverse=True):
        if score > args.max_function:
            print(f"COMPLEXITY EXCEEDED: {path}:{line}::{name}: {score} > {args.max_function}")
    if average > args.max_average:
        print(f"AVERAGE COMPLEXITY EXCEEDED: {average:.6f} > {args.max_average:g}")
    return int(worst[0] > args.max_function or average > args.max_average)


if __name__ == "__main__":
    raise SystemExit(main())
