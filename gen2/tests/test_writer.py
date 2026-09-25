"""The store's writer: JCS storage, identity bounds, all-or-nothing writes.

Trace: task 0b carried-forward requirements — writer-side JCS
canonicalization (0a round 3, RA2 ruling: schema validation does not enforce
storage format) and identity/revision bounds applied by every writer,
generated increments included, with overflow tested without partial writes
(Astra re-review RA8 / round-3 ruling 6); INVARIANTS C-13, C-4, C-11.

Oracles, independent of the code under test: expected stored JSON text
written out by hand from RFC 8785's rules (sorted keys, no whitespace, 1.0
as 1, 1e21 as 1e+21, UTF-8 not escapes); the bound 2**53-1 and its neighbours
written as literals; read-backs after refused or rolled-back writes; and raw
SQL controls showing the DDL alone accepts what the writer refuses (so the
writer is the layer doing the work).

What these tests cannot show: that the router (Phase 1) sends every write
through this module. The boundary graph makes the store module the only
sqlite3 user; it does not prove a caller uses its write path.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from gen2.store import api
from gen2.store.api import IdentityBoundError, StoreWriteError
from gen2.tests import store_fixtures

T = "2026-09-25T12:00:00Z"
TOPIC = "fleet-a:t1"
BOUND = 2**53 - 1


def h(ch: str) -> str:
    return "sha256:" + ch * 64


class WriterTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "store.sqlite3"
        self.store = api.open_store(self.path, create=True)
        with self.store.transaction() as s:
            s.insert("queue_entries", {"topic_id": TOPIC, "fleet_id": "fleet-a", "priority": 1, "status": "awaiting_brief_confirmation",
                                       "created_at": T, "updated_at": T})

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def raw(self, sql: str, *params) -> list[tuple]:
        """A second, contract-applied connection: the DDL alone, no writer."""
        conn = sqlite3.connect(self.path, isolation_level=None)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA recursive_triggers = ON")
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def audit(self, aid: str, detail) -> None:
        with self.store.transaction() as s:
            s.insert("audit_events", {"audit_event_id": aid, "at": T, "kind": "probe", "detail": detail})


class CanonicalStorageTest(WriterTestCase):
    def test_json_is_stored_in_its_jcs_form(self) -> None:
        self.audit("aud_value", {"b": 1, "a": [1.0, "é", 1e21, -0.0], "c": {"z": None, "y": True}})
        self.audit("aud_text", '{ "b" : 1,\n "a" : 2 }')
        self.audit("aud_bytes", b'{"k":"\\u00e9","j":1E2}')
        self.assertEqual(self.store.raw_text("audit_events", "detail", {"audit_event_id": "aud_value"}),
                         ['{"a":[1,"é",1e+21,0],"b":1,"c":{"y":true,"z":null}}'])
        self.assertEqual(self.store.raw_text("audit_events", "detail", {"audit_event_id": "aud_text"}), ['{"a":2,"b":1}'])
        self.assertEqual(self.store.raw_text("audit_events", "detail", {"audit_event_id": "aud_bytes"}), ['{"j":100,"k":"é"}'])
        self.assertEqual(self.store.select("audit_events", {"audit_event_id": "aud_text"})[0]["detail"], {"a": 2, "b": 1})

    def test_unhashable_json_is_refused_and_writes_nothing(self) -> None:
        for case, detail in (("duplicate key", '{"a":1,"a":2}'), ("NaN", {"a": float("nan")}), ("NaN text", '{"a":NaN}'),
                             ("integer beyond 2**53-1", {"a": 2**53}), ("precision loss", '{"a":0.1000000000000000000001}'),
                             ("lone surrogate", {"a": "\ud800"}), ("not JSON", "{")):
            with self.subTest(case=case):
                with self.assertRaises(StoreWriteError):
                    self.audit("aud_refused", detail)
                self.assertEqual(self.raw("SELECT count(*) FROM audit_events"), [(0,)])

    def test_the_ddl_alone_would_keep_non_canonical_text(self) -> None:
        """Control: json_valid admits any JSON text, so storage form is the
        writer's to enforce."""
        self.raw("INSERT INTO audit_events (audit_event_id, at, kind, detail) VALUES ('aud_raw', ?, 'probe', ?)", T, '{ "b": 1, "a": 2 }')
        self.assertEqual(self.raw("SELECT detail FROM audit_events"), [('{ "b": 1, "a": 2 }',)])

    def test_canonical_storage_makes_equal_entries_equal_text(self) -> None:
        """Why it matters to the DDL: the rating binding (RA2) compares a
        facet entry with the rated draft's entry as stored text, minus its
        importance, and fails closed on a difference. The caller writes the
        rated draft's entry with its keys in one order and the next
        revision's (the same subject) in another. Stored canonically, they
        are equal text and the unchanged rating is accepted."""
        def contract(rev: int, parent, entry: dict) -> dict:
            return {"topic_id": TOPIC, "revision": rev, "parent_revision": parent, "created_at": T, "content_hash": h(str(rev)),
                    "protocol_revision": 1, "facet_map": {"framing_version": 1, "facets": [entry]}, "obligations": [],
                    "eligibility_protocol": {"protocol_version": 1}}
        unrated = {"facet_id": "F-1", "label": "effect of X", "kind": "effect", "importance": {"proposed": None, "operator_rating": None}}
        rated = {"importance": {"operator_rating": {"operator_decision_id": "opd_rate0001", "score": 8, "band": "critical"}, "proposed": None},
                 "kind": "effect", "label": "effect of X", "facet_id": "F-1"}
        with self.store.transaction() as s:
            for rev, parent, entry in ((1, None, unrated), (2, 1, rated)):
                s.insert("contract_revisions", {"topic_id": TOPIC, "revision": rev, "parent_revision": parent, "protocol_revision": 1, "framing_version": 1,
                                                "content_hash": h(str(rev)), "document": contract(rev, parent, entry), "status": "draft", "created_at": T})
                if rev == 1:
                    s.insert("operator_decisions", {"decision_id": "opd_rate0001", "topic_id": TOPIC, "kind": "rating_approval", "disposition": "approved",
                                                    "subject_kind": "contract_revision", "subject_ref": TOPIC, "subject_revision": 1, "subject_hash": h("1"),
                                                    "operator_id": "trevor", "decided_at": T,
                                                    "payload": {"obligations": {}, "facets": {"F-1": {"score": 8, "band": "critical"}}}})
            s.insert("facets", {"topic_id": TOPIC, "contract_revision": 2, "facet_id": "F-1", "operator_importance_band": "critical",
                                "operator_importance_score": 8, "operator_rating_decision_id": "opd_rate0001"})
        self.assertEqual(self.raw("SELECT contract_revision, operator_importance_band, operator_importance_score FROM facets"), [(2, "critical", 8)])


