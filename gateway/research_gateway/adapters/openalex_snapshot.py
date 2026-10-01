"""OpenAlex from the local index only (D-2): no live calls, ever.

`find` searches gateway.index_docs (Postgres full-text) and returns the
canonical records the harvest stored, read through gateway.servable_records, the one
serving read. Phase 6 loads them; until then the index is simply empty and `find`
returns nothing, truthfully. A match that view withholds (a row not yet converted,
2b-repair-5 F2) is never served, and is counted as `withheld`: the router reports the
lane partial, never complete. Pages cut one total order of the served matches (rank, then
the identity breaking ties), and a page reads one row past `limit`, so it says positively
either where the next page starts or that nothing remains (2b-repair-6 F3).

An offset means something only in the population it was counted in, so the continuation
names that population: `<offset>:<digest of every served match, in order>`. The page, the
counts and the digest are read in ONE statement — one snapshot. A later page is read only
while the index still holds exactly that population; after a delete, an insert, a converted
row or a reordering the offset would skip or repeat matches, so that page reads nothing and
ends nothing (ContinuationInvalid; 2b-repair-7 F3-R1). The search cache cannot splice two
populations either: a page's cache key is its continuation, digest included.
"""
from __future__ import annotations

import re
import time

from .base import Client, ContinuationInvalid

SOURCE_ID = "openalex_snapshot"
SMOKE = {'local': 'local index, no network'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find",)
LOCAL = True   # answers from the local index; the router runs it before any live lane (§8)
CONTINUATION = re.compile(r"([1-9][0-9]*):([0-9a-f]{16})")


def _position(offset) -> tuple[int, str | None]:
    """(where the page starts, the population digest it was counted in); a first page names none."""
    if offset in (None, 0):
        return 0, None
    m = CONTINUATION.fullmatch(str(offset))
    if m is None:
        raise ValueError(f"{SOURCE_ID}: {offset!r} is not a continuation this lane gave")
    return int(m.group(1)), m.group(2)


def find(client: Client, query: str, *, limit: int = 20, kind: str | None = None, domain: str | None = None,
         year_from_: int | None = None, offset: int | str = 0) -> dict:
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
        "WITH m AS (SELECT r.identity, r.canonical, d.year, ts_rank(d.tsv, websearch_to_tsquery('english', %s)) AS rank, "
        "CASE WHEN r.canonical->>'works_count' ~ '^[0-9]{1,15}$' THEN (r.canonical->>'works_count')::bigint END AS works "
        "FROM gateway.index_docs d JOIN gateway.servable_records r ON r.identity = d.identity "
        f"WHERE {' AND '.join(where)}), "   # fixed strings; every value is a bound parameter
        "served AS (SELECT identity, canonical, rank, row_number() OVER "
        "(ORDER BY rank DESC, works DESC NULLS LAST, year DESC NULLS LAST, identity) AS pos FROM m WHERE canonical IS NOT NULL) "
        "SELECT (SELECT count(*) FROM served), (SELECT count(*) FROM m WHERE canonical IS NULL), "
        "(SELECT left(encode(sha256(convert_to(coalesce(string_agg(length(identity) || ':' || identity, ' ' ORDER BY pos), ''), "
        "'UTF8')), 'hex'), 16) FROM served), "
        "(SELECT coalesce(json_agg(json_build_array(identity, canonical, rank::float8) ORDER BY pos), '[]') "
        "FROM served WHERE pos > %s AND pos <= %s)"
    )
    size = max(1, min(int(limit or 20), 100))
    start, counted_in = _position(offset)
    t0 = time.monotonic()
    with client.db_lock:   # the shared connection's TRANSACTION is the hazard under parallel lanes (9·2b)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, [query, *args, start, start + size + 1])   # one row past the page: does anything remain?
                total, withheld, population, rows = cur.fetchone()
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
    if counted_in is not None and population != counted_in:
        raise ContinuationInvalid(f"the local index changed since this search's first page: offset {start} no longer "
                                  "falls where it did, so continuing would skip or repeat matches — search again from the first page")
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
            "next_offset": f"{start + size}:{population}" if more else None, "exhausted": not more}
