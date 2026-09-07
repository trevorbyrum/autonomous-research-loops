"""OpenAlex from the local index only (D-2): no live calls, ever.

`find` searches gateway.index_docs (Postgres full-text) and returns the
canonical records the harvest stored in gateway.records. Phase 6 loads them;
until then the index is simply empty and `find` returns nothing, truthfully.
"""
from __future__ import annotations

import time

from .base import Client

SOURCE_ID = "openalex_snapshot"
SMOKE = {'local': 'local index, no network'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find",)
LOCAL = True   # answers from the local index; the router runs it before any live lane (§8)


def find(client: Client, query: str, *, limit: int = 20, kind: str | None = None, domain: str | None = None,
         year_from_: int | None = None) -> dict:
    conn = client.conn
    if conn is None:
        return {"records": [], "total": 0, "capability_fact": "local index needs a database connection"}
    where = ["d.tsv @@ websearch_to_tsquery('english', %s)"]
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
        "FROM gateway.index_docs d JOIN gateway.records r ON r.identity = d.identity "
        f"WHERE {' AND '.join(where)} "   # the WHERE clauses are fixed strings; every value is a bound parameter
        "ORDER BY rank DESC, "
        "CASE WHEN r.canonical->>'works_count' ~ '^[0-9]{1,15}$' THEN (r.canonical->>'works_count')::bigint END DESC NULLS LAST, "
        "d.year DESC NULLS LAST LIMIT %s"
    )
    t0 = time.monotonic()
    with conn.cursor() as cur:
        cur.execute(sql, [query, *args, max(1, min(int(limit or 20), 100))])
        rows = cur.fetchall()
        cur.execute(f"SELECT count(*) FROM gateway.index_docs d WHERE {' AND '.join(where)}", args)
        total = cur.fetchone()[0]
    conn.commit()
    client.local(SOURCE_ID, "find", query=query, result_count=len(rows), latency_ms=int((time.monotonic() - t0) * 1000))
    records = []
    for identity, canonical, rank in rows:
        rec = dict(canonical)
        rec.setdefault("identity", identity)
        rec["source_id"] = SOURCE_ID
        rec["rank"] = float(rank)
        records.append(rec)
    return {"records": records, "total": total}
