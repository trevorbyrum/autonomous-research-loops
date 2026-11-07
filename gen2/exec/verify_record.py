"""The `verification/verify` recorder: admit re-access of the retained bytes each receipt rests on, before the result commits.

Trace: 2e2-min design O15.5; flow S4.8; V-3; DEBT-051 (this is `Router.admit_reaccess`'s production caller, and the router's receipt
check refuses a receipt that did not consume its admitted acquisition, so removing this recorder fails the commit); Astra T11 F2
(replayable, stable effects: the acquisition key is (topic, work, source_version, event, verifier), so a repeat replays).
Oracle: the router's `admitted` or `replayed` reply. Limits: it re-derives the retrieval event for each receipt from the topic's
rows through the same `artifacts.retained` read the view used, and refuses a receipt whose response, call ref, acquiring invocation or
route is not the one it finds (the pure builder checks none of this: Gate S #7); it writes nothing but the admission.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Callable, Mapping

from gen2.core import canonical
from gen2.exec import artifacts, views
from gen2.exec.common import Refused

OK = ("admitted", "replayed")
FAMILIES = ("retrieval_events", "record_work_links", "search_observations")
MAX_OUTCOME = 16 << 20


def _outcome(scratch: Path | str) -> dict:
    try:
        fd = os.open(Path(scratch) / "outcome.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise Refused(f"outcome.json unreadable: {error.strerror}") from None
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_OUTCOME:
            raise Refused("outcome.json is not a bounded regular file")
        return canonical.parse_json_strict(handle.read())


def recorder(exchanges_of: Callable[[str], artifacts.Exchanges]) -> Callable:
    """`Supervisor(..., recorders={"verification/verify": verify_record.recorder(lambda topic: ExchangeIndex(...))})`."""
    def record(control, order: Mapping, grant: Mapping, scratch: Path | str) -> None:
        outcome = _outcome(scratch)
        if (outcome["invocation_id"], outcome["topic_id"]) != (order["invocation_id"], order["topic_id"]):
            raise Refused("the outcome is another invocation's")
        receipts = outcome["verification_receipts"]
        if not receipts:
            return
        records = views.read_records(control, order["topic_id"], FAMILIES)
        exchanges = exchanges_of(order["topic_id"])
        for doc in receipts:
            found = artifacts.retained(doc["source"]["work_id"], records, exchanges)
            if (found.ref["content_hash"], found.gateway_call_ref, found.invocation_id, f"gateway:{found.lane}") != (
                    doc["obtained_content_hash"], doc["acquisition"]["gateway_call_ref"], doc["extraction"]["produced_by_invocation_id"], doc["acquisition"]["route"]):
                raise Refused(f"{doc['verification_receipt_id']}: the retained response is not the one the receipt rests on")
            reply = control.admit_reaccess({"capability_id": grant["capability_id"], "invocation_id": order["invocation_id"],
                                            "work_id": doc["source"]["work_id"], "source_version": doc["source"]["source_version"], "event_id": found.event_id})
            if reply.get("status") not in OK:
                raise Refused(f"admit_reaccess was not accepted: {reply.get('reason', reply.get('status'))}")
    return record
