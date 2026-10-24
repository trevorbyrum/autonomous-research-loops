"""Store counter entry points and retained generation/lifecycle guards."""
from .base import Mutation

TEST = 'test_store_generation.GenerationTest.test_'
COUNT = 'test_store_generation.CounterTest.test_'
LIFE = 'test_generation_lifecycle.LifecycleTest.test_'
MUTATIONS, CONTROLS = [], {}


def add(name, killer, *, control=TEST + 'guard_control', **kwargs):
    mid = '2D6A3-' + name
    MUTATIONS.append(Mutation(mid, '2d-6a3', name, (killer,), **kwargs))
    CONTROLS[mid] = {'controls': [control], 'why':
        'A separate accepted write reaches the changed counter/guard line, checked maintenance, or literal gate; only the killer asserts the removed property.'}


for suffix, killer in (('no_insert', 'insert_protection'), ('no_delete', 'delete_protection'), ('step', 'step_protection')):
    add(suffix, TEST + killer, drop_trigger='store_generation_' + suffix)
for name, old, new in (
    ('singleton-domain', "singleton = 'store'", '1'),
    ('counter-domain', 'generation BETWEEN 0 AND 9007199254740991', '1'),
    ('epoch-domain', "length(epoch) = 32 AND epoch NOT GLOB '*[^0-9a-f]*'", '1')):
    add(name, TEST + 'constraints', scope='store_generation', old=old, new=new)
for name, killer, old, new in (
    ('insert-call', 'first_write', '        self._bump_once(table)\n        self._conn.execute(f"INSERT', '        self._conn.execute(f"INSERT'),
    ('update-call', 'once_and_reset', '        self._bump_once(table)\n        cursor =', '        cursor ='),
    ('bootstrap', 'first_write', '        self._conn.execute("INSERT INTO store_generation SELECT \'store\', NULL, 0 WHERE NOT EXISTS (SELECT 1 FROM store_generation)")', '        self._conn.execute("SELECT 1")'),
    ('once', 'once_and_reset', 'if self._bumped or table not in', 'if False or table not in'),
    ('reset', 'once_and_reset', '        self._bumped = False\n        try:', '        try:'),
    ('covered', 'uncovered_and_reads', 'if self._bumped or table not in (*capture.TOPIC_TABLES, *capture.SHARED):', 'if self._bumped:'),
    ('missing-row-write', 'missing_singleton_write_refuses', 'if self._conn.execute("SELECT changes()").fetchone()[0] != 1:', 'if False:')):
    add(name, COUNT + killer, control=COUNT + ('update_control' if name == 'update-call' else 'control'), target='gen2/store/api.py', old=old, new=new)
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

add('dml-lint', 'test_sqlite_native_gate.SQLiteNativeGateTest.test_store_dml_requires_the_generation_path',
    control='test_sqlite_native_gate.SQLiteNativeGateTest.test_store_counter_and_maintenance_dml_are_allowed',
    target='tools/check_gen2_sqlite_native.py', old='    yield from store_dml_violations(text, filename)', new='    pass')

add('dml-keywords', 'test_sqlite_native_gate.SQLiteNativeGateTest.test_store_write_keyword_variants',
    control='test_sqlite_native_gate.SQLiteNativeGateTest.test_store_primitive_sites_are_allowed',
    target='tools/check_gen2_sqlite_native.py', old=r"r'\b(?:INSERT|UPDATE|DELETE|REPLACE|UPSERT)\b'",
    new=r"r'\b(?:INSERT\s+INTO|DELETE\s+FROM|UPDATE\s+\S+\s+SET)\b'")
add('dml-comments', 'test_sqlite_native_gate.SQLiteNativeGateTest.test_store_comments_and_word_boundaries',
    control='test_sqlite_native_gate.SQLiteNativeGateTest.test_store_primitive_sites_are_allowed',
    target='tools/check_gen2_sqlite_native.py', old="    return re.sub(tokens, lambda m:", new="    return value\n    return re.sub(tokens, lambda m:")
