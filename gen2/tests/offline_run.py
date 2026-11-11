"""The offline whole-workflow run's harness (2e2-min T18): a fresh store, the production station and composition, the real driver, and
the operator's steps between its waits, each through a production route. Not collected as tests.

Everything the workflow does is production code over fixtures of the outside world: the executor children are real subprocesses
(`offline_child`, `offline_discovery`) running the production child, builders and discovery client with the canned judgments and the
canned gateway. Nothing is written to the store except through the router's own commands. Limits: it proves wiring and the record
families, not research quality, and it never calls a provider.
"""
from __future__ import annotations

import os
import stat
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

from gen2.app import compose, workflow
from gen2.app.driver import Driver
from gen2.app.station import open_station
from gen2.core import canonical
from gen2.core.instants import utc_now
from gen2.exec.common import Refused
from gen2.router.boundary import work_id
from gen2.router.schemas import SchemaSet
from gen2.tests import children, offline_world
from gen2.tests.router_fixtures import TOPIC, RouterTestCase, contract, ratings

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


class Offline:
    """One fresh station, composition and driver over a temporary root; `operator` is the human, each method one production command."""

    def __init__(self, counter: str = "empty", without_recorder: str | None = None, *, record=None, live: bool = False,
                 child_module: str = "gen2.tests.offline_child") -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
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
        self.station = open_station(root / "station", station_id="stn-offline", host_id="host-offline", clock=utc_now, config_bundle=bundle, create=True,
                                    router_options={"gateway_captures": self.composition.captures, "dispatch_authority": authority},
                                    supervisor_options={"recorders": {k: v for k, v in self.composition.recorders().items() if k != without_recorder},
                                                        "dispatch": authority})
        self.composition.bind(self.station)
        self.router = self.station.router
        self.bundle_hash = self.router.status({})["config_bundles"]["active"]["bundle_hash"]
        self.said: list[str] = []
        kits = self.composition.kits(TOPIC, lanes=["semanticscholar", "crossref"], validate=validate,
                                     gateway={"commercial": False, "accept_per_item": True, "policy_version": "gw/1"})
        self.driver = Driver(self.station, topic_id=TOPIC, bundle_hash=self.bundle_hash, kits=kits, prompt_dir=PROMPTS,
                             child_module=child_module, live=live, live_env=live_env, discovery_module="gen2.tests.offline_discovery",
                             discovery_env={"GEN2_GATEWAY_URL": GATEWAY_URL, "GEN2_SECRET_GATEWAY_TOKEN_FILE": str(token), "GEN2_OFFLINE_COUNTER": counter},
                             say=self.said.append, sleep=lambda seconds: time.sleep(0.05))
        self.brief = RouterTestCase.brief_document(TOPIC)

    def close(self) -> None:
        self.station.close()
        self.path.stop()
        self.tmp.cleanup()

    # -- the operator's commands, through the router ----------------------------------
    def decide(self, did: str, kind: str, subject: dict, payload=None, disposition: str = "approved") -> dict:
        out = self.router.apply_operator_decision({"decision_id": did, "topic_id": TOPIC, "kind": kind, "disposition": disposition, "subject": {
            "kind": subject["kind"], "ref": subject.get("ref", TOPIC), "revision": subject.get("revision"), "hash": subject.get("hash")},
            "operator_id": "user", "decided_at": utc_now(), "notes": None, "payload": payload})
        if out["status"] not in ("applied", "replayed"):
            raise AssertionError(out)
        return out

    def intake(self) -> None:
        for out in (self.router.create_topic({"topic_id": TOPIC, "priority": 5}),
                    self.router.open_brief({"document": self.brief, "owner_operator_id": "user", "review_deadline": "2099-01-01T00:00:00Z"})):
            if out["status"] not in ("created", "recorded", "replayed"):
                raise AssertionError(out)

    def confirm_brief(self) -> None:
        self.decide("opd_brieft101", "brief_confirmation", {"kind": "intake_brief", "ref": "brief-1", "revision": 1, "hash": self.brief["content_hash"]})

    def approve_scope(self) -> None:
        report = max(self.records("scoping_reports"), key=lambda r: r["version"])
        self.decide("opd_scopet101", "scope_approval", {"kind": "scoping_report", "ref": report["report_id"], "revision": report["version"], "hash": report["content_hash"]})

    def approve_contract(self) -> None:
        """The first topic's contract is hand-drafted (plan row 18): draft 1 unrated, the operator's ratings, draft 2 carrying them, its approval."""
        sentinel = self.station.spool.stage(TOPIC, canonical.canonical_bytes([work_id("doi", "10.1/offline-a")]), "application/json")   # the operator's known item
        first, rated = offline_world.contract(1, None, rated=False, sentinel=sentinel), offline_world.contract(2, 1, sentinel=sentinel)
        for doc in (first,):
            assert self.router.draft_contract({"document": doc})["status"] == "recorded"
        self.decide("opd_rate0001", "rating_approval", {"kind": "contract_revision", "revision": 1, "hash": first["content_hash"]}, payload=ratings(rated))
        assert self.router.draft_contract({"document": rated})["status"] == "recorded"
        self.decide("opd_cntrt102", "contract_approval", {"kind": "contract_revision", "revision": 2, "hash": rated["content_hash"]})

    def open_review(self) -> None:
        out = self.router.open_review({"episode_id": "rev_offline0001", "topic_id": TOPIC, "kind": "fixed_cadence"})
        assert out["status"] in ("opened", "recorded", "replayed"), out

    def approve_completion(self) -> None:
        shown = self.router.status({"topic_id": TOPIC})["topics"][0]["review"]
        self.decide("opd_complete01", "completion_approval", {"kind": "dossier", "revision": shown["dossier"]["revision"], "hash": shown["dossier"]["content_hash"]})

    # -- reads ---------------------------------------------------------------------
    def records(self, *families: str):
        got = self.router.topic_records({"topic_id": TOPIC, "families": list(families)})["records"]
        return got[families[0]] if len(families) == 1 else got

    def topic(self) -> dict:
        return self.router.status({"topic_id": TOPIC})["topics"][0]

    # -- the walk ------------------------------------------------------------------
    ANSWERS = (("brief_confirmation", "confirm_brief"), ("scope_approval", "approve_scope"), ("contract_approval", "approve_contract"),
               ("open_review", "open_review"), ("completion_approval", "approve_completion"))

    def walk(self, until: str = "done", max_waits: int = 12) -> str:
        """Run the driver; at each wait do the operator's step it names; stop at `until` (the kind of wait or "done") or on a stop."""
        self.intake()
        for _ in range(max_waits):
            text = self.driver.run(max_ticks=400)
            if text == "done" or text.startswith("stopped") or until in text:
                return text
            step = next((method for kind, method in self.ANSWERS if kind in text), None)
            if step is None:
                return text
            getattr(self, step)()
        return text
