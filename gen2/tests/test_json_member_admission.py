"""C-13 staged admission happens before serialization/writes; no providers."""
import json
from unittest.mock import patch

from gen2.core import canonical
from gen2.router import boundary
from gen2.store import api
from gen2.tests import test_extraction_records as records


class AdmissionTest(records.RecordCase):
    def test_control(self):
        value = {'outer': [{'name': 'allowed\0value'}]}
        self.assertEqual(boundary.normalize(value, 'payload_invalid', member_domain=True), value)
        store = api.adopt_in_memory(self.db)  # current module, including its mutant
        with store.transaction():
            self.assertEqual(json.loads(store._prepare('source_extractions', 'output_ref', value)), value)

    def test_router_nul(self):
        for value in ({'name\0suffix': 1}, {'outer': [{'name\0suffix': 1}]}):
            for input_value in (value, json.dumps(value)):
                with self.subTest(value=input_value), patch.object(canonical.rfc8785, 'dumps', side_effect=AssertionError('serialized before refusal')):
                    with self.assertRaisesRegex(boundary.Refusal, 'NUL in object member name'):
                        boundary.normalize(input_value, 'payload_invalid', member_domain=True)

    def test_store_nul(self):
        before = self.state(exclude=())
        store = api.adopt_in_memory(self.db)
        for table, column in (('source_extractions','output_ref'), ('extraction_validations','comparison_evidence_ref'), ('quote_checks','match_result')):
            for value in ({'name\0suffix': 1}, {'outer': [{'name\0suffix': 1}]}):
                for input_value in (value, json.dumps(value)):
                    with self.subTest(table=table, value=input_value), patch.object(canonical.rfc8785, 'dumps', side_effect=AssertionError('serialized before refusal')):
                        with self.assertRaisesRegex(api.StoreWriteError, 'NUL in object member name'), store.transaction():
                            store.insert(table, {column: input_value})
        self.assertEqual(self.state(exclude=()), before)

    def test_payload_wiring(self):
        record = self.extraction(output_ref={**self.output, 'name\0suffix': 'kept'})
        out = self.send(source_extractions=[record])
        self.assertEqual(out['status'], 'rejected', out)
        self.assertIn('NUL in object member name', out['detail'])
