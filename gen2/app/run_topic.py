"""The command line that walks one topic: open the station, wire the kits and recorders, run the driver, print what it says.

Trace: 2e2-min design O17.4; the T17 brief (the driver only wires and prints; no scientific decision, alternate runner, retry or blocker
clearing here). Oracle: the driver's own printed line. Limits: the station opens from the bundle the router has active (a station with
none refuses to start, station.StationRefused); the discovery gateway's token is given as a file path and never read here.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Sequence

from gen2.app import compose
from gen2.app.driver import Driver
from gen2.app.station import StationRefused, open_station
from gen2.core.instants import utc_now
from gen2.exec.common import Refused
from gen2.router.schemas import SchemaSet

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def schema_validator(schemas: SchemaSet | None = None) -> Callable[[str, object], None]:
    schemas = schemas or SchemaSet()

    def validate(name: str, document: object) -> None:
        errors = schemas.errors(document, name)
        if errors:
            raise Refused(f"{name}: {errors[0]}")
    return validate


def main(argv: Sequence[str], *, opener=open_station, say: Callable[[str], None] = print) -> int:
    parser = argparse.ArgumentParser(prog="gen2.app.run_topic", description=__doc__.splitlines()[0])
    parser.add_argument("root", type=Path)
    parser.add_argument("topic")
    parser.add_argument("--station-id", default="station-1")
    parser.add_argument("--host-id", default="host-1")
    parser.add_argument("--prompts", type=Path, default=PROMPTS)
    parser.add_argument("--lane", action="append", default=None)
    parser.add_argument("--policy-version", type=int, default=1)
    parser.add_argument("--gateway-url")
    parser.add_argument("--gateway-token-file")
    args = parser.parse_args(list(argv))
    composition = compose.Composition(args.topic)
    try:
        station = opener(args.root, station_id=args.station_id, host_id=args.host_id, clock=utc_now,
                         router_options={"gateway_captures": composition.captures}, supervisor_options={"recorders": composition.recorders()})
    except StationRefused as error:
        say(f"the station did not start: {error}")
        return 2
    try:
        composition.bind(station)
        bundle = station.router.status({})["config_bundles"]["active"]["bundle_hash"]
        env = {k: v for k, v in (("GEN2_GATEWAY_URL", args.gateway_url), ("GEN2_SECRET_GATEWAY_TOKEN_FILE", args.gateway_token_file)) if v}
        kits = composition.kits(lanes=args.lane or ["semanticscholar"], validate=schema_validator(),
                                gateway={"commercial": False, "accept_per_item": False, "policy_version": args.policy_version})
        text = Driver(station, topic_id=args.topic, bundle_hash=bundle, kits=kits, prompt_dir=args.prompts, discovery_env=env, say=say).run()
        return 0 if text == "done" or text.startswith("waiting for") else 3
    finally:
        station.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
