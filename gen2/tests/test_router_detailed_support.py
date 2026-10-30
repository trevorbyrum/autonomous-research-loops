"""Promotion reads actual records through the sole Router support owner."""
import copy
import json
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from gen2.core import canonical
from gen2.router import support
from gen2.router.boundary import Refusal
from gen2.tests.test_receipt_summary_domain import SummaryCases
from gen2.tests import test_detailed_check_receipts as refs
from gen2.tests.detailed_receipt_fixtures import attach_checks, seed_checks
from gen2.tests.detailed_support_fixtures import history, insert_receipt
from gen2.tests.router_fixtures import empty_outcome
from gen2.tests.test_receipt_summary_domain import METHODS
from gen2.tests import router_fixtures as rf


class RouterDetailedSupportTest(unittest.TestCase):

    def opened(self, method='canonical_bytes', *, distinct=False):
        case = SummaryCases.opened(self, method)
        if distinct:
            case.record = refs.ReferenceCases.record.__get__(case)
            refs.ReferenceCases.distinct_validated(case)
            case.doc['checks'].update({k: 'checked_ok' for k in rf.KINDS})
            case.doc['detailed_checks'] = {k: dict(outcome='succeeded', record_id='target-' + k) for k in rf.KINDS}
            case.doc['receipt_version'] = 'verification-receipt/2'
        else:
            seed_checks(case, case.doc)
        return case

    def store(self, case):
        with history(case, unchecked=True):
            self.assertEqual(insert_receipt(case, case.doc)['status'], 'committed')

    def promote(self, case, accepted=False):
        before = case.state()
        case.promotion_env = case.envelope(case.producer, 'op_promote_details', {
            **empty_outcome(case.producer['invocation_id'], 'interim_transition'),
            'claim_promotions': [dict(claim_id='clm_loadbear1', revision=1)]})
        out = case.router.commit_outcome(case.promotion_env)
        self.assertEqual(out['status'], 'committed' if accepted else 'rejected', out)
        if not accepted:
            self.assertEqual(out['reason'], 'payload_invalid', out)
            self.assertIn('performed detailed checks', out['detail'])
            case.assert_audited_state(before, 1)
        self.assertEqual(case.rows('PRAGMA foreign_key_check'), [])
        return out

    def replace_doc(self, case, doc):
        with history(case, unchecked=True):
            case.x('UPDATE verification_receipts SET receipt=? WHERE verification_receipt_id=?',
                canonical.canonical_bytes(doc).decode(), case.doc['verification_receipt_id'])

    def test_control(self):
        for method in METHODS:
            with self.subTest(method=method):
                case = self.opened(method)
                self.store(case)
                self.promote(case, True)
                self.assertEqual(case.value("SELECT status FROM claims WHERE claim_id='clm_loadbear1'"), 'accepted_support')
                self.doCleanups()

    def test_stored_v1_readback_and_non_support(self):
        from gen2.router.history import HistoryReader
        for attributed in (False, True):
            with self.subTest(attributed=attributed):
                case = self.opened()
                case.doc['receipt_version'] = 'verification-receipt/1'
                if not attributed:
                    del case.doc['detailed_checks']
                # The attributed variant keeps every /2 operand qualifying,
                # so the version discriminator itself must deny support.
                self.store(case)
                self.assertEqual(case.store.select('verification_receipts')[0]['receipt'], case.doc)
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'retained.sqlite3'
                    with sqlite3.connect(path) as snapshot:
                        case.db.backup(snapshot)
                        snapshot.execute('PRAGMA journal_mode=WAL')
                    snapshot.close()
                    before = path.read_bytes()
                    reader = HistoryReader.open(path)
                    retained = reader.records('verification_receipts')
                    self.assertEqual(retained['interpretation'], 'historical_records')
                    self.assertEqual(retained['records'][0]['receipt'], case.doc)
                    self.assertEqual(path.read_bytes(), before)
                self.promote(case)
                self.doCleanups()
        # Otherwise identical current-format stored-row control.
        case = self.opened()
        self.store(case)
        self.promote(case, True)

    def test_historical_shapes(self):
        for method in METHODS:
            case = self.opened(method)
            self.store(case)
            for shape in ('old_domain', 'empty', 'null', 'partial', 'extra'):
                with self.subTest(method=method, shape=shape):
                    doc = copy.deepcopy(case.doc)
                    if shape == 'old_domain':
                        doc['checks'].update({k: 'invented' for k in rf.KINDS})
                        doc['adjudication'] = dict(adjudication_ref='adj-history', resolved_at=doc['verified_at'],
                            resolution='Retained old-domain assessment, never detailed authority.')
                    elif shape == 'empty':
                        doc['detailed_checks'] = {}
                        doc['checks'].update({k: 'invented' for k in rf.KINDS})
                    elif shape == 'null': doc['detailed_checks'] = None
                    elif shape == 'partial':
                        doc['detailed_checks'].pop('qualifications')
                        doc['checks']['qualifications'] = 'invented'
                    else:
                        doc['checks']['foreign'] = 'checked_ok'
                        doc['detailed_checks']['foreign'] = dict(outcome='succeeded',
                            record_id=doc['detailed_checks']['qualifications']['record_id'])
                    self.replace_doc(case, doc)
                    self.promote(case)
            self.doCleanups()

    def test_bindings(self):
        for method in METHODS:
            case = self.opened(method, distinct=method == 'validated_extraction')
            self.store(case)
            for kind in rf.KINDS:
                rid = case.doc['detailed_checks'][kind]['record_id']
                original = case.store.select('detailed_check_records', {'check_id': rid})[0]
                fields = dict(kind='foreign', outcome='failed', claim_id='clm_foreign01', claim_revision=2,
                    cited_spans=[*case.doc['cited_spans'], case.doc['cited_spans'][0]], work_id='wrk_foreign01',
                    source_version='v2', source_artifact_hash='sha256:' + '0' * 64,
                    **{'examined_artifact_ref.content_hash': 'sha256:' + '1' * 64})
                for field, value in fields.items():
                    with self.subTest(method=method, kind=kind, field=field):
                        with history(case):
                            case.x('UPDATE detailed_check_records SET assessment=json_set(assessment,?,json(?)) WHERE check_id=?',
                                '$.' + field, json.dumps(value), rid)
                        self.promote(case)
                        with history(case):
                            case.x('UPDATE detailed_check_records SET assessment=? WHERE check_id=?', json.dumps(original['assessment']), rid)
                for column, value in (('topic_id', 'topic_other01'),
                        ('performer_invocation_id', case.producer['invocation_id'])):
                    with self.subTest(method=method, kind=kind, column=column):
                        # Use an existing foreign topic to preserve the FK contract.
                        if column == 'topic_id':
                            value = case.value("SELECT topic_id FROM queue_entries WHERE topic_id<>? LIMIT 1", case.doc['topic_id'])
                        with history(case):
                            case.x('UPDATE detailed_check_records SET ' + column + '=? WHERE check_id=?', value, rid)
                        self.promote(case)
                        with history(case):
                            case.x('UPDATE detailed_check_records SET ' + column + '=? WHERE check_id=?', original[column], rid)
            self.doCleanups()

    def test_missing_and_outcomes(self):
        for method in METHODS:
            case = self.opened(method)
            self.store(case)
            for kind in rf.KINDS:
                for outcome in ('missing', 'absent', 'not_checked', 'unavailable', 'projection', 'outcome'):
                    with self.subTest(method=method, kind=kind, outcome=outcome):
                        doc = copy.deepcopy(case.doc)
                        entry = doc['detailed_checks'][kind]
                        if outcome == 'missing': entry.pop('record_id')
                        elif outcome == 'absent': entry['record_id'] = 'absent'
                        elif outcome == 'projection': doc['checks'][kind] = 'invented'
                        elif outcome == 'outcome': entry['outcome'] = 'failed'
                        else:
                            entry['outcome'] = outcome
                            doc['checks'][kind] = outcome
                        rid = case.doc['detailed_checks'][kind]['record_id']
                        record = case.store.select('detailed_check_records', {'check_id': rid})[0]
                        if outcome in ('not_checked', 'unavailable'):
                            with history(case, unchecked=True):
                                case.x("UPDATE detailed_check_records SET assessment=json_set(assessment,'$.outcome',?) WHERE check_id=?", outcome, rid)
                        doc['adjudication'] = dict(adjudication_ref='adj-unperformed', resolved_at=doc['verified_at'],
                            resolution='Cannot waive absent performance.')
                        self.replace_doc(case, doc)
                        self.promote(case)
                        with history(case):
                            case.x('UPDATE detailed_check_records SET assessment=? WHERE check_id=?', json.dumps(record['assessment']), rid)
            self.doCleanups()

    def test_performed_controls(self):
        for method in METHODS:
            for summary in ('checked_ok', 'checked_problem', 'not_applicable'):
                with self.subTest(method=method, summary=summary):
                    case = self.opened(method)
                    case.doc['checks'].update({k: summary for k in rf.KINDS})
                    attach_checks(case, case.doc)
                    case.doc['adjudication'] = dict(adjudication_ref='adj-performed', resolved_at=case.doc['verified_at'],
                        resolution='Attributed performed assessment retained.')
                    self.store(case)
                    self.promote(case, True)
                    self.doCleanups()

    def test_claim_owned_gates(self):
        for field, value in (('use', 'sampled'), ('verdict', 'partially_supports'),
                ('required_access_tier', 'bibliographic'), ('access_tier', 'bibliographic')):
            case = self.opened()
            self.store(case)
            with history(case, unchecked=True):
                case.x('UPDATE verification_receipts SET ' + field + '=?', value)
            self.promote(case)
            self.doCleanups()

    def test_no_receipt_pooling(self):
        for method in METHODS:
            case = self.opened(method)
            for i, missing in enumerate(('negation', 'qualifications')):
                doc = copy.deepcopy(case.doc)
                doc['verification_receipt_id'] += str(i)
                doc['detailed_checks'][missing].pop('record_id')
                original, case.doc = case.doc, doc
                self.store(case)
                case.doc = original
            self.promote(case)
            self.doCleanups()

    def test_stored_operands(self):
        case = self.opened()
        self.store(case)
        row = case.store.select('verification_receipts')[0]
        foreign_topic = case.value('SELECT topic_id FROM queue_entries WHERE topic_id<>? LIMIT 1', case.doc['topic_id'])
        for column, value in (('topic_id', foreign_topic), ('verifier_invocation_id', case.producer['invocation_id']),
                ('cited_spans', json.dumps([*case.doc['cited_spans'], case.doc['cited_spans'][0]]))):
            with self.subTest(column=column):
                with history(case, unchecked=True):
                    case.x('UPDATE verification_receipts SET ' + column + '=?', value)
                # Isolate detailed-column consumption from the newer basis gate.
                with patch.object(support, 'has_basis', return_value=True):
                    self.promote(case)
                with history(case, unchecked=True):
                    value = canonical.canonical_bytes(row[column]).decode() if column == 'cited_spans' else row[column]
                    case.x('UPDATE verification_receipts SET ' + column + '=?', value)

    def test_non_load_bearing_control(self):
        case = self.opened()
        with history(case):
            case.x("UPDATE claims SET load_bearing=0,required_access_tier=NULL WHERE claim_id='clm_loadbear1'")
        self.promote(case, True)

    def test_replay_conflict_rollback(self):
        case = self.opened('validated_extraction')
        self.store(case)
        before = case.state(exclude=())
        case.faults['in_transaction:end'] = RuntimeError('after detailed promotion')
        with self.assertRaisesRegex(RuntimeError, 'after detailed promotion'):
            self.promote(case, True)
        self.assertEqual(case.state(exclude=()), before)
        case.faults.clear()
        out = self.promote(case, True)
        before = case.state(exclude=())
        self.assertEqual(case.router.commit_outcome(case.promotion_env), dict(status='replayed', receipt=out['receipt']))
        self.assertEqual(case.state(exclude=()), before)
        other = case.envelope(case.producer, 'op_promote_details', empty_outcome(case.producer['invocation_id'], 'interim_transition'))
        self.assertEqual(case.router.commit_outcome(other)['reason'], 'operation_id_conflict')


