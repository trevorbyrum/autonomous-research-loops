"""Optional receipt bindings: independent Router/SQL predicates and controls."""
from dataclasses import replace
import json

from .base import Mutation

MUTATIONS, CONTROLS = [], {}
RAW = 'test_store_detailed_check_receipts.ReferenceDDLTest.test_'
ROUTER = 'test_detailed_check_receipts.ReferenceRouterTest.test_'


def add(name, killer, old=None, new='1 = 1', scope='verification_receipts_detailed_binding', target='ddl', control='control', drop=None):
    mid = '2D4C2-' + name
    prefix = RAW if target == 'ddl' else ROUTER
    MUTATIONS.append(Mutation(mid, '2d-4c part 2', name, (prefix + killer,), target=target,
        scope=scope if target == 'ddl' else None, old=old, new=new, drop_trigger=drop))
    CONTROLS[mid] = {'controls': [prefix + control], 'why': 'Separate admitted /2 receipt traverses this binding/domain predicate with exact recorded operands.'}


for name, old, killer in (
        ('id', "d.check_id = json_extract(k.value, '$.record_id')", 'missing'),
        ('topic', 'd.topic_id = NEW.topic_id', 'topic'),
        ('verifier', 'd.performer_invocation_id = NEW.verifier_invocation_id', 'verifier'),
        ('kind', "json_extract(d.assessment, '$.kind') = k.key", 'kind'),
        ('outcome', "json_extract(d.assessment, '$.outcome') = json_extract(k.value, '$.outcome')", 'outcome'),
        ('claim', "json_extract(d.assessment, '$.claim_id') = NEW.claim_id", 'claim'),
        ('revision', "json_extract(d.assessment, '$.claim_revision') = NEW.claim_revision", 'revision'),
        ('spans', "json_extract(d.assessment, '$.cited_spans') = json(NEW.cited_spans)", 'spans'),
        ('work', "json_extract(d.assessment, '$.work_id') = NEW.work_id", 'work'),
        ('version', "json_extract(d.assessment, '$.source_version') = NEW.source_version", 'version'),
        ('source', "json_extract(d.assessment, '$.source_artifact_hash') = s.content_hash", 'source')):
    add(name, killer, old)
add('artifact', 'artifact', "json_extract(d.assessment, '$.examined_artifact_ref.content_hash')", 'NEW.obtained_content_hash')
add('extraction-output', 'extraction_wrong_basis', "SELECT json_extract(x.output_ref, '$.content_hash') FROM source_extractions x", "SELECT NEW.obtained_content_hash FROM source_extractions x", control='extraction_control')
add('domain', 'domain', drop='verification_receipts_detailed_domain')
add('legacy-shape', 'domain', "CASE json_extract(NEW.receipt, '$.receipt_version') WHEN 'verification-receipt/2' THEN '[\"detailed_checks\"]' ELSE '[]' END", "'[\"detailed_checks\"]'", scope='verification_receipts_span_domain_v4')
p = 'gen2/router/detailed_checks.py'
for name, old, killer in (('topic', 'row["topic_id"] != doc["topic_id"]', 'topic'),
        ('verifier', 'row["performer_invocation_id"] != doc["verifier_invocation_id"]', 'verifier'),
        ('artifact', 'report["examined_artifact_ref"]["content_hash"] != artifact_hash', 'artifact'),
        ('report', 'any(report[k] != v for k, v in expected.items())', 'claim')):
    add('router-' + name, killer, old, 'False', target=p)
add('router-missing', 'missing', '{"check_id": entry["record_id"]}', '{}', target=p, control='one_reference_control')

for target, name, old in (('ddl', 'validated-selector', 'SELECT target_extraction_id FROM extraction_validations_v2'),
        (p, 'router-validated-selector', 'validations[0]["target_extraction_id"]')):
    add(name, 'distinct_validated_wrong_basis', old, old.replace('target_extraction_id', 'validator_extraction_id'),
        target=target, control='validated_equal_control')
    prefix = RAW if target == 'ddl' else ROUTER
    MUTATIONS[-1] = replace(MUTATIONS[-1], killers=(*MUTATIONS[-1].killers, prefix + 'distinct_validated_target'))
    CONTROLS['2D4C2-' + name]['why'] = (
        'Separate byte-equal validated-extraction receipt executes the target-selection branch; '
        'it remains admitted with the validator selector. Distinct canonical/target/validator bytes discriminate the killers.')

