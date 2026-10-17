"""Raw successor receipt domain/binding parity, including reverse trigger order."""
from gen2.tests.test_detailed_check_receipts import ReferenceCases, ReceiptCase


class ReferenceDDLTest(ReferenceCases, ReceiptCase):
    RAW = True
