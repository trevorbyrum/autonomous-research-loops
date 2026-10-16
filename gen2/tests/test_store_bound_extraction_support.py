"""Raw promotion uses the same durable bases, including reversed triggers."""
import unittest
from gen2.tests.test_bound_extraction_support import PromotionCases


class BoundPromotionDDLTest(PromotionCases, unittest.TestCase):
    RAW = True

    def test_raw_rollback(self):
        self.context('verifier_extraction'); self.store()
        before = self.case.rows('SELECT * FROM claims')
        self.case.x('SAVEPOINT promotion')
        self.promote()
        self.case.x('ROLLBACK TO promotion'); self.case.x('RELEASE promotion')
        self.assertEqual(self.case.rows('SELECT * FROM claims'), before)
