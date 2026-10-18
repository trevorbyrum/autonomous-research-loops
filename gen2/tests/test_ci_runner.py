"""Verification allocation and exhaustive partition regressions (ci-2).

Synthetic cgroups exercise the host-visible-core defect without changing the
host. Partitions retain whole unittest classes and every inventory identity.
"""
from __future__ import annotations

import io
import importlib.util
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

def tool(name):
    path = Path(__file__).resolve().parents[2] / "tools" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name + "_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EVIDENCE, WORKERS = tool("gen2_ci_evidence"), tool("gen2_workers")
Outcomes, in_shard, partition, shard_spec, tests = (getattr(EVIDENCE, name) for name in
                                                 ("Outcomes", "in_shard", "partition", "shard_spec", "tests"))
cpu_budget, mutation_workers = WORKERS.cpu_budget, WORKERS.mutation_workers
with mock.patch.dict(sys.modules, {"gen2_ci_evidence": EVIDENCE, "gen2_workers": WORKERS}):
    COMPARE, RUNNER = tool("gen2_ci_compare"), tool("gen2_ci")


class CPUQuotaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "self").mkdir()
        self.mount = self.root / "cgroup"
        self.child = self.mount / "slice/build"
        self.child.mkdir(parents=True)

    def setup_cgroup(self, version):
        if version == 2:
            group, filesystem = "0::/slice/build\n", "cgroup2 cgroup rw"
        else:
            group, filesystem = "1:cpu,cpuacct:/slice/build\n", "cgroup cgroup rw,cpu,cpuacct"
        (self.root / "self/cgroup").write_text(group)
        (self.root / "self/mountinfo").write_text(f"1 0 0:1 / {self.mount} rw - {filesystem}\n")

    def test_v2_host_affinity_cannot_override_container_quota(self):
        self.setup_cgroup(2)
        (self.child / "cpu.max").write_text("200000 100000\n")
        self.assertEqual(cpu_budget(proc=self.root, affinity=128, allocation="64"), 2)

    def test_unlimited_child_still_obeys_parent_and_fractional_quotas(self):
        self.setup_cgroup(2)
        (self.child / "cpu.max").write_text("max 100000\n")
        (self.mount / "cpu.max").write_text("150000 100000\n")
        self.assertEqual(cpu_budget(proc=self.root, affinity=128, allocation="64"), 1)

    def test_v1_and_explicit_smaller_allocation(self):
        self.setup_cgroup(1)
        (self.child / "cpu.cfs_quota_us").write_text("400000\n")
        (self.child / "cpu.cfs_period_us").write_text("100000\n")
        self.assertEqual(cpu_budget(proc=self.root, affinity=128, allocation="2"), 2)

    def test_affinity_is_also_a_ceiling(self):
        self.setup_cgroup(2)
        (self.child / "cpu.max").write_text("800000 100000\n")
        self.assertEqual(cpu_budget(proc=self.root, affinity=2, allocation="64"), 2)

    def test_private_namespace_membership_cannot_escape_the_visible_mount(self):
        self.setup_cgroup(2)
        (self.root / "self/cgroup").write_text("0::/../../docker.slice/build\n")
        (self.mount / "cpu.max").write_text("200000 100000\n")
        self.assertEqual(cpu_budget(proc=self.root, affinity=128, allocation="64"), 2)

    def test_bad_allocations_and_quotas_fail(self):
        self.setup_cgroup(2)
        with self.assertRaises(ValueError):
            cpu_budget(proc=self.root, affinity=8, allocation="0")
        (self.child / "cpu.max").write_text("bad 100000\n")
        with self.assertRaises(ValueError):
            cpu_budget(proc=self.root, affinity=8, allocation="8")

    def test_worker_override_cannot_oversubscribe_and_leaves_room_for_children(self):
        with mock.patch.object(WORKERS, "cpu_budget", return_value=2):
            self.assertEqual(mutation_workers(99), 1)
            self.assertEqual(mutation_workers(), 1)
            with self.assertRaises(ValueError):
                mutation_workers(0)


