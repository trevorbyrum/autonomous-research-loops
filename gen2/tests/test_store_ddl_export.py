"""Constraint tests for the gen-2 store DDL draft: the export tables — outbox
events, per-connector delivery receipts, watermarks
(gen2/store/schema/04-registries-and-export.sql, "Export").

Split from test_store_ddl.py by concern (task 2r): the classes, their
methods and assertions are unchanged.

Trace: task 0a deliverable 3 ("Uniqueness/fencing constraints expressed in
DDL where SQLite allows"); invariant IDs refer to docs/gen2/INVARIANTS.md.

What these tests show: the named constraint or trigger rejects the stated
row. Where a test also shows the same write minus the violation being
accepted, that control rules out an unrelated failure (such as a missing
foreign key); the few tests without such a control say so. Every
connection applies gen2/store/connection.sql (store_fixtures.connect). What
they cannot show: that the router uses these tables correctly, that crash recovery or
replay behave (RG-1a/RG-1b need Phase 1 fault-injection tests against the
router), or anything about concurrency. They test the draft schema only.
"""
from __future__ import annotations

import sqlite3
import unittest

from gen2.tests.store_fixtures import OTHER, TOPIC, StoreTestCase, T, h


class ExportOutboxTest(StoreTestCase):
    """The one outbound path (task 0d, operator ruling 2026-09-26). An outbox
    event's manifest is the export manifest; receipts and watermarks are per
    connector, and no database product is named anywhere in the store. Each
    test says which publication-table rule it carries, or that it is new with
    the connector contract (docs/gen2/EXPORT-API.md). Oracle: hand-written
    near-misses, each differing from an accepted row in one dimension, beside
    the accepted row itself."""

    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition")

    def capability_fact(self) -> None:
        self.x("INSERT INTO capability_facts (fact_id, capability, state, detail, since, affected_lanes, recorded_at) "
               "VALUES ('cf-1', 'export.connector.warehouse', 'failing', 'connection refused', ?, '[]', ?)", T, T)

    def test_only_approved_work_is_exported(self) -> None:
        """D46 rewrite (A2), carried from the publication outbox unchanged: the
        approval must be an approved publication_approval of this topic about
        exactly the exported source revision and hash. Each near-miss matches
        the exported source in every dimension but one; the wrong-kind probe is
        the review's (an approved rating decision) with its subject
        revision/hash made to coincide with the source's."""
        src = h("5")
        rated = self.content_hash_of(TOPIC, 1)
        probes = (
            ("opd_rejected", dict(disposition="rejected", rev=3, hsh=src), 3, src),
            ("opd_wronghsh", dict(rev=3, hsh=h("4")), 3, src),
            ("opd_stalerev", dict(rev=2, hsh=src), 3, src),
            ("opd_othertop", dict(tid=OTHER, rev=3, hsh=src), 3, src),
        )
        for did, kwargs, rev, hsh in probes:
            self.decision(did, "publication_approval", **kwargs)
        self.decision("opd_rating01", "rating_approval", rev=1, hsh=rated)
        for did, rev, hsh in [(d, r, x) for d, _, r, x in probes] + [("opd_rating01", 1, rated)]:
            with self.subTest(decision=did):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000001", "man_00000001", 1, None, did, h("1"), source_rev=rev, source_hash=hsh)
                self.assertIn("unapproved work is never exported", str(ctx.exception))
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=src)
        with self.assertRaises(sqlite3.IntegrityError):  # a valid approval exists, but is not the one named
            self.outbox("obx_00000001", "man_00000001", 1, None, "opd_rejected", h("1"), source_rev=3, source_hash=src)
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), source_rev=3, source_hash=src)

    def test_manifest_json_matches_its_columns(self) -> None:
        """Carried, and extended to what export-manifest/2 adds: the ordering
        pair, the bundle identity, the connectors and the superseded pair are
        each bound to the stored manifest, one probe per column."""
        src = h("5")
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=src)
        for override in ({"source": {"revision": 3, "content_hash": h("4")}}, {"source": {"revision": 2, "content_hash": src}},
                         {"approval": {"operator_decision_id": "opd_other", "approved_revision": 3}},
                         {"approval": {"operator_decision_id": "opd_00000002", "approved_revision": 2}}, {"artifact_kind": "evidence_correction"},
                         {"generation": 2}, {"options_revision": 2},
                         {"bundle": {"bundle_id": "exb_00000001", "bundle_version": "export-bundle/1", "content_hash": h("0")}},
                         {"expected_connectors": {"warehouse": {"connector_type": "sql"}}},
                         {"supersedes": {"manifest_id": "man_x", "generation": 1, "options_revision": None}},
                         {"supersedes": {"manifest_id": "man_x", "generation": None, "options_revision": 1}}):
            with self.subTest(override=override):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), source_rev=3, source_hash=src, manifest_overrides=override)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), source_rev=3, source_hash=src)

    def test_ordering_pairs_strictly_increase(self) -> None:
        """Carries test_generations_strictly_increase to the pair
        (generation, options_revision): a lower generation is refused however
        high its options revision, and so is a lower options revision of the
        same generation that is not a duplicate; a higher generation needs no
        higher options revision."""
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=h("5"))
        self.outbox("obx_00000001", "man_00000001", 2, 1, "opd_00000002", h("1"))
        self.outbox("obx_00000002", "man_00000002", 2, 2, "opd_00000002", h("2"), options=3, sup_options=1)
        for name, gen, opt, sup in (("a lower generation with a higher options revision", 1, 5, None),
                                    ("a lower options revision of the same generation", 2, 2, 1)):
            with self.subTest(probe=name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000003", "man_00000003", gen, sup, "opd_00000002", h("3"), options=opt)
                self.assertIn("strictly increase", str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError):  # the same pair again
            self.outbox("obx_00000003", "man_00000003", 2, 2, "opd_00000002", h("3"), options=3, sup_options=1)
        self.outbox("obx_00000003", "man_00000003", 3, 2, "opd_00000002", h("3"), options=1, sup_options=3)

    def test_one_generation_is_one_approved_revision(self) -> None:
        """New with the ordering pair: a re-export of generation 2 under a
        later options revision keeps the generation's approval and kind. The
        source revision/hash differ only together with the approval (an
        approval names exactly one revision and hash), so they are one probe;
        a second approval of the same revision and a different kind are each
        their own."""
        src = h("5")
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=src)
        self.decision("opd_reapprov", "publication_approval", rev=3, hsh=src)
        self.decision("opd_rev4appr", "publication_approval", rev=4, hsh=h("4"))
        self.outbox("obx_00000001", "man_00000001", 2, None, "opd_00000002", h("1"), source_rev=3, source_hash=src)
        for name, decision, rev, hsh, kind in (("another approved revision", "opd_rev4appr", 4, h("4"), "completion_publication"),
                                               ("another approval of the same revision", "opd_reapprov", 3, src, "completion_publication"),
                                               ("another artifact kind", "opd_00000002", 3, src, "evidence_correction")):
            with self.subTest(probe=name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000002", "man_00000002", 2, 2, decision, h("2"), options=2, source_rev=rev, source_hash=hsh, kind=kind)
                self.assertIn("one generation is one approved revision", str(ctx.exception))
        self.outbox("obx_00000002", "man_00000002", 2, 2, "opd_00000002", h("2"), options=2, source_rev=3, source_hash=src)
        self.outbox("obx_00000003", "man_00000003", 3, 2, "opd_rev4appr", h("3"), options=1, sup_options=2, source_rev=4, source_hash=h("4"))

    def test_supersession_names_a_lower_pair(self) -> None:
        """Carries the publication CHECKs (a superseded generation is lower;
        generation 1 supersedes no earlier generation) to pairs: the superseded
        pair is complete, at least (1, 1), and strictly lower. Generation 1 may
        supersede its own lower options revision."""
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=h("5"))
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"))
        for name, gen, opt, sgen, sopt in (("a later generation", 2, 1, 3, 1), ("the same pair", 2, 2, 2, 2),
                                           ("a higher options revision of the same generation", 2, 2, 2, 3),
                                           ("generation 0", 2, 1, 0, 1), ("options revision 0", 2, 1, 1, 0),
                                           ("a generation without its options revision", 2, 1, 1, None)):
            with self.subTest(probe=name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000002", "man_00000002", gen, sgen, "opd_00000002", h("2"), options=opt, sup_options=sopt)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.outbox("obx_00000002", "man_00000002", 1, 1, "opd_00000002", h("2"), options=2, sup_options=1)
        self.outbox("obx_00000003", "man_00000003", 2, 1, "opd_00000002", h("3"), options=1, sup_options=5)

    def test_manifest_names_only_declared_connector_types(self) -> None:
        """New (the store's side of the undeclared-connector-type negative that
        replaces the named-store-as-sink negative): every connector a manifest names is an
        object of a declared type, and the connectors are a non-empty object —
        the retired publication shape, an array of names, is refused even when
        its elements look like connectors."""
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=h("5"))
        for text in ('{"warehouse": {"connector_type": "graph_store"}}', '{"warehouse": "sql"}', '{"warehouse": {}}',
                     '{"warehouse": {"connector_type": "sql"}, "index": {"connector_type": "vector_store"}}'):
            with self.subTest(connectors=text):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), connectors_json=text)
                self.assertIn("declared type", str(ctx.exception))
        for text in ('[{"connector_type": "sql"}]', '{}'):
            with self.subTest(connectors=text):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), connectors_json=text)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"),
                    connectors_json='{"a": {"connector_type": "sql"}, "b": {"connector_type": "jsonl_file"}, "c": {"connector_type": "webhook"}, '
                                    '"d": {"connector_type": "extension", "implementation": {"module": "research_export_d.connector", "review_ref": "r"}}}')

    def test_delivery_receipt_only_for_named_connectors(self) -> None:
        """D48 rewrite, carried: membership, not vocabulary. The manifest names
        only `warehouse` (sql). A receipt for `archive` — a well-formed id of a
        declared type — is refused, and so is `warehouse` under another type;
        `warehouse` as sql is accepted."""
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=h("5"))
        self.capability_fact()
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), connectors={"warehouse": "sql"})
        for name, row in (("another connector", {"connector_id": "archive"}), ("the named connector as another type", {"connector_type": "jsonl_file"})):
            with self.subTest(probe=name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.delivery(**row)
                self.assertIn("does not name", str(ctx.exception))
        self.delivery(status="failed", tombstones_acknowledged=0, error_class="timeout", capability_fact_id="cf-1", acked_at=None)
        self.delivery(export_receipt_id="exr_00000002", attempt=2)

    def test_receipt_status_rules(self) -> None:
        """Carries the two publication CHECKs (a failure names its class; a
        delivery is acknowledged with its tombstones) and adds the receipt
        schema's other status rules, so the store cannot hold a receipt the
        contract refuses (P-7, H-2, A2). Each probe changes one field of a
        valid receipt of that status; the four valid receipts are accepted
        after them."""
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=h("5"))
        self.capability_fact()
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), connectors={"warehouse": "sql"})
        valid = {
            "delivered": {},
            "failed": {"status": "failed", "tombstones_acknowledged": 0, "error_class": "timeout", "capability_fact_id": "cf-1", "acked_at": None},
            "outcome_unknown": {"status": "outcome_unknown", "tombstones_acknowledged": 0, "reconciliation_required": 1,
                                "unknown_cause": "no_response_after_send", "capability_fact_id": "cf-1", "acked_at": None},
            "skipped_superseded": {"status": "skipped_superseded", "tombstones_acknowledged": 0, "acked_at": None},
        }
        probes = (
            ("a status the contract does not have (a queued request is not delivered)", "skipped_superseded", {"status": "queued"}),
            ("a failure without its class", "failed", {"error_class": None}),
            ("an error class on a delivery", "delivered", {"error_class": "timeout"}),
            ("an unreadable response as a failure class", "failed", {"error_class": "unreadable_response"}),
            ("a delivery without an acknowledgement time", "delivered", {"acked_at": None}),
            ("a delivery that did not acknowledge its tombstones", "delivered", {"tombstones_acknowledged": 0}),
            ("an acknowledgement time on a failure", "failed", {"acked_at": T}),
            ("tombstones acknowledged by a skipped delivery", "skipped_superseded", {"tombstones_acknowledged": 1}),
            ("an unknown outcome without its cause", "outcome_unknown", {"unknown_cause": None}),
            ("an unknown cause on a settled failure", "failed", {"unknown_cause": "unreadable_response"}),
            ("an unknown cause outside the vocabulary", "outcome_unknown", {"unknown_cause": "timeout"}),
            ("an unknown outcome not reconciled", "outcome_unknown", {"reconciliation_required": 0}),
            ("reconciliation left open on a settled result", "skipped_superseded", {"reconciliation_required": 1}),
            ("a failure without its capability fact", "failed", {"capability_fact_id": None}),
            ("an unknown outcome without its capability fact", "outcome_unknown", {"capability_fact_id": None}),
            ("a capability fact on a delivery", "delivered", {"capability_fact_id": "cf-1"}),
        )
        for name, status, change in probes:
            with self.subTest(probe=name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.delivery(**{**valid[status], **change})
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        for attempt, row in enumerate(valid.values(), start=1):
            self.delivery(export_receipt_id=f"exr_0000000{attempt}", attempt=attempt, **row)
        self.assertEqual(self.rows("SELECT count(*) FROM export_delivery_receipts"), [(4,)])

    def delivering(self) -> None:
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=h("5"))
        self.capability_fact()
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), connectors={"warehouse": "sql"})

    def test_receipt_document_matches_its_columns(self) -> None:
        """Astra 1b review A2 (EXPORT-API.md §9 item 3): the receipt is stored
        whole, and each column is bound to it — one probe per column, each a
        document that differs from its row in that field alone. What no column
        holds (the count's reason, the invocation) is kept in the document."""
        self.delivering()
        for override in ({"receipt_version": "export-delivery-receipt/1"}, {"export_receipt_id": "exr_00000009"}, {"manifest_id": "man_00000009"},
                         {"connector": {"connector_id": "archive", "connector_type": "sql"}}, {"connector": {"connector_id": "warehouse", "connector_type": "jsonl_file"}},
                         {"attempt": 2}, {"status": "skipped_superseded"}, {"tombstones_acknowledged": False}, {"reconciliation_required": True},
                         {"error_class": "timeout"}, {"unknown_cause": "unreadable_response"}, {"capability_fact_id": "cf-1"},
                         {"written": {"status": "partial", "value": 12, "reason": "r"}}, {"written": {"status": "observed", "value": 11}},
                         {"hold_id": "hold_00000001"}, {"attempted_at": "2026-09-25T12:00:01Z"}, {"acked_at": None}):
            with self.subTest(override=override):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.delivery(receipt_overrides=override)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.delivery(status="outcome_unknown", tombstones_acknowledged=0, reconciliation_required=1, unknown_cause="no_response_after_send",
                      capability_fact_id="cf-1", acked_at=None, written_status="partial", written_value=7, receipt_overrides={"invocation_id": "inv_pppppppp"})
        self.assertEqual(self.rows("SELECT written_status, written_value, json_extract(receipt, '$.written.reason'), json_extract(receipt, '$.invocation_id') "
                                   "FROM export_delivery_receipts"), [("partial", 7, "not every write was acknowledged", "inv_pppppppp")])

    def test_written_count_rules(self) -> None:
        """The receipt schema's count rules (observed_count; RG-U: unknown is
        never zero), now that the count is a column: each probe breaks one
        rule of an otherwise valid receipt of that status; the six valid
        shapes are accepted after them."""
        self.delivering()
        failed = {"status": "failed", "tombstones_acknowledged": 0, "error_class": "timeout", "capability_fact_id": "cf-1", "acked_at": None}
        unknown = {"status": "outcome_unknown", "tombstones_acknowledged": 0, "reconciliation_required": 1, "unknown_cause": "no_response_after_send",
                   "capability_fact_id": "cf-1", "acked_at": None}
        valid = {
            "delivered": {},
            "failed": failed,
            "partial_write": {**failed, "error_class": "partial_write"},
            "unknown": unknown,
            "unknown_partial": {**unknown, "written_status": "partial", "written_value": 3},
            "skipped": {"status": "skipped_superseded", "tombstones_acknowledged": 0, "acked_at": None},
        }
        probes = (
            ("an unknown count with a value", "unknown", {"written_status": "unknown", "written_value": 0}),
            ("an observed count without a value", "delivered", {"written_status": "observed", "written_value": None}),
            ("a delivery reporting a partial count", "delivered", {"written_status": "partial", "written_value": 12}),
            ("a skipped delivery whose count is unknown", "skipped", {"written_status": "unknown", "written_value": None}),
            ("a skipped delivery that wrote records", "skipped", {"written_status": "observed", "written_value": 3}),
            ("a partial write claiming an observed total", "partial_write", {"written_status": "observed", "written_value": 7}),
            ("a refusal claiming it wrote records", "failed", {"written_status": "observed", "written_value": 3}),
            ("a refusal reporting a partial count", "failed", {"written_status": "partial", "written_value": 0}),
            ("an unknown outcome claiming an observed count", "unknown", {"written_status": "observed", "written_value": 0}),
        )
        for name, shape, change in probes:
            with self.subTest(probe=name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.delivery(**{**valid[shape], **change})
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        for attempt, row in enumerate(valid.values(), start=1):
            self.delivery(export_receipt_id=f"exr_0000000{attempt}", attempt=attempt, **row)
        self.assertEqual(self.rows("SELECT written_status, written_value FROM export_delivery_receipts ORDER BY attempt"),
                         [("observed", 12), ("observed", 0), ("partial", 7), ("unknown", None), ("partial", 3), ("observed", 0)])

    def test_receipt_describes_its_manifest(self) -> None:
        """A receipt's topic and ordering pair are its manifest's (P-2), and a
        hold it names is a recorded hold of that topic (H-3): one probe each,
        then the receipt naming this topic's hold is accepted."""
        self.delivering()
        insert = ("INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, deadline_at, clears_when, capability_fact_id, created_at) "
                  "VALUES (?, ?, 'export:warehouse', 'capability', 'connector down', 'needs_remediation', 'router', 'router', ?, 'connector healthy', 'cf-1', ?)")
        self.x(insert, "hold_00000001", TOPIC, T, T)
        self.x(insert, "hold_00000002", OTHER, T, T)
        for name, change in (("another topic", {"receipt_overrides": {"topic_id": OTHER}}), ("another generation", {"receipt_overrides": {"generation": 2}}),
                             ("another options revision", {"receipt_overrides": {"options_revision": 2}}),
                             ("a hold of another topic", {"hold_id": "hold_00000002"}), ("a hold never recorded", {"hold_id": "hold_00000009"})):
            with self.subTest(probe=name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.delivery(**change)
                self.assertIn("describes its manifest", str(ctx.exception))
        self.delivery(hold_id="hold_00000001")

    def test_connector_watermark_never_regresses(self) -> None:
        """Carries test_sink_generation_never_regresses to the pair: an idempotent
        retry is accepted; a lower generation (whatever its options revision)
        and a lower options revision of the same generation are refused, and so
        are the regression paths that bypass an UPDATE guard (A1)."""
        self.x("INSERT INTO connector_watermarks VALUES (?, 'archive', 2, 3, ?)", TOPIC, T)
        self.x("UPDATE connector_watermarks SET generation = 2, options_revision = 3, delivered_at = ? WHERE topic_id = ? AND connector_id = 'archive'", T, TOPIC)
        for name, gen, opt in (("a lower generation with a higher options revision", 1, 9), ("a lower options revision of the same generation", 2, 2)):
            with self.subTest(probe=name):
                self.rejects("never regresses", "UPDATE connector_watermarks SET generation = ?, options_revision = ? WHERE topic_id = ? AND connector_id = 'archive'", gen, opt, TOPIC)
        for column, value in (("topic_id", OTHER), ("connector_id", "warehouse")):
            with self.subTest(identity=column):
                self.rejects("never regresses", f"UPDATE connector_watermarks SET {column} = ? WHERE topic_id = ? AND connector_id = 'archive'", value, TOPIC)
        self.rejects("connector watermark is never deleted", "DELETE FROM connector_watermarks WHERE topic_id = ? AND connector_id = 'archive'", TOPIC)
        self.rejects("connector watermark is never deleted", "INSERT OR REPLACE INTO connector_watermarks VALUES (?, 'archive', 1, 1, ?)", TOPIC, T)
        self.assertEqual(self.rows("SELECT generation, options_revision FROM connector_watermarks WHERE topic_id = ? AND connector_id = 'archive'", TOPIC), [(2, 3)])
        self.x("UPDATE connector_watermarks SET generation = 3, options_revision = 1 WHERE topic_id = ? AND connector_id = 'archive'", TOPIC)

    def test_connector_ids_are_well_formed(self) -> None:
        """Replaces the publication tables' closed product vocabulary: connector
        ids are open names, so the store holds them to the id shape instead
        (the schema's connector_id pattern) — in the watermark directly, and in
        a receipt even when its manifest names the malformed id."""
        bad = ("Warehouse", "cold_archive", "hook-", "a" * 65, "9warehouse")
        for cid in bad:
            with self.subTest(watermark=cid):
                self.rejects("CHECK constraint failed", "INSERT INTO connector_watermarks VALUES (?, ?, 1, 1, ?)", TOPIC, cid, T)
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=h("5"))
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), connectors={cid: "sql" for cid in bad})
        for attempt, cid in enumerate(bad, start=1):
            with self.subTest(receipt=cid):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.delivery(export_receipt_id=f"exr_bad0000{attempt}", connector_id=cid)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        for cid in ("s", "a" + "b" * 63, "cold-archive"):
            self.x("INSERT INTO connector_watermarks VALUES (?, ?, 1, 1, ?)", TOPIC, cid, T)


if __name__ == "__main__":
    unittest.main()
