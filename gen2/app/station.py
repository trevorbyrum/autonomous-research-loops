"""Composition root for one station (task 1c): the router over its store, the
protected spool the router reads staged bytes from, and the supervisor that
reaches the router only through the ControlBackend protocol.

Trace: gen2/boundaries.toml modules.app ("constructs the router (which owns
its store) and hands the core ControlBackend protocol to supervisor ... so
router and supervisor never import each other. No domain logic");
gen2/core/control.py; DEPLOYMENT-CONTRACT.md §2 (the mounted configuration is
activated as a versioned bundle; the engine does not start on an invalid
one); INVARIANTS G-10, RG-9 (task 1d).

The router is handed to the supervisor as the protocol object, in process.
Until task 1e there is no transport: `control` lets a caller put one in
between (the tests use it to make the router unreachable, C-10).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from gen2.router.service import Router
from gen2.supervisor.spool import Spool
from gen2.supervisor.supervisor import Policy, Supervisor, supervisor_policy


class StationRefused(RuntimeError):
    """The mounted config bundle was refused: the station does not start, and
    the router keeps the bundle that was active (with a dated fact)."""


@dataclass
class Station:
    router: Router
    spool: Spool
    supervisor: Supervisor

    def close(self) -> None:
        self.router.close()


def open_station(root: str | Path, *, station_id: str, host_id: str, clock: Callable[[], str], container_id: str | None = None,
                 config_bundle: Mapping | None = None, fixture_policy: Policy | None = None, control: Callable[[Router], object] = lambda router: router,
                 create: bool = False, router_options: dict | None = None, supervisor_options: dict | None = None) -> Station:
    """<root>/store.sqlite3, <root>/spool and <root>/jobs, wired together.

    Every start — a first one, a restart, a replacement — takes the
    supervisor's policies from recorded config bundles (G-10, RG-9;
    DEPLOYMENT-CONTRACT.md §2: restart preserves configuration pins): each
    job's from the bundle its order pins, the one it was admitted under,
    whatever is active now; the station's own from `config_bundle`, the
    mounted config-bundle/1 document, which the router activates first (a
    replay if it is already the active one), or, with none mounted, from the
    bundle the router has active (the persisted configuration). With none
    mounted and none recorded active the station does not start
    (StationRefused): there is no unpinned fallback policy.

    `fixture_policy` is a test fixture outside that guarantee: every job runs
    under it, whatever bundle it pins. It cannot be combined with a mounted
    bundle."""
    root = Path(root)
    spool = Spool(root / "spool")
    router = Router.open(root / "store.sqlite3", spool, create=create, clock=clock, **(router_options or {}))
    if fixture_policy is not None:
        if config_bundle is not None:
            router.close()
            raise ValueError("with a config bundle, the supervisor's policy is the bundle's")
        supervisor = Supervisor(control(router), spool, root / "jobs", station_id=station_id, host_id=host_id, container_id=container_id,
                                policy=fixture_policy, policies=None, clock=clock, **(supervisor_options or {}))
        return Station(router, spool, supervisor)
    if config_bundle is not None:
        activated = router.activate_config_bundle(config_bundle)
        if activated["status"] not in ("activated", "replayed"):
            router.close()
            raise StationRefused(f"the config bundle was refused ({activated['reason']}): {activated['detail']}")
        own = activated["bundle_hash"]
    else:
        own = router.active_config_bundle()
        if own is None:
            router.close()
            raise StationRefused("no config bundle is mounted and none is recorded active: the station has no policy to start under")

    def policies(bundle_hash: str) -> Policy:
        bundle = router.config_bundle(bundle_hash)
        if bundle is None:
            raise KeyError(f"config bundle {bundle_hash} is not recorded")
        return supervisor_policy(bundle)
    supervisor = Supervisor(control(router), spool, root / "jobs", station_id=station_id, host_id=host_id, container_id=container_id,
                            policy=policies(own), policies=policies, clock=clock, **(supervisor_options or {}))
    return Station(router, spool, supervisor)
