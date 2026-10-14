"""R2-1: literal schema probes, CLI refusals, and independent classifications."""
import json
import sqlite3
import unittest

from gen2.tests import test_check_ddl_rules as ddl

GUARDED = ddl.GUARDED

QUOTED_CHECK = GUARDED.replace('v TEXT', 'v TEXT CHECK ("json_valid"(v))')
COMMENT_CHECK = GUARDED.replace('v TEXT', 'v TEXT CHECK (json_valid /* JSON syntax */ (v))')
QUOTED_VIEW = GUARDED + 'CREATE VIEW operand AS SELECT "json_extract"(v, \'$.a\') FROM t;'
STRING_VIEW = GUARDED + "CREATE VIEW operand AS SELECT '--' AS label, json_extract(v, '$.a') FROM t;"
ORDINARY_VIEW = GUARDED + "CREATE VIEW operand AS SELECT json_extract(v, '$.a') FROM t;"
ALIAS_VIEW = GUARDED.replace('v TEXT', 'response_bytes TEXT') + \
    "CREATE VIEW operand AS SELECT json_extract(CAST(a.response_bytes AS TEXT), '$.a') FROM t a;"
RAW_CONTROL = """-- trace: retained-byte control
CREATE TABLE source_acquisitions (id TEXT PRIMARY KEY, response_bytes BLOB) STRICT;
CREATE TRIGGER raw_no_delete BEFORE DELETE ON source_acquisitions
BEGIN SELECT RAISE(ABORT, 'never deleted'); END;
CREATE VIEW operand AS SELECT json_extract(CAST(a.response_bytes AS TEXT), '$.a') FROM source_acquisitions a;
"""
OWNER = '2d-4b3e1-repair-1 part 2'


