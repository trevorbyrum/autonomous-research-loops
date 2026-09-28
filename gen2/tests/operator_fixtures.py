"""Shared fixtures for the operator-surface tests (not collected as tests).

An OperatorTestCase holds a durable store, the real protected spool and a
jobs directory under a temporary directory, and the engine
(gen2/app/engine.py) serving them: its station opened on its own owner
thread, its listener on an ephemeral loopback port. Every command and status
read in these tests goes over real HTTP to that listener (http.client), never
through an in-process call to the service.

The world the router has no path for (topics, first brief versions, first
contract drafts) is written with raw SQL, as in router_fixtures; the world a
supervisor would make (claims, lifecycle facts, commits) is made by a second
router over the same store in the test's own thread — the supervisor's
in-process ControlBackend calls, which the operator surface does not carry.
Both routers share the test's clock and id source. Read-backs are raw SQL on
the test's own connection, never the router's or the service's readers.

Expected outcomes are written by hand in each test.
"""
from __future__ import annotations

import http.client
import json
import os
import select
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from gen2.app.engine import Engine
from gen2.app.station import open_station
from gen2.operator.auth import Credentials
from gen2.store import api
from gen2.supervisor.spool import Spool
from gen2.tests import children
from gen2.tests import router_fixtures as rf
from gen2.tests import store_fixtures

OPERATOR_TOKEN = "op-token-alice-0123456789abcdef"
OTHER_OPERATOR_TOKEN = "op-token-bob-0123456789abcdef"
EXPORTER_TOKEN = "exporter-token-0123456789abcdef"
TOKENS = (OPERATOR_TOKEN, OTHER_OPERATOR_TOKEN, EXPORTER_TOKEN)


def credentials(operators: dict | None = None, exporter: str | None = EXPORTER_TOKEN) -> Credentials:
    return Credentials({"alice": OPERATOR_TOKEN, "bob": OTHER_OPERATOR_TOKEN} if operators is None else operators, exporter)


class StagingSpool:
    """The real spool, with the fake spool's `put` the router fixtures stage
    through: bytes staged for `topic` (TOPIC unless set) unless a topic is named."""

    def __init__(self, spool: Spool) -> None:
        self.real = spool
        self.topic = rf.TOPIC

    def put(self, raw: bytes, label: str | None = None, media_type: str = "application/json", topic: str | None = None) -> str:
        assert label is None, "the real spool names bytes by their digest"
        return self.real.stage(topic or self.topic, raw, media_type)["content_hash"]

    def read(self, content_hash: str, *, topic_id: str) -> bytes | None:
        return self.real.read(content_hash, topic_id=topic_id)

    def media_type(self, content_hash: str, *, topic_id: str) -> str | None:
        return self.real.media_type(content_hash, topic_id=topic_id)


