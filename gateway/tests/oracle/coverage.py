"""An executable coverage registry (task 2b-repair-10a, R9-5).

R9-5: the harness's coverage credited `bis.catalog`, which no test ever executed, because it counted the operations a list NAMED. Here an operation is
covered only if it ran: `Recorder` wraps the two points every operation passes through,

  * `Client.get` / `Client.post` / `Client.local` (an adapter reaching its provider, or the local index), recording which source it reached, and
  * `router.execute` (a request going through the real router), recording the request's kind and selector and the sources reached while it ran,

and `covered()` is computed from those records alone: an operation is `(source, request type, selector)`, and it is covered if some request of that kind
and selector went through the router and the source's lane reached its provider (or the local index) while it did. Nothing asserts a list.

`UNIVERSE` is what exists: every (source, capability) of the registry seed (read at run time, so a new capability appears here by itself) and the
sub-operations the documents name (PLAN.md D-31/D-32: BEA's dataset, parameter and value browses, FRED's search and one series, BLS's surveys and
popular series, Census's directory and variables, BIS and ECB's flows and their dimensions; FRED and BEA's two kinds of data request; each enrichment
kind). `EXCLUDED` lists, with a reason, every operation this oracle does not execute: dimension browsing (deferred by D-32), the local index
(it needs PostgreSQL), and operations that no case drives. An excluded operation that DID execute is a stale exclusion, and the registry fails on it.
"""
from __future__ import annotations

import collections
import functools
import threading
from dataclasses import dataclass, field

from research_gateway.adapters import base
from research_gateway.core import router as R
from research_gateway.registry.load import read_seed


def selector(request: dict) -> str:
    """The sub-operation a request names, from its fields alone."""
    kind = request.get("request_type")
    if kind == "enrich":
        return str(request.get("what") or "")
    if kind == "catalog":
        within = request.get("within")
        if within:
            if request.get("source") == "census":            # a Census dataset is named by a path (`2022/acs/acs1`): one level, not three
                return "within:1"
            return f"within:{str(within).count('/') + 1}"
        return "search" if request.get("query") else "top"
    if kind == "data":
        params = request.get("params") or {}
        if request.get("source") == "bea":
            return "dataset-list" if str(params.get("method", "")).upper() == "GETDATASETLIST" else "get-data"
    return ""


@dataclass
class Execution:
    request_type: str
    selector: str
    reached: frozenset                      # the sources whose adapters reached their provider (or the local index) while this request ran
    lanes: dict = field(default_factory=dict)   # source -> (coverage, completeness, has a count, error_class) of the lane the answer gave it: what the execution ENDED as
    raised: bool = False


@dataclass
class Recorder:
    executions: list = field(default_factory=list)
    reached: collections.Counter = field(default_factory=collections.Counter)    # (source, request type as the adapter named it) -> served calls
    loaders: collections.Counter = field(default_factory=collections.Counter)    # loader name -> records yielded
    _current: list | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _originals: dict = field(default_factory=dict)

    # -- recording
    def _reach(self, source_id: str, request_type: str) -> None:
        with self._lock:
            self.reached[(source_id, request_type)] += 1
            if self._current is not None:
                self._current.append(source_id)

    def install(self) -> "Recorder":
        if self._originals:
            return self
        rec = self
        for name in ("get", "post"):
            original = getattr(base.Client, name)
            self._originals[("Client", name)] = original

            def make(original):
                @functools.wraps(original)
                def wrapper(client, source_id, request_type, *args, **kwargs):
                    out = original(client, source_id, request_type, *args, **kwargs)     # an answer came back: raised errors are not "served"
                    rec._reach(source_id, request_type)
                    return out
                return wrapper
            setattr(base.Client, name, make(original))
        local = base.Client.local
        self._originals[("Client", "local")] = local

        @functools.wraps(local)
        def local_wrapper(client, source_id, request_type, *args, **kwargs):
            out = local(client, source_id, request_type, *args, **kwargs)
            rec._reach(source_id, request_type)
            return out
        base.Client.local = local_wrapper

        execute = R.execute
        self._originals[("router", "execute")] = execute

        @functools.wraps(execute)
        def execute_wrapper(router, request, *args, **kwargs):
            with rec._lock:
                outer, rec._current = rec._current, []
            out, raised = None, True
            try:
                out = execute(router, request, *args, **kwargs)
                raised = False
                return out
            finally:
                with rec._lock:
                    reached, rec._current = rec._current, outer
                lanes = {}
                for lane in (out.get("lanes") or []) if isinstance(out, dict) else []:
                    lanes[lane.get("source")] = (lane.get("coverage"), lane.get("completeness"), "count" in lane, lane.get("error_class"))
                rec.executions.append(Execution(str(request.get("request_type")), selector(request), frozenset(reached), lanes, raised))
        R.execute = execute_wrapper
        return self

    def watch_loader(self, module, name: str) -> None:
        """Count the records a registry loader yields (they are generators: one that is never iterated has not run)."""
        original = getattr(module, name)
        self._originals[(module.__name__, name)] = original
        rec = self

        @functools.wraps(original)
        def wrapper(*args, **kwargs):
            for item in original(*args, **kwargs):
                rec.loaders[name] += 1
                yield item
        setattr(module, name, wrapper)

    def watch_function(self, module, name: str) -> None:
        original = getattr(module, name)
        self._originals[(module.__name__, name)] = original
        rec = self

        @functools.wraps(original)
        def wrapper(*args, **kwargs):
            out = original(*args, **kwargs)
            if out is not None:
                rec.loaders[name] += 1
            return out
        setattr(module, name, wrapper)

    def uninstall(self) -> None:
        import sys
        for (owner, name), original in self._originals.items():
            if owner == "Client":
                setattr(base.Client, name, original)
            elif owner == "router":
                setattr(R, name, original)
            else:
                setattr(sys.modules[owner], name, original)
        self._originals.clear()

    # -- what ran
    def covered(self, source_id: str, request_type: str, sel: str = "") -> int:
        return sum(1 for e in self.executions if e.request_type == request_type and e.selector == sel and source_id in e.reached)


