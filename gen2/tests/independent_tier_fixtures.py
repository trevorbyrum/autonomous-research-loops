"""Admit asymmetric independent outputs and comparisons under production guards."""
from gen2.tests.router_fixtures import empty_outcome


def independent_basis(case, doc, tier, suffix='limited'):
    def row(table, key, identity):
        cur = case.db.execute('SELECT * FROM ' + table + ' WHERE ' + key + '=?', (identity,))
        return dict(zip([d[0] for d in cur.description], cur.fetchone()))

    validation = row('extraction_validations_v2', 'validation_id', doc['extraction']['validation_ref'])
    extraction = row('source_extractions', 'extraction_id', validation['validator_extraction_id'])
    output = case.artifact(('Independent output at ' + tier).encode())
    evidence = case.artifact(b'Attributed agreement within the independent output available.')
    record = {k: v for k, v in extraction.items() if k not in
        ('topic_id', 'extracting_invocation_id', 'recorded_by_operation_id', 'created_at')}
    record.update(extraction_id='independent-' + suffix, supported_tier=tier, output_ref=output)
    out = case.router.commit_outcome(case.envelope(case.verifier, 'op_extract_' + suffix,
        {**empty_outcome(case.verifier['invocation_id'], 'interim_transition'), 'source_extractions': [record]}, refs=[output]))
    case.assertEqual(out['status'], 'committed', out)
    record = {k: v for k, v in validation.items() if k not in
        ('validator_invocation_id', 'recorded_by_operation_id', 'created_at')}
    record.update(validation_id='validation-' + suffix, validator_extraction_id='independent-' + suffix,
        comparison='semantic_agreement', comparison_evidence_ref=evidence)
    out = case.router.commit_outcome(case.envelope(case.verifier, 'op_compare_' + suffix,
        {**empty_outcome(case.verifier['invocation_id'], 'interim_transition'), 'extraction_validations_v2': [record]}, refs=[evidence]))
    case.assertEqual(out['status'], 'committed', out)
    doc['extraction']['validation_ref'] = record['validation_id']
