"""A child process for test_router_crash.py (not collected as tests).

  python -m gen2.tests.router_crash_child <dir> prepare
      create a durable store in <dir>, build the world through the router,
      stage one final outcome in a file spool, write the envelope and a
      snapshot of every table to <dir>;
  python -m gen2.tests.router_crash_child <dir> crash <point>
      open the store and submit the envelope with a fault hook that ends the
      process with os._exit at <point> — no exception, no rollback, no
      cleanup runs in this process;
  python -m gen2.tests.router_crash_child <dir> resubmit
      open the store and submit the same envelope again, printing the
      response;
  python -m gen2.tests.router_crash_child <dir> transition
      open the store and submit the record_transition request read from
      stdin, printing the response (test_router_restart.py: a lost lifecycle
      reply resent from a process that shares nothing with the one that
      recorded it).

The world and the outcome are the same as the in-memory tests': a queued
topic, a running contract-admitted research pass, and a final outcome that
captures and promotes a claim, records a trigger and a hold, and requeues.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

from gen2.core import canonical
from gen2.router import service
from gen2.store import api
from gen2.tests import router_fixtures as rf
from gen2.tests import store_fixtures


class FileSpool:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(exist_ok=True)

    def put(self, raw: bytes, label: str | None = None, media_type: str = "application/json") -> str:
        digest = canonical.bytes_digest(raw)
        (self.directory / digest.replace(":", "_")).write_bytes(raw)
        (self.directory / (digest.replace(":", "_") + ".media")).write_text(media_type)
        return digest

    def read(self, content_hash: str, *, topic_id: str) -> bytes | None:
        path = self.directory / content_hash.replace(":", "_")
        return path.read_bytes() if path.is_file() else None

    def media_type(self, content_hash: str, *, topic_id: str) -> str | None:
        path = self.directory / (content_hash.replace(":", "_") + ".media")
        return path.read_text() if path.is_file() and self.read(content_hash, topic_id=topic_id) is not None else None

    def remove(self, content_hash: str) -> None:
        (self.directory / content_hash.replace(":", "_")).unlink()


def tables(path: Path) -> dict:
    conn = sqlite3.connect(path)
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {n: [list(r) for r in conn.execute(f"SELECT * FROM {n} ORDER BY rowid")] for n in names}
    finally:
        conn.close()


class World(rf.RouterTestCase):
    """The fixture builders, pointed at a durable store."""

    def __init__(self, directory: Path) -> None:
        super().__init__()
        self.directory = directory

    def setUp(self) -> None:  # not the in-memory setUp: a durable store and a file spool
        self.store = api.open_store(self.directory / "store.sqlite3", create=True)
        self.db = sqlite3.connect(self.directory / "store.sqlite3", isolation_level=None)
        self.db.executescript(store_fixtures.CONNECTION_TEXT)  # the fixture's raw writes run under the same contract
        self.spool = FileSpool(self.directory / "spool")
        self.spool.conn = None
        self.clock, self.ids, self.faults = rf.Clock(), rf.Ids(), {}
        self.router = self.make_router()
        for tid in (rf.TOPIC, rf.OTHER):
            self.x("INSERT INTO queue_entries (topic_id, fleet_id, priority, status, created_at, updated_at) VALUES (?, 'fleet-a', 1, 'awaiting_brief_confirmation', ?, ?)",
                   tid, "2026-09-27T09:00:00Z", "2026-09-27T09:00:00Z")

    def runTest(self) -> None:
        pass


def router_for(directory: Path, fault=None) -> service.Router:
    return service.Router(api.open_store(directory / "store.sqlite3"), FileSpool(directory / "spool"), clock=rf.Clock("2026-09-27T11:00:00Z"),
                          fault=fault)  # random ids: a fresh process must not re-mint the ids prepare used


def prepare(directory: Path) -> None:
    world = World(directory)
    world.setUp()
    world.to_queued()
    grant = world.started("inv_research01")
    text = world.artifact(b"claim text")
    outcome = rf.empty_outcome("inv_research01")
    outcome["next_queue_state"] = "queued"
    outcome["claims"] = [{"claim_id": "clm_00000001", "revision": 1, "text_ref": text, "load_bearing": False, "required_access_tier": None}]
    outcome["claim_promotions"] = [{"claim_id": "clm_00000001", "revision": 1}]
    outcome["review_triggers"] = [{"reason_code": "persistent_contradiction", "cause_ref": "c", "source_revision": 1, "observed_at": "2026-09-27T10:00:00Z"}]
    outcome["holds"] = [{"hold_id": "hold_000000000001", "subject_ref": "obligation:O-1", "hold_class": "judgment", "cause": "sources disagree",
                         "recoverability": "needs_decision", "required_authority": "primary", "owner": "primary", "deadline_at": "2026-10-01T00:00:00Z",
                         "clears_when": "adjudicated", "capability_fact_id": None}]
    env = world.envelope(grant, "op_final000001", outcome, refs=[text])
    world.ready(grant, env["payload_digest"])
    env["expected_state_revision"] = world.state_revision()
    world.store.close()
    world.db.close()
    (directory / "envelope.json").write_text(json.dumps(env))
    (directory / "before.json").write_text(json.dumps(tables(directory / "store.sqlite3")))


def main(argv: list[str]) -> int:
    directory, action = Path(argv[1]), argv[2]
    if action == "prepare":
        prepare(directory)
        return 0
    if action == "transition":
        print(json.dumps(router_for(directory).record_transition(json.loads(sys.stdin.read()))))
        return 0
    envelope = json.loads((directory / "envelope.json").read_text())
    if action == "crash":
        point = argv[3]

        def die(reached: str) -> None:
            if reached == point:
                os._exit(137)
        router_for(directory, die).commit_outcome(envelope)
        return 3  # the fault point was never reached
    response = router_for(directory).commit_outcome(envelope)
    print(json.dumps(response))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
