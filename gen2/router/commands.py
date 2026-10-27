"""The router's own command request shapes (commands, not stored documents), on the shared vocabulary: claim, transition, observation, works and
operator_decision. Moved from service.py unchanged; the other command tables live beside their collaborators. `LIFECYCLE_FACTS` is here because the transition
shape enumerates its target states; service.py reads it for the facts each target records.
"""
from __future__ import annotations

from gen2.core import pagination

LIFECYCLE_FACTS = {  # target state -> the facts that record it (L-2, L-3, C-9; task 1c: L-4, L-5, L-7, L-9)
    "launching": ("job_handle",),
    "running": ("host_id", "container_id", "boot_id", "start_fingerprint"),
    "result_ready": ("result_payload_digest",),
    "failed": ("failure_class", "end_evidence_ref"),
    "cancelled": ("end_evidence_ref",),
    "outcome_unknown": ("unknown_episode",),
}
_ID = {"$ref": "common.schema.json#/$defs/short_text"}
_OPT = {"oneOf": [{"type": "null"}, {"$ref": "common.schema.json#/$defs/short_text"}]}
_TS = {"$ref": "common.schema.json#/$defs/timestamp"}
_CAP = {"$ref": "common.schema.json#/$defs/capability_id"}
_INV = {"$ref": "common.schema.json#/$defs/invocation_id"}
COMMANDS = {  # the router's own request shapes (commands, not stored documents), on the shared vocabulary
    "$defs": {
        "claim": {
            "type": "object", "additionalProperties": False,
            "required": ["invocation_id", "kind", "topic_id", "config_bundle_hash", "deadline_at"],
            "properties": {
                "invocation_id": _INV, "kind": {"$ref": "common.schema.json#/$defs/invocation_kind"},
                "topic_id": {"$ref": "common.schema.json#/$defs/topic_id"}, "station_id": _ID,
                "config_bundle_hash": {"$ref": "common.schema.json#/$defs/sha256"}, "deadline_at": _TS, "lease_expires_at": _TS,
                "parent_capability_id": _CAP, "requested_by_invocation_id": _INV, "retry_of": _INV,
                "reservation": {"$ref": "router-commands#/$defs/draw"}},
            "if": {"properties": {"kind": {"const": "delegate"}}},
            "then": {"required": ["parent_capability_id"], "not": {"anyOf": [{"required": k} for k in (["lease_expires_at"], ["station_id"], ["retry_of"], ["reservation"])]}},
            "else": {"required": ["lease_expires_at", "station_id"], "not": {"required": ["parent_capability_id"]}}},
        "transition": {
            "type": "object", "additionalProperties": False, "required": ["capability_id", "invocation_id", "to_state"],
            "properties": {
                "capability_id": _CAP, "invocation_id": _INV, "to_state": {"enum": sorted(LIFECYCLE_FACTS)},
                "job_handle": _ID, "host_id": _ID, "container_id": _OPT, "boot_id": _ID, "start_fingerprint": _ID,
                "result_payload_digest": {"$ref": "common.schema.json#/$defs/sha256"},
                "failure_class": {"$ref": "execution-record.schema.json#/properties/findings/items"},
                "end_evidence_ref": {"$ref": "common.schema.json#/$defs/sha256"},
                "unknown_episode": {"type": "integer", "minimum": 1, "maximum": 9007199254740991},
                "unknown_cause": {"enum": ["spawn_uncertain", "contact_lost", "termination_unconfirmed"]}}},
        "observation": {
            "type": "object", "additionalProperties": False, "required": ["capability_id", "invocation_id", "observation", "retrieval_events"],
            "properties": {
                "capability_id": _CAP, "invocation_id": _INV,
                "observation": {
                    "type": "object", "additionalProperties": False,
                    "required": ["observation_id", "request", "request_identity", "attempt", "lane", "obligation_ids", "started_at", "ended_at",
                                 "coverage_state", "result_count", "completeness", "error_class", "capability_fact_id", "policy_version",
                                 "cost_units", "gateway_call_ref", "page_outcome", "continuation"],
                    "properties": {
                        "observation_id": {"type": "string", "pattern": "^obs_[A-Za-z0-9_-]{8,64}$"},
                        "request": {"type": ["object", "string"]}, "request_identity": {"$ref": "common.schema.json#/$defs/sha256"},
                        "attempt": {"type": "integer", "minimum": 1, "maximum": 9007199254740991}, "lane": _ID,
                        "obligation_ids": {"type": "array", "maxItems": 100, "uniqueItems": True, "items": {"$ref": "common.schema.json#/$defs/local_id"}},
                        "started_at": _TS, "ended_at": {"oneOf": [{"type": "null"}, _TS]},
                        "coverage_state": {"$ref": "common.schema.json#/$defs/coverage_state"},
                        "result_count": {"oneOf": [{"type": "null"}, {"type": "integer", "minimum": 0, "maximum": 9007199254740991}]},
                        "completeness": {"enum": ["complete", "partial", "unobserved"]},
                        "error_class": {"enum": [None, "payload_invalid", "timeout", "rate_limited", "breaker_open", "budget_refused", "provider_outage",
                                                 "credentials_rejected", "credentials_not_configured", "secrets_backend_failing", "transport_failure",
                                                 "telemetry_missing", "partial_pagination"]},
                        "capability_fact_id": _OPT, "policy_version": _ID,
                        "cost_units": {"oneOf": [{"type": "null"}, {"type": "integer", "minimum": 0, "maximum": 9007199254740991}]},
                        "gateway_call_ref": _OPT,
                        "page_outcome": {"enum": list(pagination.PAGE_OUTCOMES)},
                        "continuation": {"oneOf": [{"type": "null"}, {
                            "type": "object", "additionalProperties": False, "required": ["cursor"],
                            "properties": {"cursor": {"type": ["integer", "string"]}}}]}}},   # the shape; the cursor domain is boundary.check_page_outcome's
                "retrieval_events": {
                    "type": "array", "maxItems": 10000,
                    "items": {"type": "object", "additionalProperties": False, "required": ["event_id", "provider_record_id", "rank", "captured_at"],
                              "properties": {"event_id": {"type": "string", "pattern": "^rev_[A-Za-z0-9_-]{8,64}$"}, "provider_record_id": _ID,
                                             "rank": {"oneOf": [{"type": "null"}, {"type": "integer", "minimum": 1, "maximum": 9007199254740991}]},
                                             "captured_at": _TS}}}}},
        "works": {  # task 2a
            "type": "object", "additionalProperties": False, "required": ["capability_id", "invocation_id", "dedup_method_version", "works"],
            "properties": {
                "capability_id": _CAP, "invocation_id": _INV, "dedup_method_version": _ID,
                "works": {"type": "array", "minItems": 1, "maxItems": 1000, "items": {
                    "type": "object", "additionalProperties": False, "required": ["identity_scheme", "identity_value", "event_ids"],
                    "properties": {"identity_scheme": {"enum": ["doi", "arxiv", "pmid", "isbn", "url", "gateway_record"]}, "identity_value": _ID,
                                   "event_ids": {"type": "array", "minItems": 1, "maxItems": 10000, "uniqueItems": True,
                                                 "items": {"type": "string", "pattern": "^rev_[A-Za-z0-9_-]{8,64}$"}}}}}}},
        "operator_decision": {
            "type": "object", "additionalProperties": False,
            "required": ["decision_id", "topic_id", "kind", "disposition", "subject", "operator_id", "decided_at", "notes", "payload"],
            "properties": {
                "decision_id": {"$ref": "common.schema.json#/$defs/operator_decision_id"},
                "topic_id": {"oneOf": [{"type": "null"}, {"$ref": "common.schema.json#/$defs/topic_id"}]},
                "kind": {"enum": ["brief_confirmation", "scope_approval", "rating_approval", "contract_approval", "amendment_approval", "reframe_approval",
                                  "completion_approval", "retirement", "hold_clearance", "publication_approval", "blind_initial_disposition", "advised_feedback",
                                  "source_approval"]},
                "disposition": {"enum": ["approved", "rejected", "deferred", "recorded"]},
                "subject": {"type": "object", "additionalProperties": False, "required": ["kind", "ref", "revision", "hash"],
                            "properties": {"kind": {"enum": ["intake_brief", "scoping_report", "contract_revision", "dossier", "topic", "hold",
                                                             "publication_source", "decision_receipt", "source_proposal"]},
                                           "ref": _ID, "revision": {"oneOf": [{"type": "null"}, {"$ref": "common.schema.json#/$defs/state_revision"}]},
                                           "hash": {"oneOf": [{"type": "null"}, {"$ref": "common.schema.json#/$defs/sha256"}]}}},
                "operator_id": _ID, "decided_at": _TS,
                "notes": {"oneOf": [{"type": "null"}, {"$ref": "common.schema.json#/$defs/long_text"}]},
                "payload": {"type": ["object", "null"]}}},
    },
}
