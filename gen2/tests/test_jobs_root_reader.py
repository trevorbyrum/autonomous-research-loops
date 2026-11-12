"""One interpretation of the jobs root (S8 change 3, DEBT-052; Astra P1-2): a mixed root read by recover, incidents, delegate settlement,
Driver._orders, discovery_scratches and status.

Trace: INVARIANTS RG-2/3/9/U, L-7/L-8, C-10; BOUNDARIES Station supervisor.
What these show: a harness's two-key order is foreign and non-blocking; a scratch-only directory is a pre-prepare artifact; damaged,
non-object, mis-identified or journal-bearing-without-order entries are corrupt and block recovery and settlement (never absence);
valid incidents stay visible; every reader of the root sees the same valid orders; status is read-only and carries the classified facts.
Oracles: the fixture root written by hand. What they cannot show: the host's real debris (Lane C)."""
from __future__ import annotations

import json
import shutil
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


class MixedRootTest(sf.SupervisedTestCase):
    def put(self, handle: str, name: str, text: str) -> None:
        directory = self.supervisor.jobs_root / handle
        directory.mkdir(exist_ok=True)
        (directory / name).write_text(text)

    def build(self, *, corrupt: bool) -> None:
        self.put("job-inv_valid00001", "order.json", json.dumps({"invocation_id": "inv_valid00001", "topic_id": rf.TOPIC, "env": DISCOVERY}))
        self.put("job-inv_valid00001", "journal.json", json.dumps({"settled": "failed", "exhausted": {"kind": "retry_exhausted", "since": "2026-09-27T10:00:00Z"}}))
        for n in range(2):  # the actual harness shape
            self.put(f"job-inv_native_engine_{n}", "order.json", json.dumps({"command": ["x"], "env": {}}))
        (self.supervisor.jobs_root / "job-inv_scratchonly").mkdir()
        (self.supervisor.jobs_root / "job-inv_scratchonly" / "scratch").mkdir()
        if corrupt:
            self.put("job-inv_badjson001", "order.json", "{not json")
            self.put("job-inv_nonobject1", "order.json", "[1, 2]")
            self.put("job-inv_wrongid001", "order.json", json.dumps({"invocation_id": "inv_other00001", "topic_id": rf.TOPIC}))
            self.put("job-inv_noidentity", "order.json", json.dumps({"kind": "research_pass", "env": {}}))
            self.put("job-inv_damaged001", "journal.json", json.dumps({"incident": {"since": "x"}}))  # a journal, no order
            self.put("job-inv_badjournal", "order.json", json.dumps({"invocation_id": "inv_badjournal", "topic_id": rf.TOPIC}))
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
        station = {"invocation_id": "inv_shaped0001", "topic_id": rf.TOPIC}
        cases = {  # label: (directory, order, journal text): each must be CORRUPT, blocking, and leave the valid job's status and recovery readable
            "null_journal_harness": ("job-inv_nulljrn_h", {"command": [], "env": {}}, "null"),
            "null_journal_station": ("job-inv_shaped0001", station, "null"),
            "incident_list": ("job-inv_shaped0001", station, json.dumps({"incident": ["broken"]})),
            "recovering_without_incident": ("job-inv_shaped0001", station, json.dumps({"recovering": {"requested_by": "x"}})),
            "exhausted_string": ("job-inv_shaped0001", station, json.dumps({"exhausted": "x"})),
            "recoveries_not_list": ("job-inv_shaped0001", station, json.dumps({"recoveries": 3})),
            "numeric_invocation": ("job-123", {"invocation_id": 123, "topic_id": rf.TOPIC}, None),
            "empty_topic": ("job-inv_shaped0001", {**station, "topic_id": ""}, None),
            "malformed_invocation": ("job-bad", {"invocation_id": "bad", "topic_id": rf.TOPIC}, None),
            "env_not_object": ("job-inv_shaped0001", {**station, "env": ["x"]}, None),
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
