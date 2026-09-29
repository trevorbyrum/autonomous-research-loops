"""Shared fixtures for the router tests (not collected as tests).

A RouterTestCase holds one in-memory store (the DDL under gen2/store/, with
the connection contract), adopted through the store's checked route and
handed to a Router, plus the raw sqlite3 connection the test reads back
through. Read-backs are plain SQL on that connection, never the router's own
readers, so an assertion about what was written does not trust the code
under test.

World state that the router has no path for is written with raw SQL, and
only that: topic creation, a brief's first version and a first contract
draft (intake and contract construction are Phase 2), decision specs, and
the scoping -> awaiting_scope_approval step (the committed scoping report is
later work). Every test's router starts with BUNDLE activated through the
router (task 1d): CONFIG is its hash, the bundle new work pins. Everything the router does own — brief confirmation,
scope and contract approval, claims, lifecycle facts, observations, commits,
delivery receipts — goes through the router here, so the fixtures exercise
those paths too.

Expected accept/refuse outcomes are written by hand in each test.
"""
from __future__ import annotations

import json
import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gen2.core import canonical
from gen2.core.instants import utc_instant_ns
from gen2.router import service
from gen2.store import api
from gen2.tests import store_fixtures

EXAMPLES = Path(__file__).resolve().parents[1] / "schema" / "examples"
TOPIC = "fleet-a:t1"
OTHER = "fleet-a:t2"


def question(qid: str = "Q-screen", version: int = 1, text: str = "Does this work meet the pinned eligibility criteria?") -> dict:
    """A question registry entry (config-bundle/1) with its true content hash."""
    entry = {"question_id": qid, "version": version, "text": text}
    return {**entry, "content_hash": canonical.content_hash(entry)}


QUESTION = question()
BUNDLE = {"bundle_version": "config-bundle/1", "version": 1, "policy": {}, "questions": [QUESTION]}
CONFIG = canonical.logical_hash(BUNDLE)
EXPIRES = "2026-12-31T00:00:00Z"
DEADLINE = "2026-12-30T00:00:00Z"
CRITERIA = [
    {"criterion_id": "C-1", "kind": "semantic", "description": "population is adult outpatients", "stage": "abstract"},
    {"criterion_id": "C-2", "kind": "semantic", "description": "reports stage-level latency", "stage": "full_text"},
]


def h(ch: str) -> str:
    return "sha256:" + ch * 64


def jcs(value: object) -> bytes:
    return canonical.canonical_bytes(value)


class Clock:
    """A clock the test controls: each reading is one millisecond after the
    last, from a settable instant."""

    def __init__(self, start: str = "2026-09-27T10:00:00Z") -> None:
        self._ns = utc_instant_ns(start)

    def set(self, instant: str) -> None:
        self._ns = utc_instant_ns(instant)

    def __call__(self) -> str:
        self._ns += 1_000_000
        seconds, rest = divmod(self._ns, 10**9)
        return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + f".{rest // 1_000_000:03d}Z"


class Ids:
    def __init__(self) -> None:
        self.n = 0

    def __call__(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}{self.n:012d}"


class Spool:
    """The spool's read side (C-9): bytes and media type by content hash.
    `reads` records whether each read happened with a store transaction open
    (C-3, C-8); `read_topics` the topic each read asked under. This double
    does not scope by topic itself: the router asking under the invocation's
    topic is checked here, the spool refusing another topic's bytes in
    test_supervisor_spool.py."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.media: dict[tuple[str | None, str], str] = {}
        self.reads: list[tuple[str, bool]] = []
        self.read_topics: list[str] = []
        self.conn: sqlite3.Connection | None = None

    def put(self, raw: bytes, label: str | None = None, media_type: str = "application/json", topic: str | None = None) -> str:
        """Stage bytes; a media type recorded for one `topic` is that topic's
        (a real spool keeps one entry per topic), otherwise any topic's."""
        digest = label or canonical.bytes_digest(raw)
        self.blobs[digest] = raw
        self.media[(topic, digest)] = media_type
        return digest

    def read(self, content_hash: str, *, topic_id: str) -> bytes | None:
        self.reads.append((content_hash, bool(self.conn is not None and self.conn.in_transaction)))
        self.read_topics.append(topic_id)
        return self.blobs.get(content_hash)

    def media_type(self, content_hash: str, *, topic_id: str) -> str | None:
        if content_hash not in self.blobs:
            return None
        return self.media.get((topic_id, content_hash), self.media.get((None, content_hash)))


