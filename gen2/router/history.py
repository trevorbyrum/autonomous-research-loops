"""Retained support admission and detached history; operator rulings Oct 20/21.

Snapshots are owned by the opening Router or history reader. Qualification
reuses the independent same-receipt consumer, never SQL authority views.
"""
from copy import deepcopy
from pathlib import Path
from typing import Mapping, Protocol

from gen2.router import boundary, support
from gen2.store import api


class Rows(Protocol):
    def select(self, table: str, where: Mapping[str, object] | None = None) -> list[dict]: ...


def support_diagnostics(store: Rows) -> list[dict]:
    """Caller holds one snapshot over all claims, receipts, checks and bases."""
    deficiencies = []
    for claim in store.select("claims", {"status": "accepted_support", "load_bearing": 1}):
        try:
            support.require_support(store, claim, lambda doc: support.quote_support_valid(store, doc))
        except boundary.Refusal as exc:
            deficiencies.append({"topic_id": claim["topic_id"], "claim_id": claim["claim_id"],
                "claim_revision": claim["revision"], "deficiency": "no qualifying receipt for the complete "
                "detailed-check/basis/tier/use/capture relation: " + exc.detail})
    return deficiencies


class ReconciliationRequired(RuntimeError):
    def __init__(self, deficiencies: list[dict]) -> None:
        self.diagnostic = {"reason": "reconciliation_required", "deficiencies": deficiencies}
        super().__init__("reconciliation_required: " + "; ".join(
            f"{d['topic_id']} {d['claim_id']} revision {d['claim_revision']}: {d['deficiency']}" for d in deficiencies))


def require_retained_support(store: Rows) -> None:
    deficiencies = support_diagnostics(store)
    if deficiencies:
        raise ReconciliationRequired(deficiencies)


_FAMILIES = ("claims", "operation_receipts", "verification_receipts", "detailed_check_records",
    "quote_checks", "source_artifacts", "source_acquisitions", "source_extractions",
    "extraction_validations", "extraction_validations_v2", "audit_events")


class HistoryReader:
    """Frozen historical records, with no Store or normal Router after opening.

    Reopen for a later snapshot. Stored statuses describe history and grant no
    accepted-evidence, completion, configuration or commit capability.
    """
    def __init__(self, path: str | Path) -> None:
        with api.open_store(path) as store:
            with store.transaction():
                self._records = {family: store.select(family) for family in _FAMILIES}
                self._diagnostic = {"reason": None, "deficiencies": support_diagnostics(store)}
                if self._diagnostic["deficiencies"]:
                    self._diagnostic["reason"] = "reconciliation_required"

    @classmethod
    def open(cls, path: str | Path) -> "HistoryReader":
        return cls(path)

    def records(self, family: str) -> dict:
        if family not in _FAMILIES:
            raise ValueError("unknown historical record family")
        return {"interpretation": "historical_records", "family": family,
            "records": deepcopy(self._records[family])}

    def diagnostic(self) -> dict:
        return {"interpretation": "historical_records", **deepcopy(self._diagnostic)}
