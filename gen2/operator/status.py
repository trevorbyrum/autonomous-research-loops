"""Why every waiting item waits (task 1e): the operator's status, composed from
the router's status read and the station's open incidents.

Trace: INVARIANTS RG-9 and H-4 (status answers why every waiting item
waits), H-2 (dated capability facts), H-3 (typed holds: owner, deadline,
required authority, what clears them), L-4 (an outcome_unknown episode waits
for its reconciliation), L-6 and RG-3 (re-queues, exhausted budgets and
incidents are visible, owned and deadlined), G-1 (amendment_pending), G-4
(briefs awaiting confirmation, overdue included), C-12 and RG-9 (pinned
config bundles); BOUNDARIES.md Operator (interface guarantees); flow §4.4;
gen2/router/status.py (the facts and the router's own judgments of them);
gen2/supervisor/supervisor.py Supervisor.incidents (the incidents: a stalled
job's blocking one — the collected end whose descendants were never
confirmed ended stalls as outcome_unknown_unresolved, which needs the
operator — and each exhausted retry budget, recorded beside its job's end;
each names its invocation and topic from the job's durable order, whatever
the topic's lanes have done since, Astra 1e review finding 5). A blocking
incident says what clears it: the operator's recover_incident.

Nothing here decides anything: every reason is read off a fact, and each
names what it waits for and, where the record has them, who owns it and by
when. Reading status changes nothing (the router's read writes no row; the
incidents are read from the journals).

The engine itself waits for each open hold of no topic (`waiting`; task 1f:
a capability's hold, whose fact is among the capability facts beside it).

A topic waits for what its status says it waits for (STATUS_WAITS; an active
topic's work is in its invocations, and a completed or retired one waits for
nothing), and for each of: a pause, an open hold, a brief version awaiting
confirmation, a contract draft awaiting approval, a lane whose last work
ended failed or cancelled (not yet re-queued, re-queued and not yet claimed,
or held by its exhausted budget), pending signals, an open review, and an
incident of work that has ended. A live invocation waits for the next step of
its state (STATE_WAITS), and for each of: a refused launch admission, a
cancellation not yet confirmed, a passed deadline, an expired lease, pins an
amendment made incompatible (amendment_pending), and an incident.
"""
from __future__ import annotations

STATUS_WAITS = {
    "awaiting_brief_confirmation": "brief_confirmation",
    "scoping": "scoping_report",
    "awaiting_scope_approval": "scope_approval",
    "awaiting_contract_approval": "contract_approval",
    "queued": "claim",
    "resting": "claim",
    "held": "held",
    "capability_blocked": "capability_blocked",
    "stopped_for_resources": "stopped_for_resources",
    "awaiting_judgment": "judgment",
}
STATE_WAITS = {"admitted": "launch", "launching": "start", "running": "end", "result_ready": "commit", "outcome_unknown": "reconciliation"}


def compose(facts: dict, incidents: list[dict]) -> dict:
    listed = [{**incident, **({"clears_when": "recover_incident"} if incident["blocking"] else {})} for incident in incidents]
    return {"status": "ok", "at": facts["at"], "topics": [_topic(topic, listed) for topic in facts["topics"]], "incidents": listed,
            "config_bundles": facts["config_bundles"], "capability_facts": facts["capability_facts"],
            "waiting": [{"reason": "hold", **hold} for hold in facts["holds"]]}


def _incident(incident: dict) -> dict:  # nested: an incident's own fields never overwrite the reason
    return {"reason": "incident", "incident": {k: v for k, v in incident.items() if k != "topic_id"}}


def _topic(topic: dict, incidents: list[dict]) -> dict:
    waiting = []
    if topic["status"] in STATUS_WAITS:
        waiting.append({"reason": STATUS_WAITS[topic["status"]], "status": topic["status"]})
    if topic["paused_at"] is not None:
        waiting.append({"reason": "paused", "since": topic["paused_at"]})
    for hold in topic["holds"]:
        waiting.append({"reason": "hold", **hold})
    for brief in topic["briefs"]:
        if brief["status"] == "awaiting_confirmation":
            waiting.append({"reason": "brief_awaiting_confirmation", **{k: brief[k] for k in ("brief_id", "version", "owner", "review_deadline",
                                                                                                "overdue_since", "deadline_passed")}})
    for draft in topic["drafts"]:
        waiting.append({"reason": "draft_awaiting_approval", **draft})
    for lane in topic["lanes"]:
        if lane["state"] in ("failed", "cancelled"):
            if lane["requeue_hold"] is not None:
                reason = "requeue_hold"
            elif lane["requeue"] is None:
                reason = "requeue"
            else:
                reason = "retry_claim"
            waiting.append({"reason": reason, **lane})
    if topic["signals"]:
        waiting.append({"reason": "signals", "pending": topic["signals"]})
    for review in topic["reviews"]:
        waiting.append({"reason": "review", **review})
    live = {inv["invocation_id"] for inv in topic["invocations"]}
    waiting += [_incident(i) for i in incidents if i["topic_id"] == topic["topic_id"] and i["invocation_id"] not in live]
    return {**topic, "waiting": waiting, "invocations": [_invocation(inv, incidents) for inv in topic["invocations"]]}


def _invocation(inv: dict, incidents: list[dict]) -> dict:
    waiting = [{"reason": STATE_WAITS[inv["state"]], "state": inv["state"]}]
    if inv["unknown"] is not None:
        waiting[0].update(episode=inv["unknown"]["episode"], since=inv["unknown"]["since"], hold=inv["unknown"]["hold"])
    if inv["launch_admission"] is not None:
        waiting.append({"reason": "launch_refused", "refusal": inv["launch_admission"]})
    if inv["cancel_requested"] is not None:
        waiting.append({"reason": "cancellation", **inv["cancel_requested"]})
    if inv["deadline_passed"]:
        waiting.append({"reason": "deadline_passed", "deadline_at": inv["deadline_at"]})
    if inv["lease"]["expired"] and inv["lease"]["released_at"] is None:
        waiting.append({"reason": "lease_expired", "lease_id": inv["lease"]["lease_id"], "expires_at": inv["lease"]["expires_at"]})
    if inv["pins"]["incompatible"]:
        waiting.append({"reason": "amendment_pending", "admission": inv["admission"], "standing": inv["pins"]["standing"], "superseded_by": inv["pins"]["current"]})
    waiting += [_incident(i) for i in incidents if i["invocation_id"] == inv["invocation_id"]]
    return {**inv, "waiting": waiting}
