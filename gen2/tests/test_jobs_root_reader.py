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
from gen2.operator import status as status_view
from gen2.supervisor import jobs
from gen2.supervisor.supervisor import ControlFailure, Waiting
from gen2.tests import router_fixtures as rf
from gen2.tests import supervisor_fixtures as sf

DISCOVERY = {"GEN2_PURPOSE": "discovery/search", "GEN2_CONTEXT": "c1.e1"}
OBS = {"descendants": {"handling": "none_found", "count": 0}, "termination": None, "findings": [], "output": {"status": "present"}}
REF = {"content_hash": "sha256:" + "a" * 64, "size_bytes": 1}
KEPT = {"observation": OBS, "result": REF, "method": "exit_observed"}   # the journal's nested records as the supervisor writes them
SINCE = {"since": "2026-09-27T10:00:00Z"}
COLLECTED = {**KEPT, "record": REF}
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
                  {"descendants": OBS["descendants"]}, {"descendants": None, "termination": None}],   # the phases: kept end, and _collect's first save
    "collected": [None, KEPT, {**COLLECTED, "observation": {**OBS, "descendants": {}}}, {**COLLECTED, "result": None}, {**COLLECTED, "evidence": None},
                  {**COLLECTED, "rehandled": {}}],
    "grant": [None, {}, {"capability_id": "cap_1"}, {**GRANT, "lease": {}}], "unresolved": [None, {"episode": 1}], "outage": [None, {}],
    "pending": [None, {"purpose": "end:failed"}, {k: v for k, v in PENDING.items() if k != "digest"}], "dispatch": [None, {}, {"admission_ref": "a"}],
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
        order, handle = sf.bare_order("inv_aaaa0001", rf.TOPIC), "job-inv_aaaa0001"
        self.put(handle, "order.json", json.dumps(order))
        self.put(handle, "journal.json", json.dumps(GENUINE))
        self.assertEqual((self.supervisor.census()["valid"], self.supervisor.census()["blocking"]), (2, False))
        self.put(handle, "journal.json", json.dumps({"observing": {"descendants": OBS["descendants"], "termination": None}}))  # _collect's first save
        self.assertFalse(self.supervisor.census()["blocking"])
        self.put(handle, "journal.json", json.dumps({"observing": KEPT}))  # a kept end awaiting staging
        self.assertFalse(self.supervisor.census()["blocking"])
        for field, damaged in NESTED_DAMAGE.items():
            for n, value in enumerate(damaged):
                with self.subTest(field=field, case=n):
                    self.put(handle, "journal.json", json.dumps({field: value}))
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