class Registry:
    """A fake extension registry: admits exactly what it lists."""

    def __init__(self, admitted=()) -> None:
        self.admitted = set(admitted)

    def is_admitted(self, *, module, review_ref) -> bool:
        return (module, review_ref) in self.admitted


def empty_outcome(invocation_id: str, kind: str = "final_outcome", topic: str = TOPIC) -> dict:
    return {"outcome_version": "outcome/1", "invocation_id": invocation_id, "topic_id": topic, "operation_kind": kind,
            "next_queue_state": None, "claims": [], "claim_promotions": [], "claim_source_links": [], "verification_receipts": [], "decision_receipts": [],
            "screening_assessments": [], "review_triggers": [], "review_closures": [], "holds": [], "exports": []}


class RouterTestCase(unittest.TestCase):
    EXTENSIONS: tuple = ()

    def setUp(self) -> None:
        self.db = store_fixtures.connect()
        self.store = api.adopt_in_memory(self.db)
        self.spool = Spool()
        self.spool.conn = self.db
        self.clock = Clock()
        self.ids = Ids()
        self.faults: dict[str, BaseException] = {}
        self.router = self.make_router()
        self.seed()

    def seed(self) -> None:
        """The world every router test starts from: BUNDLE activated through
        the router (new work pins CONFIG), and two topics at intake."""
        activated = self.router.activate_config_bundle(BUNDLE)
        assert activated["status"] == "activated" and activated["bundle_hash"] == CONFIG, activated
        for tid in (TOPIC, OTHER):
            self.x("INSERT INTO queue_entries (topic_id, fleet_id, priority, status, created_at, updated_at) VALUES (?, 'fleet-a', 1, 'awaiting_brief_confirmation', ?, ?)",
                   tid, "2026-09-27T09:00:00Z", "2026-09-27T09:00:00Z")

    def tearDown(self) -> None:
        self.db.close()

    def make_router(self, **overrides) -> service.Router:
        kwargs = dict(clock=self.clock, new_id=self.ids, extensions=Registry(self.EXTENSIONS), fault=self.fault)
        kwargs.update(overrides)
        return service.Router(self.store, self.spool, **kwargs)

    def fault(self, point: str) -> None:
        if point in self.faults:
            raise self.faults.pop(point)

    # -- raw SQL -------------------------------------------------------------
    def x(self, sql: str, *params):
        return self.db.execute(sql, params)

    def rows(self, sql: str, *params) -> list[tuple]:
        return self.db.execute(sql, params).fetchall()

    def value(self, sql: str, *params):
        found = self.rows(sql, *params)
        return found[0][0] if found else None

    def state(self, exclude=("audit_events",)) -> dict[str, list[tuple]]:
        """Every table's rows (audit excluded unless asked), for 'nothing changed' assertions."""
        names = [r[0] for r in self.rows("SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {n: self.rows(f"SELECT * FROM {n} ORDER BY rowid") for n in names if n not in exclude}

    def state_revision(self, tid: str = TOPIC) -> int:
        return self.value("SELECT state_revision FROM queue_entries WHERE topic_id = ?", tid)

    def status(self, tid: str = TOPIC) -> str:
        return self.value("SELECT status FROM queue_entries WHERE topic_id = ?", tid)

    # -- world ---------------------------------------------------------------
    @staticmethod
    def brief_document(tid: str = TOPIC, version: int = 1, **changes) -> dict:
        """An intake-brief/1 document of brief-1 with its true content hash;
        `changes` edit its content (a re-version with them is not lineage-only)."""
        doc = {"brief_version": "intake-brief/1", "topic_id": tid, "brief_id": "brief-1", "version": version, "parent_version": None if version == 1 else version - 1,
               "created_at": "2026-09-27T09:00:00Z", "objective_in_operator_words": "why is intake slow", "feeds": "rebuild or not",
               "evidence_that_would_change_it": ["stage latencies"], "constraints": [], "operator_hypotheses": [], "surfaced_assumptions": [], **changes}
        doc["content_hash"] = canonical.content_hash(doc)
        return doc

    def brief(self, tid: str = TOPIC, version: int = 1, **changes) -> str:
        """An intake brief version (raw SQL: a brief's first version is intake's, Phase 2)."""
        doc = self.brief_document(tid, version, **changes)
        self.x("INSERT INTO intake_briefs (topic_id, brief_id, version, parent_version, content_hash, document, owner_operator_id, status, created_at, review_deadline) "
               "VALUES (?, 'brief-1', ?, ?, ?, ?, 'user', 'awaiting_confirmation', ?, ?)",
               tid, version, doc["parent_version"], doc["content_hash"], json.dumps(doc), doc["created_at"], "2026-10-01T00:00:00Z")
        return doc["content_hash"]

    def contract_draft(self, tid: str = TOPIC, revision: int = 1, *, true_hash: bool = True, criteria=None) -> str:
        doc = {"topic_id": tid, "revision": revision, "parent_revision": None if revision == 1 else revision - 1, "created_at": "2026-09-27T09:30:00Z",
               "protocol_revision": revision, "facet_map": {"framing_version": 1, "facets": []}, "obligations": [],
               "eligibility_protocol": {"protocol_version": revision, "criteria": criteria or CRITERIA}}
        doc["content_hash"] = canonical.content_hash(doc) if true_hash else h("9")
        self.x("INSERT INTO contract_revisions (topic_id, revision, parent_revision, protocol_revision, framing_version, content_hash, document, status, created_at) "
               "VALUES (?, ?, ?, ?, 1, ?, ?, 'draft', ?)", tid, revision, doc["parent_revision"], revision, doc["content_hash"], json.dumps(doc), doc["created_at"])
        return doc["content_hash"]

    def decide(self, did: str, kind: str, subject: dict, tid: str | None = TOPIC, disposition: str = "approved", payload=None) -> dict:
        return self.router.apply_operator_decision({
            "decision_id": did, "topic_id": tid, "kind": kind, "disposition": disposition,
            "subject": {"kind": subject.get("kind"), "ref": subject.get("ref", tid), "revision": subject.get("revision"), "hash": subject.get("hash")},
            "operator_id": "user", "decided_at": "2026-09-27T09:45:00Z", "notes": None, "payload": payload})

    def to_scoping(self, tid: str = TOPIC) -> None:
        bhash = self.brief(tid)
        out = self.decide(f"opd_brief{tid[-2:]}01", "brief_confirmation", {"kind": "intake_brief", "ref": "brief-1", "revision": 1, "hash": bhash}, tid)
        assert out["status"] == "applied", out

    def to_queued(self, tid: str = TOPIC) -> str:
        """S1 -> S3 on the router: the brief confirmed, scope and contract
        revision 1 approved (the scoping-report step is raw SQL)."""
        self.to_scoping(tid)
        chash = self.contract_draft(tid, 1)
        self.x("UPDATE queue_entries SET status = 'awaiting_scope_approval', state_revision = state_revision + 1 WHERE topic_id = ?", tid)
        out = self.decide(f"opd_scope{tid[-2:]}01", "scope_approval", {"kind": "scoping_report", "ref": "scope-1", "revision": 1, "hash": h("5")}, tid)
        assert out["status"] == "applied", out
        out = self.decide(f"opd_cntr{tid[-2:]}01", "contract_approval", {"kind": "contract_revision", "revision": 1, "hash": chash}, tid)
        assert out["status"] == "applied", out
        return chash

    # -- invocations ---------------------------------------------------------
    def claim(self, inv: str, kind: str = "research_pass", tid: str = TOPIC, **extra) -> dict:
        request = {"invocation_id": inv, "kind": kind, "topic_id": tid, "config_bundle_hash": CONFIG, "deadline_at": DEADLINE}
        if kind == "delegate":
            request["parent_capability_id"] = extra.pop("parent")["capability_id"]
        else:
            request.update(station_id="station-1", lease_expires_at=EXPIRES)
        request.update(extra)
        return self.router.claim(request)

    def running(self, grant: dict) -> None:
        for to_state, facts in (("launching", {"job_handle": "job-" + grant["invocation_id"]}),
                                ("running", {"host_id": "host-1", "boot_id": "boot-1", "start_fingerprint": "ticks=1"})):
            out = self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "to_state": to_state, **facts})
            assert out["status"] == "recorded", out

    def started(self, inv: str, kind: str = "research_pass", tid: str = TOPIC, **extra) -> dict:
        grant = self.claim(inv, kind, tid, **extra)
        assert grant["status"] == "granted", grant
        self.running(grant)
        return grant

    def stage(self, document: dict) -> tuple[str, int]:
        raw = jcs(document)
        return self.spool.put(raw), len(raw)

    def ready(self, grant: dict, digest: str) -> None:
        out = self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"],
                                             "to_state": "result_ready", "result_payload_digest": digest})
        assert out["status"] == "recorded", out

    def envelope(self, grant: dict, op: str, outcome: dict, *, refs=(), expected: int | None = None, **overrides) -> dict:
        digest, size = self.stage(outcome)
        env = {"envelope_version": "commit-outcome/1", "operation_id": op, "operation_kind": outcome["operation_kind"],
               "invocation_id": grant["invocation_id"], "capability_id": grant["capability_id"], "topic_id": grant["topic_id"],
               "admission": grant["admission"], "config_bundle_hash": grant["config_bundle_hash"],
               "lease": {"lease_id": grant["lease"]["lease_id"], "generation": grant["lease"]["generation"]},
               "expected_state_revision": self.state_revision(grant["topic_id"]) if expected is None else expected,
               "payload_digest": digest, "payload_size_bytes": size, "result_refs": list(refs), "submitted_at": "2026-09-27T10:30:00Z"}
        env.update(overrides)
        return env

    def artifact(self, text: bytes, media_type: str = "text/plain") -> dict:
        return {"content_hash": self.spool.put(text, media_type=media_type), "size_bytes": len(text), "media_type": media_type}

    def evidence(self, grant: dict, findings=("exit_nonzero",), *, handling: str = "none_found", method: str = "exit_observed", **overrides) -> str:
        """Stage the supervisor's execution record (execution-record/1) for the
        invocation's job as the running() fixture launched it, and return its
        hash: the evidence an end names (task 1c)."""
        inv = grant["invocation_id"]
        record = {"record_version": "execution-record/1", "invocation_id": inv, "topic_id": grant["topic_id"], "job_handle": "job-" + inv,
                  "method": method, "observed_at": "2026-09-27T10:20:00Z",
                  "process": {"host_id": "host-1", "container_id": None, "boot_id": "boot-1", "start_fingerprint": "ticks=1"},
                  "exit": {"code": 1, "signal": None}, "termination": None,
                  "descendants": {"handling": handling, "count": 0 if handling == "none_found" else 1},
                  "output": {"status": "not_collected", "content_hash": None, "size_bytes": None, "declared_digest": None, "detail": None},
                  "self_report": None, "findings": list(findings)}
        record.update(overrides)
        return self.spool.put(jcs(record))

    def finish(self, grant: dict, op: str, outcome: dict | None = None, *, refs=(), **overrides) -> dict:
        """Stage the final outcome, mark the result staged, and commit it."""
        outcome = outcome or empty_outcome(grant["invocation_id"], topic=grant["topic_id"])
        env = self.envelope(grant, op, outcome, refs=refs, **overrides)
        self.ready(grant, env["payload_digest"])
        env["expected_state_revision"] = self.state_revision(grant["topic_id"]) if "expected_state_revision" not in overrides else overrides["expected_state_revision"]
        return self.router.commit_outcome(env)

    # -- exports and holds -----------------------------------------------------
    def export(self, grant: dict, generation: int) -> None:
        """Commit, under `grant` (a running checkpoint of TOPIC), manifest
        man_gen<generation> of an approved publication: its bundle staged, its
        pair (generation, 1), superseding generation 1 after the first."""
        bundle = json.loads((EXAMPLES / "export-bundle" / "valid-completed-topic.json").read_text())["instance"]
        bundle.update(topic_id=TOPIC, bundle_id=f"exb_gen{generation:08d}")
        raw = jcs(bundle)
        bundle_ref = {"content_hash": self.spool.put(raw), "size_bytes": len(raw), "media_type": "application/json"}
        source = h(str(generation))
        self.decide(f"opd_publish{generation:03d}", "publication_approval", {"kind": "publication_source", "ref": "dossier-1", "revision": generation, "hash": source})
        manifest = json.loads((EXAMPLES / "export-manifest" / "valid-completion-generation-1.json").read_text())["instance"]
        manifest.update(manifest_id=f"man_gen{generation:08d}", topic_id=TOPIC, generation=generation, source={"revision": generation, "content_hash": source},
                        approval={"operator_decision_id": f"opd_publish{generation:03d}", "approved_revision": generation},
                        bundle={"bundle_id": f"exb_gen{generation:08d}", "bundle_version": "export-bundle/1", "content_hash": bundle_ref["content_hash"]},
                        supersedes=None if generation == 1 else {"manifest_id": "man_gen00000001", "generation": 1, "options_revision": 1})
        outcome = empty_outcome(grant["invocation_id"], "interim_transition")
        outcome["exports"] = [manifest]
        response = self.router.commit_outcome(self.envelope(grant, f"op_export{generation:05d}", outcome, refs=[bundle_ref]))
        assert response["status"] == "committed", response

    def hold(self, grant: dict, hold_id: str) -> None:
        """Commit, under `grant`, a judgment hold of its topic."""
        outcome = empty_outcome(grant["invocation_id"], "interim_transition", topic=grant["topic_id"])
        outcome["holds"] = [{"hold_id": hold_id, "subject_ref": "export:warehouse", "hold_class": "judgment", "cause": "delivery unsettled",
                             "recoverability": "needs_decision", "required_authority": "operator", "owner": "user", "deadline_at": "2026-10-01T00:00:00Z",
                             "clears_when": "the delivery is reconciled", "capability_fact_id": None}]
        response = self.router.commit_outcome(self.envelope(grant, "op_" + hold_id[5:], outcome))
        assert response["status"] == "committed", response

    def delivery_receipt(self, rid: str, status: str = "delivered", *, generation: int = 1, attempt: int = 1, connector: str = "warehouse", **extra) -> dict:
        """An export-delivery-receipt/2 for manifest man_gen<generation>, valid
        for its status, unless `extra` says otherwise."""
        doc = {"receipt_version": "export-delivery-receipt/2", "export_receipt_id": rid, "manifest_id": f"man_gen{generation:08d}", "topic_id": TOPIC,
               "connector": {"connector_id": connector, "connector_type": "sql" if connector == "warehouse" else "jsonl_file"},
               "generation": generation, "options_revision": 1, "attempt": attempt, "status": status,
               "written": {"status": "observed", "value": 12}, "tombstones_acknowledged": status == "delivered",
               "reconciliation_required": status == "outcome_unknown", "attempted_at": "2026-09-27T12:00:00Z",
               "acked_at": "2026-09-27T12:00:01Z" if status == "delivered" else None}
        if status == "failed":
            doc.update(error_class="unreachable", written={"status": "observed", "value": 0})
        if status == "outcome_unknown":
            doc.update(unknown_cause="no_response_after_send", written={"status": "unknown", "reason": "no response"})
        doc.update(extra)
        return doc
