"""The offline whole-workflow run's harness (2e2-min T18): a fresh store, the production station and composition, the real driver, and
the operator's steps through the CLI and authenticated listener between single walk ticks. Not collected as tests.

Everything the workflow does is production code over fixtures of the outside world: the executor children are real subprocesses
(`offline_child`, `offline_discovery`) running the production child, builders and discovery client with the canned judgments and the
canned gateway. Operator decisions use listener readbacks; raw SQL is only an independent read-only test oracle. Limits: it proves wiring and the record
families, not research quality, and it never calls a provider.
"""
from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import stat
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

from gen2.app import cli, compose, walk, workflow
from gen2.app.driver import Driver
from gen2.app.engine import Engine
from gen2.app.station import open_station
from gen2.core import canonical
from gen2.core.instants import utc_now
from gen2.exec.common import Refused
from gen2.router.boundary import work_id
from gen2.router.schemas import SchemaSet
from gen2.tests import children, offline_world, operator_fixtures as of
from gen2.tests.router_fixtures import TOPIC, RouterTestCase, ratings

PROMPTS = Path(children.path("gen2/prompts"))
GATEWAY_URL = "http://gateway.invalid:8765"
SCHEMAS = SchemaSet()


def validate(name, document):
    errors = SCHEMAS.errors(document, name + ".schema.json")
    if errors:
        raise Refused(f"{name}: {errors[0]}")


def prompt_pins():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pins", children.path("tools/gen2_prompt_pins.py"))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool.pins(PROMPTS, 1)


