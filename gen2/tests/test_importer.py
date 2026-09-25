"""The dry-run importer skeleton (task 0b): gen-1 JSON/JSONL state -> a
mapping report, reading only.

Trace: task 0b (read gen-1 read-only; no gen-2 store writes; surface every
record that does not map cleanly); INVARIANTS §12, RG-8, E-8, RG-U, C-13
(identity bounds apply to the importer's generated identities too), §11.9
(malformed lines are not dropped silently).

Oracle: a synthetic gen-1 root written here by hand in gen-1's on-disk
formats (queue.json items, AUTHORITY.md / QA-RECORD.md sections,
SEMANTIC-STATE.json obligations, SOURCE-LEDGER.md entries, JSONL logs), with
the expected status and issue codes of each record written out by hand; the
file tree's bytes and mtimes before and after; a tree made read-only for the
run (any write attempt would raise).

What these tests cannot show: that the formats match every live gen-1
deployment (the fixtures follow gen-1's writers, not live state, which this
task does not read), or anything about the managed store's contents.
"""
from __future__ import annotations

import contextlib
import io
import json
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from gen2.importer import dry_run

ROOT = Path(__file__).resolve().parents[2]
LOCK = "a" * 64


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def gen1_tree(root: Path) -> None:
    topic = root / "topics" / "latency"
    items = [
        {"id": "latency", "title": "Intake latency", "cwd": str(topic), "status": "queued", "completion_lock": LOCK, "iterations_completed": 3},
        {"id": "Mixed.Case", "cwd": str(root / "topics" / "Mixed.Case"), "status": "completed", "completion_lock": None},
        {"id": "running-one", "cwd": "/elsewhere/running-one", "status": "running"},
        {"id": "big", "cwd": str(root / "topics" / "big"), "status": "needs_attention", "iterations_completed": 2**53},
        {"id": "discovery.latency", "cwd": str(topic), "status": "queued", "lane": "intake", "managed_kind": "intake_discovery"},
    ]
    write(root / "state" / "queue.json", json.dumps({"version": 1, "revision": 7, "paused": False, "items": items}, indent=2, sort_keys=True))
    write(root / "state" / "stations.json", json.dumps({"revision": 1, "stations": {"station_1": {"interval_seconds": 60}}}))
    write(root / "state" / "events.jsonl", '{"ts": "2026-09-01T00:00:00Z", "type": "process_started"}\nnot json\n{"ts": "2026-09-01T00:01:00Z", "type": "process_finished"}\n')
    write(topic / "AUTHORITY.md", "# Intake latency\n\n## Operator brief (verbatim)\n\nWhy does intake take three days?\n\n"
                                  "## Assumptions\n\n- Three days is the median.\n- Logs are complete.\n\n## Evidence-quality vocabulary\n\n- **T1**: primary\n")
    write(topic / "QA-RECORD.md", "## Mode\n\nfocused\n\n## Operator confirmation\n\nConfirmed by the operator.\n")
    write(topic / "SEMANTIC-STATE.json", json.dumps({
        "schema_version": 2, "topic_id": "latency", "contract_sha256": "c" * 64, "authority_sha256": "d" * 64, "pending_evidence_refs": [],
        "contradictions": [{"id": "C-1", "status": "open", "resolution": None}], "deliverables": [],
        "obligations": [{"id": "SCOPE-01", "text": "Measure stage latency", "source_ref": "AUTHORITY.md", "disposition": "open"},
                        {"id": "9-bad", "text": "Supported claim", "source_ref": "AUTHORITY.md", "disposition": "supported"}]}))
    write(topic / "SOURCE-LEDGER.md", "# Sources\n\n## [SRC-001] external\n- url: https://doi.org/10.1000/xyz\n- title: A paper\n- retrieved: 2026-09-01\n\n"
                                      "## [SRC-002] local\n- path: notes.md\n")
    write(topic / "logs" / "research-activity-1.jsonl", '{"source": "crossref", "coverage": "searched_ok"}\n{broken\n{"source": "s2", "coverage": "exhausted"}\n')
    write(root / "topics" / "big" / "AUTHORITY.md", "## Operator brief (verbatim)\n\nBig topic.\n")


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*")) if p.is_file()}


