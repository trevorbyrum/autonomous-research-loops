"""Raw integrity guards for verification attention; in-memory fixtures only."""
import re
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
        for change, fragment in (({"owner": ""}, "length(owner) > 0"),
                                 ({"deadline_at": None}, "NOT NULL constraint failed: holds.deadline_at"),
                                 ({"hold_class": "agreement"}, "hold_class IN ('transient', 'capability', 'scope', 'judgment', 'unknown')")):
            with self.subTest(change=change), self.assertRaisesRegex(sqlite3.IntegrityError, re.escape(fragment)):
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
        self.x("UPDATE holds SET subject_ref = 'verification:ver_quote00001'")
        self.x("UPDATE holds SET hold_class = 'judgment'")
        before = self.snapshot("holds")
        for sql, fragment in (("UPDATE holds SET subject_ref = 'different'", "a cleared hold is final; hold identity, class and authority are immutable"),
                    ("UPDATE holds SET hold_class = 'transient'", "a cleared hold is final; hold identity, class and authority are immutable"),
                    ("UPDATE holds SET cleared_at = '2026-09-27T10:00:00Z'", "cleared_at IS NULL OR cleared_by_decision_id IS NOT NULL OR cleared_by_operation_id IS NOT NULL"),
                    ("DELETE FROM holds", "holds are never deleted")):
            with self.subTest(sql=sql):
                self.rejects(fragment, sql)
            self.assertEqual(self.snapshot("holds"), before)
        self.decision("opd_clear00001", "hold_clearance", ref=HOLD)
        self.x("UPDATE holds SET cleared_at = ?, cleared_by_decision_id = 'opd_clear00001' WHERE hold_id = ?", "2026-09-27T10:00:00Z", HOLD)
        self.assertEqual(self.rows("SELECT cleared_by_decision_id FROM holds"), [("opd_clear00001",)])
