"""Admitted attributed fixture assessments; never inferred from lexical output.

Attaching references only reads rows,
so receipt rollback/replay snapshots include all previously admitted evidence.
"""
import copy
from contextlib import contextmanager
from unittest.mock import patch

from gen2.core import canonical
from gen2.tests.router_fixtures import empty_outcome

OUTCOME = dict(checked_ok='succeeded', checked_problem='failed',
    not_applicable='not_applicable', not_checked='not_checked', unavailable='unavailable')
CONTEXT = dict(numeric_units='Quantities and unit interpretation: qualitative fixture statement.',
    denominators='Population or base: this fixture asserts no numerical population.',
    negation='Polarity and scope: the affirmative assertion in the cited fixture text.',
    qualifications='Limiting context: the assertion concerns this retained fixture only.')


def examined(case, doc):
    if doc['extraction']['method'] == 'canonical_bytes':
        return case.store.select('artifacts', {'content_hash': doc['obtained_content_hash']})[0]
    identity = doc['extraction'].get('extraction_id')
    if doc['extraction']['method'] == 'validated_extraction':
        identity = case.store.select('extraction_validations_v2',
            {'validation_id': doc['extraction']['validation_ref']})[0]['target_extraction_id']
    return case.store.select('source_extractions', {'extraction_id': identity})[0]['output_ref']


def assessment_binding(case, doc):
    source = case.store.select('source_artifacts', {'topic_id': doc['topic_id'], **doc['source']})[0]
    ref = examined(case, doc)
    return dict(**copy.deepcopy(doc['claim']), **doc['source'], source_artifact_hash=source['content_hash'],
        examined_artifact_ref={k: ref[k] for k in ('content_hash', 'size_bytes', 'media_type')},
        cited_spans=copy.deepcopy(doc['cited_spans']))


def seed_checks(case, doc):
    """Use the real Router admission/authentication path for all performed kinds."""
    binding = assessment_binding(case, doc)
    records = []
    for kind, context in CONTEXT.items():
        for outcome in ('succeeded', 'failed', 'not_applicable'):
            report = dict(**binding, kind=kind, outcome=outcome, method='attributed-assessment/1',
                context_spans=copy.deepcopy(doc['cited_spans']), context_examined=context,
                assessment=f'Attributed fixture assessment of {kind}: {outcome}.',
                applicability_reason='Qualitative fixture assertion; this aspect is outside its scope.'
                    if outcome == 'not_applicable' else '')
            identity = 'fixture-' + canonical.logical_hash([case.verifier['invocation_id'], report])[7:63]
            evidence = case.artifact(canonical.canonical_bytes(report), 'application/json')
            records.append(dict(check_id=identity, assessment=report, evidence_ref=evidence))
    payload = {**empty_outcome(case.verifier['invocation_id'], 'interim_transition'),
        'detailed_check_records': records}
    out = case.router.commit_outcome(case.envelope(case.verifier, 'op_checks_' + records[0]['check_id'][-12:],
        payload, refs=[r['evidence_ref'] for r in records]))
    case.assertEqual(out['status'], 'committed', out)
    attach_checks(case, doc)


def attach_checks(case, doc):
    """Select already admitted records; do not silently create or repair a basis."""
    binding = assessment_binding(case, doc)
    rows = case.store.select('detailed_check_records', {'topic_id': doc['topic_id'],
        'performer_invocation_id': doc['verifier_invocation_id']})
    entries = {}
    for kind in CONTEXT:
        outcome = OUTCOME[doc['checks'][kind]]
        entry = dict(outcome=outcome)
        if outcome in ('succeeded', 'failed', 'not_applicable'):
            matches = [r for r in rows if all(r['assessment'][k] == v for k, v in
                dict(**binding, kind=kind, outcome=outcome).items())]
            case.assertEqual(len(matches), 1, (kind, outcome, binding))
            entry['record_id'] = matches[0]['check_id']
        entries[kind] = entry
    doc.update(receipt_version='verification-receipt/2', detailed_checks=entries)


def unreferenced_checks(doc):
    """Current-format summaries without references, for isolated guard probes."""
    doc.update(receipt_version='verification-receipt/2', detailed_checks={
        kind: dict(outcome=OUTCOME[doc['checks'][kind]]) for kind in CONTEXT})
    return doc


@contextmanager
def reference_isolation(case):
    """Isolate refusal guards from performed-reference admission, using /2."""
    with patch.object(case.router._detailed_checks, '_require_performed_references', return_value=None):
        yield