class Operator:
    """One operator script for either endpoint. Only the local fixture may answer scientific waits automatically."""

    def __init__(self, environ, *, live=False, sentinel=None):
        self.environ, self.live, self.sentinel = dict(environ), live, sentinel
        self.brief = RouterTestCase.brief_document(TOPIC)
        self.automatic = False   # dedicated stack: every scientific wait requires the present operator

    def cli(self, argv, body=None):
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(argv, environ=self.environ, stdin=io.StringIO(json.dumps(body)), stdout=out, stderr=err)
        if not out.getvalue():
            raise AssertionError(err.getvalue())
        return code, json.loads(out.getvalue())

    def command(self, name, body):
        code, reply = self.cli(["call", name], body)
        if code:
            raise AssertionError(reply)
        return reply

    # -- the operator's commands, through the CLI and authenticated listener ------------
    def decide(self, did: str, kind: str, subject: dict, payload=None, disposition: str = "approved") -> dict:
        out = self.command("apply_operator_decision", {"decision_id": did, "topic_id": TOPIC, "kind": kind, "disposition": disposition, "subject": {
            "kind": subject["kind"], "ref": subject.get("ref", TOPIC), "revision": subject.get("revision"), "hash": subject.get("hash")},
            "decided_at": utc_now(), "notes": None, "payload": payload})
        if out["status"] not in ("applied", "replayed"):
            raise AssertionError(out)
        return out

    def intake(self) -> None:
        for out in (self.command("create_topic", {"topic_id": TOPIC, "priority": 5}),
                    self.command("open_brief", {"document": self.brief, "owner_operator_id": "alice", "review_deadline": "2099-01-01T00:00:00Z"})):
            if out["status"] not in ("created", "recorded", "replayed"):
                raise AssertionError(out)

    def confirm_brief(self) -> None:
        self.decide("opd_brieft101", "brief_confirmation", {"kind": "intake_brief", "ref": "brief-1", "revision": 1, "hash": self.brief["content_hash"]})

    def approve_scope(self) -> None:
        report = self.topic()["scoping_report"]
        self.decide("opd_scopet101", "scope_approval", {"kind": "scoping_report", "ref": report["report_id"], "revision": report["version"], "hash": report["content_hash"]})

    def approve_contract(self) -> None:
        """The first topic's contract is hand-drafted (plan row 18): draft 1 unrated, the operator's ratings, draft 2 carrying them, its approval."""
        sentinel = self.sentinel
        if sentinel is None:
            raise AssertionError("contract approval needs an authorized staged sentinel reference")
        first, rated = offline_world.contract(1, None, rated=False, sentinel=sentinel), offline_world.contract(2, 1, sentinel=sentinel)
        assert self.command("draft_contract", {"document": first})["status"] == "recorded"
        self.decide("opd_rate0001", "rating_approval", {"kind": "contract_revision", "revision": 1, "hash": first["content_hash"]}, payload=ratings(rated))
        assert self.command("draft_contract", {"document": rated})["status"] == "recorded"
        self.decide("opd_cntrt102", "contract_approval", {"kind": "contract_revision", "revision": 2, "hash": rated["content_hash"]})

    def open_review(self) -> None:
        out = self.command("open_review", {"episode_id": "rev_offline0001", "topic_id": TOPIC, "kind": "fixed_cadence"})
        assert out["status"] in ("opened", "recorded", "replayed"), out

    def approve_completion(self) -> None:
        shown = self.topic()["review"]
        assert shown["approvable"], shown
        self.decide("opd_complete01", "completion_approval", {"kind": "dossier", "revision": shown["dossier"]["revision"], "hash": shown["dossier"]["content_hash"]})

    # -- reads ---------------------------------------------------------------------
    def topic(self) -> dict:
        code, reply = self.cli(["status", "--topic", TOPIC])
        assert code == 0, reply
        return reply["topics"][0]

    # -- the walk ------------------------------------------------------------------
    ANSWERS = (("brief_confirmation", "confirm_brief"), ("scope_approval", "approve_scope"), ("contract_approval", "approve_contract"),
               ("open_review", "open_review"), ("completion_approval", "approve_completion"))

    def tick(self):
        return self.command("walk", {"topic_id": TOPIC, "live": self.live})

    def walk(self, until: str = "done", max_ticks: int = 2000) -> str:
        """Repeated single ticks; only the fixture answers waits. Dedicated-stack use stops for explicit operator supervision."""
        self.intake()
        for _ in range(max_ticks):
            reply = self.tick()
            action = reply.get("action")
            if action == "done":
                return "done"
            if action == "stop" or reply["status"] == "stopped":
                return "stopped: " + reply["code"]
            if action == "wait":
                command = reply["command"]
                if until in command or not self.automatic:
                    return command
                step = next((method for kind, method in self.ANSWERS if kind in command), None)
                if step is None:
                    return command
                getattr(self, step)()
            else:
                time.sleep(0.05)
        raise AssertionError("walk exceeded its tick bound")


