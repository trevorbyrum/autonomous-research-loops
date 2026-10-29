"""One exact offset domain at schema and actual staged Router boundaries."""
import json
import unittest
from pathlib import Path

from gen2.core import canonical
from gen2.router import boundary
from gen2.router.schemas import SchemaSet
from gen2.tests.span_cap_cases import LIMIT, NUMERALS, admitted, literal, exact_value
from gen2.tests import router_fixtures as tables
from gen2.tests import test_router_workflow as workflow
from gen2.tests.router_fixtures import empty_outcome
from gen2.tests.detailed_receipt_fixtures import attach_checks
from gen2.tests import router_fixtures as workflow_fixtures


RECEIPT_SCHEMA = Path(__file__).resolve().parents[1] / 'schema/verification-receipt.schema.json'

# Literal Router outcomes, independent of the rational oracle used by the
# supplemental schema/helper matrices. Columns are token, start, end.
ROUTER_CASES = (
    ('-1', 'rejected', 'rejected'),
    ('-0', 'committed', 'rejected'),
    ('0', 'committed', 'rejected'),
    ('0.0', 'committed', 'rejected'),
    ('-0.0', 'committed', 'rejected'),
    ('1', 'committed', 'committed'),
    ('9007199254740990', 'committed', 'committed'),
    ('9007199254740991', 'committed', 'committed'),
    ('9007199254740992', 'rejected', 'rejected'),
    ('9007199254740993', 'rejected', 'rejected'),
    ('9223372036854775809', 'rejected', 'rejected'),
    ('9007199254740991.0', 'committed', 'committed'),
    ('9.007199254740991e15', 'committed', 'committed'),
    ('90071992547409910e-1', 'committed', 'committed'),
    ('9007199254740992.0', 'rejected', 'rejected'),
    ('9.007199254740992e15', 'rejected', 'rejected'),
    ('9007199254740993e0', 'rejected', 'rejected'),
    ('9223372036854775809.0', 'rejected', 'rejected'),
    ('1e30', 'rejected', 'rejected'),
    ('1e999', 'rejected', 'rejected'),
    ('1e-999', 'rejected', 'rejected'),
    ('0e999', 'committed', 'rejected'),
    ('9007199254740991.00000000000000001', 'rejected', 'rejected'),
    ('900719925474099099999e-5', 'rejected', 'rejected'),
    ('0e999999999999999999999', 'committed', 'rejected'),
    ('0e-999999999999999999999', 'committed', 'rejected'),
    ('-0.000e+999999999999999999999', 'committed', 'rejected'),
    ('-0.000e-999999999999999999999', 'committed', 'rejected'),
    ('1e999999999999999999999', 'rejected', 'rejected'),
    ('1e-999999999999999999999', 'rejected', 'rejected'),
)


def schema_set():
    schemas = SchemaSet()
    schemas._docs['verification-receipt.schema.json'] = json.loads(RECEIPT_SCHEMA.read_text())
    return schemas


