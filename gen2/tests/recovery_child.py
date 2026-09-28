"""A child process for test_operator_recovery.py's ReplacedRecoveryTest (not
collected as tests).

  python -m gen2.tests.recovery_child <root> <crash point> <clock start>
      serve the engine (gen2/app/engine.py) over <root> — its station opened
      through the composition root (gen2/app/station.py) under the fixture
      policy and launcher, the principals from the deployment contract's
      environment names, listening on GEN2_OPERATOR_LISTEN — with a fault
      hook that ends this process with os._exit(137) at <crash point>: no
      exception, no reply, no cleanup, nothing written after that point.
      Prints `listening on HOST:PORT` once serving, as the engine does.

The router ids are random (a fresh process must not re-mint the ids the test
process used); the clock starts at <clock start> and advances a millisecond
per reading, as the test's does.
"""
from __future__ import annotations

import os
import sys
import threading

from gen2.app.engine import Engine
from gen2.app.station import open_station
from gen2.operator.auth import Credentials
from gen2.tests import router_fixtures as rf
from gen2.tests.supervisor_fixtures import FAST, launcher


def main(argv: list[str]) -> int:
    root, point, start = argv[1], argv[2], argv[3]

    def die(reached: str) -> None:
        if reached == point:
            os._exit(137)
    host, _, port = os.environ["GEN2_OPERATOR_LISTEN"].rpartition(":")
    engine = Engine(lambda: open_station(root, station_id="station-1", host_id="host-1", clock=rf.Clock(start), fixture_policy=FAST,
                                         supervisor_options={"launcher": launcher(), "fault": die}),
                    Credentials.from_environ(os.environ), listen=(host, int(port)))
    print(f"listening on {engine.address[0]}:{engine.address[1]}", flush=True)
    threading.Event().wait(120)
    engine.close()
    return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
