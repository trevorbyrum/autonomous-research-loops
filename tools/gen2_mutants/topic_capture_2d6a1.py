"""Fixed selection, immutable raw operands and history/byte hash controls."""
from .base import Mutation

TARGET = 'gen2/store/capture.py'
TEST = 'test_topic_capture.CaptureTest.test_'
MUTATIONS, CONTROLS = [], {}


def add(name, killer, old, new, target=TARGET):
    mid = '2D6A1-' + name
    MUTATIONS.append(Mutation(mid, '2d-6a1', name, (TEST + killer,), target=target, old=old, new=new))
    CONTROLS[mid] = {'controls': [TEST + 'hash_control'], 'why':
        'Independent accepted Router-owned capture and outside-lock native hash execute the changed path; assert topic identity and digest form without the removed property.'}


add('ownership', 'requires_owned_transaction', '        self._require_transaction()\n        return capture.read',
    '        pass\n        return capture.read', 'gen2/store/api.py')
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
