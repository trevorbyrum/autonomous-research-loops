"""Recorded history cannot be rewritten through the store's write paths.

Trace: Astra 0a review A1 (critical: INSERT OR REPLACE replaced an operation
receipt; delete-and-reinsert regressed a sink watermark; several tables had no
delete guard); design review §5 (receipts and trigger tombstones survive;
replay protection depends on them); INVARIANTS C-11, RG-1b, P-2.

Oracle: hand-written expectations — every attempt below must raise and leave
the stored rows byte-for-byte unchanged (read back with SELECT *). The
connection applies gen2/store/connection.sql, as the store module must.
What these tests cannot show: that the Phase 1 store module actually applies
the connection contract, or anything about crash recovery.
"""
from __future__ import annotations

import json
import sqlite3
import unittest

from gen2.tests.store_fixtures import TOPIC, StoreTestCase, T, connect, h

# The message of each table's BEFORE DELETE guard fragment we expect a
# REPLACE conflict to surface (the guard, not some other constraint).
DELETE_GUARD = {
    "operation_receipts": "never deleted; replay protection",
    "sink_generations": "high-water mark is never deleted",
    "review_triggers": "review triggers are never deleted",
    "contract_revisions": "contract revisions are never deleted",
    "verification_receipts": "verification receipts are never deleted",
}


class ConnectionContractTest(unittest.TestCase):
    def test_connection_contract_reads_back_on(self) -> None:
        db = connect()
        self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone(), (1,))
        self.assertEqual(db.execute("PRAGMA recursive_triggers").fetchone(), (1,))
        db.close()