def records_of(report: dict, gen1_id: str) -> list[dict]:
    return next(t["records"] for t in report["topics"] if t["gen1_id"] == gen1_id)


def find(records: list[dict], kind: str, ref_part: str = "") -> dict:
    matches = [r for r in records if r["gen1"] == kind and ref_part in r["ref"]]
    assert len(matches) == 1, (kind, ref_part, matches)
    return matches[0]


def codes(record: dict) -> set[str]:
    return {i["code"] for i in record["issues"]}


class ImporterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "gen1"
        gen1_tree(self.root)

    def tearDown(self) -> None:
        for path in [self.root, *self.root.rglob("*")]:
            if path.exists() and not path.is_symlink():
                path.chmod(stat.S_IRWXU)
        self._tmp.cleanup()


class DryRunMappingTest(ImporterTestCase):
    def test_every_record_is_classified_and_every_gap_is_surfaced(self) -> None:
        report = dry_run.dry_run(self.root, "fleet-a")
        records = [r for t in report["topics"] for r in t["records"]] + report["other"]
        self.assertTrue(records)
        for record in records:
            self.assertIn(record["status"], ("maps", "partial", "unmapped"))
            if record["status"] == "maps":
                self.assertEqual(record["issues"], [], record)  # "maps" means nothing is missing
            else:
                self.assertTrue(record["issues"], record)
            self.assertEqual(record["status"] == "unmapped", record["gen2_target"] is None or record["status"] == "unmapped")
        self.assertEqual(report["summary"]["records"], len(records))
        self.assertEqual(report["writes"], "none: dry run (no gen-2 store, no gen-1 file)")
        self.assertEqual(report["blocking"], [])

    def test_queue_items_map_with_the_authority_they_lack_named(self) -> None:
        report = dry_run.dry_run(self.root, "fleet-a")
        latency = records_of(report, "latency")
        item = find(latency, "queue item")
        self.assertEqual((item["status"], item["mapping"]), ("maps", {"topic_id": "fleet-a:latency", "priority": 1}))
        status = find(latency, "queue status")
        self.assertEqual((status["status"], status["mapping"]["status"], codes(status)), ("partial", "queued", {"contract-approval-unrecorded"}))
        self.assertEqual(codes(find(latency, "completion lock")), {"legacy-lock-is-not-a-gen2-hash"})
        self.assertEqual(find(latency, "completion lock")["status"], "unmapped")
        count = find(latency, "accepted iterations")
        self.assertEqual((count["status"], count["mapping"], codes(count)), ("partial", {"accepted_count": 3}, {"ordinals-without-history"}))
        mixed = records_of(report, "Mixed.Case")
        self.assertEqual((find(mixed, "queue item")["status"], codes(find(mixed, "queue item"))), ("unmapped", {"topic-id-not-a-gen2-slug"}))
        self.assertEqual(find(mixed, "queue item")["mapping"]["topic_id"], None)  # never lower-cased silently
        self.assertEqual((find(mixed, "queue status")["status"], codes(find(mixed, "queue status"))), ("unmapped", {"completion-unapproved"}))
        self.assertEqual(codes(find(mixed, "completion lock")), {"no-lock"})
        self.assertEqual(codes(find(mixed, "accepted iterations")), {"count-unknown"})
        self.assertEqual(find(mixed, "accepted iterations")["mapping"], {"accepted_count": None})  # unknown, not zero
        running = records_of(report, "running-one")
        self.assertEqual((find(running, "queue status")["status"], codes(find(running, "queue status"))), ("unmapped", {"live-execution"}))
        self.assertEqual(codes(find(running, "topic directory")), {"topic-dir-not-found"})
        big = records_of(report, "big")
        self.assertEqual(codes(find(big, "queue status")), {"untyped-hold"})
        self.assertEqual(find(big, "accepted iterations")["mapping"], {"accepted_count": None})
        self.assertIn("identity-out-of-range", codes(find(big, "accepted iterations")))
        discovery = records_of(report, "discovery.latency")
        self.assertEqual(codes(find(discovery, "queue status")), {"intake-discovery-item"})
        self.assertEqual([t["records"][0]["mapping"]["priority"] for t in report["topics"]], [1, 2, 3, 4, 5])  # queue order is the priority

    def test_without_a_fleet_no_topic_id_is_invented(self) -> None:
        report = dry_run.dry_run(self.root)
        for topic in report["topics"]:
            self.assertIsNone(topic["gen2_topic_id"])
            self.assertIn("fleet-unassigned", codes(topic["records"][0]))
            self.assertEqual(topic["records"][0]["status"], "unmapped")

    def test_the_brief_imports_awaiting_confirmation_with_its_gaps_named(self) -> None:
        brief = find(records_of(dry_run.dry_run(self.root, "fleet-a"), "latency"), "intake brief")
        self.assertEqual((brief["status"], brief["gen2_target"]), ("partial", "intake_briefs"))
        self.assertEqual({k: brief["mapping"][k] for k in ("status", "objective_in_operator_words", "surfaced_assumptions", "legacy_confirmation_evidence")},
                         {"status": "awaiting_confirmation", "objective_in_operator_words": "Why does intake take three days?",
                          "surfaced_assumptions": ["Three days is the median.", "Logs are complete."], "legacy_confirmation_evidence": True})
        self.assertEqual(codes(brief), {"brief-slot-missing", "owner-unknown", "deadline-unknown", "confirmation-unrecorded"})
        self.assertEqual(sorted(i["detail"] for i in brief["issues"] if i["code"] == "brief-slot-missing"),
                         ["gen-1 has no 'constraints' slot", "gen-1 has no 'evidence_that_would_change_it' slot", "gen-1 has no 'feeds' slot", "gen-1 has no 'operator_hypotheses' slot"])
        big = find(records_of(dry_run.dry_run(self.root, "fleet-a"), "big"), "intake brief")
        self.assertFalse(big["mapping"]["legacy_confirmation_evidence"])

    def test_obligations_sources_and_logs(self) -> None:
        latency = records_of(dry_run.dry_run(self.root, "fleet-a"), "latency")
        self.assertEqual(codes(find(latency, "obligation", "SCOPE-01")), {"obligation-contract-fields-missing"})
        self.assertEqual(codes(find(latency, "obligation", "9-bad")),
                         {"obligation-contract-fields-missing", "obligation-id-not-a-local-id", "disposition-is-not-verification"})
        self.assertEqual(codes(find(latency, "contradictions")), {"no-gen2-target"})
        doi = find(latency, "source", "SRC-001")
        self.assertEqual((doi["status"], doi["mapping"]), ("partial", {"identity_scheme": "doi", "identity_value": "10.1000/xyz"}))
        self.assertEqual((find(latency, "source", "SRC-002")["status"], codes(find(latency, "source", "SRC-002"))), ("unmapped", {"no-work-identity"}))
        log = find(latency, "history", "research-activity-1.jsonl")
        self.assertEqual((log["mapping"], codes(log)), ({"lines": 2, "malformed_lines": 1}, {"no-gen2-target", "malformed-lines"}))
        events = find(dry_run.dry_run(self.root, "fleet-a")["other"], "history", "events.jsonl")
        self.assertEqual(events["mapping"], {"lines": 2, "malformed_lines": 1})


