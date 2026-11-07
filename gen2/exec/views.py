"""Bounded, topic-scoped input views for the executors.

Trace: 2e2-min design O14.3; Astra T11 F3 (operands named per purpose); INVARIANTS RG-4 (coverage is read from
recorded observations, never model-supplied), C-12 (the brief is the one the admission pins). Oracle: the rows
the reader returns; a view adds no fact of its own. Limits: `topic_records` is T12-A's read route, coded here
against its ticket-plan shape ({status: ok, records: {family: [row, ...]}}); truncation is recorded, and the
final byte cap is orders.write_inputs'.
"""
from __future__ import annotations

from typing import Callable, Mapping, Protocol, Sequence

from gen2.core import canonical
from gen2.exec import artifacts
from gen2.exec.common import Refused

ROW_CAP = 200
OBSERVATION_KEYS = ("observation_id", "lane", "coverage_state", "completeness", "result_count", "error_class", "request")
SCOPE_FAMILIES = ("intake_briefs", "search_observations", "scoping_reports")


class RecordsReader(Protocol):
    def topic_records(self, request: Mapping) -> dict:
        """{topic_id, families} -> {status: ok, topic_id, records: {family: [row, ...]}} or {status: refused, ...}."""


def read_records(reader: RecordsReader, topic_id: str, families: Sequence[str]) -> dict[str, list[Mapping]]:
    """One read of the named families. A refusal, or a family missing from the answer, stops the order."""
    answer = reader.topic_records({"topic_id": topic_id, "families": list(families)})
    if answer.get("status") != "ok" or answer.get("topic_id") != topic_id:
        raise Refused(f"topic_records refused: {answer.get('reason', answer.get('status'))}")
    records = answer["records"]
    if set(families) - set(records):
        raise Refused(f"topic_records omitted {sorted(set(families) - set(records))}")
    return records


def bounded(family: str, rows: Sequence, truncation: list[dict], cap: int = ROW_CAP) -> list:
    """The last `cap` rows (the most recent), recording what was dropped."""
    if len(rows) > cap:
        truncation.append({"family": family, "kept": cap, "total": len(rows)})
    return list(rows[-cap:])


def scope_view(admission: Mapping, records: Mapping[str, Sequence[Mapping]], lanes: Sequence[str], as_of: str,
               truncation: list[dict]) -> dict:
    """The scoping pass's view: the pinned brief's body, what earlier searches recorded, the standing report."""
    if admission.get("context") != "pre-contract/1":
        raise Refused("a scope view needs a pre-contract/1 admission")
    pin = admission["brief"]
    matches = [row for row in records["intake_briefs"]
               if (row["brief_id"], row["version"], row["content_hash"]) == (pin["brief_id"], pin["version"], pin["content_hash"])]
    if len(matches) != 1:
        raise Refused("the admission's brief is not exactly one intake_briefs row")
    reports = sorted(records["scoping_reports"], key=lambda row: row["version"])
    return {"as_of": as_of, "brief": {**pin, "document": matches[0]["document"]}, "available_lanes": list(lanes),
            "observations": [{key: row.get(key) for key in OBSERVATION_KEYS}
                             for row in bounded("search_observations", records["search_observations"], truncation)],
            "latest_report": ({k: reports[-1][k] for k in ("report_id", "version")} if reports else None)}


ABSTRACT_CAP = 1500
RESEARCH_FAMILIES = ("contract_revisions", "works", "record_work_links", "retrieval_events",
                     "search_observations", "claims")


def abstract_of(retained: artifacts.Retained) -> str | None:
    """The retained response's own canonical `abstract` for this record (T12-G), or None."""
    try:
        body = canonical.parse_json_strict(retained.data)
        for record in body["gateway_response"]["records"] if "gateway_response" in body else body["records"]:
            if record.get("identity") == retained.provider_record_id and isinstance(record.get("abstract"), str):
                return record["abstract"] or None
    except (ValueError, KeyError, TypeError):
        pass
    return None


def research_view(admission: Mapping, records: Mapping[str, Sequence[Mapping]], exchanges: artifacts.Exchanges,
                  claim_text: Callable[[str], str | None], as_of: str, state_revision: int, truncation: list[dict]) -> dict:
    """The research pass's view: the pinned contract's own wording (objective, key questions, facets, obligation text and
    slots, confidence rubrics; none truncated, so an over-cap input is refused by write_inputs), the works the topic retrieved and retained
    (with the retained abstract when one is there), and earlier claims. A work with no staged response never
    appears, so the pass cannot cite what the builder could not bind (F3)."""
    if admission.get("context") != "contract/1":
        raise Refused("a research view needs a contract/1 admission")
    pin = admission["contract"]
    rows = [r for r in records["contract_revisions"] if (r["revision"], r["content_hash"]) == (pin["revision"], pin["content_hash"])]
    if len(rows) != 1:
        raise Refused("the admission's contract is not exactly one contract_revisions row")
    document = rows[0]["document"]
    scheme = document.get("confidence_scheme")
    record, framework = document["decision_record"], document["facet_map"]
    works, cut = [], 0
    for work in records["works"]:
        try:
            found = artifacts.retained(work["work_id"], records, exchanges)
        except Refused:
            continue
        abstract = abstract_of(found)
        entry = {"work_id": work["work_id"], "identity": f"{work['identity_scheme']}:{work['identity_value']}"}
        if abstract is not None:
            entry["abstract"], cut = abstract[:ABSTRACT_CAP], cut + (len(abstract) > ABSTRACT_CAP)
        works.append(entry)
    if cut:
        truncation.append({"family": "abstracts", "kept": len(works) - cut, "total": len(works)})
    claims = [{"claim_id": r["claim_id"], "revision": r["revision"], "load_bearing": bool(r["load_bearing"]), "text": claim_text(r["text_ref"])}
              for r in bounded("claims", records["claims"], truncation)]
    return {"as_of": as_of, "state_revision": state_revision,
            "contract": {**pin, "framing_version": rows[0]["framing_version"], "eligibility_protocol": document["eligibility_protocol"],
                         "objective": record["objective"]["operator_words"], "feeds": record["feeds"],
                         "evidence_that_would_change_it": record["evidence_that_would_change_it"],
                         "key_questions": [{k: link[k] for k in ("link_id", "key_question")} for link in framework["analytic_framework"]["links"]],
                         "facets": [{k: f[k] for k in ("facet_id", "label", "kind")} for f in framework["facets"]],
                         "confidence_scheme": None if scheme is None else {"scheme_id": scheme["scheme_id"], "version": scheme["version"], "labels": scheme["labels"]}},
            "obligations": [{"obligation_id": o["obligation_id"], "claim_type": o["template"]["claim_type"], "text": o["text"], "slots": o["slots"],
                             "facet_ids": o["facet_ids"]} for o in document["obligations"]],
            "works": bounded("works", works, truncation), "claims": claims}