class ExhaustivePartitionTest(unittest.TestCase):
    def test_nested_repeated_occurrences_run_in_real_partitions(self):
        class Repeated(unittest.TestCase):
            calls = 0
            def test_occurrence(self):
                type(self).calls += 1
                with self.subTest(same="identity"):
                    self.assertNotEqual(type(self).calls, 2, "later repeated occurrence must fail")
        class Other(unittest.TestCase):
            def test_a(self): pass
            def test_b(self): pass
        class Third(unittest.TestCase):
            def test_a(self): pass
        for total in (2, 3, 4, 8):
            with self.subTest(total=total):
                Repeated.calls = 0
                suite = unittest.TestSuite([
                    unittest.TestSuite([Repeated("test_occurrence"), Other("test_a")]),
                    unittest.TestSuite([unittest.TestSuite([Repeated("test_occurrence"), Third("test_a")]),
                                        Other("test_b"), Repeated("test_occurrence"), Other("test_a")])])
                original = list(tests(suite))
                parts = [list(tests(partition(suite, (i, total)))) for i in range(1, total + 1)]
                # A multiset is essential: set equality misses lost reexports.
                self.assertEqual(Counter(t.id() for p in parts for t in p), Counter(t.id() for t in original))
                locations = {}
                for index, part in enumerate(parts):
                    expected = [t for t in original if int.from_bytes(hashlib.sha256(
                        (type(t).__module__ + "." + type(t).__qualname__).encode()).digest(), "big") % total == index]
                    self.assertEqual(part, expected)
                    for test in part:
                        locations.setdefault(type(test), set()).add(index)
                self.assertEqual(set(locations), {Repeated, Other, Third})
                self.assertTrue(all(len(shards) == 1 for shards in locations.values()))
                results = [unittest.TextTestRunner(stream=io.StringIO(), resultclass=Outcomes).run(
                    unittest.TestSuite(part)) for part in parts]
                self.assertEqual(sum(r.testsRun for r in results), len(original))
                self.assertEqual(sum(len(r.failures) for r in results), 1)
                self.assertEqual(sum(len(r.errors) for r in results), 0)
                self.assertEqual(sum(not r.wasSuccessful() for r in results), 1)
                records = [item for r in results for item in r.outcomes]
                parent = Repeated("test_occurrence").id()
                self.assertEqual([x["outcome"] for x in records if x["id"] == parent], ["pass", "fail", "pass"])
                self.assertEqual([x["outcome"] for x in records if x["id"] == parent + " (same='identity')"],
                                 ["pass", "fail", "pass"])

    def test_every_identity_is_assigned_exactly_once(self):
        for total in (1, 2, 4, 8):
            for identity in ("a", "ddl-trigger-1", "2QT3-harness-a-case-keeps-the-modules-it-imported"):
                self.assertEqual(sum(in_shard(identity, (i, total)) for i in range(1, total + 1)), 1)

    def test_a_unittest_class_is_not_split_and_order_is_preserved(self):
        class Case(unittest.TestCase):
            def test_a(self): pass
            def test_b(self): pass
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Case)
        partitions = [list(tests(partition(suite, (i, 4)))) for i in range(1, 5)]
        self.assertEqual(sorted(map(len, partitions)), [0, 0, 0, 2])
        self.assertEqual([t.id() for part in partitions for t in part], [t.id() for t in tests(suite)])

    def test_invalid_shards_are_refused(self):
        for value in ("0/4", "5/4", "1/0", "1/65", "bad"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                shard_spec(value)

    def test_recording_keeps_subtest_failure_and_parent_failure(self):
        class Case(unittest.TestCase):
            def test_fails(self):
                with self.subTest(case="refused"):
                    self.fail("counterexample")
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=Outcomes).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(Case))
        self.assertFalse(result.wasSuccessful())
        self.assertEqual([item["outcome"] for item in result.outcomes], ["fail", "fail"])

    def test_reexported_test_occurrences_are_preserved_in_partitions_and_outcomes(self):
        class Case(unittest.TestCase):
            calls = 0

            def test_reexported(self):
                type(self).calls += 1
                with self.subTest(case="same identity"):
                    self.assertEqual(type(self).calls, 1)
        suite = unittest.TestSuite([Case("test_reexported"), Case("test_reexported")])
        self.assertEqual(len(list(tests(partition(suite, (1, 1))))), 2)
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=Outcomes).run(suite)
        self.assertEqual(result.testsRun, 2)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual([item["outcome"] for item in result.outcomes], ["pass", "pass", "fail", "fail"])


class OutcomeReportingTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def collect_fixture(self, name, parents, outcomes):
        root = self.root / name
        files = {"run.json": {"checkout_sha": "pin", "tree": "tree", "source_dirty": False,
                              "mode": "engine-unit", "shard": [2, 3], "status": "pass"},
                 "engine-unit-inventory.json": {"expected": parents, "selected": parents},
                 "engine-unit-outcomes.json": outcomes,
                 "engine-mutation-inventory.json": {"expected": ["mutant"], "selected": ["mutant"], "baselines": []},
                 "mutants/mutant.json": {"id": "mutant", "verdict": "KILLED"},
                 "trigger-order-outcomes.json": {"original": {"store": "pass"}, "reversed": {"store": "pass"}}}
        for filename, value in files.items():
            EVIDENCE.write_json(root / filename, value)
        with mock.patch.dict(os.environ, {"GEN2_CI_EVIDENCE": str(root)}):
            EVIDENCE.junit("engine-unit", outcomes)
        return root

    def test_skips_preserve_unittest_junit_and_comparison_verdicts(self):
        class Case(unittest.TestCase):
            def test_subtests(self):
                with self.subTest(i=1): self.skipTest("first exact reason")
                with self.subTest(i=2): pass
                with self.subTest(i=3): self.skipTest("second exact reason")
            @unittest.skip("whole exact reason")
            def test_whole(self): pass
            @unittest.expectedFailure
            def test_expected(self): self.fail("expected")
        standard, recorded = [unittest.TextTestRunner(stream=io.StringIO(), resultclass=cls).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(Case)) for cls in (unittest.TextTestResult, Outcomes)]
        self.assertTrue(standard.wasSuccessful())
        self.assertEqual(recorded.wasSuccessful(), standard.wasSuccessful())
        self.assertEqual((recorded.testsRun, len(recorded.failures), len(recorded.errors)), (3, 0, 0))
        skips = [(t.id(), reason) for t, reason in standard.skipped]
        self.assertEqual([(x["id"], x["detail"]) for x in recorded.outcomes if x["outcome"] == "skip"], skips)
        parent = Case("test_subtests").id()
        self.assertEqual([x["outcome"] for x in recorded.outcomes if x["id"] == parent], ["pass"])
        self.assertEqual([(x["id"], x["outcome"]) for x in recorded.outcomes if x["id"].startswith(parent + " (")],
                         [(parent + " (i=1)", "skip"), (parent + " (i=2)", "pass"), (parent + " (i=3)", "skip")])
        parents = [t.id() for t in unittest.defaultTestLoader.loadTestsFromTestCase(Case)]
        a = self.collect_fixture("reference", parents, recorded.outcomes)
        b = self.collect_fixture("candidate", parents, recorded.outcomes)
        self.assertEqual(COMPARE.collect(a, "pin"), COMPARE.collect(b, "pin"))
        xml = ET.parse(b / "engine-unit.xml")
        self.assertEqual(xml.findall(".//failure") + xml.findall(".//error"), [])
        self.assertEqual(len(xml.findall(".//skipped")), 4)
        self.assertEqual([case.find("skipped").get("message") for case in xml.findall(".//testcase")
                          if case.get("name") in dict(skips)], [reason for _, reason in skips])
        props = {p.get("name"): p.get("value") for p in xml.findall(".//property")}
        self.assertEqual({key: props[key] for key in ("checkout_sha", "tree", "mode", "shard")},
                         {"checkout_sha": "pin", "tree": "tree", "mode": "engine-unit", "shard": "[2, 3]"})

    def test_skip_then_failure_or_error_and_repeated_parent_remain_visible(self):
        for bad, expected in ((AssertionError, "fail"), (RuntimeError, "error")):
            with self.subTest(bad=bad):
                class Case(unittest.TestCase):
                    calls = 0
                    def test_repeated(self):
                        type(self).calls += 1
                        with self.subTest(i="skip"): self.skipTest("exact reason")
                        with self.subTest(i="body"):
                            if type(self).calls == 1: raise bad("counterexample")
                suite = unittest.TestSuite([Case("test_repeated"), Case("test_repeated")])
                recorded = unittest.TextTestRunner(stream=io.StringIO(), resultclass=Outcomes).run(suite)
                self.assertFalse(recorded.wasSuccessful())
                parent = Case("test_repeated").id()
                self.assertEqual([x["outcome"] for x in recorded.outcomes if x["id"] == parent], [expected, "pass"])
                self.assertEqual([x["detail"] for x in recorded.outcomes if x["outcome"] == "skip"],
                                 ["exact reason", "exact reason"])
                root = self.collect_fixture("case-" + expected, [parent, parent], recorded.outcomes)
                with self.assertRaisesRegex(ValueError, "unit outcomes missing or failed"):
                    COMPARE.collect(root, "pin")
                xml = ET.parse(root / "engine-unit.xml")
                self.assertEqual(len(xml.findall(".//failure" if expected == "fail" else ".//error")), 2)

    def test_comparison_rejects_changed_removed_or_new_skips_and_reasons(self):
        baseline = [{"id": "parent (i=1)", "outcome": "skip", "detail": "exact reason"},
                    {"id": "parent", "outcome": "pass", "detail": None},
                    {"id": "whole", "outcome": "skip", "detail": "whole reason"}]
        reference = self.collect_fixture("reference", ["parent", "whole"], baseline)
        for change in ("unchanged", "reason", "identity", "remove_subtest", "remove_whole", "skip_to_pass", "new_skip"):
            with self.subTest(change=change):
                outcomes = copy.deepcopy(baseline)
                if change == "reason": outcomes[0]["detail"] = "changed reason"
                if change == "identity": outcomes[0]["id"] = "parent (i=2)"
                if change == "remove_subtest": outcomes.pop(0)
                if change == "remove_whole": outcomes.pop()
                if change == "skip_to_pass": outcomes[0].update(outcome="pass", detail=None)
                if change == "new_skip": outcomes[1].update(outcome="skip", detail="new skip")
                candidate = self.collect_fixture(change, ["parent", "whole"], outcomes)
                with mock.patch.object(sys, "argv", ["compare", str(reference), str(candidate), "--sha", "pin",
                                                      "--out", str(self.root / "comparison.json")]), mock.patch("sys.stdout", io.StringIO()):
                    if change == "remove_whole":
                        with self.assertRaises(ValueError): COMPARE.main()
                    else:
                        self.assertEqual(COMPARE.main(), int(change != "unchanged"))