for field, killer in (('kind', 'kind'), ('outcome', 'outcome'), ('claim_revision', 'revision'),
        ('cited_spans', 'spans'), ('work_id', 'work'), ('source_version', 'version'), ('source_artifact_hash', 'source')):
    add('router-' + field, killer, 'any(report[k] != v for k, v in expected.items())',
        'any(report[k] != v for k, v in expected.items() if k != "' + field + '")', target=p)
for name, replacement, killer in (('examined-auth', '(record["evidence_ref"],)', 'recorded_examined_corrupt'),
        ('evidence-auth', '(report["examined_artifact_ref"],)', 'recorded_evidence_omitted_corrupt')):
    mid = '2D4C2-' + name
    prefix = 'test_detailed_checks.AuthenticationRegressionTest.test_'
    MUTATIONS.append(Mutation(mid, '2d-4c part 2 NB1', name, (prefix + killer,), target=p,
        old='(report["examined_artifact_ref"], record["evidence_ref"])', new=replacement))
    CONTROLS[mid] = {'controls': [prefix + 'recorded_bytes_control'],
        'why': 'A fresh operation reuses authenticated recorded bytes with no result_refs; both examined and evidence paths are entered before the writer lock.'}

# Part 4a: mandatory admission is independently enforced in SQL and Router.
for target in ('ddl', p):
    prefix = ('test_store_mandatory_detailed_receipts.MandatoryDDLTest.test_' if target == 'ddl'
        else 'test_mandatory_detailed_receipts.MandatoryRouterTest.test_')
    for kind in ('numeric_units', 'denominators', 'negation', 'qualifications'):
        mid = '2D4C4A-' + ('ddl-' if target == 'ddl' else 'router-') + kind
        old = ('["numeric_units","denominators","negation","qualifications"]' if target == 'ddl'
            else '("numeric_units", "denominators", "negation", "qualifications")')
        remaining = tuple(k for k in ('numeric_units', 'denominators', 'negation', 'qualifications') if k != kind)
        new = json.dumps(remaining, separators=(',', ':')) if target == 'ddl' else repr(remaining).replace("'", '"')
        MUTATIONS.append(Mutation(mid, '2d-4c part 4a', 'Missing performed ' + kind + ' record',
            (prefix + 'missing', prefix + 'failed_without_record'), target=target,
            scope='verification_receipts_require_detailed_checks' if target == 'ddl' else None, old=old, new=new))
        CONTROLS[mid] = {'controls': [prefix + 'control'],
            'why': 'Separate admitted load-bearing /2 support enters the mandatory record guard with all four real exact references.'}
    performed = ('checked_ok', 'checked_problem', 'not_applicable')
    for summary, killer in zip(performed, ('missing', 'failed_without_record', 'exemption_without_record')):
        mid = '2D4C4A-' + ('ddl-' if target == 'ddl' else 'router-') + summary
        old = repr(performed) if target == 'ddl' else repr(performed).replace("'", '"')
        new = repr(tuple(s for s in performed if s != summary))
        if target != 'ddl': new = new.replace("'", '"')
        MUTATIONS.append(Mutation(mid, '2d-4c part 4a', 'Performed outcome requires records: ' + summary,
            (prefix + killer,), target=target, scope='verification_receipts_require_detailed_checks' if target == 'ddl' else None,
            old=old, new=new))
        CONTROLS[mid] = {'controls': [prefix + 'control'],
            'why': 'Separate load-bearing support with admitted references passes the performed-outcome predicate and record requirement.'}

# Repair 1: raw /1 summaries cannot escape SQL 40 through an open domain.
mid = '2D4C4AR1-summary-domain'
prefix = 'test_store_receipt_summary_domain.SummaryDDLTest.test_'
MUTATIONS.append(Mutation(mid, '2d-4c part 4a repair 1', 'Open legacy summary domain bypasses mandatory records',
    (prefix + 'b1',), drop_trigger='verification_receipts_support_check_domain'))
CONTROLS[mid] = {'controls': [prefix + 'control'],
    'why': 'Separate load-bearing /2 receipts with four real exact records enter SQL 41 successfully for all three methods in both orders.'}
