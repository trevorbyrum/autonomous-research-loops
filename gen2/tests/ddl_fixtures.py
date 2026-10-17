"""Restore requested trigger catalogs after unmutated fixture seeding."""
import sqlite3


TRIGGERS = "SELECT name,sql FROM sqlite_schema WHERE type='trigger' ORDER BY rowid"


def assert_triggers(case, expected):
    case.assertEqual(case.rows(TRIGGERS), expected, 'fixture reset requested trigger catalog/order')


def restore_triggers(case, ddl, omit=()):
    """Keep complete requested definitions/order, including mutations and drops.

    Tables/views may already have been replaced by the caller. Only triggers
    are restored here; explicit isolation omissions retain their relative order.
    Assert the actual catalog before returning control to the subject test.
    """
    with sqlite3.connect(':memory:') as reference:
        reference.executescript(ddl)
        expected = [(n, s) for n, s in reference.execute(TRIGGERS) if n not in omit]
    for name, _ in case.rows(TRIGGERS):
        case.x('DROP TRIGGER "' + name.replace('"', '""') + '"')
    for _, sql in expected:
        case.x(sql)
    assert_triggers(case, expected)
    return expected