def outcome(call):
    try:
        return call()
    except Refusal as refusal:
        return (refusal.reason, refusal.detail)
    except Exception as fault:  # a crash is a wrong outcome, not an unhandled test error
        return (type(fault).__name__, str(fault))


class SelectRows:
    """Select-only rows keyed by table, as support.py reads them."""
    def __init__(self, **tables):
        self.tables = tables

    def select(self, table, where=None):
        return self.tables.get(table, [])


def tier(coverage, record):
    other = {"identity": "doi:other", "kind": "full_text", "text": "t", "abstract": "a"}
    body = json.dumps({"records": [other, {"identity": "doi:1", **record}]}).encode()
    rows = SelectRows(search_observations=[{"coverage_state": coverage}])
    return support.content_rank(rows, {"response_bytes": body, "observation_id": "o1", "provider_record_id": "doi:1"})


class ContentTierTest(unittest.TestCase):
    def test_tier_of_a_searched_full_text_abstract_only_and_bare_record(self):
        self.assertEqual(tier("searched_ok", {"kind": "full_text", "text": "body"}), 3)
        self.assertEqual(tier("searched_ok", {"kind": "full_text", "text": "body", "abstract": "a"}), 3)
        self.assertEqual(tier("searched_ok", {"kind": "full_text", "text": " ", "abstract": "a"}), 2)
        self.assertEqual(tier("searched_ok", {"kind": "full_text", "text": " "}), 1)
        self.assertEqual(tier("searched_ok", {"abstract": "a"}), 2)
        self.assertEqual(tier("searched_ok", {"kind": "abstract", "text": "body"}), 1)
        self.assertEqual(tier("searched_ok", {}), 1)

    def test_full_text_needs_a_searched_observation(self):
        self.assertEqual(tier("searched_partial", {"kind": "full_text", "text": "body", "abstract": "a"}), 2)
        self.assertEqual(tier("searched_partial", {"kind": "full_text", "text": "body"}), 1)


