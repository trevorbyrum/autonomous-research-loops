"""Durable own-extraction receipt bindings through the Router."""
import json
import unittest

from gen2.tests.detailed_receipt_fixtures import seed_checks, historical_receipt, historical_admission
from gen2.tests.router_fixtures import OwnCases


class OwnReceiptRouterTest(OwnCases, unittest.TestCase):
    pass
