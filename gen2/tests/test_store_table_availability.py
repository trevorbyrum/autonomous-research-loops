"""Isolated raw table guards; literal operands prove relationships, not transport."""
import json
import sqlite3

from gen2.tests import test_store_content_tiers as content
from gen2.tests.store_fixtures import h

TABLE = {"start": 0, "end": 5, "locator": {"kind": "table", "value": "Table 1"}}
PAGE = {"start": 5, "end": 9, "locator": {"kind": "page", "value": "2"}}


class TableDDLTest(content.relationships.RelationshipTest):
    test_binding = test_verifier = test_immutable = test_control = None
    test_relationships = test_relationship_controls = test_natural_key = None
    METHOD = "canonical_bytes"
    acquired = content.ContentDDLTest.acquired
    distractor = content.ContentDDLTest.distractor
    observation2 = content.ContentDDLTest.observation2

    def setUp(self):
        super().setUp()
        self.artifact(size=512)
        self.source(version="v4")

    def verify(self, *args, spans=(TABLE,), **changes):
        changes["obtained"] = changes.pop("obtained_override", changes["obtained"])
        changes["receipt_overrides"]["cited_spans"] = list(spans)
        changes["column_overrides"]["cited_spans"] = json.dumps(spans)
        super().verify(*args, **changes)

    def table_receipt(self, tier="bibliographic", **changes):
        content.ContentDDLTest.content_receipt(self, tier, method=self.METHOD,
            extraction="inv_vvvvvvvv" if self.METHOD == "verifier_extraction" else getattr(self, "validated_extractor", "inv_pppppppp"),
            validation="validation_unrecorded" if self.METHOD == "validated_extraction" else None, **changes)

    def refuse(self, **changes):
        before = self.rows("SELECT * FROM verification_receipts")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "table citation requires recorded full-text availability"):
            self.table_receipt(**changes)
        self.assertEqual(self.rows("SELECT * FROM verification_receipts"), before)

    def test_table_control(self):
        self.acquired(content.FULL)
        self.table_receipt("full_text", spans=(PAGE, TABLE))
        self.assertEqual(self.rows("SELECT cited_spans, access_tier, extraction_method FROM verification_receipts"),
            [(json.dumps((PAGE, TABLE)), "full_text", self.METHOD)])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def test_non_table_control(self):
        self.acquired({"identity": "rec-1"})
        self.table_receipt(spans=(PAGE,))

    def test_lower_table_control(self):
        self.acquired(content.FULL)
        self.table_receipt()

    def test_insufficient(self):
        for record, tier in (({"identity": "rec-1"}, "bibliographic"),
                ({"identity": "rec-1", "abstract": "Recorded abstract"}, "abstract")):
            for verdict in ("supports", "partially_supports", "does_not_support"):
                with self.subTest(tier=tier, verdict=verdict):
                    self.x("SAVEPOINT table_case")
                    try:
                        self.acquired(record)
                        self.refuse(tier=tier, verdict=verdict)
                        self.table_receipt(tier, verdict=verdict, spans=(PAGE,))
                    finally:
                        self.x("ROLLBACK TO table_case")
                        self.x("RELEASE table_case")

    def test_mixed(self):
        self.acquired({"identity": "rec-1"})
        self.refuse(spans=(PAGE, TABLE))
        self.table_receipt(spans=(PAGE,))

    def test_cannot_assess(self):
        for record, tier in (({"identity": "rec-1"}, "bibliographic"),
                ({"identity": "rec-1", "abstract": "Recorded abstract"}, "abstract")):
            with self.subTest(tier=tier):
                self.x("SAVEPOINT missing_table")
                try:
                    self.acquired(record)
                    self.table_receipt(tier, required="full_text", verdict="cannot_assess_at_required_tier",
                        checks=dict(self.CHECKS_OK, numeric_units="unavailable", denominators="unavailable"))
                    self.assertEqual(self.rows("SELECT verdict, access_tier, required_access_tier FROM verification_receipts"),
                        [("cannot_assess_at_required_tier", tier, "full_text")])
                finally:
                    self.x("ROLLBACK TO missing_table")
                    self.x("RELEASE missing_table")

    def test_lineage(self):
        selectors = ("work", "version", "verifier", "call", "time", "route")
        for name in selectors + (("acquirer",) if self.METHOD == "canonical_bytes" else ()):
            with self.subTest(selector=name):
                self.x("SAVEPOINT table_lineage")
                try:
                    record, others = {"identity": "rec-1"}, [{**content.FULL, "identity": "rec-2"}]
                    self.acquired(record, others)
                    changes = self.distractor(name)
                    self.acquired(record, others, event_id="e2", provider_record_id="rec-2", **changes)
                    self.refuse()
                    self.table_receipt(spans=(PAGE,))
                    self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
                finally:
                    self.x("ROLLBACK TO table_lineage")
                    self.x("RELEASE table_lineage")

    def test_diagnostics(self):
        for changes in ({}, {"obtained_override": h("7")}):
            with self.subTest(changes=changes):
                self.x("SAVEPOINT table_diagnostic")
                try:
                    if changes:
                        self.acquired({"identity": "rec-1"})
                    with self.assertRaisesRegex(sqlite3.IntegrityError, "must consume its admitted acquisition"):
                        self.table_receipt(**changes)
                    self.assertEqual(self.rows("SELECT * FROM verification_receipts"), [])
                finally:
                    self.x("ROLLBACK TO table_diagnostic")
                    self.x("RELEASE table_diagnostic")

    def test_tier_diagnostic(self):
        self.acquired({"identity": "rec-1"})
        for tier in ("full_text", "reproduced"):
            with self.subTest(tier=tier), self.assertRaisesRegex(sqlite3.IntegrityError, "tier exceeds recorded content"):
                self.table_receipt(tier)
            self.assertEqual(self.rows("SELECT * FROM verification_receipts"), [])

    def test_recorded_evidence(self):
        for record in ({"identity": "rec-1", "kind": "full_text", "links": ["https://fixture.invalid/table"],
                "has_full_text": True, "raw": {"text": "Table 1"}},
                {"identity": "rec-1", "kind": "series", "rows": [{"DataValue": "2"}], "row_count": 1,
                    "method": "GetData", "query": {"TableName": "T10101"}}):
            with self.subTest(record=record):
                self.x("SAVEPOINT table_record")
                try:
                    self.acquired(record, [{**content.FULL, "identity": "rec-other"}])
                    self.refuse()
                    self.table_receipt(spans=(PAGE,))
                finally:
                    self.x("ROLLBACK TO table_record")
                    self.x("RELEASE table_record")

    def test_bea_table_identity(self):
        identity = "table:bea:NIPA:T10101"
        self.x("INSERT INTO retrieval_events SELECT 'e2', observation_id, topic_id, ?, 2, captured_at FROM retrieval_events WHERE event_id = 'e1'", identity)
        self.x("INSERT INTO record_work_links SELECT 'e2', work_id, dedup_method_version, linked_at FROM record_work_links WHERE event_id = 'e1'")
        self.acquired({"identity": identity, "kind": "series", "rows": [{"DataValue": "2"}], "row_count": 1,
            "method": "GetData", "query": {"TableName": "T10101"}}, event_id="e2", provider_record_id=identity)
        self.refuse(spans=({**TABLE, "locator": {"kind": "table", "value": identity}},))
        self.table_receipt(spans=(PAGE,))

    def test_readback_conflict_rollback(self):
        self.acquired(content.FULL)
        self.x("SAVEPOINT retention")
        self.table_receipt("full_text")
        retained = self.rows("SELECT * FROM verification_receipts")
        self.assertEqual(json.loads(self.rows("SELECT receipt FROM verification_receipts")[0][0])["cited_spans"], [TABLE])
        for tier in ("full_text", "bibliographic"):
            with self.subTest(tier=tier), self.assertRaisesRegex(sqlite3.IntegrityError, "UNIQUE constraint"):
                self.table_receipt(tier)
            self.assertEqual(self.rows("SELECT * FROM verification_receipts"), retained)
        self.x("ROLLBACK TO retention")
        self.x("RELEASE retention")
        self.assertEqual(self.rows("SELECT * FROM verification_receipts"), [])
        self.table_receipt("full_text")


