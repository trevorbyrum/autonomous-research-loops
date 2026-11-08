"""The offline run's contract and config bundle (2e2-min T18). Not collected as tests.

`contract()` is the router fixtures' example contract (valid, hash true) as TOPIC's revision 1 with a confidence scheme, so the research
pass's confidence labels are checked against the approved scheme (recorded, not unknown). `bundle()` is the router fixtures' bundle with
`policy.executors` for the given entries (kind, purpose, pinned prompt, limits), which the order builder refuses to run without.
Limits: hand-drafted, as the first topic's contract is (plan row 18); nothing here approves or activates anything.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from gen2.tests.router_fixtures import BUNDLE, contract_doc

SCHEME = {"scheme_id": "offline-confidence", "version": 1,
          "labels": {"low": "One source, or sources that disagree.", "high": "Two or more independent sources agree."}}


def contract(revision: int = 1, parent: int | None = None) -> dict:
    return contract_doc(revision, parent, edit=lambda doc: doc.update(confidence_scheme=SCHEME))


def bundle(executors: Sequence[Mapping], version: int = 2) -> dict:
    return {**BUNDLE, "version": version, "policy": {"executors": list(executors)}}
