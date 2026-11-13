"""One interpretation of the jobs root (S8 change 3, DEBT-052; Astra P1-2): a mixed root read by recover, incidents, delegate settlement,
Driver._orders, discovery_scratches and status.

Trace: INVARIANTS RG-2/3/9/U, L-7/L-8, C-10; BOUNDARIES Station supervisor.
What these show: a harness's two-key order is foreign and non-blocking; a scratch-only directory is a pre-prepare artifact; damaged,
non-object, mis-identified or journal-bearing-without-order entries are corrupt and block recovery and settlement (never absence);
valid incidents stay visible; every reader of the root sees the same valid orders; status is read-only and carries the classified facts.
Oracles: the fixture root written by hand. What they cannot show: the host's real debris (Lane C)."""
from __future__ import annotations

import ast
import json
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from gen2.app.compose import discovery_scratches
from gen2.app.driver import Driver
from gen2.core.canonical import CanonicalizationError
from gen2.operator import status as status_view
from gen2.supervisor import jobs
from gen2.supervisor.supervisor import ControlFailure, Supervisor, Waiting
from gen2.tests import operator_fixtures as of
from gen2.tests import router_fixtures as rf
from gen2.tests import supervisor_fixtures as sf
from gen2.tests.test_operator_recovery import RecoveryFaults
from gen2.tests.test_supervisor_lifecycle import LifecycleFaults

DISCOVERY = {"GEN2_PURPOSE": "discovery/search", "GEN2_CONTEXT": "c1.e1"}
OBS = {"descendants": {"handling": "none_found", "count": 0}, "termination": None, "findings": [], "output": {"status": "present"}}
REF = {"content_hash": "sha256:" + "a" * 64, "size_bytes": 1}
CANCELLED = {**OBS, "termination": {"reason": "cancellation"}}   # what _terminate writes for a cancellation: no finding, no result
KEPT = {"observation": OBS, "result": REF, "method": "exit_observed"}   # the journal's nested records as the supervisor writes them
SINCE = {"since": "2026-09-27T10:00:00Z"}
COLLECTED = {"observation": OBS, "result": REF, "record": REF}   # no method: _retain does not keep it
GRANT = {"capability_id": "cap_1", "invocation_id": "inv_aaaa0001", "topic_id": rf.TOPIC, "admission": {}, "config_bundle_hash": "h",
         "lease": {"lease_id": "l", "generation": 1}}
PENDING = {"purpose": "reconcile:1", "record": REF, "method": "job_handle_lookup", "observation": OBS, "resolution": "found_result", "identity": None, "digest": None}
GENUINE = {"incident": SINCE, "exhausted": SINCE, "recovering": {"incident": SINCE, "requested_by": "op"}, "outage": SINCE, "grant": GRANT,
           "recoveries": [{"incident": SINCE, "outcome": "resumed"}], "collected": COLLECTED, "pending": PENDING, "unresolved": {"episode": 1, **SINCE},
           "dispatch": {"admission_ref": "a", "run_id": "r", "attempt": 1}, "budgets": {"write": 1}, "revision": 3}
