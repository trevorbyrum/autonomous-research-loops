"""Output mutators: what the oracle must notice (task 2b-repair-10a, R9-4).

R9-4: the harness took `run(op, valid)[0]` as its baseline, so a mutant that erased every title from the valid answer erased it from the baseline too, and
all 261 harness tests passed. These mutators damage the router's answer at its one public boundary (`router.execute`), knowing nothing of how the gateway
builds it, and `test_oracle.OracleNoticesMutants` requires the hand-written expectations to fail under each. Each takes the answer in place.
"""
from __future__ import annotations

import copy


def _records(out):
    return out.get("records") or []


def erase_titles(out):
    for r in _records(out):
        if "title" in r:
            r["title"] = None


def erase_authors(out):
    for r in _records(out):
        if "authors" in r:
            r["authors"] = []


def shift_years(out):
    for r in _records(out):
        if isinstance(r.get("year"), int):
            r["year"] += 1


def erase_licences(out):
    for r in _records(out):
        if "license" in r:
            r["license"] = None


def fabricate_record(out):
    rs = _records(out)
    if rs:
        extra = copy.deepcopy(rs[0])
        extra["identity"] = "doi:10.9999/fabricated"
        rs.append(extra)


def drop_first_record(out):
    rs = _records(out)
    if rs:
        rs.pop(0)


def reorder_retrieved(out):
    for lane in out.get("lanes") or []:
        if isinstance(lane.get("retrieved"), list):
            lane["retrieved"] = list(reversed(lane["retrieved"]))


def fabricate_entry(out):
    es = out.get("entries")
    if isinstance(es, list) and es:
        extra = copy.deepcopy(es[0])
        extra["id"] = "FABRICATED"
        es.append(extra)


def drop_first_entry(out):
    es = out.get("entries")
    if isinstance(es, list) and es:
        es.pop(0)


def erase_counts(out):
    for r in _records(out):
        for k in ("file_count", "row_count"):
            if k in r:
                r[k] = 0


MUTANTS = {fn.__name__: fn for fn in (erase_titles, erase_authors, shift_years, erase_licences, fabricate_record, drop_first_record, reorder_retrieved,
                                       fabricate_entry, drop_first_entry, erase_counts)}


# Mutants of FAILURE handling, not of valid answers (they leave every valid answer alone, so they are not in MUTANTS: `all_problems` would not notice them, and should not).
def launder_unreadable_catalog(out):
    """What Astra's R10-3 mutant did, at the router's boundary: the BIS validation `identified(...)` deleted turns an unreadable flow listing into a complete one-entry answer
    whose entry is named None (the review: "searched_ok, complete, count one, retrieved ['None']"). The caller applies it only where the input holds an unnamed flow: the
    real mutant changed nothing else."""
    if out.get("request_type") != "catalog":
        return
    for lane in out.get("lanes") or []:
        if lane.get("coverage") == "provider_unavailable" and lane.get("error_class") == "payload_invalid":
            lane.pop("error_class", None)
            lane.update(coverage="searched_ok", completeness="complete", count=1, retrieved=["None"])
            out["entries"] = [{"id": None, "kind": "dataflow"}]


FAILURE_MUTANTS = {fn.__name__: fn for fn in (launder_unreadable_catalog,)}

