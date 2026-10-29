"""Restore trigger catalogs after explicit historical/corrupt-operand isolation."""


TRIGGERS = "SELECT name,sql FROM sqlite_schema WHERE type='trigger' ORDER BY rowid"


def assert_triggers(case, expected):
    case.assertEqual(case.rows(TRIGGERS), expected, 'fixture reset requested trigger catalog/order')


def restore_triggers(case, *, catalog):
    """Restore the captured definitions and assert the complete catalog."""
    expected = catalog
    for name, _ in case.rows(TRIGGERS):
        case.x('DROP TRIGGER "' + name.replace('"', '""') + '"')
    for _, sql in expected:
        case.x(sql)
    assert_triggers(case, expected)
    return expected
