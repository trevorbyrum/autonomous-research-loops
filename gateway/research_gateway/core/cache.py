"""Identity-keyed cache with a redistribution policy (PLAN.md §6, I-8).

Redistributable records are persisted to gateway.records / record_sources with
their raw payload and served for `metadata_ttl`. Everything else lives in
process memory for at most `memory_ttl` (default one hour) and is never written
to the database or exported. Search results are memory-only.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Callable

from . import identity as ident


class Cache:
    def __init__(self, conn=None, *, clock: Callable[[], float] = time.time, memory_ttl: float = 3600.0,
                 metadata_ttl: float = 7 * 86400.0, search_ttl: float = 3600.0):
        self.conn, self._clock = conn, clock
        self.memory_ttl, self.metadata_ttl, self.search_ttl = memory_ttl, metadata_ttl, search_ttl
        self._records: dict[str, tuple[float, dict]] = {}
        self._searches: dict[str, tuple[float, dict]] = {}
        self.persisted = 0

    # ------------------------------------------------------------ records
    def get_record(self, identity: str) -> dict | None:
        key = ident.canonical(identity)
        hit = self._records.get(key)
        if hit and hit[0] > self._clock():
            return hit[1]
        if hit:
            del self._records[key]
        if self.conn is None:
            return None
        with self.conn.cursor() as cur:
            cur.execute("SELECT canonical FROM gateway.records WHERE identity = %s AND last_seen > now() - make_interval(secs => %s)",
                        (key, self.metadata_ttl))
            row = cur.fetchone()
        self.conn.commit()
        return row[0] if row else None

    def put_record(self, record: dict, *, redistributable: bool) -> None:
        key = ident.canonical(record["identity"])
        ttl = self.metadata_ttl if redistributable else self.memory_ttl
        self._records[key] = (self._clock() + ttl, record)
        if redistributable and self.conn is not None:
            self._persist(key, record)

    def _persist(self, key: str, record: dict) -> None:
        canonical = {k: v for k, v in record.items() if k not in ("raw", "provenance")}
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO gateway.records (identity, kind, canonical, last_seen) VALUES (%s, %s, %s, now()) "
                "ON CONFLICT (identity) DO UPDATE SET kind = EXCLUDED.kind, canonical = EXCLUDED.canonical, last_seen = now()",
                (key, record["kind"], json.dumps(canonical, default=str)),
            )
            for prov in record.get("provenance") or [{"source_id": record["source_id"], "raw": record.get("raw")}]:
                cur.execute(
                    "INSERT INTO gateway.record_sources (identity, source_id, raw, fetched_at, license, redistributable) "
                    "VALUES (%s, %s, %s, now(), %s, true) ON CONFLICT (identity, source_id) DO UPDATE SET "
                    "raw = EXCLUDED.raw, fetched_at = now(), license = EXCLUDED.license, redistributable = true",
                    (key, prov["source_id"], json.dumps(prov.get("raw"), default=str), record.get("license")),
                )
        self.conn.commit()
        self.persisted += 1

    # ------------------------------------------------------------ searches
    @staticmethod
    def search_key(request_type: str, payload: dict) -> str:
        canon = json.dumps({"t": request_type, "p": payload}, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canon.encode()).hexdigest()

    def get_search(self, key: str) -> dict | None:
        hit = self._searches.get(key)
        if hit and hit[0] > self._clock():
            return hit[1]
        if hit:
            del self._searches[key]
        return None

    def put_search(self, key: str, result: dict) -> None:
        self._searches[key] = (self._clock() + self.search_ttl, result)

    def stats(self) -> dict:
        now = self._clock()
        return {"records_in_memory": sum(1 for exp, _ in self._records.values() if exp > now),
                "searches_in_memory": sum(1 for exp, _ in self._searches.values() if exp > now),
                "persisted": self.persisted}
