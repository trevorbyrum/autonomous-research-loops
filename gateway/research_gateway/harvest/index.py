"""Tier 0 index (PLAN.md §8): canonical records → gateway.records / record_sources /
index_docs (Postgres full-text). Loaders hand records here; nothing else writes the index.

    python3 -m research_gateway.harvest.index --counts     # rows per kind and per loader
    python3 -m research_gateway.harvest.index --reindex    # rebuild index_docs from records
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Iterable

from ..core import db

BATCH = 500


class IssnMap:
    """ISSN → the identity already holding it, so a journal known under several ISSNs (print,
    electronic, ISSN-L) is one record whichever registry mentions it first. Loaded once per run
    from the stored venues; new records register their ISSNs as they are written."""

    def __init__(self, conn=None):
        self._map: dict[str, str] = {}
        if conn is not None:
            with conn.cursor() as cur:
                cur.execute("SELECT identity, canonical->'issns' FROM gateway.records WHERE kind = 'venue' AND canonical ? 'issns'")
                for identity, issns in cur.fetchall():
                    for i in issns or []:
                        self._map.setdefault(str(i), identity)
            conn.commit()

    def identity_for(self, issns: list[str], preferred: str | None = None) -> str | None:
        """The existing identity for any of these ISSNs, else `preferred`, else None; every ISSN
        given is then known to belong to that identity (so a later row with only the other ISSN joins too)."""
        found = next((self._map[i] for i in issns if i in self._map), preferred)
        if found:
            for i in issns:
                self._map.setdefault(i, found)
        return found

    def __len__(self) -> int:
        return len(self._map)


def text_for(record: dict) -> str:
    """What the full-text index sees for a record: names, publisher, identifiers, subjects, country."""
    parts = [record.get("title"), record.get("venue"), record.get("description")]
    parts += list((record.get("identifiers") or {}).values())
    parts += list(record.get("subjects") or [])
    parts += list(record.get("aliases") or [])
    parts.append(record.get("country"))
    return " ".join(str(p) for p in parts if p)


def upsert(cur, record: dict, source_id: str, *, license: str | None = None) -> None:
    """Merge one record: canonical fields fill in (later loaders add, never erase), a
    provenance row per loader, and the index document."""
    canonical = {k: v for k, v in record.items() if k not in ("raw", "provenance") and v not in (None, "", [], {})}
    cur.execute(
        "INSERT INTO gateway.records (identity, kind, canonical, last_seen) VALUES (%s, %s, %s, now()) "
        "ON CONFLICT (identity) DO UPDATE SET canonical = gateway.records.canonical || EXCLUDED.canonical, last_seen = now()",
        (record["identity"], record["kind"], json.dumps(canonical, default=str)),
    )
    cur.execute(
        "INSERT INTO gateway.record_sources (identity, source_id, raw, fetched_at, license, redistributable) "
        "VALUES (%s, %s, %s, now(), %s, true) ON CONFLICT (identity, source_id) DO UPDATE SET "
        "raw = EXCLUDED.raw, fetched_at = now(), license = EXCLUDED.license",
        (record["identity"], source_id, json.dumps(record.get("raw"), default=str), license or record.get("license")),
    )
    cur.execute(
        "INSERT INTO gateway.index_docs (identity, kind, domain, year, tsv) "
        "VALUES (%s, %s, %s, %s, to_tsvector('english', %s)) ON CONFLICT (identity) DO UPDATE SET "
        "kind = EXCLUDED.kind, domain = COALESCE(EXCLUDED.domain, gateway.index_docs.domain), "
        "year = COALESCE(EXCLUDED.year, gateway.index_docs.year), tsv = EXCLUDED.tsv",
        (record["identity"], record["kind"], record.get("domain"), record.get("year"), text_for(record)),
    )


LOADER_LOCK = 7_310_001   # advisory lock key: loaders run one at a time (they upsert overlapping identities)


def load(conn, records: Iterable[dict], source_id: str, *, license: str | None = None, batch: int = BATCH) -> int:
    """Upsert a stream of records in batches under the loader lock; returns how many were written.
    A batch that still deadlocks (another writer on the same rows) is retried a few times."""
    n = 0
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", (LOADER_LOCK,))
    conn.commit()
    try:
        pending: list[dict] = []
        for rec in records:
            pending.append(rec)
            if len(pending) >= batch:
                n += _write_batch(conn, pending, source_id, license)
                pending = []
        if pending:
            n += _write_batch(conn, pending, source_id, license)
    finally:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (LOADER_LOCK,))
        conn.commit()
    return n


def _write_batch(conn, batch: list[dict], source_id: str, license: str | None, attempts: int = 3) -> int:
    import psycopg
    for attempt in range(attempts):
        try:
            with conn.cursor() as cur:
                for rec in batch:
                    upsert(cur, rec, source_id, license=license)
            conn.commit()
            return len(batch)
        except psycopg.errors.DeadlockDetected:
            conn.rollback()
            if attempt == attempts - 1:
                raise
    return 0


def reindex(conn, identities: list[str] | None = None) -> int:
    """Rebuild index documents from the stored canonical records (all of them, or the given identities)."""
    with conn.cursor() as cur:
        if identities is None:
            cur.execute("SELECT identity, kind, canonical FROM gateway.records")
        else:
            cur.execute("SELECT identity, kind, canonical FROM gateway.records WHERE identity = ANY(%s)", (list(identities),))
        rows = cur.fetchall()
        for identity, kind, canonical in rows:
            rec = dict(canonical)
            cur.execute(
                "INSERT INTO gateway.index_docs (identity, kind, domain, year, tsv) VALUES (%s, %s, %s, %s, to_tsvector('english', %s)) "
                "ON CONFLICT (identity) DO UPDATE SET kind = EXCLUDED.kind, tsv = EXCLUDED.tsv",
                (identity, kind, rec.get("domain"), rec.get("year"), text_for(rec)),
            )
    conn.commit()
    return len(rows)


def counts(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT kind, count(*) FROM gateway.index_docs GROUP BY kind ORDER BY kind")
        by_kind = dict(cur.fetchall())
        cur.execute("SELECT source_id, count(*) FROM gateway.record_sources GROUP BY source_id ORDER BY source_id")
        by_loader = dict(cur.fetchall())
        cur.execute("SELECT count(*) FROM gateway.records")
        records = cur.fetchone()[0]
    conn.commit()
    return {"records": records, "index_by_kind": by_kind, "provenance_by_source": by_loader}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--counts", action="store_true")
    ap.add_argument("--reindex", action="store_true")
    args = ap.parse_args(argv)
    with db.connect() as conn:
        if args.reindex:
            print(f"reindexed {reindex(conn)} records")
        print(json.dumps(counts(conn), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
