"""Tests for the improvements: stop_file, log retention, events pruning,
snapshot surfacing, sync sort optimization, and failure scan tightening."""

import os
import sys
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from research_loops.queue import QueueStore
from research_loops.runner import (
    _SCAN_TAIL_CHARS,
    FailureKind,
    LoopRunner,
    UsageLedger,
    classify_failure,
)


class StopFileTests(unittest.TestCase):
    """Fix 3: recurring item with stop_file transitions without a wasted cycle."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = QueueStore(self.root)
        self.ledger = UsageLedger(self.root / "state" / "events.jsonl")
        self.runner = LoopRunner(self.store, self.ledger, poll_seconds=0.05)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_recurring_done_stop_completes_instead_of_rescheduling(self):
        stop_file = self.root / "STOP"
        # Simulate: the loop runs successfully (exit 0) and writes DONE.
        command = (
            f"import pathlib; pathlib.Path({str(stop_file)!r}).write_text('DONE\\n')"
        )
        item = self.store.add(
            title="Recurring with stop",
            cwd=str(self.root),
            command=[sys.executable, "-c", command],
            repeat_seconds=900,
            stop_file="STOP",
        )
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(self.store.get(item["id"])["status"], "completed")

    def test_done_stop_fails_closed_when_completion_command_rejects_it(self):
        stop_file = self.root / "STOP"
        command = (
            f"import pathlib; pathlib.Path({str(stop_file)!r}).write_text('DONE\\n')"
        )
        item = self.store.add(
            title="Semantically incomplete",
            cwd=str(self.root),
            command=[sys.executable, "-c", command],
            repeat_seconds=900,
            stop_file="STOP",
            completion_command=[
                sys.executable,
                "-c",
                "import sys; print('open obligations remain'); sys.exit(1)",
            ],
        )

        result = self.runner.run_once()

        self.assertEqual(result["outcome"], "needs_attention")
        state = self.store.get(item["id"])
        self.assertEqual(state["status"], "needs_attention")
        self.assertEqual(state["last_error_kind"], "configuration")
        self.assertIn("open obligations remain", state["last_error"])

    def test_recurring_needs_operator_stop_goes_to_attention(self):
        stop_file = self.root / "STOP"
        command = (
            f"import pathlib; pathlib.Path({str(stop_file)!r}).write_text('NEEDS-OPERATOR: manual review')"
        )
        item = self.store.add(
            title="Recurring attention",
            cwd=str(self.root),
            command=[sys.executable, "-c", command],
            repeat_seconds=900,
            stop_file="STOP",
        )
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "needs_attention")
        state = self.store.get(item["id"])
        self.assertEqual(state["status"], "needs_attention")
        self.assertEqual(state["last_error_kind"], "configuration")

    def test_no_stop_file_still_reschedules(self):
        item = self.store.add(
            title="Normal recurring",
            cwd=str(self.root),
            command=[sys.executable, "-c", "pass"],
            repeat_seconds=60,
        )
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "scheduled")
        self.assertEqual(self.store.get(item["id"])["status"], "backoff")

    def test_missing_stop_file_falls_through(self):
        self.store.add(
            title="Stop file absent",
            cwd=str(self.root),
            command=[sys.executable, "-c", "pass"],
            repeat_seconds=60,
            stop_file="NONEXISTENT",
        )
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "scheduled")

    def test_bounded_item_done_stop_completes(self):
        stop_file = self.root / "STOP"
        command = (
            f"import pathlib; pathlib.Path({str(stop_file)!r}).write_text('DONE')"
        )
        item = self.store.add(
            title="Bounded with stop",
            cwd=str(self.root),
            command=[sys.executable, "-c", command],
            stop_file="STOP",
        )
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(self.store.get(item["id"])["status"], "completed")

    def test_stale_stop_file_from_earlier_attempt_is_ignored(self):
        # A STOP written before the run starts (leftover from a previous
        # attempt the operator forgot to clear) must NOT re-trigger a terminal
        # transition: only a file this run created/modified counts.
        stop_file = self.root / "STOP"
        stop_file.write_text("NEEDS-OPERATOR: old, operator resumed without deleting")
        item = self.store.add(
            title="Stale stop",
            cwd=str(self.root),
            command=[sys.executable, "-c", "pass"],  # run does NOT touch STOP
            repeat_seconds=60,
            stop_file="STOP",
        )
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "scheduled")
        self.assertEqual(self.store.get(item["id"])["status"], "backoff")

    def test_stop_file_modified_by_run_counts_even_if_preexisting(self):
        # The file existed before, but THIS run overwrote it with DONE.
        stop_file = self.root / "STOP"
        stop_file.write_text("NEEDS-OPERATOR: old state")
        command = (
            "import pathlib, time; time.sleep(0.01); "
            f"pathlib.Path({str(stop_file)!r}).write_text('DONE — all units covered')"
        )
        item = self.store.add(
            title="Overwritten stop",
            cwd=str(self.root),
            command=[sys.executable, "-c", command],
            repeat_seconds=60,
            stop_file="STOP",
        )
        result = self.runner.run_once()
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(self.store.get(item["id"])["status"], "completed")


class ScanTailCharsTests(unittest.TestCase):
    """Fix 4: pattern scan only looks at the last 2 KB, not 8 KB."""

    def test_scan_tail_is_2kb(self):
        self.assertEqual(_SCAN_TAIL_CHARS, 2000)

    def test_rate_limit_in_old_prose_not_matched(self):
        # Fill 3 KB of harmless prose, then put "429" early (outside the tail).
        prose = "The request was examined. " * 150  # ~3.6 KB
        output = "429 too many requests\n" + prose + "\nexit code 1"
        kind = classify_failure(1, output)
        # The "429" is outside the 2 KB tail, so this should be transient.
        self.assertEqual(kind, FailureKind.TRANSIENT)

    def test_rate_limit_in_tail_is_matched(self):
        output = "x" * 2000 + "\n429 too many requests\nexit 1"
        kind = classify_failure(1, output)
        self.assertEqual(kind, FailureKind.RATE_LIMIT)


class LogRetentionTests(unittest.TestCase):
    """Fix 5: logs older than 90 days are swept."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = QueueStore(self.root)
        self.ledger = UsageLedger(self.root / "state" / "events.jsonl")
        self.runner = LoopRunner(self.store, self.ledger, poll_seconds=0.05)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_old_logs_deleted(self):
        old_log = self.runner.log_dir / "old-attempt-1-20260101T000000Z.log"
        old_log.write_text("old log")
        old_time = time.time() - 91 * 86400
        os.utime(old_log, (old_time, old_time))

        recent_log = self.runner.log_dir / "recent-attempt-1-20260825T000000Z.log"
        recent_log.write_text("recent log")

        removed = self.runner._sweep_old_logs()
        self.assertEqual(removed, 1)
        self.assertFalse(old_log.exists())
        self.assertTrue(recent_log.exists())

    def test_non_log_files_not_touched(self):
        other = self.runner.log_dir / "notes.txt"
        other.write_text("keep me")
        old_time = time.time() - 91 * 86400
        os.utime(other, (old_time, old_time))

        removed = self.runner._sweep_old_logs()
        self.assertEqual(removed, 0)
        self.assertTrue(other.exists())