class Offline(Operator):
    """Local fixture endpoint: station built on the Engine owner thread, outside collaborators canned at the test boundary."""

    def __init__(self, counter: str = "empty", without_recorder: str | None = None, *, record=None, live: bool = False,
                 child_module: str = "gen2.tests.offline_child", invalid_judgment: bool = False) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        if invalid_judgment:
            (root / "station").mkdir()
            (root / "station" / "invalid-judgment").touch()
        token = root / "gateway-token"
        token.write_text("offline-token\n")
        # The driver's order command is `python3 -m <module> <dir>` run in the job's scratch with a bare environment: put a `python3` that
        # finds this checkout and its dependencies first on the PATH the supervisor passes on (the production image has gen2 installed).
        bin_dir = root / "bin"
        bin_dir.mkdir()
        wrapper = bin_dir / "python3"
        wrapper.write_text(f"#!/bin/sh\nPYTHONPATH={Path(children.path('gen2')).parent} exec {sys.executable} \"$@\"\n")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        self.path = mock.patch.dict(os.environ, {"PATH": f"{bin_dir}:{os.environ['PATH']}"})
        self.path.start()
        bundle = offline_world.bundle(workflow.executor_entries(prompt_pins()))
        self.composition = compose.Composition()
        authority = live_env = None
        if record is not None:   # a qualified authority from a record document, mounted the way the engine reads it (record, its pin, the manifest)
            document, manifest = record(root / "station")   # a callable: (the station root) -> (record document, manifest bytes)
            data = canonical.canonical_bytes(document)
            files = {"GEN2_QUALIFICATION_RECORD": data, "GEN2_MANIFEST": manifest}
            for name, content in files.items():
                (root / name).write_bytes(content)
            environ = {**{name: str(root / name) for name in files}, "GEN2_QUALIFICATION_PIN": canonical.bytes_digest(data)}
            authority = self.composition.authority(root / "station" / "jobs", environ)
            live_env = {"GEN2_MANIFEST": environ["GEN2_MANIFEST"], "GEN2_RETAINED_DIR": str(root)}
        def opener():
            station = open_station(root / "station", station_id="stn-offline", host_id="host-offline", clock=utc_now, config_bundle=bundle, create=True,
                                    router_options={"gateway_captures": self.composition.captures, "dispatch_authority": authority},
                                    supervisor_options={"recorders": {k: v for k, v in self.composition.recorders().items() if k != without_recorder},
                                                        "dispatch": authority})
            self.composition.bind(station)
            # Test-boundary operand setup only. The dedicated endpoint has no staging privilege (change 9 awaits a ruling).
            self.sentinel = station.spool.stage(TOPIC, canonical.canonical_bytes([work_id("doi", "10.1/offline-a")]), "application/json")
            return station

        def make_driver(topic_id, live=False):
            station = self.composition.station
            bundle_hash = station.router.status({})["config_bundles"]["active"]["bundle_hash"]
            kits = self.composition.kits(topic_id, lanes=["semanticscholar", "crossref"], validate=validate,
                                         gateway={"commercial": False, "accept_per_item": True, "policy_version": "gw/1"})
            return Driver(station, topic_id=topic_id, bundle_hash=bundle_hash, kits=kits, prompt_dir=PROMPTS,
                             child_module=child_module, live=live, live_env=live_env, discovery_module="gen2.tests.offline_discovery",
                             discovery_env={"GEN2_GATEWAY_URL": GATEWAY_URL, "GEN2_SECRET_GATEWAY_TOKEN_FILE": str(token), "GEN2_OFFLINE_COUNTER": counter},
                             say=lambda line: None)
        self.logs = []
        self.engine = Engine(opener, of.credentials(), log=self.logs.append, walker=lambda station: walk.Walker(make_driver))
        host, port = self.engine.address
        super().__init__({"GEN2_OPERATOR_URL": f"http://{host}:{port}", "GEN2_OPERATOR_TOKEN": of.OPERATOR_TOKEN}, live=live, sentinel=self.sentinel)
        self.automatic = True

    def close(self) -> None:
        self.engine.close()
        self.path.stop()
        self.tmp.cleanup()

    def records(self, family: str):
        """Independent read-only test oracle; operator decisions never call this reader."""
        with sqlite3.connect(f"file:{Path(self.tmp.name) / 'station' / 'store.sqlite3'}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            sql = db.execute("SELECT sql FROM sqlite_schema WHERE name = ?", (family,)).fetchone()[0]
            json_columns = re.findall(r"json_valid\((\w+)\)", sql)
            # This fresh fixture contains one topic; some evidence tables bind it through foreign keys rather than topic_id.
            return [{k: json.loads(v) if k in json_columns and v is not None else v for k, v in dict(row).items()}
                    for row in db.execute('SELECT * FROM "' + family.replace('"', '""') + '"')]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", choices=("fixture", "dedicated"), required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    run = Offline(live=args.live) if args.endpoint == "fixture" else Operator(os.environ, live=args.live)
    try:
        print(run.walk())   # dedicated never answers a scientific wait automatically
    finally:
        if args.endpoint == "fixture":
            run.close()
