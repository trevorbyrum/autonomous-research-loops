"""Raw summary-domain regressions are included in the trigger-order gate."""
import unittest

from gen2.tests.test_receipt_summary_domain import SummaryCases


class SummaryDDLTest(SummaryCases, unittest.TestCase):
    RAW = True
