"""OpenAlex from the local index only (D-2): no live calls, ever.

`find` searches gateway.index_docs (Postgres full-text) and returns the
canonical records the harvest stored, read through gateway.servable_records, the one
serving read. Phase 6 loads them; until then the index is simply empty and `find`
returns nothing, truthfully. A match that view withholds (a row not yet converted,
2b-repair-5 F2) is never served, and is counted as `withheld`: the router reports the
lane partial, never complete. Pages are offsets into one total order (rank, then the
identity breaking ties): a page reads one row past `limit`, so it says positively either
where the next page starts or that nothing remains (2b-repair-6 F3).
"""
from __future__ import annotations

import time

from .base import Client

SOURCE_ID = "openalex_snapshot"
SMOKE = {'local': 'local index, no network'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find",)
LOCAL = True   # answers from the local index; the router runs it before any live lane (§8)


def find(client: Client, query: str, *, limit: int = 20, kind: str | None = None, domain: str | None = None,
         year_from_: int | None = None, offset: int = 0) -> dict:
    conn = client.conn
    if conn is None:
        return {"records": [], "total": 0, "capability_fact": "local index needs a database connection"}
    # only the index's contracted population is ever served (D-19): rows of any other kind —
    # e.g. left behind by an older loader — can neither surface nor borrow this source's identity (D-25)
    where = ["d.tsv @@ websearch_to_tsquery('english', %s)",
             "d.kind IN ('venue', 'repository')", "r.kind = d.kind"]  # a mislabelled index row cannot borrow a record of another kind (D-26)
    args: list = [query]
    if kind:
        where.append("d.kind = %s")
        args.append(kind)
    if domain and domain != "other":
        where.append("(d.domain = %s OR d.domain IS NULL)")
        args.append(domain)
    if year_from_:
        where.append("d.year >= %s")
        args.append(year_from_)
    sql = (
        "SELECT r.identity, r.canonical, ts_rank(d.tsv, websearch_to_tsquery('english', %s)) AS rank "
        "FROM gateway.index_docs d JOIN gateway.servable_records r ON r.identity = d.identity "
        f"WHERE {' AND '.join(where)} AND r.canonical IS NOT NULL "   # fixed strings; every value is a bound parameter
        "ORDER BY rank DESC, "
        "CASE WHEN r.canonical->>'works_count' ~ '^[0-9]{1,15}$' THEN (r.canonical->>'works_count')::bigint END DESC NULLS LAST, "
        "d.year DESC NULLS LAST, r.identity LIMIT %s OFFSET %s"
    )
    size, start = max(1, min(int(limit or 20), 100)), int(offset or 0)
    if start < 0:
        raise ValueError(f"{SOURCE_ID}: a page cannot start at offset {start}")
    t0 = time.monotonic()
    with client.db_lock:   # the shared connection's TRANSACTION is the hazard under parallel lanes (9·2b)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, [query, *args, size + 1, start])   # one row past the page: does anything remain?
                rows = cur.fetchall()
                cur.execute("SELECT count(r.canonical), count(*) - count(r.canonical) FROM gateway.index_docs d "
                            f"JOIN gateway.servable_records r ON r.identity = d.identity WHERE {' AND '.join(where)}", args)
                total, withheld = cur.fetchone()
            conn.commit()
        except Exception:
            # the transaction is RECOVERED before the lock is released: a failed local query
            # must never leave the shared connection aborted for the sibling lane whose
            # call-log write would then raise AuditError and fail the whole request (9·2b)
            try:
                conn.rollback()
            except Exception:
                pass
            raise
    more, rows = len(rows) > size, rows[:size]
    client.local(SOURCE_ID, "find", query=query, result_count=len(rows), latency_ms=int((time.monotonic() - t0) * 1000))
    records = []
    for identity, canonical, rank in rows:
        rec = dict(canonical)
        rec.setdefault("identity", identity)
        rec["source_id"] = SOURCE_ID
        rec["rank"] = float(rank)
        records.append(rec)
    return {"records": records, "total": total, "withheld": withheld,
            "next_offset": start + size if more else None, "exhausted": not more}
