"""Verification allocation and exhaustive partition regressions (ci-2).

Synthetic cgroups exercise the host-visible-core defect without changing the
host. Partitions retain whole unittest classes and every inventory identity.
"""
from __future__ import annotations

import io
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

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
