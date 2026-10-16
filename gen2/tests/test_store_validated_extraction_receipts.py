"""Raw INSERT consumers, also exercised with reversed installed triggers."""
import unittest
from gen2.tests.test_validated_extraction_receipts import ValidatedCases


class ValidatedReceiptDDLTest(ValidatedCases, unittest.TestCase):
    RAW = True
