"""Shared fixtures for the router tests (not collected as tests).

A RouterTestCase holds one in-memory store (the DDL under gen2/store/, with
the connection contract), adopted through the store's checked route and
handed to a Router, plus the raw sqlite3 connection the test reads back
through. Read-backs are plain SQL on that connection, never the router's own
readers, so an assertion about what was written does not trust the code
under test.

World state is written with raw SQL where the router had no path for it
when these fixtures were written: topic creation, a brief's first version
and a first contract draft, the scope step (scoping -> awaiting_scope_approval
-> awaiting_contract_approval: scope_seeded), and decision specs. Task 2a
gave the router all but decision specs (create_topic, open_brief,
draft_contract, and the scoping report's commit and scope approval:
scoped()); the suites written before it keep these fixtures as they are,
since a real scoping pass would change the leases, receipts and counts they
assert, and the 2a tests (test_router_workflow.py) use the router's paths.
Since task 2a a scope approval needs a stored report, so the seeded scope
step records no decision. Every test's router starts with BUNDLE activated through the
router (task 1d): CONFIG is its hash, the bundle new work pins. Everything the router does own — brief confirmation,
scope and contract approval, claims, lifecycle facts, observations, commits,
delivery receipts — goes through the router here, so the fixtures exercise
those paths too.

Expected accept/refuse outcomes are written by hand in each test.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from gen2.core import canonical
from gen2.core.gateway_capture import RetainedExchange
from gen2.core.instants import utc_instant_ns
from gen2.router import service
from gen2.store import api
from gen2.tests import store_fixtures

EXAMPLES = Path(__file__).resolve().parents[1] / "schema" / "examples"
TOPIC = "fleet-a:t1"
OTHER = "fleet-a:t2"


def find_request(query: str = "intake latency", **sent) -> dict:
    """The attempted-request document of a find observation (gen2/core/pagination.py): the lane, the page, and the request sent,
    which names its type (`request_type`, from a closed set) because what an end means depends on it."""
    return {"lane": "crossref", "page": 1, "request": {"request_type": "find", "query": query, **sent}}


def question(qid: str = "Q-screen", version: int = 1, text: str = "Does this work meet the pinned eligibility criteria?") -> dict:
    """A question registry entry (config-bundle/1) with its true content hash."""
    entry = {"question_id": qid, "version": version, "text": text}
    return {**entry, "content_hash": canonical.content_hash(entry)}


QUESTION = question()
# task 2a: the templates the example contract (schema/examples/contract-v2/valid-two-obligations.json) is drafted in
TEMPLATES = {"obligation": [{"template_id": "T-comparison", "template_version": 1, "claim_type": "comparison",
                             "required_slots": ["comparator", "intervention", "outcome", "population"], "optional_slots": ["setting"]}],
             "method_design": [{"template_id": "MD-sr-plus-initiation", "template_version": 1,
                                "families": [{"family": "systematic_review", "role": "primary"}, {"family": "truth_discovery", "role": "added", "purpose": "initiation"}]}]}
BUNDLE = {"bundle_version": "config-bundle/1", "version": 1, "policy": {}, "questions": [QUESTION], "templates": TEMPLATES}
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

    def next_reads(self, instant: str) -> None:
        """The next reading is exactly `instant`: a repeated or earlier one, as a real clock may give."""
        self._ns = utc_instant_ns(instant) - 1_000_000

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
            "screening_assessments": [], "review_triggers": [], "review_closures": [], "scoping_reports": [], "source_proposals": [], "holds": [], "exports": []}


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

    def state(self, exclude=()) -> dict[str, list[tuple]]:
        """All tables except the explicitly excluded ones; generation is visible."""
        names = [r[0] for r in self.rows("SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {n: self.rows(f"SELECT * FROM {n} ORDER BY rowid") for n in names if n not in exclude}

    def assert_generation_delta(self, before, after, increments):
        """Normalize only after exact singleton, epoch and counter assertions."""
        rows = before['store_generation']
        self.assertLessEqual(len(rows), 1)
        singleton, epoch, counter = rows[0] if rows else ('store', None, 0)
        expected = [(singleton, epoch, counter + increments)] if rows or increments else []
        self.assertEqual(after['store_generation'], expected)
        after['store_generation'] = before['store_generation']

    def assert_audited_state(self, before, increments, *, audits=1, exclude=(), msg=None):
        after = self.state(exclude=exclude)
        self.assert_generation_delta(before, after, increments)
        if 'audit_events' in before:
            self.assertEqual(after['audit_events'][:len(before['audit_events'])], before['audit_events'])
            self.assertEqual(len(after['audit_events']), len(before['audit_events']) + audits)
            after['audit_events'] = before['audit_events']
        self.assertEqual(after, before, msg)

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
               "eligibility_protocol": {"protocol_version": revision, "criteria": criteria or CRITERIA}, "method_design": {},
               "decision_record": {"objective": {"confirmed_brief": {"brief_id": "brief-1", "version": 1, "confirmed_by": f"opd_brief{tid[-2:]}01"}}}}
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
        """S1 -> S3 for the pre-2a suites: the brief confirmed on the router,
        the scope step seeded raw (scope_seeded: no report, no decision), and
        contract revision 1 (a raw-SQL draft naming the confirmed brief)
        approved on the router."""
        self.to_scoping(tid)
        chash = self.contract_draft(tid, 1)
        self.scope_seeded(tid)
        out = self.decide(f"opd_cntr{tid[-2:]}01", "contract_approval", {"kind": "contract_revision", "revision": 1, "hash": chash}, tid)
        assert out["status"] == "applied", out
        return chash

    def scope_seeded(self, tid: str = TOPIC) -> None:
        """The pre-2a suites' scope step, raw: scoping -> awaiting_scope_approval
        -> awaiting_contract_approval, two queue moves the DDL admits, with no
        report and no decision (scoped() is the router's path)."""
        for status in ("awaiting_scope_approval", "awaiting_contract_approval"):
            self.x("UPDATE queue_entries SET status = ?, state_revision = state_revision + 1 WHERE topic_id = ?", status, tid)

    def scoping_report_document(self, tid: str = TOPIC, version: int = 1, **changes) -> dict:
        """A scoping-report/1 of report scope-1, scoped under the topic's brief-1 v1, its hash true."""
        doc = {"report_version": "scoping-report/1", "report_id": "scope-1", "topic_id": tid, "version": version, "parent_version": None if version == 1 else version - 1,
               "created_at": "2026-09-27T09:40:00Z", "brief": {"brief_id": "brief-1", "version": 1, "content_hash": self.brief_document(tid)["content_hash"]},
               "territory_map": {"extent": "some forty studies", "range": "human and agent intake", "nature": "case studies, few comparisons"},
               "traditions": [{"tradition_id": "TR-re", "community": "requirements engineering", "names": ["elicitation completeness"], "assumptions": "omissions are countable"}],
               "candidate_facets": [{"facet_id": "F-effect", "label": "effect on omissions", "rationale": "the decision turns on it"}],
               "gap_map": [{"facet_id": "F-effect", "question_type": "effect", "state": "unknown"}], "deliberately_out": [],
               "discovery_mechanisms": [{"mechanism": "database_search", "status": "ran"}], "coverage": [], **changes}
        doc["content_hash"] = canonical.content_hash(doc)
        return doc

    def scoped(self, tid: str = TOPIC, inv: str | None = None) -> dict:
        """S2 on the router (task 2a): a pre-contract research pass commits the
        scoping report — the topic moves to awaiting_scope_approval — and the
        operator approves exactly that report; returns it."""
        inv = inv or f"inv_scope{tid[-2:]}0001"
        report = self.scoping_report_document(tid)
        out = self.finish(self.started(inv, tid=tid), f"op_scope{tid[-2:]}0001", {**empty_outcome(inv, topic=tid), "scoping_reports": [report]})
        assert out["status"] == "committed", out
        out = self.decide(f"opd_scope{tid[-2:]}01", "scope_approval", {"kind": "scoping_report", "ref": "scope-1", "revision": 1, "hash": report["content_hash"]}, tid)
        assert out["status"] == "applied", out
        return report

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

    def stage(self, document: dict, topic: str = TOPIC) -> tuple[str, int]:
        raw = jcs(document)
        if hasattr(self.spool, "real"):  # the operator suites' staging spool
            return self.spool.put(raw, topic=topic), len(raw)
        if hasattr(self.spool, "put"):  # this file's fake and the restart suite's: bytes for any topic
            return self.spool.put(raw), len(raw)
        return self.spool.stage(topic, raw, "application/json")["content_hash"], len(raw)  # the real spool (the supervisor suites' worlds)

    def ready(self, grant: dict, digest: str) -> None:
        out = self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"],
                                             "to_state": "result_ready", "result_payload_digest": digest})
        assert out["status"] == "recorded", out

    def envelope(self, grant: dict, op: str, outcome: dict, *, refs=(), expected: int | None = None, **overrides) -> dict:
        digest, size = self.stage(outcome, grant["topic_id"])
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

    def verification_receipt(self, verifier: dict) -> dict:
        return {"receipt_version": "verification-receipt/1", "verification_receipt_id": "ver_000000000001", "topic_id": TOPIC,
                "claim": {"claim_id": "clm_00000001", "claim_revision": 1}, "source": {"work_id": "wrk_00000001", "source_version": "v1"},
                "cited_spans": [{"start": 0, "end": 5, "locator": {"kind": "page", "value": "3"}}], "obtained_content_hash": h("7"),
                "access_tier": "full_text", "requested_for": {"use": "load_bearing", "required_access_tier": "full_text"},
                "acquisition": {"route": "gateway:crossref", "retrieved_at": "2026-09-27T10:00:00Z", "gateway_call_ref": "call-1", "cache_reuse": False},
                "extraction": {"method": "verifier_extraction", "extractor": "x-1", "produced_by_invocation_id": verifier["invocation_id"], "validation_ref": None},
                "producer_invocation_id": "inv_research01", "verifier_invocation_id": verifier["invocation_id"],
                "verifier_capability_id": verifier["capability_id"], "quote_check_id": None,
                "checks": {"exact_quote": {"status": "not_applicable", "normalization_version": "n1", "source_artifact_hash": h("7")},
                           "numeric_units": "checked_ok", "denominators": "checked_ok", "negation": "not_applicable", "qualifications": "checked_ok"},
                "adjudication": None, "verdict": "supports", "verified_at": "2026-09-27T10:05:00Z"}


