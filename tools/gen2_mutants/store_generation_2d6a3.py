"""Every generation event and integrity guard, with separate accepted controls."""
from .base import Mutation

TEST = 'test_store_generation.GenerationTest.test_'
LIFE = 'test_generation_lifecycle.LifecycleTest.test_'
TABLES = '''queue_entries contract_revisions facets obligations invocations
leases search_observations retrieval_events screening_assessments claims
semantic_assessments source_lifecycle registry_dispositions branch_windows
obligation_assessments amendment_impacts claim_source_links verification_receipts
source_artifacts source_acquisitions source_extractions detailed_check_records
holds operator_decisions artifact_topics dossiers operation_receipts
record_work_links works source_lineage quote_checks extraction_validations
extraction_validations_v2 artifacts extractor_registry_revisions extractor_tools audit_events'''.split()
MUTATIONS, CONTROLS = [], {}


def add(name, killer, *, control=TEST + 'event_control', **kwargs):
    mid = '2D6A3-' + name
    MUTATIONS.append(Mutation(mid, '2d-6a3', name, (killer,), **kwargs))
    CONTROLS[mid] = {'controls': [control], 'why':
        'Separate accepted control executes the installed event body/guard (all table/event probes), or the checked durable open/read path for lifecycle edits; it asserts row identity without the removed property.'}


for table in TABLES:
    for event in ('insert', 'update', 'delete'):
        add(table + '-' + event, TEST + 'event_bumps', drop_trigger=f'capture_generation_{table}_{event}')
for suffix, killer in (('no_insert', 'insert_protection'), ('no_delete', 'delete_protection'), ('step', 'step_protection')):
    add(suffix, TEST + killer, drop_trigger='store_generation_' + suffix)
for name, old, new in (
    ('singleton-domain', "singleton = 'store'", '1'),
    ('counter-domain', 'generation BETWEEN 0 AND 9007199254740991', '1'),
    ('epoch-domain', "length(epoch) = 32 AND epoch NOT GLOB '*[^0-9a-f]*'", '1')):
    add(name, TEST + 'constraints', scope='store_generation', old=old, new=new)
add('missing-row-write', TEST + 'missing_singleton_write_refuses', scope='capture_generation_queue_entries_insert',
    old='changes() <> 1', new='0')
for name, killer, old, new in (
    ('renewal', 'reopen_and_restore_renew_epoch',
     'conn.execute("UPDATE store_generation SET epoch = lower(hex(randomblob(16))) WHERE singleton = \'store\'")', 'conn.execute("SELECT 1")'),
    ('admission-row', 'missing_singleton_no_lazy_initialization', '    generation_state(conn)\n', '    pass\n'),
    ('schema-cookie', 'ddl_and_vacuum_change_cookie',
     'return (*rows[0][1:], conn.execute("PRAGMA schema_version").fetchone()[0])', 'return (*rows[0][1:], 0)')):
    add(name, LIFE + killer, control=LIFE + 'control', target='gen2/store/db.py', old=old, new=new)
