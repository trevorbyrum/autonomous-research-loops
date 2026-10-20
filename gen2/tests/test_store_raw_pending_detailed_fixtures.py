"""Pending-family current positives retain exact admitted claim/revision records."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch

from gen2.core import canonical
from gen2.store import db
from gen2.tests import store_fixtures as sf
from gen2.tests import test_pending_extraction_support as pending
from gen2.tests import test_store_content_tiers as content
from gen2.tests import test_store_detailed_receipt_fixtures as converted
from gen2.tests.ddl_fixtures import TRIGGERS
from gen2.tests.test_store_fixture_order import reverse_triggers


class RawPendingFixtureTest(unittest.TestCase):
    check_receipt = converted.ConvertedFixtureTest.check_receipt

    def opened(self):
        case = pending.PendingDDLTest()
        case.setUp()
        self.addCleanup(case.tearDown)
        return case

    def retained(self, case, rid="ver_content1"):
        doc = json.loads(case.rows("SELECT receipt FROM verification_receipts WHERE verification_receipt_id=?", rid)[0][0])
        self.check_receipt(case.assessments, doc, case.assessments.source)
        return doc

    def test_original_canonical_distractor_and_inherited_controls_keep_distinct_records(self):
        seen, legacy = [], []
        for method in ("test_canonical_support_control", "test_canonical_distractors", "test_content_controls"):
            case = self.opened(); verify = case.verify
            def observe(rid, *args, **kwargs):
                records = case.rows("SELECT * FROM detailed_check_records")
                verify(rid, *args, **kwargs)
                self.assertEqual(case.rows("SELECT * FROM detailed_check_records"), records)
                if kwargs.get("historical"):
                    legacy.append(json.loads(case.rows("SELECT receipt FROM verification_receipts WHERE verification_receipt_id=?", rid)[0][0]))
                else:
                    seen.append(self.retained(case, rid))
            with patch.object(case, "verify", side_effect=observe): getattr(case, method)()
        self.assertEqual(len(seen), 8)
        self.assertEqual([d["receipt_version"] for d in legacy], ["verification-receipt/1"] * 2)
        bindings = {}
        for doc in seen:
            key = (doc["claim"]["claim_id"], doc["claim"]["claim_revision"])
            bindings.setdefault(key, set()).update(e["record_id"] for e in doc["detailed_checks"].values())
        self.assertEqual(set(bindings), {("clm_00000001", 1), ("clm_00000001", 2), ("clm_other001", 2)})
        self.assertEqual(sum(map(len, bindings.values())), len(set.union(*bindings.values())))

    def test_each_kind_and_performed_outcome_preserves_conflict_and_rollback(self):
        case = self.opened(); case.prepare_pending(); case.acquired(content.FULL)
        before = case.assessments.state(exclude=())
        for kind in ("numeric_units", "denominators", "negation", "qualifications"):
            for outcome, status in (("succeeded", "checked_ok"), ("failed", "checked_problem"), ("not_applicable", "not_applicable")):
                with self.subTest(kind=kind, outcome=outcome):
                    case.x("SAVEPOINT receipt")
                    try:
                        case.content_receipt("full_text", claim=("clm_00000001", 2), verdict="partially_supports",
                            checks=dict(case.CHECKS_OK, **{kind: status}))
                        doc = self.retained(case)
                        self.assertEqual(doc["detailed_checks"][kind]["outcome"], outcome)
                        self.assertEqual(case.rows("SELECT * FROM detailed_check_records"), before["detailed_check_records"])
                        with self.assertRaisesRegex(sqlite3.IntegrityError, "UNIQUE constraint"):
                            case.content_receipt("full_text", claim=("clm_00000001", 2))
                    finally:
                        case.x("ROLLBACK TO receipt"); case.x("RELEASE receipt")
                    self.assertEqual(case.assessments.state(exclude=()), before)

    def test_foreign_claim_and_revision_refuse_atomically_then_matching_promotes(self):
        case = self.opened(); case.prepare_pending(other=True); case.acquired(content.FULL)
        rows = []
        for claim in (("clm_00000001", 1), ("clm_other001", 2), ("clm_00000001", 2)):
            case.x("SAVEPOINT row")
            case.content_receipt("full_text", claim=claim, use="load_bearing")
            self.retained(case)
            cursor = case.x("SELECT * FROM verification_receipts")
            rows.append(dict(zip([d[0] for d in cursor.description], cursor.fetchone())))
            case.x("ROLLBACK TO row"); case.x("RELEASE row")
        matching = json.loads(rows[-1]["receipt"])
        before = case.assessments.state(exclude=())
        for foreign in rows[:-1]:
            bad = copy.deepcopy(matching)
            bad["detailed_checks"] = json.loads(foreign["receipt"])["detailed_checks"]
            row = dict(rows[-1], receipt=canonical.canonical_bytes(bad).decode())
            with self.assertRaisesRegex(sqlite3.IntegrityError, "receipt detailed check binding"):
                case.x(f"INSERT INTO verification_receipts ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values())
            self.assertEqual(case.assessments.state(exclude=()), before)
        case.content_receipt("full_text", claim=("clm_00000001", 2), use="load_bearing")
        self.retained(case); case.promote()
        self.assertEqual(case.rows("SELECT claim_id,revision,status FROM claims ORDER BY claim_id,revision"),
            [("clm_00000001", 1, "provisional"), ("clm_00000001", 2, "accepted_support"), ("clm_other001", 2, "provisional")])
        raw = case.assessments.spool.read(matching["obtained_content_hash"], topic_id=sf.TOPIC)
        self.assertEqual(case.rows("SELECT response_bytes FROM source_acquisitions"), [(raw,)])
        self.assertEqual(canonical.bytes_digest(raw), matching["obtained_content_hash"])

    def test_full_admission_restores_requested_views_and_trigger_catalog(self):
        requested = reverse_triggers(sf.DDL_TEXT).replace("d.topic_id = NEW.topic_id", "1 = 1")
        requested = requested.replace("ELSE 1 END AS recorded_tier_rank", "ELSE (0 + 1) END AS recorded_tier_rank")
        requested += "\nDROP TRIGGER verification_receipts_detailed_domain;\n"
        views = "SELECT name,sql FROM sqlite_schema WHERE type='view' ORDER BY rowid"
        def catalog(ddl):
            with sqlite3.connect(":memory:") as reference:
                reference.executescript(ddl)
                return list(reference.execute(TRIGGERS)), list(reference.execute(views))
        full, expected = catalog(db.schema_text()), catalog(requested)
        seed = pending.seed_checks; seen = []
        def observe(bridge, doc):
            self.assertEqual((bridge.rows(TRIGGERS), bridge.rows(views)), full)
            seen.append(doc["claim"])
            return seed(bridge, doc)
        with patch.object(sf, "DDL_TEXT", requested), patch.object(pending, "seed_checks", observe):
            case = self.opened(); case.prepare_pending(other=True)
            self.assertEqual((case.rows(TRIGGERS), case.rows(views)), expected)
            case.acquired(content.FULL)
            case.content_receipt("full_text", claim=("clm_00000001", 2), use="load_bearing")
            self.retained(case); case.promote()
            self.assertEqual((case.rows(TRIGGERS), case.rows(views)), expected)
        self.assertEqual(seen, [dict(claim_id=claim, claim_revision=2) for claim in ("clm_00000001", "clm_other001")])