class EventsPruningTests(unittest.TestCase):
    """Fix 7: events.jsonl pruned to 90 days, and --since filter works."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "events.jsonl"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_old_events_pruned(self):
        ledger = UsageLedger(self.path)
        old_ts = (datetime.now(UTC) - timedelta(days=91)).isoformat().replace(
            "+00:00", "Z"
        )
        new_ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        ledger.append({"type": "process_finished", "ts": old_ts, "item_id": "old"})
        ledger.append({"type": "process_finished", "ts": new_ts, "item_id": "new"})

        removed = ledger.sweep_old_events()
        self.assertEqual(removed, 1)
        events = ledger.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["item_id"], "new")

    def test_since_filter(self):
        ledger = UsageLedger(self.path)
        old_ts = (datetime.now(UTC) - timedelta(days=30)).isoformat().replace(
            "+00:00", "Z"
        )
        new_ts = (datetime.now(UTC) - timedelta(days=1)).isoformat().replace(
            "+00:00", "Z"
        )
        ledger.append({"type": "test", "ts": old_ts, "item_id": "old"})
        ledger.append({"type": "test", "ts": new_ts, "item_id": "new"})

        cutoff = datetime.now(UTC) - timedelta(days=7)
        filtered = ledger.events(since=cutoff)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["item_id"], "new")

    def test_events_without_ts_are_kept(self):
        ledger = UsageLedger(self.path)
        ledger.append({"type": "no_ts_event"})
        removed = ledger.sweep_old_events()
        self.assertEqual(removed, 0)
        self.assertEqual(len(ledger.events()), 1)

    def test_corrupt_line_is_skipped_by_events_and_kept_by_sweep(self):
        ledger = UsageLedger(self.path)
        ledger.append({"type": "good", "item_id": "ok"})
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write('{"torn": "wri\n')
        # events() must not raise and must skip the corrupt line.
        events = ledger.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["item_id"], "ok")
        # sweep must not raise and must keep the corrupt line verbatim.
        removed = ledger.sweep_old_events()
        self.assertEqual(removed, 0)
        raw = self.path.read_text(encoding="utf-8")
        self.assertIn('{"torn": "wri', raw)


class SnapshotsTests(unittest.TestCase):
    """Fix 6: subscription-window snapshots are surfaced."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "events.jsonl"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_snapshots_returned(self):
        ledger = UsageLedger(self.path)
        ledger.append(
            {
                "type": "process_finished",
                "item_id": "router",
                "provider": "codex",
                "attempt": 1,
                "quota_snapshot_before": {"remaining": 100},
                "quota_snapshot_after": {"remaining": 80},
            }
        )
        ledger.append(
            {
                "type": "process_finished",
                "item_id": "other",
                "provider": "anthropic",
                "attempt": 1,
            }
        )
        snaps = ledger.snapshots()
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]["item_id"], "router")
        self.assertEqual(snaps[0]["quota_snapshot_before"], {"remaining": 100})

    def test_snapshots_with_since(self):
        ledger = UsageLedger(self.path)
        old_ts = (datetime.now(UTC) - timedelta(days=30)).isoformat().replace(
            "+00:00", "Z"
        )
        new_ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        ledger.append(
            {
                "type": "process_finished",
                "item_id": "old",
                "ts": old_ts,
                "quota_snapshot_before": {"r": 1},
            }
        )
        ledger.append(
            {
                "type": "process_finished",
                "item_id": "new",
                "ts": new_ts,
                "quota_snapshot_before": {"r": 2},
            }
        )
        cutoff = datetime.now(UTC) - timedelta(days=7)
        snaps = ledger.snapshots(since=cutoff)
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]["item_id"], "new")


