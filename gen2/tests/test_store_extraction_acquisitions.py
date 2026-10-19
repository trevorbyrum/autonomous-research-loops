"""Extraction input lineage, isolated from CHECKs and the support fence."""
import json
import sqlite3

from gen2.tests.test_store_canonical_receipts import CanonicalDDLTest
from gen2.tests.store_fixtures import T, h

METHODS = ("verifier_extraction", "validated_extraction")


class ExtractionDDLTest(CanonicalDDLTest):
    test_canonical_control = test_missing_admission = test_predicates = None

    def extraction_receipt(self, method, **changes):
        acq = {"route": "gateway:crossref", "retrieved_at": T, "gateway_call_ref": "gw-call:1", "cache_reuse": True}
        acq.update(changes.pop("acquisition", {}))
        version = changes.pop("version", "v2")
        verifier = changes.pop("verifier", "inv_vvvvvvvv")
        self.verify("ver_extraction1", method=method, tier="bibliographic", required="bibliographic", use="sampled",
            verifier=verifier, extraction=verifier if method == "verifier_extraction" else "inv_pppppppp",
            validation="validation_unrecorded" if method == "validated_extraction" else None,
            quote=("not_applicable", None), gateway=acq["gateway_call_ref"],
            receipt_overrides={"source": {"work_id": changes.get("work", "wrk_00000001"), "source_version": version}, "acquisition": acq},
            column_overrides={"source_version": version, "acquisition": json.dumps(acq)}, **changes)

    def test_control(self):
        self.raw()
        for method in METHODS:
            with self.subTest(method=method):
                self.x("SAVEPOINT extraction")
                try:
                    self.extraction_receipt(method)
                    self.assertEqual(self.rows("SELECT source_version, extraction_method, extraction_invocation_id, verifier_invocation_id FROM verification_receipts"),
                        [("v2", method, "inv_vvvvvvvv" if method == "verifier_extraction" else "inv_pppppppp", "inv_vvvvvvvv")])
                    self.assertEqual(self.rows("SELECT acquired_by_invocation_id, response_bytes FROM source_acquisitions"), [("inv_pppppppp", b'{}        ')])
                    self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
                finally:
                    self.x("ROLLBACK TO extraction")
                    self.x("RELEASE extraction")

    def test_missing(self):
        for method in METHODS:
            with self.subTest(method=method):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "extraction receipt must consume its admitted acquisition"):
                    self.extraction_receipt(method, historical=True)
                self.assertEqual(self.rows("SELECT * FROM verification_receipts"), [])

    def test_selectors(self):
        for method in METHODS:
            for name in ("work", "version", "verifier", "hash", "call", "time", "route"):
                with self.subTest(method=method, selector=name):
                    self.fresh_operand()
                    acquisition, negative, control = self.operands(name)
                    self.raw(**acquisition)
                    before = self.rows("SELECT * FROM verification_receipts")
                    with self.assertRaisesRegex(sqlite3.IntegrityError, "extraction receipt must consume its admitted acquisition"):
                        self.extraction_receipt(method, historical=True, **negative)
                    self.assertEqual(self.rows("SELECT * FROM verification_receipts"), before)
                    self.extraction_receipt(method, **control)
                    self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])

    def test_verdicts(self):
        for method in METHODS:
            for verdict in ("supports", "partially_supports", "does_not_support", "cannot_assess_at_required_tier"):
                with self.subTest(method=method, verdict=verdict):
                    with self.assertRaisesRegex(sqlite3.IntegrityError, "extraction receipt must consume its admitted acquisition"):
                        self.extraction_receipt(method, verdict=verdict, historical=True)
        self.assertEqual(self.rows("SELECT * FROM verification_receipts"), [])

    def test_unstaged_input(self):
        self.raw()
        for method in METHODS:
            with self.subTest(method=method):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "extraction receipt must consume its admitted acquisition"):
                    self.extraction_receipt(method, obtained=h("0"), historical=True)
        self.assertEqual(self.rows("SELECT * FROM verification_receipts"), [])
