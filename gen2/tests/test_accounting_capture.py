"""Existing accounting entries capture once and perform pure work after closure."""
from unittest.mock import patch

from gen2.router import accounting
from gen2.router.boundary import Refusal
from gen2.store import capture
from gen2.tests.router_fixtures import TOPIC, OTHER, RouterTestCase


class CaptureTest(RouterTestCase):
    def test_existing_entries_and_precontract_control(self):
        before = self.state(exclude=())
        for name, converter in (("candidate_units", "convert_inventory"), ("evidence_inventory", "convert_inventory"),
                                ("coverage_snapshot", "convert_coverage_snapshot")):
            with self.subTest(name=name):
                convert = getattr(accounting, converter)
                def outside(*args):
                    self.assertFalse(self.db.in_transaction)
                    with patch.object(self.store, "select", side_effect=AssertionError("conversion read Store")):
                        return convert(*args)
                with patch.object(accounting, converter, side_effect=outside) as pure, \
                     patch.object(self.store, "capture_topic", wraps=self.store.capture_topic) as read:
                    native = getattr(self.router, name)(TOPIC, history="native")
                    legacy = getattr(self.router, name)(TOPIC, history="legacy_unknown")
                self.assertEqual((read.call_count, pure.call_count), (2, 2))
                if name == "candidate_units":
                    self.assertEqual((native.retrieved_records.value, legacy.retrieved_records.value), (0, None))
                else:
                    inv = native.inventory if name == "coverage_snapshot" else native
                    self.assertIsNone(inv.current_contract_revision)
                    self.assertEqual(inv.observations, ())
        self.assertEqual(self.state(exclude=()), before)

    def test_conversion_failure_has_closed_capture(self):
        before = self.state(exclude=())
        with patch.object(accounting, "convert_inventory", side_effect=ValueError("pure failure")):
            with self.assertRaisesRegex(ValueError, "pure failure"):
                self.router.evidence_inventory(TOPIC, history="native")
        self.assertFalse(self.db.in_transaction)
        self.assertEqual(self.db.execute("PRAGMA query_only").fetchone(), (0,))
        self.assertEqual(self.state(exclude=()), before)

    def test_unknown_and_explicit_history(self):
        for name in ("candidate_units", "evidence_inventory", "coverage_snapshot"):
            with self.subTest(name=name):
                with self.assertRaises(Refusal):
                    getattr(self.router, name)("topic_missing1", history="native")
                with self.assertRaises(ValueError):
                    getattr(self.router, name)(OTHER, history="invented")

    def test_raw_decoding_is_pure_and_does_not_mutate(self):
        raw = self.store.capture_topic(TOPIC)
        before = capture.input_hash(raw, "native")
        with patch.object(self.store, "capture_topic", side_effect=AssertionError("pure recapture")):
            first = accounting.convert_coverage_snapshot(raw, TOPIC, "native")
            self.assertEqual(accounting.convert_coverage_snapshot(raw, TOPIC, "native"), first)
        self.assertEqual(capture.input_hash(raw, "native"), before)
