"""Explicit disposable history preparation; never a current admission route."""
from contextlib import contextmanager, nullcontext
import sqlite3
from unittest.mock import patch

from gen2.tests.ddl_fixtures import TRIGGERS, restore_triggers


@contextmanager
def history(case, *, unchecked=False):
    catalog = case.rows(TRIGGERS)
    checks = case.rows('PRAGMA ignore_check_constraints')[0][0]
    if unchecked:
        case.x('PRAGMA ignore_check_constraints=ON')
    for name, _ in catalog:
        case.x('DROP TRIGGER "' + name.replace('"', '""') + '"')
    try:
        yield
    finally:
        case.x("PRAGMA ignore_check_constraints=" + str(checks))
        restore_triggers(case, None, catalog=catalog)


def subject_views(case, ddl):
    # Seed real records under pristine DDL, then restore the actual subject
    # views as well as triggers (including mutants and trace instrumentation).
    with sqlite3.connect(':memory:') as reference:
        reference.executescript(ddl)
        views = reference.execute("SELECT name,sql FROM sqlite_schema WHERE type='view' ORDER BY rowid").fetchall()
    for name, _ in views:
        case.x('DROP VIEW "' + name + '"')
    for _, sql in views:
        case.x(sql)
    restore_triggers(case, ddl)


@contextmanager
def prior_consumption(case):
    """Isolate earlier predicates on explicit historical refusal operands."""
    catalog = case.rows(TRIGGERS)
    sql = case.rows("SELECT sql FROM sqlite_schema WHERE name='detailed_support_receipts'")[0][0]
    case.x('DROP VIEW detailed_support_receipts')
    case.x('CREATE VIEW detailed_support_receipts AS SELECT verification_receipt_id FROM verification_receipts')
    try:
        # Earlier SQL-predicate experiments explicitly suspend only the new
        # independent detailed promotion consumer, never current controls.
        router = getattr(case, 'router', None)
        with patch.object(router._detailed_checks, 'require_support', return_value=None) if router else nullcontext():
            yield
    finally:
        case.x('DROP VIEW detailed_support_receipts'); case.x(sql)
        case.assertEqual(case.rows(TRIGGERS), catalog)