# ------------------------------------------------------------------ what exists
def seed_operations() -> set:
    """(source, capability) for every source of the registry seed: read at run time, so a capability added tomorrow is a row here tomorrow."""
    return {(s["id"], cap) for s in read_seed() for cap in (s.get("capabilities") or [])}


# sub-operations the documents name beyond the seed's (source, capability) pairs: (source, request type, selector)
SUB_OPERATIONS = (
    ("crossref", "enrich", "references"),
    ("semanticscholar", "enrich", "citations"), ("semanticscholar", "enrich", "references"),
    ("opencitations", "enrich", "citations"), ("opencitations", "enrich", "references"), ("opencitations", "enrich", "metadata"),
    ("unpaywall", "enrich", "oa_location"), ("core", "enrich", "full_text"),
    ("fred", "catalog", "search"), ("fred", "catalog", "within:1"),
    ("bea", "data", "get-data"), ("bea", "data", "dataset-list"),
    ("bea", "catalog", "top"), ("bea", "catalog", "within:1"), ("bea", "catalog", "within:2"),
    ("bls", "catalog", "top"), ("bls", "catalog", "within:1"),
    ("census", "catalog", "top"), ("census", "catalog", "within:1"),
    ("bis", "catalog", "top"), ("bis", "catalog", "within:1"), ("bis", "catalog", "within:2"),
    ("ecb", "catalog", "top"), ("ecb", "catalog", "within:1"), ("ecb", "catalog", "within:2"),
)
# A (source, capability) pair with sub-operations above is those sub-operations; every other pair is one operation with no selector.

# what no case in this oracle executes, and why: (source, request type, selector) -> reason. Each is reported; none is credited.
EXCLUDED = {
    ("bis", "catalog", "within:2"): "dimension browsing (the codes of one dimension): per-dimension codelists are deferred (PLAN.md D-32), so the operation does not exist yet",
    ("ecb", "catalog", "within:2"): "dimension browsing (the codes of one dimension): per-dimension codelists are deferred (PLAN.md D-32), so the operation does not exist yet",
    ("openalex_snapshot", "find", ""): "the local index is a PostgreSQL full-text lookup; this oracle runs without a database (make gen2-gateway step 2 runs the DB-backed suite)",
    ("harvard_dataverse", "resolve", ""): "no oracle case drives it: the resolve harness has no Dataverse operation (a disclosed gap, not a pass)",
    ("qdr", "find", ""): "QDR is a Dataverse installation and shares Harvard Dataverse's implementation (PROVIDER-PAGINATION.md); no separate case drives it",
    ("qdr", "resolve", ""): "QDR is a Dataverse installation and shares Harvard Dataverse's implementation (PROVIDER-PAGINATION.md); no separate case drives it",
    ("core", "resolve", ""): "reachable only as a substitute for a failed resolver (PLAN.md R-1); no oracle case forces the fallback",
    ("wms", "fetch", ""): "Harvard Dataverse-backed static files (PLAN.md §3); no oracle case",
    ("globe", "fetch", ""): "disabled in the seed (enabled = false): the router never plans it",
}


def universe() -> dict:
    """{(source, request type, selector): the reason it is excluded, or None}: every operation that exists."""
    covered_by_sub = {(sid, cap) for sid, cap, _ in SUB_OPERATIONS}
    ops = {(sid, cap, ""): None for sid, cap in seed_operations() if (sid, cap) not in covered_by_sub}
    ops.update({key: None for key in SUB_OPERATIONS})
    for key, reason in EXCLUDED.items():
        assert key in ops, f"EXCLUDED names an operation that does not exist: {key}"
        assert reason, f"an exclusion needs its reason: {key}"
        ops[key] = reason
    return ops
