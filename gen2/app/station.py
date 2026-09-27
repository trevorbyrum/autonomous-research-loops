"""Composition root for one station (task 1c): the router over its store, the
protected spool the router reads staged bytes from, and the supervisor that
reaches the router only through the ControlBackend protocol.

Trace: gen2/boundaries.toml modules.app ("constructs the router (which owns
its store) and hands the core ControlBackend protocol to supervisor ... so
router and supervisor never import each other. No domain logic");
gen2/core/control.py.

The router is handed to the supervisor as the protocol object, in process.
Until task 1e there is no transport: `control` lets a caller put one in
between (the tests use it to make the router unreachable, C-10).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gen2.router.service import Router
from gen2.supervisor.spool import Spool
from gen2.supervisor.supervisor import Policy, Supervisor


@dataclass
class Station:
    router: Router
    spool: Spool
    supervisor: Supervisor

    def close(self) -> None:
        self.router.close()


def open_station(root: str | Path, *, station_id: str, host_id: str, clock: Callable[[], str], container_id: str | None = None,
                 policy: Policy = Policy(), control: Callable[[Router], object] = lambda router: router, create: bool = False,
                 router_options: dict | None = None, supervisor_options: dict | None = None) -> Station:
    """<root>/store.sqlite3, <root>/spool and <root>/jobs, wired together."""
    root = Path(root)
    spool = Spool(root / "spool")
    router = Router.open(root / "store.sqlite3", spool, create=create, clock=clock, **(router_options or {}))
    supervisor = Supervisor(control(router), spool, root / "jobs", station_id=station_id, host_id=host_id, container_id=container_id,
                            policy=policy, clock=clock, **(supervisor_options or {}))
    return Station(router, spool, supervisor)
