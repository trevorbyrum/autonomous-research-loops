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
LIVE = ("GEN2_MANIFEST", "GEN2_RETAINED_DIR")   # protected paths a live child reads (never secrets)
GATEWAY = {"commercial": False, "accept_per_item": False, "policy_version": 1}
LANES = ["semanticscholar"]

TOPIC = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
FAILURES = ((Refused, "refused"), (OSError, "io"), (ValueError, "malformed"), (KeyError, "malformed"))   # first match wins; a code per kind, never the text


class Walker:
    def __init__(self, make_driver: Callable[..., Driver]) -> None:
        self._make_driver = make_driver

    def walk(self, request: Mapping) -> dict:
        """{topic_id, live?} -> {status: ok, action: issue|advance|wait|stop|done, code?, command?}, or {status: refused, reason}. One tick.
        `live` is the operator's per-call permission to start live work: the exact boolean true, default off, never stored."""
        if (not isinstance(request, Mapping) or not {"topic_id"} <= set(request) <= {"topic_id", "live"} or not isinstance(request["topic_id"], str)
                or not TOPIC.match(request["topic_id"]) or type(request.get("live", False)) is not bool):
            return {"status": "refused", "reason": "request_invalid"}
        try:
            action = self._make_driver(request["topic_id"], live=request.get("live", False)).tick()
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


def driver_factory(station, composition: compose.Composition, environ: Mapping[str, str]) -> Callable[..., Driver]:
    """The driver for one topic, built per call from the opened station (the active bundle and the kits are read fresh each time)."""
    # Selection is pinned in each new discovery order; a later non-live tick does not revoke that job's network access.
    def make(topic_id: str, live: bool = False) -> Driver:
        bundle = station.router.status({})["config_bundles"]["active"]["bundle_hash"]
        kits = composition.kits(topic_id, lanes=LANES, gateway=GATEWAY, validate=validate)
        return Driver(station, topic_id=topic_id, bundle_hash=bundle, kits=kits, prompt_dir=Path(environ.get("GEN2_PROMPTS", PROMPTS)),
                      discovery_module="gen2.app.discovery" if live else "gen2.discovery.child",
                      discovery_env={k: environ[k] for k in DISCOVERY if k in environ}, live_env={k: environ[k] for k in LIVE if k in environ}, live=live, say=lambda line: None)
    return make