class DetailedBindingTest(unittest.TestCase):
    DOC = {"topic_id": "top_a", "verifier_invocation_id": "inv_v", "obtained_content_hash": "sha256:o", "verdict": "supports",
        "requested_for": {"use": "sampled"}, "extraction": {"method": "canonical_bytes"}, "cited_spans": [{"start": 0, "end": 4}],
        "claim": {"claim_id": "clm_1", "claim_revision": 1}, "source": {"work_id": "wrk_1", "source_version": "v1"},
        "checks": {"negation": "checked_ok"}, "detailed_checks": {"negation": {"outcome": "succeeded", "record_id": "chk_1"}}}

    def check(self, *records):  # each record: (its topic, the outcome its assessment reports)
        report = {**self.DOC["claim"], **self.DOC["source"], "kind": "negation", "outcome": "succeeded",
            "cited_spans": self.DOC["cited_spans"], "source_artifact_hash": "sha256:s", "examined_artifact_ref": {"content_hash": "sha256:o"}}
        rows = SelectRows(source_artifacts=[{"content_hash": "sha256:s"}],
            detailed_check_records=[{"topic_id": t, "performer_invocation_id": "inv_v", "assessment": {**report, "outcome": o}} for t, o in records])
        return outcome(lambda: support.require_receipt(rows, self.DOC))

    def test_the_first_stored_check_is_the_one_bound(self):
        refusal = ("payload_invalid", "receipt detailed check binding")
        good, foreign, other = ("top_a", "succeeded"), ("top_foreign", "succeeded"), ("top_a", "failed")
        self.assertEqual(self.check(good), None)
        self.assertEqual(self.check(good, foreign), None)
        self.assertEqual(self.check(good, other), None)
        self.assertEqual(self.check(foreign, good), refusal)
        self.assertEqual(self.check(other, good), refusal)
        self.assertEqual(self.check(), refusal)
