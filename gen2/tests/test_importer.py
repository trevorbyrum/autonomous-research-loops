"""The dry-run importer skeleton (task 0b): gen-1 JSON/JSONL state -> a
mapping report, reading only.

Trace: task 0b (read gen-1 read-only; no gen-2 store writes; surface every
record that does not map cleanly); INVARIANTS §12, RG-8, E-8, RG-U, C-13
(identity bounds apply to the importer's generated identities too), §11.9
(malformed lines are not dropped silently).

Oracle: a synthetic gen-1 root written here by hand in gen-1's on-disk
formats (queue.json items, AUTHORITY.md / QA-RECORD.md sections,
SEMANTIC-STATE.json obligations, SOURCE-LEDGER.md entries, JSONL logs), with
the expected status and issue codes of each record written out by hand; an
input inventory enumerated by hand (every record the input holds, and every
input file with its size) that the report is reconciled against; the file
tree's bytes and mtimes before and after; a tree made read-only for the run
(any write attempt would raise). The race tests (Astra 0b review A2) replace
a path at the moment the importer opens it or just after it checked it, as
the review's own probes did: real renames and symlinks in a temporary tree,
scheduled by wrapping os.open or the importer's own check, never by changing
what the check decides. All inputs are synthetic; no gen-1 state is read.
The A5-R1/A5-R2 tests (Astra 0b-repair re-review) run the CLI end to end,
on the review's own probes and on the same defects beside valid records,
and parse what it printed. Their oracle is a printed report that names the
defect, with the expected records and escaped text written out by hand, not
merely the absence of an exception.

What these tests cannot show: that the formats match every live gen-1
deployment (the fixtures follow gen-1's writers, not live state, which this
task does not read), or anything about the managed store's contents; nor
races other than the ones scheduled here (a file's bytes changing during a
read, or the report directory moved between the last check and the write,
which the module docstring states it does not cover).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

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


def queue_text(root: Path, edit=None, tokens: dict[str, str] | None = None) -> str:
    """queue.json after `edit(queue)`; each tokens key (a string value in the
    edited queue) is replaced by the raw numeral text it names."""
    queue = json.loads((root / "state" / "queue.json").read_text(encoding="utf-8"))
    if edit is not None:
        edit(queue)
    text = json.dumps(queue)
    for placeholder, raw in (tokens or {}).items():
        assert text.count(json.dumps(placeholder)) == 1, placeholder
        text = text.replace(json.dumps(placeholder), raw)
    return text


class ImporterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "gen1"
        gen1_tree(self.root)

    def tearDown(self) -> None:
        for path in [self.root, *self.root.rglob("*")]:
            if path.exists() and not path.is_symlink():
                path.chmod(stat.S_IRWXU)
        self._tmp.cleanup()

    def dry(self, fleet: str | None = "fleet-a", root: Path | None = None) -> dict:
        """The report for the fixture (or `root`). A crash fails the test (A5:
        malformed input is reported, never fatal)."""
        try:
            return dry_run.dry_run(self.root if root is None else root, fleet)
        except Exception as exc:
            self.fail(f"the importer crashed instead of reporting: {exc!r}")

    def edit_queue(self, edit=None, tokens: dict[str, str] | None = None) -> None:
        (self.root / "state" / "queue.json").write_text(queue_text(self.root, edit, tokens), encoding="utf-8")


def inventory_tree(root: Path) -> None:
    """A gen-1 root whose every record is enumerated in INVENTORY below. It
    holds each input family the importer reads, input it cannot interpret
    (a malformed status, a non-object item, an item without an id, a
    non-object obligation), two items claiming one topic id, two
    obligations claiming one id, a precision-losing count, an unsupported
    semantic-state version, keys and fields with no mapping, and absent
    files."""
    alpha = root / "topics" / "alpha"
    items = [
        {"id": "alpha", "cwd": str(alpha), "status": "queued", "completion_lock": LOCK, "iterations_completed": 2, "title": "Alpha"},
        {"id": "delta", "status": "paused"},
        {"id": "delta", "status": "backoff"},
        {"id": "beta", "status": [], "iterations_completed": "@@COUNT@@"},
        {"id": "gamma", "status": "completed"},
        "not an object",
        {"status": "queued"},
    ]
    text = json.dumps({"version": 1, "revision": 3, "paused": False, "items": items}).replace('"@@COUNT@@"', "1.0000000000000001")
    write(root / "state" / "queue.json", text)
    write(root / "state" / "events.jsonl", '{"type": "a"}\n{"type": "b"}\n{not json\n')
    write(root / "state" / "stations.json", json.dumps({"revision": 1}))
    write(alpha / "AUTHORITY.md", "## Operator brief (verbatim)\n\nAlpha brief.\n\n## Assumptions\n\n- One.\n")
    write(alpha / "QA-RECORD.md", "## Mode\n\nfocused\n")
    write(alpha / "SEMANTIC-STATE.json", json.dumps({
        "schema_version": 2, "topic_id": "alpha", "evidence_graph": {"nodes": []}, "deliverables": [], "pending_evidence_refs": [],
        "contradictions": [{"id": "C-1"}],
        "obligations": [{"id": "OB-1", "text": "t", "disposition": "open"}, {"id": "OB-1", "text": "u", "disposition": "open"}, 7]}))
    write(alpha / "SOURCE-LEDGER.md", "## [SRC-001] external\n- url: https://doi.org/10.1/a\n\n## [SRC-002] internal\n- path: x\n")
    write(alpha / "logs" / "run.jsonl", '{"source": "crossref"}\n')
    write(root / "topics" / "gamma" / "SEMANTIC-STATE.json", json.dumps({"schema_version": 999, "evidence": [{"id": "E-1"}]}))


BRIEF_GAPS = ["brief-slot-missing"] * 4 + ["confirmation-unrecorded", "deadline-unknown", "owner-unknown"]
# (gen-1 item, [(kind, ref, status, issue codes)]) per queue item in order, then "other"; written by hand from the tree above.
INVENTORY = [
    ("alpha", [("queue item", "alpha", "maps", []), ("queue status", "alpha.status=queued", "partial", ["contract-approval-unrecorded"]),
               ("completion lock", "alpha.completion_lock", "unmapped", ["legacy-lock-is-not-a-gen2-hash"]),
               ("accepted iterations", "alpha.iterations_completed", "partial", ["ordinals-without-history"]),
               ("unmapped fields", "alpha.fields", "unmapped", ["no-gen2-target"]),
               ("intake brief", "alpha/AUTHORITY.md", "partial", BRIEF_GAPS),
               ("semantic state", "alpha/SEMANTIC-STATE.json", "unmapped", ["unrecognized-material"]),
               ("obligation", "alpha#OB-1", "partial", ["obligation-contract-fields-missing", "target-identity-collision"]),
               ("obligation", "alpha#OB-1", "partial", ["obligation-contract-fields-missing", "target-identity-collision"]),
               ("obligation", "alpha#obligations[2]", "unmapped", ["field-shape"]),
               ("contradictions", "alpha#contradictions", "unmapped", ["no-gen2-target"]),
               ("source", "alpha#SRC-001", "partial", ["work-identity-unverified"]),
               ("source", "alpha#SRC-002", "unmapped", ["no-work-identity"]),
               ("history", "alpha/logs/run.jsonl", "unmapped", ["no-gen2-target"])]),
    *(("delta", [("queue item", "delta", "partial", ["target-identity-collision"]), ("queue status", f"delta.status={status}", "partial", [code]),
                 ("completion lock", "delta.completion_lock", "unmapped", ["no-lock"]),
                 ("accepted iterations", "delta.iterations_completed", "unmapped", ["count-unknown"]), ("topic directory", "delta", "unmapped", ["topic-dir-not-found"])])
      for status, code in (("paused", "untyped-hold"), ("backoff", "backoff-is-two-states"))),
    ("beta", [("queue item", "beta", "maps", []), ("queue status", "beta.status=[]", "unmapped", ["field-shape"]),
              ("completion lock", "beta.completion_lock", "unmapped", ["no-lock"]),
              ("accepted iterations", "beta.iterations_completed", "partial", ["identity-not-an-integer", "ordinals-without-history"]),
              ("topic directory", "beta", "unmapped", ["topic-dir-not-found"])]),
    ("gamma", [("queue item", "gamma", "maps", []), ("queue status", "gamma.status=completed", "unmapped", ["completion-unapproved"]),
               ("completion lock", "gamma.completion_lock", "unmapped", ["no-lock"]),
               ("accepted iterations", "gamma.iterations_completed", "unmapped", ["count-unknown"]),
               ("intake brief", "gamma/AUTHORITY.md", "unmapped", ["no-brief"]),
               ("semantic state", "gamma/SEMANTIC-STATE.json", "unmapped", ["unsupported-schema-version"])]),
]
INVENTORY_OTHER = [("queue state", "state/queue.json", "unmapped", ["no-gen2-target"]),
                   ("queue item", "items[5]", "unmapped", ["queue-shape"]), ("queue item", "items[6]", "unmapped", ["queue-shape"]),
                   ("history", "state/events.jsonl", "unmapped", ["malformed-lines", "no-gen2-target"]),
                   ("station configuration", "state/stations.json", "unmapped", ["no-gen2-target"])]
INVENTORY_ABSENT = {"topics/gamma/AUTHORITY.md", "topics/gamma/SOURCE-LEDGER.md"}


def as_rows(records: list[dict]) -> list[tuple]:
    return sorted((r["gen1"], r["ref"], r["status"], sorted(i["code"] for i in r["issues"])) for r in records)


class DryRunMappingTest(ImporterTestCase):
    def test_every_record_is_classified_and_every_gap_is_surfaced(self) -> None:
        """Reconciled against the input, not against the importer's own
        output (Astra 0b review, Gate C REJECT of the earlier version): the
        report's records are exactly INVENTORY's, item by item, so a record
        omitted, added, or classified otherwise fails; every file of the tree
        is a source read at its own size, and the absent ones are named; the
        summary counts are INVENTORY's."""
        root = self.tmp / "inventory"
        inventory_tree(root)
        report = self.dry(root=root)
        self.assertEqual([t["gen1_id"] for t in report["topics"]], [gen1_id for gen1_id, _ in INVENTORY])
        for (gen1_id, expected), topic in zip(INVENTORY, report["topics"]):
            with self.subTest(topic=gen1_id):
                self.assertEqual(as_rows(topic["records"]), sorted((k, r, s, sorted(c)) for k, r, s, c in expected))
        self.assertEqual(as_rows(report["other"]), sorted((k, r, s, sorted(c)) for k, r, s, c in INVENTORY_OTHER))
        files = {str(p.relative_to(root)): p.stat().st_size for p in root.rglob("*") if p.is_file()}
        self.assertEqual(report["sources"], {**{name: f"read ({size} bytes)" for name, size in files.items()}, **{name: "absent" for name in INVENTORY_ABSENT}})
        self.assertEqual(report["blocking"], [])
        rows = [row for _, expected in INVENTORY for row in expected] + INVENTORY_OTHER
        self.assertEqual(report["summary"], {"records": len(rows), "maps": sum(r[2] == "maps" for r in rows), "partial": sum(r[2] == "partial" for r in rows),
                                             "unmapped": sum(r[2] == "unmapped" for r in rows), "issues": sum(len(r[3]) for r in rows), "blocking": 0})
        self.assertEqual((report["summary"]["records"], report["summary"]["maps"], report["summary"]["partial"]), (40, 3, 11))  # counted by hand
        for record in [r for t in report["topics"] for r in t["records"]] + report["other"]:
            self.assertEqual(record["status"] == "maps", record["issues"] == [], record)  # "maps" means nothing is missing
        self.assertEqual(report["writes"], "none: dry run (no gen-2 store, no gen-1 file)")

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
        self.assertEqual(codes(find(latency, "obligation", "SCOPE-01")), {"obligation-contract-fields-missing", "fields-not-mapped"})  # source_ref
        self.assertEqual(codes(find(latency, "obligation", "9-bad")),
                         {"obligation-contract-fields-missing", "obligation-id-not-a-local-id", "disposition-is-not-verification", "fields-not-mapped"})
        self.assertEqual(codes(find(latency, "contradictions")), {"no-gen2-target"})
        doi = find(latency, "source", "SRC-001")
        self.assertEqual((doi["status"], doi["mapping"]), ("partial", {"identity_scheme": "doi", "identity_value": "10.1000/xyz"}))
        self.assertEqual((find(latency, "source", "SRC-002")["status"], codes(find(latency, "source", "SRC-002"))), ("unmapped", {"no-work-identity"}))
        log = find(latency, "history", "research-activity-1.jsonl")
        self.assertEqual((log["mapping"], codes(log)), ({"lines": 2, "malformed_lines": 1}, {"no-gen2-target", "malformed-lines"}))
        events = find(dry_run.dry_run(self.root, "fleet-a")["other"], "history", "events.jsonl")
        self.assertEqual(events["mapping"], {"lines": 2, "malformed_lines": 1})

    def test_malformed_fields_are_reported_and_the_report_is_still_produced(self) -> None:
        """Astra 0b review A5: a queue item with status [] and a semantic
        state with obligations 3 raised uncaught TypeErrors. Each wrong-typed
        field the importer interprets is now an issue on its record, nothing
        is coerced, and the rest of the input still maps."""
        def edit(queue):
            queue["items"][0]["status"] = []
            queue["items"][1]["cwd"] = 7
            queue["items"][3]["lane"] = ["intake"]
            queue["items"].append({"id": 12, "status": "queued"})
            queue["items"].append({"id": "nul\u0000id", "cwd": str(self.root / "topics" / "nul\u0000id"), "status": "queued"})
            queue["items"].append({"id": "deep", "status": "@@DEEP@@", "completion_lock": "@@DEEPER@@"})
        deep = "[" * 1500 + "]" * 1500  # parses, but deeper than Python can walk or repr
        self.edit_queue(edit, {"@@DEEP@@": deep, "@@DEEPER@@": deep})
        write(self.root / "state" / "stations.json", "[" * 100000)  # deeper than the parser can take
        state = json.loads((self.root / "topics" / "latency" / "SEMANTIC-STATE.json").read_text(encoding="utf-8"))
        write(self.root / "topics" / "latency" / "SEMANTIC-STATE.json", json.dumps(dict(state, obligations=3, deliverables={"a": 1})))
        write(self.root / "topics" / "big" / "SEMANTIC-STATE.json", json.dumps({"schema_version": 2, "obligations": [
            {"id": 5, "text": "t"}, {"id": "OB-2", "text": ["x"], "disposition": 4}]}))
        report = self.dry()
        latency = records_of(report, "latency")
        status = find(latency, "queue status")
        self.assertEqual((status["ref"], status["status"], status["mapping"], codes(status)), ("latency.status=[]", "unmapped", {"status": None}, {"field-shape"}))
        self.assertEqual((find(latency, "queue item")["status"], find(latency, "queue item")["mapping"]["topic_id"]), ("maps", "fleet-a:latency"))
        self.assertEqual([(r["ref"], r["status"], codes(r)) for r in latency if r["gen1"] in ("obligations", "deliverables")],
                         [("latency#obligations", "unmapped", {"field-shape"}), ("latency#deliverables", "unmapped", {"field-shape"})])
        self.assertEqual([r for r in latency if r["gen1"] == "obligation"], [])
        self.assertEqual(find(latency, "intake brief")["status"], "partial")  # the readable parts still map
        big = records_of(report, "big")
        self.assertEqual((find(big, "queue status")["status"], codes(find(big, "queue status"))), ("unmapped", {"untyped-hold", "field-shape"}))
        self.assertEqual((find(big, "obligation", "obligations[0]")["status"], codes(find(big, "obligation", "obligations[0]"))), ("unmapped", {"field-shape"}))
        ob2 = find(big, "obligation", "OB-2")
        self.assertEqual((ob2["mapping"]["text"], sorted(i["code"] for i in ob2["issues"])),
                         (None, ["field-shape", "field-shape", "obligation-contract-fields-missing"]))
        mixed = records_of(report, "Mixed.Case")
        self.assertIn(("unmapped", {"field-shape"}), [(r["status"], codes(r)) for r in mixed if r["gen1"] == "topic directory"])
        self.assertEqual((find(report["other"], "queue item", "items[5]")["status"], codes(find(report["other"], "queue item", "items[5]"))),
                         ("unmapped", {"queue-shape"}))
        self.assertNotIn("12", [t["gen1_id"] for t in report["topics"]])  # an integer id is not stringified into a topic
        nul = records_of(report, "nul\u0000id")
        self.assertEqual(codes(find(nul, "topic directory")), {"topic-dir-not-found"})
        self.assertEqual(codes(find(nul, "queue item")), {"topic-id-not-a-gen2-slug"})
        deep = records_of(report, "deep")
        self.assertEqual((find(deep, "queue status")["status"], codes(find(deep, "queue status"))), ("unmapped", {"field-shape"}))
        self.assertLess(len(find(deep, "queue status")["issues"][0]["detail"]), 300)  # a quoted gen-1 value is abbreviated, not copied whole
        self.assertEqual((find(deep, "completion lock")["mapping"], "value-unrepresentable" in codes(find(deep, "completion lock"))), ({"legacy_lock": None}, True))
        self.assertIn("maximum recursion depth", find(report["other"], "station configuration")["issues"][0]["detail"])
        self.assertIn('"report_version"', dry_run.render(report))

    def test_two_records_claiming_one_gen2_identity_are_flagged(self) -> None:
        """A5: two queue items with the same valid id both mapped, with the
        same gen-2 primary key. Both now carry the collision, neither is
        renamed, and neither reports "maps"; likewise two obligations with
        one id. A distinct id beside them is not flagged."""
        self.edit_queue(lambda queue: queue["items"].append({"id": "latency", "status": "paused"}))
        state = json.loads((self.root / "topics" / "latency" / "SEMANTIC-STATE.json").read_text(encoding="utf-8"))
        state["obligations"].append({"id": "SCOPE-01", "text": "Again", "disposition": "open"})
        write(self.root / "topics" / "latency" / "SEMANTIC-STATE.json", json.dumps(state))
        report = self.dry()
        entries = [t for t in report["topics"] if t["gen1_id"] == "latency"]
        self.assertEqual(len(entries), 2)
        for entry in entries:
            item = find(entry["records"], "queue item")
            self.assertEqual((item["status"], item["mapping"]["topic_id"]), ("partial", "fleet-a:latency"))
            self.assertIn("target-identity-collision", codes(item))
            scope = [r for r in entry["records"] if r["ref"] == "latency#SCOPE-01"]
            self.assertEqual([("target-identity-collision" in codes(r), r["mapping"]["obligation_id"]) for r in scope], [(True, "SCOPE-01"), (True, "SCOPE-01")])
            self.assertNotIn("target-identity-collision", codes(find(entry["records"], "obligation", "9-bad")))
        self.assertNotIn("target-identity-collision", codes(find(records_of(report, "big"), "queue item")))

    def test_identity_numerals_are_checked_as_written(self) -> None:
        """A5: 9007199254740990.6 parsed as 9007199254740991.0 and was then
        accepted as that integer; 1.0000000000000001 mapped as 1. The token is
        now checked before a lossy conversion is accepted or used: a
        fraction, a numeral binary64 does not hold exactly, a string or a
        boolean is not an integer; an integral value in range is accepted in
        any notation (as the store's writer does), and one past 2**53-1 is
        out of range."""
        cases = {"9007199254740990.6": (None, "identity-not-an-integer"), "1.0000000000000001": (None, "identity-not-an-integer"),
                 "1.5": (None, "identity-not-an-integer"), '"3"': (None, "identity-not-an-integer"), "true": (None, "identity-not-an-integer"),
                 "1e400": (None, "identity-not-an-integer"), "9007199254740992": (None, "identity-out-of-range"), "-1": (None, "identity-out-of-range"),
                 "3.0": (3, None), "1e2": (100, None), "9007199254740991": (9007199254740991, None)}
        original = (self.root / "state" / "queue.json").read_text(encoding="utf-8")
        for token, (count, code) in cases.items():
            with self.subTest(token=token):
                (self.root / "state" / "queue.json").write_text(original, encoding="utf-8")
                self.edit_queue(lambda queue: queue["items"][0].update(iterations_completed="@@N@@"), {"@@N@@": token})
                record = find(records_of(self.dry(), "latency"), "accepted iterations")
                self.assertEqual(record["mapping"], {"accepted_count": count})
                self.assertEqual(codes(record), {"ordinals-without-history"} | ({code} if code else set()))


    def test_unsupported_versions_and_unmapped_material_are_reported(self) -> None:
        """A5: a semantic state with schema_version 999 and an unknown
        evidence collection was recorded as read, with no record and no
        issue. An unsupported version is now named and nothing in it is
        interpreted; keys and fields with no mapping are listed, not
        dropped; a queue of another version maps no item and blocks."""
        latency = self.root / "topics" / "latency" / "SEMANTIC-STATE.json"
        write(latency, json.dumps({"schema_version": 999, "topic_id": "latency", "evidence": [{"id": "E-1"}],
                                   "obligations": [{"id": "SCOPE-09", "text": "x", "disposition": "open"}]}))
        write(self.root / "topics" / "big" / "SEMANTIC-STATE.json", json.dumps({"schema_version": 2, "obligations": [], "evidence_graph": {"nodes": [1]}}))
        report = self.dry()
        records = records_of(report, "latency")
        semantic = find(records, "semantic state")
        self.assertEqual((semantic["status"], codes(semantic), semantic["mapping"]),
                         ("unmapped", {"unsupported-schema-version"}, {"schema_version": 999, "keys": ["evidence", "obligations", "schema_version", "topic_id"]}))
        self.assertEqual([r for r in records if r["gen1"] == "obligation"], [])
        self.assertEqual(report["sources"]["topics/latency/SEMANTIC-STATE.json"], f"read ({latency.stat().st_size} bytes)")
        big = find(records_of(report, "big"), "semantic state")
        self.assertEqual((big["status"], codes(big), big["mapping"]), ("unmapped", {"unrecognized-material"}, {"keys": ["evidence_graph"]}))
        fields = find(records, "unmapped fields")
        self.assertEqual((fields["status"], fields["mapping"]), ("unmapped", {"fields": ["title"]}))
        self.assertEqual(find(report["other"], "queue state")["mapping"], {"fields": ["paused", "revision"]})
        for version in (2, None, "1", 1.0):
            with self.subTest(queue_version=version):
                self.edit_queue(lambda queue: queue.update(version=version) if version is not None else queue.pop("version"))
                report = self.dry()
                self.assertEqual([i["code"] for i in report["blocking"]], ["queue-version-unsupported"])
                self.assertEqual(report["topics"], [])
                write(self.root / "state" / "queue.json", queue_text(self.root, lambda queue: queue.update(version=1)))


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
        self.edit_queue(lambda queue: queue["items"].append("not an object"))
        report = dry_run.dry_run(self.root, "fleet-a")
        self.assertEqual([i["code"] for i in report["blocking"]], ["managed-store-not-read"])
        self.assertEqual(report["sources"]["state/control.sqlite3"], "present, not read")
        queue_records = [r for t in report["topics"] for r in t["records"] if r["gen1"] in ("queue item", "queue status", "completion lock", "accepted iterations", "unmapped fields")]
        queue_records += [r for r in report["other"] if r["gen1"] in ("queue item", "queue state")]
        self.assertEqual({r["gen1"] for r in queue_records}, {"queue item", "queue status", "completion lock", "accepted iterations", "unmapped fields", "queue state"})
        for record in queue_records:
            self.assertIn("stale-snapshot", codes(record))
            self.assertNotEqual(record["status"], "maps")

    def test_paths_outside_the_root_are_not_read(self) -> None:
        """A link is refused, not followed, wherever it points, and the refusal
        is reported as missing evidence (a record naming it), not as an
        absent file. An item id cannot walk out of the root either."""
        outside = self.tmp / "outside-ledger.md"
        write(outside, "## [SRC-009] external\n- url: https://example.org/secret\n")
        ledger = self.root / "topics" / "latency" / "SOURCE-LEDGER.md"
        ledger.unlink()
        ledger.symlink_to(outside)
        shutil.rmtree(self.root / "topics" / "big")
        (self.root / "topics" / "big").symlink_to(self.root / "topics" / "latency", target_is_directory=True)  # a link inside the root
        write(self.tmp / "escape" / "AUTHORITY.md", "## Operator brief (verbatim)\n\nescape-marker\n")
        self.edit_queue(lambda queue: queue["items"].extend([{"id": "../../escape", "status": "queued"}, {"id": str(self.tmp / "escape"), "status": "queued"}]))
        report = dry_run.dry_run(self.root, "fleet-a")
        key = "topics/latency/SOURCE-LEDGER.md"
        self.assertEqual(report["sources"].get(key), "refused: topics/latency/SOURCE-LEDGER.md is a symlink (links are not followed)")
        latency = records_of(report, "latency")
        self.assertEqual([r for r in latency if r["gen1"] == "source"], [])
        self.assertEqual((find(latency, "unread input", key)["status"], codes(find(latency, "unread input", key))), ("unmapped", {"input-refused"}))
        self.assertEqual(report["sources"].get("topics/big"), "refused: topics/big is a symlink (links are not followed)")
        self.assertEqual(codes(find(records_of(report, "big"), "topic directory")), {"topic-dir-not-found"})
        self.assertEqual([r for r in records_of(report, "big") if r["gen1"] == "intake brief"], [])  # latency's brief is not read again through the link
        self.assertIn("input-refused", codes(find(report["other"], "unread input", "topics/big")))
        for gen1_id in ("../../escape", str(self.tmp / "escape")):
            self.assertEqual(codes(find(records_of(report, gen1_id), "topic directory")), {"topic-dir-not-found"})
        text = dry_run.render(report)
        self.assertNotIn("example.org/secret", text)
        self.assertNotIn("escape-marker", text)

    def swap_at_open(self, name: str, replace):
        """Patch os.open so that `replace()` runs just before the first open of
        a path named `name`: the path is replaced at the moment it is opened
        (the review's scheduled check/open race, with no gap left)."""
        real_open, done = os.open, []

        def opener(path, flags, mode=0o777, *, dir_fd=None):
            if path == name and not done:
                done.append(path)
                replace()
            return real_open(path, flags, mode, dir_fd=dir_fd)
        return mock.patch.object(dry_run.os, "open", opener), done

    def test_a_source_replaced_by_a_link_as_it_is_opened_is_not_followed(self) -> None:
        """Astra 0b review A2, the read race: after the reader's containment
        checks, state/queue.json was replaced by a symlink to an outside file,
        and the report carried the outside topic "outside-marker" as read
        from queue.json. Here the file, or its parent directory, is replaced
        by a link to outside at the moment the reader opens it: nothing
        outside is read, the queue is reported as not read, and it blocks."""
        outside = self.tmp / "outside"
        write(outside / "queue.json", json.dumps({"version": 1, "items": [{"id": "outside-marker", "status": "queued"}]}))
        state = self.root / "state"

        def swap_file():
            (state / "queue.json").unlink()
            (state / "queue.json").symlink_to(outside / "queue.json")

        def swap_parent():
            state.rename(self.tmp / "state-moved")
            state.symlink_to(outside, target_is_directory=True)

        for case, name, replace, blocking in (("file", "queue.json", swap_file, ["queue-not-read"]),
                                              ("parent directory", "state", swap_parent, ["managed-store-unverifiable", "queue-not-read"])):
            with self.subTest(case=case):
                patch, done = self.swap_at_open(name, replace)
                with patch:
                    report = self.dry()
                self.assertEqual(done, [name])  # the swap happened
                self.assertNotIn("outside-marker", dry_run.render(report))
                self.assertTrue(report["sources"].get("state/queue.json", "").startswith("refused: "), report["sources"].get("state/queue.json"))
                self.assertEqual([i["code"] for i in report["blocking"]], blocking)
                self.assertEqual(report["topics"], [])
                shutil.rmtree(self.root)
                gen1_tree(self.root)

    def test_managed_store_evidence_is_never_mistaken_for_absence(self) -> None:
        """Astra 0b review A3: with state/control.sqlite3 a symlink to an
        existing outside file, the importer reported no managed store and
        mapped the JSON queue as clean. gen-1 runs managed when that path
        exists. The shapes now give three distinct answers: absent (the queue
        maps), a regular file (blocks: not read, stale), and anything the
        importer cannot establish without following or opening it (blocks:
        cannot verify, stale): an outside link, a dangling link, a link inside
        the root, a directory, or a state/ that is itself a link."""
        managed = self.root / "state" / "control.sqlite3"
        write(self.tmp / "outside.sqlite3", "outside-marker")
        cases = {
            "absent": (lambda: None, [], None),
            "regular file": (lambda: write(managed, ""), ["managed-store-not-read"], "present, not read"),
            "symlink to an existing outside file": (lambda: managed.symlink_to(self.tmp / "outside.sqlite3"), ["managed-store-unverifiable"],
                                                    f"a symlink to {str(self.tmp / 'outside.sqlite3')!r}; not followed or read"),
            "dangling symlink": (lambda: managed.symlink_to(self.tmp / "missing.sqlite3"), ["managed-store-unverifiable"],
                                 f"a symlink to {str(self.tmp / 'missing.sqlite3')!r}; not followed or read"),
            "symlink inside the root": (lambda: managed.symlink_to("queue.json"), ["managed-store-unverifiable"], "a symlink to 'queue.json'; not followed or read"),
            "directory": (lambda: managed.mkdir(), ["managed-store-unverifiable"], "a directory; not followed or read"),
        }
        for case, (make, blocking, source) in cases.items():
            with self.subTest(case=case):
                make()
                report = self.dry()
                self.assertEqual([i["code"] for i in report["blocking"]], blocking)
                self.assertEqual(report["sources"].get("state/control.sqlite3"), source)
                item = find(records_of(report, "latency"), "queue item")
                if blocking:
                    self.assertEqual((item["status"], "stale-snapshot" in codes(item)), ("partial", True))
                else:
                    self.assertEqual((item["status"], item["issues"]), ("maps", []))
                self.assertNotIn("outside-marker", dry_run.render(report))
                if managed.is_dir() and not managed.is_symlink():
                    managed.rmdir()
                elif managed.exists() or managed.is_symlink():
                    managed.unlink()
        state = self.root / "state"
        state.rename(self.tmp / "state-elsewhere")
        state.symlink_to(self.tmp / "state-elsewhere", target_is_directory=True)
        report = self.dry()
        self.assertEqual([i["code"] for i in report["blocking"]], ["managed-store-unverifiable", "queue-not-read"])
        self.assertEqual(report["sources"]["state/control.sqlite3"],
                         "an entry that cannot be examined (refused: state is a symlink (links are not followed)); not followed or read")

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
        linked = self.tmp / "linked-out"
        linked.symlink_to(self.root, target_is_directory=True)  # a stable link into the root
        status, _, err = self.run_cli("--fleet", "fleet-a", "--report", str(linked / "report.json"))
        self.assertEqual((status, "inside the gen-1 root" in err), (2, True), err)
        self.assertEqual(snapshot(self.root), before)
        existing = Path(self._tmp.name) / "existing.json"
        existing.write_text("keep", encoding="utf-8")
        self.assertEqual(self.run_cli("--report", str(existing))[0], 2)
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep")
        status, _, err = self.run_cli("--report", str(self.tmp / "no-such-dir" / "report.json"))
        self.assertEqual((status, "cannot open the report's directory" in err), (2, True), err)

    def test_a_report_directory_swapped_for_a_link_after_the_check_is_not_followed(self) -> None:
        """Astra 0b review A2, the report race: after main validated an empty
        output directory outside the root, the directory was renamed and a
        symlink to the gen-1 root put in its place, and the CLI exited 0
        having written report.json inside that root. The directory is now
        held by descriptor from that first open, so the report lands in the
        directory that was checked (under its new name) and the gen-1 tree
        is unchanged."""
        before = snapshot(self.root)
        out, moved = self.tmp / "out", self.tmp / "out.moved"
        out.mkdir()
        real = dry_run._report_directory

        def then_swap(target):
            held = real(target)
            out.rename(moved)
            out.symlink_to(self.root, target_is_directory=True)
            return held
        with mock.patch.object(dry_run, "_report_directory", then_swap):
            status, _, err = self.run_cli("--fleet", "fleet-a", "--report", str(out / "report.json"))
        self.assertEqual(status, 0, err)
        self.assertTrue(out.is_symlink())  # the swap happened
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / "report.json").exists())
        self.assertEqual(json.loads((moved / "report.json").read_text(encoding="utf-8"))["report_version"], "gen1-import-dry-run/1")

    def test_a_report_directory_moved_into_the_root_gets_no_report(self) -> None:
        """The case the descriptor alone cannot answer: the checked directory
        itself is moved into the gen-1 tree. Moved before the file is
        created, the check just before creation refuses and nothing is
        created; moved just after, the check after creation refuses and
        nothing is written into the (empty) file. This test does the moving,
        so the gen-1 tree it checks is expected to hold the moved directory."""
        for when in ("before create", "after create"):
            with self.subTest(when=when):
                out, inside = self.tmp / f"out-{when[0]}", self.root / f"moved-in-{when[0]}"
                out.mkdir()
                real, calls = dry_run._outside_root, []

                def checked(dir_fd, root):
                    calls.append(1)
                    if len(calls) == (1 if when == "before create" else 2):
                        out.rename(inside)
                    return real(dir_fd, root)
                with mock.patch.object(dry_run, "_outside_root", checked):
                    status, _, err = self.run_cli("--fleet", "fleet-a", "--report", str(out / "report.json"))
                self.assertEqual(status, 2, err)
                self.assertIn("inside the gen-1 root", err)
                if when == "before create":
                    self.assertEqual(list(inside.iterdir()), [])
                    self.assertIn("nothing was created", err)
                else:
                    self.assertEqual([(p.name, p.stat().st_size) for p in inside.iterdir()], [("report.json", 0)])
                    self.assertIn("nothing was written to it", err)

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
        # A5: a numeral binary64 does not hold exactly is kept out, not rounded into the report
        self.edit_queue(lambda queue: queue["items"][0].update(completion_lock="@@LOCK@@"), {"@@LOCK@@": "0.1000000000000000000001"})
        report = dry_run.dry_run(self.root, "fleet-a")
        lock = find(records_of(report, "latency"), "completion lock")
        self.assertEqual((lock["mapping"], "numeral-not-exact" in codes(lock)), ({"legacy_lock": None}, True))

    def report_via_cli(self, root: Path, *args: str) -> tuple[int, dict]:
        """(exit status, report) from the CLI for `root`, the report parsed from
        what it printed. A crash, or output that is not a report, fails the
        test (A5: input the importer cannot interpret is reported)."""
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                status = dry_run.main(["--gen1-root", str(root), *args])
        except Exception as exc:
            self.fail(f"the importer crashed instead of reporting: {exc!r} ({len(out.getvalue())} report bytes)")
        report = json.loads(out.getvalue())
        self.assertEqual(report["report_version"], "gen1-import-dry-run/1")
        return status, report

    def test_numerals_the_parser_cannot_convert_are_reported_not_fatal(self) -> None:
        """Astra 0b-repair re-review A5-R2: a 4,301-digit integer, past the
        interpreter's integer-conversion limit, in state/queue.json or in the
        middle line of state/events.jsonl escaped as a ValueError, and the
        CLI printed no report. An exponent past Decimal's range did the same
        (InvalidOperation). Such a queue now blocks as queue-unparseable and
        the report is printed; such a line is counted as malformed and its
        neighbours are read. The numerals just inside each limit (4,300
        digits; an 18-digit exponent) are still read as numbers and reported
        on their own record, as is an exponent so large the number overflows
        (certainly not a binary64, so no exactness check is needed). The
        limit is not raised."""
        limit = sys.get_int_max_str_digits()
        if not limit:
            self.skipTest("this interpreter has no integer-conversion limit")
        # count token -> (exit status, blocking issue, its detail, accepted-iterations codes when the queue maps); by hand
        cases = {"9" * (limit + 1): (1, ["queue-unparseable"], f"an integer numeral of {limit + 1} digits is past the interpreter's integer-conversion limit", None),
                 "9" * limit: (0, [], None, {"identity-out-of-range", "ordinals-without-history"}),
                 "1e-9999999999999999999": (1, ["queue-unparseable"], "the numeral '1e-9999999999999999999' has an exponent past what can be checked exactly", None),
                 "1e-999999999999999999": (0, [], None, {"identity-not-an-integer", "ordinals-without-history"}),
                 "1e9999999999999999999": (0, [], None, {"identity-not-an-integer", "ordinals-without-history"})}
        for n, (token, (exit_status, blocking, detail, count_codes)) in enumerate(cases.items()):
            with self.subTest(queue=token[:24], length=len(token)):
                root = self.tmp / f"queue-{n}"
                write(root / "state" / "queue.json", '{"version":1,"items":[{"id":"topic","status":"queued","iterations_completed":' + token + '}]}')  # the review's payload
                status, report = self.report_via_cli(root, "--fleet", "fleet-a")
                self.assertEqual((status, [i["code"] for i in report["blocking"]]), (exit_status, blocking))
                if count_codes is None:
                    self.assertEqual((report["blocking"][0]["detail"], report["topics"]), (detail, []))
                else:
                    count = find(records_of(report, "topic"), "accepted iterations")
                    self.assertEqual((count["mapping"], codes(count)), ({"accepted_count": None}, count_codes))
        for token, bad in (("9" * (limit + 1), 1), ("9" * limit, 0), ("1e-9999999999999999999", 1), ("1e-999999999999999999", 0)):
            with self.subTest(events=token[:24], length=len(token)):
                write(self.root / "state" / "events.jsonl", '{"type": "a"}\n{"n": ' + token + '}\n{"type": "b"}\n')
                status, report = self.report_via_cli(self.root, "--fleet", "fleet-a")
                events = find(report["other"], "history", "events.jsonl")
                self.assertEqual((status, events["mapping"], codes(events)),
                                 (0, {"lines": 3 - bad, "malformed_lines": bad}, {"no-gen2-target", "malformed-lines"} if bad else {"no-gen2-target"}))
                self.assertEqual(find(records_of(report, "latency"), "queue item")["mapping"], {"topic_id": "fleet-a:latency", "priority": 1})  # the rest maps as usual
        self.assertEqual(sys.get_int_max_str_digits(), limit)

    def test_the_reviews_invalid_unicode_probes_get_a_report(self) -> None:
        """Astra 0b-repair re-review A5-R1: each of these queues, alone in a
        gen-1 root, crashed the CLI with no report. A lone surrogate (the
        JSON escape \\ud800) reached a ref, an issue's text, or the topic id
        and a sources key. Each now gets a report that names the defect.
        The expected records and issue text are written out by hand, with
        each lone surrogate shown as the six characters \\ud800."""
        escaped = "not valid Unicode (it holds a lone surrogate), so shown escaped: each backslash doubled, each lone surrogate written \\udXXX"
        probes = {  # queue.json -> (topics, other, [(kind, ref, issue code, its detail)])
            "status": (r'{"version":1,"items":[{"id":"topic","status":"\ud800"}]}',
                       [("topic", [("queue item", "topic", "maps", []), ("queue status", r"topic.status=\ud800", "unmapped", ["invalid-unicode", "unknown-status"]),
                                   ("completion lock", "topic.completion_lock", "unmapped", ["no-lock"]),
                                   ("accepted iterations", "topic.iterations_completed", "unmapped", ["count-unknown"]),
                                   ("topic directory", "topic", "unmapped", ["topic-dir-not-found"])])], [],
                       [("queue status", r"topic.status=\ud800", "invalid-unicode", "ref: " + escaped)]),
            "unknown key": (r'{"version":1,"items":[],"\ud800":1}', [],
                            [("queue state", "state/queue.json", "unmapped", ["invalid-unicode", "no-gen2-target", "value-unrepresentable"])],
                            [("queue state", "state/queue.json", "no-gen2-target", r"queue-level fields with no mapping in this skeleton: \ud800"),
                             ("queue state", "state/queue.json", "invalid-unicode", "issues[0].detail: " + escaped)]),
            "id": (r'{"version":1,"items":[{"id":"bad\ud800id","status":"queued"}]}', [], [("queue item", "items[0]", "unmapped", ["invalid-unicode"])],
                   [("queue item", "items[0]", "invalid-unicode", r"items[0]: its id 'bad\ud800id' is not valid Unicode (it holds a lone surrogate), so it names no gen-2 topic")]),
        }
        for name, (queue, topics, other, details) in probes.items():
            with self.subTest(probe=name):
                root = self.tmp / name.replace(" ", "-")
                write(root / "state" / "queue.json", queue)
                status, report = self.report_via_cli(root, "--fleet", "fleet-a")
                self.assertEqual((status, report["blocking"]), (0, []))
                self.assertEqual([(t["gen1_id"], as_rows(t["records"])) for t in report["topics"]], [(g, sorted(rows)) for g, rows in topics])
                self.assertEqual(as_rows(report["other"]), sorted(other))
                self.assertEqual(set(report["sources"]), {"state/queue.json", "state/events.jsonl", "state/stations.json"})  # no path made of the id
                records = [r for t in report["topics"] for r in t["records"]] + report["other"]
                for kind, ref, code, detail in details:
                    record = find([r for r in records if r["ref"] == ref], kind)
                    self.assertEqual([i["detail"] for i in record["issues"] if i["code"] == code], [detail])
                self.assertEqual(report["summary"]["issues"], sum(len(r[3]) for _, rows in topics for r in rows) + sum(len(r[3]) for r in other))

    def test_invalid_unicode_is_reported_beside_records_that_still_map(self) -> None:
        """A5-R1 among valid neighbours in the same files: an item whose id
        holds a lone surrogate; one whose status does, after a literal
        backslash, which shows the escaping is reversible; one with such a
        field name; a queue-level key; an obligation id; a cwd; and a topic
        log whose file name is not UTF-8. Each is reported where it occurs,
        escaped (each backslash doubled, each lone surrogate as \\udXXX),
        with an invalid-unicode issue. The records around them are exactly
        what the unedited tree gives."""
        _, before = self.report_via_cli(self.root, "--fleet", "fleet-a")
        cwd = json.dumps(str(self.root / "topics") + "/x")[:-1] + r'\ud800"'

        def edit(queue):
            queue["@@KEY@@"] = 1
            queue["items"] += [{"id": "@@ID@@", "status": "queued"}, {"id": "odd-status", "status": "@@STATUS@@"},
                               {"id": "odd-field", "status": "queued", "@@FIELD@@": True}, {"id": "odd-cwd", "cwd": "@@CWD@@", "status": "queued"}]
        self.edit_queue(edit, {"@@KEY@@": r'"\ud800"', "@@ID@@": r'"bad\ud800id"', "@@STATUS@@": r'"\\\ud800"', "@@FIELD@@": r'"f\udfff"', "@@CWD@@": cwd})
        semantic = self.root / "topics" / "latency" / "SEMANTIC-STATE.json"
        state = json.loads(semantic.read_text(encoding="utf-8"))
        state["obligations"].append({"id": "OB-\ud800", "text": "x", "disposition": "open"})
        write(semantic, json.dumps(state))  # json.dumps writes the surrogate as the escape \ud800
        with open(os.path.join(os.fsencode(self.root / "topics" / "latency" / "logs"), b"\xff.jsonl"), "wb") as handle:
            handle.write(b'{"source": "crossref"}\n')
        status, after = self.report_via_cli(self.root, "--fleet", "fleet-a")
        self.assertEqual((status, after["blocking"]), (0, []))
        for gen1_id in ("latency", "discovery.latency"):  # both read topics/latency
            with self.subTest(topic=gen1_id):
                new = {gen1_id + r"#OB-\ud800": ("obligation", "partial", ["invalid-unicode", "obligation-contract-fields-missing", "obligation-id-not-a-local-id",
                                                                             "value-unrepresentable"]),
                       gen1_id + r"/logs/\udcff.jsonl": ("history", "unmapped", ["invalid-unicode", "no-gen2-target"])}
                records = records_of(after, gen1_id)
                self.assertEqual([r for r in records if r["ref"] not in new], records_of(before, gen1_id))
                self.assertEqual(as_rows([r for r in records if r["ref"] in new]), sorted((k, ref, s, c) for ref, (k, s, c) in new.items()))
        self.assertEqual(after["topics"][1:4], before["topics"][1:4])
        expected = {
            "odd-status": [("queue item", "odd-status", "maps", []), ("queue status", r"odd-status.status=\\\ud800", "unmapped", ["invalid-unicode", "unknown-status"]),
                           ("topic directory", "odd-status", "unmapped", ["topic-dir-not-found"])],
            "odd-field": [("queue item", "odd-field", "maps", []), ("queue status", "odd-field.status=queued", "partial", ["contract-approval-unrecorded"]),
                          ("unmapped fields", "odd-field.fields", "unmapped", ["invalid-unicode", "no-gen2-target", "value-unrepresentable"]),
                          ("topic directory", "odd-field", "unmapped", ["topic-dir-not-found"])],
            "odd-cwd": [("queue item", "odd-cwd", "maps", []), ("queue status", "odd-cwd.status=queued", "partial", ["contract-approval-unrecorded"]),
                        ("topic directory", "odd-cwd", "unmapped", ["topic-dir-not-found", "value-unrepresentable"])],
        }
        self.assertEqual([t["gen1_id"] for t in after["topics"][5:]], list(expected))
        for topic in after["topics"][5:]:
            gen1_id = topic["gen1_id"]
            self.assertEqual(as_rows(topic["records"]), sorted(expected[gen1_id] + [("completion lock", f"{gen1_id}.completion_lock", "unmapped", ["no-lock"]),
                                                                                     ("accepted iterations", f"{gen1_id}.iterations_completed", "unmapped", ["count-unknown"])]))
        other_before = {r["ref"]: r for r in before["other"]}
        self.assertEqual([r for r in after["other"] if r["ref"] in ("state/events.jsonl", "state/stations.json")],
                         [other_before["state/events.jsonl"], other_before["state/stations.json"]])
        self.assertEqual(as_rows([r for r in after["other"] if r["ref"] not in ("state/events.jsonl", "state/stations.json")]), sorted([
            ("queue state", "state/queue.json", "unmapped", ["invalid-unicode", "no-gen2-target", "value-unrepresentable"]),
            ("queue item", "items[5]", "unmapped", ["invalid-unicode"]),
            ("unread input", r"topics/x\ud800", "unmapped", ["input-refused", "invalid-unicode"]),
            ("source path", r"topics/latency/logs/\udcff.jsonl", "unmapped", ["invalid-unicode"]),
            ("source path", r"topics/x\ud800", "unmapped", ["invalid-unicode"])]))
        queue_state = find(after["other"], "queue state")
        self.assertEqual(queue_state["issues"][0]["detail"], r"queue-level fields with no mapping in this skeleton: paused, revision, \ud800")
        self.assertEqual(find(records_of(after, "odd-field"), "unmapped fields")["issues"][0]["detail"], r"queue item fields with no mapping in this skeleton: f\udfff")
        self.assertEqual(find(after["other"], "source path", "logs")["mapping"], {"status": "read (23 bytes)"})
        self.assertEqual(set(after["sources"]) - set(before["sources"]), set())  # the two paths that are not text are records, not keys

    def test_a_root_path_or_fleet_that_is_not_valid_unicode_is_reported(self) -> None:
        """A5-R1 in the report's own fields: a gen-1 root whose path is not
        UTF-8 (\\udcff once decoded) and a fleet holding a lone surrogate are
        shown escaped, with a blocking invalid-unicode issue naming them,
        and the topics are still mapped. A missing root's blocking issue,
        which quotes the path, is escaped too."""
        odd = self.tmp / "gen1-\udcff"
        gen1_tree(odd)
        status, report = self.report_via_cli(odd, "--fleet", "fleet-\ud800")
        self.assertEqual((status, report["gen1_root"], report["fleet_id"]), (1, str(self.tmp.resolve()) + r"/gen1-\udcff", r"fleet-\ud800"))
        self.assertEqual([(i["code"], i["detail"].split(":")[0]) for i in report["blocking"]], [("invalid-unicode", "gen1_root, fleet_id")])
        self.assertEqual([t["gen1_id"] for t in report["topics"]], ["latency", "Mixed.Case", "running-one", "big", "discovery.latency"])
        self.assertEqual(codes(find(records_of(report, "latency"), "queue item")), {"fleet-invalid"})
        self.assertEqual(find(records_of(report, "latency"), "intake brief")["status"], "partial")  # read through the root's odd path
        status, report = self.report_via_cli(self.tmp / "absent-\udcfe", "--fleet", "fleet-a")
        self.assertEqual((status, [(i["code"], i["detail"].split(":")[0]) for i in report["blocking"]]),
                         (1, [("no-gen1-root", str(self.tmp.resolve()) + r"/absent-\udcfe is not a directory"), ("invalid-unicode", "gen1_root, blocking[0].detail")]))
        self.assertEqual(report["fleet_id"], "fleet-a")


if __name__ == "__main__":
    unittest.main()