class InventoryTest(unittest.TestCase):
    setUp = ddl.DdlRuleTest.setUp
    tearDown = ddl.DdlRuleTest.tearDown
    run_check = ddl.DdlRuleTest.run_check

    def manifest(self, schema, scalar, pending=()):
        manifest = ddl.classification(schema, scalar)
        manifest['pending'] = dict.fromkeys(pending, OWNER)
        (self.root / 'tools').mkdir(exist_ok=True)
        (self.root / 'tools/gen2_json_member_domain.json').write_text(json.dumps(manifest))

    def pair(self, schema, accepted=False, name='t.v'):
        # Pin even the new schema: an unknown column must fail independently
        # of hash drift. Accepted controls explicitly assign its pending owner.
        self.manifest(schema, ['t.id'], [name] if accepted else [])
        result = self.run_check(schema)
        self.assertEqual(result.returncode, 0 if accepted else 1, result.stderr)
        if not accepted:
            self.assertIn('JSON member domain uncovered column: ' + name, result.stderr)

    def test_quoted_check(self): self.pair(QUOTED_CHECK)
    def test_quoted_check_control(self): self.pair(QUOTED_CHECK, True)
    def test_comment_check(self): self.pair(COMMENT_CHECK)
    def test_comment_check_control(self): self.pair(COMMENT_CHECK, True)
    def test_quoted_view(self): self.pair(QUOTED_VIEW)
    def test_quoted_view_control(self): self.pair(QUOTED_VIEW, True)
    def test_string_view(self): self.pair(STRING_VIEW)
    def test_string_view_control(self): self.pair(STRING_VIEW, True)
    def test_ordinary_view(self): self.pair(ORDINARY_VIEW)
    def test_ordinary_view_control(self): self.pair(ORDINARY_VIEW, True)
    def test_alias(self): self.pair(ALIAS_VIEW, name='t.response_bytes')

    def test_alias_control(self):
        self.manifest(RAW_CONTROL, ['source_acquisitions.id'])
        result = self.run_check(RAW_CONTROL)
        self.assertEqual(result.returncode, 0, result.stderr)
        with sqlite3.connect(':memory:') as conn:
            conn.executescript(RAW_CONTROL)
            conn.execute('INSERT INTO source_acquisitions VALUES (?,?)', ('p', b'{"a":7}'))
            self.assertEqual(conn.execute('SELECT * FROM operand').fetchall(), [(7,)])

    def test_existing_scalar_new_use(self):
        self.manifest(GUARDED, ['t.id', 't.v'])
        # Isolate the catalog binding even if someone refreshed only the DDL hash.
        path = self.root / 'tools/gen2_json_member_domain.json'
        manifest = json.loads(path.read_text())
        manifest['ddl_sha256'] = ddl.classification(ORDINARY_VIEW, [])['ddl_sha256']
        path.write_text(json.dumps(manifest))
        result = self.run_check(ORDINARY_VIEW)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('schema classification changed', result.stderr)
        self.assertIn('JSON member domain uncovered column: t.v', result.stderr)

    def test_scalar_control(self):
        self.manifest(GUARDED, ['t.id', 't.v'])
        result = self.run_check(GUARDED)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_statement_without_catalog_object(self):
        self.manifest(GUARDED, ['t.id', 't.v'])
        result = self.run_check(GUARDED + "SELECT json_extract(v, '$.a') FROM t;")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('schema classification changed', result.stderr)

    def test_temporary_schema(self):
        schema = GUARDED + 'CREATE TEMP VIEW transient AS SELECT json_extract(v, \'$.a\') FROM t;'
        self.manifest(schema, ['t.id', 't.v'])
        result = self.run_check(schema)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('cannot classify temporary objects', result.stderr)

    def test_attached_schema(self):
        schema = GUARDED + "ATTACH ':memory:' AS extra; CREATE TABLE extra.t (v TEXT);"
        self.manifest(schema, ['t.id', 't.v'])
        result = self.run_check(schema)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('cannot classify attached schemas', result.stderr)

    def test_sqlite_prefix_is_user_table(self):
        schema = GUARDED + """
        -- trace: a legitimate user name, outside SQLite's reserved sqlite_ prefix
        CREATE TABLE sqliteprobe (id TEXT PRIMARY KEY, v TEXT CHECK (json_valid(v))) STRICT;
        CREATE TRIGGER sqliteprobe_guard BEFORE DELETE ON sqliteprobe
        BEGIN SELECT RAISE(ABORT, 'never deleted'); END;
        """
        self.manifest(GUARDED, ['t.id', 't.v'])
        result = self.run_check(schema)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('JSON member domain uncovered column: sqliteprobe.v', result.stderr)

    def test_generated_column(self):
        schema = GUARDED.replace('v TEXT', "v TEXT, g TEXT GENERATED ALWAYS AS ('scalar') STORED")
        self.manifest(schema, ['t.id', 't.v'])
        result = self.run_check(schema)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('JSON member domain uncovered column: t.g', result.stderr)

    def test_unclassified_blob(self):
        schema = GUARDED.replace('v TEXT', 'v BLOB')
        self.manifest(schema, ['t.id'], ['t.v'])
        result = self.run_check(schema)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('unclassified storage type: t.v (BLOB)', result.stderr)

    def test_retained_wrong_type(self):
        schema = RAW_CONTROL.replace('response_bytes BLOB', 'response_bytes TEXT')
        self.manifest(schema, ['source_acquisitions.id'], ['source_acquisitions.response_bytes'])
        result = self.run_check(schema)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('unclassified storage type: source_acquisitions.response_bytes (TEXT)', result.stderr)

    def test_unclassified_any(self):
        schema = GUARDED.replace('v TEXT', 'v ANY')
        self.manifest(schema, ['t.id'], ['t.v'])
        result = self.run_check(schema)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('unclassified storage type: t.v (ANY)', result.stderr)

    def test_scalar_stale(self):
        self.manifest(GUARDED, ['t.id', 't.v', 't.absent'])
        result = self.run_check(GUARDED)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('scalar classifications repeated/stale', result.stderr)

    def test_scalar_overlap(self):
        schema = GUARDED.replace('v TEXT', 'v TEXT CHECK (json_valid(v))')
        self.manifest(schema, ['t.id', 't.v'], ['t.v'])
        result = self.run_check(schema)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('scalar classifications overlap JSON columns', result.stderr)

    def test_serialized_scalar(self):
        schema = GUARDED.replace('v TEXT', 'v TEXT CHECK (json_valid(v))')
        self.manifest(schema, ['t.id', 't.v'])
        result = self.run_check(schema)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('JSON member domain uncovered column: t.v', result.stderr)

    def view(self, function):
        schema = GUARDED + f'CREATE VIEW operand AS SELECT {function}(v) FROM t;'
        self.manifest(schema, ['t.id', 't.v'])
        return self.run_check(schema)

    def test_unresolved_view(self):
        result = self.view('unknown_function')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('cannot prepare view operand', result.stderr)

    def test_view_control(self):
        result = self.view('length')
        self.assertEqual(result.returncode, 0, result.stderr)

    def trigger(self, event, function):
        schema = GUARDED + f'CREATE TRIGGER probe BEFORE {event} ON t BEGIN SELECT {function}(1); END;'
        self.manifest(schema, ['t.id', 't.v'])
        return self.run_check(schema)

    def test_unresolved_insert(self):
        result = self.trigger('INSERT', 'unknown_function')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('cannot prepare INSERT', result.stderr)

    def test_unresolved_update(self):
        result = self.trigger('UPDATE OF v', 'unknown_function')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('cannot prepare UPDATE', result.stderr)

    def test_unresolved_delete(self):
        result = self.trigger('DELETE', 'unknown_function')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('cannot prepare DELETE', result.stderr)

    def test_trigger_control(self):
        for event in ('INSERT', 'UPDATE OF v', 'DELETE'):
            with self.subTest(event=event):
                result = self.trigger(event, 'length')
                self.assertEqual(result.returncode, 0, result.stderr)