class OperatorTestCase(rf.RouterTestCase):
    def setUp(self) -> None:  # not the in-memory setUp: a durable store, the real spool, the engine
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = api.open_store(self.root / "store.sqlite3", create=True)
        self.db = sqlite3.connect(self.root / "store.sqlite3", isolation_level=None)
        self.db.executescript(store_fixtures.CONNECTION_TEXT)
        self.spool = StagingSpool(Spool(self.root / "spool"))
        self.clock, self.ids, self.faults = rf.Clock(), rf.Ids(), {}
        self.router = self.make_router()
        self.seed()
        self.logs: list[str] = []
        self.engine = self.start_engine()

    def tearDown(self) -> None:
        if self.engine is not None:
            self.engine.close()
        self.store.close()
        self.db.close()
        self._tmp.cleanup()

    def start_engine(self, creds: Credentials | None = None, **station) -> Engine:
        """The engine over this test's state directory, as a restart finds it:
        nothing mounted, so the router restores the active bundle."""
        return Engine(lambda: open_station(self.root, station_id="station-1", host_id="host-1", clock=self.clock,
                                           router_options={"new_id": self.ids}, **station),
                      creds or credentials(), log=self.logs.append)

    def restart(self, creds: Credentials | None = None) -> None:
        self.engine.close()
        self.engine = None
        self.engine = self.start_engine(creds)

    # -- HTTP ------------------------------------------------------------------
    def http(self, method: str, path: str, body=None, *, token: str | None = OPERATOR_TOKEN, raw: bytes | None = None,
             headers: dict | None = None) -> tuple[int, object, dict]:
        """One request to the engine's listener: (status, the JSON reply, the
        response headers)."""
        host, port = self.engine.address
        connection = http.client.HTTPConnection(host, port, timeout=30)
        sent = {} if headers is None else dict(headers)
        if token is not None:
            sent["Authorization"] = f"Bearer {token}"
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
        try:
            connection.request(method, path, body=data, headers=sent)
            response = connection.getresponse()
            text = response.read()
            return response.status, json.loads(text) if text else None, {k.lower(): v for k, v in response.getheaders()}
        finally:
            connection.close()

    def command(self, operation: str, body, *, token: str | None = OPERATOR_TOKEN) -> tuple[int, object]:
        code, reply, _ = self.http("POST", f"/v1/commands/{operation}", body, token=token)
        return code, reply

    def status_doc(self, topic: str | None = None, *, token: str = OPERATOR_TOKEN) -> dict:
        code, reply, _ = self.http("GET", "/v1/status" + ("" if topic is None else f"?topic={topic}"), token=token)
        assert code == 200, (code, reply)
        return reply

    def topic_status(self, tid: str = rf.TOPIC) -> dict:
        return next(t for t in self.status_doc()["topics"] if t["topic_id"] == tid)

    # -- world ---------------------------------------------------------------
    def late_brief(self, tid: str, brief_id: str, owner: str, deadline: str = "2026-09-27T09:30:00Z") -> None:
        """A brief's first version (raw SQL: intake's, Phase 2) whose review
        deadline is already past on the test's clock."""
        doc = self.brief_document(tid, 1, brief_id=brief_id)
        self.x("INSERT INTO intake_briefs (topic_id, brief_id, version, parent_version, content_hash, document, owner_operator_id, status, created_at, review_deadline) "
               "VALUES (?, ?, 1, NULL, ?, ?, ?, 'awaiting_confirmation', ?, ?)", tid, brief_id, doc["content_hash"], json.dumps(doc), owner, doc["created_at"], deadline)

    def decision(self, did: str, kind: str, subject: dict, tid: str | None = rf.TOPIC, disposition: str = "approved", payload=None) -> dict:
        """An operator decision's body as the operator sends it: no operator_id,
        which the surface supplies from the token."""
        return {"decision_id": did, "topic_id": tid, "kind": kind, "disposition": disposition,
                "subject": {"kind": subject.get("kind"), "ref": subject.get("ref", tid), "revision": subject.get("revision"), "hash": subject.get("hash")},
                "decided_at": "2026-09-27T09:45:00Z", "notes": None, "payload": payload}

    def ended(self, grant: dict, failure_class: str = "exit_nonzero") -> None:
        """Record, as the supervisor would, that running work failed with its
        execution record staged."""
        self.spool.topic = grant["topic_id"]
        try:
            evidence = self.evidence(grant, findings=(failure_class,))
        finally:
            self.spool.topic = rf.TOPIC
        out = self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "to_state": "failed",
                                             "failure_class": failure_class, "end_evidence_ref": evidence})
        assert out["status"] == "recorded", out


class EngineProcesses:
    """For an OperatorTestCase whose engines are processes of their own
    (`python -m gen2.app.engine`, or a child module serving it), started
    through children.py so each imports the code tree under test, with the
    deployment contract's environment names; and the CLI as its own process.

    Every engine process's whole output is collected when it is stopped
    (stop()) — its stderr log, and every byte of its stdout: the line read
    at its start to learn its address, and what followed — and every
    assertion about that output is made after the collection: each started
    engine stopped and collected, none empty, each saying what it should
    (Astra 1e review finding 7: a check run before the collection passed on
    nothing; Astra 1e-repair re-review finding 3: the line read at the start
    was left out of it)."""
    ENV = {"GEN2_SECRETS": "env", "GEN2_OPERATOR_LISTEN": "127.0.0.1:0", "GEN2_OPERATOR_TOKENS": f"alice={OPERATOR_TOKEN},bob={OTHER_OPERATOR_TOKEN}",
           "GEN2_SECRET_EXPORTER_TOKEN": EXPORTER_TOKEN}

    def setUp(self) -> None:
        super().setUp()
        self.started = 0  # engine processes started: each writes its own log
        self.running: dict[subprocess.Popen, tuple] = {}  # started and not yet stopped: the process -> (its log, the stdout read from it so far)
        self.engines: list[str] = []  # each stopped engine's whole output, in the order they stopped
        self.clis: list[str] = []  # each CLI run's stdout and stderr

    def spawn(self, args: list[str] | None = None, **env) -> tuple[subprocess.Popen, str | None]:
        """Start an engine process — `python -m gen2.app.engine` over this
        test's root, or `args` — and read its first stdout line; (the
        process, its URL), or (the process, None) if that line names no
        address. The line read is kept as the start of its stdout."""
        self.started += 1
        log = open(self.root / f"engine-{self.started}.log", "w+")
        environ = {k: v for k, v in {**os.environ, **self.ENV, **env}.items() if v is not None}
        process = children.popen(args or ["-m", "gen2.app.engine", "--root", str(self.root), "--station-id", "station-1", "--host-id", "host-1"],
                                 env=environ, stdout=subprocess.PIPE, stderr=log, text=True)
        read: list[str] = []
        self.running[process] = (log, read)
        self.addCleanup(self.stop, process)  # a test failing before it stops an engine
        ready, _, _ = select.select([process.stdout], [], [], 30)
        line = process.stdout.readline() if ready else ""
        read.append(line)
        return process, (f"http://{line.split()[-1]}" if line.startswith("listening on ") else None)

    def stop(self, process: subprocess.Popen) -> str:
        """End the engine — SIGTERM ends it where it stands; one that ended
        by itself is reaped — and collect its whole output: its log, then
        its stdout from its first byte. Once per process."""
        log, read = self.running.pop(process, (None, None))
        if log is None:
            return ""
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=30)
        with log:
            log.seek(0)
            output = log.read() + "".join(read) + (process.stdout.read() or "")
        process.stdout.close()
        self.engines.append(output)
        return output

    def cli(self, url: str, token: str | None, *args: str, body: dict | None = None) -> tuple[int, object]:
        environ = {**os.environ, "GEN2_OPERATOR_URL": url, "GEN2_OPERATOR_TOKEN": token or ""}
        done = children.python(["-m", "gen2.app.cli", *args], env=environ, input=None if body is None else json.dumps(body),
                               capture_output=True, text=True, timeout=60)
        self.clis.append(done.stdout + done.stderr)
        return done.returncode, json.loads(done.stdout) if done.stdout.strip() else None

    def assert_collected(self, count: int, says: str) -> None:
        """Every engine this test started was stopped and its output
        collected — `count` of them, none empty — and each says `says`."""
        self.assertEqual((self.started, len(self.engines), self.running), (count, count, {}))
        for output in self.engines:
            self.assertIn(says, output)

    def assert_no_token_in_any_output(self, *extra: str) -> None:
        self.assertTrue(self.engines and all(self.engines), "no engine output was collected to check")
        for output in (*self.engines, *self.clis):
            for token in (*TOKENS, *extra):
                self.assertNotIn(token, output)


