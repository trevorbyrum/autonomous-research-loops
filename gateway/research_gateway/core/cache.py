"""Identity-keyed cache with a redistribution policy (PLAN.md §6, I-8).

Redistributable records are persisted to gateway.records / record_sources with
their raw payload and served for `metadata_ttl`; only provenance members from
redistributable sources are written. Everything else lives in process memory
for at most `memory_ttl` (default one hour), bounded in size, and is never
written to the database or exported. Search results are memory-only.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Callable

from . import identity as ident
from .canonical import member_summary


class Cache:
    """Thread-safe: worker threads and front-door threads share one instance; the lock covers
    the memory stores and the cache's own database connection (never a worker's or the control one)."""

    def __init__(self, conn=None, *, clock: Callable[[], float] = time.time, memory_ttl: float = 3600.0,
                 metadata_ttl: float = 7 * 86400.0, search_ttl: float = 3600.0,
                 max_records: int = 10_000, max_searches: int = 2_000):
        self.conn, self._clock = conn, clock
        self.memory_ttl, self.metadata_ttl, self.search_ttl = memory_ttl, metadata_ttl, search_ttl
        self.max_records, self.max_searches = max_records, max_searches
        self._records: dict[str, tuple[float, dict]] = {}
        self._searches: dict[str, tuple[float, dict]] = {}
        self._lock = threading.RLock()
        self.persisted = 0
        self.evicted = 0

    # ------------------------------------------------------------ bounds
    def _bound(self, store: dict, limit: int) -> None:
        """Drop expired entries once the store is full; then the oldest, until it fits."""
        if len(store) < limit:
            return
        now = self._clock()
        for k in [k for k, (exp, _) in store.items() if exp <= now]:
            del store[k]
            self.evicted += 1
        while len(store) >= limit:
            del store[next(iter(store))]
            self.evicted += 1

    # ------------------------------------------------------------ records
    def get_record(self, identity: str) -> dict | None:
        key = ident.canonical(identity)
        with self._lock:
            hit = self._records.get(key)
            if hit and hit[0] > self._clock():
                return hit[1]
            if hit:
                del self._records[key]
            if self.conn is None:
                return None
            try:
                with self.conn.cursor() as cur:
                    cur.execute("SELECT canonical FROM gateway.records WHERE identity = %s AND last_seen > now() - make_interval(secs => %s)",
                                (key, self.metadata_ttl))
                    row = cur.fetchone()
                    members = []
                    if row and not row[0].get("provenance"):
                        # legacy rows persisted before the canonical summary existed: rebuild
                        # what record_sources still knows (licence + persistence time) so a
                        # reload never forgets WHO said what (finding 19). New rows carry the
                        # full original summary inside canonical and skip this.
                        cur.execute("SELECT source_id, license, fetched_at FROM gateway.record_sources "
                                    "WHERE identity = %s ORDER BY source_id", (key,))
                        members = [{"source_id": sid, "identity": key, "license": lic,
                                    "retrieved_at": fetched.isoformat(timespec="seconds") if fetched else None}
                                   for sid, lic, fetched in cur.fetchall()]
                self.conn.commit()
            except Exception:
                try:
                    self.conn.rollback()   # never leave the cache connection in an aborted transaction (D-24)
                except Exception:
                    pass
                raise
            if row is None:
                return None
            return {**row[0], "provenance": members} if members else row[0]

    def put_record(self, record: dict, *, redistributable: bool, persist_members: list[int] | None = None) -> None:
        """Keep the record in memory — for `metadata_ttl` only when EVERY member is redistributable,
        else `memory_ttl` (§6: a restricted member never outlives an hour) — and persist only the
        provenance members at the given INDEXES (each judged with its own licence; two entries
        from one source are separate, D-25), skipping members that carry no raw payload so a
        stored payload is never overwritten with nothing (D-23)."""
        key = ident.canonical(record["identity"])
        ttl = self.metadata_ttl if redistributable else self.memory_ttl
        with self._lock:
            self._bound(self._records, self.max_records)
            self._records[key] = (self._clock() + ttl, record)
            if self.conn is not None:
                try:
                    self._persist(key, record, persist_members if persist_members is not None
                                  else ([0] if redistributable else []))
                except Exception:
                    try:
                        self.conn.rollback()   # a failed persist never poisons the next one (D-24)
                    except Exception:
                        pass
                    raise

    def _persist(self, key: str, record: dict, persist_members: list[int]) -> None:
        # without explicit provenance the synthesized member list mirrors the router's exactly —
        # one entry per source in `sources` order, only the record's OWN source carrying its raw —
        # so a member index authorized there never lands on a different member here (D-26)
        provenance = record.get("provenance")
        if not provenance:
            own = record.get("source_id")
            provenance = [{"source_id": s, "raw": record.get("raw") if s == own else None,
                           "license": record.get("license") if s == own else None}
                          for s in record.get("sources") or [own]]
        members = [provenance[i] for i in persist_members if 0 <= i < len(provenance) and provenance[i].get("raw") is not None]
        if not members:
            return
        canonical = {k: v for k, v in record.items() if k not in ("raw", "provenance")}
        canonical["sources"] = [p["source_id"] for p in members]
        # the citation-grade member summary survives persistence VERBATIM (original
        # retrieval stamps, links, attribution — scalar strings only, never raw): a
        # reload must not replace two distinct retrieval times with the persistence
        # time (re-verify finding 19). All members' facts are kept, not only the
        # raw-persisted ones — facts are not payloads (D-25).
        canonical["provenance"] = [member_summary(m) for m in provenance if isinstance(m, dict)]
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO gateway.records (identity, kind, canonical, last_seen) VALUES (%s, %s, %s, now()) "
                "ON CONFLICT (identity) DO UPDATE SET kind = EXCLUDED.kind, canonical = EXCLUDED.canonical, last_seen = now()",
                (key, record["kind"], json.dumps(canonical, default=str)),
            )
            for prov in members:
                cur.execute(
                    "INSERT INTO gateway.record_sources (identity, source_id, raw, fetched_at, license, redistributable) "
                    "VALUES (%s, %s, %s, now(), %s, true) ON CONFLICT (identity, source_id) DO UPDATE SET "
                    "raw = EXCLUDED.raw, fetched_at = now(), license = EXCLUDED.license, redistributable = true",
                    (key, prov["source_id"], json.dumps(prov.get("raw"), default=str),
                     prov.get("license") if "license" in prov else record.get("license")),  # each member's own licence (D-23)
                )
        self.conn.commit()
        self.persisted += 1

    # ------------------------------------------------------------ searches
    @staticmethod
    def search_key(request_type: str, payload: dict) -> str:
        canon = json.dumps({"t": request_type, "p": payload}, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canon.encode()).hexdigest()

    def get_search(self, key: str) -> dict | None:
        with self._lock:
            hit = self._searches.get(key)
            if hit and hit[0] > self._clock():
                return hit[1]
            if hit:
                del self._searches[key]
            return None

    def put_search(self, key: str, result: dict) -> None:
        with self._lock:
            self._bound(self._searches, self.max_searches)
            self._searches[key] = (self._clock() + self.search_ttl, result)

    def stats(self) -> dict:
        now = self._clock()
        with self._lock:
            return {"records_in_memory": sum(1 for exp, _ in self._records.values() if exp > now),
                    "searches_in_memory": sum(1 for exp, _ in self._searches.values() if exp > now),
                    "persisted": self.persisted, "evicted": self.evicted}
