"""Counterfactual checks for schema fixtures: a negative fixture must be
refused by the rule it was written for, not by some other rule that happens
to report the same (keyword, path).

Trace: Astra 0c review C1. The mixed-disposition negative still passed after
its rule was removed, because a second, unrelated rule failed at the same
instance path; Astra showed it by running the repository's own schema check
on a temporary copy of the whole schema tree with the rule deleted. These
tests make that counterfactual a standing check. Each run copies gen2/schema
and docs/gen2/BOUNDARIES.md into a temporary root, runs
`tools/check_gen2_schemas.py --root <tmp> --part schemas` as a subprocess,
and each test asserts that the fixtures it names still behave exactly as
declared.

Unmutated, these tests restate what `make gen2-schemas` already checks. Their
purpose is the mutation inventory (tools/gen2_mutations.py, the `0CR-`
entries): the harness points one of the *_SCHEMA globals below at a copy of
that schema with a rule removed, and the test named for the rule's negative
must then fail, because that negative no longer behaves exactly as declared.
That happens in one of two ways, and they prove different things:

- An isolated negative declares one error, from its rule alone. The kill
  means the negative now validates: the mutant admits a bad document, and
  the negative depends on that rule. Every export negative except the
  combined unreadable-response regression is of this kind (the manifest and
  freshness-envelope negatives of task 0d included, and the per-member ones
  0d-repair added beside its whole-object negatives), and so are the three
  single-member identity negatives.
- A combined negative declares two or three errors, and the negative is
  still refused after the removal, only with fewer errors than declared. The
  kill means the checker noticed that rule's contribution go missing. It
  does not mean the mutant admits a bad document (another rule may still
  refuse it), and it does not say which rule produced which error: a second
  edit that adds an equal error at the same (keyword, path) keeps the count
  and goes unnoticed (Astra 0c-repair re-review, BLOCK 3). The decision-
  receipt audit negatives are of this kind, because their guards overlap by
  design, and so are the bare-identity and unreadable-response regressions.
  Where the members can be removed one at a time, an isolated negative backs
  the combined one; the identity members are, and the review's compensated
  mutant is in the inventory to show it is now refused.

Neither kind proves the rule is the right one, and these tests read no
runtime behaviour.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "tools" / "check_gen2_schemas.py"
SCHEMAS = REPO / "gen2" / "schema"
# The checker imports gen2.core.instants; a temp root holds only the schemas.
ENV = {**os.environ, "PYTHONPATH": str(REPO)}

# Module globals: tools/gen2_mutations.py points one at a mutated copy.
EXPORT_BUNDLE_SCHEMA = SCHEMAS / "export-bundle.schema.json"
EXPORT_RECEIPT_SCHEMA = SCHEMAS / "export-delivery-receipt.schema.json"
EXPORT_MANIFEST_SCHEMA = SCHEMAS / "export-manifest.schema.json"
FRESHNESS_SCHEMA = SCHEMAS / "freshness-envelope.schema.json"
COMMON_SCHEMA = SCHEMAS / "common.schema.json"
DECISION_RECEIPT_SCHEMA = SCHEMAS / "decision-receipt.schema.json"
INVOCATION_SCHEMA = SCHEMAS / "invocation.schema.json"
EXECUTION_RECORD_SCHEMA = SCHEMAS / "execution-record.schema.json"
OVERRIDES = {
    "EXPORT_BUNDLE_SCHEMA": "export-bundle.schema.json",
    "EXPORT_RECEIPT_SCHEMA": "export-delivery-receipt.schema.json",
    "EXPORT_MANIFEST_SCHEMA": "export-manifest.schema.json",
    "FRESHNESS_SCHEMA": "freshness-envelope.schema.json",
    "COMMON_SCHEMA": "common.schema.json",
    "DECISION_RECEIPT_SCHEMA": "decision-receipt.schema.json",
    "INVOCATION_SCHEMA": "invocation.schema.json",
    "EXECUTION_RECORD_SCHEMA": "execution-record.schema.json",
}
FAILURE = re.compile(r"^SCHEMA CHECK FAILURE: (\S+?): (.*)$")


class FixtureCounterfactualTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(SCHEMAS, root / "gen2" / "schema")
            (root / "docs" / "gen2").mkdir(parents=True)
            shutil.copyfile(REPO / "docs" / "gen2" / "BOUNDARIES.md", root / "docs" / "gen2" / "BOUNDARIES.md")
            for name, filename in OVERRIDES.items():
                shutil.copyfile(globals()[name], root / "gen2" / "schema" / filename)
            result = subprocess.run([sys.executable, str(CHECKER), "--root", str(root), "--part", "schemas"],
                                    capture_output=True, text=True, timeout=120, env=ENV)
        cls.failures: dict[str, list[str]] = {}
        for line in result.stderr.splitlines():
            match = FAILURE.match(line)
            if match:
                cls.failures.setdefault(match.group(1), []).append(match.group(2))
        broken = {path: why for path, why in cls.failures.items() if "/examples/" not in path}
        if broken or (result.returncode != 0 and not cls.failures):
            # A mutant that breaks a schema file itself is not a rule removal:
            # erroring here makes the harness report it INVALID, never KILLED.
            raise RuntimeError(f"the schema tree does not load: {broken or result.stderr[-2000:]}")

    def assertBehaveAsDeclared(self, schema: str, *fixtures: str) -> None:
        for fixture in fixtures:
            path = f"gen2/schema/examples/{schema}/{fixture}"
            self.assertNotIn(path, self.failures, msg=f"{path}: {self.failures.get(path)}")

    # --- export-bundle: a mixed disposition names its adjudication holds (A3, C1)
    def test_a_mixed_disposition_without_its_hold_list_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-bundle", "valid-completed-topic.json",
                                    "invalid-mixed-disposition-without-an-adjudication-item.json")

    def test_a_mixed_disposition_with_an_empty_hold_list_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-bundle", "valid-completed-topic.json",
                                    "invalid-mixed-disposition-with-an-empty-adjudication-list.json")


    # --- export-delivery-receipt: the status says what is known about the
    # sink (A2), and a partial write is a partial count (A4)
    def test_a_partial_write_claiming_an_observed_total_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-delivery-receipt", "valid-partial-write-failed.json",
                                    "invalid-partial-write-claiming-an-observed-total.json")

    def test_a_failure_whose_count_is_unknown_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-delivery-receipt", "valid-webhook-known-refusal.json",
                                    "invalid-ambiguous-post-send-recorded-as-a-failure.json")

    def test_a_refusal_claiming_it_wrote_records_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-delivery-receipt", "valid-webhook-known-refusal.json",
                                    "invalid-refusal-claiming-it-wrote-records.json")

    def test_an_unreadable_response_is_not_a_failure_class(self) -> None:
        self.assertBehaveAsDeclared("export-delivery-receipt", "valid-webhook-known-refusal.json",
                                    "invalid-unreadable-response-as-an-error-class.json")

    def test_the_reviews_unreadable_response_reproduction_is_refused_twice(self) -> None:
        self.assertBehaveAsDeclared("export-delivery-receipt", "valid-partial-write-failed.json",
                                    "invalid-unreadable-response-recorded-as-a-settled-failure.json")

    def test_an_unknown_outcome_without_a_cause_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-delivery-receipt", "valid-webhook-ambiguous-post-send.json",
                                    "invalid-outcome-unknown-without-a-cause.json")

    def test_a_settled_result_carrying_an_unknown_cause_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-delivery-receipt", "valid-webhook-known-refusal.json",
                                    "invalid-settled-result-carrying-an-unknown-cause.json")

    # --- export-manifest/2: the one outbound manifest (task 0d, operator ruling
    # 2026-09-26). Every rule publication-manifest/1 and export-manifest/1 held
    # keeps an isolated negative here; the connector vocabulary is closed.
    def test_an_undeclared_connector_type_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-manifest", "valid-correction-generation-2.json", "invalid-undeclared-connector-type.json")

    def test_an_extension_connector_without_its_implementation_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-manifest", "valid-superseding-options-revision-2.json",
                                    "invalid-extension-without-an-implementation.json")

    # Per member (0d-repair; Astra 0d review finding 2): the whole-object
    # negative above survives dropping either member from `required`, so each
    # member has its own one-error negative; the valid extension is the control.
    def test_an_extension_implementation_names_its_module(self) -> None:
        self.assertBehaveAsDeclared("export-manifest", "valid-superseding-options-revision-2.json",
                                    "invalid-extension-implementation-without-its-module.json")

    def test_an_extension_implementation_names_its_review(self) -> None:
        self.assertBehaveAsDeclared("export-manifest", "valid-superseding-options-revision-2.json",
                                    "invalid-extension-implementation-without-its-review.json")

    def test_a_reference_connector_claiming_an_implementation_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-manifest", "valid-superseding-options-revision-2.json",
                                    "invalid-reference-connector-claiming-an-implementation.json")

    def test_a_connector_id_that_cannot_spell_its_variable_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-manifest", "valid-first-export-generation-3.json", "valid-single-character-connector-id.json",
                                    "invalid-connector-id-that-cannot-spell-its-variable.json")

    def test_an_export_for_no_connector_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-manifest", "valid-first-export-generation-3.json", "invalid-export-with-no-connectors.json")

    def test_an_export_without_an_approval_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-manifest", "valid-correction-generation-2.json", "invalid-export-without-an-approval.json")

    def test_a_first_manifest_with_tombstones_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-manifest", "valid-first-export-generation-3.json", "invalid-first-export-with-tombstones.json")

    def test_generation_1_supersedes_only_generation_1(self) -> None:
        """Both directions: generation 1 superseding generation 2 is refused,
        and generation 1 superseding its own lower options revision is not (the
        retired publication rule, 'generation 1 supersedes nothing', would
        refuse that re-export)."""
        self.assertBehaveAsDeclared("export-manifest", "valid-generation-1-options-revision-2.json",
                                    "invalid-generation-1-superseding-a-later-generation.json")

    def test_a_supersession_names_its_whole_pair(self) -> None:
        self.assertBehaveAsDeclared("export-manifest", "valid-correction-generation-2.json",
                                    "invalid-supersedes-without-its-options-revision.json")

    def test_delivery_state_is_not_a_manifest_field(self) -> None:
        self.assertBehaveAsDeclared("export-manifest", "valid-correction-generation-2.json", "invalid-delivery-state-in-manifest.json")

    def test_the_retired_publication_manifest_version_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-manifest", "valid-completion-generation-1.json",
                                    "invalid-retired-publication-manifest-version.json")

    # --- freshness-envelope/2: engine reads are served from the local record,
    # and the three facts stay separate (task 0d re-scope).
    def test_complete_export_delivery_needs_every_connector_delivered(self) -> None:
        self.assertBehaveAsDeclared("freshness-envelope", "valid-partial-export-delivery.json", "invalid-complete-with-a-failed-connector.json")

    def test_a_delivered_connector_names_its_pair(self) -> None:
        self.assertBehaveAsDeclared("freshness-envelope", "valid-partial-export-delivery.json", "invalid-delivered-without-a-pair.json")

    # The null-pair negative above survives dropping either pair member from
    # `required` (0d-repair; Astra 0d review finding 2): each member has its
    # own negative, and the complete pair in the valid fixture is the control.
    def test_a_delivered_pair_names_its_options_revision(self) -> None:
        self.assertBehaveAsDeclared("freshness-envelope", "valid-partial-export-delivery.json",
                                    "invalid-delivered-pair-without-its-options-revision.json")

    def test_a_delivered_pair_names_its_generation(self) -> None:
        self.assertBehaveAsDeclared("freshness-envelope", "valid-partial-export-delivery.json",
                                    "invalid-delivered-pair-without-its-generation.json")

    def test_a_read_cannot_claim_a_projected_revision(self) -> None:
        self.assertBehaveAsDeclared("freshness-envelope", "valid-partial-export-delivery.json", "invalid-projected-revision-claimed.json")

    def test_a_read_cannot_claim_mixed_generation(self) -> None:
        """The other retired /1 field (0d-repair; Astra 0d review finding 2):
        the projected-revision negative says nothing about it. Two shapes, so
        restoring the field as a bare flag or as /1 defined it are both
        noticed."""
        self.assertBehaveAsDeclared("freshness-envelope", "valid-partial-export-delivery.json",
                                    "invalid-mixed-generation-claimed.json", "invalid-mixed-generation-as-in-envelope-1.json")

    def test_no_connectors_lists_none(self) -> None:
        self.assertBehaveAsDeclared("freshness-envelope", "valid-no-connectors-enabled.json", "invalid-no-connectors-listing-one.json")

    def test_a_delivery_status_is_about_at_least_one_connector(self) -> None:
        self.assertBehaveAsDeclared("freshness-envelope", "valid-partial-export-delivery.json",
                                    "invalid-partial-delivery-listing-no-connector.json")

    def test_nothing_approved_means_nothing_served(self) -> None:
        self.assertBehaveAsDeclared("freshness-envelope", "valid-partial-export-delivery.json", "invalid-served-without-an-approval.json")

    def test_completion_is_at_a_dossier_revision(self) -> None:
        self.assertBehaveAsDeclared("freshness-envelope", "valid-partial-export-delivery.json", "invalid-completed-without-dossier.json")

    def test_an_overdue_feed_is_not_current(self) -> None:
        self.assertBehaveAsDeclared("freshness-envelope", "valid-dead-feed-degraded.json", "invalid-current-with-overdue-feed.json")

    def test_degraded_currency_names_a_feed(self) -> None:
        self.assertBehaveAsDeclared("freshness-envelope", "valid-early-feed-failure-degraded.json", "invalid-degraded-without-reason.json")

    def test_feed_issue_reasons_are_closed(self) -> None:
        self.assertBehaveAsDeclared("freshness-envelope", "valid-early-feed-failure-degraded.json", "invalid-unlisted-feed-reason.json")

    # --- the 0c-repair audit: 0a negatives whose one declared signature hid
    # two or three errors. Now counted, each rule's removal is noticed.
    def test_an_abstention_that_discards_its_raw_artifact_is_refused_by_both_rules(self) -> None:
        self.assertBehaveAsDeclared("decision-receipt", "valid-truncated-input-abstains.json",
                                    "invalid-abstention-discards-raw-artifact.json")

    def test_a_shadow_receipt_with_a_commit_is_refused_by_both_rules(self) -> None:
        self.assertBehaveAsDeclared("decision-receipt", "valid-jev-screening-shadow.json",
                                    "invalid-shadow-with-commit-effect.json")

    def test_a_bare_process_identity_is_refused_three_times(self) -> None:
        self.assertBehaveAsDeclared("invocation", "valid-research-pass-running.json", "invalid-bare-identity.json")

    # --- per-member identity coverage (Astra 0c-repair re-review BLOCK 3): the
    # count above cannot tell the three missing members apart, so each has its
    # own negative with one error.
    def test_a_process_identity_without_its_host_is_refused(self) -> None:
        self.assertBehaveAsDeclared("invocation", "valid-research-pass-running.json",
                                    "invalid-identity-without-host-id.json")

    def test_a_process_identity_without_its_boot_id_is_refused(self) -> None:
        self.assertBehaveAsDeclared("invocation", "valid-research-pass-running.json",
                                    "invalid-identity-without-boot-id.json")

    def test_a_process_identity_without_its_start_fingerprint_is_refused(self) -> None:
        self.assertBehaveAsDeclared("invocation", "valid-research-pass-running.json",
                                    "invalid-identity-without-start-fingerprint.json")

    # --- task 1c: an invocation's failure record, and the supervisor's execution record (isolated negatives)
    def test_a_failed_invocation_carries_its_failure_record(self) -> None:
        self.assertBehaveAsDeclared("invocation", "valid-failed-empty-output.json", "invalid-failed-without-a-failure-record.json")

    def test_only_a_failed_invocation_carries_a_failure_record(self) -> None:
        self.assertBehaveAsDeclared("invocation", "valid-research-pass-running.json", "invalid-failure-record-on-running-work.json")

    def test_a_failure_class_is_a_structural_finding(self) -> None:
        self.assertBehaveAsDeclared("invocation", "valid-failed-empty-output.json", "invalid-failure-class-from-the-agent.json")

    def test_collected_output_names_its_hash(self) -> None:
        self.assertBehaveAsDeclared("execution-record", "valid-exited-with-output.json", "invalid-present-output-without-its-hash.json")

    def test_output_not_collected_names_no_hash(self) -> None:
        self.assertBehaveAsDeclared("execution-record", "valid-empty-output-despite-self-report.json", "invalid-absent-output-with-a-hash.json")

    def test_findings_are_structural_classes(self) -> None:
        self.assertBehaveAsDeclared("execution-record", "valid-empty-output-despite-self-report.json", "invalid-self-report-as-a-finding.json")

    def test_a_group_termination_records_its_reason(self) -> None:
        self.assertBehaveAsDeclared("execution-record", "valid-never-started.json", "invalid-termination-without-a-reason.json")

    def test_terminated_descendants_are_counted(self) -> None:
        self.assertBehaveAsDeclared("execution-record", "valid-exited-with-output.json", "invalid-descendants-terminated-none.json")

    def test_an_exit_is_a_code_or_a_signal(self) -> None:
        self.assertBehaveAsDeclared("execution-record", "valid-exited-with-output.json", "invalid-exit-with-code-and-signal.json")


if __name__ == "__main__":
    unittest.main()
