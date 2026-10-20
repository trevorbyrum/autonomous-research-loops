"""Predicate-isolated canonical consumption; SQL proves recorded lineage only."""
import json
import sqlite3
from unittest.mock import patch

from gen2.core import canonical
from gen2.store import db
from gen2.tests import store_fixtures as sf
from gen2.tests.raw_detailed_receipt_fixtures import RawAssessmentFixture
from gen2.tests.detailed_receipt_fixtures import seed_checks, attach_checks
from gen2.tests.ddl_fixtures import restore_triggers
from gen2.tests.store_fixtures import TOPIC, T, h
from gen2.tests import test_store_acquisition_relationships as relationships


class CanonicalDDLTest(relationships.RelationshipTest):
    # Use operand builders, without inheriting the prior slice's test inventory.
    test_binding = test_verifier = test_immutable = test_control = None
    test_relationships = test_relationship_controls = test_natural_key = None

    def setUp(self):
        requested = sf.DDL_TEXT
        raw = b'{}        '
        digest = canonical.bytes_digest(raw)
        original = self.x
        # Replace the old source hash label with the actual examined bytes.
        with patch.object(sf, 'DDL_TEXT', db.schema_text()), patch.object(self, 'x',
                side_effect=lambda sql, *params: original(sql, *(digest if p == h('7') else p for p in params))):
            super().setUp()
            self.assessments = RawAssessmentFixture(self, raw)
        self.restore_catalog(requested)

    def restore_catalog(self, ddl):
        from gen2.tests.test_store_content_tiers import ContentDDLTest
        ContentDDLTest.restore_views(self, ddl)
        restore_triggers(self, ddl)

    def fresh_operand(self):
        # Router admission cannot nest inside the old outer SQL savepoint.
        self.tearDown()
        self.setUp()

    def source(self, **changes):
        if changes.get('digest') == h('7'):
            changes['digest'] = self.assessments.source['content_hash']
        super().source(**changes)

    def raw(self, **changes):
        changes.setdefault('content_hash', self.assessments.source['content_hash'])
        super().raw(**changes)
        from gen2.tests.extraction_receipt_fixtures import seed
        seed(self)
        requested = sf.DDL_TEXT
        self.restore_catalog(db.schema_text())
        try:
            inv = changes.get('verifier_invocation_id', 'inv_vvvvvvvv')
            self.x("UPDATE leases SET expires_at='2026-12-31T00:00:00Z' WHERE lease_id=(SELECT lease_id FROM invocations WHERE invocation_id=?)", inv)
            self.x("UPDATE invocations SET deadline_at='2026-12-30T00:00:00Z' WHERE invocation_id=?", inv)
            if self.rows('SELECT state FROM invocations WHERE invocation_id=?', inv) != [('running',)]:
                self.to_running(inv)
            self.assessments.verifier = self.assessments.router._grant('fixture', inv)
            seed_checks(self.assessments, dict(topic_id=TOPIC,
                claim=dict(claim_id='clm_00000001', claim_revision=1),
                source=dict(work_id=changes.get('work_id', 'wrk_00000001'), source_version=changes.get('source_version', 'v2')),
                cited_spans=[dict(start=0, end=5, locator=dict(kind='page', value='3'))],
                obtained_content_hash=changes['content_hash'], extraction=dict(method='canonical_bytes'),
                verifier_invocation_id=inv, checks=self.CHECKS_OK))
        finally:
            self.restore_catalog(requested)

    def verify(self, *args, historical=False, **changes):
        changes.setdefault('obtained', self.assessments.source['content_hash'])
        original = self.x
        def insert(sql, *params):
            if not historical and sql.startswith('INSERT INTO verification_receipts ('):
                cols = sql.split('(', 1)[1].split(')', 1)[0].split(', ')
                row = dict(zip(cols, params)); doc = json.loads(row['receipt'])
                attach_checks(self.assessments, doc)
                for key in ('receipt', 'cited_spans', 'acquisition'):
                    row[key] = canonical.canonical_bytes(doc if key == 'receipt' else doc[key]).decode()
                params = tuple(row[col] for col in cols)
            return original(sql, *params)
        with patch.object(self, 'x', side_effect=insert):
            super().verify(*args, historical=historical, **changes)

    def canonical_receipt(self, **changes):
        acq = {"route": "gateway:crossref", "retrieved_at": T, "gateway_call_ref": "gw-call:1", "cache_reuse": True}
        acq.update(changes.pop("acquisition", {}))
        version = changes.pop("version", "v2")
        self.verify("ver_canonical1", tier="bibliographic", required="bibliographic", method="canonical_bytes", extraction=changes.pop("extraction", "inv_pppppppp"), use="sampled", quote=("not_applicable", None),
            gateway=acq["gateway_call_ref"], receipt_overrides={"source": {"work_id": changes.get("work", "wrk_00000001"), "source_version": version}, "acquisition": acq},
            column_overrides={"source_version": version, "acquisition": json.dumps(acq)}, **changes)

    def test_canonical_control(self):
        self.raw()
        self.canonical_receipt()
        self.assertEqual(self.rows("SELECT source_version, extraction_method, extraction_invocation_id FROM verification_receipts WHERE verification_receipt_id = 'ver_canonical1'"),
            [("v2", "canonical_bytes", "inv_pppppppp")])
        self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def test_missing_admission(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "must consume its admitted acquisition"):
            self.canonical_receipt(historical=True)

    def test_predicates(self):
        for name in ("work", "version", "verifier", "hash", "acquirer", "call", "time", "route"):
            with self.subTest(predicate=name):
                self.fresh_operand()
                acquisition, negative, control = self.operands(name)
                self.raw(**acquisition)
                before = self.rows("SELECT * FROM verification_receipts")
                with self.assertRaisesRegex(sqlite3.IntegrityError, "must consume its admitted acquisition"):
                    self.canonical_receipt(historical=True, **negative)
                self.assertEqual(self.rows("SELECT * FROM verification_receipts"), before)
                self.canonical_receipt(**control)
                self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def operands(self, name):
        if name == "work":
            self.other_work()
            return {"work_id": "wrk_other001", "event_id": "e2", "provider_record_id": "rec-2"}, {}, {"work": "wrk_other001"}
        if name == "version":
            return {}, {"version": "v3"}, {}
        if name == "hash":
            self.artifact()
            return {}, {"obtained": h("e")}, {}
        if name == "verifier":
            self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_vvvvvvvv'", T)
            self.lease("lease_newver01", 99, scope="verification")
            self.invocation("inv_newver01", kind="verification", lease="lease_newver01")
            return {"verifier_invocation_id": "inv_newver01"}, {}, {"verifier": "inv_newver01"}
        if name == "acquirer":
            self.lease("lease_newacq1", 99, scope="checkpoint")
            self.invocation("inv_newacq01", kind="checkpoint", lease="lease_newacq1")
            self.observation(invocation="inv_newacq01")
            self.event(observation="o2")
            return {"acquired_by_invocation_id": "inv_newacq01", "observation_id": "o2", "event_id": "e2", "provider_record_id": "rec-2", "attempt": 2}, {}, {"extraction": "inv_newacq01"}
        field, value = {"call": ("gateway_call_ref", "gw-call:2"), "time": ("retrieved_at", "2026-09-28T00:00:00Z"), "route": ("route", "gateway:core")}[name]
        return {}, {"acquisition": {field: value}}, {}
