"""Same-receipt basis consumption with SQL support and ceiling views disabled."""
import copy
import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from gen2.tests import test_router_detailed_support as detailed
from gen2.tests.detailed_support_fixtures import history
from gen2.tests.test_canonical_receipt_admission import ReceiptCase
from gen2.tests.test_canonical_content_tiers import FULL
from gen2.tests.test_reaccess_admission import RAW
from gen2.tests.test_receipt_summary_domain import METHODS


class RouterSupportBasisTest(unittest.TestCase):
    RAW = True
    store = detailed.RouterDetailedSupportTest.store
    promote = detailed.RouterDetailedSupportTest.promote
    replace_doc = detailed.RouterDetailedSupportTest.replace_doc

    def opened(self, method='canonical_bytes', reverse=False, *, full=False):
        response = json.loads(RAW)
        if full: response['records'] = [FULL]
        with patch.object(ReceiptCase, 'RESPONSE', json.dumps(response).encode()):
            case = detailed.RouterDetailedSupportTest.opened(self, method, reverse,
                distinct=method == 'validated_extraction')
        case.x('DROP VIEW bound_extraction_receipts')
        case.x('CREATE VIEW bound_extraction_receipts AS SELECT verification_receipt_id FROM verification_receipts')
        case.x('DROP VIEW source_acquisition_content_tiers')
        case.x('CREATE VIEW source_acquisition_content_tiers AS SELECT *,4 AS recorded_tier_rank FROM source_acquisitions')
        return case

    @contextmanager
    def altered(self, case, table, field, value, where='1'):
        old = case.rows('SELECT rowid,' + field + ' FROM ' + table + ' WHERE ' + where)
        with history(case, unchecked=True):
            case.x('UPDATE ' + table + ' SET ' + field + '=? WHERE ' + where, value)
        try:
            yield
        finally:
            with history(case, unchecked=True):
                for rid, previous in old:
                    case.x('UPDATE ' + table + ' SET ' + field + '=? WHERE rowid=?', previous, rid)

    def test_control(self):
        for reverse in (False, True):
            for method in METHODS:
                for full in (False, True):
                    with self.subTest(reverse=reverse, method=method, full=full):
                        case = self.opened(method, reverse, full=full)
                        if full: case.doc['access_tier'] = 'full_text'
                        self.store(case)
                        self.promote(case, True)
                        self.doCleanups()

    def test_acquisition(self):
        for reverse in (False, True):
            for method in METHODS:
                case = self.opened(method, reverse)
                self.store(case)
                other_hash = case.value('SELECT content_hash FROM artifacts WHERE content_hash<>? LIMIT 1', case.source['content_hash'])
                for field, value in (('gateway_call_ref', 'foreign-call'), ('retrieved_at', '2000-01-01T00:00:00Z'),
                        ('lane', 'foreign'), ('content_hash', other_hash), ('provider_record_id', 'foreign-record')):
                    with self.subTest(method=method, reverse=reverse, field=field), self.altered(case, 'source_acquisitions', field, value):
                        self.promote(case)
                if method == 'canonical_bytes':
                    with self.altered(case, 'source_acquisitions', 'acquired_by_invocation_id', case.verifier['invocation_id']):
                        self.promote(case)
                # Stored acquisition/invocation operands override detached JSON.
                with self.altered(case, 'verification_receipts', 'acquisition', json.dumps({**case.doc['acquisition'], 'route': 'gateway:foreign'})):
                    self.promote(case)
                with self.altered(case, 'verification_receipts', 'extraction_invocation_id', 'inv_capture001' if method == 'verifier_extraction' else 'inv_verify0001'):
                    self.promote(case)
                self.doCleanups()

    def test_content(self):
        for reverse in (False, True):
            for method in METHODS:
                case = self.opened(method, reverse, full=True)
                case.doc['access_tier'] = 'full_text'
                self.store(case)
                identity = FULL['identity']
                bodies = (b'not JSON', b'[]', b'{"records":{}}',
                    b'{"records":[],"records":' + json.dumps([FULL]).encode() + b'}',
                    json.dumps({'records': [FULL]}).replace('}', ',"extra":NaN}', 1).encode(),
                    json.dumps({'records': [dict(identity=identity, abstract='Abstract only')]}).encode(),
                    json.dumps({'records': [dict(identity=identity, kind='full_text', links=['https://fixture.invalid'])]}).encode(),
                    json.dumps({'records': [dict(identity=identity), {**FULL, 'identity': 'foreign'}]}).encode(),
                    json.dumps({'records': [{**FULL, 'text': ' \u200b\ufe0f\U000e0001'}]}).encode())
                for body in bodies:
                    with self.subTest(method=method, reverse=reverse, body=body), self.altered(case, 'source_acquisitions', 'response_bytes', body):
                        self.promote(case)
                with self.altered(case, 'search_observations', 'coverage_state', 'metadata_only'):
                    self.promote(case)
                self.doCleanups()
        case = self.opened()
        self.store(case)
        for text in ('', ' \u200b\ufe0f\U000e0001', '\x00apparent content', None, 42):
            body = json.dumps({'records': [dict(identity=FULL['identity'], abstract=text)]}).encode()
            with self.subTest(text=text), self.altered(case, 'source_acquisitions', 'response_bytes', body):
                self.promote(case)

    def test_extraction(self):
        for reverse in (False, True):
            for method in METHODS[1:]:
                case = self.opened(method, reverse)
                self.store(case)
                eid = (case.doc['extraction']['extraction_id'] if method == 'verifier_extraction' else 'distinct-target')
                where = "extraction_id='" + eid + "'"
                for field, value in (('extractor_registry_version', None), ('supported_tier', 'bibliographic'),
                        ('extractor_identity', 'foreign-tool'), ('extracting_invocation_id',
                         case.producer['invocation_id'] if method == 'verifier_extraction' else case.verifier['invocation_id'])):
                    with self.subTest(method=method, reverse=reverse, field=field), self.altered(case, 'source_extractions', field, value, where):
                        self.promote(case)
                if method == 'verifier_extraction':
                    with self.altered(case, 'source_extractions', 'extracting_invocation_id', case.producer['invocation_id'], where), self.altered(case, 'verification_receipts', 'extraction_invocation_id', case.producer['invocation_id']):
                        self.promote(case)
                # A second retained acquisition with a different event cannot lend
                # its extraction to the exact acquisition selected by this receipt.
                acquisition = case.store.select('source_acquisitions')[0]
                event = case.store.select('retrieval_events')[0]
                with history(case):
                    event.update(event_id='rev_foreignbasis', provider_record_id='foreign-record')
                    case.x('INSERT INTO retrieval_events (' + ','.join(event) + ') VALUES (' + ','.join('?' * len(event)) + ')', *event.values())
                    acquisition.update(event_id=event['event_id'], gateway_call_ref='foreign-call')
                    case.x('INSERT INTO source_acquisitions (' + ','.join(acquisition) + ') VALUES (' + ','.join('?' * len(acquisition)) + ')', *acquisition.values())
                with self.altered(case, 'source_extractions', 'event_id', event['event_id'], where):
                    self.promote(case)
                doc = copy.deepcopy(case.doc)
                doc['checks']['tier0'] = dict(signal='alarm', checker='fixture', checker_version='1')
                doc['adjudication'] = dict(adjudication_ref='adj-alarm', resolved_at=doc['verified_at'], resolution='Does not waive the extraction alarm.')
                self.replace_doc(case, doc)
                self.promote(case)
                self.doCleanups()

    def test_validation(self):
        for reverse in (False, True):
            case = self.opened('validated_extraction', reverse)
            self.store(case)
            for field, value in (('method', 'same_family_replay'), ('policy_version', 1), ('outcome', 'failed'),
                    ('validator_invocation_id', case.producer['invocation_id'])):
                with self.subTest(reverse=reverse, field=field), self.altered(case, 'extraction_validations_v2', field, value, "validation_id='distinct-validation'"):
                    self.promote(case)
            with self.altered(case, 'source_extractions', 'supported_tier', 'bibliographic', "extraction_id='distinct-validator'"):
                self.promote(case)
            # A /1-only ID and an absent ID supply no /2 authority; target records remain real.
            with history(case, unchecked=True):
                case.x('INSERT INTO extraction_validations SELECT * FROM extraction_validations_v2 WHERE validation_id=?', 'distinct-validation')
                case.x('DELETE FROM extraction_validations_v2 WHERE validation_id=?', 'distinct-validation')
            self.promote(case)
            self.doCleanups()

    def test_no_pooling(self):
        for reverse in (False, True):
            for method in METHODS:
                case = self.opened(method, reverse)
                original = copy.deepcopy(case.doc)
                case.doc['verification_receipt_id'] += 'badbasis'
                case.doc['acquisition']['route'] = 'gateway:foreign'
                self.store(case)
                case.doc = copy.deepcopy(original)
                case.doc['verification_receipt_id'] += 'badchecks'
                case.doc['detailed_checks']['negation'].pop('record_id')
                self.store(case)
                self.promote(case)
                # Add one complete receipt after refusal; the loop must skip the two bad candidates.
                case.doc = original
                self.store(case)
                self.promote(case, True)
                self.doCleanups()

    def test_replay_conflict_rollback(self):
        detailed.RouterDetailedSupportTest.test_replay_conflict_rollback(self)
