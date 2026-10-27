"""Explicit disposable history preparation; never a current admission route."""
from contextlib import contextmanager
import sqlite3

from gen2.core import canonical

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


def insert_receipt(case, doc):
    """Explicit historical/corrupt operand; never current receipt admission."""
    d = doc
    values = [d['verification_receipt_id'], d['topic_id'], d['claim']['claim_id'], d['claim']['claim_revision'],
        d['source']['work_id'], d['source']['source_version'], d['cited_spans'], d['obtained_content_hash'],
        d['access_tier'], d['requested_for']['use'], d['requested_for']['required_access_tier'], d['acquisition'],
        d['extraction']['method'], d['extraction']['produced_by_invocation_id'], d['extraction']['validation_ref'],
        d['producer_invocation_id'], d['verifier_invocation_id'], d['quote_check_id'], d['verdict'], d, d['verified_at']]
    try:
        case.x('INSERT INTO verification_receipts VALUES (' + ','.join('?' * len(values)) + ')',
            *[canonical.canonical_bytes(v).decode() if isinstance(v, (dict, list)) else v for v in values])
        return {'status': 'committed'}
    except sqlite3.IntegrityError as exc:
        return {'status': 'rejected', 'detail': str(exc)}
