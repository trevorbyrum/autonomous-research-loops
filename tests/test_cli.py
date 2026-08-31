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

    def test_add_depends_on_flag_round_trips_and_gates_claiming(self):
        self.run_cli("add", "--id", "router", "--title", "Router", "--cwd", "/tmp", "--", "true")
        consumer = json.loads(
            self.run_cli(
                "add", "--id", "consumer", "--title", "Consumer", "--cwd", "/tmp",
                "--depends-on", "router", "--", "true",
            ).stdout
        )
        self.assertEqual(consumer["depends_on"], ["router"])

        claimed = json.loads(self.run_cli("run", "--once").stdout)
        self.assertEqual(claimed["item_id"], "router")

    def test_add_depends_on_accepts_a_not_yet_added_id(self):
        # A dependency may forward-reference an id that doesn't exist yet -- it
        # only has to exist by the time this item is actually claimed (see
        # claim_next()'s own dependencies_satisfied() check).
        consumer = json.loads(
            self.run_cli(
                "add", "--id", "consumer", "--title", "Consumer", "--cwd", "/tmp",
                "--depends-on", "not-added-yet", "--", "true",
            ).stdout
        )
        self.assertEqual(consumer["depends_on"], ["not-added-yet"])

    def test_internal_citations_flag_defaults_off_and_round_trips_on(self):
        default_item = json.loads(
            self.run_cli("add", "--id", "default", "--title", "D", "--cwd", "/tmp", "--", "true").stdout
        )
        self.assertFalse(default_item["internal_citations"])

        enabled_item = json.loads(
            self.run_cli(
                "add", "--id", "enabled", "--title", "E", "--cwd", "/tmp",
                "--internal-citations", "--", "true",
            ).stdout
        )
        self.assertTrue(enabled_item["internal_citations"])

    def test_doctor_cli_reports_an_unlocked_item(self):
        self.run_cli("add", "--id", "unlocked", "--title", "U", "--cwd", "/tmp", "--", "true")
        report = json.loads(self.run_cli("doctor").stdout)
        self.assertFalse(report["healthy"])
        self.assertEqual(report["unlocked_items"], ["unlocked"])

    def test_pause_cli_defaults_graceful_and_now_flag_requests_immediate(self):
        queued = json.loads(
            self.run_cli("add", "--id", "queued", "--title", "Q", "--cwd", "/tmp", "--", "true").stdout
        )
        # A non-running item pauses immediately regardless of --now.
        self.assertEqual(queued["status"], "queued")
        paused = json.loads(self.run_cli("pause", "queued").stdout)
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["desired_state"], "paused")

        self.run_cli("resume", "queued")
        paused_now = json.loads(self.run_cli("pause", "queued", "--now").stdout)
        self.assertEqual(paused_now["status"], "paused")

    def test_agents_cli_swaps_main_and_secondary_independently(self):
        self.run_cli(
            "add", "--id", "t1", "--title", "T1", "--cwd", "/tmp",
            "--agent-main", "claude", "--agent-secondary", "codex", "--", "true",
        )
        after_main = json.loads(self.run_cli("agents", "t1", "--main", "hermes").stdout)
        self.assertEqual(after_main["agent_main"], "hermes")
        self.assertEqual(after_main["agent_secondary"], "codex")

        after_secondary = json.loads(
            self.run_cli("agents", "t1", "--secondary", "qwen3.8-27b").stdout
        )
        self.assertEqual(after_secondary["agent_main"], "hermes")
        self.assertEqual(after_secondary["agent_secondary"], "qwen3.8-27b")

        cleared = json.loads(self.run_cli("agents", "t1", "--secondary", "").stdout)
        self.assertEqual(cleared["agent_main"], "hermes")
        self.assertIsNone(cleared["agent_secondary"])

    def test_agents_cli_requires_at_least_one_flag(self):
        self.run_cli("add", "--id", "t1", "--title", "T1", "--cwd", "/tmp", "--", "true")
        result = self.run_cli("agents", "t1", check=False)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
