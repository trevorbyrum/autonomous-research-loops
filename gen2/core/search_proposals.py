"""Pure proposal-to-request constraints shared by discovery and its Router proof."""
MODE = "proposal-discovery/1"
FACTS = ("search_plan/1", "discovery_binding/1")
PINS = ("topic_id", "admission_context", "contract_revision", "brief_ref", "brief_version", "brief_hash", "brief_confirmation_decision_id", "config_bundle_hash")
RECEIPT_PINS = ("topic_id", "invocation_id", "config_bundle_hash", "admission_context", "contract_revision", "brief_hash")
FILTERS = {"find": {"kind": str, "domain": str, "published_after": str, "year_from": int, "limit": int, "within": str},
           "resolve": {}, "enrich": {"what": str}, "fetch": {"params": dict}, "data": {"params": dict}}


def gateway_request(proposal):
    """Exact attempted request constraints; unsupported filters refuse instead of disappearing."""
    kind, filters = proposal["request_type"], dict(proposal.get("filters") or {})
    for key, value in filters.items():
        if key not in FILTERS[kind] or not isinstance(value, FILTERS[kind][key]) or isinstance(value, bool):
            raise ValueError(f"{proposal['proposal_id']}: filter {key!r} is not a {kind} filter of the right type")
    target = {"find": "query", "resolve": "identity"}.get(kind, "target")
    return {"request_type": kind, target: proposal["query"], "lanes": [proposal["lane"]], **filters}