class SyncSortTests(unittest.TestCase):
    """Fix 10: sync sort uses dict lookup, not list.index()."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = QueueStore(self.root)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_sync_preserves_relative_order_of_non_manifest_items(self):
        # Add items not in the manifest.
        self.store.add(
            title="Extra A", cwd="/tmp", command=["true"], item_id="extra-a"
        )
        self.store.add(
            title="Extra B", cwd="/tmp", command=["true"], item_id="extra-b"
        )
        # Sync a manifest with two items.
        self.store.sync(
            [
                {"id": "m1", "title": "M1", "cwd": "/tmp", "command": ["true"]},
                {"id": "m2", "title": "M2", "cwd": "/tmp", "command": ["true"]},
            ]
        )
        order = [i["id"] for i in self.store.snapshot()["items"]]
        # Manifest items come first, then non-manifest items in their original order.
        self.assertEqual(order, ["m1", "m2", "extra-a", "extra-b"])

    def test_sync_reorders_to_manifest_order(self):
        self.store.add(
            title="A", cwd="/tmp", command=["true"], item_id="a"
        )
        self.store.add(
            title="B", cwd="/tmp", command=["true"], item_id="b"
        )
        self.store.sync(
            [
                {"id": "b", "title": "B", "cwd": "/tmp", "command": ["true"]},
                {"id": "a", "title": "A", "cwd": "/tmp", "command": ["true"]},
            ]
        )
        order = [i["id"] for i in self.store.snapshot()["items"]]
        self.assertEqual(order, ["b", "a"])


class StopFileDefinitionFieldTests(unittest.TestCase):
    """Fix 3: stop_file is a definition field preserved by sync."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.store = QueueStore(self.root)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_sync_updates_stop_file(self):
        self.store.add(
            title="Test",
            cwd="/tmp",
            command=["true"],
            item_id="t1",
            stop_file="STOP",
        )
        self.store.sync(
            [
                {
                    "id": "t1",
                    "title": "Test",
                    "cwd": "/tmp",
                    "command": ["true"],
                    "stop_file": "DONE_FILE",
                }
            ]
        )
        item = self.store.get("t1")
        self.assertEqual(item["stop_file"], "DONE_FILE")

    def test_add_with_stop_file(self):
        item = self.store.add(
            title="T",
            cwd="/tmp",
            command=["true"],
            item_id="t",
            stop_file="STOP",
        )
        self.assertEqual(item["stop_file"], "STOP")


