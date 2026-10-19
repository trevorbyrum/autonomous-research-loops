"""Part-1 record predicates, each paired with a separate admitted control."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
RAW, ROUTER = 'test_store_detailed_checks.DDLCheckTest.test_', 'test_detailed_checks.RouterCheckTest.test_'


def add(name, killer, scope=None, old=None, new='', target='ddl', control='control', drop=None):
    mid = '2D4C1-' + name
    prefix = RAW if target == 'ddl' else ROUTER
    MUTATIONS.append(Mutation(mid, '2d-4c part 1', name, (prefix + killer,), target=target,
        scope=scope, old=old, new=new, drop_trigger=drop))
    CONTROLS[mid] = {'controls': [prefix + control], 'why': 'Separate admitted/readable record exercises admission; unconditional immutability is paired with a successful insert into its guarded table.'}


for name, killer in (('domain', 'domain'), ('artifacts', 'artifacts'), ('spans_v2', 'spans'), ('immutable_u', 'immutable'), ('immutable_d', 'immutable')):
    add('spans' if name == 'spans_v2' else name, killer, drop='detailed_check_records_' + name)
for name, old, killer in (
        ('claim', "c.claim_id = json_extract(NEW.assessment, '$.claim_id')", 'bindings'),
        ('revision', "c.revision = json_extract(NEW.assessment, '$.claim_revision')", 'bindings'),
        ('work', "s.work_id = json_extract(NEW.assessment, '$.work_id')", 'bindings'),
        ('version', "s.source_version = json_extract(NEW.assessment, '$.source_version')", 'bindings'),
        ('hash', "s.content_hash = json_extract(NEW.assessment, '$.source_artifact_hash')", 'bindings'),
        ('producer', 'v.invocation_id <> c.producer_invocation_id', 'producer'),
        ('source-producer', 'v.invocation_id <> s.invocation_id', 'attribution'),
        ('topic', 'v.topic_id = c.topic_id', 'attribution'), ('kind', "v.kind = 'verification'", 'attribution'),
        ('contract', "v.admission_context = 'contract/1'", 'attribution'), ('parent', 'v.parent_invocation_id IS NULL', 'attribution'),
        ('committer', 'o.invocation_id = v.invocation_id', 'attribution'), ('operation-topic', 'o.topic_id = c.topic_id', 'attribution'),
        ('pin', 'o.contract_revision = v.contract_revision', 'attribution')):
    add(name, killer, 'detailed_check_records_binding', old, '1 = 1')
for column in ('assessment', 'evidence_ref'):
    for event in ('i', 'u'):
        for predicate, old in (('duplicate', 'HAVING count(*) > 1'), ('nul', "instr(CAST(key AS BLOB), x'00') > 0")):
            add(f'{column}-{event}-{predicate}', 'member_' + predicate,
                f'member_domain_detailed_check_records_{column}_{event}', old, 'HAVING count(*) < 0' if predicate == 'duplicate' else '0 > 1', control='member_control')
add('evidence-equality', 'evidence_mismatch', old='if canonical.canonical_bytes(evidence) != canonical.canonical_bytes(report):',
    new='if False:', target='gen2/router/detailed_checks.py')
add('router-source-hash', 'router_bindings', old='or sources[0]["content_hash"] != report["source_artifact_hash"]',
    new='or False', target='gen2/router/detailed_checks.py')