NESTED_DAMAGE = {  # structure: damaged values of that journal field, each beside the consumer that indexes it (see the table in jobs.py)
    "incident": [{"since": ""}, {**SINCE, "last_refusal": {}}], "exhausted": [None, {"kind": "x"}], "recovering": [None, {"incident": SINCE}],
    "recoveries": [None, [{"incident": SINCE}]],
    "observing": [None, {}, {**KEPT, "method": None}, {**KEPT, "observation": {}}, {k: v for k, v in KEPT.items() if k != "result"},
                  {"descendants": OBS["descendants"]}, {"descendants": None, "termination": None},   # the phases: kept end, and _collect's first save
                  {**KEPT, "result": None}, {**KEPT, "result": None, "terminated": ""},
                  {**KEPT, "result": None, "terminated": "timeout", "observation": {**OBS, "termination": {"reason": "timeout"}}}, {**KEPT, "method": "\ud800"}, {**KEPT, "observation": {**OBS, "findings": [1]}},
                  {**KEPT, "observation": {**OBS, "exit": float("nan")}}],   # null result unexplained (_retain copies it); findings[0]; not canonicalizable
    "collected": [None, KEPT, {**COLLECTED, "observation": {**OBS, "descendants": {}}}, {**COLLECTED, "result": None}, {**COLLECTED, "evidence": None},
                  {**COLLECTED, "rehandled": {}}],
    "grant": [None, {}, {"capability_id": "cap_1"}, {**GRANT, "lease": {}}], "unresolved": [None, {"episode": 1}, {"episode": 1, "since": "2026-13-45T00:00:00Z"}, {"episode": 1, "since": "tomorrow"}], "outage": [None, {}, {"since": "not-an-instant"}, {"since": 5}],
    "pending": [None, {"purpose": "end:failed"}, {k: v for k, v in PENDING.items() if k != "digest"}, {**PENDING, "identity": 1}, {**PENDING, "identity": ["host_id"]},
                {**PENDING, "identity": {"capability_id": "x"}}, {**PENDING, "digest": 5}, {**PENDING, "resolution": "confirmed_failed"}, {**PENDING, "resolution": "terminated_group"},
                {**PENDING, "method": "\ud800"},
                {**PENDING, "purpose": "end:failed"}, {**PENDING, "observation": {**OBS, "exit": float("nan")}}], "dispatch": [None, {}, {"admission_ref": "a"}],
}