class ReadOnlyTest(ImporterTestCase):
    def test_nothing_in_the_gen1_tree_changes_even_when_it_is_read_only(self) -> None:
        before = snapshot(self.root)
        for path in [*self.root.rglob("*"), self.root]:
            path.chmod(0o555 if path.is_dir() else 0o444)
        report = dry_run.dry_run(self.root, "fleet-a")
        self.assertGreater(report["summary"]["records"], 10)
        self.assertEqual(snapshot(self.root), before)

    def test_managed_store_blocks_and_the_json_queue_is_marked_stale(self) -> None:
        write(self.root / "state" / "control.sqlite3", "")
        report = dry_run.dry_run(self.root, "fleet-a")
        self.assertEqual([i["code"] for i in report["blocking"]], ["managed-store-not-read"])
        self.assertEqual(report["sources"]["state/control.sqlite3"], "present, not read")
        queue_records = [r for t in report["topics"] for r in t["records"] if r["gen1"] in ("queue item", "queue status", "completion lock", "accepted iterations")]
        self.assertTrue(queue_records)
        for record in queue_records:
            self.assertIn("stale-snapshot", codes(record))
            self.assertNotEqual(record["status"], "maps")

    def test_paths_outside_the_root_are_not_read(self) -> None:
        outside = Path(self._tmp.name) / "outside-ledger.md"
        write(outside, "## [SRC-009] external\n- url: https://example.org/secret\n")
        ledger = self.root / "topics" / "latency" / "SOURCE-LEDGER.md"
        ledger.unlink()
        ledger.symlink_to(outside)
        report = dry_run.dry_run(self.root, "fleet-a")
        self.assertEqual(report["sources"][str(ledger)], "refused: resolves outside the gen-1 root")
        self.assertEqual([r for r in records_of(report, "latency") if r["gen1"] == "source"], [])

    def test_absent_queue_is_blocking(self) -> None:
        (self.root / "state" / "queue.json").unlink()
        self.assertEqual([i["code"] for i in dry_run.dry_run(self.root, "fleet-a")["blocking"]], ["queue-absent"])

    def test_the_importer_cannot_reach_a_store(self) -> None:
        """Structural: the boundary graph lets it import core only, with no
        restricted stdlib capability (no sqlite3), so it cannot write a gen-2
        store or open gen-1's SQLite (make gen2-boundaries enforces it)."""
        graph = tomllib.loads((ROOT / "gen2" / "boundaries.toml").read_text(encoding="utf-8"))["modules"]["importer"]
        self.assertEqual((graph["may_import"], graph["stdlib_capabilities"], graph["third_party"]), (["core"], [], []))