# The world CommandWorld builds, by name: each operator command has a body the
# operator's token gets applied, in this order (the brief decision before the
# next brief version, which would otherwise supersede what it confirms).
RUNNING, FAILED, CHECKPOINT = "inv_running0001", "inv_discfail01", "inv_checkpt001"


class CommandWorld(OperatorTestCase):
    """TOPIC under an approved contract (revision 2, test_router_amendments'
    ContractWorld) with a running research pass, a failed discovery and a
    running checkpoint that committed export manifest man_gen00000001; OTHER
    at intake with brief-1 v1 awaiting confirmation and brief-2 v1 past its
    review deadline. `bodies()` gives each command a request the operator's
    token gets applied, and the exporter's token its receipt."""

    def setUp(self) -> None:
        super().setUp()
        from gen2.tests import test_router_amendments as amend  # the module, so its tests are not collected here
        self.amend = amend
        amend.ContractWorld.build_world(self)
        self.run_grant = self.started(RUNNING)
        self.ended(self.started(FAILED, kind="discovery"))
        self.checkpoint = self.started(CHECKPOINT, kind="checkpoint")
        self.export(self.checkpoint, 1)
        self.brief(rf.OTHER)
        self.late_brief(rf.OTHER, "brief-2", "bob")

    def store_draft(self, doc: dict) -> None:
        self.amend.ContractWorld.store_draft(self, doc)

    def bodies(self) -> dict[str, dict]:
        other_brief = self.value("SELECT content_hash FROM intake_briefs WHERE topic_id = ? AND brief_id = 'brief-1' AND version = 1", rf.OTHER)
        return {
            "apply_operator_decision": self.decision("opd_brief_other", "brief_confirmation",
                                                     {"kind": "intake_brief", "ref": "brief-1", "revision": 1, "hash": other_brief}, rf.OTHER),
            "request_cancel": {"invocation_id": RUNNING, "reason": "the operator stops this pass"},
            "requeue": {"invocation_id": FAILED, "reason": "diagnosed: a transient fault"},
            "close_brief": {"topic_id": rf.TOPIC, "brief_id": "brief-1", "version": 1, "closure": "archived", "reason": "the contract is approved"},
            "activate_config_bundle": {**rf.BUNDLE, "version": 2},
            "version_brief": {"document": self.brief_document(rf.OTHER, 2), "owner_operator_id": "bob", "review_deadline": "2026-10-05T00:00:00Z"},
            "mark_brief_overdue": {"topic_id": rf.OTHER, "brief_id": "brief-2", "version": 1},
            "propose_amendment": {"document": self.amend.contract_doc(3, 2, edit=self.amend.compatible)},
            "ack_delivery": self.delivery_receipt("exr_000000000001"),
        }