class MixedRootTest(sf.SupervisedTestCase):
    def put(self, handle: str, name: str, text: str) -> None:
        directory = self.supervisor.jobs_root / handle
        directory.mkdir(exist_ok=True)
        (directory / name).write_text(text)

    def build(self, *, corrupt: bool) -> None:
        self.put("job-inv_valid00001", "order.json", json.dumps(sf.bare_order("inv_valid00001", rf.TOPIC, env=DISCOVERY)))
        self.put("job-inv_valid00001", "journal.json", json.dumps({"settled": "failed", "exhausted": {"kind": "retry_exhausted", "since": "2026-09-27T10:00:00Z"}}))
        for n in range(2):  # the actual harness shape
            self.put(f"job-inv_native_engine_{n}", "order.json", json.dumps({"command": ["x"], "env": {}}))
        (self.supervisor.jobs_root / "job-inv_scratchonly").mkdir()
        (self.supervisor.jobs_root / "job-inv_scratchonly" / "scratch").mkdir()
        if corrupt:
            self.put("job-inv_badjson001", "order.json", "{not json")
            self.put("job-inv_nonobject1", "order.json", "[1, 2]")
            self.put("job-inv_wrongid001", "order.json", json.dumps(sf.bare_order("inv_other00001", rf.TOPIC)))
            self.put("job-inv_noidentity", "order.json", json.dumps({"kind": "research_pass", "env": {}}))
            self.put("job-inv_damaged001", "journal.json", json.dumps({"incident": {"since": "x"}}))  # a journal, no order
            self.put("job-inv_badjournal", "order.json", json.dumps(sf.bare_order("inv_badjournal", rf.TOPIC)))
            self.put("job-inv_badjournal", "journal.json", "[]")
            self.put("job-inv_harnessjrn", "order.json", json.dumps({"command": [], "env": {}}))
            self.put("job-inv_harnessjrn", "journal.json", "{}")  # two keys but station state beside it: not positively foreign

    def recover(self) -> dict:
        with mock.patch.object(self.supervisor, "advance", side_effect=lambda inv: "advanced:" + inv):  # the valid job's own lifecycle is not under test
            return self.supervisor.recover()

    def kinds(self) -> dict:
        return {e.name: e.kind for e in jobs.entries(self.supervisor.jobs_root)}

    def test_classification_of_a_mixed_root(self) -> None:
        self.build(corrupt=True)
        kinds = self.kinds()
        self.assertEqual({k for k, v in kinds.items() if v == jobs.VALID}, {"job-inv_valid00001"})
        self.assertEqual({k for k, v in kinds.items() if v == jobs.FOREIGN}, {"job-inv_native_engine_0", "job-inv_native_engine_1"})
        self.assertEqual({k for k, v in kinds.items() if v == jobs.PRE_PREPARE}, {"job-inv_scratchonly"})
        self.assertEqual({k for k, v in kinds.items() if v == jobs.CORRUPT}, {
            "job-inv_badjson001", "job-inv_nonobject1", "job-inv_wrongid001", "job-inv_noidentity", "job-inv_damaged001", "job-inv_badjournal", "job-inv_harnessjrn"})

    def test_foreign_and_pre_prepare_alone_block_nothing(self) -> None:
        self.build(corrupt=False)
        self.assertEqual([i["invocation_id"] for i in self.supervisor.incidents()], ["inv_valid00001"])
        census = self.supervisor.census()
        self.assertEqual((census["valid"], census["foreign"], census["pre_prepare"], census["corrupt"], census["blocking"]), (1, 2, 1, [], False))
        self.supervisor._settle_delegates({"kind": "research_pass", "invocation_id": "inv_parent0001"})  # no delegate, nothing ambiguous: settles
        self.assertEqual(self.recover(), {"inv_valid00001": "advanced:inv_valid00001"})  # foreign work is never adopted
        self.assertFalse((self.supervisor.jobs_root / "job-inv_native_engine_0" / "journal.json").exists())

    def test_ambiguous_state_blocks_recovery_and_settlement_and_is_visible(self) -> None:
        self.build(corrupt=True)
        with self.assertRaises(ControlFailure) as raised:
            self.recover()
        self.assertEqual({v for k, v in raised.exception.outcomes.items() if k != "inv_valid00001"}, {"corrupt_job_state"})
        self.assertEqual(len(raised.exception.outcomes), 8)  # the seven corrupt entries and the valid job, which still recovered
        with self.assertRaises(Waiting):
            self.supervisor._settle_delegates({"kind": "research_pass", "invocation_id": "inv_parent0001"})
        self.assertEqual([i["invocation_id"] for i in self.supervisor.incidents()], ["inv_valid00001"])  # status still reads
        census = self.supervisor.census()
        self.assertEqual((census["foreign"], census["pre_prepare"], census["blocking"], len(census["corrupt"])), (2, 1, True, 7))
        doc = status_view.compose({"at": "t", "topics": [], "config_bundles": [], "capability_facts": [], "holds": []}, [], census)
        self.assertEqual(doc["station"], census)
        self.assertNotIn("station", status_view.compose({"at": "t", "topics": [], "config_bundles": [], "capability_facts": [], "holds": []}, []))
        self.assertNotIn("{not json", json.dumps(doc))  # reasons name a class of failure, never entry content

    def test_driver_and_discovery_agree_with_the_reader(self) -> None:
        self.build(corrupt=True)
        station = SimpleNamespace(supervisor=self.supervisor)
        valid = jobs.orders(self.supervisor.jobs_root)
        self.assertEqual([o["invocation_id"] for o in valid], ["inv_valid00001"])
        self.assertEqual(list(Driver._orders(SimpleNamespace(station=station, topic_id=rf.TOPIC))), valid)
        self.assertEqual(discovery_scratches(station, rf.TOPIC)(), [Path(self.supervisor.jobs_root / "job-inv_valid00001" / "scratch")])

    def test_every_consumed_shape_is_checked_by_the_reader(self) -> None:
        station = sf.bare_order("inv_shaped0001", rf.TOPIC)
        cases = {  # label: (directory, order, journal text): each must be CORRUPT, blocking, and leave the valid job's status and recovery readable
            "null_journal_harness": ("job-inv_nulljrn_h", {"command": [], "env": {}}, "null"),
            "null_journal_station": ("job-inv_shaped0001", station, "null"),
            "incident_list": ("job-inv_shaped0001", station, json.dumps({"incident": ["broken"]})),
            "recovering_without_incident": ("job-inv_shaped0001", station, json.dumps({"recovering": {"requested_by": "x"}})),
            "exhausted_string": ("job-inv_shaped0001", station, json.dumps({"exhausted": "x"})),
            "recoveries_not_list": ("job-inv_shaped0001", station, json.dumps({"recoveries": 3})),
            "numeric_invocation": ("job-123", {**station, "invocation_id": 123}, None),
            "deadline_not_instant": ("job-inv_shaped0001", {**station, "deadline_at": "soon"}, None),
            "deadline_not_text": ("job-inv_shaped0001", {**station, "deadline_at": 5}, None),
            "empty_topic": ("job-inv_shaped0001", {**station, "topic_id": ""}, None),
            "malformed_invocation": ("job-bad", {**station, "invocation_id": "bad"}, None),
            "env_not_object": ("job-inv_shaped0001", {**station, "env": ["x"]}, None),
            "env_value_not_text": ("job-inv_shaped0001", {**station, "env": {"A": 1}}, None),
            "missing_kind": ("job-inv_shaped0001", {k: v for k, v in station.items() if k != "kind"}, None),
            "delegate_without_parent": ("job-inv_shaped0001", {**station, "kind": "delegate"}, None),
            **{f"budgets_{label}": ("job-inv_aaaa0001", sf.bare_order("inv_aaaa0001", rf.TOPIC), json.dumps({"incident": {"since": "x"}, "budgets": budgets}))
               for label, budgets in (("null", None), ("list", []), ("string_counter", {"recovery": "broken"}), ("bool_counter", {"recovery": True}),
                                      ("negative_counter", {"recovery": -1}), ("float_counter", {"write": 1.5}), ("null_counter", {"router": None}))},
        }
        self.build(corrupt=False)
        for label, (handle, order, journal) in cases.items():
            with self.subTest(label):
                self.put(handle, "order.json", json.dumps(order))
                if journal is not None:
                    self.put(handle, "journal.json", journal)
                census = self.supervisor.census()
                self.assertEqual(([c["entry"] for c in census["corrupt"]], census["blocking"], census["valid"]), ([handle], True, 1))
                self.assertEqual([i["invocation_id"] for i in self.supervisor.incidents()], ["inv_valid00001"])
                with self.assertRaises(ControlFailure) as raised:
                    self.recover()
                self.assertEqual(raised.exception.outcomes, {handle: "corrupt_job_state", "inv_valid00001": "advanced:inv_valid00001"})
                with self.assertRaises(Waiting):
                    self.supervisor._settle_delegates({"kind": "research_pass", "invocation_id": "inv_parent0001"})
                shutil.rmtree(self.supervisor.jobs_root / handle)

    def test_nested_records_are_checked_against_their_consumers(self) -> None:
        """Every nested structure the supervisor, driver and compose index (the table in jobs.py): genuine states are valid; a null, a wrong
        type or an incomplete record of each is CORRUPT, blocking, and real recovery (advance not stubbed) still reaches the valid job."""
        self.build(corrupt=False)
        self.supervisor.submit(self.order("research_pass"))  # a REAL admitted job (its own order, grant and journal), sorted before the valid one
        handle = f"job-{sf.MAIN}"
        real = json.loads((self.supervisor.jobs_root / handle / "journal.json").read_text())
        self.put(handle, "journal.json", json.dumps(real))
        self.assertEqual((self.supervisor.census()["valid"], self.supervisor.census()["blocking"]), (2, False))
        self.put(handle, "journal.json", json.dumps({**real, **GENUINE}))
        self.assertEqual((self.supervisor.census()["valid"], self.supervisor.census()["blocking"]), (2, False))
        for journal in ({"observing": {"descendants": OBS["descendants"], "termination": None}}, {"observing": KEPT},   # _collect's first save; a kept end
                        {"observing": {**KEPT, "result": None, "observation": {**OBS, "findings": ["exit_nonzero"]}}},
                        {"observing": {**KEPT, "result": None, "method": "execution_group_termination", "terminated": "cancellation", "observation": CANCELLED}},
                        {"collected": {**COLLECTED, "result": None, "terminated": "cancellation", "observation": CANCELLED}},
                        {"pending": {"purpose": "end:cancelled", "record": None, "method": "job_handle_lookup", "observation": OBS}},   # no finding: a cancellation
                        {"pending": {**PENDING, "resolution": "terminated_group", "observation": CANCELLED}},
                        {"pending": {**PENDING, "resolution": "confirmed_failed", "observation": {**OBS, "findings": ["never_started"]},
                                     "identity": dict.fromkeys(jobs.PROCESS_KEYS, "x")}}, {"outage": {"since": "2026-09-27T10:00:00.5Z"}}):
            self.put(handle, "journal.json", json.dumps({**real, **journal}))
            self.assertFalse(self.supervisor.census()["blocking"], journal)
        for field, damaged in NESTED_DAMAGE.items():
            for n, value in enumerate(damaged):
                with self.subTest(field=field, case=n):
                    self.put(handle, "journal.json", json.dumps({**real, field: value}))
                    census = self.supervisor.census()
                    self.assertEqual(([c["entry"] for c in census["corrupt"]], census["blocking"], census["valid"]), ([handle], True, 1))
                    with mock.patch.object(self.supervisor, "advance", wraps=self.supervisor.advance) as advance, self.assertRaises(ControlFailure) as raised:
                        self.supervisor.recover()
                    advance.assert_called_once_with("inv_valid00001")
                    self.assertEqual(raised.exception.outcomes, {handle: "corrupt_job_state", "inv_valid00001": "failed"})
                    with self.assertRaises(Waiting):
                        self.supervisor._settle_delegates({"kind": "research_pass", "invocation_id": "inv_parent0001"})