# -- Workflow and approved-contract worlds -----------------------------------


EXAMPLE = json.loads((EXAMPLES / "contract-v2" / "valid-two-obligations.json").read_text())["instance"]


def contract_doc(revision: int, parent: int | None, *, rated: bool = True, edit=None) -> dict:
    """The example contract as TOPIC's revision `revision`; `edit` changes it."""
    doc = copy.deepcopy(EXAMPLE)
    # 2c-3b: these declared thresholds/challenge/screening operands have no
    # automatic evaluator. This Router fixture explicitly requests reviews.
    for profile in doc["stopping_profiles"]:
        for rule in profile["rules"]:
            rule["evaluation"] = "reviewed_judgment"
    doc.update(topic_id=TOPIC, revision=revision, parent_revision=parent, created_at="2026-09-27T09:30:00Z")
    doc["decision_record"]["objective"]["confirmed_brief"] = {"brief_id": "brief-1", "version": 1, "confirmed_by": "opd_brieft101"}  # the world's (task 2a checks it)
    for entry in doc["facet_map"]["facets"] + doc["obligations"]:
        entry["importance"]["proposed"] = None
        if not rated:
            entry["importance"]["operator_rating"] = None
    if edit is not None:
        edit(doc)
    doc["content_hash"] = canonical.content_hash(doc)
    return doc


def compatible(doc: dict) -> None:
    """A surveillance-policy edit — when a completed topic is re-checked
    (flow S8) — with no framing, protocol or obligation change
    (CompatibilityRuleTest states why it is compatible)."""
    doc["surveillance_policy"]["freshness_requirement"]["max_currency_age_days"] = 90


def protocol_changed(doc: dict) -> None:
    doc["protocol_revision"] = 2
    doc["eligibility_protocol"]["protocol_version"] = 2
    doc["eligibility_protocol"]["criteria"][1]["description"] = "Reports an omission, coverage or cost outcome for elicited requirements."


REFRAMED_QUESTION = "Which facets does intake design cause to be missed, and at what operator cost?"


def reframed(doc: dict) -> None:
    """A reframe: a framework link's key question reworded, under the next framing version (G-6)."""
    doc["facet_map"]["framing_version"] = 2
    doc["facet_map"]["analytic_framework"]["links"][0]["key_question"] = REFRAMED_QUESTION


def columns(entry: dict) -> tuple:
    """A facet's or obligation's importance columns, from its entry (written out here, not the router's projection)."""
    proposed, rating = entry["importance"]["proposed"] or {}, entry["importance"]["operator_rating"] or {}
    return (proposed.get("source"), proposed.get("score"), proposed.get("decision_receipt_id"), rating.get("band"), rating.get("score"), rating.get("operator_decision_id"))


REVIEW_BY = "2026-10-01T00:00:00Z"


def jcs_hash(text: str) -> str:
    """SHA-256 over JCS bytes written out by hand in the test (keys sorted, no whitespace)."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def work_of(scheme: str, value: str) -> str:
    return "wrk_" + jcs_hash(f'{{"identity_scheme":"{scheme}","identity_value":"{value}"}}').split(":", 1)[1]


def contract(revision: int, parent: int | None, *, topic: str = TOPIC, rated: bool = True, edit=None) -> dict:
    """The example contract as `topic`'s revision, its ratings citing opd_rate0001 (the example's), its hash true."""
    def change(doc: dict) -> None:
        doc["topic_id"] = topic
        doc["decision_record"]["objective"]["confirmed_brief"] = {"brief_id": "brief-1", "version": 1, "confirmed_by": f"opd_brief{topic[-2:]}01"}
        if edit is not None:
            edit(doc)
    return contract_doc(revision, parent, rated=rated, edit=change)


def ratings(doc: dict) -> dict:
    """A rating_approval's payload: exactly the ratings `doc` carries."""
    rating = lambda entry: {"band": entry["importance"]["operator_rating"]["band"], "score": entry["importance"]["operator_rating"].get("score")}  # noqa: E731
    return {"facets": {f["facet_id"]: rating(f) for f in doc["facet_map"]["facets"]}, "obligations": {o["obligation_id"]: rating(o) for o in doc["obligations"]}}