class WithoutRecursiveTriggersTest(StoreTestCase):
    """Characterizes why connection.sql's recursive_triggers line is load-bearing:
    without it SQLite skips the DELETE guard during REPLACE conflict
    resolution and a committed receipt is silently rewritten."""

    APPLY_CONNECTION_CONTRACT = False

    def test_replace_rewrites_a_receipt_when_the_connection_contract_is_skipped(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.receipt("op_00000001", "inv_pppppppp", digest="d")
        self.x("INSERT OR REPLACE INTO operation_receipts SELECT operation_id, receipt_id, operation_kind, invocation_id, topic_id, request_fingerprint, ?, lease_id, lease_generation, admission_context, contract_revision, brief_hash, config_bundle_hash, state_revision_before, state_revision_after, validator_version, policy_version, json_set(receipt, '$.payload_digest', ?), committed_at FROM operation_receipts WHERE operation_id = 'op_00000001'", h("0"), h("0"))
        self.assertEqual(self.rows("SELECT payload_digest FROM operation_receipts"), [(h("0"),)])


class ReplaceAndDeleteTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")

    def assertRewriteRefused(self, table: str, sql: str, *params, fragment: str | None = None) -> None:
        before = self.snapshot(table)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.x(sql, *params)
        if fragment is not None:
            self.assertIn(fragment, str(ctx.exception))
        self.assertEqual(self.snapshot(table), before)

    def test_replace_cannot_rewrite_a_receipt_on_any_key(self) -> None:
        self.receipt("op_00000001", "inv_pppppppp", kind="final_outcome", before=0, digest="d")
        cols = "operation_id, receipt_id, operation_kind, invocation_id, topic_id, request_fingerprint, payload_digest, lease_id, lease_generation, admission_context, contract_revision, config_bundle_hash, state_revision_before, state_revision_after, validator_version, policy_version, receipt, committed_at"
        ins = f"INSERT OR REPLACE INTO operation_receipts ({cols}) VALUES (?, ?, ?, 'inv_pppppppp', ?, ?, ?, 'lease_aaaaaaaa', 1, 'contract/1', 1, ?, ?, ?, 'v1', 'p1', ?, ?)"

        def body(op, rid, digest):
            return json.dumps({"operation_id": op, "receipt_id": rid, "payload_digest": digest, "admission": {"context": "contract/1", "contract": {"revision": 1}, "brief": None}})
        guard = DELETE_GUARD["operation_receipts"]
        # primary key: same operation_id, different fingerprint/digest (the review's probe)
        self.assertRewriteRefused("operation_receipts", ins, "op_00000001", "rcpt_00000001", "final_outcome", TOPIC, h("9"), h("0"), h("c"), 0, 1, body("op_00000001", "rcpt_00000001", h("0")), T, fragment=guard)
        # alternate unique key: receipt_id
        self.assertRewriteRefused("operation_receipts", ins, "op_00000002", "rcpt_00000001", "interim_transition", TOPIC, h("9"), h("0"), h("c"), 5, 6, body("op_00000002", "rcpt_00000001", h("0")), T, fragment=guard)
        # partial unique index: one final outcome per invocation
        self.assertRewriteRefused("operation_receipts", ins, "op_00000003", "rcpt_00000003", "final_outcome", TOPIC, h("9"), h("0"), h("c"), 7, 8, body("op_00000003", "rcpt_00000003", h("0")), T, fragment=guard)
        # unique index: one commit per produced state revision
        self.assertRewriteRefused("operation_receipts", ins, "op_00000004", "rcpt_00000004", "interim_transition", TOPIC, h("9"), h("0"), h("c"), 0, 1, body("op_00000004", "rcpt_00000004", h("0")), T, fragment=guard)
        # REPLACE INTO is the same statement under another spelling
        self.assertRewriteRefused("operation_receipts", ins.replace("INSERT OR REPLACE", "REPLACE"), "op_00000001", "rcpt_00000001", "final_outcome", TOPIC, h("9"), h("0"), h("c"), 0, 1, body("op_00000001", "rcpt_00000001", h("0")), T, fragment=guard)
        # upsert DO UPDATE fires the UPDATE guard instead
        self.assertRewriteRefused("operation_receipts", ins.replace("INSERT OR REPLACE", "INSERT") + " ON CONFLICT (operation_id) DO UPDATE SET payload_digest = excluded.payload_digest",
                                  "op_00000001", "rcpt_00000001", "final_outcome", TOPIC, h("9"), h("0"), h("c"), 0, 1, body("op_00000001", "rcpt_00000001", h("0")), T, fragment="operation receipts are immutable")
        self.assertRewriteRefused("operation_receipts", "DELETE FROM operation_receipts", fragment=guard)

    def test_sink_watermark_cannot_regress_by_delete_reinsert_or_replace(self) -> None:
        self.x("INSERT INTO sink_generations VALUES (?, 'qdrant', 2, ?)", TOPIC, T)
        guard = DELETE_GUARD["sink_generations"]
        self.assertRewriteRefused("sink_generations", "DELETE FROM sink_generations WHERE topic_id = ? AND sink = 'qdrant'", TOPIC, fragment=guard)
        self.assertRewriteRefused("sink_generations", "INSERT OR REPLACE INTO sink_generations VALUES (?, 'qdrant', 1, ?)", TOPIC, T, fragment=guard)
        self.assertRewriteRefused("sink_generations", "REPLACE INTO sink_generations VALUES (?, 'qdrant', 1, ?)", TOPIC, T, fragment=guard)
        self.assertEqual(self.rows("SELECT delivered_generation FROM sink_generations"), [(2,)])

    def test_handled_trigger_replayed_after_its_episode_closed_stays_handled(self) -> None:
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition", before=0)
        self.receipt("op_00000002", "inv_pppppppp", kind="interim_transition", before=1)
        self.x("INSERT INTO review_episodes (episode_id, topic_id, kind, opened_at, opened_by_operation_id) VALUES ('ep-1', ?, 'method_fit', ?, 'op_00000001')", TOPIC, T)
        insert = "INSERT INTO review_triggers (trigger_identity, topic_id, reason_code, signal_source, cause_ref, observed_at, episode_id, handled_at) VALUES (?, ?, 'persistent_contradiction', 'deterministic', 'CL-3', ?, ?, ?)"
        self.x(insert, h("1"), TOPIC, T, "ep-1", T)
        self.x("UPDATE review_episodes SET closed_at = ?, closed_by_operation_id = 'op_00000002' WHERE episode_id = 'ep-1'", T)
        guard = DELETE_GUARD["review_triggers"]
        # the gen-1 probe shape: the same trigger replayed, unhandled, after the episode closed
        self.assertRewriteRefused("review_triggers", insert.replace("INSERT", "INSERT OR REPLACE"), h("1"), TOPIC, T, None, None, fragment=guard)
        self.assertRewriteRefused("review_triggers", insert.replace("INSERT", "REPLACE"), h("1"), TOPIC, T, None, None, fragment=guard)
        self.assertRewriteRefused("review_triggers", insert, h("1"), TOPIC, T, None, None, fragment="UNIQUE constraint failed: review_triggers.trigger_identity")
        # OR IGNORE is a no-op, not a reopening
        self.x(insert.replace("INSERT", "INSERT OR IGNORE"), h("1"), TOPIC, T, None, None)
        self.assertEqual(self.rows("SELECT episode_id, handled_at FROM review_triggers"), [("ep-1", T)])
        self.assertEqual(self.rows("SELECT closed_at FROM review_episodes"), [(T,)])

    def test_update_or_replace_cannot_delete_the_approved_contract(self) -> None:
        self.approved_revision(TOPIC)  # revision 1 (already approved for the invocation in setUp)
        self.contract(TOPIC, 2)
        self.decision("opd_00000002", "amendment_approval", rev=2, hsh=self.content_hash_of(TOPIC, 2))
        # approving revision 2 collides with revision 1 on the one-approved index;
        # OR REPLACE would resolve that by deleting revision 1
        self.assertRewriteRefused("contract_revisions", "UPDATE OR REPLACE contract_revisions SET status = 'approved', approved_by_decision_id = 'opd_00000002' WHERE topic_id = ? AND revision = 2", TOPIC,
                                  fragment=DELETE_GUARD["contract_revisions"])


class EveryTableSweepTest(StoreTestCase):
    """Attacks every table of a fully populated store; the oracle is that
    nothing changes. Which guard fires is not asserted here (a BEFORE INSERT
    trigger may fire before the conflict); the isolated tests above pin the
    delete guard itself for the tables replay safety depends on."""

    def setUp(self) -> None:
        super().setUp()
        self.populate_every_table()

    def test_every_table_is_populated(self) -> None:
        empty = [t for t in self.tables() if self.rows(f"SELECT count(*) FROM {t}")[0][0] == 0]
        self.assertEqual(empty, [], "extend StoreTestCase.populate_every_table for new tables")

    # Hand-written oracle: the tables whose rows are records of fact and admit
    # no UPDATE at all (the others move through guarded state machines tested
    # in test_store_ddl.py).
    APPEND_ONLY = ("artifacts", "audit_events", "claim_source_links", "decision_receipts", "decision_specs", "dossiers",
                   "facets", "invocation_transitions", "obligations", "operation_receipts", "operator_decisions", "outbox_events",
                   "quote_checks", "record_work_links", "research_ordinals", "retrieval_events", "screening_assessments",
                   "search_observations", "sink_delivery_receipts", "verification_receipts")

    def test_append_only_tables_reject_every_update(self) -> None:
        for table in self.APPEND_ONLY:
            with self.subTest(table=table):
                first = self.rows(f"SELECT name FROM pragma_table_info('{table}') ORDER BY cid LIMIT 1")[0][0]
                before = self.snapshot(table)
                with self.assertRaises(sqlite3.IntegrityError):
                    self.x(f"UPDATE {table} SET {first} = {first}")  # even a no-op rewrite is refused
                self.assertEqual(self.snapshot(table), before)

    def test_no_table_can_be_deleted_from_or_replaced_into(self) -> None:
        for table in self.tables():
            with self.subTest(table=table):
                before = self.snapshot(table)
                with self.assertRaises(sqlite3.IntegrityError):
                    self.x(f"DELETE FROM {table}")
                self.assertEqual(self.snapshot(table), before)
                with self.assertRaises(sqlite3.IntegrityError):
                    self.x(f"INSERT OR REPLACE INTO {table} SELECT * FROM {table} WHERE rowid = (SELECT min(rowid) FROM {table})")
                self.assertEqual(self.snapshot(table), before)


if __name__ == "__main__":
    unittest.main()