class ConsumedFieldsLintTest(unittest.TestCase):
    """A LIMITED LINT, not a proof of coverage: a journal or order field read by constant key straight off a variable or attribute named
    journal/djournal/order/dorder (or off a direct read of the file), in supervisor.py, driver.py or compose.py, must be in the reader's table
    (jobs.JOURNAL_FIELDS, jobs.ORDER_FIELDS). It misses aliases (`j = journal`), helper parameters, copies, computed keys and other modules,
    and says nothing of nested keys or shapes; the behavioural tests of MixedRootTest are the oracle of correctness."""
    MODULES = ("supervisor/supervisor.py", "app/driver.py", "app/compose.py")
    KINDS = {"journal": ("journal", "djournal"), "order": ("order", "dorder")}

    def reads(self) -> set[tuple[str, str]]:
        def kind(node):  # which document a base expression is: a variable or attribute named for it, or a read of its file
            while isinstance(node, ast.BoolOp):
                node = node.values[0]
            name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "read" and node.args \
                    and isinstance(node.args[0], ast.Constant):
                name = {"journal.json": "journal", "order.json": "order"}.get(node.args[0].value)
            return next((k for k, names in self.KINDS.items() if name == k or name in names), None)
        found = set()
        for module in self.MODULES:
            for node in ast.walk(ast.parse((Path(jobs.__file__).parent.parent / module).read_text())):
                if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) and isinstance(node.slice, ast.Constant):
                    base, key = node.value, node.slice.value
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("get", "pop", "setdefault") \
                        and node.args and isinstance(node.args[0], ast.Constant):
                    base, key = node.func.value, node.args[0].value
                else:
                    continue
                if isinstance(key, str) and kind(base):
                    found.add((kind(base), key))
        return found

    def test_the_scan_sees_the_known_consumers(self) -> None:
        found = self.reads()
        for pair in (("journal", "budgets"), ("journal", "settled"), ("journal", "revision"), ("order", "topic_id"), ("order", "env"), ("order", "kind")):
            self.assertIn(pair, found)

    def test_every_consumed_field_is_in_its_table(self) -> None:
        tables = {"journal": jobs.JOURNAL_FIELDS, "order": jobs.ORDER_FIELDS}
        self.assertEqual(sorted((kind, key) for kind, key in self.reads() if key not in tables[kind]), [])


