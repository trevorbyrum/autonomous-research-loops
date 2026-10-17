"""Reseeding must retain actual requested catalogs, including counterfactuals."""
import sqlite3
import unittest
from unittest.mock import patch

from gen2.store import db
from gen2.tests import store_fixtures as sf
from gen2.tests.ddl_fixtures import TRIGGERS, assert_triggers, restore_triggers
from gen2.tests import test_store_detailed_check_receipts as receipts


def reverse_triggers(ddl):
    # Independent catalog construction: do not trust the runner's reversal.
    with sqlite3.connect(':memory:') as reference:
        reference.executescript(ddl)
        triggers = reference.execute(TRIGGERS).fetchall()
    return ddl + '\n' + '\n'.join('DROP TRIGGER ' + n + ';' for n, _ in triggers) + '\n' + '\n'.join(
        sql + ';' for _, sql in reversed(triggers))


class FixtureOrderTest(unittest.TestCase):
    def fixture(self, ddl):
        case = receipts.ReferenceDDLTest('test_control')
        with patch.object(sf, 'DDL_TEXT', ddl):
            case.setUp()
        self.addCleanup(case.tearDown)
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(ddl)
            expected = reference.execute(TRIGGERS).fetchall()
        assert_triggers(case, expected)
        return case, expected

    def test_setup_retains_exact_order_and_reversal(self):
        ddl = db.schema_text()
        normal, expected = self.fixture(ddl)
        reversed_case, reversed_expected = self.fixture(reverse_triggers(ddl))
        self.assertEqual(reversed_expected, list(reversed(expected)))
        normal.test_control()
        reversed_case.test_control()

    def test_setup_retains_dropped_and_mutated_definitions(self):
        ddl = reverse_triggers(db.schema_text()).replace('d.topic_id = NEW.topic_id', '1 = 1')
        ddl += '\nDROP TRIGGER verification_receipts_detailed_domain;\n'
        case, expected = self.fixture(ddl)
        self.assertNotIn('verification_receipts_detailed_domain', dict(expected))
        self.assertIn('1 = 1', dict(expected)['verification_receipts_detailed_binding'])

    def test_catalog_assertion_detects_silent_reset(self):
        case, expected = self.fixture(reverse_triggers(db.schema_text()))
        restore_triggers(case, db.schema_text())
        with self.assertRaisesRegex(AssertionError, 'fixture reset requested trigger catalog/order'):
            assert_triggers(case, expected)