def link(claim: str = "clm_00000001", revision: int = 1, work: str | None = None, obligation: str = "O-1") -> dict:
    return {"claim_id": claim, "claim_revision": revision, "work_id": work or work_of("doi", "10.1/x"), "source_version": "v1", "obligation_id": obligation,
            "spans": [{"start": 10, "end": 42, "locator": {"kind": "page", "value": "3"}}], "contribution": "answer",
            "evidence_origin_lineage": "study-1", "analytical_method": None}


def signal(cause: str = "retraction-notice-7", *, reason: str = "retraction", source: str = "deterministic", revision: int = 1,
           observed: str = "2026-09-27T09:50:00Z", tid: str = TOPIC) -> dict:
    return {"topic_id": tid, "reason_code": reason, "signal_source": source, "cause_ref": cause, "source_revision": revision, "observed_at": observed}


UNAVAILABLE = {"observation_id": "obs_t1scope002", "request": find_request("cost"), "request_identity": canonical.logical_hash(find_request("cost")), "attempt": 1,
               "lane": "semantic_scholar", "obligation_ids": [], "started_at": "2026-09-27T10:00:00Z", "ended_at": "2026-09-27T10:00:01Z",
               "coverage_state": "provider_unavailable", "result_count": None, "completeness": "unobserved", "error_class": "provider_outage",
               "capability_fact_id": None, "policy_version": "pol-1", "cost_units": None, "gateway_call_ref": None, "page_outcome": "failed", "continuation": None}


PROPOSAL_EXAMPLE = json.loads((EXAMPLES / "source-proposal" / "valid-domain-lane-with-a-key.json").read_text())["instance"]


def proposal(grant: dict, pid: str = "srcp_00000001", **changes) -> dict:
    doc = {**PROPOSAL_EXAMPLE, "proposal_id": pid, "topic_id": grant["topic_id"],
           "proposed_by": {"invocation_id": grant["invocation_id"], "invocation_kind": grant["kind"]}, **changes}
    doc["motivation"] = {**doc["motivation"], "blocked_obligation_ids": changes.get("blocked", [])}
    doc.pop("blocked", None)
    return doc


class Workflow(RouterTestCase):
    """Router paths for S1-S3, and the capture helpers of S4-S5."""

    def open_brief(self, tid: str = TOPIC, version: int = 1, deadline: str = REVIEW_BY, **changes) -> dict:
        return self.router.open_brief({"document": self.brief_document(tid, version, **changes), "owner_operator_id": "user", "review_deadline": deadline})

    def confirm(self, tid: str = TOPIC, version: int = 1, doc: dict | None = None) -> None:
        doc = doc or self.brief_document(tid, version)
        out = self.decide(f"opd_brief{tid[-2:]}{version:02d}", "brief_confirmation", {"kind": "intake_brief", "ref": "brief-1", "revision": version,
                                                                                     "hash": doc["content_hash"]}, tid)
        assert out["status"] == "applied", out

    def draft(self, doc: dict) -> dict:
        return self.router.draft_contract({"document": doc})

    def rate(self, rated: dict, tid: str = TOPIC) -> dict:
        """The operator rates draft 1 of `tid`, as `rated` states the ratings."""
        r1 = self.value("SELECT content_hash FROM contract_revisions WHERE topic_id = ? AND revision = 1", tid)
        return self.decide("opd_rate0001", "rating_approval", {"kind": "contract_revision", "revision": 1, "hash": r1}, tid, payload=ratings(rated))

    def rated_drafts(self, tid: str = TOPIC) -> dict:
        """S1 and S3's drafts through the router: the brief opened and
        confirmed, draft 1 unrated, the operator's rating of it, draft 2
        carrying the ratings."""
        if not self.rows("SELECT 1 FROM intake_briefs WHERE topic_id = ?", tid):
            assert self.open_brief(tid)["status"] == "recorded"
            self.confirm(tid)
        r2 = contract(2, 1, topic=tid)
        assert self.draft(contract(1, None, topic=tid, rated=False))["status"] == "recorded"
        assert self.rate(r2, tid)["status"] == "applied"
        assert self.draft(r2)["status"] == "recorded"
        return r2

    def scope_approved(self, tid: str = TOPIC) -> dict:
        """S2 through the router: a pre-contract pass commits the scoping report, the operator approves exactly it (router_fixtures.scoped)."""
        return self.scoped(tid)

    def approve(self, doc: dict, tid: str = TOPIC, did: str | None = None) -> dict:
        return self.decide(did or f"opd_cntr{tid[-2:]}{doc['revision']:02d}", "contract_approval",
                           {"kind": "contract_revision", "revision": doc["revision"], "hash": doc["content_hash"]}, tid)

    def approved(self, tid: str = TOPIC) -> dict:
        r2 = self.rated_drafts(tid)
        self.scope_approved(tid)
        out = self.approve(r2, tid)
        assert out["status"] == "applied", out
        return r2

    # -- S4 capture ------------------------------------------------------------------
    def observe(self, grant: dict, observation_id: str, records: tuple[str, ...]) -> list[str]:
        """A successful search of the grant's topic capturing `records`; returns the retrieval event ids."""
        request = find_request(observation_id)
        events = [{"event_id": f"rev_{observation_id[4:]}{n:02d}", "provider_record_id": record, "rank": n, "captured_at": "2026-09-27T10:00:00Z"}
                  for n, record in enumerate(records, 1)]
        observation = {"observation_id": observation_id, "request": request, "request_identity": canonical.logical_hash(request), "attempt": 1, "lane": "crossref",
                       "obligation_ids": ["O-1"], "started_at": "2026-09-27T10:00:00Z", "ended_at": "2026-09-27T10:00:01Z", "coverage_state": "searched_ok",
                       "result_count": len(events), "completeness": "complete", "error_class": None, "capability_fact_id": None, "policy_version": "pol-1",
                       "cost_units": None, "gateway_call_ref": "call-1", "page_outcome": "end_unknown", "continuation": None}
        out = self.router.record_observation({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "observation": observation,
                                              "retrieval_events": events})
        assert out["status"] == "recorded", out
        return [e["event_id"] for e in events]

    def register(self, grant: dict, works: list[tuple[str, str, list[str]]], version: str = "dedup-1") -> dict:
        return self.router.register_works({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "dedup_method_version": version,
                                           "works": [{"identity_scheme": s, "identity_value": v, "event_ids": list(e)} for s, v, e in works]})

    def capture(self, grant: dict, op: str, claim: str = "clm_00000001", revision: int = 1, **sections) -> dict:
        """An interim commit under `grant` capturing a claim (unless claim is None), with any other sections."""
        outcome = empty_outcome(grant["invocation_id"], "interim_transition", topic=grant["topic_id"])
        refs = []
        if claim is not None:
            text = self.artifact(f"{claim} r{revision}".encode())
            outcome["claims"] = [{"claim_id": claim, "revision": revision, "text_ref": text, "load_bearing": False, "required_access_tier": None}]
            refs = [text]
        outcome.update(sections)
        return self.router.commit_outcome(self.envelope(grant, op, outcome, refs=refs))

    def refused_commit(self, grant: dict, op: str, reason: str, detail: str, **sections) -> None:
        before = self.state()
        out = self.capture(grant, op, claim=None, **sections)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", reason), out)
        self.assertIn(detail, out.get("detail", ""))
        self.assert_audited_state(before, 1)