class ObservedWrites:
    """Every journal the supervisor REALLY saves (the real `_save`, read back from disk) must classify VALID: the genuine states the
    predicate may never reject, from real submit, collect, end, reconcile, outage, cancellation and operator recovery. Nothing is repaired."""
    def setUp(self) -> None:
        super().setUp()
        self.saved, real = [], Supervisor._save

        def observed(supervisor, job, journal):
            real(supervisor, job, journal)
            kind = {e.name: e.kind for e in jobs.entries(supervisor.jobs_root)}[job.handle]
            self.saved.append((kind, job.handle, sorted(job.read("journal.json"))))
        patch = mock.patch.object(Supervisor, "_save", observed)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self) -> None:
        try:
            self.assertEqual([w for w in self.saved if w[0] != jobs.VALID], [])
        finally:
            super().tearDown()


class LifecycleWritesAreValidTest(ObservedWrites, LifecycleFaults, sf.SupervisedTestCase):
    KIND = "research_pass"

    def test_the_observer_sees_the_writes(self) -> None:  # the other tests call tearDown mid-test: this one shows the observer is not vacuous
        self.assertEqual((self.submit(), self.supervisor.run(sf.MAIN)), ("running", "committed"))
        self.assertGreaterEqual(len(self.saved), 5)


class RecoveryWritesAreValidTest(ObservedWrites, RecoveryFaults, of.OperatorTestCase):
    KIND = "research_pass"


