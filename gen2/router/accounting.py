"""Minimal read adapter; called inside the Router's snapshot, no arithmetic."""
from typing import Mapping, Protocol

from gen2 import accounting as a


class Rows(Protocol):
    def select(self, table: str, where: Mapping[str, object] | None = None) -> list[dict]: ...


def read_inventory(rows: Rows, topic_id: str, history: a.History) -> a.Inventory:
    where = {"topic_id": topic_id}
    observations = tuple(a.Observation(o["observation_id"], o["invocation_id"], o["lane"], o["request_identity"],
                                       o["request"]["request"]["request_type"], o["completeness"], o["page_outcome"], o["result_count"])
                         for o in rows.select("search_observations", where))
    retrievals = tuple(a.Retrieval(r["event_id"], r["observation_id"]) for r in rows.select("retrieval_events", where))
    events = {r.event_id for r in retrievals}
    works = {w["work_id"] for w in rows.select("works")}
    links = tuple(a.WorkLink(l["event_id"], l["work_id"]) for l in rows.select("record_work_links")
                  if l["event_id"] in events and l["work_id"] in works)
    assessments = tuple(a.Assessment(s["work_id"]) for s in rows.select("screening_assessments", where))
    claims = tuple(a.Claim(c["claim_id"], c["revision"], c["status"]) for c in rows.select("claims", where))
    passes = tuple(a.Pass(p["invocation_id"], p["kind"], p["state"]) for p in rows.select("invocations", where))
    return a.Inventory(history, observations, retrievals, links, assessments, claims, passes)
