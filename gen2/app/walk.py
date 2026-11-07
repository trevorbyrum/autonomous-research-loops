"""The hosted walk: one driver tick for one topic, run on the engine's owner thread, answered in fixed words.

Trace: process map v1 gap 3; Astra live-hosting design review (accepted shape: one station, one owner thread, one tick per call, the
operator's client loop; no ticker, no global recovery, no per-topic cache); INVARIANTS C-1 (one writer: a second station over the same
store is excluded), DEBT-055 (supervised only: nothing advances unless the operator calls). Oracle: `Driver.tick`'s own action. Limits:
the reply is a closed set of words (`action`, `code`) and never carries ids, hold text, exception text or request values; the
completion hand-off is the reviewed status block, which the client reads from status. The driver is built per call for the validated
topic, so nothing goes stale between calls; a refused or failing tick says so and is never repeated by the server.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Mapping

from gen2.app import compose, workflow
from gen2.app.driver import Driver
from gen2.exec.common import Refused
from gen2.router.schemas import SchemaSet

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
DISCOVERY = ("GEN2_GATEWAY_URL", "GEN2_SECRET_GATEWAY_TOKEN_FILE")   # the gateway's URL and its token FILE; the token itself is never read here
GATEWAY = {"commercial": False, "accept_per_item": False, "policy_version": 1}
LANES = ["semanticscholar"]

TOPIC = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
FAILURES = ((Refused, "refused"), (OSError, "io"), (ValueError, "malformed"), (KeyError, "malformed"))   # first match wins; a code per kind, never the text


class Walker:
    def __init__(self, make_driver: Callable[[str], Driver]) -> None:
        self._make_driver = make_driver

    def walk(self, request: Mapping) -> dict:
        """{topic_id} -> {status: ok, action: issue|advance|wait|stop|done, code?, command?}, or {status: refused, reason}. One tick."""
        if not isinstance(request, Mapping) or set(request) != {"topic_id"} or not isinstance(request["topic_id"], str) or not TOPIC.match(request["topic_id"]):
            return {"status": "refused", "reason": "request_invalid"}
        try:
            action = self._make_driver(request["topic_id"]).tick()
        except tuple(kind for kind, _ in FAILURES) as error:
            return {"status": "stopped", "code": next(word for kind, word in FAILURES if isinstance(error, kind))}
        if isinstance(action, workflow.Wait):
            return {"status": "ok", "action": "wait", "command": action.command}
        if isinstance(action, workflow.Stop):
            return {"status": "ok", "action": "stop", "code": action.code}
        return {"status": "ok", "action": type(action).__name__.lower()}


def validate(name: str, document: object) -> None:
    """The discovery intake's validator: it names a schema by its bare name; the schema set knows filenames."""
    errors = SchemaSet().errors(document, f"{name}.schema.json")
    if errors:
        raise Refused(f"{name}: {errors[0]}")


def driver_factory(station, composition: compose.Composition, environ: Mapping[str, str]) -> Callable[[str], Driver]:
    """The driver for one topic, built per call from the opened station (the active bundle and the kits are read fresh each time)."""
    def make(topic_id: str) -> Driver:
        bundle = station.router.status({})["config_bundles"]["active"]["bundle_hash"]
        kits = composition.kits(topic_id, lanes=LANES, gateway=GATEWAY, validate=validate)
        return Driver(station, topic_id=topic_id, bundle_hash=bundle, kits=kits, prompt_dir=Path(environ.get("GEN2_PROMPTS", PROMPTS)),
                      discovery_env={k: environ[k] for k in DISCOVERY if k in environ}, say=lambda line: None)
    return make