class ContractWorld(RouterTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.build_world()

    def build_world(self) -> None:
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000001', 'doi', '10.1/x', '2026-09-27T09:00:00Z')")
        self.to_scoping()
        self.scope_seeded()
        r1, rated = contract_doc(1, None, rated=False), contract_doc(2, 1)
        self.store_draft(r1)
        payload = {"facets": {f["facet_id"]: {"band": f["importance"]["operator_rating"]["band"], "score": f["importance"]["operator_rating"].get("score")}
                              for f in rated["facet_map"]["facets"]},
                   "obligations": {o["obligation_id"]: {"band": o["importance"]["operator_rating"]["band"], "score": o["importance"]["operator_rating"].get("score")}
                                   for o in rated["obligations"]}}
        assert self.decide("opd_rate0001", "rating_approval", {"kind": "contract_revision", "revision": 1, "hash": r1["content_hash"]}, payload=payload)["status"] == "applied"
        self.store_draft(rated)
        assert self.decide("opd_cntr0002", "contract_approval", {"kind": "contract_revision", "revision": 2, "hash": rated["content_hash"]})["status"] == "applied"

    def store_draft(self, doc: dict) -> None:
        """A first draft and its rows (raw SQL: contract construction is Phase 2)."""
        self.x("INSERT INTO contract_revisions (topic_id, revision, parent_revision, protocol_revision, framing_version, content_hash, document, status, created_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?)", doc["topic_id"], doc["revision"], doc["parent_revision"], doc["protocol_revision"],
               doc["facet_map"]["framing_version"], doc["content_hash"], jcs(doc).decode(), doc["created_at"])
        for f in doc["facet_map"]["facets"]:
            self.x("INSERT INTO facets (topic_id, contract_revision, facet_id, proposed_importance_source, proposed_importance_score, proposed_decision_receipt_id, "
                   "operator_importance_band, operator_importance_score, operator_rating_decision_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   doc["topic_id"], doc["revision"], f["facet_id"], *columns(f))
        for o in doc["obligations"]:
            self.x("INSERT INTO obligations (topic_id, contract_revision, obligation_id, template_id, template_version, claim_type, facet_ids, stopping_profile_id, exploratory, "
                   "proposed_importance_source, proposed_importance_score, proposed_decision_receipt_id, operator_importance_band, operator_importance_score, operator_rating_decision_id) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", doc["topic_id"], doc["revision"], o["obligation_id"], o["template"]["template_id"],
                   o["template"]["template_version"], o["template"]["claim_type"], json.dumps(o["facet_ids"]), o["stopping_profile_id"], int(o["exploratory"]), *columns(o))

    def propose(self, revision: int, edit=None, parent: int | None = None) -> dict:
        doc = contract_doc(revision, revision - 1 if parent is None else parent, edit=edit)
        out = self.router.propose_amendment({"document": doc})
        assert out["status"] == "recorded", out
        return doc

    def approve(self, doc: dict, kind: str = "amendment_approval", did: str | None = None) -> dict:
        return self.decide(did or f"opd_amend{doc['revision']:04d}", kind, {"kind": "contract_revision", "revision": doc["revision"], "hash": doc["content_hash"]})

    def impact(self, did: str) -> dict:
        document = self.value("SELECT document FROM amendment_impacts WHERE decision_id = ?", did)
        self.assertIsNotNone(document, f"no impact is recorded for {did}")
        return json.loads(document)

    def research(self, inv: str = "inv_research01", *, load_bearing: bool = True) -> dict:
        """A research pass under revision 2 that screens (an inclusion and an
        exclusion), captures a claim (load-bearing, at full text, unless
        `load_bearing` is False) and observes a search."""
        grant = self.started(inv)
        text = self.artifact(b"a load-bearing claim")
        outcome = empty_outcome(inv, "interim_transition")
        outcome["claims"] = [{"claim_id": "clm_00000001", "revision": 1, "text_ref": text, "load_bearing": load_bearing,
                               "required_access_tier": "full_text" if load_bearing else None}]
        outcome["screening_assessments"] = [
            {"assessment_id": "asm_000000000001", "work_id": "wrk_00000001", "stage": "abstract", "decision": "include", "reason_code": None,
             "criterion_results": {"EC-outcome": "met"}, "actor_kind": "primary", "decision_receipt_id": None, "supersedes_assessment_id": None},
            {"assessment_id": "asm_000000000002", "work_id": "wrk_00000001", "stage": "abstract", "decision": "exclude", "reason_code": "EC-outcome",
             "criterion_results": {"EC-outcome": "not_met"}, "actor_kind": "primary", "decision_receipt_id": None, "supersedes_assessment_id": None}]
        assert self.router.commit_outcome(self.envelope(grant, "op_capture0001", outcome, refs=[text]))["status"] == "committed"
        request = find_request("intake omissions")
        observation = {"observation_id": "obs_000000000001", "request": request, "request_identity": canonical.logical_hash(request), "attempt": 1, "lane": "crossref",
                       "obligation_ids": ["O-1"], "started_at": "2026-09-27T10:00:00Z", "ended_at": "2026-09-27T10:00:01Z", "coverage_state": "searched_empty",
                       "result_count": 0, "completeness": "complete", "error_class": None, "capability_fact_id": None, "policy_version": "pol-1", "cost_units": None,
                       "gateway_call_ref": "call-1", "page_outcome": "end_unknown", "continuation": None}
        assert self.router.record_observation({"capability_id": grant["capability_id"], "invocation_id": inv, "observation": observation, "retrieval_events": []})["status"] == "recorded"
        return grant

    def verify(self, canonical_producer=None, acquisition_producer=None) -> dict:
        verifier = self.started("inv_verify01", "verification")
        self.verifier = verifier
        from gen2.tests.detailed_receipt_fixtures import seed_checks
        doc = self.verification_receipt(verifier)
        if canonical_producer is not None or acquisition_producer is not None:
            # Raw admitted fixture operands for the amendment control. This
            # test exercises pin compatibility, not capture authentication.
            raw = b'{"records":[{"identity":"rec-full","kind":"full_text","text":"Fixture full text"}]}'
            ref = self.artifact(raw, "application/json")
            self.x("""INSERT INTO search_observations (observation_id, invocation_id, topic_id, request_identity, attempt,
                lane, request, obligation_ids, started_at, ended_at, coverage_state, result_count, completeness,
                error_class, capability_fact_id, policy_version, cost_units, gateway_call_ref, page_outcome, continuation)
                SELECT 'obs_support001', invocation_id, topic_id, request_identity, 2, lane, request, obligation_ids,
                started_at, ended_at, 'searched_ok', 1, completeness, error_class, capability_fact_id, policy_version,
                cost_units, gateway_call_ref, page_outcome, continuation FROM search_observations
                WHERE observation_id = 'obs_000000000001'""")
            self.x("INSERT INTO retrieval_events VALUES ('rev_support001', 'obs_support001', ?, 'rec-full', 1, '2026-09-27T10:00:00Z')", TOPIC)
            self.x("INSERT INTO record_work_links VALUES ('rev_support001', 'wrk_00000001', 'dedup-1', '2026-09-27T10:00:00Z')")
            payload = {**empty_outcome("inv_research01", "interim_transition"), "source_artifacts": [
                {"work_id": "wrk_00000001", "source_version": "canonical-v1", "artifact_ref": ref}]}
            self.assertEqual(self.router.commit_outcome(self.envelope(canonical_producer or acquisition_producer, "op_support001", payload, refs=[ref]))["status"], "committed")
            request, identity = self.rows("SELECT request, request_identity FROM search_observations WHERE observation_id = 'obs_support001'")[0]
            self.x("INSERT INTO source_acquisitions VALUES (?, 'wrk_00000001', 'canonical-v1', ?, 'obs_support001', 'rev_support001', 'call-1', 'inv_research01', 2, 'crossref', 'find', 'rec-full', '2026-09-27T10:00:00Z', 'inv_verify01', ?, ?, ?, '2026-09-27T10:00:00Z')", TOPIC, ref["content_hash"], identity, request.encode(), raw)
            doc["source"]["source_version"] = "canonical-v1"
            doc["obtained_content_hash"] = doc["checks"]["exact_quote"]["source_artifact_hash"] = ref["content_hash"]
            if canonical_producer is not None:
                doc["extraction"].update(method="canonical_bytes", produced_by_invocation_id="inv_research01")
        if acquisition_producer is not None:
            from gen2.tests.extraction_receipt_fixtures import seed, attach
            seed(self, verifier, acquisition_producer)
            attach(self, doc)
        # Authenticate retained assessments before the receipt transaction.
        seed_checks(self, doc)
        own = {**empty_outcome("inv_verify01", "interim_transition"), "verification_receipts": [doc]}
        assert self.router.commit_outcome(self.envelope(verifier, "op_verify0001", own))["status"] == "committed"
        return verifier

    def promote_revision_one(self, grant: dict, op: str) -> dict:
        outcome = {**empty_outcome(grant["invocation_id"], "interim_transition"), "claim_promotions": [{"claim_id": "clm_00000001", "revision": 1}]}
        before = self.state()
        response = self.router.commit_outcome(self.envelope(grant, op, outcome))
        self.assertEqual((response["status"], response.get("reason")), ("rejected", "amendment_pending"), response)
        self.assertIn("contract-admitted work adopts it as a new revision", response.get("detail"))
        self.assert_audited_state(before, 1)
        return response

    def adopt(self, grant: dict) -> None:
        text = self.artifact(b"a load-bearing claim")
        adopt = {**empty_outcome(grant["invocation_id"], "interim_transition"),
                 "claims": [{"claim_id": "clm_00000001", "revision": 2, "text_ref": text, "load_bearing": False, "required_access_tier": None}],
                 "claim_promotions": [{"claim_id": "clm_00000001", "revision": 2}]}
        self.assertEqual(self.router.commit_outcome(self.envelope(grant, "op_adopt000001", adopt, refs=[text]))["status"], "committed")
        self.assertEqual(self.rows("SELECT revision, status FROM claims ORDER BY revision"), [(1, "provisional"), (2, "accepted_support")])

    def refused_command(self, method, request: dict, reason: str, detail: str | None = None) -> None:
        before = self.state()
        out = getattr(self.router, method)(request)
        self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
        if detail is not None:
            self.assertIn(detail, out.get("detail", ""))
        self.assertEqual(self.state(), before)


# -- Retained acquisition and receipt worlds ----------------------------------


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


REQUEST = b'{"lane":"crossref","page":1,"request":{"query":"fixture","request_type":"find"}}'


RAW = b'{"request_type":"find","observation":{"captured":true,"call_ref":101,"invocation_id":"inv_capture001","attempt":1},"lanes":[{"source":"crossref","coverage":"searched_ok","completeness":"complete","retrieved":["doi:10.1/fixture"]}],"records":[{"identity":"doi:10.1/fixture","kind":"article","title":"Fixture","abstract":"An abstract"}]}'


STAMP = "2026-09-27T10:00:00Z"


def raw_acquisition(case, **changes):
    row = {"topic_id": TOPIC, "work_id": case.work, "source_version": "v1", "content_hash": digest(case.raw),
        "observation_id": "obs_capture001", "event_id": "rev_capture001", "gateway_call_ref": "gw-call:101",
        "acquired_by_invocation_id": case.ACQUIRER, "attempt": 1, "lane": "crossref", "request_type": "find",
        "provider_record_id": "doi:10.1/fixture", "retrieved_at": STAMP, "verifier_invocation_id": "inv_verify0001",
        "request_identity": digest(REQUEST), "request_bytes": REQUEST, "response_bytes": case.raw, "admitted_at": STAMP, **changes}
    case.x(f"INSERT INTO source_acquisitions ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values())


class AcquisitionCase(Workflow):
    ACQUIRER = "inv_capture001"
    EVENT_ID = "rev_capture001"
    RESPONSE = RAW
    COVERAGE = "searched_ok"

    def setUp(self):
        super().setUp()
        self.approved()
        self.producer = self.started("inv_capture001")
        self.acquirer = self.producer if self.ACQUIRER == "inv_capture001" else self.started(self.ACQUIRER, "checkpoint")
        self.raw = self.RESPONSE.replace(b"inv_capture001", self.ACQUIRER.encode())
        obs = {"observation_id": "obs_capture001", "request": json.loads(REQUEST), "request_identity": digest(REQUEST),
            "attempt": 1, "lane": "crossref", "obligation_ids": ["O-1"], "started_at": STAMP, "ended_at": STAMP,
            "coverage_state": self.COVERAGE, "result_count": 1, "completeness": "complete", "error_class": None,
            "capability_fact_id": None, "policy_version": "pol-1", "cost_units": None, "gateway_call_ref": "gw-call:101",
            "page_outcome": "end_unknown", "continuation": None}
        event = {"event_id": self.EVENT_ID, "provider_record_id": "doi:10.1/fixture", "rank": 1, "captured_at": STAMP}
        self.assertEqual(self.router.record_observation({**{k: self.acquirer[k] for k in ("capability_id", "invocation_id")},
            "observation": obs, "retrieval_events": [event]})["status"], "recorded")
        self.work = self.register(self.acquirer, [("doi", "10.1/fixture", [self.EVENT_ID])])["works"][0]["work_id"]
        self.source = self.artifact(self.raw, "application/json")
        payload = {**empty_outcome("inv_capture001", "interim_transition"),
            "source_artifacts": [{"work_id": self.work, "source_version": "v1", "artifact_ref": self.source}]}
        self.assertEqual(self.router.commit_outcome(self.envelope(self.producer, "op_capture001", payload, refs=[self.source]))["status"], "committed")
        self.verifier = self.started("inv_verify0001", "verification")
        self.exchange = RetainedExchange(TOPIC, self.ACQUIRER, 1, "gw-call:101", REQUEST, self.raw)
        self.reads, self.after_read = [], lambda: None
        self.router = self.make_router(gateway_captures=self)

    def read(self, **key):
        self.reads.append((key, self.db.in_transaction))
        self.after_read()
        return self.exchange

    def request(self, **changes):
        return {**{k: self.verifier[k] for k in ("capability_id", "invocation_id")},
            "work_id": self.work, "source_version": "v1", "event_id": self.EVENT_ID, **changes}

    def refuse(self, detail, reason="reaccess_invalid", **changes):
        before = self.state(exclude=())
        out = self.router.admit_reaccess(self.request(**changes))
        self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
        self.assertIn(detail, out.get("detail", ""))
        self.assertEqual(self.state(exclude=()), before)


class ReceiptCase(AcquisitionCase):
    def setUp(self):
        super().setUp()
        text = self.artifact(b"Fixture claim")
        payload = {**empty_outcome("inv_capture001", "interim_transition"),
            "claims": [{"claim_id": "clm_fixture001", "revision": 1, "text_ref": text,
                "load_bearing": False, "required_access_tier": None}]}
        self.assertEqual(self.router.commit_outcome(self.envelope(self.producer, "op_claim001", payload, refs=[text]))["status"], "committed")

    def document(self):
        return {"receipt_version": "verification-receipt/1", "verification_receipt_id": "ver_fixture001", "topic_id": TOPIC,
            "claim": {"claim_id": "clm_fixture001", "claim_revision": 1}, "source": {"work_id": self.work, "source_version": "v1"},
            "cited_spans": [{"start": 0, "end": 5, "locator": {"kind": "section", "value": "Abstract"}}],
            "obtained_content_hash": self.source["content_hash"], "access_tier": "abstract",
            "requested_for": {"use": "sampled", "required_access_tier": "abstract"},
            "acquisition": {"route": "gateway:crossref", "retrieved_at": STAMP, "gateway_call_ref": "gw-call:101", "cache_reuse": True},
            "extraction": {"method": "canonical_bytes", "extractor": "canonical/1", "produced_by_invocation_id": self.ACQUIRER, "validation_ref": None},
            "producer_invocation_id": "inv_capture001", "verifier_invocation_id": "inv_verify0001", "verifier_capability_id": self.verifier["capability_id"],
            "quote_check_id": None, "checks": {"exact_quote": {"status": "not_applicable", "normalization_version": "none/1", "source_artifact_hash": self.source["content_hash"]},
                "numeric_units": "not_applicable", "denominators": "not_applicable", "negation": "checked_ok", "qualifications": "checked_ok"},
            "adjudication": None, "verdict": "supports", "verified_at": STAMP}

    def send(self, doc=None, op="op_verify001"):
        payload = {**empty_outcome(self.verifier['invocation_id'], "interim_transition"), "verification_receipts": [doc or self.document()]}
        self.env = self.envelope(self.verifier, op, payload)
        return self.router.commit_outcome(self.env)

    def rejected(self, doc=None):
        before = self.state()
        out = self.send(doc)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.assertIn("must consume its admitted acquisition", out["detail"])
        self.assert_audited_state(before, 1)

    def admit(self):
        self.assertEqual(self.router.admit_reaccess(self.request())["status"], "admitted")
        from gen2.tests.extraction_receipt_fixtures import seed
        seed(self)


class AttributedReceiptCase(ReceiptCase):
    """Attributed current receipts; base ReceiptCase isolates format/refusal probes."""
    def document(self):
        from gen2.tests.detailed_receipt_fixtures import attach_checks
        doc = super().document()
        doc.update(verifier_invocation_id=self.verifier['invocation_id'],
            verifier_capability_id=self.verifier['capability_id'])
        attach_checks(self, doc)
        return doc

    def admit(self):
        # Seed attributed assessments before snapshots.
        from gen2.tests.detailed_receipt_fixtures import seed_checks
        super().admit()
        doc = ReceiptCase.document(self)
        doc.update(verifier_invocation_id=self.verifier['invocation_id'],
            verifier_capability_id=self.verifier['capability_id'])
        seed_checks(self, doc)

    def rejected(self, doc=None):
        # Explicit /1 isolation of acquisition refusals, never a positive basis.
        from gen2.tests.detailed_receipt_fixtures import historical_receipt
        doc = doc or ReceiptCase.document(self)
        historical_receipt(doc)
        super().rejected(doc)


class RecordCase(AcquisitionCase):
    RAW = False

    def setUp(self):
        super().setUp()
        self.assertEqual(self.router.register_extractor_registry({"registry_version": 1, "operator_id": "fixture-operator",
            "reason": "approve fixture tools", "tools": [{"extractor_identity": "tool-a", "family": "family-a"},
                {"extractor_identity": "tool-b", "family": "family-b"}]})["status"], "registered")
        self.assertEqual(self.router.admit_reaccess(self.request())["status"], "admitted")
        self.extractor = self.started("inv_extract001", "checkpoint")
        self.output = self.artifact(b"independent extraction output")
        self.evidence = self.artifact(b"validator comparison rationale")
        for grant in (self.extractor, self.verifier):
            payload = empty_outcome(grant["invocation_id"], "interim_transition")
            self.assertEqual(self.router.commit_outcome(self.envelope(grant, "op_setup_" + grant["invocation_id"],
                payload, refs=[self.output, self.evidence]))["status"], "committed")

    def extraction(self, identity="target", **changes):
        return {**dict(extraction_id=identity, work_id=self.work, source_version="v1", event_id=self.EVENT_ID,
            verifier_invocation_id=self.verifier["invocation_id"], extractor_identity="tool-a" if identity == "target" else "tool-b",
            extractor_version="1", extractor_registry_version=1, output_ref=self.output, supported_tier="abstract"), **changes}

    def validation(self, **changes):
        return {"validation_id": "validation-1", "target_extraction_id": "target", "validator_extraction_id": "independent",
            "method": "independent_extraction", "policy_version": 1, "outcome": "succeeded", "comparison": "byte_equal",
            "comparison_evidence_ref": self.evidence, **changes}

    def foreign_ref(self, text):
        ref = self.artifact(text)
        self.to_scoping(OTHER)
        other = self.started("inv_other001", tid=OTHER)
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, ?, ?, ?)",
            ref["content_hash"], ref["size_bytes"], ref["media_type"], STAMP)
        self.x("INSERT INTO artifact_topics VALUES (?, ?, ?, ?)", ref["content_hash"], OTHER, other["invocation_id"], STAMP)
        return ref

    def send(self, grant=None, op="op_record0001", **sections):
        grant = grant or self.extractor
        payload = {**empty_outcome(grant["invocation_id"], "interim_transition"), **sections}
        return self.router.commit_outcome(self.envelope(grant, op, payload))

    def basis(self, target_grant=None, target=None, independent=None):
        self.assertEqual(self.send(target_grant, source_extractions=[target or self.extraction()])["status"], "committed")
        self.assertEqual(self.send(self.verifier, "op_independent1", source_extractions=[independent or self.extraction("independent")])["status"], "committed")

    def refuse(self, **sections):
        before = self.state()
        grant = self.verifier if "extraction_validations" in sections else self.extractor
        out = self.send(grant, "op_refused001", **sections)
        self.assertEqual(out["status"], "rejected", out)
        if self.RAW:
            self.assertEqual(self.state(exclude=()), before)
        else:
            self.assert_audited_state(before, 1)


IDENTITY = "doi:10.1/fixture"


FULL = {"identity": IDENTITY, "kind": "full_text", "text": "Complete fixture text"}


@contextmanager
def fixture(record, coverage="searched_ok", others=(), *, detailed=False):
    case = AttributedReceiptCase() if detailed else ReceiptCase()
    response = json.loads(RAW)
    response["records"] = [record, *others]
    response["lanes"][0]["coverage"] = coverage
    case.RESPONSE = json.dumps(response).encode()
    case.COVERAGE = coverage
    case.setUp()
    try:
        case.admit()
        yield case
    finally:
        case.tearDown()


# Current positive owners opt into admitted assessments; base fixtures isolate probes.
attributed_fixture = partial(fixture, detailed=True)


def content_document(case, tier, verdict="supports"):
    doc = case.document()
    doc["access_tier"] = tier
    doc["requested_for"]["required_access_tier"] = tier
    doc["verdict"] = verdict
    return doc


def send(case, doc):
    case.env = case.envelope(case.verifier, "op_verify001",
        {**empty_outcome(case.verifier["invocation_id"], "interim_transition"), "verification_receipts": [doc]})
    return case.router.commit_outcome(case.env)


def extraction_document(case, method, *, detailed=True):
    from gen2.tests.detailed_receipt_fixtures import attach_checks
    doc = ReceiptCase.document(case)
    doc['access_tier'] = doc['requested_for']['required_access_tier'] = 'bibliographic'
    doc["extraction"].update(method=method,
        produced_by_invocation_id=case.verifier["invocation_id"] if method == "verifier_extraction" else case.ACQUIRER,
        validation_ref="validation_unrecorded" if method == "validated_extraction" else None)
    doc["verifier_invocation_id"] = case.verifier["invocation_id"]
    doc["verifier_capability_id"] = case.verifier["capability_id"]
    from gen2.tests.extraction_receipt_fixtures import attach
    attach(case, doc)
    if detailed and isinstance(case, AttributedReceiptCase):
        attach_checks(case, doc)
    return doc


def load_claim(case, tier):
    ref = case.artifact(b"Independent load-bearing claim")
    out = case.router.commit_outcome(case.envelope(case.producer, "op_loadclaim1",
        {**empty_outcome("inv_capture001", "interim_transition"), "claims": [{"claim_id": "clm_loadbear1", "revision": 1,
            "text_ref": ref, "load_bearing": True, "required_access_tier": tier}]}, refs=[ref]))
    case.assertEqual(out["status"], "committed", out)


def support_document(case, method, tier):
    from gen2.tests.detailed_receipt_fixtures import attach_checks
    doc = content_document(case, tier)
    doc["claim"]["claim_id"] = "clm_loadbear1"
    doc["requested_for"]["use"] = "load_bearing"
    doc["extraction"].update(method=method)
    if method == "verifier_extraction":
        doc["extraction"]["produced_by_invocation_id"] = "inv_verify0001"
    if method == "validated_extraction":
        doc["extraction"]["validation_ref"] = "validation_unrecorded"
    from gen2.tests.extraction_receipt_fixtures import attach
    attach(case, doc)
    if isinstance(case, AttributedReceiptCase):
        attach_checks(case, doc)
    return doc


@contextmanager
def bound_fixture(record, tier='full_text'):
    from gen2.tests.detailed_receipt_fixtures import seed_checks
    with attributed_fixture(record) as case:
        load_claim(case, tier)
        doc = ReceiptCase.document(case)
        doc['claim']['claim_id'] = 'clm_loadbear1'
        # Ordinary extraction outputs equal these canonical bytes. The
        # distinct-output regression separately checks artifact selection.
        seed_checks(case, doc)
        yield case


EXTRACTION_METHODS = ("verifier_extraction", "validated_extraction")


TABLE = {"start": 0, "end": 5, "locator": {"kind": "table", "value": "Table 1"}}


PAGE = {"start": 5, "end": 9, "locator": {"kind": "page", "value": "2"}}


METHODS = ("canonical_bytes", "verifier_extraction", "validated_extraction")


def seed_spans(case, bindings=((TABLE,), (PAGE,), (PAGE, TABLE))):
    from gen2.tests.detailed_receipt_fixtures import seed_checks
    for spans in bindings:
        doc = ReceiptCase.document(case)
        doc['cited_spans'] = list(spans)
        # Byte-equal ordinary outputs share this exact binding; no
        # source/target/validator discrimination is claimed here.
        seed_checks(case, doc)


@contextmanager
def span_fixture(record, coverage='searched_ok', others=(), *, bindings=((TABLE,), (PAGE,), (PAGE, TABLE))):
    with attributed_fixture(record, coverage, others) as case:
        seed_spans(case, bindings)
        yield case


def document(case, method, tier, verdict="supports", spans=(TABLE,), *, detailed=True):
    from gen2.tests.detailed_receipt_fixtures import attach_checks
    doc = extraction_document(case, method)
    if method == "verifier_extraction":
        doc["extraction"]["produced_by_invocation_id"] = case.verifier["invocation_id"]
    doc.update(access_tier=tier, verdict=verdict, cited_spans=list(spans))
    doc["requested_for"]["required_access_tier"] = tier
    if detailed:
        attach_checks(case, doc)
    return doc


class CheckCase(AcquisitionCase):
    RAW = False

    def setUp(self):
        super().setUp()
        self.assertEqual(self.capture(self.producer, 'op_claimcheck1')['status'], 'committed')
        self.assertEqual(self.capture(self.verifier, 'op_setupcheck1', claim=None)['status'], 'committed')

    def record(self, **changes):
        span = {'start': 0, 'end': 10, 'locator': {'kind': 'paragraph', 'value': '1'}}
        report = dict(claim_id='clm_00000001', claim_revision=1, work_id=self.work, source_version='v1',
            source_artifact_hash=self.source['content_hash'], examined_artifact_ref=self.source,
            cited_spans=[span], context_spans=[{**span, 'end': 20}], kind='numeric_units', outcome='succeeded',
            method='attributed-assessment/1', assessment='Verifier assessment of this claim and source.',
            context_examined='No quantities; units interpreted in the retained surrounding text.', applicability_reason='')
        report.update(changes)
        ref = self.artifact(json.dumps(report).encode(), 'application/json')
        return dict(check_id='check-1', assessment=report, evidence_ref=ref)

    def env(self, record, grant=None, op='op_detailcheck1'):
        grant = grant or self.verifier
        payload = {**empty_outcome(grant['invocation_id'], 'interim_transition'), 'detailed_check_records': [record]}
        return self.envelope(grant, op, payload, refs=[record['evidence_ref']] if record['evidence_ref'] else [])

    def send(self, record, grant=None, op='op_detailcheck1'):
        return self.router.commit_outcome(self.env(record, grant, op))

    def refuse(self, record):
        before = self.state(exclude=())
        out = self.send(record)
        self.assertEqual(out['status'], 'rejected', out)
        if self.RAW:
            self.assertEqual(self.state(exclude=()), before)
        else:
            self.assert_audited_state(before, 1)
        return out


KINDS = ('numeric_units', 'denominators', 'negation', 'qualifications')


OUTCOMES = ('succeeded', 'failed', 'not_applicable', 'not_checked', 'unavailable')


class OwnCases:

    def setUp(self):
        from gen2.tests.detailed_receipt_fixtures import seed_checks
        context = fixture(FULL)
        self.case = context.__enter__()
        self.doc = extraction_document(self.case, 'verifier_extraction')
        seed_checks(self.case, self.doc)
        self.addCleanup(context.__exit__, None, None, None)
        self.doc['access_tier'] = self.doc['requested_for']['required_access_tier'] = 'bibliographic'

    def submit(self):
        return send(self.case, self.doc)

    def refuse(self):
        # Historical /1 operands isolate the existing extraction predicate.
        from gen2.tests.detailed_receipt_fixtures import historical_receipt, historical_admission
        historical_receipt(self.doc)
        before = self.case.state(exclude=())
        with historical_admission(self.case):
            out = self.submit()
        self.assertEqual(out['status'], 'rejected', out)
        self.assertEqual(out.get('reason'), 'payload_invalid', out)
        self.assertIn('receipt needs its verifier durable extraction', out['detail'])
        self.case.assert_audited_state(before, 1)
        self.assertEqual(self.case.rows('PRAGMA foreign_key_check'), [])

    def clone(self, table, changes, where=''):
        cur = self.case.db.execute('SELECT * FROM ' + table + (' WHERE ' + where if where else '') + ' LIMIT 1')
        row = {**dict(zip([d[0] for d in cur.description], cur.fetchone())), **changes}
        self.case.x(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values())

    def foreign(self, selector):
        c = self.case
        inv = self.doc['verifier_invocation_id']; version = 'v1'; work = c.work; event = c.EVENT_ID
        if selector == 'version':
            version = 'v2'
            self.clone('source_artifacts', {'source_version': version})
            self.clone('source_acquisitions', {'source_version': version})
        elif selector == 'verifier':
            self.assertEqual(c.finish(c.verifier, 'op_oldverify1')['status'], 'committed')
            c.verifier = c.started('inv_foreign01', 'verification')
            c.admit()
            self.doc = extraction_document(c, 'verifier_extraction')
            op = c.value('SELECT operation_id FROM operation_receipts WHERE invocation_id = ?', c.verifier['invocation_id'])
            self.clone('source_extractions', dict(extraction_id='foreign-basis', extracting_invocation_id=c.verifier['invocation_id'],
                recorded_by_operation_id=op), "verifier_invocation_id = '" + inv + "'")
            self.doc['extraction']['extraction_id'] = 'foreign-basis'
            return
        else:
            observation = 'obs_foreign01'; event = 'rev_foreign01'
            changes = dict(observation_id=observation, attempt=2)
            if selector == 'call': changes['gateway_call_ref'] = 'gw-call:102'
            if selector == 'route':
                request = json.loads(c.value('SELECT request FROM search_observations'))
                request['lane'] = 'core'
                changes.update(lane='core', request=json.dumps(request))
            self.clone('search_observations', changes)
            event_changes = dict(event_id=event, observation_id=observation)
            if selector == 'time': event_changes['captured_at'] = '2026-09-28T10:00:00Z'
            if selector == 'work':
                work = 'wrk_foreign01'
                self.clone('works', dict(work_id=work, identity_value='10.1/foreign'))
                event_changes['provider_record_id'] = 'other-record'
            self.clone('retrieval_events', event_changes)
            self.clone('record_work_links', dict(event_id=event, work_id=work))
            if selector == 'work': self.clone('source_artifacts', {'work_id': work})
            obs = dict(zip([d[0] for d in c.db.execute('SELECT * FROM search_observations LIMIT 0').description],
                c.rows('SELECT * FROM search_observations WHERE observation_id = ?', observation)[0]))
            self.clone('source_acquisitions', dict(event_id=event, work_id=work, observation_id=observation, attempt=2,
                gateway_call_ref=obs['gateway_call_ref'], lane=obs['lane'], request_bytes=obs['request'].encode(),
                provider_record_id=event_changes.get('provider_record_id', 'doi:10.1/fixture'),
                retrieved_at=event_changes.get('captured_at', self.doc['acquisition']['retrieved_at'])))
        self.clone('source_extractions', dict(extraction_id='foreign-basis', work_id=work, source_version=version,
            event_id=event, verifier_invocation_id=inv, supported_tier='bibliographic'))
        self.doc['extraction']['extraction_id'] = 'foreign-basis'

    def test_control(self):
        self.assertEqual(self.submit()['status'], 'committed')
        self.assertEqual(json.loads(self.case.value('SELECT receipt FROM verification_receipts')), self.doc)
        self.assertEqual(self.case.rows('PRAGMA foreign_key_check'), [])

    def test_missing(self):
        del self.doc['extraction']['extraction_id']
        self.refuse()

    def test_invented(self):
        self.doc['extraction']['extraction_id'] = 'invented'
        self.refuse()

    def test_tool(self):
        self.doc['extraction']['extractor'] = 'Receipt-tool'
        self.refuse()

    def test_unpinned(self):
        self.case.x('DROP TRIGGER source_extractions_immutable_u')
        self.case.x('UPDATE source_extractions SET extractor_registry_version = NULL')
        self.refuse()

    def test_tier(self):
        self.case.x('DROP TRIGGER source_extractions_immutable_u')
        self.case.x("UPDATE source_extractions SET supported_tier = 'bibliographic'")
        self.doc['access_tier'] = self.doc['requested_for']['required_access_tier'] = 'abstract'
        self.refuse()

    def test_extractor(self):
        op = self.case.value('SELECT operation_id FROM operation_receipts WHERE invocation_id = ?', self.case.ACQUIRER)
        self.clone('source_extractions', dict(extraction_id='foreign-basis', extracting_invocation_id=self.case.ACQUIRER, recorded_by_operation_id=op))
        self.doc['extraction']['extraction_id'] = 'foreign-basis'
        self.refuse()

    def test_version(self): self.foreign('version'); self.refuse()
    def test_work(self): self.foreign('work'); self.refuse()
    def test_verifier(self): self.foreign('verifier'); self.refuse()
    def test_call(self): self.foreign('call'); self.refuse()
    def test_time(self): self.foreign('time'); self.refuse()
    def test_route(self): self.foreign('route'); self.refuse()
