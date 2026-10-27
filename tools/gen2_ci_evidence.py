"""Small shared recording and exhaustive partition helpers for CI runners."""
from __future__ import annotations

import hashlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


def complete_union(inventories, total):
    """Validate occurrences, while forbidding identities shared between shards."""
    expected = Counter(inventories[0]["expected"]) if inventories else Counter()
    seen, selected = set(), Counter()
    if len(inventories) != total or not expected:
        raise ValueError("requires the complete union of shards")
    for index, row in enumerate(inventories, 1):
        identities = set(row["selected"])
        if (row["shard"] != [index, total] or not row["success"] or
                Counter(row["expected"]) != expected or seen & identities):
            raise ValueError("failed, overlapping or inconsistent shard")
        seen.update(identities)
        selected.update(row["selected"])
    if selected != expected:
        raise ValueError("requires the complete union of shards")


def parallel(commands, directory):
    """Standard process execution; each worker owns its evidence and log files."""
    def execute(item):
        index, command = item
        out = Path(directory) / f"shard-{index}"
        out.mkdir(parents=True)
        log = out / "console.log"
        env = {**os.environ, "GEN2_CI_EVIDENCE": str(out), "GEN2_TEST_LOG": str(out / "tests.log")}
        with log.open("w") as stream:
            result = subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT)
        return result.returncode, out
    with ThreadPoolExecutor(max_workers=len(commands)) as executor:
        return list(executor.map(execute, enumerate(commands, 1)))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def record(name: str, value: object) -> None:
    if directory := os.environ.get("GEN2_CI_EVIDENCE"):
        write_json(Path(directory) / name, value)


def junit(name: str, outcomes: list[dict], properties: dict | None = None) -> None:
    if not (directory := os.environ.get("GEN2_CI_EVIDENCE")):
        return
    identity = Path(directory) / "run.json"
    metadata = json.loads(identity.read_text()) if identity.exists() else {}
    metadata.update(properties or {})
    context = {key: metadata[key] for key in
               ("checkout_sha", "tree", "source_dirty", "mode", "shard", "acceptance", "banner", "ran", "omitted")
               if key in metadata}
    label = name
    if "mode" in context and "shard" in context:
        index, total = context["shard"]
        label += f" [mode={context['mode']} shard={index}/{total} sha={context.get('checkout_sha', 'unknown')}]"
    suite = ET.Element("testsuite", name=label, tests=str(len(outcomes)))
    props = ET.SubElement(suite, "properties")
    for key, value in context.items():
        ET.SubElement(props, "property", name=key, value=value if isinstance(value, str) else json.dumps(value))
    for outcome in outcomes:
        case = ET.SubElement(suite, "testcase", name=outcome["id"], classname=label)
        status = outcome["outcome"]
        if status in ("skip", "expected_failure"):
            detail = outcome.get("detail")
            ET.SubElement(case, "skipped", message=status if detail is None else detail)
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
    # Keep all occurrences of a class in one shard, in discovery-relative order.
    # Filtering can coalesce fixture transitions when intervening classes vanish.
    return unittest.TestSuite(test for test in tests(suite) if in_shard(
        test.__class__.__module__ + "." + test.__class__.__qualname__, shard))


class Outcomes(unittest.TextTestResult):
    """Preserve unittest's verdict, and record test/subtest identities separately."""

    def __init__(self, *args):
        super().__init__(*args)
        self.outcomes = []
        self.current_id = None
        self.current_recorded = False
        self.current_subtests = []

    def startTest(self, test):
        self.current_id = test.id()
        self.current_recorded = False
        self.current_subtests = []
        super().startTest(test)

    def observed(self, test, outcome, detail=None):
        self.outcomes.append({"id": test.id(), "outcome": outcome, "detail": detail})
        if test.id() == self.current_id:
            self.current_recorded = True

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
        if getattr(test, "test_case", None) is not None and test.test_case.id() == self.current_id:
            self.current_subtests.append("skip")
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
        self.current_subtests.append(outcome)
        self.observed(subtest, outcome)
        super().addSubTest(test, subtest, err)

    def stopTest(self, test):
        if not self.current_recorded:
            # unittest suppresses addSuccess after a subtest skip as well as
            # after a failure/error. Derive this occurrence's parent outcome
            # from its subtests, never earlier occurrences of the same ID.
            outcome = ("error" if "error" in self.current_subtests else
                       "fail" if "fail" in self.current_subtests else
                       "pass" if "skip" in self.current_subtests else "fail")
            self.observed(test, outcome)
        super().stopTest(test)
