"""Raw mandatory admission, also executed with reversed installed triggers."""
import unittest

from gen2.tests.test_mandatory_detailed_receipts import MandatoryCases


class MandatoryDDLTest(MandatoryCases, unittest.TestCase):
    RAW = True
