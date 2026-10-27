"""Raw integrity guards for verification attention; in-memory fixtures only."""
import sqlite3

from gen2.tests.store_fixtures import StoreTestCase, TOPIC, T
from gen2.tests.router_fixtures import HOLD


class HoldDDLTest(StoreTestCase):
    def record(self, **changes):
        row = {"hold_id": HOLD, "topic_id": TOPIC, "subject_ref": "verification:ver_quote00001", "hold_class": "judgment",
            "cause": "verification disagreement: does_not_support", "recoverability": "needs_decision", "required_authority": "primary",
            "owner": "primary:station-1", "deadline_at": "2026-09-27T11:00:00Z", "clears_when": "primary adjudication",
            "created_at": T, **changes}
        self.x("INSERT INTO holds (" + ", ".join(row) + ") VALUES (" + ", ".join("?" for _ in row) + ")", *row.values())

    def test_open_control(self):
        self.record()
        self.assertEqual(self.rows("SELECT hold_class, owner, deadline_at, cleared_at FROM holds"),
            [("judgment", "primary:station-1", "2026-09-27T11:00:00Z", None)])

    def test_shape(self):
        for change in ({"owner": ""}, {"deadline_at": None}, {"hold_class": "agreement"}):
            with self.subTest(change=change), self.assertRaises(sqlite3.IntegrityError):
                self.record(**change)
            self.assertEqual(self.rows("SELECT * FROM holds"), [])
        self.record()

    def test_created_open(self):
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_clear0001")
        self.receipt("op_clear00001", "inv_clear0001", kind="interim_transition")
        # The clearance CHECK and foreign key are satisfied; only open creation refuses.
        with self.assertRaisesRegex(sqlite3.IntegrityError, "created open"):
            self.record(cleared_at=T, cleared_by_operation_id="op_clear00001")
        self.assertEqual(self.rows("SELECT * FROM holds"), [])

    def test_identity_and_clearance(self):
        self.record()
        for sql in ("UPDATE holds SET subject_ref = 'different'", "UPDATE holds SET hold_class = 'transient'",
                    "UPDATE holds SET cleared_at = '2026-09-27T10:00:00Z'", "DELETE FROM holds"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.x(sql)
        self.decision("opd_clear00001", "hold_clearance", ref=HOLD)
        self.x("UPDATE holds SET cleared_at = ?, cleared_by_decision_id = 'opd_clear00001' WHERE hold_id = ?", T, HOLD)
        self.assertEqual(self.rows("SELECT cleared_by_decision_id FROM holds"), [("opd_clear00001",)])
