"""A child process for test_supervisor_crash.py (not collected as tests).

  python -m gen2.tests.supervisor_child <root> <invocation id> <crash point> <clock start>
      open the station on <root> through the composition root
      (gen2/app/station.py: the store, the spool, the jobs directory), and
      advance the job of <invocation id> — its order is already stored under
      its handle — until it settles, with a fault hook that ends this process
      with os._exit(137) at <crash point>: no exception, no cleanup, nothing
      written after that point. Exit 3 if the point is never reached.

The router ids are random (a fresh process must not re-mint the ids the test
process used); the clock starts at <clock start> and advances a millisecond
per reading, as the test's does.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from gen2.app.station import open_station
from gen2.tests import router_fixtures as rf
from gen2.tests.supervisor_fixtures import FAST, launcher


def main(argv: list[str]) -> int:
    root, invocation_id, point, start = Path(argv[1]), argv[2], argv[3], argv[4]

    def die(reached: str) -> None:
        if reached == point:
            os._exit(137)
    station = open_station(root, station_id="station-1", host_id="host-test", clock=rf.Clock(start), policy=FAST,
                           supervisor_options={"launcher": launcher(), "fault": die})
    print(station.supervisor.run(invocation_id, timeout_s=60))
    return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
