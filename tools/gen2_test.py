#!/usr/bin/env python3
"""Run the gen-2 test suite verbosely and keep its whole output (make gen2-test).

Task 1c-repair C2: a failure, intermittent or not, must carry its identity.
Every test's name and outcome, every traceback, and whatever the tests write
to stdout or stderr — a failing supervisor test prints its jobs' records and
keeps its temporary tree (gen2/tests/supervisor_fixtures.py) — goes to the
terminal and, whole, to a log file: $GEN2_TEST_LOG, else
<tmp>/gen2-test-logs/gen2-test-<UTC time>.log. Its path is printed first and
last. The exit status is unittest's (0 only if every test passed): nothing
here masks a failure.
"""
from __future__ import annotations

import os
import json
import hashlib
import sys
import tempfile
import time
import unittest
from pathlib import Path

from gen2_ci_evidence import Outcomes, complete_union, junit, parallel, partition, record, shard_spec, tests
from gen2_coverage import Baseline, source_state
from gen2_mutation_runner import EvidenceResult

ROOT = Path(__file__).resolve().parent.parent


class Tee:
    """A text stream writing to every stream it holds, flushed per write."""

    def __init__(self, *streams) -> None:
        self.streams = streams

    def write(self, text: str) -> int:
        for stream in self.streams:
            stream.write(text)
            stream.flush()
        return len(text)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shard", type=shard_spec, default=(1, 1))
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.workers <= 64 or (args.workers > 1 and args.shard != (1, 1)):
        raise ValueError("workers must be 1..64 and require full discovery")
    if args.workers > 1:
        if directory := os.environ.get("GEN2_CI_EVIDENCE"):
            Path(directory).mkdir(parents=True, exist_ok=True)
        out = Path(tempfile.mkdtemp(prefix="gen2-shards-", dir=os.environ.get("GEN2_CI_EVIDENCE"))).resolve()
        capture = os.environ.get("GEN2_TEST_COVERAGE")
        baseline = Baseline(capture) if capture else None
        if baseline:
            baseline.start()
            baseline.coverage.stop()
        print(f"gen2-test: {args.workers} shards; logs in {out}", flush=True)
        runs = parallel([[sys.executable, __file__, "--worker", "--shard", f"{i}/{args.workers}"]
                         for i in range(1, args.workers + 1)], out)
        inventories = [json.loads((path / "engine-unit-inventory.json").read_text()) for _, path in runs]
        for (code, _), row in zip(runs, inventories):
            row["success"] = row["success"] and code == 0
        complete_union(inventories, args.workers)
        if baseline:
            baseline.combine(inventories, args.workers)
        outcomes = [row for _, path in runs for row in json.loads((path / "engine-unit-outcomes.json").read_text())]
        record("engine-unit-inventory.json", dict(expected=inventories[0]["expected"],
            selected=[t for row in inventories for t in row["selected"]], shard=[1, 1], shards=inventories))
        record("engine-unit-outcomes.json", outcomes)
        junit("engine-unit", outcomes)
        print(f"gen2-test: passed {sum(row['tests_run'] for row in inventories)} tests across {args.workers} shards; {out}")
        return 0
    capture = os.environ.pop("GEN2_TEST_COVERAGE", None)
    if capture and args.shard != (1, 1) and not args.worker:
        raise ValueError("a coverage baseline requires the complete union of shards")
    baseline = Baseline(capture, parallel=args.worker) if capture else None
    if args.worker:
        scratch = Path(os.environ["GEN2_CI_EVIDENCE"]) / "tmp"
        scratch.mkdir()
        tempfile.tempdir = str(scratch)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    log = Path(os.environ.pop("GEN2_TEST_LOG", None) or Path(tempfile.gettempdir()) / "gen2-test-logs" / f"gen2-test-{stamp}.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(ROOT / "gen2" / "tests"), str(ROOT)]  # as `python -m unittest discover -s gen2/tests` from the repository
    with open(log, "w", encoding="utf-8") as handle:
        tee = Tee(sys.__stderr__, handle)
        sys.stdout = sys.stderr = tee  # what the tests print is kept with their outcomes
        try:
            print(f"gen2-test: the whole verbose output is kept in {log}")
            if baseline:
                baseline.start()
            suite = unittest.defaultTestLoader.discover(str(ROOT / "gen2" / "tests"), pattern="test_*.py")
            expected = [test.id() for test in tests(suite)]
            # Existing discovery includes re-exported TestCase classes. Keep
            # every occurrence, as the original runner does; comparison uses
            # multisets rather than silently deduplicating or refusing them.
            if not expected:
                raise ValueError("test discovery is empty")
            suite = partition(suite, args.shard)
            selected = [test.id() for test in tests(suite)]
            if not selected and not args.worker:
                raise ValueError("test shard is empty")
            record("engine-unit-inventory.json", {"expected": expected, "selected": selected, "shard": args.shard})
            # Tests launch counterfactual/partial harnesses of their own. Those
            # child runs must not publish into this invocation's evidence.
            directory = os.environ.pop("GEN2_CI_EVIDENCE", None)
            try:
                resultclass = (lambda *a: type("CoveredOutcomes", (EvidenceResult, Outcomes), {})(
                    *a, coverage=baseline.coverage)) if baseline else Outcomes
                result = unittest.TextTestRunner(stream=tee, verbosity=2, resultclass=resultclass).run(suite)
            finally:
                if directory is not None:
                    os.environ["GEN2_CI_EVIDENCE"] = directory
            if baseline:
                baseline.finish(result)
            record("engine-unit-inventory.json", dict(expected=expected, selected=selected, shard=args.shard,
                success=result.wasSuccessful(), tests_run=result.testsRun,
                before=baseline.before if baseline else None, after=source_state() if baseline else None,
                coverage_file=baseline.coverage.get_data().data_filename() if baseline else None,
                coverage_sha256=hashlib.sha256(Path(baseline.coverage.get_data().data_filename()).read_bytes()).hexdigest() if baseline else None))
            record("engine-unit-outcomes.json", result.outcomes)
            junit("engine-unit", result.outcomes)
            print(f"gen2-test: {'passed' if result.wasSuccessful() else 'FAILED'}; the whole verbose output is kept in {log}")
        finally:
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__  # before the log closes: nothing may write to it afterwards
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