class ExtractionTableDDLTest(TableDDLTest):
    METHOD = "verifier_extraction"


class ValidatedTableDDLTest(TableDDLTest):
    METHOD = "validated_extraction"

    def test_insufficient(self):
        super().test_insufficient()
        # A validated target may be extracted by someone other than the acquirer.
        # Preserve the old table guard's independent-extractor killer as well as
        # its producer-acquired target cases; every operand remains admitted.
        self.lease('lease_extract01', 3, scope='checkpoint')
        self.invocation('inv_extract01', kind='checkpoint', lease='lease_extract01')
        self.receipt('op_extract01', 'inv_extract01', lease='lease_extract01', gen=3, before=200000, kind='interim_transition')
        self.acquired({'identity': 'rec-1'})
        for table, where, changes in (
                ('source_extractions', "extracting_invocation_id='inv_pppppppp'", dict(extraction_id='independent-target',
                    extracting_invocation_id='inv_extract01', recorded_by_operation_id='op_extract01')),
                ('extraction_validations_v2', '1', dict(validation_id='independent-target-validation', target_extraction_id='independent-target'))):
            cur = self.db.execute('SELECT * FROM ' + table + ' WHERE ' + where + ' LIMIT 1')
            row = {**dict(zip([d[0] for d in cur.description], cur.fetchone())), **changes}
            self.x(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values())
        self.validated_extractor = 'inv_extract01'
        self.refuse()
        self.table_receipt(spans=(PAGE,))
        self.assertEqual(self.rows('PRAGMA foreign_key_check'), [])