class WatchdogNotifyTests(unittest.TestCase):
    """Fix 9: NOTIFY_SOCKET-based sd_notify, no-op outside systemd."""

    def test_notify_noop_without_notify_socket(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOTIFY_SOCKET", None)
            self.assertFalse(LoopRunner._notify("READY=1"))
            self.assertFalse(LoopRunner._notify_watchdog())

    def test_notify_sends_datagram_to_notify_socket(self):
        import socket as socket_mod

        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        sock_path = str(Path(tempdir.name) / "notify.sock")
        server = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_DGRAM)
        self.addCleanup(server.close)
        server.bind(sock_path)
        server.settimeout(2)
        with mock.patch.dict(os.environ, {"NOTIFY_SOCKET": sock_path}):
            self.assertTrue(LoopRunner._notify("READY=1"))
        data, _ = server.recvfrom(64)
        self.assertEqual(data, b"READY=1")

    def test_notify_bad_socket_returns_false(self):
        with mock.patch.dict(
            os.environ, {"NOTIFY_SOCKET": "/nonexistent/notify.sock"}
        ):
            self.assertFalse(LoopRunner._notify("READY=1"))

    def test_watchdog_pinged_during_child_supervision(self):
        # run_once() blocks for the whole child runtime; the watchdog must be
        # fed inside that supervision loop, not just between runs, or systemd
        # would kill the worker WatchdogSec into every long iteration.
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        root = Path(tempdir.name)
        store = QueueStore(root)
        ledger = UsageLedger(root / "state" / "events.jsonl")
        runner = LoopRunner(store, ledger, poll_seconds=0.05)
        store.add(
            title="Slow child",
            cwd=str(root),
            command=[sys.executable, "-c", "import time; time.sleep(0.5)"],
        )
        with mock.patch.object(LoopRunner, "_notify_watchdog") as ping:
            runner.run_once()
        # ~0.5s of supervision at 0.05s poll => several pings.
        self.assertGreaterEqual(ping.call_count, 2)


if __name__ == "__main__":
    unittest.main()