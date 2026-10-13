"""Isolated member-domain pairs on each covered column, both write events."""
import json
import sqlite3
from unittest.mock import patch

from gen2.store import api, db
from gen2.tests import store_fixtures as fx, test_store_extraction_records as extraction, test_store_governed_quotes as quote


class DomainPairs:
    def attempt(self, event, text, accepted):
        self.x('SAVEPOINT domain_pair')
        try:
            if event == 'u':
                self.insert_raw(json.dumps(self.document))
                self.x(f'DROP TRIGGER {self.table}_immutable_u')  # isolate UPDATE domain from unconditional immutability
            before = list(self.db.iterdump())
            def write():
                if event == 'i':
                    self.insert_raw(text)
                else:
                    self.x(f'UPDATE {self.table} SET {self.column}=? WHERE {self.identity}=?', text, self.row_id)
            if accepted:
                write()
                row = self.reader.select(self.table, {self.identity: self.row_id})[0]
                self.assertEqual(row[self.column], json.loads(text))
            else:
                # Existing JSON readers may diagnose malformed syntax first
                # in reversed order; either SQLite refusal must be atomic.
                error = sqlite3.Error if text == '{malformed' else sqlite3.IntegrityError
                with self.assertRaises(error):
                    write()
                self.assertEqual(list(self.db.iterdump()), before)
        finally:
            self.x('ROLLBACK TO domain_pair')
            self.x('RELEASE domain_pair')

    def pairs(self, event, predicate):
        base = json.dumps(self.document)
        if predicate == 'duplicate':
            for member in self.members:
                for key in (json.dumps(member), '"\\u%04x%s"' % (ord(member[0]), member[1:])):
                    with self.subTest(event=event, member=member, key=key):
                        good = base[:-1] + ', "probe": {"a":1,"A":2}, "other":{"a":3}}'
                        self.attempt(event, good, True)
                        self.attempt(event, base[:-1] + ', ' + key + ': "forged"}', False)
            self.attempt(event, base[:-1] + ', "probe":{"a":1,"a":2}}', False)
        elif predicate == 'nul':
            for member in self.members:
                good = {**self.document, 'probe': {'name_suffix': 'kept\0value'}}
                bad = dict(self.document)
                bad[member + '\0suffix'] = bad.pop(member)
                with self.subTest(event=event, member=member):
                    self.attempt(event, json.dumps(good), True)
                    self.attempt(event, json.dumps(bad), False)
            self.attempt(event, json.dumps({**self.document, 'probe': {'name\0suffix': 'kept\0value'}}), False)
        else:
            self.attempt(event, base, True)
            self.attempt(event, '{malformed', False)

    def test_control_i(self):
        self.attempt('i', json.dumps({**self.document, 'probe': [{'a':'kept\0value'}, {'a':2,'A':3}]}), True)

    def test_control_u(self):
        self.attempt('u', json.dumps({**self.document, 'probe': [{'a':'kept\0value'}, {'a':2,'A':3}]}), True)


class OutputTest(DomainPairs, extraction.records.RecordCase):
    table, column, identity, row_id = 'source_extractions', 'output_ref', 'extraction_id', 'target'
    members = ('content_hash', 'size_bytes', 'media_type')

    def setUp(self):
        extraction.DDLTest.setUp(self)
        self.document, self.reader = self.output, self.store

    def insert_raw(self, text):
        out = extraction.DDLTest.send(self, source_extractions=[self.extraction(output_ref=text)])
        if out['status'] != 'committed':
            raise sqlite3.IntegrityError('raw domain refused')


class ComparisonTest(DomainPairs, extraction.records.RecordCase):
    table, column, identity, row_id = 'extraction_validations', 'comparison_evidence_ref', 'validation_id', 'validation-1'
    members = OutputTest.members

    def setUp(self):
        extraction.DDLTest.setUp(self)
        self.basis()
        self.document, self.reader = self.evidence, self.store

    def insert_raw(self, text):
        out = extraction.DDLTest.send(self, self.verifier, extraction_validations=[self.validation(comparison_evidence_ref=text)])
        if out['status'] != 'committed':
            raise sqlite3.IntegrityError('raw domain refused')


class QuoteTest(DomainPairs, fx.StoreTestCase):
    table, column, identity, row_id = 'quote_checks', 'match_result', 'check_id', 'qck_governed001'
    members = ('artifact_hash', 'expected_artifact_hash', 'span_start', 'span_end', 'status')

    def setUp(self):
        # Adopt the normal schema, then preserve the transformed quote triggers.
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(fx.DDL_TEXT)
            objects = reference.execute("SELECT name,sql FROM sqlite_schema WHERE type='trigger' AND tbl_name='quote_checks' ORDER BY rowid").fetchall()
        with patch.object(fx, 'DDL_TEXT', db.schema_text()):
            fx.StoreTestCase.setUp(self)
            self.populate_every_table()
            self.receipt('op_verify0001', 'inv_vvvvvvvv', lease='lease_vvvvvvvv', gen=2, before=50)
        self.reader = api.adopt_in_memory(self.db)
        for name, in self.rows("SELECT name FROM sqlite_schema WHERE type='trigger' AND tbl_name='quote_checks'"):
            self.x(f'DROP TRIGGER {name}')
        for _, sql in objects:
            self.x(sql)
        self.assertEqual(self.rows("SELECT name,sql FROM sqlite_schema WHERE type='trigger' AND tbl_name='quote_checks' ORDER BY rowid"), objects)
        self.x('SAVEPOINT quote_template')
        quote.DDLTest.raw(self)
        self.document = json.loads(self.rows("SELECT match_result FROM quote_checks WHERE check_id=?", self.row_id)[0][0])
        self.x('ROLLBACK TO quote_template')
        self.x('RELEASE quote_template')

    def insert_raw(self, text):
        quote.DDLTest.raw(self, match_result=text)


# Each event/predicate has its own killer and independent accepted control.
for predicate in ('duplicate', 'nul', 'valid'):
    for event in ('i', 'u'):
        def test(self, event=event, predicate=predicate):
            self.pairs(event, predicate)
        setattr(DomainPairs, f'test_{predicate}_{event}', test)