class IdentityBoundTest(WriterTestCase):
    def lease(self, lid: str, generation, scope: str = "research") -> None:
        with self.store.transaction() as s:
            s.insert("leases", {"lease_id": lid, "topic_id": TOPIC, "scope": scope, "generation": generation, "station_id": "st1",
                                "granted_at": T, "expires_at": T})

    def test_identity_columns_are_bounded_by_value_on_insert(self) -> None:
        self.lease("lease_topf", 9007199254740990.0, "discovery")  # an integral float in range is the same value
        self.lease("lease_top", BOUND)  # (the DDL: generations strictly increase per topic; one live lease per scope)
        self.assertEqual(self.raw("SELECT generation, typeof(generation) FROM leases ORDER BY generation"),
                         [(BOUND - 1, "integer"), (BOUND, "integer")])
        for value in (2**53, 9007199254740992.0, 9.007199254740992e15, -1, 1.5, True, "7", float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(IdentityBoundError):
                    self.lease("lease_over", value, "checkpoint")
        self.assertEqual(self.raw("SELECT count(*) FROM leases"), [(2,)])
        self.raw("INSERT INTO leases (lease_id, topic_id, scope, generation, station_id, granted_at, expires_at) VALUES ('lease_raw', ?, 'verification', ?, 'st1', ?, ?)",
                 TOPIC, 2**53, T, T)  # control: the DDL's INTEGER accepts 2**53; the writer is the bound
        self.assertEqual(self.raw("SELECT generation FROM leases WHERE lease_id = 'lease_raw'"), [(2**53,)])

    def test_a_generated_increment_past_the_bound_writes_nothing(self) -> None:
        """next_in_sequence refuses max + 1 past 2**53-1, and the transaction
        that asked for it (which had already written a row) leaves nothing."""
        self.lease("lease_top", BOUND)
        with self.assertRaises(IdentityBoundError):
            with self.store.transaction() as s:
                s.insert("artifacts", {"content_hash": h("a"), "size_bytes": 1, "media_type": "text/plain", "staged_at": T})
                s.lease_generation = s.next_in_sequence("leases", "generation", {"topic_id": TOPIC})
        self.assertEqual(self.raw("SELECT count(*) FROM artifacts"), [(0,)])
        self.assertEqual(self.raw("SELECT lease_id, generation FROM leases"), [("lease_top", BOUND)])
        self.assertEqual(self.store.next_in_sequence("leases", "generation", {"topic_id": "fleet-a:none"}), 1)

    def test_advance_is_bounded_and_compare_and_set(self) -> None:
        self.raw("INSERT INTO sink_generations (topic_id, sink, delivered_generation, delivered_at) VALUES (?, 'neo4j', ?, ?), (?, 'qdrant', 5, ?)",
                 TOPIC, BOUND, T, TOPIC, T)
        with self.assertRaises(IdentityBoundError):
            with self.store.transaction() as s:
                s.insert("artifacts", {"content_hash": h("b"), "size_bytes": 1, "media_type": "text/plain", "staged_at": T})
                s.advance("sink_generations", {"topic_id": TOPIC, "sink": "neo4j"}, "delivered_generation", expected=BOUND)
        self.assertEqual(self.raw("SELECT count(*) FROM artifacts"), [(0,)])
        with self.assertRaises(IdentityBoundError):
            with self.store.transaction() as s:
                s.update("sink_generations", {"topic_id": TOPIC, "sink": "qdrant"}, {"delivered_generation": 2**53})
        with self.assertRaises(StoreWriteError):  # stale expectation: nothing matches, nothing changes
            with self.store.transaction() as s:
                s.advance("sink_generations", {"topic_id": TOPIC, "sink": "qdrant"}, "delivered_generation", expected=4)
        with self.store.transaction() as s:
            self.assertEqual(s.advance("sink_generations", {"topic_id": TOPIC, "sink": "qdrant"}, "delivered_generation", expected=5), 6)
        self.assertEqual(self.raw("SELECT sink, delivered_generation FROM sink_generations ORDER BY sink"), [("neo4j", BOUND), ("qdrant", 6)])
        self.raw("UPDATE sink_generations SET delivered_generation = ? WHERE sink = 'neo4j'", 2**53)  # control: the DDL accepts it
        self.assertEqual(self.raw("SELECT delivered_generation FROM sink_generations WHERE sink = 'neo4j'"), [(2**53,)])

    def test_every_integer_column_is_classified_once(self) -> None:
        """A new INTEGER column cannot land unbounded by accident: each is an
        identity, a flag, a score or a measure — exactly one — and every
        classified name exists in the DDL."""
        sets = {"identity": api.IDENTITY_COLUMNS, "flag": api.FLAG_COLUMNS, "score": api.SCORE_COLUMNS, "measure": api.MEASURE_COLUMNS}
        seen = set()
        for table, columns in api.integer_columns(self.store).items():
            for column in columns:
                homes = [name for name, members in sets.items() if column in members]
                self.assertEqual(len(homes), 1, f"{table}.{column} is classified as {homes}")
                seen.add(column)
        self.assertEqual(set().union(*sets.values()) - seen, set())

    def test_other_integers_stay_json_interoperable(self) -> None:
        with self.store.transaction() as s:
            s.insert("artifacts", {"content_hash": h("c"), "size_bytes": BOUND, "media_type": "text/plain", "staged_at": T})
        for value in (2**53, -(2**53), True, 1.0):
            with self.subTest(value=value):
                with self.assertRaises(StoreWriteError):
                    with self.store.transaction() as s:
                        s.insert("artifacts", {"content_hash": h("d"), "size_bytes": value, "media_type": "text/plain", "staged_at": T})
        self.assertEqual(self.raw("SELECT size_bytes FROM artifacts"), [(BOUND,)])


def fact(fid: str, superseded_by: str | None = None) -> dict:
    return {"fact_id": fid, "capability": "gateway.crossref", "state": "healthy", "detail": fid, "since": T, "affected_lanes": ["research"],
            "superseded_by_fact_id": superseded_by, "recorded_at": T}


def artifact(ch: str) -> dict:
    return {"content_hash": h(ch), "size_bytes": 1, "media_type": "text/plain", "staged_at": T}


def deny(*statements: str):
    """An SQLite authorizer refusing the named transaction statements
    (fault injection through SQLite's own mechanism, not a mock)."""
    def authorizer(action, arg1, *_):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and arg1 in statements else sqlite3.SQLITE_OK
    return authorizer


class WritePathTest(WriterTestCase):
    def test_writes_run_inside_a_transaction(self) -> None:
        with self.assertRaises(Exception) as ctx:
            self.store.insert("artifacts", artifact("e"))
        self.assertIsInstance(ctx.exception, StoreWriteError)
        self.assertEqual(self.raw("SELECT count(*) FROM artifacts"), [(0,)])

    def test_writes_need_the_stores_own_transaction(self) -> None:
        """A transaction SQLite reports on the connection, but that
        Store.transaction() did not open, does not admit writes (the review's
        A1 step 5: after the failed COMMIT, an insert outside any context was
        accepted because only SQLite's flag was checked). Fault injection: the
        test opens that transaction on the Store's private connection."""
        self.store._conn.execute("BEGIN")
        try:
            with self.assertRaises(Exception) as ctx:
                self.store.insert("artifacts", artifact("o"))
            self.assertIsInstance(ctx.exception, StoreWriteError)
        finally:
            self.store._conn.execute("ROLLBACK")
        self.assertEqual(self.raw("SELECT count(*) FROM artifacts"), [(0,)])

    def test_a_ddl_refusal_propagates_and_rolls_back_the_transaction(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            with self.store.transaction() as s:
                s.insert("artifacts", artifact("f"))
                s.insert("queue_entries", {"topic_id": "fleet-a:t2", "fleet_id": "fleet-a", "priority": 1, "status": "active", "created_at": T, "updated_at": T})
        self.assertIn("created awaiting brief confirmation", str(ctx.exception))
        self.assertEqual(self.raw("SELECT count(*) FROM artifacts"), [(0,)])
        self.assertEqual(self.raw("SELECT topic_id FROM queue_entries"), [(TOPIC,)])

    def test_a_refusal_at_commit_rolls_back_and_the_store_stays_usable(self) -> None:
        """Astra 0b review A1, the review's reproduction: the successor FK of a
        capability fact is DEFERRABLE INITIALLY DEFERRED, so linking a
        successor that is never inserted is refused by COMMIT itself, after
        every statement succeeded. Nothing of that transaction persists (on
        a second connection, and on the Store's own), the Store is not left
        inside it (writes outside a context are refused, and a new
        transaction is not "nested"), and completing the supersession later
        does not bring the failed batch's audit event back."""
        with self.store.transaction() as s:
            s.insert("capability_facts", fact("cf_old"))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            with self.store.transaction() as s:
                s.insert("audit_events", {"audit_event_id": "aud_lost", "at": T, "kind": "probe", "detail": {}})
                s.update("capability_facts", {"fact_id": "cf_old"}, {"superseded_by_fact_id": "cf_missing"})
        self.assertEqual(str(ctx.exception), "FOREIGN KEY constraint failed")
        self.assertEqual(getattr(ctx.exception, "__notes__", []), [])  # rolled back normally: the Store is not closed
        self.assertEqual(self.raw("SELECT count(*) FROM audit_events"), [(0,)])  # a second connection
        self.assertEqual(self.raw("SELECT fact_id, superseded_by_fact_id FROM capability_facts"), [("cf_old", None)])
        self.assertEqual(self.store.select("audit_events"), [])  # the Store's own connection sees the same
        self.assertEqual([(r["fact_id"], r["superseded_by_fact_id"]) for r in self.store.select("capability_facts")], [("cf_old", None)])
        with self.assertRaises(Exception) as outside:
            self.store.insert("audit_events", {"audit_event_id": "aud_outside", "at": T, "kind": "probe", "detail": {}})
        self.assertIsInstance(outside.exception, StoreWriteError)
        with self.store.transaction() as s:  # the same connection: a new transaction, not a nested one
            s.update("capability_facts", {"fact_id": "cf_old"}, {"superseded_by_fact_id": "cf_new"})
            s.insert("capability_facts", fact("cf_new"))
        self.assertEqual(self.raw("SELECT fact_id, superseded_by_fact_id FROM capability_facts ORDER BY fact_id"), [("cf_new", None), ("cf_old", "cf_new")])
        self.assertEqual(self.raw("SELECT count(*) FROM audit_events"), [(0,)])

    def test_a_transaction_sqlite_already_ended_is_not_rolled_back_again(self) -> None:
        """An interrupted INSERT inside a transaction makes SQLite roll the
        whole transaction back itself. The interrupt is what propagates: an
        unconditional ROLLBACK here would raise "no transaction is active"
        in its place (A1: never mask the original failure). Fault injection:
        a progress handler interrupting the statement, set on the Store's
        private connection."""
        with self.assertRaises(sqlite3.OperationalError) as ctx:
            with self.store.transaction() as s:
                s.insert("artifacts", artifact("i"))
                s._conn.set_progress_handler(lambda: 1, 1)
                try:
                    s.insert("artifacts", artifact("j"))
                finally:
                    s._conn.set_progress_handler(None, 1)
        self.assertEqual(str(ctx.exception), "interrupted")
        self.assertEqual(getattr(ctx.exception, "__notes__", []), [])
        self.assertEqual(self.raw("SELECT count(*) FROM artifacts"), [(0,)])
        with self.store.transaction() as s:
            s.insert("artifacts", artifact("k"))
        self.assertEqual(self.raw("SELECT content_hash FROM artifacts"), [(h("k"),)])

    def test_a_failed_rollback_closes_the_connection_and_the_store_refuses_use(self) -> None:
        """COMMIT refused and ROLLBACK working (the review's authorizer
        variant): nothing persists and the Store stays usable. COMMIT and
        ROLLBACK both refused: the Store cannot show its connection holds
        nothing, so it closes it (SQLite discards the open transaction) and
        refuses further use. Either way COMMIT's own error is what
        propagates. Fault injection: an SQLite authorizer on the Store's
        private connection."""
        with self.assertRaises(sqlite3.DatabaseError) as ctx:
            with self.store.transaction() as s:
                s.insert("artifacts", artifact("l"))
                s._conn.set_authorizer(deny("COMMIT"))
        self.store._conn.set_authorizer(None)
        self.assertEqual((str(ctx.exception), getattr(ctx.exception, "__notes__", [])), ("not authorized", []))
        self.assertEqual(self.raw("SELECT count(*) FROM artifacts"), [(0,)])
        with self.store.transaction() as s:
            s.insert("artifacts", artifact("m"))
        with self.assertRaises(sqlite3.DatabaseError) as ctx:
            with self.store.transaction() as s:
                s.insert("artifacts", artifact("n"))
                s._conn.set_authorizer(deny("COMMIT", "ROLLBACK"))
        notes = getattr(ctx.exception, "__notes__", [])
        self.assertEqual((str(ctx.exception), len(notes)), ("not authorized", 1))
        self.assertIn("ROLLBACK failed", notes[0])
        self.assertIn("this Store refuses further use", notes[0])
        self.assertEqual(self.raw("SELECT content_hash FROM artifacts"), [(h("m"),)])
        self.raw("INSERT INTO audit_events (audit_event_id, at, kind, detail) VALUES ('aud_after', ?, 'probe', '{}')", T)  # no write lock is left held
        for attempt in (lambda: self.store.transaction().__enter__(), lambda: self.store.insert("artifacts", artifact("p"))):
            with self.assertRaises(Exception) as refused:
                attempt()
            self.assertIsInstance(refused.exception, StoreWriteError)
            self.assertIn("closed after a failed transaction", str(refused.exception))

    def test_an_update_touches_exactly_one_row(self) -> None:
        self.raw("INSERT INTO sink_generations (topic_id, sink, delivered_generation, delivered_at) VALUES (?, 'neo4j', 3, ?), (?, 'qdrant', 3, ?)", TOPIC, T, TOPIC, T)
        with self.assertRaises(StoreWriteError):
            with self.store.transaction() as s:
                s.update("sink_generations", {"topic_id": TOPIC}, {"delivered_generation": 4})
        self.assertEqual(self.raw("SELECT delivered_generation FROM sink_generations"), [(3,), (3,)])

    def test_names_come_from_the_schema_only(self) -> None:
        for table, row in (("no_such_table", {"a": 1}), ("artifacts", {"content_hash": h("g"), "size_bytes": 1, "media_type": "x", "staged_at": T, "extra": 1}),
                           ("artifacts; DROP TABLE artifacts", {"a": 1})):
            with self.subTest(table=table):
                with self.assertRaises(StoreWriteError):
                    with self.store.transaction() as s:
                        s.insert(table, row)
        for table in ("no_such_table", "artifacts; DROP TABLE artifacts"):  # a read with no conditions names no column to check
            with self.subTest(read=table):
                with self.assertRaises(Exception) as ctx:
                    self.store.select(table)
                self.assertIsInstance(ctx.exception, StoreWriteError)
        self.assertEqual(self.raw("SELECT count(*) FROM sqlite_schema WHERE name = 'artifacts'"), [(1,)])


class ReceiptHashContractWriterTest(store_fixtures.StoreTestCase):
    """C-13 / Astra 0a ruling R1 (frozen in 0b), at the writer: a receipt
    whose recorded hash contract is not the frozen one is refused before any
    SQL runs (StoreWriteError, not the DDL's IntegrityError), and a receipt
    recording it is written. Rows come from the DDL-test fixtures (an
    in-memory store with the connection contract), written through Store."""

    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.store = api.Store(self.db, {})

    def commit_receipt(self, hash_contract) -> None:
        body = self.receipt_body("op_00000001", "rcpt_00000001", "final_outcome", "inv_pppppppp", TOPIC, 0, digest=h("d"))
        store_fixtures._override(body, {"hash_contract": hash_contract})
        rev = body["admission"]["contract"]["revision"]
        with self.store.transaction() as s:
            s.insert("operation_receipts", {
                "operation_id": "op_00000001", "receipt_id": "rcpt_00000001", "operation_kind": "final_outcome", "invocation_id": "inv_pppppppp",
                "topic_id": TOPIC, "request_fingerprint": h("f"), "payload_digest": h("d"), "lease_id": "lease_aaaaaaaa", "lease_generation": 1,
                "admission_context": "contract/1", "contract_revision": rev, "brief_hash": None, "config_bundle_hash": h("c"),
                "state_revision_before": 0, "state_revision_after": 1, "validator_version": "v1", "policy_version": "p1", "receipt": body, "committed_at": T})

    def test_commit_receipt_contract_checked_before_sql(self) -> None:
        for case, value in (("absent", store_fixtures.DROP), ("another fingerprint", {"canonicalization": "jcs-rfc8785/1", "fingerprint": "commit-fingerprint/2"}),
                            ("fingerprint missing", {"canonicalization": "jcs-rfc8785/1"})):
            with self.subTest(case=case):
                with self.assertRaises(Exception) as ctx:
                    self.commit_receipt(value)
                self.assertIsInstance(ctx.exception, StoreWriteError)
                self.assertEqual(self.rows("SELECT count(*) FROM operation_receipts"), [(0,)])
        self.commit_receipt({"fingerprint": "commit-fingerprint/1", "canonicalization": "jcs-rfc8785/1"})
        self.assertEqual(self.rows("SELECT json_extract(receipt, '$.hash_contract') FROM operation_receipts"),
                         [('{"canonicalization":"jcs-rfc8785/1","fingerprint":"commit-fingerprint/1"}',)])

    def test_decision_receipt_contract_checked_before_sql(self) -> None:
        spec = self.spec()
        self.decision_receipt("dec_00000001", "inv_pppppppp", spec)  # the fixture's own row: gives a valid receipt to copy
        row = dict(zip([d[0] for d in self.db.execute("SELECT * FROM decision_receipts").description], self.rows("SELECT * FROM decision_receipts")[0]))
        body = json.loads(row["receipt"])
        for case, value in (("absent", store_fixtures.DROP), ("a fingerprint contract", {"canonicalization": "jcs-rfc8785/1", "fingerprint": "commit-fingerprint/1"})):
            with self.subTest(case=case):
                doc = dict(body, decision_receipt_id="dec_00000002")
                store_fixtures._override(doc, {"hash_contract": value})
                with self.assertRaises(Exception) as ctx:
                    with self.store.transaction() as s:
                        s.insert("decision_receipts", dict(row, decision_receipt_id="dec_00000002", receipt=doc))
                self.assertIsInstance(ctx.exception, StoreWriteError)
        with self.store.transaction() as s:
            s.insert("decision_receipts", dict(row, decision_receipt_id="dec_00000002", receipt=dict(body, decision_receipt_id="dec_00000002")))
        self.assertEqual(self.rows("SELECT count(*) FROM decision_receipts"), [(2,)])


if __name__ == "__main__":
    unittest.main()
