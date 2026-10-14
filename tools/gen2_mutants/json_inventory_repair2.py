"""Predicate-level mutations of exhaustive classification, with CLI controls."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
TEST = 'test_json_inventory.InventoryTest.test_'


def add(name, killer, control, old, new, also=()):
    mid = 'JSON-INVENTORY-' + name
    MUTATIONS.append(Mutation(mid, '2d-4b3e1-repair-2', name, (TEST + killer,),
        old=old, new=new, also=also, target='tools/gen2_json_member_domain.py'))
    CONTROLS[mid] = {'controls': [TEST + control], 'why':
        'Independent literal-schema CLI control passes under this inventory predicate mutation.'}


for case in ('quoted_check', 'comment_check', 'quoted_view', 'string_view', 'ordinary_view'):
    add(case, case, case + '_control', 'used.add(name)',
        "if name in manifest.get('scalar', []) or name in manifest['covered'] or name in manifest['pending']: used.add(name)")
add('alias', 'alias', 'alias_control', "if name in RETAINED_BYTES and kind == 'BLOB':",
    "if name.rsplit('.', 1)[-1] == 'response_bytes':")
add('snapshot', 'existing_scalar_new_use', 'scalar_control',
    "if (manifest.get('schema_sha256') == schema_sha256(conn)", 'if (True')
add('ddl-snapshot', 'statement_without_catalog_object', 'scalar_control',
    "and manifest.get('ddl_sha256') == hashlib.sha256(sql.encode()).hexdigest()", 'and True')
add('temporary', 'temporary_schema', 'scalar_control',
    "failures.append('JSON member domain cannot classify temporary objects')", 'pass')
add('attached', 'attached_schema', 'scalar_control',
    "failures.append('JSON member domain cannot classify attached schemas')", 'pass')
add('user-prefix', 'sqlite_prefix_is_user_table', 'scalar_control',
    "WHERE name NOT GLOB 'sqlite_*' ORDER BY type, name", "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name",
    also=(("WHERE type='table' AND name NOT GLOB 'sqlite_*'", "WHERE type='table' AND name NOT LIKE 'sqlite_%'"),))
add('generated', 'generated_column', 'scalar_control',
    "SELECT * FROM pragma_table_xinfo(?)", "SELECT * FROM pragma_table_xinfo(?) WHERE hidden = 0")
for case in ('unclassified_blob', 'retained_wrong_type', 'unclassified_any'):
    add(case, case, 'alias_control', "if kind in ('BLOB', 'ANY') or name in RETAINED_BYTES:", 'if False:')
add('scalar-stale', 'scalar_stale', 'scalar_control',
    'if len(scalar) != len(set(scalar)) or set(scalar) - used:', 'if False:')
add('scalar-overlap', 'scalar_overlap', 'quoted_check_control',
    "if set(scalar) & (set(manifest['covered']) | manifest['pending'].keys() | serialized):", 'if False:')
add('serialized', 'serialized_scalar', 'scalar_control', 'return used | serialized, failures', 'return used, failures')
add('view-prepare', 'unresolved_view', 'view_control',
    "failures.append(f'JSON member domain cannot prepare view {view}: {exc}')", 'pass')
for event in ('INSERT', 'UPDATE', 'DELETE'):
    add(event.lower() + '-prepare', 'unresolved_' + event.lower(), 'trigger_control',
        "conn.execute('EXPLAIN ' + statement).fetchall()",
        f"if not statement.startswith('{event}'): conn.execute('EXPLAIN ' + statement).fetchall()")
