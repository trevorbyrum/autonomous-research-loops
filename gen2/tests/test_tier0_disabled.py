"""2d-5 / H-2: literal capability truth across activation and operator reads."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gen2.router import service
from gen2.store import api
from gen2.tests import operator_fixtures as of, router_fixtures as rf

T = "2026-10-22T00:00:00Z"
LATER = "2026-10-23T00:00:00Z"


class Tier0ActivationTest(unittest.TestCase):
    def test_fresh_activation_records_dated_disabled_fact(self):
        with tempfile.TemporaryDirectory() as root:
            router = service.Router.open(Path(root) / "store.sqlite3", rf.Spool(), create=True, clock=lambda: T)
            try:
                self.assertEqual(router.activate_config_bundle(rf.BUNDLE)["status"], "activated")
                with router._snapshot():
                    facts = router._store.select("capability_facts")
                self.assertEqual([(f["capability"], f["state"], f["detail"], f["since"], f["recorded_at"],
                                   f["last_success_at"], f["affected_lanes"], f["superseded_by_fact_id"]) for f in facts],
                                 [("tier-0", "unknown", "tier-0 disabled", T, T, None, [], None)])
                status = router.status({})
                self.assertEqual([(f["capability"], f["detail"]) for f in status["capability_facts"]],
                                 [("tier-0", "tier-0 disabled")])
            finally:
                router.close()

    def test_retained_store_without_fact_gets_one_at_activation(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "store.sqlite3"
            # A pre-slice store: existing bundle, no capability observation.
            with api.open_store(path, create=True) as store:
                with store.transaction():
                    store.insert("config_bundles", {"bundle_hash": rf.CONFIG, "version": 1, "document": rf.BUNDLE,
                                                   "status": "active", "activated_at": T})
                    self.assertEqual(store.select("capability_facts"), [])
            router = service.Router.open(path, rf.Spool(), clock=lambda: LATER)
            try:
                self.assertEqual(router.restore_config_bundle(), rf.CONFIG)
                self.assertEqual([(f["capability"], f["state"], f["detail"], f["since"], f["last_success_at"])
                                  for f in router.status({})["capability_facts"]],
                                 [("tier-0", "unknown", "tier-0 disabled", LATER, None)])
            finally:
                router.close()

    def test_restart_and_status_preserve_original_fact_without_performed_records(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "store.sqlite3"
            router = service.Router.open(path, rf.Spool(), create=True, clock=lambda: T)
            self.assertEqual(router.activate_config_bundle(rf.BUNDLE)["status"], "activated")
            before = router.status({})["capability_facts"]
            router.close()
            router = service.Router.open(path, rf.Spool(), clock=lambda: LATER)
            try:
                self.assertEqual(router.restore_config_bundle(), rf.CONFIG)
                self.assertEqual(router.status({})["capability_facts"], before)
                with router._snapshot():
                    self.assertEqual(len(router._store.select("capability_facts")), 1)
                    for family in ("verification_receipts", "detailed_check_records", "quote_checks", "holds"):
                        self.assertEqual(router._store.select(family), [], family)
                    self.assertEqual([e["kind"] for e in router._store.select("audit_events")], ["config_bundle_activated"])
            finally:
                router.close()

    def test_fact_write_failure_prevents_activation(self):
        with tempfile.TemporaryDirectory() as root:
            router = service.Router.open(Path(root) / "store.sqlite3", rf.Spool(), create=True, clock=lambda: T)
            insert = api.Store.insert
            def unavailable(store, table, row):
                if table == "capability_facts" and row.get("capability") == "tier-0":
                    raise api.StoreWriteError("fact unavailable")
                return insert(store, table, row)
            try:
                with patch.object(api.Store, "insert", autospec=True, side_effect=unavailable):
                    reply = router.activate_config_bundle(rf.BUNDLE)
                self.assertEqual((reply["status"], reply["reason"]), ("refused", "bundle_invalid"))
                self.assertIn("fact unavailable", reply["detail"])
                with router._snapshot():
                    self.assertEqual(router._store.select("config_bundles"), [])
                    self.assertEqual(router._store.select("capability_facts", {"capability": "tier-0"}), [])
            finally:
                router.close()

    def test_config_activation_control(self):
        """Independent accepted startup path for omission/false-pass mutants."""
        with tempfile.TemporaryDirectory() as root:
            router = service.Router.open(Path(root) / "store.sqlite3", rf.Spool(), create=True, clock=lambda: T)
            try:
                self.assertEqual(router.activate_config_bundle(rf.BUNDLE)["status"], "activated")
                self.assertEqual(router.restore_config_bundle(), rf.CONFIG)
                self.assertEqual(router.status({})["config_bundles"]["active"]["bundle_hash"], rf.CONFIG)
            finally:
                router.close()


class Tier0StatusTest(of.OperatorTestCase):
    def test_operator_status_never_reports_tier0_performed_or_passed(self):
        before = self.state(exclude=())
        for topic in (None, rf.TOPIC):
            facts = [f for f in self.status_doc(topic)["capability_facts"] if f["capability"] == "tier-0"]
            self.assertEqual(len(facts), 1)
            self.assertEqual((facts[0]["state"], facts[0]["detail"], facts[0]["last_success_at"], facts[0]["affected_lanes"]),
                             ("unknown", "tier-0 disabled", None, []))
            self.assertEqual(self.rows("SELECT fact_id, since FROM capability_facts WHERE capability = 'tier-0'"),
                             [(facts[0]["fact_id"], facts[0]["since"])])
        self.assertEqual(self.state(exclude=()), before)

    def test_other_capability_facts_remain_visible_control(self):
        self.x("INSERT INTO capability_facts (fact_id, capability, state, detail, since, affected_lanes, recorded_at) "
               "VALUES ('fact_other0001', 'other-capability', 'failing', 'unavailable', ?, '[]', ?)", T, T)
        self.assertIn(("other-capability", "failing", "unavailable"),
                      [(f["capability"], f["state"], f["detail"]) for f in self.status_doc()["capability_facts"]])


if __name__ == "__main__":
    unittest.main()
