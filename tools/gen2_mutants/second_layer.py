"""The guards kept as a documented second layer (not independently killable),
moved verbatim from tools/gen2_mutations.py (task 2r)."""

# Guards deliberately kept as a second layer behind another guard that
# always fires first for every row that reaches them, so no test can kill
# their removal alone. Listed so a reviewer does not mistake them for missed
# coverage; each names the first layer (which IS in the inventory).
SECOND_LAYER = {
    "gen2/operator/service.py label(): the method label (GET/POST, else ?) (1e-repair, Astra 1e review finding 3)":
        "only do_GET and do_POST call the service, and the engine's fault path runs inside them, so every method it labels is GET or POST; "
        "any other method is refused by http.server's dispatch through the engine's send_error, a fixed reply and fixed log line "
        "(1E-engine-parser-reflects kills its removal). The label is kept so the rule reads the same for method and route",
    "gen2/operator/service.py _answer: redact() on the log line (1e-repair, Astra 1e review finding 3)":
        "a log line holds only the service's labels (1E-svc-unknown-route-verbatim, 1E-svc-unknown-command-verbatim, 1E-svc-log-leaks-token "
        "kill a request's text reaching it), a configured principal's role and name, and a reply's status, which the router or supervisor "
        "writes from its own vocabulary; none carries a request's text, so no configured token can reach it for redaction to take out. "
        "The reply's redaction is the tested layer (1E-svc-reply-unredacted)",
    "gen2/operator/service.py _mcp: arguments omitted read as {} (1e-repair, Astra 1e review finding 4)":
        "MCP_PARAMS types every params member before the tool call reads it, so a given `arguments` that is not an object is refused first "
        "(1E-mcp-params-types-unchecked); only an omitted one reaches the default. The review's truthiness defect (arguments [] read as {}) "
        "is killed through that type check",
    "gen2/supervisor/supervisor.py _settle_delegates: the delegate's own lock, taken under its parent's (1c-repair-4)":
        "every caller that writes a delegate's journal holds its parent's lock first (_exclusive: a delegate's advance and recover() take "
        "the parent's, then the delegate's; a parent ends its delegates holding its own), so no second caller can hold the delegate's while a "
        "parent holds its own and settles it; the parent's lock is the first layer (1C-sup-delegate-locks-only-itself, 1C-jobs-lock-not-taken). "
        "It is taken so the rule reads the same for every journal, and holds if a future path takes a delegate's lock alone",
    "invocation_reconciliations CHECK: request's json_type(request) = 'object' conjunct (1c-repair A8)":
        "the column-agreement CHECK reads the request's resolution, method, evidence and digest with json_extract, which is NULL for any "
        "non-object JSON, so a non-object request is refused there first (1C-ddl-reconciliation-request-unbound drops that CHECK; "
        "RecordedRequestTest pins the refusal of an array request)",
    "export_delivery_receipts CHECK (connector_type IN ('sql', 'jsonl_file', 'webhook', 'extension')) (0d)":
        "a receipt is refused unless its manifest names that connector with that type (export_delivery_receipts_expected_connector, "
        "D48-*), and a manifest names only declared types (outbox_events_connectors_declared, 0D-connectors-*); the trigger fires before "
        "the CHECK, so an undeclared type is refused there first. The CHECK is the store's last word on the vocabulary if either trigger goes",
    "outbox_events_generation_is_one_approved_revision: the source_revision and source_content_hash conjuncts alone (0d)":
        "an approval names exactly one source revision and hash (outbox_events_only_approved, A2-publication-revision/-hash), so a re-export "
        "whose revision or hash differs cites a different approval as well; the three are mutated together as one dimension "
        "(0D-one-generation-another-approved-revision), and the approval conjunct alone (0D-one-generation-another-approval)",
    "screening_provider_needs_qualified_authority (trigger)":
        "screening_assessments_bound requires the receipt's commit_operation_id to be the assessment's recording operation; a receipt has a "
        "commit_operation_id only for commit_reversible_action, which a CHECK allows only at qualified authority (A10-screening-binds-commit)",
    "verification_receipts CHECK (verdict != 'supports' OR exact_quote.status IN ('matched', 'not_applicable'))":
        "a mismatched quote is always quarantined (quote_checks CHECK, A6-D32-byte-mismatch) and a matched/mismatched status needs a bound check "
        "(A6-quote-check-iff-status), so verification_receipts_bindings refuses support on it first (A6-quote-binding-*)",
    "invocations CHECK: the unknown_episode >= 1 conjunct of the outcome_unknown shape (RA4)":
        "an invocation is inserted admitted with unknown_episode 0 (column CHECK >= 0), and every entry into outcome_unknown takes "
        "exactly the previous number + 1 (invocations_unknown_episode_is_fresh, RA4-entry-takes-next-identity), so the conjunct cannot fail on its own",
    "facets/obligations_rating_is_what_the_operator_rated: the d.kind = 'rating_approval' conjunct (RA2)":
        "only a rating decision carries a payload (operator_decisions CHECK, RA2-payload-only-on-rating-decisions) and a decision without one joins "
        "no payload row, so a decision of another kind is refused before the kind conjunct is read",
    "contract_approval_pointer_set_by_approval: its superseded case (RA3-R — no pointer first recorded by draft -> superseded)":
        "since 0a-repair-3 ruling 1, contract_status_forward_only refuses draft -> superseded outright (R1c-draft-superseded-edge-restored), and a "
        "pointer can only be first recorded on a draft (a non-draft holds one by CHECK, R1c-approved-without-decision); the trigger's approved "
        "exemption and the trigger itself are mutated (RA3R-approval-refused-too, RA3R-dropped). Which of the two triggers reports first is "
        "SQLite trigger order, which no test may depend on",
    "intake_briefs_confirmation_bound: each subject conjunct alone (topic; brief id and version; hash)":
        "a brief_confirmation is recorded only about a stored brief with exactly that topic, id, version and hash (IB-decision-subject-exists), "
        "and brief hashes are unique, so any one of them identifies the same stored subject as the rest; they are mutated together "
        "(IB-confirmation-subject). At admission the pins are not otherwise checked, so there each conjunct is mutated alone (A4-brief-confirmation-*)",
    "intake_briefs CHECKs: confirmed/archived hold a confirming decision; awaiting/cancelled hold none (0b)":
        "a brief is confirmed only through intake_briefs_confirmation_bound, which needs an existing decision (IB-confirmation-bound-dropped), "
        "archived is reached only from confirmed (IB-archive-from-awaiting), and the pointer is set only by that transition and never "
        "changes (IB-pointer-dropped, IB-pointer-changes-after); so neither CHECK can be the first refusal",
    "claims_accepted_support_needs_receipt: its required-tier, obtained-tier and performed-checks conjuncts (RA5, re-checked at promotion)":
        "a load-bearing-use receipt is written only at its claim's own required tier (verification_receipts_use_matches_claim, RA5-use-matches-claim-*), "
        "'supports' never exceeds the obtained tier (verification_receipts CHECK), and a load-bearing support cannot record an unperformed check "
        "(A6-load-bearing-support-checks-performed); the trigger's own use and verdict conjuncts are mutated (RA5-promotion-*)",
}


SECOND_LAYER_TRIGGERS = {"screening_provider_needs_qualified_authority"}
