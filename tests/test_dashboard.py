import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from research_loops.dashboard import render_dashboard, write_dashboard
from research_loops.queue import QueueError
from research_loops.runner import UsageLedger


ROOT = Path(__file__).resolve().parents[1]


class DashboardRenderingTests(unittest.TestCase):
    def test_renders_active_queue_and_completed_metrics_with_coverage(self):
        state = {
            "revision": 7,
            "paused": False,
            "pause_reason": None,
            "worker_policies": {"worker-3": {"claim_limit": 5, "claims_used": 2}},
            "items": [
                {
                    "id": "active",
                    "title": "Active topic",
                    "status": "running",
                    "desired_state": "running",
                    "claimed_by": "worker-3",
                    "attempts": 4,
                    "command": ["run-topic", "/topic", "research3"],
                    "next_eligible_at": "2026-08-28T11:59:00Z",
                },
                {
                    "id": "queued",
                    "title": "Queued topic",
                    "status": "queued",
                    "desired_state": "running",
                    "claimed_by": None,
                    "attempts": 0,
                    "accepted_by_workers": [],
                    "command": ["run-topic", "/topic", "research1"],
                },
                {
                    "id": "complete",
                    "title": "Completed topic",
                    "status": "completed",
                    "desired_state": "paused",
                    "claimed_by": None,
                    "attempts": 3,
                    "finished_at": "2026-08-28T12:00:00Z",
                    "command": ["run-topic", "/topic", "research1"],
                },
            ],
        }
        events = [
            {
                "type": "process_finished",
                "item_id": "complete",
                "attempt": 1,
                "ts": "2026-08-28T10:00:00Z",
                "duration_seconds": 60,
                "usage": {"api_calls": 4, "total_tokens": 1000, "model": "model-a"},
            },
            {
                "type": "process_finished",
                "item_id": "complete",
                "attempt": 2,
                "ts": "2026-08-28T11:00:00Z",
                "duration_seconds": 120,
                "usage": {"api_calls": 6, "total_tokens": 3000, "model": "model-a"},
            },
            {
                "type": "process_finished",
                "item_id": "complete",
                "attempt": 3,
                "ts": "2026-08-28T12:00:00Z",
                "duration_seconds": 180,
                "usage": None,
            },
        ]

        result = render_dashboard(
            state,
            events,
            generated_at=datetime(2026, 8, 28, 12, 1, tzinfo=UTC),
        )

        self.assertIn("# Research Loops Status", result)
        self.assertIn("Queue revision: **7**", result)
        self.assertIn("Active topic", result)
        self.assertIn("current 4", result)
        # State / Next eligible dropped from the Active table (operator, 2026-09-05)
        self.assertNotIn("running now", result)
        self.assertNotIn("| Topic | Worker | State |", result)
        self.assertIn("Queued topic", result)
        self.assertIn("Completed topic", result)
        self.assertIn("10 reported \\(coverage 2/3\\)", result)
        self.assertIn("2m 0s \\(coverage 3/3\\)", result)
        self.assertIn("2,000 reported \\(coverage 2/3\\)", result)
        self.assertIn("retained event ledger", result)
        self.assertIn("eventually consistent", result)

    def test_categories_are_exhaustive_and_global_pause_is_prominent(self):
        state = {
            "revision": 8,
            "paused": True,
            "pause_reason": "operator maintenance",
            "worker_policies": {},
            "items": [
                {"id": "running", "title": "Running", "status": "running", "desired_state": "running", "claimed_by": "worker-1", "attempts": 2},
                {"id": "cadence", "title": "Cadence", "status": "backoff", "desired_state": "running", "claimed_by": "worker-2", "attempts": 3},
                {"id": "queued-backoff", "title": "Queued backoff", "status": "backoff", "desired_state": "running", "claimed_by": None, "attempts": 1},
                {"id": "paused-owned", "title": "Paused owned", "status": "paused", "desired_state": "paused", "claimed_by": "worker-9", "attempts": 4},
                {"id": "attention", "title": "Attention", "status": "needs_attention", "desired_state": "paused", "claimed_by": "stale", "attempts": 5},
                {"id": "unknown", "title": "Unknown", "status": "mystery", "desired_state": "running", "claimed_by": None, "attempts": 0},
                "not-an-object",
            ],
        }

        result = render_dashboard(state, [], generated_at=datetime(2026, 8, 28, tzinfo=UTC))

        self.assertIn("Queue globally paused: **yes**", result)
        self.assertIn("operator maintenance", result)
        self.assertIn("last 3; next 4", result)
        self.assertIn("Queued backoff", result)
        self.assertIn("Paused owned", result)
        self.assertIn("Attention", result)
        self.assertIn("Unknown", result)
        self.assertIn("malformed item", result)
        self.assertIn("| Active | 2 |", result)
        self.assertIn("| Queued | 1 |", result)
        self.assertIn("| Needs Attention | 1 |", result)
        self.assertIn("| Paused | 1 |", result)
        self.assertIn("| Unclassified | 2 |", result)

    def test_invalid_metrics_are_unavailable_not_zero(self):
        state = {
            "revision": 1,
            "paused": False,
            "worker_policies": {},
            "items": [{"id": "done", "title": "Done", "status": "completed", "desired_state": "paused", "attempts": 99}],
        }
        invalid = [True, -1, float("nan"), float("inf"), "12"]
        events = [
            {"type": "process_finished", "item_id": "done", "attempt": index, "duration_seconds": value, "usage": {"api_calls": value, "total_tokens": value}}
            for index, value in enumerate(invalid, start=1)
        ]

        result = render_dashboard(state, events, generated_at=datetime(2026, 8, 28, tzinfo=UTC))

        # Completed rows carry identity only (operator ruling 2026-09-04:
        # metric detail moves to STATS.md), so the coverage-disclosing cells
        # now all come from the economics section.
        self.assertGreaterEqual(result.count("unavailable \\(coverage 0/5\\)"), 4)
        self.assertIn("| Done | 99 | 5 | unavailable |", result)

    def test_duplicate_attempts_id_reuse_and_removed_ids_are_disclosed(self):
        state = {
            "revision": 2,
            "paused": False,
            "worker_policies": {},
            "items": [{"id": "reused", "title": "Reused", "status": "completed", "desired_state": "paused", "attempts": 1}],
        }
        events = [
            {"type": "process_finished", "item_id": "reused", "attempt": 1, "duration_seconds": 1, "usage": {"api_calls": 1, "total_tokens": 10}},
            {"type": "process_finished", "item_id": "reused", "attempt": 1, "duration_seconds": 2, "usage": {"api_calls": 2, "total_tokens": 20}},
            {"type": "process_finished", "item_id": "removed", "attempt": 9, "duration_seconds": 3, "usage": {"api_calls": 3, "total_tokens": 30}},
        ]

        result = render_dashboard(state, events, generated_at=datetime(2026, 8, 28, tzinfo=UTC))

        self.assertIn("| Reused | 1 | 2 |", result)
        self.assertIn("Events for IDs absent from current queue | 1", result)
        self.assertIn("IDs and attempt numbers are not immutable", result)

    def test_untrusted_markdown_and_html_are_neutralized(self):
        payload = "bad|\\line\r\n`code` [link](https://x) ![img](x) <script>*x*</script> # head"
        state = {
            "revision": 3,
            "paused": False,
            "worker_policies": {},
            "items": [{"id": "bad", "title": payload, "status": "queued", "desired_state": "running", "claimed_by": None, "attempts": 0}],
        }

        result = render_dashboard(state, [], generated_at=datetime(2026, 8, 28, tzinfo=UTC))

        self.assertNotIn("<script>", result)
        self.assertNotIn("![img](x)", result)
        self.assertNotIn("[link](https://x)", result)
        self.assertNotIn("bad|\\line", result)
        self.assertIn("&lt;script&gt;", result)
        self.assertIn("bad\\|\\\\line", result)

    def test_empty_and_cross_source_skew_render_deterministically(self):
        generated = datetime(2026, 8, 28, tzinfo=UTC)
        empty = {"revision": 0, "paused": False, "worker_policies": {}, "items": []}
        first = render_dashboard(empty, [], generated_at=generated)
        self.assertEqual(first, render_dashboard(empty, [], generated_at=generated))
        self.assertIn("unavailable \\(coverage 0/0\\)", first)

        terminal_without_event = {
            "revision": 4,
            "paused": False,
            "worker_policies": {},
            "items": [{"id": "terminal", "title": "Terminal", "status": "completed", "desired_state": "paused", "attempts": 1}],
        }
        older_events = render_dashboard(terminal_without_event, [], generated_at=generated)
        self.assertIn("| Terminal | 1 | 0 | unavailable |", older_events)

        newer_events = render_dashboard(
            empty,
            [{"type": "process_finished", "item_id": "not-in-snapshot", "attempt": 1, "duration_seconds": 1, "usage": None}],
            generated_at=generated,
        )
        self.assertIn("Events for IDs absent from current queue | 1", newer_events)

    def test_usage_ledger_skips_malformed_lines_before_rendering(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "events.jsonl"
            path.write_text(
                "not json\n"
                '{"type":"process_finished","item_id":"gone","duration_seconds":1}\n',
                encoding="utf-8",
            )
            events = UsageLedger(path).events()
            result = render_dashboard(
                {"revision": 1, "paused": False, "worker_policies": {}, "items": []},
                events,
                generated_at=datetime(2026, 8, 28, tzinfo=UTC),
            )
            self.assertIn("Retained process\\_finished records | 1", result)

    def test_atomic_write_replaces_content_with_mode_0600(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "STATUS.md"
            output.write_text("old", encoding="utf-8")
            os.chmod(output, 0o644)

            write_dashboard(output, "new\n")

            self.assertEqual(output.read_text(encoding="utf-8"), "new\n")
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_rejects_symlink_directory_and_missing_parent_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            original = root / "original"
            original.write_text("preserve", encoding="utf-8")
            symlink = root / "STATUS.md"
            symlink.symlink_to(original)
            with self.assertRaisesRegex(QueueError, "symlink"):
                write_dashboard(symlink, "replace")
            self.assertEqual(original.read_text(encoding="utf-8"), "preserve")

            with self.assertRaisesRegex(QueueError, "regular file"):
                write_dashboard(root, "replace")
            with self.assertRaisesRegex(QueueError, "parent"):
                write_dashboard(root / "missing" / "STATUS.md", "replace")

    def test_replace_failure_preserves_previous_output(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "STATUS.md"
            output.write_text("old", encoding="utf-8")
            with mock.patch("research_loops.dashboard.os.replace", side_effect=OSError("blocked")):
                with self.assertRaisesRegex(QueueError, "blocked"):
                    write_dashboard(output, "new")
            self.assertEqual(output.read_text(encoding="utf-8"), "old")
            self.assertEqual(list(Path(tempdir).glob(".STATUS.md.*.tmp")), [])


class DashboardServiceTemplateTests(unittest.TestCase):
    def test_only_repository_root_dashboard_is_ignored(self):
        root_ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/STATUS.md", root_ignore)
        self.assertNotIn("STATUS.md", root_ignore)

    def test_dashboard_timer_and_service_reference_each_other(self):
        service = (ROOT / "deploy" / "systemd" / "research-loops-dashboard.service").read_text(encoding="utf-8")
        timer = (ROOT / "deploy" / "systemd" / "research-loops-dashboard.timer").read_text(encoding="utf-8")
        self.assertIn("Type=oneshot", service)
        self.assertIn("dashboard --output", service)
        self.assertIn("Unit=research-loops-dashboard.service", timer)
        self.assertIn("WantedBy=timers.target", timer)


if __name__ == "__main__":
    unittest.main()


class DashboardIntakeLaneTests(unittest.TestCase):
    """Intake items (discovery passes) never sit in the research tables."""

    def _render(self, status, desired="paused", claimed=None):
        state = {
            "revision": 1,
            "paused": False,
            "items": [
                {
                    "id": "discovery.some-topic",
                    "title": "Discovery: some",
                    "status": status,
                    "desired_state": desired,
                    "claimed_by": claimed,
                    "attempts": 1,
                    "lane": "intake",
                    "finished_at": "2026-09-03T00:00:00Z",
                },
            ],
        }
        return render_dashboard(state, [], generated_at=datetime(2026, 9, 3, tzinfo=UTC))

    def _section(self, output, heading):
        body = output.split(f"## {heading}\n")[1]
        return body.split("\n## ")[0]

    def test_completed_resolved_discovery_moves_to_completed_intakes(self):
        # No DRAFT-TOPIC.md at cwd -> the pass is resolved history, shown at
        # the end of the doc, never in the awaiting table or research tables.
        output = self._render("completed")
        self.assertIn("Discovery: some", self._section(output, "Completed intakes"))
        self.assertNotIn("Discovery: some", self._section(output, "Intake (awaiting the operator)"))
        self.assertNotIn("Discovery: some", self._section(output, "Completed topics"))

    def test_completed_discovery_with_open_draft_awaits_the_operator(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "DRAFT-TOPIC.md").write_text("draft")
            state = {
                "revision": 1, "paused": False,
                "items": [{
                    "id": "discovery.some-topic", "title": "Discovery: some-topic",
                    "status": "completed", "desired_state": "paused",
                    "claimed_by": None, "attempts": 1, "lane": "intake",
                    "cwd": tmp, "finished_at": "2026-09-03T00:00:00Z",
                }],
            }
            output = render_dashboard(state, [], generated_at=datetime(2026, 9, 3, tzinfo=UTC))
            self.assertIn("Discovery: some", self._section(output, "Intake (awaiting the operator)"))
            self.assertNotIn("Discovery: some", self._section(output, "Completed intakes"))

    def test_every_intake_state_stays_out_of_research_tables(self):
        for status, desired, claimed in (
            ("queued", "running", None),
            ("running", "running", "intake-1"),
            ("needs_attention", "running", None),
            ("paused", "paused", None),
        ):
            with self.subTest(status=status):
                output = self._render(status, desired, claimed)
                intake = self._section(output, "Intake (awaiting the operator)")
                self.assertIn("Discovery: some", intake)
                for heading in ("Active topics", "Queued topics", "Completed topics", "Needs attention", "Paused topics"):
                    self.assertNotIn("Discovery: some", self._section(output, heading))

    def test_overview_counts_only_awaiting_intake(self):
        output = self._render("completed")
        overview = self._section(output, "Overview")
        self.assertIn("| Intake | 0 |", overview.replace("  ", " "))
        running = self._render("running", "running", "intake-1")
        overview = self._section(running, "Overview")
        self.assertIn("| Intake | 1 |", overview.replace("  ", " "))


class NeedsAttentionFlagTests(unittest.TestCase):
    """The Needs attention table says WHERE to look, not just that something broke."""

    def _render(self, last_error):
        state = {
            "revision": 1,
            "paused": False,
            "items": [{
                "id": "t", "title": "Some topic", "status": "needs_attention",
                "desired_state": "running", "claimed_by": None, "attempts": 3,
                "last_error": last_error, "last_error_kind": "configuration",
            }],
        }
        return render_dashboard(state, [], generated_at=datetime(2026, 9, 3, tzinfo=UTC))

    def test_structured_flags_surface_in_their_own_column(self):
        output = self._render(
            "NEEDS-OPERATOR\nflag: deferred-obligation SCOPE-A3\n  depends on unshipped tooling\n"
        )
        section = output.split("## Needs attention\n")[1].split("\n## ")[0]
        self.assertIn("Flags", section)
        self.assertIn("deferred", section)
        self.assertIn("SCOPE", section)

    def test_unstructured_errors_fall_back_to_first_line(self):
        section = self._render("STOP present: NEEDS-OPERATOR\nmore detail").split(
            "## Needs attention\n")[1].split("\n## ")[0]
        self.assertIn("STOP present", section)


class UnclassifiedVisibilityTests(unittest.TestCase):
    def test_empty_unclassified_section_is_omitted(self):
        state = {"revision": 1, "paused": False, "items": []}
        output = render_dashboard(state, [], generated_at=datetime(2026, 9, 3, tzinfo=UTC))
        self.assertNotIn("## Unclassified items", output)

    def test_malformed_item_still_surfaces_the_section(self):
        state = {"revision": 1, "paused": False, "items": ["not-a-dict"]}
        output = render_dashboard(state, [], generated_at=datetime(2026, 9, 3, tzinfo=UTC))
        self.assertIn("## Unclassified items", output)
        self.assertIn("malformed item", output)


class IterationEconomicsTests(unittest.TestCase):
    """Saturation-era only: pre-epoch iterations and mixed-era topics never
    price into the planning numbers."""

    def _render(self, tmp):
        from research_loops.dashboard import SATURATION_EPOCH
        pre, post = "2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z"
        new_topic = Path(tmp) / "new-topic"
        new_topic.mkdir()
        (new_topic / "SEMANTIC-STATE.json").write_text(json.dumps({
            "obligations": [{"id": "A", "disposition": "supported"},
                            {"id": "B", "disposition": "supported"}],
        }))
        mixed = Path(tmp) / "mixed"
        mixed.mkdir()
        (mixed / "SEMANTIC-STATE.json").write_text(json.dumps({
            "obligations": [{"id": "M", "disposition": "supported"}],
        }))
        state = {"revision": 1, "paused": False, "items": [
            {"id": "t", "title": "T", "status": "running", "desired_state": "running",
             "claimed_by": "w", "attempts": 5, "cwd": str(new_topic)},
            {"id": "m", "title": "M", "status": "completed", "desired_state": "paused",
             "claimed_by": None, "attempts": 9, "cwd": str(mixed)},
        ]}
        events = [
            # fully post-epoch topic: two productive + one idle
            {"type": "process_finished", "item_id": "t", "ts": post, "duration_seconds": 60,
             "iteration_result": {"signature_changed": True}},
            {"type": "process_finished", "item_id": "t", "ts": post, "duration_seconds": 180,
             "iteration_result": {"signature_changed": True}},
            {"type": "process_finished", "item_id": "t", "ts": post, "duration_seconds": 5,
             "iteration_result": {"signature_changed": False}},
            # mixed-era topic: one pre-epoch productive (fully ignored for
            # durations), one post-epoch productive (counted for durations,
            # NOT for the ratio -- topic has pre-era history)
            {"type": "process_finished", "item_id": "m", "ts": pre, "duration_seconds": 999,
             "iteration_result": {"signature_changed": True}},
            {"type": "process_finished", "item_id": "m", "ts": post, "duration_seconds": 120,
             "iteration_result": {"signature_changed": True}},
        ]
        return render_dashboard(state, events, generated_at=datetime(2026, 9, 4, tzinfo=UTC))

    def test_epoch_scoping_and_ratio_strictness(self):
        import tempfile as _tf
        with _tf.TemporaryDirectory() as tmp:
            output = self._render(tmp)
            section = output.split("## Iteration economics")[1].split("\n## ")[0]
            # durations: 60/120/180 post-epoch productive; the 999s pre-epoch run absent
            self.assertIn("1m 0s min / 2m 0s median / 3m 0s max", section)
            self.assertNotIn("16m 39s", section)
            # ratio only over the fully-post-epoch topic: 2 productive / 2 resolved
            self.assertIn("over 1 fully", section)
            self.assertIn("1 topics with pre", section)

    def test_no_data_means_no_section(self):
        state = {"revision": 1, "paused": False, "items": []}
        output = render_dashboard(state, [], generated_at=datetime(2026, 9, 4, tzinfo=UTC))
        self.assertNotIn("## Iteration economics", output)
