"""Small shared recording and exhaustive partition helpers for CI runners."""
from __future__ import annotations

import hashlib
import json
import os
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def record(name: str, value: object) -> None:
    if directory := os.environ.get("GEN2_CI_EVIDENCE"):
        write_json(Path(directory) / name, value)


def junit(name: str, outcomes: list[dict]) -> None:
    if not (directory := os.environ.get("GEN2_CI_EVIDENCE")):
        return
    suite = ET.Element("testsuite", name=name, tests=str(len(outcomes)))
    for outcome in outcomes:
        case = ET.SubElement(suite, "testcase", name=outcome["id"], classname=name)
        status = outcome["outcome"]
        if status in ("skip", "expected_failure"):
            ET.SubElement(case, "skipped", message=outcome.get("detail") or status)
        elif status != "pass":
            ET.SubElement(case, "error" if status == "error" else "failure", message=status)
    ET.ElementTree(suite).write(Path(directory) / (name + ".xml"), encoding="utf-8", xml_declaration=True)


def shard_spec(text: str) -> tuple[int, int]:
    index, total = map(int, text.split("/"))
    if not 1 <= index <= total <= 64:
        raise ValueError("shard must be INDEX/TOTAL, with 1 <= INDEX <= TOTAL <= 64")
    return index, total


def in_shard(identity: str, shard: tuple[int, int]) -> bool:
    index, total = shard
    return int.from_bytes(hashlib.sha256(identity.encode()).digest(), "big") % total == index - 1


def tests(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from tests(item)
        else:
            yield item


def partition(suite, shard: tuple[int, int]) -> unittest.TestSuite:
    # Keep a class together: no extra class fixture transitions or ordering changes.
    return unittest.TestSuite(test for test in tests(suite) if in_shard(
        test.__class__.__module__ + "." + test.__class__.__qualname__, shard))


class Outcomes(unittest.TextTestResult):
    """Preserve unittest's verdict, and record test/subtest identities separately."""

    def __init__(self, *args):
        super().__init__(*args)
        self.outcomes = []
        self.completed = set()

    def observed(self, test, outcome, detail=None):
        self.outcomes.append({"id": test.id(), "outcome": outcome, "detail": detail})
        self.completed.add(test.id())

    def addSuccess(self, test):
        self.observed(test, "pass")
        super().addSuccess(test)

    def addFailure(self, test, err):
        self.observed(test, "fail")
        super().addFailure(test, err)

    def addError(self, test, err):
        self.observed(test, "error")
        super().addError(test, err)

    def addSkip(self, test, reason):
        self.observed(test, "skip", reason)
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        self.observed(test, "expected_failure")
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self.observed(test, "unexpected_success")
        super().addUnexpectedSuccess(test)

    def addSubTest(self, test, subtest, err):
        outcome = "pass" if err is None else "fail" if issubclass(err[0], test.failureException) else "error"
        self.observed(subtest, outcome)
        super().addSubTest(test, subtest, err)

    def stopTest(self, test):
        if test.id() not in self.completed:
            errors = {item.id() for item, _ in self.errors}
            children = [item for item in self.outcomes if item["id"].startswith(test.id() + " ")]
            outcome = "error" if test.id() in errors or any(item["outcome"] == "error" for item in children) else "fail"
            self.observed(test, outcome)
        super().stopTest(test)