class CommandTest(ImporterTestCase):
    def run_cli(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = dry_run.main(["--gen1-root", str(self.root), *args])
        return status, out.getvalue(), err.getvalue()

    def test_report_is_refused_inside_the_gen1_root_or_over_a_file(self) -> None:
        before = snapshot(self.root)
        for target in (self.root / "report.json", self.root / "topics" / "latency" / "report.json", self.root / "state" / "queue.json"):
            with self.subTest(target=str(target)):
                status, _, err = self.run_cli("--fleet", "fleet-a", "--report", str(target))
                self.assertEqual(status, 2, err)
                self.assertIn("refused", err)
        self.assertEqual(snapshot(self.root), before)
        existing = Path(self._tmp.name) / "existing.json"
        existing.write_text("keep", encoding="utf-8")
        self.assertEqual(self.run_cli("--report", str(existing))[0], 2)
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep")

    def test_report_written_outside_and_exit_status_reflects_blocking(self) -> None:
        target = Path(self._tmp.name) / "report.json"
        status, _, err = self.run_cli("--fleet", "fleet-a", "--report", str(target))
        self.assertEqual(status, 0, err)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["report_version"], "gen1-import-dry-run/1")
        self.assertIn("nothing written to gen-1 or a gen-2 store", err)
        write(self.root / "state" / "control.sqlite3", "")
        status, out, _ = self.run_cli("--fleet", "fleet-a")
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(out)["blocking"][0]["code"], "managed-store-not-read")

    def test_python_dash_m_runs_the_importer(self) -> None:
        result = subprocess.run([sys.executable, "-m", "gen2.importer", "--gen1-root", str(self.root), "--fleet", "fleet-a"],
                                cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["fleet_id"], "fleet-a")

    def test_an_unrepresentable_gen1_value_is_surfaced_not_fatal(self) -> None:
        queue = json.loads((self.root / "state" / "queue.json").read_text(encoding="utf-8"))
        queue["items"][0]["completion_lock"] = 2**60
        (self.root / "state" / "queue.json").write_text(json.dumps(queue), encoding="utf-8")
        report = dry_run.dry_run(self.root, "fleet-a")
        lock = find(records_of(report, "latency"), "completion lock")
        self.assertEqual(lock["mapping"], {"legacy_lock": None})
        self.assertIn("value-unrepresentable", codes(lock))
        self.assertIn('"report_version": "gen1-import-dry-run/1"', dry_run.render(report))

if __name__ == "__main__":
    unittest.main()