class SpanCapTest(unittest.TestCase):
    def test_link_locator_matrix(self):
        case = workflow.ClaimSourceLinkTest()
        case.setUp()
        try:
            self.assertEqual(case.capture(case.grant, 'op_loc_claim000')['status'], 'committed')
            schemas = schema_set()
            cases = [(n, 'rejected') for n in NUMERALS]
            cases.extend((('9007199254740992.0', 'rejected'),
                ('"9007199254740993"', 'committed')))
            for i, (n, expected) in enumerate(cases):
                with self.subTest(n=n):
                    raw_spans = literal('start', '0').replace('"value": "2"', '"value": ' + n)
                    target = 'outcome-document.schema.json#/properties/claim_source_links/items/properties/spans'
                    self.assertEqual(not schemas.errors(exact_value(raw_spans), target), expected == 'committed')
                    entry = workflow_fixtures.link()
                    entry['spans'] = '__SPAN__'
                    payload = {**empty_outcome(case.grant['invocation_id'], 'interim_transition'), 'claim_source_links': [entry]}
                    env = case.envelope(case.grant, f'op_locator_{i:04}', empty_outcome(case.grant['invocation_id'], 'interim_transition'))
                    raw = json.dumps(payload).replace('"__SPAN__"', raw_spans).encode()
                    env.update(payload_digest=case.spool.put(raw, media_type='application/json'), payload_size_bytes=len(raw))
                    before = case.state()
                    out = case.router.commit_outcome(env)
                    self.assertEqual(out['status'], expected, out)
                    if expected == 'committed':
                        self.assertEqual(case.store.select('claim_source_links')[0]['spans'], json.loads(raw_spans))
                    else:
                        self.assertEqual(out['reason'], 'payload_invalid')
                        self.assertEqual(case.store.select('claim_source_links'), [])
                        case.assert_audited_state(before, 1)
                        if n == '9007199254740992.0':
                            self.assertIn("/locator/value: type is not ['string']", out['detail'])
        finally:
            case.tearDown()

    def test_link_router_cap(self):
        for key in ('start', 'end'):
            case = workflow.ClaimSourceLinkTest()
            case.setUp()
            try:
                self.assertEqual(case.capture(case.grant, 'op_cap_claim000')['status'], 'committed')
                for i, (n, expected) in enumerate((
                        ('9007199254740992', 'rejected'),
                        ('9007199254740992.0', 'rejected'),
                        ('9.007199254740992e15', 'rejected'),
                        ('9007199254740991', 'committed'))):
                    with self.subTest(key=key, n=n):
                        entry = workflow_fixtures.link()
                        entry['spans'] = '__SPAN__'
                        payload = {**empty_outcome(case.grant['invocation_id'], 'interim_transition'),
                            'claim_source_links': [entry]}
                        env = case.envelope(case.grant, f'op_link_cap_{i:03}',
                            empty_outcome(case.grant['invocation_id'], 'interim_transition'))
                        raw = json.dumps(payload).replace('"__SPAN__"', literal(key, n)).encode()
                        env.update(payload_digest=case.spool.put(raw, media_type='application/json'), payload_size_bytes=len(raw))
                        before = case.state()
                        out = case.router.commit_outcome(env)
                        self.assertEqual(out['status'], expected, out)
                        if expected == 'rejected':
                            self.assertEqual(out['reason'], 'payload_invalid')
                            self.assertEqual(case.store.select('claim_source_links'), [])
                            case.assert_audited_state(before, 1)
                            if n in ('9007199254740992.0', '9.007199254740992e15'):
                                self.assertIn(f'/spans/0/{key}: maximum 9007199254740991 violated', out['detail'])
                        else:
                            self.assertEqual(case.store.select('claim_source_links')[0]['spans'], json.loads(literal(key, n)))
            finally:
                case.tearDown()

    def test_quote_router_cap(self):
        from gen2.tests.router_fixtures import QuotesCase
        case = QuotesCase()
        case.setUp()
        self.addCleanup(case.tearDown)
        for field in ('span_start', 'span_end'):
            with self.subTest(field=field):
                before = case.state()
                payload = {**empty_outcome(case.grant['invocation_id'], 'interim_transition'),
                    'quote_checks': [case.record(**{field: 9007199254740992})]}
                env = case.envelope(case.grant, case.ids('op_cap_'), empty_outcome(case.grant['invocation_id'], 'interim_transition'))
                raw = json.dumps(payload).encode()
                env.update(payload_digest=case.spool.put(raw, media_type='application/json'), payload_size_bytes=len(raw))
                out = case.router.commit_outcome(env)
                self.assertEqual((out['status'], out.get('reason')), ('rejected', 'payload_invalid'), out)
                self.assertEqual(case.rows('SELECT * FROM quote_checks'), [])
                case.assert_audited_state(before, 1)
        self.assertEqual(case.send([case.record()])['status'], 'committed')

    def test_schemas(self):
        schemas = schema_set()
        targets = ('verification-receipt.schema.json#/properties/cited_spans',
            'detailed-check-record.schema.json#/$defs/assessment/properties/cited_spans',
            'detailed-check-record.schema.json#/$defs/assessment/properties/context_spans',
            'outcome-document.schema.json#/properties/claim_source_links/items/properties/spans')
        for target in targets:
            for key in ('start', 'end'):
                for n in NUMERALS:
                    with self.subTest(target=target, key=key, n=n):
                        self.assertEqual(not schemas.errors(exact_value(literal(key, n)), target), admitted(key, n))

    def test_router_boundary(self):
        for key in ('start', 'end'):
            for n in NUMERALS:
                with self.subTest(key=key, n=n):
                    value = exact_value(literal(key, n))
                    if admitted(key, n): boundary.check_span_offsets(value)
                    else:
                        with self.assertRaisesRegex(boundary.Refusal, '9007199254740991'):
                            boundary.check_span_offsets(value)

    def test_control(self):
        spans = exact_value(literal('start', str(LIMIT)))
        boundary.check_span_offsets(spans)
        self.assertEqual(schema_set().errors(spans, 'verification-receipt.schema.json#/properties/cited_spans'), [])
        self.assertEqual(canonical.parse_json_strict(canonical.canonical_bytes(spans)), spans)

    def test_receipt_router_matrix(self):
        # Admit each distinct exact binding before snapshots. Repeated literal
        # spellings of the same value consume the same already admitted rows.
        bindings = {canonical.canonical_bytes(exact_value(literal(key, n))):
            exact_value(literal(key, n)) for column, key in enumerate(('start', 'end'), 1)
            for n, start, end in ROUTER_CASES if (start, end)[column - 1] == 'committed'}
        for method in tables.METHODS:
            with tables.span_fixture({'identity': tables.IDENTITY}, bindings=bindings.values()) as case:
                for column, key in enumerate(('start', 'end'), 1):
                    for i, row in enumerate(ROUTER_CASES):
                        n, expected = row[0], row[column]
                        with self.subTest(method=method, key=key, n=n):
                            doc = tables.document(case, method, 'bibliographic', spans=(tables.PAGE,), detailed=False)
                            doc['verification_receipt_id'] = f'ver_cap_{key}_{i:03}'
                            if expected == 'committed':
                                doc['cited_spans'] = exact_value(literal(key, n))
                                attach_checks(case, doc)
                            doc['cited_spans'] = '__SPAN__'
                            payload = {**empty_outcome(case.verifier['invocation_id'], 'interim_transition'), 'verification_receipts': [doc]}
                            env = case.envelope(case.verifier, f'op_cap_{key}_{i:03}', empty_outcome(case.verifier['invocation_id'], 'interim_transition'))
                            raw = json.dumps(payload).replace('"__SPAN__"', literal(key, n)).encode()
                            env.update(payload_digest=case.spool.put(raw, media_type='application/json'), payload_size_bytes=len(raw))
                            before = case.state()
                            out = case.router.commit_outcome(env)
                            self.assertEqual(out['status'], expected, out)
                            if expected == 'committed':
                                self.assertEqual(case.store.select('verification_receipts', {'verification_receipt_id': doc['verification_receipt_id']})[0]['cited_spans'], canonical.parse_json_strict(literal(key, n)))
                            else:
                                self.assertEqual(out['reason'], 'payload_invalid')
                                self.assertEqual(case.store.select('verification_receipts', {'verification_receipt_id': doc['verification_receipt_id']}), [])
                                case.assert_audited_state(before, 1)
                                if n in ('9007199254740992.0', '9.007199254740992e15'):
                                    self.assertIn(f'/cited_spans/0/{key}: maximum 9007199254740991 violated', out['detail'])

    def test_record_router_matrix(self):
        case = tables.CheckCase()
        case.setUp()
        try:
            for field in ('cited_spans', 'context_spans'):
                for column, key in enumerate(('start', 'end'), 1):
                    for i, row in enumerate(ROUTER_CASES):
                        n, expected = row[0], row[column]
                        with self.subTest(field=field, key=key, n=n):
                            record = case.record(outcome='not_checked', **{field: '__SPAN__'})
                            record.update(check_id=f'cap-{field}-{key}-{i}', evidence_ref=None)
                            env = case.env(case.record(outcome='not_checked'), op=f'op_cap_{field}_{key}_{i:03}')
                            payload = {**empty_outcome(case.verifier['invocation_id'], 'interim_transition'), 'detailed_check_records': [record]}
                            raw = json.dumps(payload).replace('"__SPAN__"', literal(key, n)).encode()
                            env.update(result_refs=[], payload_digest=case.spool.put(raw, media_type='application/json'), payload_size_bytes=len(raw))
                            before = case.state()
                            out = case.router.commit_outcome(env)
                            self.assertEqual(out['status'], expected, out)
                            if expected == 'committed':
                                self.assertEqual(case.store.select('detailed_check_records', {'check_id': record['check_id']})[0]['assessment'][field], canonical.parse_json_strict(literal(key, n)))
                            else:
                                self.assertEqual(out['reason'], 'payload_invalid')
                                self.assertEqual(case.store.select('detailed_check_records', {'check_id': record['check_id']}), [])
                                case.assert_audited_state(before, 1)
                                if n in ('9007199254740992.0', '9.007199254740992e15'):
                                    self.assertIn(f'/{field}/0/{key}: maximum 9007199254740991 violated', out['detail'])
        finally: case.tearDown()
