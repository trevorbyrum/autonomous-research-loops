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
add('bootstrap', TEST + 'writer_initialization', scope='capture_generation_queue_entries_insert',
    old="INSERT INTO store_generation SELECT 'store', NULL, 0\n    WHERE NOT EXISTS (SELECT 1 FROM store_generation);", new='SELECT 1;')
for name, killer, target, old, new in (
    ('maintenance-renewal', 'reopen_preserves_proof_and_restore_renews_epoch', 'gen2/store/api.py',
     'store._conn.execute("UPDATE store_generation SET epoch = lower(hex(randomblob(16))) WHERE singleton = \'store\'")', 'store._conn.execute("SELECT 1")'),
    ('maintenance-bootstrap', 'initial_state_has_no_read_side_initialization', 'gen2/store/api.py',
     'store._conn.execute("INSERT INTO store_generation SELECT \'store\', NULL, 0 WHERE NOT EXISTS (SELECT 1 FROM store_generation)")', 'store._conn.execute("SELECT 1")'),
    ('maintenance-on-error', 'failed_maintenance_still_invalidates_admissible_result', 'gen2/store/api.py',
     '        try:\n            operation(path)\n        finally:', '        operation(path)\n        if True:'),
    ('admission-row', 'invalid_singleton_no_read_repair', 'gen2/store/db.py', '    generation_state(conn)\n', '    pass\n'),
    ('schema-cookie', 'ddl_and_vacuum_change_cookie', 'gen2/store/db.py',
     'return epoch, generation, conn.execute("PRAGMA schema_version").fetchone()[0]', 'return epoch, generation, 0')):
    add(name, LIFE + killer, control=LIFE + 'maintenance_control', target=target, old=old, new=new)

add('schema-only-install', 'test_reference_schema.ReferenceSchemaTest.test_reference_has_all_objects_without_seed_dml',
    old='CREATE TRIGGER store_generation_no_insert BEFORE INSERT ON store_generation',
    new="INSERT INTO store_generation VALUES ('store',NULL,0);\nCREATE TRIGGER store_generation_no_insert BEFORE INSERT ON store_generation")
