"""Fixed selection, immutable raw operands and history/byte hash controls."""
from .base import Mutation

TARGET = 'gen2/store/capture.py'
TEST = 'test_topic_capture.CaptureTest.test_'
MUTATIONS, CONTROLS = [], {}


def add(name, killer, old, new, target=TARGET):
    mid = '2D6A1-' + name
    MUTATIONS.append(Mutation(mid, '2d-6a1', name, (TEST + killer,), target=target, old=old, new=new))
    CONTROLS[mid] = {'controls': [TEST + 'hash_control'], 'why':
        'Independent accepted Store-owned capture and outside-transaction native hash execute the changed path; assert topic identity and digest form without the removed property.'}


add('ownership', 'requires_owned_transaction', '        if self._in_transaction or self._conn.in_transaction:',
    '        if False:', 'gen2/store/api.py')
add('topic', 'isolation_and_authorization', '(name, "r.topic_id=:topic")', '(name, "1")')
add('authorization', 'isolation_and_authorization',
    'r.content_hash IN (SELECT content_hash FROM artifact_topics WHERE topic_id=:topic)', 'r.topic_id=:topic')
for name, killer, predicate in (
    ('works', 'isolation_and_authorization', 'r.work_id IN (SELECT l.work_id FROM record_work_links l JOIN retrieval_events e USING(event_id) WHERE e.topic_id=:topic)'),
    ('links', 'isolation_and_authorization', 'r.event_id IN (SELECT event_id FROM retrieval_events WHERE topic_id=:topic)'),
    ('lineage', 'other_shared_relations', 'r.assessment_id IN (SELECT assessment_id FROM semantic_assessments WHERE topic_id=:topic)'),
    ('quotes', 'other_shared_relations', '(r.claim_id,r.claim_revision) IN (SELECT claim_id,revision FROM claims WHERE topic_id=:topic)')):
    add(name, killer, predicate, '1')
add('pins', 'historical_registry', 'SELECT extractor_registry_version FROM source_extractions WHERE topic_id=:topic',
    'SELECT max(registry_version) FROM extractor_registry_revisions')
add('groups', 'groups_and_order', 'tuple(tables))', 'tuple(t for t in tables if t.name != "source_lineage"))')
add('immutable-value', 'immutable', '@dataclass(frozen=True)\nclass TopicCapture', '@dataclass\nclass TopicCapture')
add('immutable-table', 'immutable', '@dataclass(frozen=True)\nclass RawTable', '@dataclass\nclass RawTable')
add('immutable-rows', 'immutable', 'tuple(cursor.fetchall())', 'cursor.fetchall()')
add('history', 'hash_binding', '"history": history', '"history": "native"')
add('blob', 'hash_binding', 'canonical.bytes_digest(cell)', '"omitted"')
add('hash-groups', 'hash_binding', 'for table in snapshot.tables]', 'for table in snapshot.tables if table.rows]')
add('hash-order', 'hash_binding', 'for row in table.rows]', 'for row in reversed(table.rows)]')
add('json-metadata', 'hash_binding', '"json_columns": table.json_columns', '"json_columns": ()')


def reader(name, killer, old, new, also=(), control='test_capture_reader.FileReaderTest.test_control'):
    mid = '2D6A1-WAL-' + name
    MUTATIONS.append(Mutation(mid, '2d-6a-D1', name, ('test_capture_reader.' + killer,),
                              target='gen2/store/db.py', old=old, new=new, also=also))
    CONTROLS[mid] = {'controls': [control], 'why':
        'Accepted checked capture reaches the changed reader guard or cleanup; its literal topic/hash control stays valid without the removed property.'}


reader('snapshot', 'FileReaderTest.test_coherent_while_writer_commits',
       'conn.execute("BEGIN DEFERRED")', 'conn.execute("SELECT 1")',
       also=(('        conn.execute("COMMIT")\n    except BaseException as exc:',
              '        if conn.in_transaction:\n            conn.execute("COMMIT")\n    except BaseException as exc:'),))
reader('close', 'FileReaderTest.test_failure_closes_file_reader',
       '        conn.close()\n        return', '        pass\n        return')
reader('schema', 'FileReaderTest.test_schema_drift_refuses',
       '        check_schema_identity(conn)\n        if identity is not None:',
       '        pass\n        if identity is not None:')
reader('compatibility', 'FileReaderTest.test_schema_and_connection_failures_close_reader',
       '            compat.check_connection(conn)', '            pass')
reader('wal', 'FileReaderTest.test_nonwal_refuses',
       'if conn.execute("PRAGMA journal_mode").fetchone()[0] != "wal":', 'if False:')
reader('identity', 'FileReaderTest.test_file_identity_mismatch_refuses',
       'if (stat.st_dev, stat.st_ino) != expected:', 'if False:')
reader('dml', 'MemoryReaderTest.test_dml_is_prohibited',
       'conn.execute("PRAGMA query_only = ON")', 'conn.execute("PRAGMA query_only = OFF")',
       also=(('if conn.execute("PRAGMA query_only").fetchone()[0] != 1:', 'if False:'),))
reader('memory-restore', 'MemoryReaderTest.test_failure_releases_memory_reader',
       'conn.execute(f"PRAGMA query_only = {query_only}")', 'pass',
       also=(('if conn.execute("PRAGMA query_only").fetchone()[0] != query_only:', 'if False:'),),
       control=TEST + 'hash_control')
reader('query-only-readback', 'FileReaderTest.test_failed_pragma_readbacks_refuse',
       'if conn.execute("PRAGMA query_only").fetchone()[0] != 1:', 'if False:')
reader('operational-readback', 'FileReaderTest.test_failed_pragma_readbacks_refuse',
       'if conn.execute(f"PRAGMA {name}").fetchone()[0] != expected:', 'if False:')
