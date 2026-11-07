"""The command that walks one topic: open the station, wire the kits and recorders, run the driver until a wait or a stop, print it.

Trace: 2e2-min design O17.4; the T17 brief (the driver only wires and prints: no scientific decision, alternate runner, retry or
blocker clearing). Oracle: the driver's own printed line. Limits: the station opens from the bundle the router has active (none
refuses to start); no options. The discovery gateway's URL and token FILE come from the environment (GEN2_GATEWAY_URL,
GEN2_SECRET_GATEWAY_TOKEN_FILE), the token itself never; the station ids from GEN2_STATION_ID and GEN2_HOST_ID.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence

from gen2.app import compose
from gen2.app.driver import Driver
from gen2.app.station import StationRefused, open_station
from gen2.core.instants import utc_now
from gen2.exec.common import Refused
from gen2.router.schemas import SchemaSet

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
DISCOVERY = ("GEN2_GATEWAY_URL", "GEN2_SECRET_GATEWAY_TOKEN_FILE")


def validate(name: str, document: object) -> None:
    """The discovery intake's validator: it names a schema by its bare name (`search-proposal`); the schema set knows filenames."""
    errors = SchemaSet().errors(document, f"{name}.schema.json")
    if errors:
        raise Refused(f"{name}: {errors[0]}")


def main(argv: Sequence[str], *, environ: Mapping[str, str] = os.environ, opener=open_station, say: Callable[[str], None] = print) -> int:
    """`python -m gen2.app.run_topic <root> <topic>`: 0 at a wait or done, 2 if the station will not start, 3 if the walk stopped."""
    if len(argv) != 2:
        say("usage: gen2.app.run_topic <root> <topic>")
        return 2
    root, topic = argv
    composition = compose.Composition(topic)
    try:
        station = opener(Path(root), station_id=environ.get("GEN2_STATION_ID", "station-1"), host_id=environ.get("GEN2_HOST_ID", "host-1"), clock=utc_now,
                         router_options={"gateway_captures": composition.captures}, supervisor_options={"recorders": composition.recorders()})
    except StationRefused as error:
        say(f"the station did not start: {error}")
        return 2
    try:
        return _walk(station, composition, topic, environ, say)
    except (Refused, OSError, ValueError, KeyError) as error:   # a refusal or a failed read stops the walk with its reason, not a traceback
        say(f"stopped: {type(error).__name__}: {error}")
        return 3
    finally:
        station.close()


def _walk(station, composition, topic, environ, say) -> int:
    composition.bind(station)
    kits = composition.kits(lanes=["semanticscholar"], validate=validate, gateway={"commercial": False, "accept_per_item": False, "policy_version": 1})
    bundle = station.router.status({})["config_bundles"]["active"]["bundle_hash"]
    text = Driver(station, topic_id=topic, bundle_hash=bundle, kits=kits, prompt_dir=PROMPTS,
                  discovery_env={k: environ[k] for k in DISCOVERY if k in environ}, say=say).run()
    return 0 if text == "done" or text.startswith("waiting for") else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
