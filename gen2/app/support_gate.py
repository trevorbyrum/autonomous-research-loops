"""Wires the router's own support predicates to the topic's decoded rows, for the executors that may not import the router.

Trace: Astra #137 F1 (a verification-selection must exclude only what `support.require_support` accepts, never a second weaker
definition); V-3, V-4, V-6, V-8. This is an adapter, not a rule: it presents `topic_records` rows as the `Rows` the router's
`support` module reads, decodes the base64 form `topic_records` gives bytes in, and asks `support.require_support` with
`support.quote_support_valid` as the capture predicate; `support.nonblank` is the router's own blank rule. Oracle: those
predicates. Limits: an operand family that is absent, or a row that lacks a field, counts as NOT qualified (the claim stays
selected for verification); `topic_records` must carry `quote_checks` (lane A) for the capture predicate to see a quarantine.
"""
from __future__ import annotations

import base64
from typing import Callable, Mapping, Sequence

from gen2.router import support
from gen2.router.boundary import Refusal


def _decode(row: Mapping) -> dict:
    return {key: base64.b64decode(value["data"]) if isinstance(value, dict) and value.get("encoding") == "base64" and set(value) == {"encoding", "data"} else value
            for key, value in row.items()}


class TopicRows:
    """The `Rows` protocol over one topic_records answer."""

    def __init__(self, records: Mapping[str, Sequence[Mapping]]) -> None:
        self._tables = {family: [_decode(row) for row in rows] for family, rows in records.items()}

    def select(self, table: str, where: Mapping | None = None) -> list[dict]:
        return [row for row in self._tables.get(table, []) if all(row.get(k) == v for k, v in (where or {}).items())]


class RouterSupport:
    """The `Support` the verification view consults."""

    @staticmethod
    def qualified(records: Mapping[str, Sequence[Mapping]]) -> Callable[[Mapping], bool]:
        rows = TopicRows(records)

        def check(claim: Mapping) -> bool:
            subject = {"claim_id": claim["claim_id"], "revision": claim["revision"], "load_bearing": bool(claim["load_bearing"]),
                       "required_access_tier": claim["required_access_tier"]}
            try:
                support.require_support(rows, subject, lambda doc: support.quote_support_valid(rows, doc))
            except (Refusal, KeyError, TypeError, IndexError, ValueError):
                return False
            return True
        return check

    @staticmethod
    def nonblank(text: object) -> bool:
        return support.nonblank(text)
