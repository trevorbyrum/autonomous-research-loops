import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "loop-queue"
        self.root.mkdir()

    def tearDown(self):
        self.tempdir.cleanup()

    def run_cli(self, *args, check=True):
        return subprocess.run(
            [sys.executable, "-m", "research_loops", "--root", str(self.root), *args],
            text=True,
            capture_output=True,
            check=check,
        )

    def test_add_list_move_pause_resume_restart_remove_and_usage(self):
        first = json.loads(
            self.run_cli("add", "--id", "first", "--title", "First", "--cwd", "/tmp", "--", "true").stdout
        )
        second = json.loads(
            self.run_cli("add", "--id", "second", "--title", "Second", "--cwd", "/tmp", "--", "true").stdout
        )
        self.run_cli("move", second["id"], "0")
        listed = json.loads(self.run_cli("list", "--json").stdout)
        self.assertEqual([item["id"] for item in listed["items"]], ["second", "first"])

        self.run_cli("pause", "first", "--reason", "hold")
        self.run_cli("resume", "first")
        restarted = json.loads(self.run_cli("restart", "first").stdout)
        self.assertEqual(restarted["restart_generation"], 1)
        self.run_cli("remove", "first")
        usage = json.loads(self.run_cli("usage", "--json").stdout)
        self.assertEqual(usage["summary"]["runs"], 0)
        # Without --include-snapshots, no snapshots key is present.
        self.assertNotIn("snapshots", usage)

    def test_only_one_queue_worker_can_run(self):
        worker = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "research_loops",
                "--root",
                str(self.root),
                "run",
                "--idle-sleep",
                "0.05",
                "--no-usage-snapshot",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            lock = self.root / "state" / "worker.lock"
            for _ in range(100):
                if lock.exists():
                    break
                import time

                time.sleep(0.01)
            second = self.run_cli("run", "--once", "--no-usage-snapshot", check=False)
            self.assertEqual(second.returncode, 2)
            self.assertIn("already running", second.stderr)
        finally:
            worker.terminate()
            worker.wait(timeout=5)
            if worker.stdout:
                worker.stdout.close()
            if worker.stderr:
                worker.stderr.close()

    def test_worker_policy_cli_switches_between_finite_and_continuous(self):
        finite = json.loads(
            self.run_cli("worker-policy", "worker-3", "--claim-limit", "2").stdout
        )
        self.assertEqual(finite, {"claim_limit": 2, "claims_used": 0})
        continuous = json.loads(
            self.run_cli("worker-policy", "worker-3", "--continuous").stdout
        )
        self.assertEqual(continuous, {"claim_limit": None, "claims_used": 0})

        invalid = self.run_cli(
            "worker-policy", "worker-3", "--claim-limit", "-1", check=False
        )
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("claim limit", invalid.stderr)

    def test_dashboard_default_and_explicit_output_do_not_mutate_queue(self):
        self.run_cli("add", "--id", "one", "--title", "One", "--cwd", "/tmp", "--", "true")
        queue_path = self.root / "state" / "queue.json"
        before = queue_path.read_bytes()

        default_result = json.loads(self.run_cli("dashboard").stdout)
        default_output = self.root.parent / "STATUS.md"
        self.assertEqual(default_result["output"], str(default_output))
        self.assertTrue(default_output.is_file())
        self.assertIn("# Research Loops Status", default_output.read_text(encoding="utf-8"))

        explicit_output = self.root / "operator-view.md"
        explicit_result = json.loads(
            self.run_cli("dashboard", "--output", str(explicit_output)).stdout
        )
        self.assertEqual(explicit_result["output"], str(explicit_output))
        self.assertTrue(explicit_output.is_file())
        self.assertEqual(queue_path.read_bytes(), before)

        invalid = self.run_cli(
            "dashboard", "--output", str(self.root / "missing" / "view.md"), check=False
        )
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("parent", invalid.stderr)

    def test_dashboard_cli_rejects_symlink_without_changing_target(self):
        target = self.root / "operator-target.md"
        target.write_text("preserve", encoding="utf-8")
        symlink = self.root / "operator-view.md"
        symlink.symlink_to(target)

        result = self.run_cli("dashboard", "--output", str(symlink), check=False)

        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink", result.stderr)
        self.assertTrue(symlink.is_symlink())
        self.assertEqual(target.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
