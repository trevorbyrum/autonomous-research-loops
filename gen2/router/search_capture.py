"""E-2/E-4: Router-derived plans and execution bindings, joined in detached reads.

Facts are atomic with commit/admission. A reference string grants no ownership;
proof uses exact retained receipts, admission pins and requests. No spool I/O.
"""
from gen2 import accounting as a
from gen2.core.search_proposals import MODE, FACTS, PINS, RECEIPT_PINS, gateway_request
from gen2.router.boundary import Refusal


def context(inv):
    return {k: inv[k] for k in PINS}


def enabled(core, inv):
    return core._registries._bundle(inv["config_bundle_hash"])["policy"].get("search_capture") == MODE


def plan(core, inv, payload):
    if not enabled(core, inv) or inv["kind"] not in ("research_pass", "checkpoint"):
        return None
    proposals = payload.get("search_proposals", [])
    if len({p["proposal_id"] for p in proposals}) != len(proposals):
        raise Refusal("payload_invalid", "search_proposals repeats a proposal id")
    if inv["kind"] == "checkpoint" and not proposals:
        return None
    try:
        return {"context": context(inv), "proposals": [{"proposal_id": p["proposal_id"], "request": gateway_request(p),
            "obligation_ids": p["obligation_ids"], "page_cap": p["page_cap"] if p["request_type"] == "find" else 1} for p in proposals]}
    except ValueError as error:
        raise Refusal("payload_invalid", str(error)) from None


def proven_plan(inv, facts, receipts):
    if len(facts) != 1 or len(receipts) != 1 or inv["state"] != "committed":
        return None
    fact, receipt = facts[0], receipts[0]
    if any(receipt[k] != inv[k] for k in RECEIPT_PINS):
        return None
    detail = fact["detail"]
    if (fact["topic_id"], fact["operation_id"], detail.get("payload_digest"), detail.get("context")) != (
            inv["topic_id"], receipt["operation_id"], receipt["payload_digest"], context(inv)):
        return None
    return detail


def bind(core, inv, now):
    source = inv["requested_by_invocation_id"]
    if inv["kind"] != "discovery" or source is None or not enabled(core, inv):
        return
    proposer = core._one("invocations", {"invocation_id": source})
    facts = core._store.select("audit_events", {"kind": FACTS[0], "invocation_id": source})
    receipts = core._store.select("operation_receipts", {"invocation_id": source, "operation_kind": "final_outcome"})
    proof = proven_plan(proposer, facts, receipts) if proposer and enabled(core, proposer) else None
    if proof is None or proposer["kind"] not in ("research_pass", "checkpoint") or any(inv[k] != proposer[k] for k in PINS[:-1]):
        raise Refusal("discovery_binding_invalid", "discovery requires its proposer's exact committed plan and admission pins")
    core._audit(FACTS[1], now, {"context": context(inv), "proposer": source, "source_operation": receipts[0]["operation_id"],
                "payload_digest": receipts[0]["payload_digest"]}, topic_id=inv["topic_id"], invocation_id=inv["invocation_id"])


def resolve(read, modes):
    """Return typed pass expectations and per-observation attribution; absent/ambiguous proof stays unknown."""
    invs = {i["invocation_id"]: i for i in read("invocations")}
    audits, receipts = list(read("audit_events")), list(read("operation_receipts"))
    plans, bindings = {}, {}
    for iid, inv in invs.items():
        if modes.get(inv["config_bundle_hash"]):
            proof = proven_plan(inv, [f for f in audits if (f["kind"], f["invocation_id"]) == (FACTS[0], iid)],
                                [r for r in receipts if (r["invocation_id"], r["operation_kind"]) == (iid, "final_outcome")])
            if proof is not None and inv["kind"] in ("research_pass", "checkpoint"):
                plans[iid] = proof
    for iid, inv in invs.items():
        facts = [f for f in audits if (f["kind"], f["invocation_id"]) == (FACTS[1], iid)]
        if inv["kind"] != "discovery" or not modes.get(inv["config_bundle_hash"]) or len(facts) != 1:
            continue
        fact, source = facts[0], inv["requested_by_invocation_id"]
        detail, proof = fact["detail"], plans.get(source)
        if proof is not None and fact["topic_id"] == inv["topic_id"] and detail.get("context") == context(inv) and detail.get("proposer") == source:
            receipt = next(r for r in receipts if r["invocation_id"] == source and r["operation_kind"] == "final_outcome")
            if (detail.get("source_operation"), detail.get("payload_digest")) == (receipt["operation_id"], receipt["payload_digest"]) and all(inv[k] == invs[source][k] for k in PINS[:-1]):
                bindings[iid] = source
    passes = tuple(a.Pass(iid, i["kind"], i["state"], i["parent_invocation_id"], bool(modes.get(i["config_bundle_hash"])),
                         tuple(p["proposal_id"] for p in plans[iid]["proposals"]) if iid in plans else None, bindings.get(iid)) for iid, i in invs.items())
    attribution = {}
    for obs in read("search_observations"):
        iid, request = obs["invocation_id"], obs["request"]
        source = bindings.get(iid)
        owned = {}
        if source is not None and isinstance(request, dict):
            proposals = [p for p in plans[source]["proposals"] if request.get("proposal_ref") == f"{source}:{p['proposal_id']}"]
            if len(proposals) == 1:
                p, sent = proposals[0], request.get("request", {})
                if ({k: v for k, v in sent.items() if k != "cursors"} == p["request"] and obs["lane"] in p["request"]["lanes"]
                        and obs["obligation_ids"] == p["obligation_ids"] and 1 <= request.get("page", 0) <= p["page_cap"]):
                    owned = {"proposed_by": source, "chain": (iid, obs["attempt"], p["proposal_id"])}
        labelled = isinstance(request, dict) and "proposal_ref" in request
        attribution[obs["observation_id"]] = owned or {"unbound": bool(labelled or modes.get(invs[iid]["config_bundle_hash"]) and invs[iid]["kind"] == "discovery")}
    return passes, attribution
