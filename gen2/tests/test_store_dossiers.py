"""Dossier DDL is an integrity floor, independent of the Router codec."""
import sqlite3

from gen2.tests.store_fixtures import StoreTestCase, TOPIC, h


class DossierIntegrityTest(StoreTestCase):
    def test_document_and_producer_integrity_with_raw_json_control(self):
        self.approve_contract(TOPIC, 1)
        self.lease('lease_dossier0001', 1)
        self.invocation('inv_dossier0001', lease='lease_dossier0001')
        sql = "INSERT INTO dossiers VALUES (?,1,1,'eval-1',?,?,?,'2026-09-25T12:00:00Z')"
        for body, invocation in ((None, 'inv_dossier0001'), ('not json', 'inv_dossier0001'), ('{}', 'inv_missing000')):
            before = self.snapshot('dossiers')
            with self.assertRaises(sqlite3.IntegrityError):
                self.x(sql, TOPIC, h('e'), body, invocation)
            self.assertEqual(self.snapshot('dossiers'), before)
        self.x(sql, TOPIC, h('e'), '{}', 'inv_dossier0001')
        self.assertEqual(self.rows('SELECT document,invocation_id FROM dossiers'), [('{}', 'inv_dossier0001')])
        for statement in ("UPDATE dossiers SET document='[]'", 'DELETE FROM dossiers', 'INSERT OR REPLACE INTO dossiers SELECT * FROM dossiers'):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'immutable|never deleted'):
                self.x(statement)
        with self.assertRaises(sqlite3.IntegrityError):
            self.x(sql, TOPIC, h('f'), '{}', 'inv_dossier0001')