class PartialScopeTest(unittest.TestCase):
    def test_default_reports_scope_and_actual_execution_on_success_and_failure(self):
        for codes in ([0, 0, 0], [0, 7]):
            with self.subTest(codes=codes), tempfile.TemporaryDirectory() as directory:
                out = Path(directory)
                with mock.patch.object(RUNNER, "git", return_value="pin"), \
                     mock.patch.object(RUNNER.subprocess, "call", side_effect=codes) as execute, \
                     mock.patch("sys.stdout", new_callable=io.StringIO) as console:
                    self.assertEqual(RUNNER.default_run(out), codes[-1])
                report = json.loads((out / "default-1-of-1/scope.json").read_text())
                self.assertEqual(report["acceptance"], "partial")
                self.assertFalse(report["full_acceptance"])
                self.assertEqual(report["ran"], ["T0", "complete trigger-order", "units 1/8"])
                self.assertEqual(report["omitted"], ["unit partitions 2–8/8", "all mutation work", "all gateway modes"])
                self.assertEqual([x["status"] for x in report["executions"]],
                                 ["pass", "pass", "pass"] if len(codes) == 3 else ["pass", "fail", "not_run"])
                self.assertEqual(execute.call_count, len(codes))
                for call, (mode, shard) in zip(execute.call_args_list, RUNNER.DEFAULT_WORK):
                    self.assertIn(mode, call.args[0])
                    self.assertIn(f"{shard[0]}/{shard[1]}", call.args[0])
                self.assertEqual(console.getvalue().count(RUNNER.PARTIAL_BANNER + "\n"), 2)
                xml = ET.parse(out / "default-1-of-1/acceptance-scope.xml")
                self.assertIn(RUNNER.PARTIAL_BANNER, xml.find("testcase").get("name"))
                self.assertEqual(len(xml.findall(".//error")), int(codes[-1] != 0))
                props = {p.get("name"): p.get("value") for p in xml.findall(".//property")}
                self.assertEqual(props["checkout_sha"], "pin")
                self.assertEqual(props["mode"], "default")
                self.assertEqual(props["shard"], "[1, 1]")