class ContainmentTest(sf.SupervisedTestCase):
    """Real recovery over a real unknown-outcome job (a refused launcher, the router's own outcome_unknown) placed BEFORE a valid job:
    a failure of the damaged job's step on its persisted state is a blocking outcome for that job, the later job still advances, recovery
    raises ControlFailure, settlement waits and status shows it; the job's journal and hold are exactly as they were. With the reader's
    journal check withdrawn (`reader_accepts`), containment alone stands between each round-5 case and an aborted recovery."""
    KIND = "research_pass"
    LATER = "inv_valid00001"
    TERMINATED_GROUP = {**PENDING, "resolution": "terminated_group", "method": "execution_group_termination"}

    def setUp(self) -> None:
        super().setUp()
        self.prepare(self.KIND)
        refused = self.make_supervisor(launcher=(str(self.root / "missing-interpreter"),))
        self.assertEqual(refused.submit(self.order(self.KIND)), "launching")
        grant = self.journal()["grant"]
        self.assertEqual(self.router.record_transition({"capability_id": grant["capability_id"], "invocation_id": sf.MAIN, "to_state": "outcome_unknown",
                                                         "unknown_episode": 1, "unknown_cause": "spawn_uncertain"})["status"], "recorded")
        later = self.root / "jobs" / f"job-{self.LATER}"
        later.mkdir()
        (later / "order.json").write_text(json.dumps(sf.bare_order(self.LATER, rf.TOPIC, env=DISCOVERY)))
        (later / "journal.json").write_text(json.dumps({"settled": "failed"}))
        self.supervisor = self.make_supervisor()

    def damage(self, **fields) -> None:
        job = self.supervisor.job(sf.MAIN)
        job.write("journal.json", {**job.read("journal.json"), **fields})

    def recover(self, *, reader_accepts: bool) -> tuple[dict, list, dict]:
        advanced, real = [], self.supervisor.advance

        def recording(inv, **kwargs):
            advanced.append(inv)
            return real(inv, **kwargs)
        with mock.patch.object(self.supervisor, "advance", recording), mock.patch.object(jobs, "JOURNAL_FIELDS", {} if reader_accepts else jobs.JOURNAL_FIELDS):
            with self.assertRaises(ControlFailure) as raised:
                self.supervisor.recover()
            return raised.exception.outcomes, advanced, self.supervisor.census()

    def assertContained(self, reason: str, *, reader_accepts: bool = True) -> None:
        handle = f"job-{sf.MAIN}"
        outcomes, advanced, census = self.recover(reader_accepts=reader_accepts)
        self.assertEqual(outcomes[sf.MAIN], "corrupt_job_state")
        self.assertIn(self.LATER, advanced)  # the later valid job still advanced
        self.assertNotIn("settled", self.supervisor.job(sf.MAIN).read("journal.json"))  # nothing completed, released or settled
        self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", sf.MAIN), "outcome_unknown")
        self.assertTrue(census["blocking"])
        self.assertEqual([c["reason"] for c in census["corrupt"] if c["entry"] == handle], [f"contained: {reason} in recover"])  # a fixed class, once
        self.assertEqual(census["valid"], 1)  # the later job only: a contained job is not also counted valid
        self.assertNotIn(sf.MAIN, json.dumps(census["corrupt"]).replace(handle, ""))
        self.assertTrue(census["blocking"] and status_view.compose({"at": "t", "topics": [], "config_bundles": [], "capability_facts": [], "holds": []},
                                                                    [], jobs.census(self.root / "jobs"))["station"]["blocking"])  # from the files alone
        doc = status_view.compose({"at": "t", "topics": [], "config_bundles": [], "capability_facts": [], "holds": []}, [], census)
        self.assertEqual(doc["station"], census)

    def test_terminated_group_without_a_finding_or_cancellation(self) -> None:
        self.damage(pending=self.TERMINATED_GROUP)
        self.assertContained("consumed_index")

    def test_a_kept_end_without_a_result_or_finding(self) -> None:
        kept = {**KEPT, "result": None, "terminated": "timeout", "observation": {**OBS, "termination": {"reason": "timeout"}}}
        self.damage(observing=kept, collected=None)
        self.assertContained("consumed_index")

    def test_a_method_that_will_not_serialize(self) -> None:
        self.damage(pending={**PENDING, "record": None, "resolution": "confirmed_failed", "method": "\ud800", "observation": {**OBS, "findings": ["x"]}})
        self.assertContained("canonical")

    def test_an_outage_at_the_last_supported_instant(self) -> None:  # the reader accepts it: only the window arithmetic fails
        down = sf.Unreachable(self.control)
        down.down = True
        self.supervisor = self.make_supervisor(control=down)
        self.damage(outage={"since": "9999-12-31T23:59:59Z"})
        self.assertContained("consumed_value", reader_accepts=False)

    def test_a_cancellation_the_router_does_not_know(self) -> None:  # the journal alone cannot tell: accepted by the reader itself
        cancelled = {**PENDING, "resolution": "terminated_group", "method": "execution_group_termination",
                     "observation": CANCELLED}
        self.damage(pending=cancelled)
        self.assertContained("consumed_index", reader_accepts=False)

    def test_a_contained_failure_blocks_a_fresh_supervisor_before_any_recovery(self) -> None:
        self.damage(pending=self.TERMINATED_GROUP)
        self.recover(reader_accepts=True)
        fresh = self.make_supervisor()  # a restart: no recover() yet
        census = fresh.census()
        self.assertTrue(census["blocking"])
        self.assertEqual([c["reason"] for c in census["corrupt"]], ["contained: consumed_index in recover"])
        self.assertEqual(census["valid"], 1)
        with self.assertRaises(ControlFailure):  # and recovery does not skip it either
            fresh.recover()

    def test_status_shows_no_exception_text_or_stored_value(self) -> None:
        sentinel = "PRIVATE_SENTINEL_1152921504606846977"
        self.damage(pending={**PENDING, "record": None, "resolution": "confirmed_failed", "method": "\ud800",
                             "observation": {**OBS, "findings": [sentinel]}})
        self.recover(reader_accepts=True)
        job = self.supervisor.job(sf.MAIN)
        job.write(jobs.CONTAINED, {"reason": sentinel, "step": sentinel})  # a marker holding anything else is not echoed either
        self.assertNotIn(sentinel, json.dumps(self.supervisor.census()))
        self.assertIn("unreadable marker", json.dumps(self.supervisor.census()))

    def test_a_delegate_that_fails_its_settlement_step_keeps_its_parent_waiting(self) -> None:
        delegate = self.root / "jobs" / "job-inv_delegate001"
        delegate.mkdir()
        (delegate / "order.json").write_text(json.dumps(sf.bare_order("inv_delegate001", rf.TOPIC, kind="delegate", parent_invocation_id="inv_parent0001")))
        (delegate / "journal.json").write_text(json.dumps({"grant": "damaged"}))
        with mock.patch.object(jobs, "JOURNAL_FIELDS", {}):
            with self.assertRaises(Waiting):
                self.supervisor._settle_delegates({"kind": "research_pass", "invocation_id": "inv_parent0001"})
            self.assertEqual([c["entry"] for c in self.supervisor.census()["corrupt"]], ["job-inv_delegate001"])
        self.assertEqual(self.supervisor.job("inv_delegate001").read(jobs.CONTAINED), {"reason": "consumed_type", "step": "settle"})
