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
import sys
import tempfile
import time
import unittest
from pathlib import Path

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
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    log = Path(os.environ.get("GEN2_TEST_LOG") or Path(tempfile.gettempdir()) / "gen2-test-logs" / f"gen2-test-{stamp}.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(ROOT / "gen2" / "tests"), str(ROOT)]  # as `python -m unittest discover -s gen2/tests` from the repository
    with open(log, "w", encoding="utf-8") as handle:
        tee = Tee(sys.__stderr__, handle)
        sys.stdout = sys.stderr = tee  # what the tests print is kept with their outcomes
        try:
            print(f"gen2-test: the whole verbose output is kept in {log}")
            suite = unittest.defaultTestLoader.discover(str(ROOT / "gen2" / "tests"), pattern="test_*.py")
            result = unittest.TextTestRunner(stream=tee, verbosity=2).run(suite)
            print(f"gen2-test: {'passed' if result.wasSuccessful() else 'FAILED'}; the whole verbose output is kept in {log}")
        finally:
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__  # before the log closes: nothing may write to it afterwards
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
