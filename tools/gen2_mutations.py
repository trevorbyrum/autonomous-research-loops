#!/usr/bin/env python3
"""Mutation harness for the gen-2 store DDL and its connection contract.

Each mutation below removes or weakens exactly one guard in memory (never on
disk), reruns the guard's declared killer tests and its paired controls
against the mutant, and checks that the killers catch it while the controls
still pass:

  KILLED    every test listed in `killers` fails, and every paired control
            passes. A failure is an assertion failure, or an
            sqlite3.IntegrityError raised in a test body outside setUp (a
            write the test expects to succeed was refused, i.e. the mutant
            over-restricts);
  SURVIVED  no killer fails — the guard is untested;
  INVALID   the mutation text was not found exactly once, a listed killer
            did not fail, a paired control did not pass (it failed, erred,
            was skipped or did not run), or tests errored (setup broke
            rather than an assertion catching the mutant) while some listed
            killer did not fail in its own body. Setup errors elsewhere are
            reported but tolerated when every listed killer failed in its
            body: an over-restricting mutant can also break a shared fixture.

Children (task 1c; attestation task 1c-repair, Astra 1c review C1). A
Python-module or disk target is also written into a temporary copy of the
gen2/ tree, named in GEN2_CHILD_ROOT for the run of its killers; children
started through gen2/tests/children.py import that tree alone (their import
root is fixed there, whatever working directory a caller passes). The copy
written there carries a one-line prologue: a child that executes it appends
an attestation — the test running (GEN2_ATTEST_TEST, set as each test
starts), its pid, the file, the SHA-256 of the file's bytes — to the run's
attestation file. What is checked:
  * before the killers, for a module target, a probe child started through
    the helper imports the module and must attest exactly the mutant's
    bytes (the loading control; a disk target, a script only children run,
    is checked on the killers' own children below);
  * after the killers, every attestation must name the tree's copy and the
    mutant's bytes: a child that executed other bytes of the target makes
    the mutation INVALID;
  * a kill that rests on a child — every disk target, and a module target
    marked via_child — needs, for each declared killer, an attestation from
    a child that executed the mutant during that very test; a killer that
    failed without one is not credited (INVALID).
An in-process kill needs none: the killers run in this interpreter over the
in-memory mutant. What this does not cover: a child that executes the target
and dies before its prologue runs, and tools run by explicit path ("attr"
targets), which are handed the mutated copy by path. `--no-disk` turns the
child tree off, to show what an in-memory-only run misses.

Which tests run (task 1c-repair, runtime; task 1c-repair-2 C4, Astra 1c
re-review C4): per mutant, its declared killers, which must fail, and its
paired controls, which must pass — kept apart, because a control is not
expected to fail. The controls come from tools/gen2_mutation_controls.json:
tests that are not the mutant's killers and that, in a traced unmutated run,
took an accepted path through the code the mutant changes (that tool's
docstring says what counts: for Python, a changed line itself, or the guard
directly governing a changed statement, passed where the change is a
refusal — never a branch enclosing the guard; task 1c-repair-3). A control
passing under the mutant shows the mutant left that path working; it does
not by itself show why a killer failed (that tool's docstring, "What the
rule establishes"). A killer is not assumed to hold its own accepted
case: some do, many do not. Where only a killer takes that path, the file
may instead credit the killer with its own accepted case, read and recorded
as running under the mutant too (in_killer). A mutant with no entry
in that file, a killer or control name that does not resolve to exactly one
test, a test that is both, or an in_killer test that is not its killer stops
the run; a mutant with neither is listed in the file with its reason, and
the run names it. Controls that rest
on a child (a disk target's) need a child's attestation, as killers do.
Other tests do not run under a mutant: what they would have observed is not
evidence for it (broader discovery is a separate run when the mapping
changes). The unmutated baselines run once per loading mode, not once per
target: the whole store suite (the DDL and connection mutants' baseline,
their controls included); every module and disk target's killers and
controls together over one unmutated child tree; and each path-handed
("attr") target's killers and controls over its own unmutated copy. The
whole unmutated suite runs once per build, in make gen2-test. Workers are
bounded (default: one fewer than the cores, a core left for the children the
killers start), and each verdict is printed as its worker finishes; no test
timeout is changed. How long a run takes depends on the host's load and is
not a property of the inventory: recorded runs of the same inventory before
the controls took 434 s on an idle host and 737 s and 1,219 s under load.

Exit 0 only if the unmutated baselines pass and every mutation is KILLED.
The inventory is the reviewable claim: Astra's Gate C re-runs it
(`make gen2-mutation`) instead of trusting a count. A kill proves the named
tests notice the guard's absence; it does not prove the guard is the right
rule.

Trace: task 0a-repair ("every fix must be independently mutation-testable");
Astra 0a review, "Independent mutation record".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import re
import sqlite3
import sys
import time
import traceback
import unittest
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "gen2" / "tests"
CONTROLS_FILE = ROOT / "tools" / "gen2_mutation_controls.json"  # written by tools/gen2_mutation_controls.py


@dataclass(frozen=True)
class Mutation:
    mid: str
    finding: str
    description: str
    killers: tuple[str, ...]
    drop_trigger: str | None = None
    old: str | None = None
    new: str = ""
    target: str = "ddl"  # ddl | connection | a repo-relative file in FILE_TARGETS
    also: tuple[tuple[str, str], ...] = ()  # further (old, new) edits applied with this one (a dimension-level mutation)
    scope: str | None = None  # apply the edits only inside this trigger or table (CREATE TRIGGER <scope> ... END; / CREATE TABLE <scope> ... STRICT;)
    via_child: bool = False  # a module target whose kill rests on a child: each killer needs a child's attestation (module docstring, "Children")


# File targets: how the named tests are pointed at a mutated copy. ("attr",
# module, name): the file is written to a temp dir and module.name is set to
# its path (tests that run tools as subprocesses or read config files);
# ("module", dotted): the mutated source is loaded as that module and the
# killer test modules are reloaded so their imports rebind to it, and it is
# also written into the child tree (module docstring, "Children");
# ("disk",): a file only children run (a script started by path); the
# mutant exists only in the child tree.
FILE_TARGETS = {
    "tools/check_boundaries.py": ("attr", "test_check_boundaries", "CHECKER"),
    "gen2/boundaries.toml": ("attr", "test_check_boundaries", "REAL_BOUNDARIES"),
    "tools/check_gen2_schemas.py": ("attr", "test_check_ddl_rules", "CHECKER"),
    "gen2/core/instants.py": ("module", "gen2.core.instants"),
    "gen2/core/canonical.py": ("module", "gen2.core.canonical", "gen2.router.boundary", "gen2.router.lifecycle", "gen2.router.registries", "gen2.router.amendments",
                               "gen2.router.scheduling", "gen2.router.service", "gen2.tests.router_fixtures"),
    "gen2/store/compat.py": ("module", "gen2.store.compat"),
    "gen2/store/db.py": ("module", "gen2.store.db"),
    "gen2/store/api.py": ("module", "gen2.store.api"),
    "gen2/importer/dry_run.py": ("module", "gen2.importer.dry_run"),
    "gen2/importer/__main__.py": ("disk",),  # `python -m gen2.importer` runs it; only children do
    # task 1c. A supervisor module's dependents are reloaded over the mutant; jobshim.py runs only in children.
    "gen2/router/lifecycle.py": ("module", "gen2.router.lifecycle", "gen2.router.scheduling", "gen2.router.service", "gen2.tests.router_fixtures"),
    "gen2/supervisor/spool.py": ("module", "gen2.supervisor.spool", "gen2.supervisor.supervisor", "gen2.tests.supervisor_fixtures"),
    "gen2/supervisor/jobs.py": ("module", "gen2.supervisor.jobs", "gen2.supervisor.supervisor", "gen2.tests.supervisor_fixtures"),
    "gen2/supervisor/supervisor.py": ("module", "gen2.supervisor.supervisor", "gen2.app.station", "gen2.tests.supervisor_fixtures"),
    "gen2/supervisor/jobshim.py": ("disk",),
    "gen2/schema/execution-record.schema.json": ("attr", "test_schema_counterfactuals", "EXECUTION_RECORD_SCHEMA"),
    # task 1b. A router module's dependents (named after the dotted module) are
    # reloaded over the mutant, in order, before the killers are.
    "gen2/router/service.py": ("module", "gen2.router.service", "gen2.tests.router_fixtures"),
    "gen2/router/boundary.py": ("module", "gen2.router.boundary", "gen2.router.lifecycle", "gen2.router.registries", "gen2.router.amendments",
                                "gen2.router.scheduling", "gen2.router.service", "gen2.tests.router_fixtures"),
    "gen2/router/schemas.py": ("attr", "test_router_schemas", "VALIDATOR"),  # the oracle tool loads the mutated copy
    # task 1d: the router's mixins (their dependents reloaded after them), and the composition root
    "gen2/router/registries.py": ("module", "gen2.router.registries", "gen2.router.service", "gen2.app.station", "gen2.tests.router_fixtures"),
    "gen2/router/amendments.py": ("module", "gen2.router.amendments", "gen2.router.service", "gen2.tests.router_fixtures"),
    "gen2/router/scheduling.py": ("module", "gen2.router.scheduling", "gen2.router.service", "gen2.tests.router_fixtures"),
    "gen2/app/station.py": ("module", "gen2.app.station"),
    "tools/gen2_trigger_order.py": ("attr", "test_trigger_order_tool", "TOOL"),
    "tools/gen_source_catalog.py": ("attr", "test_source_catalog", "TOOL"),
    # A schema file: the whole schema tree is re-checked with this file replaced (0c-repair, C1).
    "gen2/schema/export-bundle.schema.json": ("attr", "test_schema_counterfactuals", "EXPORT_BUNDLE_SCHEMA"),
    "gen2/schema/export-delivery-receipt.schema.json": ("attr", "test_schema_counterfactuals", "EXPORT_RECEIPT_SCHEMA"),
    "gen2/schema/export-manifest.schema.json": ("attr", "test_schema_counterfactuals", "EXPORT_MANIFEST_SCHEMA"),
    "gen2/schema/freshness-envelope.schema.json": ("attr", "test_schema_counterfactuals", "FRESHNESS_SCHEMA"),
    "gen2/schema/common.schema.json": ("attr", "test_schema_counterfactuals", "COMMON_SCHEMA"),
    "gen2/schema/decision-receipt.schema.json": ("attr", "test_schema_counterfactuals", "DECISION_RECEIPT_SCHEMA"),
    "gen2/schema/invocation.schema.json": ("attr", "test_schema_counterfactuals", "INVOCATION_SCHEMA"),
}

H = "test_store_history."
D = "test_store_ddl."
FI = "test_store_ddl.FacetImportanceTest."
AD = "test_store_ddl.AdmissionAndLeaseTest."
IL = "test_store_ddl.InvocationLifecycleTest."
VT = "test_store_ddl.VerificationTest."
CS = "test_store_ddl.ContractAdmittedSupportTest."
LT = "test_store_ddl.InvocationLifecycleTest."
DC = "test_store_ddl.DecisionReceiptConsistencyTest."
SD = "test_store_ddl.ScreeningAndDecisionTest."
OB = "test_store_ddl.ObservationTest."
VO = "test_store_ddl.DraftVocabularyTransitionTest."
CB = "test_check_boundaries.BoundaryCheckerTest."
DR = "test_check_ddl_rules.DdlRuleTest."
IN = "test_instants.UtcInstantTest."
CN = "test_canonical."
RI = "test_store_history.RecordIdentityTest."
EX = "test_store_examples.ExampleWorldTest."
CG = "test_store_ddl.ContractGovernanceTest."
SG = "test_sqlite_gate."
IB = "test_store_intake.IntakeBriefTest."
SC = "test_source_catalog.CatalogToolTest."
SF = "test_schema_counterfactuals.FixtureCounterfactualTest."
X = "ExportOutboxTest."
RC = "test_router_commit."
RO = "test_router_ops."
RE = "test_router_evidence."
RX = "test_router_crash."
RS = "test_router_schemas."
RT = "test_router_time."
RR = "test_router_restart."
SVC = "gen2/router/service.py"
LIF = "gen2/router/lifecycle.py"
SPV = "gen2/supervisor/supervisor.py"
SPL = "gen2/supervisor/spool.py"
JBS = "gen2/supervisor/jobs.py"
ER = "gen2/schema/execution-record.schema.json"
INV = "gen2/schema/invocation.schema.json"
SS = "test_store_supervision."
LC = "test_router_lifecycle."
SP = "test_supervisor_spool."
SJ = "test_supervisor_jobs."
SLR = "test_supervisor_lifecycle.ResearchPassLifecycleTest."
SLD = "test_supervisor_lifecycle.DelegateLifecycleTest."
SCD = "test_supervisor_crash.DiscoveryCrashTest."
SCP = "test_supervisor_crash.DelegateCrashTest."
SDR = "test_supervisor_delegates.ResearchPassParentTest."
SBR = "test_supervisor_budgets.ResearchPassBudgetTest."
SBD = "test_supervisor_budgets.DelegateBudgetTest."
SDD = "test_supervisor_delegates.DiscoveryParentTest."
SSR = "test_supervisor_serialization.ResearchPassSerializedTest."
SSD = "test_supervisor_serialization.DiscoverySerializedTest."
SSB = "test_supervisor_serialization.BackstopAndCrashTest."
BND = "gen2/router/boundary.py"
# task 1d
REG, AMD, SCH, APP = "gen2/router/registries.py", "gen2/router/amendments.py", "gen2/router/scheduling.py", "gen2/app/station.py"
RG, AM, SQ, SR = "test_router_registries.", "test_router_amendments.", "test_router_scheduling.", "test_store_registries."
STC = "test_station_config.PinnedPolicyTest."
# task 1d-repair (Astra 1d review): the station's restart and scheduling cases, and re-queues through the supervisor
STR, STS, SRQ = "test_station_config.RestartPolicyTest.", "test_station_config.StationSchedulingTest.", "test_supervisor_requeue."
RECEIPT = "gen2/schema/export-delivery-receipt.schema.json"
MANIFEST = "gen2/schema/export-manifest.schema.json"
ENVELOPE = "gen2/schema/freshness-envelope.schema.json"
IDENTITY = ("job_handle", "host_id", "container_id", "boot_id", "start_fingerprint")
IDENTITY_KILLER = {  # each identity member's own one-error negative (0c-repair-2)
    "host_id": "test_a_process_identity_without_its_host_is_refused",
    "boot_id": "test_a_process_identity_without_its_boot_id_is_refused",
    "start_fingerprint": "test_a_process_identity_without_its_start_fingerprint_is_refused",
}

MUTATIONS: list[Mutation] = [
    # --- A1: history cannot be rewritten ------------------------------------
    Mutation("A1-recursive-triggers-off", "A1", "connection contract omits recursive_triggers (REPLACE skips delete guards)",
             (H + "ReplaceAndDeleteTest.test_replace_cannot_rewrite_a_receipt_on_any_key",
              H + "ConnectionContractTest.test_connection_contract_reads_back_on",
              D + "CommitFencingTest.test_operation_id_reuse_rejected_and_receipts_immutable"),
             target="connection", old="PRAGMA recursive_triggers = ON;\n"),
    Mutation("A1-receipt-delete-guard", "A1", "drop operation_receipts delete guard",
             (H + "ReplaceAndDeleteTest.test_replace_cannot_rewrite_a_receipt_on_any_key",
              D + "CommitFencingTest.test_operation_id_reuse_rejected_and_receipts_immutable",
              H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into"),
             drop_trigger="operation_receipts_immutable_d"),
    Mutation("A1-connector-watermark-delete-guard", "A1", "drop connector_watermarks delete guard (carries the sink-watermark case, 0d)",
             (H + "ReplaceAndDeleteTest.test_connector_watermark_cannot_regress_by_delete_reinsert_or_replace",
              D + "ExportOutboxTest.test_connector_watermark_never_regresses"),
             drop_trigger="connector_watermarks_no_delete"),
    Mutation("A1-review-trigger-delete-guard", "A1", "drop review_triggers delete guard",
             (H + "ReplaceAndDeleteTest.test_handled_trigger_replayed_after_its_episode_closed_stays_handled",
              D + "OrdinalAndTriggerTest.test_trigger_identity_unique_and_handled_is_final"),
             drop_trigger="review_triggers_no_delete"),
    Mutation("A1-contract-delete-guard", "A1", "drop contract_revisions delete guard",
             (H + "ReplaceAndDeleteTest.test_update_or_replace_cannot_delete_the_approved_contract",
              D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted"),
             drop_trigger="contract_no_delete"),
    Mutation("A1-queue-delete-guard", "A1", "drop queue_entries delete guard",
             (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="queue_entries_no_delete"),
    Mutation("A1-works-delete-guard", "A1", "drop works delete guard",
             (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="works_no_delete"),
    Mutation("A1-record-work-links-delete-guard", "A1", "drop record_work_links delete guard",
             (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="record_work_links_no_delete"),
    Mutation("A1-claim-source-links-delete-guard", "A1", "drop claim_source_links delete guard",
             (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="claim_source_links_no_delete"),
    Mutation("A1-quote-checks-delete-guard", "A1", "drop quote_checks delete guard",
             (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="quote_checks_no_delete"),
    Mutation("A1-delivery-receipts-delete-guard", "A1", "drop export_delivery_receipts delete guard",
             (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="export_delivery_receipts_no_delete"),
    *(Mutation(f"A1-append-only-update-{trigger}", "A1", f"drop UPDATE guard {trigger}",
               (H + "EveryTableSweepTest.test_append_only_tables_reject_every_update",), drop_trigger=trigger)
      for trigger in ("artifacts_immutable_u", "audit_events_append_only_u", "claim_source_links_immutable_u",
                      "decision_receipts_immutable_u", "decision_specs_immutable_u", "dossiers_immutable_u",
                      "invocation_transitions_append_only_u", "obligations_immutable", "operation_receipts_immutable_u",
                      "operator_decisions_immutable_u", "outbox_events_immutable_u", "quote_checks_immutable_u",
                      "record_work_links_immutable_u", "research_ordinals_immutable_u", "retrieval_events_immutable_u",
                      "screening_assessments_immutable_u", "search_observations_immutable_u",
                      "export_delivery_receipts_immutable_u", "verification_receipts_immutable_u", "artifact_topics_immutable_u",
                      "questions_immutable_u", "reservation_draws_immutable_u", "amendment_impacts_immutable_u")),
    # --- A2: decisions bound to their exact subject ---------------------------
    # Each gate is mutated per binding dimension (naming, kind, disposition,
    # topic, subject, currency, protocol); each dimension has a near-miss probe
    # that differs from a valid decision only there. Where the schema makes
    # conjuncts mutually determined (a contract's topic/revision/hash via its
    # unique hash and the decision-time existence check) they are mutated
    # together as one dimension.
    Mutation("A2-queue-created-at-intake", "A2", "topics may be inserted in any status",
             (D + "ContractGovernanceTest.test_terminal_statuses_cannot_be_inserted",), drop_trigger="queue_entries_created_at_intake"),
    Mutation("A2-status-change-advances-revision", "A2", "status may change without a commit",
             (D + "ContractGovernanceTest.test_status_change_is_a_commit",), drop_trigger="queue_status_change_advances_revision"),
    Mutation("A2-status-decision-iff-gated", "A2", "status_decision_id no longer tied to decision-gated statuses",
             (D + "ContractGovernanceTest.test_status_change_is_a_commit",),
             old="\n  CHECK ((status IN ('completed_with_qualified_conclusions', 'retired')) = (status_decision_id IS NOT NULL)),", new=""),
    Mutation("A2-completion-naming", "A2", "completion accepts any valid approval, not the one named",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",), old="    WHERE d.decision_id = NEW.status_decision_id\n      AND d.topic_id = NEW.topic_id\n      AND d.kind = 'completion_approval'", new="    WHERE d.topic_id = NEW.topic_id\n      AND d.kind = 'completion_approval'"),
    Mutation("A2-completion-kind", "A2", "completion gate ignores decision kind",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",), old="      AND d.kind = 'completion_approval'\n", new=""),
    Mutation("A2-completion-disposition", "A2", "completion gate ignores disposition",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",), old="      AND d.kind = 'completion_approval'\n      AND d.disposition = 'approved'\n", new="      AND d.kind = 'completion_approval'\n"),
    Mutation("A2-completion-topic", "A2", "completion gate binds the dossier to the decision's topic, not the transition's",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",),
             old="    JOIN dossiers x ON x.topic_id = NEW.topic_id AND x.dossier_revision = d.subject_revision AND x.content_hash = d.subject_hash",
             new="    JOIN dossiers x ON x.topic_id = d.topic_id AND x.dossier_revision = d.subject_revision AND x.content_hash = d.subject_hash",
             also=(("    WHERE d.decision_id = NEW.status_decision_id\n      AND d.topic_id = NEW.topic_id\n      AND d.kind = 'completion_approval'", "    WHERE d.decision_id = NEW.status_decision_id\n      AND d.kind = 'completion_approval'"),)),
    Mutation("A2-completion-currency", "A2", "completion accepts an approval of a superseded dossier",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",),
             old="      AND x.dossier_revision = (SELECT max(y.dossier_revision) FROM dossiers y WHERE y.topic_id = NEW.topic_id)\n", new=""),
    Mutation("A2-completion-active-contract", "A2", "completion ignores which contract is active",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",), old="      AND x.contract_revision IS NEW.active_contract_revision\n", new=""),
    Mutation("A2-completion-contract-approved", "A2", "completion ignores whether the contract is approved",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",), old="      AND c.status = 'approved')\nBEGIN\n  SELECT RAISE(ABORT, 'completion requires", new=")\nBEGIN\n  SELECT RAISE(ABORT, 'completion requires"),
    Mutation("A2-retirement-naming", "A2", "retirement accepts any valid decision, not the one named",
             (D + "ContractGovernanceTest.test_retirement_needs_operator_decision",), old="    WHERE d.decision_id = NEW.status_decision_id\n      AND d.topic_id = NEW.topic_id\n      AND d.kind = 'retirement'", new="    WHERE d.topic_id = NEW.topic_id\n      AND d.kind = 'retirement'"),
    Mutation("A2-retirement-topic", "A2", "retirement ignores the decision's topic",
             (D + "ContractGovernanceTest.test_retirement_needs_operator_decision",), old="      AND d.topic_id = NEW.topic_id\n      AND d.kind = 'retirement'", new="      AND d.kind = 'retirement'"),
    Mutation("A2-retirement-kind", "A2", "retirement ignores decision kind",
             (D + "ContractGovernanceTest.test_retirement_needs_operator_decision",), old="      AND d.kind = 'retirement'\n", new=""),
    Mutation("A2-retirement-disposition", "A2", "retirement ignores disposition",
             (D + "ContractGovernanceTest.test_retirement_needs_operator_decision",), old="      AND d.kind = 'retirement'\n      AND d.disposition = 'approved'\n", new="      AND d.kind = 'retirement'\n"),
    Mutation("A2-retirement-state-revision", "A2", "a retirement decision about an earlier state is accepted (stale/reuse)",
             (D + "ContractGovernanceTest.test_retirement_needs_operator_decision",), old="\n      AND d.subject_revision = OLD.state_revision)", new=")"),
    Mutation("RA1-terminal-decision-pointer", "RA1", "the review's probe: a completed/retired topic's authorizing decision may be swapped or cleared without a status change",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier", D + "ContractGovernanceTest.test_retirement_needs_operator_decision"),
             drop_trigger="queue_status_decision_moves_with_status"),
    Mutation("RA1-pointer-moves-with-revision", "RA1", "advancing state_revision alone counts as the transition that may move the pointer",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier", D + "ContractGovernanceTest.test_retirement_needs_operator_decision"),
             scope="queue_status_decision_moves_with_status", old="AND NEW.status IS OLD.status", new="AND NEW.status IS OLD.status AND NEW.state_revision IS OLD.state_revision"),
    Mutation("A2-contract-created-as-draft", "A2", "contracts may be inserted approved",
             (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted",), drop_trigger="contract_created_as_draft"),
    Mutation("A2-contract-approval-naming", "A2", "contract approval accepts any valid approval, not the one named",
             (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted",), old="    WHERE d.decision_id = NEW.approved_by_decision_id\n", new="    WHERE 1\n"),
    Mutation("A2-contract-approval-kind", "A2", "contract approval ignores decision kind",
             (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted",), old="      AND d.kind IN ('contract_approval', 'amendment_approval', 'reframe_approval')\n", new=""),
    Mutation("A2-contract-approval-disposition", "A2", "contract approval ignores disposition",
             (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted",),
             old="      AND d.kind IN ('contract_approval', 'amendment_approval', 'reframe_approval')\n      AND d.disposition = 'approved'\n", new="      AND d.kind IN ('contract_approval', 'amendment_approval', 'reframe_approval')\n"),
    Mutation("A2-contract-approval-subject", "A2", "contract approval ignores subject topic/revision/hash",
             (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted",),
             old="      AND d.topic_id = NEW.topic_id\n      AND d.subject_revision = NEW.revision\n      AND d.subject_hash = NEW.content_hash)", new=")"),
    # --- RA2: a rating is exactly what the operator rated (facets and obligations alike) ---
    *(Mutation(f"RA2-{kind}-{key}", "RA2", f"{kind} rating: {desc}", (killer,), scope=f"{kind}s_rating_is_what_the_operator_rated", old=old, new=new)
      for kind, killer, subject in (("facet", FI + "test_facet_rating_bound_to_a_rating_decision", "facet_id"),
                                    ("obligation", D + "ContractGovernanceTest.test_operator_rating_bound_to_a_rating_decision", "obligation_id"))
      for key, desc, old, new in (
          ("naming", "any valid rating decision will do, not the one named", "  WHERE d.decision_id = NEW.operator_rating_decision_id\n", "  WHERE 1\n"),
          ("disposition", "a rejected rating decision authorizes", "AND d.kind = 'rating_approval' AND d.disposition = 'approved'", "AND d.kind = 'rating_approval'"),
          ("topic", "another topic's rating decision authorizes", "    AND d.topic_id = NEW.topic_id\n", ""),
          ("lineage", "the rated draft may be any revision, not an ancestor (unrelated draft; self-hash cycle)",
           "    AND d.subject_revision IN (\n          WITH RECURSIVE lineage(rev) AS (\n            SELECT parent_revision FROM contract_revisions WHERE topic_id = NEW.topic_id AND revision = NEW.contract_revision\n"
           "            UNION SELECT c.parent_revision FROM contract_revisions c JOIN lineage l ON c.topic_id = NEW.topic_id AND c.revision = l.rev)\n          SELECT rev FROM lineage)\n", ""),
          ("lineage-includes-self", "a decision about the revision carrying it counts (self-hash cycle)",
           "            SELECT parent_revision FROM contract_revisions WHERE topic_id = NEW.topic_id AND revision = NEW.contract_revision\n",
           "            SELECT revision FROM contract_revisions WHERE topic_id = NEW.topic_id AND revision = NEW.contract_revision\n"),
          ("payload-subject", "any rated entry of the payload stands for this one (a subject the operator did not rate)", f"    AND p.key = NEW.{subject}\n", ""),
          ("payload-band", "the band may differ from what the operator rated", "    AND json_extract(p.value, '$.band') IS NEW.operator_importance_band\n", ""),
          ("payload-score", "the score may differ from what the operator rated", "    AND json_extract(p.value, '$.score') IS NEW.operator_importance_score\n", ""),
          ("subject-definition", "the same id may carry a redefined subject", "\n    AND json_remove(he.value, '$.importance') IS json_remove(re.value, '$.importance'))", ")"),
          ("rated-draft", "the definition may be compared with any revision, not the rated draft",
           "    AND rated.topic_id = d.topic_id AND rated.revision = d.subject_revision\n", "    AND rated.topic_id = d.topic_id\n"))),
    Mutation("RA2-payload-only-on-rating-decisions", "RA2", "a rating decision may lack its payload, or another kind carry one",
             (D + "ContractGovernanceTest.test_only_a_rating_decision_carries_a_rating_payload",),
             old="  CHECK ((kind = 'rating_approval') = (payload IS NOT NULL)),\n", new=""),
    Mutation("RA2-payload-shape", "RA2", "a rating payload need not carry facet and obligation objects",
             (D + "ContractGovernanceTest.test_only_a_rating_decision_carries_a_rating_payload",),
             old="  CHECK (kind != 'rating_approval' OR (json_type(payload, '$.facets') IS 'object' AND json_type(payload, '$.obligations') IS 'object')),\n", new=""),
    Mutation("RA2-payload-of-its-draft", "RA2", "a rating payload may name subjects its draft does not have",
             (D + "ContractGovernanceTest.test_only_a_rating_decision_carries_a_rating_payload",), drop_trigger="operator_decisions_rating_payload_of_its_draft"),
    *(Mutation(f"RA2-payload-{key}", "RA2", desc, (D + "ContractGovernanceTest.test_only_a_rating_decision_carries_a_rating_payload",),
               scope="operator_decisions_rating_payload_of_its_draft", old=old, new=new)
      for key, desc, old, new in (
          ("facet-band", "a rated facet need not carry a band from the vocabulary",
           "             WHERE coalesce(json_extract(p.value, '$.band'), '') NOT IN ('critical', 'important', 'limited')\n                OR NOT EXISTS (SELECT 1 FROM contract_revisions c, json_each(c.document, '$.facet_map.facets') e",
           "             WHERE NOT EXISTS (SELECT 1 FROM contract_revisions c, json_each(c.document, '$.facet_map.facets') e"),
          ("obligation-band", "a rated obligation need not carry a band",
           "             WHERE coalesce(json_extract(p.value, '$.band'), '') NOT IN ('critical', 'important', 'limited')\n                OR NOT EXISTS (SELECT 1 FROM contract_revisions c, json_each(c.document, '$.obligations') e",
           "             WHERE NOT EXISTS (SELECT 1 FROM contract_revisions c, json_each(c.document, '$.obligations') e"),
          ("facet-in-draft", "a payload facet need not be a facet of the rated draft",
           "                                 AND json_extract(e.value, '$.facet_id') IS p.key))", "                                 AND 1))"),
          ("obligation-in-draft", "a payload obligation need not be an obligation of the rated draft",
           "                                 AND json_extract(e.value, '$.obligation_id') IS p.key)))", "                                 AND 1)))"))),
    # --- RA2-R: a contract's parent is a strictly earlier revision (proper ancestry) ---
    *(Mutation(f"RA2R-{key}", "RA2-R", desc, killers, scope="contract_revisions",
               old="\n  CONSTRAINT contract_parent_is_earlier CHECK (parent_revision IS NULL OR parent_revision < revision),", new=new)
      for key, desc, killers, new in (
          ("dropped", "the review's probe: a revision may be its own parent, a later revision's child, or on a cycle",
           (CG + "test_parent_is_a_strictly_earlier_revision", CG + "test_operator_rating_bound_to_a_rating_decision",
            FI + "test_facet_rating_bound_to_a_rating_decision", EX + "test_review_ra2r_self_parent_contract_cannot_rate_itself"), ""),
          ("self-parent", "a revision may name itself as its parent (the review's probe)",
           (CG + "test_parent_is_a_strictly_earlier_revision", CG + "test_operator_rating_bound_to_a_rating_decision",
            FI + "test_facet_rating_bound_to_a_rating_decision", EX + "test_review_ra2r_self_parent_contract_cannot_rate_itself"),
           "\n  CONSTRAINT contract_parent_is_earlier CHECK (parent_revision IS NULL OR parent_revision <= revision),"),
          ("only-self-excluded", "only self-parentage is refused: a later parent, and so a cycle, is admitted",
           (CG + "test_parent_is_a_strictly_earlier_revision", CG + "test_operator_rating_bound_to_a_rating_decision",
            FI + "test_facet_rating_bound_to_a_rating_decision"),
           "\n  CONSTRAINT contract_parent_is_earlier CHECK (parent_revision IS NULL OR parent_revision != revision),"))),
    Mutation("A2-proposal-receipt-class", "A2", "a Jev proposal may cite any decision class",
             (D + "ContractGovernanceTest.test_proposed_importance_cites_an_importance_receipt",), scope="obligations_proposal_cites_importance_receipt",
             old=" AND r.decision_class = 'importance_score')", new=")"),
    Mutation("A2-proposal-receipt-topic", "A2", "a Jev proposal may cite another topic's receipt",
             (D + "ContractGovernanceTest.test_proposed_importance_cites_an_importance_receipt",), scope="obligations_proposal_cites_importance_receipt",
             old="          AND r.topic_id = NEW.topic_id AND r.decision_class", new="          AND r.decision_class"),
    Mutation("A3-facet-band-score", "A3", "facet band/score consistency CHECK removed", (FI + "test_facet_rating_bound_to_a_rating_decision",), scope="facets",
             old="  CHECK (operator_importance_score IS NULL\n      OR (operator_importance_band = 'critical' AND operator_importance_score BETWEEN 7 AND 9)\n      OR (operator_importance_band = 'important' AND operator_importance_score BETWEEN 4 AND 6)\n      OR (operator_importance_band = 'limited' AND operator_importance_score BETWEEN 1 AND 3))",
             new="  CHECK (1)"),
    Mutation("A2-holds-created-open", "A2", "holds may be inserted cleared",
             (D + "HoldTest.test_holds_are_created_open",), drop_trigger="holds_created_open"),
    Mutation("A2-hold-clearance-naming", "A2", "a hold clears with any valid clearance, not the one named",
             (D + "HoldTest.test_operator_hold_cleared_only_by_operator_decision",), old="    WHERE d.decision_id = NEW.cleared_by_decision_id\n", new="    WHERE 1\n"),
    Mutation("A2-hold-clearance-kind", "A2", "hold clearance ignores decision kind",
             (D + "HoldTest.test_operator_hold_cleared_only_by_operator_decision",), old="      AND d.kind = 'hold_clearance' AND d.disposition = 'approved'\n      AND d.topic_id IS NEW.topic_id", new="      AND d.disposition = 'approved'\n      AND d.topic_id IS NEW.topic_id"),
    Mutation("A2-hold-clearance-disposition", "A2", "hold clearance ignores disposition",
             (D + "HoldTest.test_operator_hold_cleared_only_by_operator_decision",), old="      AND d.kind = 'hold_clearance' AND d.disposition = 'approved'\n      AND d.topic_id IS NEW.topic_id", new="      AND d.kind = 'hold_clearance'\n      AND d.topic_id IS NEW.topic_id"),
    Mutation("A2-hold-clearance-subject", "A2", "hold clearance ignores which hold (and so topic) it is about",
             (D + "HoldTest.test_operator_hold_cleared_only_by_operator_decision",), old="      AND d.topic_id IS NEW.topic_id\n      AND d.subject_ref = NEW.hold_id)", new=")"),
    Mutation("A2-publication-naming", "A2", "publication accepts any valid approval, not the one named",
             (D + "ExportOutboxTest.test_only_approved_work_is_exported",), old="  WHERE d.decision_id = NEW.approval_decision_id\n", new="  WHERE 1\n"),
    Mutation("A2-publication-kind", "A2", "publication ignores decision kind (the review's rating-decision probe)",
             (D + "ExportOutboxTest.test_only_approved_work_is_exported",), old="    AND d.kind = 'publication_approval' AND d.disposition = 'approved'\n", new="    AND d.disposition = 'approved'\n"),
    Mutation("A2-publication-disposition", "A2", "publication ignores disposition",
             (D + "ExportOutboxTest.test_only_approved_work_is_exported",), old="    AND d.kind = 'publication_approval' AND d.disposition = 'approved'\n", new="    AND d.kind = 'publication_approval'\n"),
    Mutation("A2-publication-topic", "A2", "publication ignores the approval's topic",
             (D + "ExportOutboxTest.test_only_approved_work_is_exported",), old="    AND d.topic_id = NEW.topic_id\n    AND d.subject_revision = NEW.source_revision", new="    AND d.subject_revision = NEW.source_revision"),
    Mutation("A2-publication-revision", "A2", "publication ignores the approved source revision",
             (D + "ExportOutboxTest.test_only_approved_work_is_exported",), old="    AND d.subject_revision = NEW.source_revision\n", new=""),
    Mutation("A2-publication-hash", "A2", "publication ignores the approved source hash",
             (D + "ExportOutboxTest.test_only_approved_work_is_exported",), old="\n    AND d.subject_hash = NEW.source_content_hash)", new=")"),
    *(Mutation(f"A2-manifest-binds-{key}", "A2", f"manifest JSON no longer bound to its {key} column",
               (D + "ExportOutboxTest.test_manifest_json_matches_its_columns",), old=f"\n     AND json_extract(manifest, '$.{path}') IS {col}", new="")
      for key, path, col in (("artifact-kind", "artifact_kind", "artifact_kind"), ("source-revision", "source.revision", "source_revision"),
                             ("source-hash", "source.content_hash", "source_content_hash"), ("approval-id", "approval.operator_decision_id", "approval_decision_id"),
                             ("approved-revision", "approval.approved_revision", "source_revision"), ("supersedes", "supersedes.generation", "supersedes_generation"),
                             # 0d: what export-manifest/2 adds to the stored manifest
                             ("generation", "generation", "generation"), ("options-revision", "options_revision", "options_revision"),
                             ("bundle-hash", "bundle.content_hash", "bundle_content_hash"),
                             ("supersedes-options-revision", "supersedes.options_revision", "supersedes_options_revision"))),
    Mutation("A2-manifest-binds-expected-connectors", "A2", "manifest JSON no longer bound to expected_connectors (carries expected_sinks, 0d)",
             (D + "ExportOutboxTest.test_manifest_json_matches_its_columns",), old="\n     AND json_extract(manifest, '$.expected_connectors') IS json(expected_connectors))", new=")"),
    Mutation("A2-subject-exists-contract", "A2", "a contract decision may name a nonexistent revision/hash",
             (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted",),
             old="WHEN (NEW.subject_kind = 'contract_revision' AND NOT EXISTS (\n        SELECT 1 FROM contract_revisions c\n        WHERE c.topic_id = NEW.topic_id AND c.revision = NEW.subject_revision AND c.content_hash = NEW.subject_hash))\n  OR ",
             new="WHEN "),
    Mutation("A2-subject-exists-dossier", "A2", "a completion decision may name a nonexistent dossier/hash",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",),
             old="  OR (NEW.subject_kind = 'dossier' AND NOT EXISTS (\n        SELECT 1 FROM dossiers x\n        WHERE x.topic_id = NEW.topic_id AND x.dossier_revision = NEW.subject_revision AND x.content_hash = NEW.subject_hash))\n", new=""),
    Mutation("A2-subject-exists-hold", "A2", "a clearance may name a nonexistent or other-topic hold",
             (D + "HoldTest.test_decision_subject_must_exist_with_its_topic",),
             old="  OR (NEW.subject_kind = 'hold' AND NOT EXISTS (\n        SELECT 1 FROM holds k WHERE k.hold_id = NEW.subject_ref AND k.topic_id IS NEW.topic_id))\n", new=""),
    Mutation("A2-subject-exists-decision-receipt", "A2", "a blind/advised record may name a nonexistent receipt",
             (D + "HoldTest.test_decision_subject_must_exist_with_its_topic",),
             old="  OR (NEW.subject_kind = 'decision_receipt' AND NOT EXISTS (\n        SELECT 1 FROM decision_receipts r WHERE r.decision_receipt_id = NEW.subject_ref AND r.topic_id = NEW.topic_id))\n", new=""),
    *(Mutation(f"A2-decision-shape-{key}", "A2", f"operator_decisions CHECK removed: {key}",
               (D + "HoldTest.test_decision_subject_shape",), old=old, new="")
      for key, old in (
          ("kind-subject-map", "\n  CHECK ((kind = 'brief_confirmation' AND subject_kind = 'intake_brief')\n      OR (kind = 'scope_approval' AND subject_kind = 'scoping_report')\n      OR (kind IN ('rating_approval', 'contract_approval', 'amendment_approval', 'reframe_approval') AND subject_kind = 'contract_revision')\n      OR (kind = 'completion_approval' AND subject_kind = 'dossier')\n      OR (kind = 'retirement' AND subject_kind = 'topic')\n      OR (kind = 'hold_clearance' AND subject_kind = 'hold')\n      OR (kind = 'publication_approval' AND subject_kind = 'publication_source')\n      OR (kind IN ('blind_initial_disposition', 'advised_feedback') AND subject_kind = 'decision_receipt')),"),
          ("versioned-subject", "\n  CHECK (subject_kind NOT IN ('intake_brief', 'scoping_report', 'contract_revision', 'dossier', 'publication_source')\n      OR (subject_revision IS NOT NULL AND subject_hash IS NOT NULL)),"),
          ("ref-is-topic", "\n  CHECK (subject_kind NOT IN ('contract_revision', 'dossier', 'topic') OR subject_ref IS topic_id),"),
          ("topic-revision", "\n  CHECK (subject_kind != 'topic' OR subject_revision IS NOT NULL),"),
          ("topic-scoped", "\n  CHECK (subject_kind = 'hold' OR topic_id IS NOT NULL),"),
          ("recorded-only-blind", ",\n  CHECK ((kind IN ('blind_initial_disposition', 'advised_feedback')) = (disposition = 'recorded'))"))),
    # --- A3: facet importance is its own record; G-3 gates approval ------------
    Mutation("A3-facet-document-binding", "A3", "facet rows no longer equal their document entry",
             (FI + "test_facet_row_must_equal_its_document_entry",), scope="facets_bound_to_document_and_decision",
             old="WHEN NOT EXISTS (", new="WHEN 0 AND NOT EXISTS ("),
    Mutation("A3-facet-proposal-class", "A3", "facet proposal may cite any decision class", (FI + "test_facet_proposal_cites_an_importance_receipt",),
             scope="facets_bound_to_document_and_decision", old=" AND r.decision_class = 'importance_score'))", new="))"),
    Mutation("A3-facet-proposal-topic", "A3", "facet proposal may cite another topic's receipt", (FI + "test_facet_proposal_cites_an_importance_receipt",),
             scope="facets_bound_to_document_and_decision", old="          AND r.topic_id = NEW.topic_id AND r.decision_class", new="          AND r.decision_class"),
    Mutation("A3-obligation-document-binding", "A3", "obligation rows no longer equal their document entry", (FI + "test_obligation_row_equals_its_entry_and_tags_only_its_facets",),
             scope="obligations_bound_to_document_and_facets", old="WHEN NOT EXISTS (", new="WHEN 0 AND NOT EXISTS ("),
    Mutation("A3-obligation-facet-referential", "A3", "obligations may tag facets absent from their revision", (FI + "test_obligation_row_equals_its_entry_and_tags_only_its_facets",),
             scope="obligations_bound_to_document_and_facets", old="  OR EXISTS (\n       SELECT 1 FROM json_each(NEW.facet_ids) j", new="  OR 0 AND EXISTS (\n       SELECT 1 FROM json_each(NEW.facet_ids) j"),
    Mutation("A3-approval-obligation-rows-complete", "A3", "approval ignores missing obligation rows", (FI + "test_approval_needs_complete_rows_and_every_facet_rated",),
             scope="contract_approval_needs_rated_covered_facets", old="       IS NOT json_array_length(NEW.document, '$.obligations')", new="       IS NOT (SELECT count(*) FROM obligations o WHERE o.topic_id = NEW.topic_id AND o.contract_revision = NEW.revision)"),
    Mutation("A3-approval-facet-rows-complete", "A3", "approval ignores missing facet rows", (FI + "test_approval_needs_complete_rows_and_every_facet_rated",),
             scope="contract_approval_needs_rated_covered_facets", old="       IS NOT json_array_length(NEW.document, '$.facet_map.facets')", new="       IS NOT (SELECT count(*) FROM facets f WHERE f.topic_id = NEW.topic_id AND f.contract_revision = NEW.revision)"),
    Mutation("A3-approval-every-facet-rated", "A3", "approval allows unrated facets", (FI + "test_approval_needs_complete_rows_and_every_facet_rated",),
             scope="contract_approval_needs_rated_covered_facets", old="  OR EXISTS (SELECT 1 FROM facets f WHERE f.topic_id = NEW.topic_id AND f.contract_revision = NEW.revision AND f.operator_importance_band IS NULL)\n", new=""),
    Mutation("A3-approval-uncovered-critical", "A3", "approval ignores uncovered critical facets (G-3)", (FI + "test_critical_facet_with_zero_obligations_is_representable_and_blocks_approval",),
             scope="contract_approval_needs_rated_covered_facets", old="  OR EXISTS (SELECT 1 FROM uncovered_critical_facets u WHERE u.topic_id = NEW.topic_id AND u.contract_revision = NEW.revision))", new=")"),
    Mutation("A3-facets-delete-guard", "A3", "drop facets delete guard", (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="facets_no_delete"),
    Mutation("A3-facets-update-guard", "A3", "drop facets update guard", (H + "EveryTableSweepTest.test_append_only_tables_reject_every_update", FI + "test_facet_rating_bound_to_a_rating_decision"), drop_trigger="facets_immutable"),
    # --- A4 / R2.1 / R2.2: admission context, leases, parentage ------------------
    Mutation("R2.2-parent-only-for-delegates", "R2.2", "non-delegates (verifiers) may have a controlling parent",
             (VT + "test_verifier_must_be_separate_verification_invocation",), old="  CHECK ((kind = 'delegate') = (parent_invocation_id IS NOT NULL)),\n", new="  CHECK (kind != 'delegate' OR parent_invocation_id IS NOT NULL),\n"),
    Mutation("R2.2-blanket-requested-by-rule", "R2.2", "over-restriction: a verifier requested by the producer is refused (the rejected blanket rule)",
             (VT + "test_verifier_must_be_separate_verification_invocation",), scope="verification_receipts_role_separation",
             old="  OR (SELECT producer_invocation_id FROM claims", new="  OR (SELECT requested_by_invocation_id FROM invocations WHERE invocation_id = NEW.verifier_invocation_id) IS NEW.producer_invocation_id\n  OR (SELECT producer_invocation_id FROM claims"),
    Mutation("R2.1-delegate-has-no-lease", "R2.1", "delegates may hold their own lease",
             (IL + "test_delegate_inherits_a_running_parent_of_its_topic",), old="  CHECK ((kind = 'delegate') = (lease_id IS NULL)),\n", new="  CHECK (kind = 'delegate' OR lease_id IS NOT NULL),\n"),
    Mutation("R2.1-one-owner-per-lease", "R2.1", "two invocations may own one lease",
             (AD + "test_invocation_owns_a_live_lease_of_its_kind_and_topic",), old="CREATE UNIQUE INDEX invocations_one_owner_per_lease ON invocations (lease_id) WHERE lease_id IS NOT NULL;\n", new=""),
    Mutation("R2.1-lease-scope", "R2.1", "an invocation may own a lease of another scope",
             (AD + "test_invocation_owns_a_live_lease_of_its_kind_and_topic",), scope="invocations_lease_matches_kind",
             old="    AND l.scope = CASE NEW.kind", new="    AND 1 OR l.scope = CASE NEW.kind"),
    Mutation("R2.1-lease-topic", "R2.1", "an invocation may own another topic's lease",
             (AD + "test_invocation_owns_a_live_lease_of_its_kind_and_topic",), scope="invocations_lease_matches_kind",
             old="l.topic_id = NEW.topic_id AND ", new=""),
    Mutation("R2.1-lease-live", "R2.1", "an invocation may be admitted on a released lease",
             (AD + "test_invocation_owns_a_live_lease_of_its_kind_and_topic",), scope="invocations_lease_matches_kind",
             old=" AND l.released_at IS NULL", new=""),
    Mutation("R2.1-delegate-parent-topic", "R2.1", "a delegate may run under another topic's parent",
             (IL + "test_delegate_inherits_a_running_parent_of_its_topic",), scope="invocations_delegate_inherits_parent",
             old=" AND p.topic_id = NEW.topic_id", new=""),
    Mutation("R2.1-delegate-parent-not-delegate", "R2.1", "delegate chains allowed",
             (IL + "test_delegate_inherits_a_running_parent_of_its_topic",), scope="invocations_delegate_inherits_parent",
             old="    AND p.kind != 'delegate' AND p.state", new="    AND p.state"),
    Mutation("R2.1-delegate-parent-running", "R2.1", "a delegate may start under a parent that is not running",
             (IL + "test_delegate_inherits_a_running_parent_of_its_topic",), scope="invocations_delegate_inherits_parent",
             old=" AND p.state IN ('launching', 'running')", new=""),
    Mutation("R2.1-delegate-inherits-pins", "R2.1", "a delegate may carry other admission pins than its parent",
             (IL + "test_delegate_inherits_a_running_parent_of_its_topic",), scope="invocations_delegate_inherits_parent",
             old="    AND p.admission_context IS NEW.admission_context AND p.contract_revision IS NEW.contract_revision\n", new=""),
    Mutation("R2.2-requested-by-same-topic", "R2.2", "a causal requester may be of another topic (or the invocation itself)",
             (VT + "test_requested_by_is_same_topic_and_never_self",), drop_trigger="invocations_requested_by_same_topic"),
    Mutation("A4-contract-admission-approved", "A4", "contract/1 admission accepts a draft revision",
             (AD + "test_contract_admission_needs_an_approved_revision",), scope="invocations_admission_context",
             old=" AND c.status = 'approved'))", new="))"),
    Mutation("A4-pre-contract-closes-on-approval", "A4", "pre-contract admission stays open after a contract is approved",
             (AD + "test_pre_contract_admission_closes_once_a_contract_is_approved",), scope="invocations_admission_context",
             old="        EXISTS (SELECT 1 FROM contract_revisions c WHERE c.topic_id = NEW.topic_id AND c.status != 'draft')\n     OR NOT EXISTS (", new="        NOT EXISTS ("),
    *(Mutation(f"A4-brief-confirmation-{key}", "A4/0b", f"pre-contract admission ignores the pinned brief row's {key}",
               (AD + "test_pre_contract_admission_needs_the_confirmed_brief",), scope="invocations_admission_context", old=old, new=new)
      for key, old, new in (
          ("confirming-decision", "\n          AND b.confirmed_by_decision_id = NEW.brief_confirmation_decision_id))))", "))))"),
          ("topic", "        WHERE b.topic_id = NEW.topic_id\n          AND b.brief_id", "        WHERE b.brief_id"),
          ("brief-hash", " AND b.content_hash = NEW.brief_hash", ""),
          ("brief-version", " AND b.version = NEW.brief_version", ""),
          ("brief-id", "          AND b.brief_id = NEW.brief_ref AND ", "          AND "))),
    Mutation("A4-brief-confirmation-status", "A4/0b", "pre-contract admission accepts a superseded (no longer current) brief version",
             (AD + "test_pre_contract_admission_pins_the_current_confirmed_version",),
             scope="invocations_admission_context", old="\n          AND b.status = 'confirmed'", new=""),
    Mutation("A4-pre-contract-kinds", "A4", "any kind may be admitted pre-contract",
             (AD + "test_pre_contract_admission_only_for_scoping_kinds",), old="  CHECK (admission_context = 'contract/1' OR kind IN ('discovery', 'delegate', 'research_pass')),\n", new=""),
    Mutation("A4-contract-pins-exclusive", "A4", "a pre-contract row may carry a contract revision",
             (AD + "test_admission_pins_are_exclusive",), old="  CHECK ((admission_context = 'contract/1') = (contract_revision IS NOT NULL)),\n  CHECK (CASE", new="  CHECK (CASE"),
    Mutation("A4-brief-pins-exclusive", "A4", "a contract row may carry brief pins",
             (AD + "test_admission_pins_are_exclusive",), old="           ELSE brief_ref IS NULL AND brief_version IS NULL AND brief_hash IS NULL AND brief_confirmation_decision_id IS NULL END),", new="           ELSE 1 END),"),
    *(Mutation(f"A4-receipt-pinned-{key}", "A4", f"a receipt may carry another {key} than its invocation",
               (AD + test,), scope="operation_receipts_admission_pinned", old=old, new="")
      for key, test, old in (
          ("contract-revision", "test_receipt_carries_the_invocations_admission_and_config", "    AND i.contract_revision IS NEW.contract_revision\n"),
          ("context", "test_receipt_carries_the_invocations_admission_and_config", "    AND i.admission_context IS NEW.admission_context\n"),
          ("brief", "test_pre_contract_receipt_carries_the_brief_pinned_at_admission", "    AND i.brief_hash IS NEW.brief_hash\n"),
          ("config", "test_receipt_carries_the_invocations_admission_and_config", "\n    AND i.config_bundle_hash IS NEW.config_bundle_hash"))),
    *(Mutation(f"A4-receipt-json-{key}", "A4", f"receipt JSON admission.{key} no longer bound",
               (AD + "test_receipt_json_admission_matches_its_columns",), old=old, new="")
      for key, old in (("context", "\n     AND json_extract(receipt, '$.admission.context') IS admission_context"),
                       ("contract", "\n     AND json_extract(receipt, '$.admission.contract.revision') IS contract_revision"),
                       ("brief", "\n     AND json_extract(receipt, '$.admission.brief.content_hash') IS brief_hash"))),
    Mutation("A4-ordinal-needs-contract", "A4", "a pre-contract research pass may earn an ordinal",
             (AD + "test_pre_contract_research_pass_earns_no_ordinal",), old="  OR (SELECT admission_context FROM operation_receipts WHERE operation_id = NEW.operation_id) IS NOT 'contract/1'\n", new=""),
    # --- A5: lifecycle pins, launch handle, reconciliation; D06 matrix ------------
    Mutation("A5-D06-reopen-committed-cancelled", "A5", "the review's surviving mutant: committed/cancelled may return to running",
             (LT + "test_terminal_states_are_final",), scope="invocations_allowed_transitions",
             old="  OR (OLD.state = 'outcome_unknown' AND NEW.state IN (", new="  OR (OLD.state IN ('committed', 'cancelled') AND NEW.state = 'running')\n  OR (OLD.state = 'outcome_unknown' AND NEW.state IN ("),
    Mutation("A5-D06-unknown-back-to-launching", "A5", "outcome_unknown may return to launching",
             (LT + "test_terminal_states_are_final",), scope="invocations_allowed_transitions",
             old="NEW.state IN ('running', 'result_ready', 'committed', 'failed', 'cancelled')))", new="NEW.state IN ('launching', 'running', 'result_ready', 'committed', 'failed', 'cancelled')))"),
    Mutation("A5-D06-skip-admitted-to-running", "A5", "admitted may skip straight to running",
             (LT + "test_terminal_states_are_final",), scope="invocations_allowed_transitions",
             old="(OLD.state = 'admitted' AND NEW.state IN ('launching', 'cancelled'))", new="(OLD.state = 'admitted' AND NEW.state IN ('launching', 'running', 'cancelled'))"),
    Mutation("A5-D06-drop-result-ready-to-committed", "A5", "over-restriction: result_ready may no longer commit",
             (LT + "test_terminal_states_are_final",), scope="invocations_allowed_transitions",
             old="(OLD.state = 'result_ready' AND NEW.state IN ('committed', 'failed', 'outcome_unknown'))", new="(OLD.state = 'result_ready' AND NEW.state IN ('failed', 'outcome_unknown'))"),
    Mutation("A5-launch-intent-carries-handle", "A5", "launch intent may be recorded without the stable job handle",
             (LT + "test_launching_requires_launch_intent",), old="  CHECK (launch_intent_at IS NULL OR job_handle IS NOT NULL),\n", new=""),
    *(Mutation(f"A5-pin-{key}", "A5", f"invocation {key} no longer write-once",
               (LT + "test_process_identity_is_write_once",), scope="invocations_identity_immutable", old=old, new="")
      for key, old in (("host", "\n  OR (OLD.host_id IS NOT NULL AND NEW.host_id IS NOT OLD.host_id)"),
                       ("container", "\n  OR (OLD.container_id IS NOT NULL AND NEW.container_id IS NOT OLD.container_id)"),
                       ("admitted-at", "\n  OR NEW.admitted_at IS NOT OLD.admitted_at"),
                       ("requested-by", "\n  OR NEW.requested_by_invocation_id IS NOT OLD.requested_by_invocation_id"),
                       ("admission-context", "\n  OR NEW.admission_context IS NOT OLD.admission_context"),
                       ("contract-revision", "\n  OR NEW.contract_revision IS NOT OLD.contract_revision"),
                       ("brief-pins", "\n  OR NEW.brief_ref IS NOT OLD.brief_ref OR NEW.brief_version IS NOT OLD.brief_version"),
                       ("brief-hash-decision", "\n  OR NEW.brief_hash IS NOT OLD.brief_hash OR NEW.brief_confirmation_decision_id IS NOT OLD.brief_confirmation_decision_id"),
                       ("config", "\n  OR NEW.config_bundle_hash IS NOT OLD.config_bundle_hash"),
                       ("result-digest", "\n  OR (OLD.result_payload_digest IS NOT NULL AND NEW.result_payload_digest IS NOT OLD.result_payload_digest)"))),
    Mutation("A5-unknown-needs-reconciliation", "A5", "outcome_unknown may be left with a timestamp and a digest (the review's probe)",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped",), drop_trigger="invocations_unknown_needs_reconciliation"),
    Mutation("A5-reconciliation-episode", "A5", "an earlier episode's reconciliation may be reused",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped", LT + "test_every_exit_needs_its_own_episodes_record"),
             scope="invocations_unknown_needs_reconciliation", old=" AND r.unknown_episode = OLD.unknown_episode", new=""),
    # --- RA4: each unknown episode has its own, never-reused identity -----------------
    Mutation("RA4-episode-keyed-by-timestamp", "RA4", "the pre-RA4 key: an exit is reconciled by any record whose start time matches (a re-entry at a reused timestamp)",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped",), scope="invocations_unknown_needs_reconciliation",
             old=" AND r.unknown_episode = OLD.unknown_episode", new=" AND r.unknown_since = OLD.outcome_unknown_since"),
    Mutation("RA4-episode-identity-dropped", "RA4", "the review's attack: an active episode's start time can be rewound (and its identity rewritten)",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped",), drop_trigger="invocations_unknown_episode_is_fresh"),
    *(Mutation(f"RA4-{key}", "RA4", desc, (LT + "test_outcome_unknown_is_reconciled_not_skipped",), scope="invocations_unknown_episode_is_fresh", old=old, new=new)
      for key, desc, old, new in (
          ("entry-takes-next-identity", "a re-entry may keep or reuse an earlier episode's identity",
           "          THEN NEW.unknown_episode IS NOT OLD.unknown_episode + 1\n", "          THEN 0\n"),
          ("identity-immutable", "an episode's identity may be rewritten outside an entry",
           "          ELSE NEW.unknown_episode IS NOT OLD.unknown_episode OR NEW.outcome_unknown_since", "          ELSE NEW.outcome_unknown_since"),
          ("start-time-immutable", "the review's rewind: an episode's start time may be changed outside an entry",
           " OR NEW.outcome_unknown_since IS NOT OLD.outcome_unknown_since END", " END"))),
    Mutation("RA4-reconciliation-names-current-episode", "RA4", "a record may be written for an earlier episode sharing the current start time",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped",), scope="invocation_reconciliations_for_current_episode",
             old="\n    AND i.unknown_episode = NEW.unknown_episode AND i.outcome_unknown_since = NEW.unknown_since)", new=" AND i.outcome_unknown_since = NEW.unknown_since)"),
    Mutation("A5-reconciliation-running-branch", "A5", "over-restriction: found_running no longer supports running",
             (LT + "test_terminal_states_are_final",), scope="invocations_unknown_needs_reconciliation", old="(NEW.state = 'running' AND r.resolution = 'found_running')", new="(0)"),
    Mutation("A5-reconciliation-result-digest", "A5", "result_ready accepted with another digest than the one found",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped",), scope="invocations_unknown_needs_reconciliation", old=" AND r.result_payload_digest = NEW.result_payload_digest)", new=")"),
    Mutation("A5-reconciliation-committed-receipt", "A5", "found_committed accepted without a final receipt",
             (LT + "test_found_committed_needs_the_final_receipt",), scope="invocations_unknown_needs_reconciliation",
             old="\n            AND EXISTS (SELECT 1 FROM operation_receipts o WHERE o.invocation_id = NEW.invocation_id AND o.operation_kind = 'final_outcome'))", new=")"),
    Mutation("A5-reconciliation-failed-resolution", "A5", "failed accepted with any resolution",
             (LT + "test_reconciliation_resolutions_and_evidence",), scope="invocations_unknown_needs_reconciliation", old="(NEW.state = 'failed' AND r.resolution IN ('confirmed_failed', 'terminated_group'))", new="(NEW.state = 'failed')"),
    Mutation("A5-reconciliation-cancelled-resolution", "A5", "cancelled accepted with any resolution",
             (LT + "test_reconciliation_resolutions_and_evidence",), scope="invocations_unknown_needs_reconciliation", old="(NEW.state = 'cancelled' AND r.resolution = 'terminated_group')", new="(NEW.state = 'cancelled')"),
    Mutation("A5-reconciliation-current-episode", "A5", "a reconciliation may be recorded for a past episode or a known state",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped",), drop_trigger="invocation_reconciliations_for_current_episode"),
    Mutation("A5-reconciliation-digest-iff-found-result", "A5", "digest no longer tied to found_result",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped", LT + "test_reconciliation_resolutions_and_evidence"),
             old="  CHECK ((resolution = 'found_result') = (result_payload_digest IS NOT NULL)),\n", new=""),
    Mutation("A5-reconciliation-descendants", "A5", "terminal resolutions without descendant confirmation",
             (LT + "test_reconciliation_resolutions_and_evidence",), old="  CHECK (resolution NOT IN ('confirmed_failed', 'terminated_group') OR descendants_confirmed_at IS NOT NULL),\n", new=""),
    Mutation("A5-reconciliation-termination-method", "A5", "termination method no longer tied to terminated_group",
             (LT + "test_reconciliation_resolutions_and_evidence",), old=",\n  CHECK ((resolution = 'terminated_group') = (method = 'execution_group_termination'))", new=""),
    Mutation("A5-reconciliation-update-guard", "A5", "reconciliation records may be edited",
             (LT + "test_reconciliation_resolutions_and_evidence", H + "EveryTableSweepTest.test_append_only_tables_reject_every_update"), drop_trigger="invocation_reconciliations_immutable_u"),
    Mutation("A5-reconciliation-delete-guard", "A5", "reconciliation records may be deleted",
             (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="invocation_reconciliations_no_delete"),
    # --- A6 / A10: verification support integrity and receipt binding -------------
    Mutation("A6-D32-byte-mismatch", "A6", "the review's surviving mutant: a byte mismatch need not quarantine the quote",
             (VT + "test_nli_alarm_quarantines_the_quote",), old=",\n  CHECK (exact_match != 'mismatch' OR quote_quarantined = 1)", new=""),
    Mutation("A6-verifier-extraction-is-own", "A6", "a producer's extraction may be passed off as the verifier's own",
             (VT + "test_producer_unvalidated_extraction_rejected",), old="  CHECK (extraction_method != 'verifier_extraction' OR extraction_invocation_id = verifier_invocation_id),\n", new=""),
    Mutation("A6-validated-extraction-cites-validation", "A6", "a 'validated' extraction need not cite its validation",
             (VT + "test_producer_unvalidated_extraction_rejected",), old="  CHECK (extraction_method != 'validated_extraction' OR extraction_validation_ref IS NOT NULL),\n", new=""),
    Mutation("A6-canonical-bytes-authenticated", "A6", "canonical bytes need no authenticated acquisition",
             (VT + "test_producer_unvalidated_extraction_rejected",), old="  CHECK (extraction_method != 'canonical_bytes' OR json_extract(acquisition, '$.gateway_call_ref') IS NOT NULL),\n", new=""),
    Mutation("A6-canonical-bytes-staged", "A6", "canonical bytes need not be a staged artifact with the obtained hash",
             (VT + "test_producer_unvalidated_extraction_rejected",), scope="verification_receipts_bindings",
             old="  OR (NEW.extraction_method = 'canonical_bytes' AND NOT EXISTS (SELECT 1 FROM artifacts a WHERE a.content_hash = NEW.obtained_content_hash))\n", new=""),
    Mutation("A6-D28-old-over-restriction", "A6", "over-restriction restored: producer-acquired canonical bytes refused (the review's D28 finding)",
             (VT + "test_producer_unvalidated_extraction_rejected",),
             old="  CHECK (extraction_method != 'verifier_extraction' OR extraction_invocation_id = verifier_invocation_id),\n",
             new="  CHECK (extraction_method != 'verifier_extraction' OR extraction_invocation_id = verifier_invocation_id),\n  CHECK (extraction_invocation_id != producer_invocation_id OR extraction_validation_ref IS NOT NULL),\n"),
    Mutation("A6-quote-check-iff-status", "A6", "a matched/mismatched quote need not name its quote check",
             (VT + "test_quote_check_binding",), old="  CHECK ((coalesce(json_extract(receipt, '$.checks.exact_quote.status'), 'missing') IN ('matched', 'mismatch')) = (quote_check_id IS NOT NULL)),\n", new=""),
    *(Mutation(f"A6-support-needs-{name.replace('_', '-')}", "A6", f"'supports' accepted with an adverse/unperformed {name} check",
               (VT + "test_support_needs_successful_checks_or_adjudication",), scope="verification_receipts",
               old=f"coalesce(json_extract(receipt, '$.checks.{name}'), 'missing') IN ('checked_ok', 'not_applicable')", new="1")
      for name in ("numeric_units", "denominators", "negation", "qualifications")),
    Mutation("A6-support-needs-no-tier0-alarm", "A6", "'supports' accepted over an unadjudicated tier-0 alarm",
             (VT + "test_support_needs_successful_checks_or_adjudication",), old="\n     AND json_extract(receipt, '$.checks.tier0.signal') IS NOT 'alarm'))", new="))"),
    Mutation("A6-support-adjudication-escape", "A6", "over-restriction: an explicit adjudication no longer resolves an adverse check",
             (VT + "test_support_needs_successful_checks_or_adjudication",), old="  CHECK (verdict != 'supports' OR json_type(receipt, '$.adjudication') IS 'object' OR (", new="  CHECK (verdict != 'supports' OR ("),
    Mutation("A6-load-bearing-support-checks-performed", "A6", "a load-bearing partial support may skip its checks",
             (VT + "test_truthful_unsuccessful_verdicts_may_record_unperformed_checks",), old="  CHECK (use != 'load_bearing' OR verdict NOT IN ('supports', 'partially_supports') OR (", new="  CHECK (1 OR ("),
    Mutation("A6-truthful-cannot-assess-over-restriction", "A6", "over-restriction restored: load-bearing checks required for every verdict (the review's rejected truthful receipt)",
             (VT + "test_truthful_unsuccessful_verdicts_may_record_unperformed_checks",), old="  CHECK (use != 'load_bearing' OR verdict NOT IN ('supports', 'partially_supports') OR (", new="  CHECK (use != 'load_bearing' OR ("),
    # --- RA5: promotion from the stored claim; sampling never qualifies ----------
    Mutation("RA5-promotion-accepts-sampling", "RA5", "the review's probe: a sampled receipt (any checks, any adjudication) promotes a load-bearing claim",
             (VT + "test_sampling_never_qualifies_a_load_bearing_claim",), scope="claims_accepted_support_needs_receipt",
             old="    AND v.use = 'load_bearing'\n", new=""),
    Mutation("RA5-promotion-verdict", "RA5", "a load-bearing partial support promotes the claim",
             (VT + "test_sampling_never_qualifies_a_load_bearing_claim",), scope="claims_accepted_support_needs_receipt",
             old="AND v.verdict = 'supports'\n", new="AND v.verdict IN ('supports', 'partially_supports')\n"),
    Mutation("RA5-use-matches-claim-dropped", "RA5", "a load-bearing-use receipt may re-describe its claim's designation",
             (VT + "test_load_bearing_receipt_states_its_claims_designation",), drop_trigger="verification_receipts_use_matches_claim"),
    Mutation("RA5-use-matches-claim-load-bearing", "RA5", "a load-bearing-use receipt may be about a claim that is not load-bearing",
             (VT + "test_load_bearing_receipt_states_its_claims_designation",), scope="verification_receipts_use_matches_claim",
             old="    AND c.load_bearing = 1\n", new=""),
    Mutation("RA5-use-matches-claim-tier", "RA5", "a load-bearing-use receipt may name another required tier than its claim's",
             (VT + "test_load_bearing_receipt_states_its_claims_designation",), scope="verification_receipts_use_matches_claim",
             old="\n    AND c.required_access_tier = NEW.required_access_tier)", new=")"),
    # --- task 1a / V-10: accepted support needs contract-admitted production ---------
    Mutation("V10-dropped", "1a", "the limited-consumer rule restored: pre-contract (scoping) output becomes accepted support",
             (CS + "test_pre_contract_claim_with_a_qualifying_receipt_is_refused", CS + "test_every_claim_needs_admission_not_only_load_bearing",
              CS + "test_adopted_pre_contract_claim_with_a_receipt_is_allowed", CS + "test_contested_to_accepted_support_follows_the_same_rule",
              CS + "test_the_producer_is_work_of_the_claims_own_topic"), drop_trigger="claims_accepted_support_needs_contract_admission"),
    *(Mutation(f"V10-{key}", "1a", desc, tuple(CS + k for k in killers), scope=scope, old=old, new=new)
      for key, desc, killers, scope, old, new in (
          ("admission-context", "any producer of the claim's topic qualifies, pre-contract (scoping) work included",
           ("test_pre_contract_claim_with_a_qualifying_receipt_is_refused", "test_every_claim_needs_admission_not_only_load_bearing",
            "test_adopted_pre_contract_claim_with_a_receipt_is_allowed", "test_contested_to_accepted_support_follows_the_same_rule"),
           "claims_accepted_support_needs_contract_admission", "\n    AND p.admission_context = 'contract/1'", ""),
          ("producer-topic", "another topic's contract-admitted work qualifies as this topic's production",
           ("test_the_producer_is_work_of_the_claims_own_topic",),
           "claims_accepted_support_needs_contract_admission", "\n    AND p.topic_id = NEW.topic_id)", ")"),
          ("load-bearing-only", "the rule narrowed to V-4's scope: only load-bearing claims need admission",
           ("test_every_claim_needs_admission_not_only_load_bearing",),
           "claims_accepted_support_needs_contract_admission", "WHEN NEW.status = 'accepted_support' AND NOT EXISTS (",
           "WHEN NEW.status = 'accepted_support' AND NEW.load_bearing = 1 AND NOT EXISTS ("),
          ("contested-exempt", "contested -> accepted_support skips the admission rule",
           ("test_contested_to_accepted_support_follows_the_same_rule",),
           "claims_accepted_support_needs_contract_admission", "WHEN NEW.status = 'accepted_support' AND NOT EXISTS (",
           "WHEN NEW.status = 'accepted_support' AND OLD.status IS NOT 'contested' AND NOT EXISTS ("),
          ("receipt-substitutes-for-admission", "the two conditions merged: a supporting load-bearing receipt stands in for contract admission",
           ("test_pre_contract_claim_with_a_qualifying_receipt_is_refused",),
           "claims_accepted_support_needs_contract_admission", "WHEN NEW.status = 'accepted_support' AND NOT EXISTS (",
           "WHEN NEW.status = 'accepted_support' AND NOT EXISTS (SELECT 1 FROM verification_receipts v WHERE v.claim_id = NEW.claim_id "
           "AND v.claim_revision = NEW.revision AND v.use = 'load_bearing' AND v.verdict = 'supports') AND NOT EXISTS ("),
          ("admission-substitutes-for-receipt", "the two conditions merged: contract admission stands in for the verification receipt",
           ("test_contract_admitted_claim_without_a_receipt_is_refused",),
           "claims_accepted_support_needs_receipt", "WHEN NEW.status = 'accepted_support' AND NEW.load_bearing = 1 AND NOT EXISTS (",
           "WHEN NEW.status = 'accepted_support' AND NEW.load_bearing = 1 AND NOT EXISTS (SELECT 1 FROM invocations p "
           "WHERE p.invocation_id = NEW.producer_invocation_id AND p.admission_context = 'contract/1') AND NOT EXISTS ("),
          ("adoption-per-claim", "adoption read per claim id, not per revision: an adopted revision admits the scoping revision and a relabelled one too",
           ("test_adopted_pre_contract_claim_with_a_receipt_is_allowed",),
           "claims_accepted_support_needs_contract_admission", "  WHERE p.invocation_id = NEW.producer_invocation_id\n",
           "  WHERE p.invocation_id IN (SELECT producer_invocation_id FROM claims WHERE claim_id = NEW.claim_id)\n"),
          ("adoption-refused", "over-restriction: a claim with any pre-contract revision can never become accepted support (no adoption)",
           ("test_adopted_pre_contract_claim_with_a_receipt_is_allowed",),
           "claims_accepted_support_needs_contract_admission", "\n    AND p.topic_id = NEW.topic_id)",
           "\n    AND p.topic_id = NEW.topic_id\n    AND NOT EXISTS (SELECT 1 FROM claims o JOIN invocations q ON q.invocation_id = o.producer_invocation_id "
           "WHERE o.claim_id = NEW.claim_id AND q.admission_context = 'pre-contract/1'))"))),
    # --- RA3: scientific rows only under contract-admitted work and approved pins -------
    *(Mutation(f"RA3-{key}", "RA3", desc, tuple(AD + k for k in killers), drop_trigger=trigger)
      for key, desc, killers, trigger in (
          ("screening-dropped", "pre-contract work may record a screening disposition against a draft (the review's probe)",
           ("test_pre_contract_work_records_no_scientific_disposition", "test_scientific_rows_bind_the_approved_protocol_they_name"), "screening_assessments_under_approved_protocol"),
          ("link-dropped", "a claim-source link may tie pre-contract or other-protocol work to an obligation",
           ("test_pre_contract_work_records_no_scientific_disposition", "test_scientific_rows_bind_the_approved_protocol_they_name"), "claim_source_links_under_approved_protocol"),
          ("dossier-dropped", "a dossier may be evaluated against a draft",
           ("test_pre_contract_work_records_no_scientific_disposition", "test_scientific_rows_bind_the_approved_protocol_they_name"), "dossiers_under_approved_protocol"))),
    # --- RA3-R: the approving decision is recorded only by the draft -> approved transition ---
    Mutation("RA3R-dropped", "RA3-R", "the review's probe: an approving decision may be recorded on a still-draft revision, which then admits a dossier",
             (CG + "test_approval_pointer_is_set_only_by_the_approval_transition", AD + "test_pre_contract_work_records_no_scientific_disposition",
              EX + "test_review_ra3r_approval_pointer_without_approval"), drop_trigger="contract_approval_pointer_set_by_approval"),
    # (RA3R-superseded-too — the pointer first recorded by draft -> superseded — is a second layer since
    # the draft -> superseded edge was removed; see SECOND_LAYER.)
    # --- 0a-repair-3 ruling 1: draft -> superseded is not an edge -------------------
    Mutation("R1c-draft-superseded-edge-restored", "0b-cleanup-1", "the unreachable draft -> superseded edge is back in the status machine (the CHECK then refuses in its place)",
             (CG + "test_approval_pointer_is_set_only_by_the_approval_transition",), scope="contract_status_forward_only",
             old="(OLD.status = 'draft' AND NEW.status IN ('draft', 'approved'))", new="(OLD.status = 'draft' AND NEW.status IN ('draft', 'approved', 'superseded'))"),
    Mutation("R1c-approved-without-decision", "0b-cleanup-1", "drop the CHECK that a non-draft revision holds its approving decision",
             (CG + "test_approval_pointer_is_set_only_by_the_approval_transition",),
             old="  CHECK (status = 'draft' OR approved_by_decision_id IS NOT NULL),\n", new=""),
    Mutation("RA3R-approval-refused-too", "RA3-R", "over-restriction: not even the draft -> approved transition may record its decision",
             (CG + "test_approval_pointer_is_set_only_by_the_approval_transition", AD + "test_scientific_rows_bind_the_approved_protocol_they_name",
              EX + "test_review_ra3r_approval_pointer_without_approval"), scope="contract_approval_pointer_set_by_approval",
             old="\n  AND NEW.status IS NOT 'approved'\n", new="\n"),
    *(Mutation(f"RA3-{key}", "RA3", desc, (AD + "test_scientific_rows_bind_the_approved_protocol_they_name",), scope=scope, old=old, new=new)
      for key, desc, scope, old, new in (
          ("screening-operation-pin", "a screening row may be recorded by a commit pinned to another revision", "screening_assessments_under_approved_protocol",
           "WHERE o.operation_id = NEW.recorded_by_operation_id AND o.contract_revision = NEW.contract_revision)", "WHERE o.operation_id = NEW.recorded_by_operation_id)"),
          ("screening-invocation-pin", "a screening row may be assessed by work pinned to another revision", "screening_assessments_under_approved_protocol",
           "WHERE i.invocation_id = NEW.invocation_id AND i.contract_revision = NEW.contract_revision))", "WHERE i.invocation_id = NEW.invocation_id))"),
          ("screening-framing", "a screening row may carry another framing version than its revision's", "screening_assessments_under_approved_protocol",
           "\n         AND c.framing_version = NEW.framing_version", ""),
          ("screening-eligibility", "a screening row may carry another eligibility-protocol version than its revision's", "screening_assessments_under_approved_protocol",
           "\n         AND json_extract(c.document, '$.eligibility_protocol.protocol_version') IS NEW.eligibility_protocol_version)", ")"),
          ("link-topic", "a link may name this topic's obligation for another topic's claim", "claim_source_links_under_approved_protocol",
           "\n    AND c.topic_id = NEW.topic_id", ""),
          ("link-producer-pin", "a link may name another protocol revision than its claim's producing work", "claim_source_links_under_approved_protocol",
           "\n    AND p.contract_revision = NEW.contract_revision)", ")"))),
    # --- RA6: one representation — every duplicated identity field equals its twin ------
    *(Mutation(f"RA6-receipt-json-{field.replace('.', '-')}", "RA6", f"a commit receipt's JSON {field} may differ from its row",
               (AD + "test_receipt_json_admission_matches_its_columns", EX + "test_commit_receipt_cannot_describe_another_row"), scope="operation_receipts",
               old=f"\n     AND json_extract(receipt, '$.{field}') IS {column}", new="")
      for field, column in (("operation_kind", "operation_kind"), ("invocation_id", "invocation_id"), ("topic_id", "topic_id"),
                            ("request_fingerprint", "request_fingerprint"), ("state_revision_before", "state_revision_before"),
                            ("state_revision_after", "state_revision_after"), ("validation.validator_version", "validator_version"),
                            ("validation.policy_version", "policy_version"), ("committed_at", "committed_at"))),
    Mutation("RA6-receipt-json-lease-release-lease", "RA6", "a commit receipt may record the release of another lease than its fencing one",
             (AD + "test_receipt_json_admission_matches_its_columns", EX + "test_commit_receipt_cannot_describe_another_row"), scope="operation_receipts",
             old="json_extract(receipt, '$.effects.lease_release.lease_id') IS lease_id\n          AND ", new=""),
    Mutation("RA6-receipt-json-lease-release-generation", "RA6", "a commit receipt may record another released generation than its fencing one",
             (AD + "test_receipt_json_admission_matches_its_columns", EX + "test_commit_receipt_cannot_describe_another_row"), scope="operation_receipts",
             old="\n          AND json_extract(receipt, '$.effects.lease_release.generation') IS lease_generation", new=""),
    Mutation("RA6-receipt-admission-references-dropped", "RA6", "a commit receipt's JSON may name another contract hash or brief than its pins",
             (AD + "test_receipt_json_admission_matches_its_columns", AD + "test_pre_contract_receipt_json_names_the_pinned_brief"),
             drop_trigger="operation_receipts_admission_references"),
    *(Mutation(f"RA6-receipt-admission-{key}", "RA6", desc, (killer,), scope="operation_receipts_admission_references", old=old, new=new)
      for key, desc, killer, old, new in (
          ("contract-hash", "the receipt JSON may name another contract content hash", AD + "test_receipt_json_admission_matches_its_columns",
           "WHEN json_extract(NEW.receipt, '$.admission.contract.content_hash')\n       IS NOT (SELECT content_hash FROM contract_revisions WHERE topic_id = NEW.topic_id AND revision = NEW.contract_revision)\n  OR ", "WHEN "),
          ("brief-id", "the receipt JSON may name another brief", AD + "test_pre_contract_receipt_json_names_the_pinned_brief",
           "         AND json_extract(NEW.receipt, '$.admission.brief.brief_id') IS i.brief_ref\n", ""),
          ("brief-version", "the receipt JSON may name another brief version", AD + "test_pre_contract_receipt_json_names_the_pinned_brief",
           "         AND json_extract(NEW.receipt, '$.admission.brief.version') IS i.brief_version\n", ""),
          ("brief-confirmation", "the receipt JSON may name another confirming decision", AD + "test_pre_contract_receipt_json_names_the_pinned_brief",
           "\n         AND json_extract(NEW.receipt, '$.admission.brief_confirmation_decision_id') IS i.brief_confirmation_decision_id)", ")"))),
    Mutation("RA6-decision-spec-id", "RA6", "the review's probe: a decision receipt may name another spec id than its hash selects",
             (DC + "test_receipt_matches_its_spec", EX + "test_decision_receipt_cannot_name_another_spec"), scope="decision_receipts_match_spec",
             old="WHEN (SELECT spec_id FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT json_extract(NEW.receipt, '$.spec.spec_id')\n  OR ", new="WHEN "),
    Mutation("RA6-decision-decided-at", "RA6", "a decision receipt's JSON decided_at may differ from its row", (DC + "test_receipt_row_matches_its_json",),
             scope="decision_receipts", old="\n     AND json_extract(receipt, '$.decided_at') IS decided_at", new=""),
    *(Mutation(f"RA6-obligation-{key}", "RA6", f"the review's probe: an obligation row's {key} may differ from its document entry",
               (FI + "test_obligation_row_equals_its_entry_and_tags_only_its_facets", EX + "test_obligation_rows_cannot_contradict_the_example_document"),
               scope="obligations_bound_to_document_and_facets", old=f"         AND json_extract(e.value, '$.{path}') IS NEW.{key}\n", new="")
      for key, path in (("template_id", "template.template_id"), ("template_version", "template.template_version"), ("claim_type", "template.claim_type"),
                        ("stopping_profile_id", "stopping_profile_id"), ("exploratory", "exploratory"))),
    *(Mutation(f"RA6-contract-{key}", "RA6", f"a contract document's {key} may differ from its row", (CG + "test_hash_lock_binds_document_to_row",),
               scope="contract_revisions", old=f"\n     AND json_extract(document, '$.{key}') IS {key}", new="")
      for key in ("parent_revision", "created_at")),
    Mutation("A6-binds-verifier-capability", "A10", "the receipt may name another invocation's capability",
             (VT + "test_receipt_names_the_verifiers_own_capability",), scope="verification_receipts_bindings",
             old="WHEN (SELECT capability_id FROM invocations WHERE invocation_id = NEW.verifier_invocation_id) IS NOT json_extract(NEW.receipt, '$.verifier_capability_id')\n  OR ", new="WHEN "),
    *(Mutation(f"A6-quote-binding-{key}", "A6", f"a bound quote check may differ in {key}", (VT + "test_quote_check_binding",), scope="verification_receipts_bindings", old=old, new=new)
      for key, old, new in (
          ("claim", "          AND q.claim_id = NEW.claim_id AND q.claim_revision = NEW.claim_revision\n", ""),
          ("source", "          AND q.source_artifact_hash IS json_extract(NEW.receipt, '$.checks.exact_quote.source_artifact_hash')\n", ""),
          ("status", "          AND q.exact_match IS json_extract(NEW.receipt, '$.checks.exact_quote.status')\n", ""),
          ("quarantine", "          AND (NEW.verdict != 'supports' OR q.quote_quarantined = 0\n               OR (q.exact_match = 'matched' AND q.nli_signal = 'alarm' AND json_type(NEW.receipt, '$.adjudication') IS 'object'))))", "))"),
          ("adjudication-escape", "\n               OR (q.exact_match = 'matched' AND q.nli_signal = 'alarm' AND json_type(NEW.receipt, '$.adjudication') IS 'object'))))", ")))"))),
    *(Mutation(f"A10-verification-json-{path.replace('.', '-').replace('_', '-')}", "A10", f"verification receipt column {col} no longer bound to $.{path}",
               (VT + "test_receipt_row_matches_its_json",), scope="verification_receipts", old=f"\n     AND json_extract(receipt, '$.{path}') IS {col}", new="")
      for path, col in (("topic_id", "topic_id"), ("claim.claim_id", "claim_id"), ("claim.claim_revision", "claim_revision"), ("source.work_id", "work_id"),
                        ("source.source_version", "source_version"), ("cited_spans", "json(cited_spans)"), ("obtained_content_hash", "obtained_content_hash"),
                        ("access_tier", "access_tier"), ("requested_for.use", "use"), ("requested_for.required_access_tier", "required_access_tier"),
                        ("acquisition", "json(acquisition)"), ("extraction.method", "extraction_method"), ("extraction.produced_by_invocation_id", "extraction_invocation_id"),
                        ("extraction.validation_ref", "extraction_validation_ref"), ("producer_invocation_id", "producer_invocation_id"),
                        ("verifier_invocation_id", "verifier_invocation_id"), ("quote_check_id", "quote_check_id"))),
    Mutation("A10-verification-json-verdict", "A10", "verification verdict column no longer bound to the receipt JSON (the review's contradiction probe)",
             (VT + "test_receipt_row_matches_its_json",), scope="verification_receipts", old="\n     AND json_extract(receipt, '$.verdict') IS verdict),", new="),"),
    Mutation("A10-verification-json-receipt-id", "A10", "verification receipt id no longer bound to the JSON",
             (VT + "test_receipt_row_matches_its_json",), scope="verification_receipts", old="  CHECK (json_extract(receipt, '$.verification_receipt_id') IS verification_receipt_id\n     AND ", new="  CHECK ("),
    # --- A7 / A10: decision spec and receipt consistency; screening/observation binding ---
    Mutation("A7-spec-provider-primitive", "A7", "a fallback spec may answer with a Jev primitive",
             (DC + "test_spec_shape_by_class_and_provider",), old="  CHECK ((provider = 'jev' AND primitive IN ('noul', 'choice', 'score')) OR (provider = 'llm_fallback' AND primitive = 'label')),\n", new=""),
    Mutation("A7-spec-options-object", "A7", "spec options may be a list (duplicate ids possible)",
             (DC + "test_spec_shape_by_class_and_provider",), old="  CHECK (json_type(document, '$.options') IS 'object'),\n", new=""),
    Mutation("A7-spec-at-least-two-options", "A7", "a spec may offer one option",
             (DC + "test_spec_shape_by_class_and_provider",), scope="decision_specs_option_count", old="WHEN (SELECT count(*) FROM json_each(NEW.document, '$.options')) < 2\n  OR ", new="WHEN "),
    Mutation("A7-spec-noul-two-options", "A7", "a Noul may offer other than two options",
             (DC + "test_spec_shape_by_class_and_provider",), scope="decision_specs_option_count", old="\n  OR (NEW.primitive = 'noul' AND (SELECT count(*) FROM json_each(NEW.document, '$.options')) != 2)", new=""),
    Mutation("A7-spec-screening-protocol", "A7", "a screening spec may have no eligibility protocol (the review's probe)",
             (DC + "test_spec_shape_by_class_and_provider",), old="  CHECK (decision_class != 'screening' OR json_type(document, '$.protocol.eligibility_protocol_version') IS 'integer'),\n", new=""),
    Mutation("NULL-spec-screening-protocol", "A7", "NULL-CHECK regression: '=' instead of IS lets an absent protocol pass",
             (DC + "test_spec_shape_by_class_and_provider",), old="json_type(document, '$.protocol.eligibility_protocol_version') IS 'integer'", new="json_type(document, '$.protocol.eligibility_protocol_version') = 'integer'"),
    Mutation("NULL-support-adjudication", "A6", "NULL-CHECK regression: '=' instead of IS lets an absent adjudication key pass an adverse check",
             (VT + "test_absent_keys_are_not_passes",), old="  CHECK (verdict != 'supports' OR json_type(receipt, '$.adjudication') IS 'object' OR (", new="  CHECK (verdict != 'supports' OR json_type(receipt, '$.adjudication') = 'object' OR ("),
    Mutation("NULL-support-quote-status", "A6", "NULL-CHECK regression: an absent exact-quote status passes",
             (VT + "test_absent_keys_are_not_passes",), old="  CHECK (verdict != 'supports' OR coalesce(json_extract(receipt, '$.checks.exact_quote.status'), 'missing') IN ('matched', 'not_applicable')),",
             new="  CHECK (verdict != 'supports' OR json_extract(receipt, '$.checks.exact_quote.status') IN ('matched', 'not_applicable')),"),
    Mutation("A7-spec-method-protocol", "A7", "a method_selection spec may have no contract protocol",
             (DC + "test_spec_shape_by_class_and_provider",), old="  CHECK (decision_class != 'method_selection' OR json_type(document, '$.protocol') IS 'object'),\n", new=""),
    *(Mutation(f"A7-spec-json-{key}", "A7", f"spec {key} column no longer bound to its document",
               (DC + "test_spec_shape_by_class_and_provider",), scope="decision_specs", old=old, new="")
      for key, old in (("primitive", "\n     AND json_extract(document, '$.primitive') IS primitive"),
                       ("policy-id", "\n     AND json_extract(document, '$.action_policy.policy_id') IS policy_id"),
                       ("policy-version", "\n     AND json_extract(document, '$.action_policy.version') IS policy_version"),
                       ("protocol-topic", "\n     AND json_extract(document, '$.protocol.topic_id') IS protocol_topic_id"))),
    Mutation("A7-shadow-no-commit", "A7", "a shadow receipt may carry a committed operation (the review's probe)",
             (DC + "test_action_fixes_the_outcome_shape",), old="  CHECK ((action = 'commit_reversible_action') = (commit_operation_id IS NOT NULL)),\n", new="  CHECK (action != 'commit_reversible_action' OR commit_operation_id IS NOT NULL),\n"),
    Mutation("A7-proposal-iff-attach", "A7", "proposal ref no longer tied to attach_proposal",
             (DC + "test_action_fixes_the_outcome_shape",), old="  CHECK ((action = 'attach_proposal') = (proposal_ref IS NOT NULL)),\n", new=""),
    Mutation("A7-hold-only-for-hold-actions", "A7", "a hold may be named by shadow/commit/proposal actions",
             (DC + "test_action_fixes_the_outcome_shape",), old="  CHECK (action NOT IN ('shadow_log_only', 'commit_reversible_action', 'attach_proposal') OR hold_id IS NULL),\n", new=""),
    Mutation("A7-abstention-keeps-raw", "A7", "an abstention may discard the raw response (the review's probe)",
             (DC + "test_abstention_retains_the_raw_response",), old="  CHECK (response_status NOT IN ('answered', 'abstained') OR raw_response_digest IS NOT NULL),\n", new="  CHECK (response_status != 'answered' OR raw_response_digest IS NOT NULL),\n"),
    Mutation("A7-raw-is-retained-artifact", "A7", "the raw digest need not be a retained artifact",
             (DC + "test_abstention_retains_the_raw_response",), old="  raw_response_digest TEXT REFERENCES artifacts (content_hash),", new="  raw_response_digest TEXT,"),
    *(Mutation(f"A7-match-spec-{key}", "A7", f"receipt may differ from its spec in {key}", (DC + "test_receipt_matches_its_spec",), scope="decision_receipts_match_spec", old=old, new="")
      for key, old in (
          ("primitive", "  OR (NEW.answer IS NOT NULL AND (SELECT primitive FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT json_extract(NEW.answer, '$.primitive'))\n"),
          ("policy-id", "  OR (SELECT policy_id FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT NEW.policy_id\n"),
          ("policy-version", "  OR (SELECT policy_version FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT NEW.policy_version\n"),
          ("protocol-topic", "  OR coalesce((SELECT protocol_topic_id FROM decision_specs WHERE spec_hash = NEW.spec_hash), NEW.topic_id) IS NOT NEW.topic_id\n"),
          ("selected-option", "  OR (json_extract(NEW.answer, '$.selected_option_id') IS NOT NULL AND NOT EXISTS (\n        SELECT 1 FROM decision_specs sp, json_each(sp.document, '$.options') o\n        WHERE sp.spec_hash = NEW.spec_hash AND o.key = json_extract(NEW.answer, '$.selected_option_id')))\n"),
          ("distribution", "\n  OR EXISTS (\n        SELECT 1 FROM json_each(NEW.answer, '$.distribution') d\n        WHERE NOT EXISTS (SELECT 1 FROM decision_specs sp, json_each(sp.document, '$.options') o WHERE sp.spec_hash = NEW.spec_hash AND o.key = d.key))"))),
    *(Mutation(f"A10-decision-json-{path.replace('.', '-').replace('_', '-')}", "A10", f"decision receipt {col} no longer bound to $.{path}",
               (DC + "test_receipt_row_matches_its_json",), scope="decision_receipts", old=f"\n     AND json_extract(receipt, '$.{path}') IS {col}", new="")
      for path, col in (("invocation_id", "invocation_id"), ("topic_id", "topic_id"), ("spec.spec_hash", "spec_hash"), ("decision_class", "decision_class"),
                        ("provider", "provider"), ("subject.kind", "subject_kind"), ("subject.ref", "subject_ref"), ("input_manifest.input_status", "input_status"),
                        ("provider_response.status", "response_status"), ("provider_response.raw_response_digest", "raw_response_digest"),
                        ("provider_response.raw_response_artifact.content_hash", "raw_response_digest"), ("provider_response.answer", "json(answer)"),
                        ("policy.policy_id", "policy_id"), ("policy.version", "policy_version"), ("authorization.authority_level", "authority_level"),
                        ("authorization.qualification_ref", "qualification_ref"), ("action", "action"), ("outcome.commit_operation_id", "commit_operation_id"),
                        ("outcome.proposal_ref", "proposal_ref"), ("outcome.hold_id", "hold_id"), ("blind_sample.selected", "blind_sample"))),
    Mutation("A10-decision-json-receipt-id", "A10", "decision receipt id no longer bound to its JSON",
             (DC + "test_receipt_row_matches_its_json",), scope="decision_receipts", old="  CHECK (json_extract(receipt, '$.decision_receipt_id') IS decision_receipt_id\n     AND ", new="  CHECK ("),
    *(Mutation(f"A10-screening-binds-{key}", "A10", f"a provider assessment may differ from its receipt in {key}", (SD + "test_provider_assessment_is_exactly_its_receipts_committed_action",),
               scope="screening_assessments_bound", old=old, new=new)
      for key, old, new in (("class", "AND r.decision_class = 'screening' ", ""), ("invocation", " AND r.invocation_id IS NEW.invocation_id", ""),
                            ("commit", "          AND r.commit_operation_id = NEW.recorded_by_operation_id\n", ""),
                            ("subject-kind", "AND r.subject_kind = 'work' ", ""), ("subject-ref", " AND r.subject_ref = NEW.work_id))", "))"))),
    Mutation("A10-screening-operation-topic", "A10", "the recording operation may be another topic's", (SD + "test_assessment_operation_invocation_and_reversal_are_of_its_topic",),
             scope="screening_assessments_bound", old="  OR (SELECT topic_id FROM operation_receipts WHERE operation_id = NEW.recorded_by_operation_id) IS NOT NEW.topic_id\n", new=""),
    Mutation("A10-screening-invocation-topic", "A10", "the assessing invocation may be another topic's", (SD + "test_assessment_operation_invocation_and_reversal_are_of_its_topic",),
             scope="screening_assessments_bound", old="  OR (NEW.invocation_id IS NOT NULL AND (SELECT topic_id FROM invocations WHERE invocation_id = NEW.invocation_id) IS NOT NEW.topic_id)\n", new=""),
    Mutation("A10-screening-reversal-same-work", "A10", "a reversal may supersede another work's assessment", (SD + "test_assessment_operation_invocation_and_reversal_are_of_its_topic",),
             scope="screening_assessments_bound", old=" AND o.work_id = NEW.work_id))", new="))"),
    Mutation("A10-screening-reversal-same-topic", "A10", "a reversal may supersede another topic's assessment", (SD + "test_assessment_operation_invocation_and_reversal_are_of_its_topic",),
             scope="screening_assessments_bound", old=" AND o.topic_id = NEW.topic_id AND", new=" AND"),
    Mutation("A10-observation-invocation-topic", "A10", "an observation may be recorded under another topic's invocation (the review's probe)",
             (OB + "test_observation_invocation_is_of_its_topic",), drop_trigger="search_observations_invocation_topic"),
    # --- A11: partial results kept and marked (RG-4) -------------------------------
    Mutation("A11-completeness-tied-to-coverage", "A11", "completeness no longer tied to the coverage state", (OB + "test_partial_results_are_kept_and_marked_incomplete",),
             old="  CHECK ((coverage_state IN ('searched_ok', 'searched_empty', 'metadata_only')) = (completeness != 'unobserved')),\n", new=""),
    Mutation("A11-searched-empty-only-complete", "A11", "an empty partial page may read as an empty search", (OB + "test_partial_results_are_kept_and_marked_incomplete",),
             old="  CHECK (coverage_state != 'searched_empty' OR completeness = 'complete'),\n", new=""),
    Mutation("A11-partial-says-why", "A11", "a partial result need not name its error class", (OB + "test_partial_results_are_kept_and_marked_incomplete",),
             old="  CHECK (completeness != 'partial' OR error_class IS NOT NULL),\n", new=""),
    Mutation("A11-complete-has-no-error", "A11", "a complete successful search may carry an error", (OB + "test_partial_results_are_kept_and_marked_incomplete",),
             old="  CHECK (coverage_state NOT IN ('searched_ok', 'searched_empty') OR completeness = 'partial' OR error_class IS NULL),", new="  CHECK (1),"),
    Mutation("A11-old-partial-ban", "A11", "over-restriction restored: a partial result may keep no count/error (the review's A11 finding)", (OB + "test_partial_results_are_kept_and_marked_incomplete",),
             old="  CHECK (coverage_state NOT IN ('searched_ok', 'searched_empty') OR completeness = 'partial' OR error_class IS NULL),", new="  CHECK (coverage_state NOT IN ('searched_ok', 'searched_empty') OR error_class IS NULL),"),
    # --- R2.5: draft vocabularies with explicit transition semantics --------------
    *(Mutation(f"R2.5-queue-{key}", "R2.5", desc, (VO + "test_queue_status_transitions",), scope="queue_status_transitions", old=old, new=new)
      for key, desc, old, new in (
          ("revive-retired", "retired topics may be requeued", "  OR (OLD.status = 'completed_with_qualified_conclusions' AND NEW.status IN ('queued', 'retired')))",
           "  OR (OLD.status = 'completed_with_qualified_conclusions' AND NEW.status IN ('queued', 'retired'))\n  OR (OLD.status = 'retired' AND NEW.status = 'queued'))"),
          ("skip-intake", "intake may jump straight to active", "(OLD.status = 'awaiting_brief_confirmation' AND NEW.status IN ('scoping', 'retired'))",
           "(OLD.status = 'awaiting_brief_confirmation' AND NEW.status IN ('scoping', 'active', 'retired'))"),
          ("complete-from-queued", "a queued (never active) topic may complete", "(OLD.status = 'queued' AND NEW.status IN ('active', 'held', 'capability_blocked', 'retired'))",
           "(OLD.status = 'queued' AND NEW.status IN ('active', 'held', 'capability_blocked', 'completed_with_qualified_conclusions', 'retired'))"),
          ("resource-stop-as-completion", "a resource stop may be relabeled as completion", "(OLD.status = 'stopped_for_resources' AND NEW.status IN ('queued', 'awaiting_judgment', 'retired'))",
           "(OLD.status = 'stopped_for_resources' AND NEW.status IN ('queued', 'awaiting_judgment', 'completed_with_qualified_conclusions', 'retired'))"),
          ("drop-contract-approval-to-queued", "over-restriction: an approved contract can no longer be queued",
           "(OLD.status = 'awaiting_contract_approval' AND NEW.status IN ('queued', 'scoping', 'retired'))", "(OLD.status = 'awaiting_contract_approval' AND NEW.status IN ('scoping', 'retired'))"))),
    *(Mutation(f"R2.5-claim-{key}", "R2.5", desc, (VO + "test_claim_status_transitions",), scope="claims_status_transitions", old=old, new=new)
      for key, desc, old, new in (
          ("revive-superseded", "a superseded claim may return to provisional", "  OR (OLD.status = 'rejected' AND NEW.status = 'superseded'))",
           "  OR (OLD.status = 'rejected' AND NEW.status = 'superseded')\n  OR (OLD.status = 'superseded' AND NEW.status = 'provisional'))"),
          ("rejected-to-support", "a rejected claim may become accepted support", "(OLD.status = 'rejected' AND NEW.status = 'superseded')",
           "(OLD.status = 'rejected' AND NEW.status IN ('superseded', 'accepted_support'))"),
          ("quarantine-to-support", "a quarantined claim may skip re-capture straight to support", "(OLD.status = 'quarantined' AND NEW.status IN ('provisional', 'rejected', 'superseded'))",
           "(OLD.status = 'quarantined' AND NEW.status IN ('provisional', 'accepted_support', 'rejected', 'superseded'))"),
          ("drop-provisional-to-support", "over-restriction: a provisional claim can no longer be accepted",
           "(OLD.status = 'provisional' AND NEW.status IN ('accepted_support', 'contested', 'rejected', 'quarantined', 'superseded'))",
           "(OLD.status = 'provisional' AND NEW.status IN ('contested', 'rejected', 'quarantined', 'superseded'))"))),
    Mutation("R2.5-mandatory-signals-not-model-raised", "R2.5", "a model observation may raise (and so be ranked below) a retraction signal",
             (VO + "test_mandatory_signals_are_code_or_operator_raised",), old=",\n  CHECK (reason_code NOT IN ('retraction', 'decision_record_change') OR signal_source IN ('deterministic', 'operator'))", new=""),
    # --- A8 (checker), and the Python-side A1/A11 guards: file-target mutants ---------
    Mutation("A8-global-alias-map", "A8", "the original bug: one last-wins alias map for the whole file", (CB + "test_alias_reuse_in_another_scope_does_not_hide_a_capability",),
             target="tools/check_boundaries.py", old="        scope = self._target_scope(name)\n        scope.bound.add(name)\n        if import_target is not None:\n            if name in scope.nonlocal_names:",
             new="        scope = self.scope.module()\n        scope.bound.add(name)\n        if import_target is not None:\n            scope.imports[name] = set()  # last binding wins, file-wide\n            if name in scope.nonlocal_names:"),
    Mutation("A8-global-declaration-ignored", "A8", "`global y; import os as y` treated as a local binding", (CB + "test_alias_reuse_in_another_scope_does_not_hide_a_capability",),
             target="tools/check_boundaries.py", old="        if name in self.scope.global_names:\n            return self.scope.module()\n        return self.scope", new="        return self.scope"),
    Mutation("A8-builtins-import-alias", "A8", "`from builtins import eval as evaluate` not reported", (CB + "test_forbidden_builtin_calls",),
             target="tools/check_boundaries.py", old='        if target.startswith("builtins.") and target.split(".", 1)[1] in forbidden:', new='        if False:'),
    Mutation("A8-builtins-module-alias", "A8", "`import builtins as b; b.exec(...)` not reported", (CB + "test_forbidden_builtin_calls",),
             target="tools/check_boundaries.py", old='            if base == "builtins" and chain[1] and chain[1][0] in forbidden:', new='            if False:'),
    Mutation("A8-dunder-builtins", "A8", "`__builtins__[...]` not reported", (CB + "test_forbidden_builtin_calls",),
             target="tools/check_boundaries.py", old='        if node.id == "__builtins__":\n            refs.append((node.lineno, "__builtins__", "builtin", ""))\n        elif', new='        if'),
    Mutation("A8-bare-references", "A8", "forbidden builtins reached by name are no longer reported", (CB + "test_forbidden_builtin_calls",),
             target="tools/check_boundaries.py", old="        elif node.id in forbidden:", new="        elif False:"),
    Mutation("A8-unscoped-builtin-names", "A8", "over-restriction: any name spelled like a builtin is flagged (re.compile, parameters)", (CB + "test_shadowed_names_are_not_builtins",),
             target="tools/check_boundaries.py", old='            if targets is None or any(t == f"builtins.{node.id}" for t in targets):', new='            if True:'),
    # --- RA7: signature expressions, nonlocal imports, posix; the review's 3 scope survivors ---
    *(Mutation(f"RA7-{key}", "RA7", desc, tuple(CB + k for k in killers), target="tools/check_boundaries.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("annotations-not-visited", "the review's probe: parameter annotations are not visited (def f(x: eval('1')))",
           ("test_forbidden_builtin_calls", "test_review_ra7_reproductions_under_the_real_graph"),
           ",\n                     *(a.annotation for a in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg) if a is not None)", ""),
          ("returns-not-visited", "return annotations are not visited", ("test_forbidden_builtin_calls",),
           "*args.kw_defaults, node.returns,", "*args.kw_defaults,"),
          ("type-params-not-visited", "type-parameter bounds are not visited", ("test_forbidden_builtin_calls",),
           '        for param in getattr(node, "type_params", ()):', "        for param in ():"),
          ("nonlocal-import-binds-locally", "the review's probe: `nonlocal x; import os as x` binds only the inner scope",
           ("test_review_ra7_reproductions_under_the_real_graph",), "            if name in scope.nonlocal_names:", "            if False:"),
          ("class-scope-visible", "Astra's survivor: a class body is treated as visible to its methods",
           ("test_scope_resolution_witnesses",), 'visible = scope is start or scope.kind != "class"', "visible = True"),
          ("walrus-binds-in-comprehension", "Astra's survivor: a comprehension walrus binds inside the comprehension",
           ("test_scope_resolution_witnesses",),
           '        while scope.kind == "comprehension" and scope.parent is not None:  # PEP 572: binds in the enclosing scope\n            scope = scope.parent\n', ""),
          ("global-ignored-in-resolution", "Astra's survivor: `global` is ignored when resolving a reference",
           ("test_scope_resolution_witnesses",), "    if name in scope.global_names:\n        scope = scope.module()\n    while scope is not None:", "    while scope is not None:"))),
    Mutation("RA7-real-graph-posix", "RA7", "the review's probe: posix (the module behind os) unrestricted in the real graph",
             (CB + "test_review_ra7_reproductions_under_the_real_graph", CB + "test_real_graph_restricts_low_level_and_alternate_surfaces"),
             target="gen2/boundaries.toml", old='"posix", ', new=""),
    Mutation("RA7-real-graph-nt", "RA7", "nt (the Windows module behind os) unrestricted in the real graph",
             (CB + "test_real_graph_restricts_low_level_and_alternate_surfaces",), target="gen2/boundaries.toml", old='"nt", ', new=""),
    *(Mutation(f"A8-real-graph-{name.strip('_')}", "A8", f"{name} dropped from the real restricted list", (CB + "test_real_graph_restricts_low_level_and_alternate_surfaces",),
               target="gen2/boundaries.toml", old=f'"{name}", ', new="")
      for name in ("_sqlite3", "_posixsubprocess", "imaplib")),
    Mutation("A1-replace-lint", "A1", "the REPLACE lint no longer runs", (CB + "test_replace_sql_in_a_store_write_path_fails",),
             target="tools/check_boundaries.py", old="    if mod.name not in cfg.forbidden_sql_exempt:", new="    if False:"),
    Mutation("A1-ddl-rule-delete-guards", "A1", "the build no longer requires a delete guard on every table", (DR + "test_table_without_delete_guard_fails", DR + "test_conditional_delete_guard_does_not_count"),
             target="tools/check_gen2_schemas.py", old="        if not guarded:", new="        if False:"),
    Mutation("A1-ddl-rule-on-conflict", "A1", "the build no longer refuses ON CONFLICT clauses", (DR + "test_on_conflict_replace_clause_fails",),
             target="tools/check_gen2_schemas.py", old='    if re.search(r"\\bON\\s+CONFLICT\\b", _strip_sql_comments(text), re.IGNORECASE):', new="    if False:"),
    Mutation("A1-ddl-rule-pragmas", "A1", "the build no longer reads the connection pragmas back (contract executed, not gated)", (DR + "test_connection_contract_without_recursive_triggers_fails",),
             target="tools/check_gen2_schemas.py", old='        compat.apply_connection_contract(conn, (root / conn_rel).read_text(encoding="utf-8"))',
             new='        conn.executescript((root / conn_rel).read_text(encoding="utf-8"))'),
    Mutation("SQLC-build-skips-library-gate", "0b-R4", "the DDL check no longer runs the store's SQLite gate on the build's SQLite", (DR + "test_refused_sqlite_fails_the_ddl_check",),
             target="tools/check_gen2_schemas.py", old="        compat.check_library(conn)\n    except compat.StoreCompatibilityError as exc:\n        conn.close()",
             new="        pass\n    except compat.StoreCompatibilityError as exc:\n        conn.close()"),
    Mutation("SQLC-build-unprobed-json", "0b-R4", "the DDL check no longer refuses a JSON function the gate does not probe", (DR + "test_json_function_without_a_gate_probe_fails",),
             target="tools/check_gen2_schemas.py", old="    if unprobed:", new="    if False:"),
    Mutation("A11-instants-calendar", "A11", "timestamps checked for shape only (February 31 accepted)", (IN + "test_impossible_or_malformed_instants_refused",),
             target="gen2/core/instants.py", old="        datetime(*(int(part) for part in match.groups()))\n", new="        pass\n"),
    Mutation("A11-instants-utc-only", "A11", "offsets other than Z accepted", (IN + "test_impossible_or_malformed_instants_refused",),
             target="gen2/core/instants.py", old=r"(?:\.[0-9]{1,9})?Z\Z", new=r"(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"),
    # Astra's independent survivors (re-review), now killed; and the ASCII cleanup
    Mutation("A11-instants-empty-fraction", "A11", "Astra's survivor: a decimal point with no fraction digits accepted", (IN + "test_impossible_or_malformed_instants_refused",),
             target="gen2/core/instants.py", old=r"(?:\.[0-9]{1,9})?Z\Z", new=r"(?:\.[0-9]{0,9})?Z\Z"),
    Mutation("A11-instants-pre-1970", "A11", "Astra's survivor: real instants before 1970 refused", (IN + "test_real_instants_accepted",),
             target="gen2/core/instants.py", old="    if match is None:\n        return False\n", new="    if match is None or int(match.group(1)) < 1970:\n        return False\n"),
    Mutation("A11-instants-unicode-digits", "A11", "the helper's \\d admits Unicode decimal digits the schema's ASCII pattern refuses", (IN + "test_impossible_or_malformed_instants_refused",),
             target="gen2/core/instants.py", old=r'_SHAPE = re.compile(r"\A([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]{1,9})?Z\Z")',
             new=r'_SHAPE = re.compile(r"\A(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?Z\Z")'),
    Mutation("A11-instants-strings-only", "A11", "non-strings accepted", (IN + "test_non_strings_refused",),
             target="gen2/core/instants.py", old="    if not isinstance(value, str):\n        return False", new="    if not isinstance(value, str):\n        return True"),
    # --- R1: RFC 8785 JCS canonicalization; raw bytes kept raw -------------------------
    *(Mutation(f"R1-{key}", "R1", desc, tuple(CN + k for k in killers), target="gen2/core/canonical.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("sort-keys-is-not-jcs", "json.dumps(sort_keys=True) substituted for JCS (the ruling's explicit counterexample)",
           ("PublishedVectorsTest.test_rfc_3_2_3_utf16_property_order", "PublishedVectorsTest.test_cross_implementation_vectors"),
           "        return rfc8785.dumps(value)", '        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")'),
          ("duplicate-keys-merged", "duplicate keys silently merged (last wins)", ("StrictBoundaryTest.test_parse_rejects",),
           "        if key in out:\n            raise CanonicalizationError(f\"duplicate object key {key!r}\")\n", ""),
          ("precision-lost-silently", "precision-losing literals rounded instead of refused", ("StrictBoundaryTest.test_parse_rejects",),
           "        if Decimal(repr(value)) != Decimal(text):", "        if False:"),
          ("integers-unbounded", "integers beyond 2**53-1 accepted by the strict parser", ("StrictBoundaryTest.test_parse_rejects",),
           "        if abs(value) > INT_BOUND:", "        if False:"),
          ("lone-surrogates-accepted", "invalid Unicode (lone surrogates) accepted by the strict parser", ("StrictBoundaryTest.test_parse_rejects",),
           "            value.encode(\"utf-8\")\n", "            pass\n"),
          ("fingerprint-drops-lease", "an authority-bearing field (lease) excluded from the fingerprint",
           ("HashSemanticsTest.test_semantically_changed_envelopes_fingerprint_differently", "HashSemanticsTest.test_contract_versions_are_declared"),
           'FINGERPRINT_EXCLUDES = ("submitted_at",)', 'FINGERPRINT_EXCLUDES = ("submitted_at", "lease")'),
          ("fingerprint-keeps-submitted-at", "submitted_at (non-identity metadata) included in the fingerprint",
           ("HashSemanticsTest.test_request_fingerprint_excludes_exactly_submitted_at",), 'FINGERPRINT_EXCLUDES = ("submitted_at",)', "FINGERPRINT_EXCLUDES = ()"),
          ("content-hash-covers-itself", "a document's content hash covers its own content_hash field",
           ("HashSemanticsTest.test_content_hash_excludes_exactly_itself",), 'CONTENT_HASH_EXCLUDES = ("content_hash",)', "CONTENT_HASH_EXCLUDES = ()"),
          ("raw-bytes-canonicalized", "raw provider bytes canonicalized before hashing (the ruling's false-provenance case)",
           ("HashSemanticsTest.test_raw_bytes_are_hashed_raw_never_canonicalized",), "    return _sha256(bytes(raw))", "    return logical_hash(parse_json_strict(bytes(raw)))"),
          # Astra's independent survivors (re-review), now killed
          ("underflow-to-zero", "Astra's survivor: a numeral that underflows is accepted as 0.0", ("StrictBoundaryTest.test_parse_rejects",),
           "        if Decimal(repr(value)) != Decimal(text):", "        if value != 0 and Decimal(repr(value)) != Decimal(text):"),
          ("raw-bytes-stripped", "Astra's survivor: retained bytes stripped of leading/trailing whitespace before hashing",
           ("HashSemanticsTest.test_raw_bytes_are_hashed_raw_never_canonicalized",), "    return _sha256(bytes(raw))", "    return _sha256(bytes(raw).strip())"),
          ("bytes-decoded-as-ascii", "Astra's survivor: JSON bytes decoded as ASCII, not UTF-8", ("StrictBoundaryTest.test_parse_decodes_bytes_as_utf8",),
           '            text = text.decode("utf-8")', '            text = text.decode("ascii")'),
          # RA8: identity bounds by value
          ("identity-bounded-by-type", "the review's RA8 probe: only int identities are bounded (9007199254740992.0 / ...e0 pass)",
           ("StrictBoundaryTest.test_identity_bound_holds_by_value_in_every_notation",),
           "    if not minimum <= value <= INT_BOUND:", "    if isinstance(value, int) and not minimum <= value <= INT_BOUND:"),
          ("identity-non-integral", "a non-integral float passes as an identity", ("StrictBoundaryTest.test_identity_bound_holds_by_value_in_every_notation",),
           "    if isinstance(value, float) and not (math.isfinite(value) and value.is_integer()):", "    if isinstance(value, float) and not math.isfinite(value):"),
          ("identity-bool", "a JSON boolean passes as an identity", ("StrictBoundaryTest.test_identity_bound_holds_by_value_in_every_notation",),
           "    if isinstance(value, bool) or not isinstance(value, (int, float)):", "    if not isinstance(value, (int, float)):"))),
    # --- 0b: the SQLite compatibility gate (Astra third review ruling 4) and the store's open path ----
    *(Mutation(f"SQLC-{key}", "0b-R4", desc, tuple(SG + k for k in killers), target="gen2/store/compat.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("version-string-compare", "the version compared as a string (3.9.0 passes, 3.100.0 is refused)",
           ("VersionFloorTest.test_version_is_compared_as_numbers",), "    if not meets_floor(version):", '    if reported < ".".join(map(str, SQLITE_FLOOR)):'),
          ("version-unanchored", "a version with trailing text parsed as its prefix instead of refused",
           ("VersionFloorTest.test_unparseable_version_is_refused_not_guessed",),
           r'_VERSION = re.compile(r"\A([0-9]+)\.([0-9]+)\.([0-9]+)\Z")', r'_VERSION = re.compile(r"\A([0-9]+)\.([0-9]+)\.([0-9]+)")'),
          ("json-not-probed", "JSON never probed: the version check alone admits a JSON-less build",
           ("JsonCapabilityTest.test_missing_json_function_is_refused_at_a_passing_version", "JsonCapabilityTest.test_json_function_answering_wrongly_is_refused"),
           "    for name, sql, expected in JSON_PROBES:", "    for name, sql, expected in ():"),
          ("json-presence-only", "a JSON function that exists but answers wrongly is accepted",
           ("JsonCapabilityTest.test_json_function_answering_wrongly_is_refused",), "        if got != expected:", "        if False:"),
          ("pragmas-not-read-back", "the connection contract executed but its pragmas never read back",
           ("ConnectionContractGateTest.test_a_contract_without_a_required_pragma_is_refused", "ConnectionContractGateTest.test_a_misspelled_pragma_does_not_pass_silently"),
           "        if row != (1,):", "        if False:"),
          ("required-pragmas-from-file-only", "only the pragmas the contract file names are read back (a file dropping one is trusted)",
           ("ConnectionContractGateTest.test_a_contract_without_a_required_pragma_is_refused", "ConnectionContractGateTest.test_a_misspelled_pragma_does_not_pass_silently"),
           "[*REQUIRED_PRAGMAS, *pragmas_set_by(text)]", "[*pragmas_set_by(text)]"))),
    *(Mutation(f"DBO-{key}", "0b-R4", desc, tuple(SG + k for k in killers), target="gen2/store/db.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("gate-after-open", "the library is checked only on the durable connection, after the path is created",
           ("OpenStoreTest.test_refused_library_creates_nothing_on_disk",),
           "        compat.check_connection(probe)  # the library itself; nothing on disk exists or is opened yet", "        pass"),
          ("implicit-create", "a missing store is opened as if it existed (no startup error)",
           ("OpenStoreTest.test_missing_store_is_an_error_not_a_mode",), "    if not create and not path.is_file():", "    if False:"),
          ("create-over-existing", "create proceeds over an existing file",
           ("OpenStoreTest.test_create_refuses_an_existing_path",), "    if create and path.exists():", "    if False:"),
          ("durable-contract-skipped", "the durable connection gets the library check but not the connection contract",
           ("OpenStoreTest.test_created_store_reopens_with_the_contract_applied",),
           "        observed = compat.check_connection(conn)  # the durable connection: contract applied and read back here",
           "        observed = compat.check_library(conn)"),
          ("no-schema-identity", "an existing store is admitted whatever its schema",
           ("OpenStoreTest.test_a_store_with_another_schema_is_not_admitted",), "        check_schema_identity(conn)\n    except BaseException:", "        pass\n    except BaseException:"),
          ("schema-names-only", "schema identity compares object names, not their SQL (a weakened guard passes)",
           ("OpenStoreTest.test_a_store_with_another_schema_is_not_admitted",),
           "    changed = sorted(f\"{k} {n}\" for (k, n) in expected.keys() & actual.keys() if expected[(k, n)] != actual[(k, n)])", "    changed = []"),
          ("user-version-ignored", "another schema version is admitted",
           ("OpenStoreTest.test_a_store_with_another_schema_is_not_admitted",),
           "    if missing or extra or changed or stored_version != version:", "    if missing or extra or changed:"))),
    # --- 0b carried requirements: writer-side JCS storage and identity bounds (RA2/RA8 rulings) ----
    *(Mutation(f"WR-{key}", "0b-writer", desc, tuple("test_writer." + k for k in killers), target="gen2/store/api.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("json-not-canonicalized", "JSON values stored as json.dumps output, not JCS",
           ("CanonicalStorageTest.test_json_is_stored_in_its_jcs_form", "CanonicalStorageTest.test_canonical_storage_makes_equal_entries_equal_text"),
           '                return canonical.canonical_bytes(parsed).decode("utf-8")', '                return __import__("json").dumps(parsed)'),
          ("text-stored-as-given", "JSON text from the caller stored as given (only parsed values canonicalized)",
           ("CanonicalStorageTest.test_json_is_stored_in_its_jcs_form",),
           '                parsed = canonical.parse_json_strict(value) if isinstance(value, (str, bytes)) else value\n',
           '                if isinstance(value, str):\n                    return value\n                parsed = canonical.parse_json_strict(value) if isinstance(value, bytes) else value\n'),
          ("identity-unbounded", "identity columns written without the RA8 bound (insert, update and advance share it)",
           ("IdentityBoundTest.test_identity_columns_are_bounded_by_value_on_insert", "IdentityBoundTest.test_advance_is_bounded_and_compare_and_set"),
           "                    return canonical.identity_integer(value)", "                    return value"),
          ("sequence-unbounded", "a generated next value is returned past 2**53-1",
           ("IdentityBoundTest.test_a_generated_increment_past_the_bound_writes_nothing",),
           "            return canonical.identity_integer((current or 0) + 1)", "            return (current or 0) + 1"),
          ("no-rollback", "a failing transaction commits what it wrote before the failure",
           ("IdentityBoundTest.test_a_generated_increment_past_the_bound_writes_nothing", "WritePathTest.test_a_ddl_refusal_propagates_and_rolls_back_the_transaction",
            "WritePathTest.test_a_refusal_at_commit_rolls_back_and_the_store_stays_usable"),
           '        try:\n            self._conn.execute("ROLLBACK")', '        try:\n            self._conn.execute("COMMIT")'),
          ("autocommit-writes", "writes accepted outside a transaction",
           ("WritePathTest.test_writes_run_inside_a_transaction",), "        if not (self._in_transaction and self._conn.in_transaction):", "        if False:"),
          # Astra 0b review A1: the whole transaction lifecycle, COMMIT included
          ("A1-rollback-unconditional", "ROLLBACK issued even when SQLite already ended the transaction (its error closes the store)",
           ("WritePathTest.test_a_transaction_sqlite_already_ended_is_not_rolled_back_again",),
           "        if not self._conn.in_transaction:\n            return\n        try:\n", "        try:\n"),
          ("A1-rollback-failure-ignored", "a failed ROLLBACK is ignored: the connection stays open inside the failed transaction",
           ("WritePathTest.test_a_failed_rollback_closes_the_connection_and_the_store_refuses_use",),
           '        except BaseException as rollback_error:\n            self._close_unusable(f"ROLLBACK failed ({rollback_error!r})", exc)\n',
           "        except BaseException as rollback_error:\n            pass\n"),
          ("A1-closed-store-reused", "a Store whose connection was closed after a failed rollback is used again",
           ("WritePathTest.test_a_failed_rollback_closes_the_connection_and_the_store_refuses_use",), "        if self._unusable is not None:", "        if False:"),
          ("A1-any-open-transaction-admits-writes", "writes accepted inside any transaction SQLite reports, not only the Store's own",
           ("WritePathTest.test_writes_need_the_stores_own_transaction",),
           "        if not (self._in_transaction and self._conn.in_transaction):", "        if not self._conn.in_transaction:"),
          ("measures-unbounded", "non-identity integers written past +/-(2**53-1)",
           ("IdentityBoundTest.test_other_integers_stay_json_interoperable",), " or abs(value) > canonical.INT_BOUND:", ":"),
          ("bool-as-measure", "a boolean accepted as a non-flag integer",
           ("IdentityBoundTest.test_other_integers_stay_json_interoperable",),
           '                raise StoreWriteError(f"{table}.{column}: a boolean is not an integer here")', "                return int(value)"),
          ("update-many-rows", "an update matching several rows is accepted",
           ("WritePathTest.test_an_update_touches_exactly_one_row",), "        if cursor.rowcount != 1:", "        if cursor.rowcount == 0:"),
          ("unknown-names-passed", "a table name outside the schema reaches the SQL text",
           ("WritePathTest.test_names_come_from_the_schema_only",),
           '        if table not in self._columns:\n            raise StoreWriteError(f"unknown table {table!r}")\n        known = self._columns[table]',
           "        known = self._columns.get(table, {})"))),
    # --- 0b: the hashing contract recorded (and frozen) on receipts (Astra 0a ruling R1) ----
    *(Mutation(f"C13-{key}", "0b-R1-freeze", desc, tuple("test_store_ddl.HashContractTest." + k for k in killers), scope=scope, old=old, new=new)
      for key, desc, killers, scope, old, new in (
          ("commit-contract-unchecked", "a commit receipt may record any hashing contract, or none",
           ("test_commit_receipt_records_the_frozen_contracts", "test_frozen_versions_agree_across_ddl_schema_and_helper"), "operation_receipts",
           "  CONSTRAINT operation_receipts_hash_contract_frozen CHECK (\n        coalesce(json_extract(receipt, '$.hash_contract.canonicalization'), '') IN ('jcs-rfc8785/1')\n    AND coalesce(json_extract(receipt, '$.hash_contract.fingerprint'), '') IN ('commit-fingerprint/1'))",
           "  CHECK (1)"),
          ("commit-fingerprint-unchecked", "a commit receipt's fingerprint contract is not checked",
           ("test_commit_receipt_records_the_frozen_contracts",), "operation_receipts",
           "\n    AND coalesce(json_extract(receipt, '$.hash_contract.fingerprint'), '') IN ('commit-fingerprint/1'))", ")"),
          ("commit-absent-passes", "an absent contract passes (a NULL CHECK result is a pass)",
           ("test_commit_receipt_records_the_frozen_contracts",), "operation_receipts",
           "        coalesce(json_extract(receipt, '$.hash_contract.canonicalization'), '') IN ('jcs-rfc8785/1')\n    AND coalesce(json_extract(receipt, '$.hash_contract.fingerprint'), '') IN ('commit-fingerprint/1'))",
           "        json_extract(receipt, '$.hash_contract.canonicalization') IN ('jcs-rfc8785/1')\n    AND json_extract(receipt, '$.hash_contract.fingerprint') IN ('commit-fingerprint/1'))"),
          ("decision-contract-unchecked", "a decision receipt may record any canonicalization contract, or none",
           ("test_decision_receipt_records_the_frozen_canonicalization_only",), "decision_receipts",
           "        coalesce(json_extract(receipt, '$.hash_contract.canonicalization'), '') IN ('jcs-rfc8785/1')\n    AND json_type(receipt, '$.hash_contract.fingerprint') IS NULL),",
           "        1),"),
          ("decision-claims-fingerprint", "a decision receipt may name a fingerprint contract it has no fingerprint for",
           ("test_decision_receipt_records_the_frozen_canonicalization_only",), "decision_receipts",
           "\n    AND json_type(receipt, '$.hash_contract.fingerprint') IS NULL),", "),"))),
    Mutation("WR-A1-commit-unprotected", "0b-writer", "the review's shape: COMMIT after the rollback path (a deferred-FK refusal leaves the transaction open)",
             ("test_writer.WritePathTest.test_a_refusal_at_commit_rolls_back_and_the_store_stays_usable",), target="gen2/store/api.py",
             old='            yield self\n            self._conn.execute("COMMIT")\n', new="            yield self\n",
             also=(("        finally:\n            self._in_transaction = False\n",
                    '        finally:\n            self._in_transaction = False\n        self._conn.execute("COMMIT")\n'),)),
    # --- 0b repair A4: no unchecked route to a Store --------------------------------
    *(Mutation(f"WR-A4-{key}", "0b-A4", desc, tuple(SG + "OpenStoreTest." + k for k in killers), target="gen2/store/api.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("constructor-unchecked", "the review's reproduction: Store(connection, {}) admits a caller-built store",
           ("test_a_store_is_made_only_through_a_checked_route", "test_refused_library_creates_nothing_on_disk"),
           "        if _admitted_by is not _ADMITTED:", "        if False:"),
          ("adoption-ungated", "adoption takes the connection's pragmas on trust (no gate, no contract read-back)",
           ("test_a_store_is_made_only_through_a_checked_route", "test_refused_library_creates_nothing_on_disk"),
           "    observed = compat.check_connection(conn)\n    db.check_schema_identity(conn)\n",
           '    observed = {"pragmas": {"foreign_keys": 1, "recursive_triggers": 1}}\n    db.check_schema_identity(conn)\n'),
          ("adoption-any-schema", "adoption admits a connection whatever its schema",
           ("test_a_store_is_made_only_through_a_checked_route",),
           "    observed = compat.check_connection(conn)\n    db.check_schema_identity(conn)\n", "    observed = compat.check_connection(conn)\n"),
          ("adoption-of-a-file", "a durable file is adopted, bypassing open_store",
           ("test_a_store_is_made_only_through_a_checked_route",), "    if files:\n", "    if False:\n"),
          ("adoption-inside-a-transaction", "a connection with a transaction open is adopted",
           ("test_a_store_is_made_only_through_a_checked_route",), "    if conn.in_transaction:\n        raise db.StoreOpenError(\"adopt_in_memory", "    if False:\n        raise db.StoreOpenError(\"adopt_in_memory"),
          ("adoption-not-autocommit", "a connection Python opens transactions on implicitly is adopted",
           ("test_a_store_is_made_only_through_a_checked_route",), "    if conn.isolation_level is not None:", "    if False:"))),
    Mutation("C13-writer-unchecked", "0b-R1-freeze", "the writer does not check a receipt's recorded hash contract (only the DDL would)",
             ("test_writer.ReceiptHashContractWriterTest.test_commit_receipt_contract_checked_before_sql",
              "test_writer.ReceiptHashContractWriterTest.test_decision_receipt_contract_checked_before_sql"),
             target="gen2/store/api.py", old="        self._check_hash_contract(table, prepared)\n", new=""),
    # --- 0b: durable intake briefs (G-4, C-12, G-13; INVARIANTS §13) ------------------
    *(Mutation(f"IB-{key}-dropped", "0b-intake", desc, tuple(IB + k for k in killers), drop_trigger=trigger)
      for key, desc, killers, trigger in (
          ("created-awaiting", "a brief may be inserted confirmed, overdue or closed", ("test_a_brief_is_written_awaiting_confirmation_with_owner_and_deadline",),
           "intake_briefs_created_awaiting"),
          ("transitions", "any brief status move is allowed", ("test_cancellation_and_archival_are_explicit_and_final",), "intake_briefs_status_transitions"),
          ("confirmation-bound", "a brief may be confirmed under any decision", ("test_confirmation_names_an_approved_decision_about_exactly_this_version",),
           "intake_briefs_confirmation_bound"),
          ("pointer", "the confirming decision may be recorded without the transition, or changed after", ("test_confirmation_names_an_approved_decision_about_exactly_this_version",),
           "intake_briefs_confirmation_pointer_set_by_confirmation"),
          ("superseded-by-later", "a version may be superseded with no later version", ("test_a_version_is_superseded_only_by_a_later_one_and_one_is_confirmed",),
           "intake_briefs_superseded_by_a_later_version"),
          ("overdue", "overdue may be re-marked, cleared, set on a confirmed brief or with a status change", ("test_expiry_marks_overdue_and_never_advances",),
           "intake_briefs_overdue_marks_only"),
          ("content", "a brief version's content, lineage, owner or deadline may change", ("test_content_lineage_owner_and_deadline_are_immutable",),
           "intake_briefs_content_immutable"),
          ("terminal", "a cancelled/superseded/archived version may still change", ("test_cancellation_and_archival_are_explicit_and_final",),
           "intake_briefs_terminal_immutable"),
          ("delete-guard", "intake briefs may be deleted or REPLACEd", ("test_content_lineage_owner_and_deadline_are_immutable",), "intake_briefs_no_delete"),
          ("queue-gate", "a topic leaves intake without a confirmed brief (G-4)", ("test_an_unconfirmed_brief_cannot_advance_the_topic",),
           "queue_scoping_needs_confirmed_brief"))),
    *(Mutation(f"IB-{key}", "0b-intake", desc, tuple(IB + k for k in killers), scope=scope, old=old, new=new)
      for key, desc, killers, scope, old, new in (
          ("archive-from-awaiting", "an unconfirmed brief may be archived instead of cancelled", ("test_cancellation_and_archival_are_explicit_and_final",),
           "intake_briefs_status_transitions", "(OLD.status = 'confirmed' AND NEW.status IN ('superseded', 'archived'))",
           "(OLD.status IN ('confirmed', 'awaiting_confirmation') AND NEW.status IN ('superseded', 'archived'))"),
          ("confirmation-kind", "any decision kind confirms", ("test_confirmation_names_an_approved_decision_about_exactly_this_version",),
           "intake_briefs_confirmation_bound", "    AND d.kind = 'brief_confirmation' AND d.disposition = 'approved'\n", "    AND d.disposition = 'approved'\n"),
          ("confirmation-disposition", "a rejected confirmation confirms", ("test_confirmation_names_an_approved_decision_about_exactly_this_version",),
           "intake_briefs_confirmation_bound", "    AND d.kind = 'brief_confirmation' AND d.disposition = 'approved'\n", "    AND d.kind = 'brief_confirmation'\n"),
          ("confirmation-subject", "an approved confirmation of any brief of the topic confirms (subject conjuncts removed together)",
           ("test_confirmation_names_an_approved_decision_about_exactly_this_version",), "intake_briefs_confirmation_bound",
           "\n    AND d.subject_ref = NEW.brief_id AND d.subject_revision = NEW.version AND d.subject_hash = NEW.content_hash)", ")"),
          ("pointer-changes-after", "the recorded confirming decision may be swapped for another valid one", ("test_confirmation_names_an_approved_decision_about_exactly_this_version",),
           "intake_briefs_confirmation_pointer_set_by_confirmation", "  AND (OLD.status IS NOT 'awaiting_confirmation' OR ", "  AND ("),
          ("pointer-without-transition", "the confirming decision may be recorded without the confirming transition",
           ("test_confirmation_names_an_approved_decision_about_exactly_this_version",),
           "intake_briefs_confirmation_pointer_set_by_confirmation", " OR NEW.status IS NOT 'confirmed')", ")"),
          ("overdue-remarked", "overdue may be re-marked or cleared", ("test_expiry_marks_overdue_and_never_advances",),
           "intake_briefs_overdue_marks_only", "  AND (OLD.overdue_since IS NOT NULL OR ", "  AND ("),
          ("overdue-advances", "marking overdue may carry a status change with it", ("test_expiry_marks_overdue_and_never_advances",),
           "intake_briefs_overdue_marks_only", " OR NEW.status IS NOT OLD.status)", ")"),
          ("overdue-on-confirmed", "a confirmed brief may be marked overdue", ("test_expiry_marks_overdue_and_never_advances",),
           "intake_briefs_overdue_marks_only", " OR OLD.status IS NOT 'awaiting_confirmation'", ""),
          ("queue-gate-any-brief", "an unconfirmed (awaiting or cancelled) brief lets a topic leave intake", ("test_an_unconfirmed_brief_cannot_advance_the_topic",),
           "queue_scoping_needs_confirmed_brief", " AND b.status = 'confirmed')", ")"),
          ("queue-gate-any-topic", "another topic's confirmed brief lets this topic leave intake", ("test_an_unconfirmed_brief_cannot_advance_the_topic",),
           "queue_scoping_needs_confirmed_brief", "WHERE b.topic_id = NEW.topic_id AND b.status", "WHERE b.status"),
          ("parent-earlier", "a brief version may name itself (or a later version) as its parent", ("test_content_lineage_owner_and_deadline_are_immutable",),
           "intake_briefs", "  CONSTRAINT intake_brief_parent_is_earlier CHECK (parent_version IS NULL OR parent_version < version),\n", ""),
          ("closed-iff-cancelled-archived", "a brief may be cancelled or archived without recording the act", ("test_cancellation_and_archival_are_explicit_and_final",),
           "intake_briefs", "  CHECK ((status IN ('cancelled', 'archived')) = (closed_at IS NOT NULL)),\n", ""),
          ("closed-fields-together", "the closing act may omit its actor", ("test_cancellation_and_archival_are_explicit_and_final",),
           "intake_briefs", "  CHECK ((closed_by IS NULL) = (closed_at IS NULL) AND (closed_at IS NULL) = (close_reason IS NULL)),\n", ""),
          ("document-binding", "the brief document may describe another topic, brief, version, lineage, time or hash than its row",
           ("test_a_brief_is_written_awaiting_confirmation_with_owner_and_deadline",), "intake_briefs",
           "  CHECK (json_extract(document, '$.topic_id') IS topic_id\n     AND json_extract(document, '$.brief_id') IS brief_id\n     AND json_extract(document, '$.version') IS version\n     AND json_extract(document, '$.parent_version') IS parent_version\n     AND json_extract(document, '$.created_at') IS created_at\n     AND json_extract(document, '$.content_hash') IS content_hash)\n",
           "  CHECK (1)\n"))),
    Mutation("IB-one-confirmed-per-topic", "0b-intake", "two brief versions of a topic may be confirmed at once",
             (IB + "test_a_version_is_superseded_only_by_a_later_one_and_one_is_confirmed",),
             old="CREATE UNIQUE INDEX intake_briefs_one_confirmed_per_topic\n  ON intake_briefs (topic_id) WHERE status = 'confirmed';\n", new=""),
    Mutation("IB-decision-subject-exists", "0b-intake", "a brief_confirmation may be recorded about a brief that is not stored (G-13 subject existence)",
             (AD + "test_pre_contract_admission_needs_the_confirmed_brief",), scope="operator_decisions_subject_exists",
             old="\n  OR (NEW.subject_kind = 'intake_brief' AND NOT EXISTS (\n        SELECT 1 FROM intake_briefs b\n        WHERE b.topic_id = NEW.topic_id AND b.brief_id = NEW.subject_ref AND b.version = NEW.subject_revision AND b.content_hash = NEW.subject_hash))",
             new=""),
    # --- 0b: the dry-run importer skeleton (reads gen-1 only; surfaces, never resolves) ----
    Mutation("IMP-report-overwrites-open", "0b-importer", "the report may overwrite an existing file (the existence check and the exclusive open removed together)",
             ("test_importer.CommandTest.test_report_is_refused_inside_the_gen1_root_or_over_a_file",), target="gen2/importer/dry_run.py",
             old="        os.stat(target.name, dir_fd=dir_fd, follow_symlinks=False)\n    except FileNotFoundError:\n",
             new="        raise FileNotFoundError\n    except FileNotFoundError:\n",
             also=(("os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW", "os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW"),)),
    *(Mutation(f"IMP-{key}", "0b-importer", desc, tuple("test_importer." + k for k in killers), target="gen2/importer/dry_run.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("managed-store-ignored", "a managed deployment's stale JSON queue is mapped as authority",
           ("ReadOnlyTest.test_managed_store_blocks_and_the_json_queue_is_marked_stale", "CommandTest.test_report_written_outside_and_exit_status_reflects_blocking",
            "ReadOnlyTest.test_managed_store_evidence_is_never_mistaken_for_absence"),
           "    stale = _managed_store(reader, blocking)\n", "    stale = None\n"),
          ("stale-not-marked", "queue records from a stale snapshot are not marked", ("ReadOnlyTest.test_managed_store_blocks_and_the_json_queue_is_marked_stale",),
           "        if stale is not None:\n            for record in records:", "        if False:\n            for record in records:"),
          ("malformed-lines-dropped", "malformed JSONL lines are dropped silently (gen-1 defect §11.9)", ("DryRunMappingTest.test_obligations_sources_and_logs",),
           "    if bad:\n        issues.append(", "    if False:\n        issues.append("),
          ("fleet-invented", "a missing fleet is defaulted", ("DryRunMappingTest.test_without_a_fleet_no_topic_id_is_invented",),
           "    if fleet is None:\n        issues.append(", '    fleet = fleet or "default"\n    if fleet is None:\n        issues.append('),
          ("id-lowercased", "a non-slug gen-1 id is lower-cased silently", ("DryRunMappingTest.test_queue_items_map_with_the_authority_they_lack_named",),
           "    if not TOPIC_SLUG.match(gen1_id):", "    gen1_id = gen1_id.lower()\n    if not TOPIC_SLUG.match(gen1_id):"),
          ("completed-maps", "gen-1 completed maps to gen-2 completion without an operator approval", ("DryRunMappingTest.test_queue_items_map_with_the_authority_they_lack_named",),
           '    "completed": (None, "completion-unapproved",', '    "completed": ("completed_with_qualified_conclusions", "completion-unapproved",'),
          ("running-maps", "live gen-1 execution maps to an active topic", ("DryRunMappingTest.test_queue_items_map_with_the_authority_they_lack_named",),
           '    "running": (None, "live-execution",', '    "running": ("active", "live-execution",'),
          ("identity-unbounded", "an identity past 2**53-1 is carried into the mapping", ("DryRunMappingTest.test_queue_items_map_with_the_authority_they_lack_named",),
           "        return canonical.identity_integer(value)", "        return value"),
          ("unknown-count-is-zero", "a missing iteration count becomes zero (RG-U)", ("DryRunMappingTest.test_queue_items_map_with_the_authority_they_lack_named",),
           '{"accepted_count": None},\n                               [_issue("count-unknown"', '{"accepted_count": 0},\n                               [_issue("count-unknown"'),
          ("issues-do-not-downgrade", "a record with issues still reports that it maps", ("DryRunMappingTest.test_queue_items_map_with_the_authority_they_lack_named",
                                                                                          "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced"),
           '("partial" if issues else "maps")', '"maps"'),
          ("brief-imported-confirmed", "the imported brief is presented as confirmed", ("DryRunMappingTest.test_the_brief_imports_awaiting_confirmation_with_its_gaps_named",),
           '"status": "awaiting_confirmation",', '"status": "confirmed",'),
          ("disposition-trusted", "a gen-1 agent-written disposition is not flagged as unverified", ("DryRunMappingTest.test_obligations_sources_and_logs",),
           '        if isinstance(disposition, str) and disposition != "open":', "        if False:"),
          ("queue-absent-silent", "a root with no queue yields an empty report with nothing blocking", ("ReadOnlyTest.test_absent_queue_is_blocking",),
           "    elif queue is None and stale is None:", "    elif False:"),
          ("report-inside-root", "the report may be written inside the gen-1 root (the descriptor check before the file is created removed)",
           ("CommandTest.test_report_is_refused_inside_the_gen1_root_or_over_a_file", "CommandTest.test_a_report_directory_moved_into_the_root_gets_no_report"),
           '    if not _outside_root(dir_fd, reader.identity):\n        raise ReportRefused("the report', '    if False:\n        raise ReportRefused("the report'),
          ("unrepresentable-fatal", "a gen-1 value JCS cannot represent is kept, so the report cannot be rendered",
           ("CommandTest.test_an_unrepresentable_gen1_value_is_surfaced_not_fatal",),
           '            mapping[key] = None\n            issues.append(_issue("value-unrepresentable"', '            issues.append(_issue("value-unrepresentable"'),
          # --- 0b repair A2: reads and the report bound to the objects checked ---
          ("A2-file-link-followed", "a source file that is a symlink is followed (O_NOFOLLOW dropped on files)",
           ("ReadOnlyTest.test_paths_outside_the_root_are_not_read", "ReadOnlyTest.test_a_source_replaced_by_a_link_as_it_is_opened_is_not_followed"),
           "_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC", "_FILE = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC"),
          ("A2-dir-link-followed", "a directory on the way to a source that is a symlink is followed (O_NOFOLLOW dropped on directories)",
           ("ReadOnlyTest.test_paths_outside_the_root_are_not_read", "ReadOnlyTest.test_a_source_replaced_by_a_link_as_it_is_opened_is_not_followed"),
           "_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC", "_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC"),
          ("A2-path-reopened", "the review's shape: the file is reopened by pathname after the walk, not opened from the walked directory",
           ("ReadOnlyTest.test_paths_outside_the_root_are_not_read", "ReadOnlyTest.test_a_source_replaced_by_a_link_as_it_is_opened_is_not_followed"),
           "                    fd = os.open(rel.name, _FILE, dir_fd=parent)", "                    fd = os.open(self.root / rel, os.O_RDONLY)"),
          ("A2-dotdot-walks-out", "a '..' or absolute path component (from a gen-1 id) is walked, out of the root",
           ("ReadOnlyTest.test_paths_outside_the_root_are_not_read",), '        if rel.is_absolute() or ".." in rel.parts:', "        if False:"),
          ("A2-refusal-as-absence", "a refused or unreadable source is reported as absent, not as missing evidence",
           ("ReadOnlyTest.test_paths_outside_the_root_are_not_read", "ReadOnlyTest.test_a_source_replaced_by_a_link_as_it_is_opened_is_not_followed"),
           '    return status is not None and status.startswith(("refused", "unreadable"))', "    return False"),
          ("A2-report-by-path", "the review's shape: the report is opened by pathname after the check, following a swapped parent",
           ("CommandTest.test_a_report_directory_swapped_for_a_link_after_the_check_is_not_followed",),
           "                _write_report(*destination, text, reader)\n", '                open(args.report, "x", encoding="utf-8").write(text)\n'),
          ("A2-report-unchecked-after-create", "no descriptor check after the file is created: the report is written into a directory moved into the root",
           ("CommandTest.test_a_report_directory_moved_into_the_root_gets_no_report",),
           "        if not _outside_root(dir_fd, reader.identity):\n            raise ReportRefused(f\"the report's directory moved",
           "        if False:\n            raise ReportRefused(f\"the report's directory moved"),
          ("A2-ancestry-not-walked", "only the report directory itself is compared with the root, not its ancestors",
           ("CommandTest.test_report_is_refused_inside_the_gen1_root_or_over_a_file", "CommandTest.test_a_report_directory_moved_into_the_root_gets_no_report"),
           '            parent = os.open("..",', '            return True\n            parent = os.open("..",'),
          # --- 0b repair A3: managed-store evidence fails closed ---
          ("A3-link-taken-as-absent", "a symlink at state/control.sqlite3 counts as no managed store",
           ("ReadOnlyTest.test_managed_store_evidence_is_never_mistaken_for_absence",), '    if kind == "absent":\n        return None', '    if kind in ("absent", "symlink"):\n        return None'),
          ("A3-unexaminable-taken-as-absent", "an entry that is not a file, or cannot be examined, counts as no managed store",
           ("ReadOnlyTest.test_managed_store_evidence_is_never_mistaken_for_absence",), '    if kind == "absent":\n        return None',
           '    if kind in ("absent", "unverifiable", "directory", "other"):\n        return None'),
          ("A3-entry-followed", "the review's shape: the managed-store entry is judged through its link (a dangling link reads as absent)",
           ("ReadOnlyTest.test_managed_store_evidence_is_never_mistaken_for_absence",),
           "                st = os.stat(rel.name, dir_fd=parent, follow_symlinks=False)", "                st = os.stat(rel.name, dir_fd=parent, follow_symlinks=True)"),
          ("A3-stale-not-on-malformed-items", "a malformed queue item from a stale snapshot is not marked stale",
           ("ReadOnlyTest.test_managed_store_blocks_and_the_json_queue_is_marked_stale",),
           '            if stale is not None:\n                record["issues"].append(', '            if False:\n                record["issues"].append('),
          ("A3-stale-not-on-queue-state", "the queue-level record from a stale snapshot is not marked stale",
           ("ReadOnlyTest.test_managed_store_blocks_and_the_json_queue_is_marked_stale",),
           '                                 + ([_issue("stale-snapshot", stale, "the managed store\'s state")] if stale is not None else []), unmapped=True))',
           "                                 , unmapped=True))"),
          # --- 0b repair A5: input the importer cannot interpret is reported ---
          ("A5-numerals-rounded", "the review's shape: a numeral binary64 does not hold exactly is rounded (9007199254740990.6 becomes 9007199254740991)",
           ("DryRunMappingTest.test_identity_numerals_are_checked_as_written", "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced",
            "CommandTest.test_an_unrepresentable_gen1_value_is_surfaced_not_fatal"),
           "    if Decimal(repr(value)) != written:\n        return InexactNumeral(token)\n", ""),
          ("A5-fraction-as-identity", "a fractional identity is judged only by the range check (reported as out of range, not as a non-integer)",
           ("DryRunMappingTest.test_identity_numerals_are_checked_as_written",), "            or isinstance(value, float) and not value.is_integer():", "            or False:"),
          ("A5-inexact-kept-in-mapping", "an inexact numeral in a mapped value is reported as merely unrepresentable",
           ("CommandTest.test_an_unrepresentable_gen1_value_is_surfaced_not_fatal",), "        if inexact:\n", "        if False:\n"),
          ("A5-status-shape-unchecked", "the review's reproduction: status [] reaches the status table (uncaught TypeError)",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           '    if not isinstance(status, str):\n        target, status_issues = None, [_issue("field-shape"', '    if False:\n        target, status_issues = None, [_issue("field-shape"'),
          ("A5-lane-shape-unchecked", "a wrong-typed lane/managed_kind is read as 'not intake' and the status mapped",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",), "    if shape:\n        target, status_issues = None,", "    if False:\n        target, status_issues = None,"),
          ("A5-collection-shape-unchecked", "the review's reproduction: obligations 3 (a non-list collection) goes unreported",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           "        if state.get(key) is not None and not isinstance(state[key], list):", "        if False:"),
          ("A5-obligation-id-unchecked", "an obligation whose id is not a string is mapped (uncaught TypeError)",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           '        if not isinstance(obl, dict) or not isinstance(obl.get("id"), str):', "        if not isinstance(obl, dict):"),
          ("A5-obligation-fields-unchecked", "an obligation's wrong-typed text/disposition goes unreported",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           '        issues += [i for i in (_shape(obl, f, TEXT_OR_NULL, where) for f in ("text", "disposition")) if i]\n', ""),
          ("A5-item-id-unchecked", "a queue item whose id is not a string is mapped (uncaught TypeError)",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           '        if not isinstance(item, dict) or not isinstance(item.get("id"), str):', "        if not isinstance(item, dict):"),
          ("A5-cwd-shape-unchecked", "a wrong-typed cwd is ignored silently", ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           "        if cwd_issue:", "        if False:"),
          ("A5-queue-collision-unflagged", "the review's reproduction: two queue items with one id both map, to one primary key",
           ("DryRunMappingTest.test_two_records_claiming_one_gen2_identity_are_flagged", "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced"),
           "        if valid_ids.count(gen1_id) > 1:", "        if False:"),
          ("A5-obligation-collision-unflagged", "two obligations with one id both map",
           ("DryRunMappingTest.test_two_records_claiming_one_gen2_identity_are_flagged", "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced"),
           "        if ids.count(oid) > 1:", "        if False:"),
          ("A5-semantic-version-unchecked", "the review's reproduction: schema_version 999 is interpreted as the known format, silently",
           ("DryRunMappingTest.test_unsupported_versions_and_unmapped_material_are_reported", "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced"),
           "    if type(version) is not int or version != SEMANTIC_STATE_VERSION:", "    if False:"),
          ("A5-queue-version-unchecked", "a queue of another version is mapped as version 1",
           ("DryRunMappingTest.test_unsupported_versions_and_unmapped_material_are_reported",),
           '    elif isinstance(queue, dict) and (type(queue.get("version")) is not int or queue["version"] != QUEUE_VERSION):', "    elif False:"),
          ("A5-unknown-keys-dropped", "semantic-state keys outside the format are dropped silently",
           ("DryRunMappingTest.test_unsupported_versions_and_unmapped_material_are_reported", "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced"),
           "    unknown = _unmapped_fields(state, SEMANTIC_STATE_KEYS)\n    if unknown:", "    unknown = _unmapped_fields(state, SEMANTIC_STATE_KEYS)\n    if False:"),
          ("A5-item-fields-dropped", "queue item fields with no mapping are dropped silently",
           ("DryRunMappingTest.test_unsupported_versions_and_unmapped_material_are_reported", "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced"),
           "    extra = _unmapped_fields(item, QUEUE_ITEM_MAPPED)\n    if extra:", "    extra = _unmapped_fields(item, QUEUE_ITEM_MAPPED)\n    if False:"),
          ("A5-queue-fields-dropped", "queue-level fields with no mapping are dropped silently",
           ("DryRunMappingTest.test_unsupported_versions_and_unmapped_material_are_reported", "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced"),
           '        extra = _unmapped_fields(queue, {"version", "items"})\n        if extra:', '        extra = _unmapped_fields(queue, {"version", "items"})\n        if False:'),
          ("A5-nul-path-crashes", "a NUL in a gen-1 id or cwd reaches os.open unguarded (uncaught ValueError)",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           "                except ValueError:  # an embedded NUL, from a gen-1 id or cwd\n                    raise _Unread(", "                except OSError as _:\n                    raise _Unread("),
          ("A5-deep-json-crashes", "JSON nested past the parser's depth is an uncaught RecursionError",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           "    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:", "    except (UnicodeDecodeError, json.JSONDecodeError) as exc:"),
          ("A5-deep-value-crashes", "a parsed value too deep to walk crashes the record check",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           "        except (canonical.CanonicalizationError, RecursionError) as exc:", "        except canonical.CanonicalizationError as exc:"),
          ("A5-unbounded-repr", "gen-1 values are quoted in issue text whole, however large (plain repr)",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",), "_show = _SHOW.repr\n", "_show = repr\n"),
          ("A5-obligation-fields-dropped", "obligation fields with no mapping are dropped silently", ("DryRunMappingTest.test_obligations_sources_and_logs",),
           "        extra = _unmapped_fields(obl, OBLIGATION_MAPPED)\n        if extra:", "        extra = _unmapped_fields(obl, OBLIGATION_MAPPED)\n        if False:"),
          # --- 0b repair-2 A5-R1: text that is not valid Unicode is reported, escaped, never substituted ---
          ("A5R1-item-id-unchecked", "the review's probe: a queue id holding a lone surrogate is mapped, into the topic id, refs and paths",
           ("CommandTest.test_the_reviews_invalid_unicode_probes_get_a_report", "CommandTest.test_invalid_unicode_is_reported_beside_records_that_still_map"), '        elif not _is_text(item["id"]):', "        elif False:"),
          ("A5R1-ref-not-escaped", "the review's probe: a ref quoting a lone surrogate (from a status) reaches the report as it is",
           ("CommandTest.test_the_reviews_invalid_unicode_probes_get_a_report", "CommandTest.test_invalid_unicode_is_reported_beside_records_that_still_map"), '    ref = _text(ref, "ref", escaped)\n', ""),
          ("A5R1-issue-text-not-escaped", "the review's probe: issue text quoting a lone surrogate (from an unknown key) reaches the report as it is",
           ("CommandTest.test_the_reviews_invalid_unicode_probes_get_a_report", "CommandTest.test_invalid_unicode_is_reported_beside_records_that_still_map"), '            issue[field] = _text(issue[field], f"issues[{n}].{field}", escaped)\n', "            pass\n"),
          ("A5R1-escape-unreported", "a record's text is escaped with no issue saying so (the locator passes for the name)",
           ("CommandTest.test_the_reviews_invalid_unicode_probes_get_a_report", "CommandTest.test_invalid_unicode_is_reported_beside_records_that_still_map"), "    if escaped:\n        issues.append(_escaped_issue(", "    if False:\n        issues.append(_escaped_issue("),
          ("A5R1-escape-not-reversible", "backslashes are not doubled, so an escaped lone surrogate reads the same as a written backslash-u",
           ("CommandTest.test_invalid_unicode_is_reported_beside_records_that_still_map",), r'    return text.replace("\\", "\\\\").encode(', "    return text.encode("),
          ("A5R1-source-key-kept", "a source path that is not valid Unicode stays a key of sources",
           ("CommandTest.test_invalid_unicode_is_reported_beside_records_that_still_map",), "        if _is_text(path) and _is_text(status):", "        if True:"),
          ("A5R1-root-not-escaped", "a gen-1 root path that is not UTF-8 reaches the report as it is",
           ("CommandTest.test_a_root_path_or_fleet_that_is_not_valid_unicode_is_reported",), '    root = _text(str(reader.root), "gen1_root", escaped)', "    root = str(reader.root)"),
          ("A5R1-fleet-not-escaped", "a fleet holding a lone surrogate reaches the report as it is",
           ("CommandTest.test_a_root_path_or_fleet_that_is_not_valid_unicode_is_reported",), '    fleet_id = None if fleet is None else _text(fleet, "fleet_id", escaped)', "    fleet_id = fleet"),
          ("A5R1-blocking-text-not-escaped", "a blocking issue quoting a root path that is not UTF-8 reaches the report as it is",
           ("CommandTest.test_a_root_path_or_fleet_that_is_not_valid_unicode_is_reported",), '            issue[field] = _text(issue[field], f"blocking[{n}].{field}", escaped)\n', "            pass\n"),
          ("A5R1-report-escape-unreported", "the report's own fields are escaped with no blocking issue saying so",
           ("CommandTest.test_a_root_path_or_fleet_that_is_not_valid_unicode_is_reported",), "    if escaped:\n        blocking.append(_escaped_issue(", "    if False:\n        blocking.append(_escaped_issue("),
          # --- 0b repair-2 A5-R2: a numeral the parser cannot convert is reported, never fatal ---
          ("A5R2-int-limit-uncaught", "the review's probe: a 4,301-digit integer escapes the parser as a ValueError (no integer hook)",
           ("CommandTest.test_numerals_the_parser_cannot_convert_are_reported_not_fatal",), ", parse_float=_gen1_float, parse_int=_gen1_int)", ", parse_float=_gen1_float)"),
          ("A5R2-oversize-int-zeroed", "an integer past the conversion limit is read as 0, not refused",
           ("CommandTest.test_numerals_the_parser_cannot_convert_are_reported_not_fatal",), '        raise Gen1ParseError(f"an integer numeral of', '        return 0\n        raise Gen1ParseError(f"an integer numeral of'),
          ("A5R2-limit-lifted", "the fix the review forbids: the integer-conversion limit is lifted for the parse (then restored), so the numeral is converted",
           ("CommandTest.test_numerals_the_parser_cannot_convert_are_reported_not_fatal",),
           '        return json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant, parse_float=_gen1_float, parse_int=_gen1_int)\n',
           '        limit = __import__("sys").get_int_max_str_digits()\n        __import__("sys").set_int_max_str_digits(0)\n        try:\n'
           '            return json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant, parse_float=_gen1_float, parse_int=_gen1_int)\n'
           '        finally:\n            __import__("sys").set_int_max_str_digits(limit)\n'),
          ("A5R2-exponent-uncaught", "an exponent past Decimal's range escapes the parser as InvalidOperation",
           ("CommandTest.test_numerals_the_parser_cannot_convert_are_reported_not_fatal",), "    except InvalidOperation:\n        raise Gen1ParseError(", "    except ZeroDivisionError:\n        raise Gen1ParseError("),
          ("A5R2-overflow-unparseable", "an exponent so large the number overflows makes the file unparseable instead of an inexact numeral on its record",
           ("CommandTest.test_numerals_the_parser_cannot_convert_are_reported_not_fatal",), '    if value != value or value in (float("inf"), float("-inf")):\n        return InexactNumeral(token)\n', ""))),
    # --- task 1a / V-10: a gen-1 disposition never imports as accepted support ---
    *(Mutation(f"V10-importer-{key}", "1a", desc, ("test_importer.DryRunMappingTest.test_no_gen1_disposition_imports_as_accepted_support",),
               target="gen2/importer/dry_run.py", old=old, new=new)
      for key, desc, old, new in (
          ("maps-disposition", "gen-1's agent-written 'supported' disposition is mapped as an accepted-support claim status",
           '"obligations", {"obligation_id": oid, "text": text if isinstance(text, TEXT_OR_NULL) else None}, issues))',
           '"obligations", {"obligation_id": oid, "text": text if isinstance(text, TEXT_OR_NULL) else None, '
           '"claim_status": "accepted_support" if disposition == "supported" else "provisional"}, issues))'),
          ("report-omits-admission", "the report states only the receipt condition, not contract-admitted production",
           '"contract-admitted production (V-10) and, for a load-bearing claim, a verification receipt (V-4), and gen-1 work has neither"',
           '"a verification receipt (V-4)"'))),
    *(Mutation(f"IMP-graph-{key}", "0b-importer", desc, (CB + "test_importer_cannot_reach_a_store_under_the_real_graph",), target="gen2/boundaries.toml",
               old='may_import = ["core"]\nstdlib_capabilities = []\nthird_party = []\n\n[modules.operator]', new=new)
      for key, desc, new in (
          ("store-granted", "the boundary graph lets the importer import the store (and so write a gen-2 store)",
           'may_import = ["core", "store"]\nstdlib_capabilities = []\nthird_party = []\n\n[modules.operator]'),
          ("sqlite-granted", "the boundary graph grants the importer sqlite3",
           'may_import = ["core"]\nstdlib_capabilities = ["sqlite3"]\nthird_party = []\n\n[modules.operator]'))),
    # --- 0b cleanup 2: the permanent reversed-trigger-order check ----------------------
    *(Mutation(f"TO-{key}", "0b-cleanup-2", desc, tuple("test_trigger_order_tool.TriggerOrderToolTest." + k for k in killers),
               target="tools/gen2_trigger_order.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("not-reversed", "the rebuild re-creates the triggers in their original order",
           ("test_rebuild_creates_the_same_triggers_in_reverse",), r'"\n".join(reversed(blocks))', r'"\n".join(blocks)'),
          ("rebuild-order-unchecked", "a rebuild that did not reverse the order is not detected",
           ("test_a_rebuild_that_keeps_the_order_is_refused",), "    if r_order != list(reversed(order)):", "    if False:"),
          ("rebuild-triggers-unchecked", "a rebuild that lost or changed a trigger is not detected",
           ("test_a_rebuild_that_keeps_the_order_is_refused",), "    if r_sql != sql:", "    if False:"),
          ("differences-ignored", "outcomes that differ between the two orders are not reported",
           ("test_outcomes_must_be_green_and_identical",), "        if a != b:", "        if False:"),
          ("original-failures-ignored", "a failure in the original order is not reported when both orders agree",
           ("test_outcomes_must_be_green_and_identical",), '        if outcome != "pass":', "        if False:"))),
    # --- coverage pass: pre-existing 0a guards, so the inventory spans the whole DDL ----
    *(Mutation(f"cov-delete-guard-{trigger}", "C-11", f"drop delete guard {trigger}",
               (H + ("EveryTableSweepTest.test_unreferenced_rows_cannot_be_deleted_either" if trigger in ("claims_no_delete", "invocations_no_delete", "leases_no_delete", "outbox_events_immutable_d",
                                                                                                     "config_bundles_no_delete", "reservations_no_delete")
                     else "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into"),), drop_trigger=trigger)
      for trigger in ("artifacts_immutable_d", "audit_events_append_only_d", "capability_facts_no_delete", "claims_no_delete", "decision_receipts_immutable_d",
                      "decision_specs_immutable_d", "dossiers_immutable_d", "holds_no_delete", "invocation_transitions_append_only_d", "invocations_no_delete",
                      "leases_no_delete", "obligations_no_delete", "operator_decisions_immutable_d", "outbox_events_immutable_d", "research_ordinals_immutable_d",
                      "retrieval_events_immutable_d", "review_episodes_no_delete", "screening_assessments_immutable_d", "search_observations_immutable_d",
                      "verification_receipts_immutable_d", "artifact_topics_immutable_d", "questions_no_delete", "qualifications_no_delete",
                      "reservation_draws_no_delete", "retries_no_delete", "amendment_impacts_no_delete", "config_bundles_no_delete",
                      "reservations_no_delete")),
    *(Mutation(f"cov-{trigger}", "0a", f"drop {trigger} (a pre-existing 0a guard)", tuple(killers), drop_trigger=trigger)
      for trigger, killers in (
          ("operation_receipts_fenced", (D + "CommitFencingTest.test_stale_generation_rejected", D + "CommitFencingTest.test_released_lease_cannot_commit",
                                         D + "CommitFencingTest.test_cross_topic_commit_rejected", D + "CommitFencingTest.test_commit_under_another_invocations_lease_rejected")),
          ("claims_accepted_support_needs_receipt", (VT + "test_accepted_support_needs_receipt_at_required_tier", CS + "test_contract_admitted_claim_without_a_receipt_is_refused")),
          ("connector_watermarks_never_regress", (D + "ExportOutboxTest.test_connector_watermark_never_regresses",)),
          ("invocations_start_admitted", (LT + "test_invocations_start_admitted",)),
          ("leases_generation_increases", (D + "LeaseFencingTest.test_generation_strictly_increases_per_topic",)),
          ("leases_release_final_identity_immutable", (D + "LeaseFencingTest.test_release_is_write_once",)),
          ("queue_state_revision_advances_by_one", (D + "CommitFencingTest.test_state_revision_advances_by_exactly_one",)),
          ("contract_status_forward_only", (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted", CG + "test_approval_pointer_is_set_only_by_the_approval_transition")),
          ("claims_start_provisional", (VT + "test_claims_start_provisional",)),
          ("retrieval_events_from_successful_search", (OB + "test_retrieval_events_only_from_successful_searches",)),
          ("review_triggers_handled_is_final", (D + "OrdinalAndTriggerTest.test_trigger_identity_unique_and_handled_is_final",)),
          ("outbox_events_pair_increases", (D + "ExportOutboxTest.test_ordering_pairs_strictly_increase",)),
          ("holds_clear_once_identity_immutable", (D + "HoldTest.test_operator_hold_cleared_only_by_operator_decision", RI + "test_hold_identity_class_and_authority_are_immutable")),
          ("queue_topic_identity_immutable", (RI + "test_topic_identity_is_immutable",)),
          ("review_episodes_close_once", (RI + "test_review_episode_closes_once",)),
          ("claims_identity_immutable", (RI + "test_claim_content_is_immutable_per_revision",)),
          ("works_identity_immutable", (RI + "test_work_identity_is_immutable",)))),
    Mutation("D48-any-declared-connector", "A2", "the review's surviving mutant, carried (0d): any connector of a declared type accepted, not just the ones the manifest names",
             (D + "ExportOutboxTest.test_delivery_receipt_only_for_named_connectors",), scope="export_delivery_receipts_expected_connector",
             old="WHEN NOT EXISTS (\n  SELECT 1 FROM outbox_events e, json_each(e.expected_connectors) j\n  WHERE e.manifest_id = NEW.manifest_id AND j.key = NEW.connector_id\n    AND json_extract(j.value, '$.connector_type') IS NEW.connector_type)",
             new="WHEN NEW.connector_type NOT IN ('sql', 'jsonl_file', 'webhook', 'extension')"),
    Mutation("D48-expected-connector-dropped", "A2", "drop the expected-connector trigger", (D + "ExportOutboxTest.test_delivery_receipt_only_for_named_connectors",),
             drop_trigger="export_delivery_receipts_expected_connector"),
    Mutation("D48-connector-type-unmatched", "0d", "a receipt may name the manifest's connector under another type",
             (D + "ExportOutboxTest.test_delivery_receipt_only_for_named_connectors",), scope="export_delivery_receipts_expected_connector",
             old="\n    AND json_extract(j.value, '$.connector_type') IS NEW.connector_type)", new=")"),
    # --- 0d: the export tables (operator ruling 2026-09-26) ---------------------
    # outbox_events is the export-manifest table; export_delivery_receipts and
    # connector_watermarks replace the per-sink tables. Each mutant removes one
    # rule, and its test's probe for that rule is the only one it admits.
    *(Mutation(f"0D-{key}", "0d", desc, (D + X + killer,), old=old, new=new, scope=scope)
      for key, desc, killer, scope, old, new in (
          ("pair-lower-generation-admitted", "a lower generation is admitted when its options revision is higher",
           "test_ordering_pairs_strictly_increase", "outbox_events_pair_increases",
           "    AND (e.generation > NEW.generation\n         OR (e.generation = NEW.generation AND e.options_revision >= NEW.options_revision)))",
           "    AND ((e.generation = NEW.generation AND e.options_revision >= NEW.options_revision)))"),
          ("pair-lower-options-admitted", "a lower options revision of the same generation is admitted",
           "test_ordering_pairs_strictly_increase", "outbox_events_pair_increases",
           "    AND (e.generation > NEW.generation\n         OR (e.generation = NEW.generation AND e.options_revision >= NEW.options_revision)))",
           "    AND (e.generation > NEW.generation))"),
          ("one-generation-another-approved-revision", "a re-export of a generation may carry another approved revision (source, hash and approval together)",
           "test_one_generation_is_one_approved_revision", "outbox_events_generation_is_one_approved_revision",
           "    AND (e.source_revision IS NOT NEW.source_revision\n         OR e.source_content_hash IS NOT NEW.source_content_hash\n"
           "         OR e.approval_decision_id IS NOT NEW.approval_decision_id\n         OR e.artifact_kind",
           "    AND (e.artifact_kind"),
          ("one-generation-another-approval", "a re-export of a generation may cite another approval of the same revision",
           "test_one_generation_is_one_approved_revision", "outbox_events_generation_is_one_approved_revision",
           "\n         OR e.approval_decision_id IS NOT NEW.approval_decision_id", ""),
          ("one-generation-another-kind", "a re-export of a generation may change its artifact kind",
           "test_one_generation_is_one_approved_revision", "outbox_events_generation_is_one_approved_revision",
           "\n         OR e.artifact_kind IS NOT NEW.artifact_kind))", "))"),
          ("connector-types-widened", "the manifest trigger admits a store kind as a connector type",
           "test_manifest_names_only_declared_connector_types", "outbox_events_connectors_declared",
           "        NOT IN ('sql', 'jsonl_file', 'webhook', 'extension'))", "        NOT IN ('sql', 'jsonl_file', 'webhook', 'extension', 'graph_store'))"),
          ("connectors-need-not-be-an-object", "expected_connectors may be an array (the retired expected_sinks shape)",
           "test_manifest_names_only_declared_connector_types", None, "AND json_type(expected_connectors) = 'object' ", ""),
          ("connectors-may-be-empty", "a manifest may name no connector",
           "test_manifest_names_only_declared_connector_types", None, " AND json(expected_connectors) != '{}'", ""),
          ("supersedes-pair-incomplete", "a superseded generation may be stored without its options revision",
           "test_supersession_names_a_lower_pair", None,
           "\n  CHECK ((supersedes_generation IS NULL) = (supersedes_options_revision IS NULL)),", ""),
          ("supersedes-generation-floor", "a manifest may supersede generation 0",
           "test_supersession_names_a_lower_pair", None,
           "OR (supersedes_generation >= 1 AND supersedes_options_revision >= 1\n", "OR (supersedes_options_revision >= 1\n"),
          ("supersedes-options-floor", "a manifest may supersede options revision 0",
           "test_supersession_names_a_lower_pair", None,
           "OR (supersedes_generation >= 1 AND supersedes_options_revision >= 1\n", "OR (supersedes_generation >= 1\n"),
          ("supersedes-a-later-generation", "a manifest may supersede a later generation",
           "test_supersession_names_a_lower_pair", None,
           "         AND (supersedes_generation < generation\n", "         AND (1\n"),
          ("supersedes-its-own-pair", "a manifest may supersede its own pair",
           "test_supersession_names_a_lower_pair", None,
           "supersedes_options_revision < options_revision)))", "supersedes_options_revision <= options_revision)))"),
          ("receipt-status-queued", "a receipt may say `queued` (durable enqueueing counted as delivery state)",
           "test_receipt_status_rules", None,
           "status IN ('delivered', 'failed', 'skipped_superseded', 'outcome_unknown')",
           "status IN ('delivered', 'failed', 'skipped_superseded', 'outcome_unknown', 'queued')"),
          ("receipt-failure-without-class", "a failure need not name its class (carried publication CHECK)",
           "test_receipt_status_rules", "export_delivery_receipts", "\n  CHECK (status != 'failed' OR error_class IS NOT NULL),", ""),
          ("receipt-class-on-a-settled-non-failure", "an error class may ride on a delivery",
           "test_receipt_status_rules", None, "\n  CHECK (error_class IS NULL OR status = 'failed'),", ""),
          ("receipt-unreadable-response-is-a-class", "unreadable_response is a failure class (A2, restored in the store)",
           "test_receipt_status_rules", None, "'conflict', 'partial_write'))", "'conflict', 'partial_write', 'unreadable_response'))"),
          ("receipt-delivered-without-ack", "a delivery need not carry its acknowledgement time (carried publication CHECK)",
           "test_receipt_status_rules", "export_delivery_receipts",
           "CHECK (status != 'delivered' OR (acked_at IS NOT NULL AND tombstones_acknowledged = 1))",
           "CHECK (status != 'delivered' OR (tombstones_acknowledged = 1))"),
          ("receipt-delivered-without-tombstones", "a delivery need not acknowledge its tombstones (carried publication CHECK)",
           "test_receipt_status_rules", "export_delivery_receipts",
           "CHECK (status != 'delivered' OR (acked_at IS NOT NULL AND tombstones_acknowledged = 1))",
           "CHECK (status != 'delivered' OR (acked_at IS NOT NULL))"),
          ("receipt-ack-on-a-non-delivery", "a failure may carry an acknowledgement time",
           "test_receipt_status_rules", None, "\n  CHECK (acked_at IS NULL OR status = 'delivered'),", ""),
          ("receipt-tombstones-on-a-non-delivery", "a skipped delivery may claim its tombstones were acknowledged",
           "test_receipt_status_rules", None, "\n  CHECK (tombstones_acknowledged = 0 OR status = 'delivered'),", ""),
          ("receipt-unknown-without-cause", "an unknown outcome need not say why",
           "test_receipt_status_rules", None,
           "CHECK ((unknown_cause IS NOT NULL) = (status = 'outcome_unknown'))", "CHECK (unknown_cause IS NULL OR status = 'outcome_unknown')"),
          ("receipt-cause-on-a-settled-result", "a settled result may carry an unknown cause",
           "test_receipt_status_rules", None,
           "CHECK ((unknown_cause IS NOT NULL) = (status = 'outcome_unknown'))", "CHECK (status != 'outcome_unknown' OR unknown_cause IS NOT NULL)"),
          ("receipt-cause-vocabulary-widened", "an unknown cause may be a failure class",
           "test_receipt_status_rules", None,
           "'unreadable_response', 'unauthoritative_response'))", "'unreadable_response', 'unauthoritative_response', 'timeout'))"),
          ("receipt-unknown-not-reconciled", "an unknown outcome need not be reconciled (P-7)",
           "test_receipt_status_rules", None,
           "CHECK (reconciliation_required = (status = 'outcome_unknown'))", "CHECK (reconciliation_required = 0 OR status = 'outcome_unknown')"),
          ("receipt-reconciliation-on-a-settled-result", "reconciliation may be left open on a settled result",
           "test_receipt_status_rules", None,
           "CHECK (reconciliation_required = (status = 'outcome_unknown'))", "CHECK (reconciliation_required = 1 OR status != 'outcome_unknown')"),
          ("receipt-failure-without-fact", "a failure need not raise a capability fact (H-2)",
           "test_receipt_status_rules", None,
           "status NOT IN ('failed', 'outcome_unknown') OR capability_fact_id IS NOT NULL", "status NOT IN ('outcome_unknown') OR capability_fact_id IS NOT NULL"),
          ("receipt-unknown-without-fact", "an unknown outcome need not raise a capability fact (H-2)",
           "test_receipt_status_rules", None,
           "status NOT IN ('failed', 'outcome_unknown') OR capability_fact_id IS NOT NULL", "status NOT IN ('failed') OR capability_fact_id IS NOT NULL"),
          ("receipt-fact-on-a-delivery", "a delivery may carry a capability fact",
           "test_receipt_status_rules", None,
           ",\n  CHECK (status != 'delivered' OR capability_fact_id IS NULL)\n) STRICT;", "\n) STRICT;"),
          ("receipt-connector-id-unshaped", "a receipt may name a connector id that is not a legal id",
           "test_connector_ids_are_well_formed", "export_delivery_receipts",
           "connector_id TEXT NOT NULL CHECK (connector_id GLOB '[a-z]*' AND connector_id NOT GLOB '*[^a-z0-9-]*' AND connector_id NOT GLOB '*-' AND length(connector_id) <= 64),",
           "connector_id TEXT NOT NULL,"),
          ("watermark-connector-id-unshaped", "a watermark may be kept under a connector id that is not a legal id (replaces the product-vocabulary CHECK)",
           "test_connector_ids_are_well_formed", "connector_watermarks",
           "connector_id TEXT NOT NULL CHECK (connector_id GLOB '[a-z]*' AND connector_id NOT GLOB '*[^a-z0-9-]*' AND connector_id NOT GLOB '*-' AND length(connector_id) <= 64),",
           "connector_id TEXT NOT NULL,"),
          ("watermark-lower-generation", "a watermark may fall to a lower generation with a higher options revision",
           "test_connector_watermark_never_regresses", "connector_watermarks_never_regress",
           "WHEN NEW.generation < OLD.generation\n  OR (NEW.generation", "WHEN (NEW.generation"),
          ("watermark-lower-options", "a watermark may fall to a lower options revision of the same generation",
           "test_connector_watermark_never_regresses", "connector_watermarks_never_regress",
           "\n  OR (NEW.generation = OLD.generation AND NEW.options_revision < OLD.options_revision)", ""),
          ("watermark-moves-topic", "a watermark may move to another topic",
           "test_connector_watermark_never_regresses", "connector_watermarks_never_regress",
           "\n  OR NEW.topic_id IS NOT OLD.topic_id OR NEW.connector_id IS NOT OLD.connector_id", "\n  OR NEW.connector_id IS NOT OLD.connector_id"),
          ("watermark-moves-connector", "a watermark may move to another connector",
           "test_connector_watermark_never_regresses", "connector_watermarks_never_regress",
           "\n  OR NEW.topic_id IS NOT OLD.topic_id OR NEW.connector_id IS NOT OLD.connector_id", "\n  OR NEW.topic_id IS NOT OLD.topic_id"),
      )),
    # --- 1b-repair A2: the whole delivery receipt, bound to its columns (EXPORT-API.md §9 item 3) ---
    Mutation("1BR-receipt-binds-version", "1b-A2", "a delivery receipt's document need not be export-delivery-receipt/2",
             (D + X + "test_receipt_document_matches_its_columns",), scope="export_delivery_receipts",
             old="CHECK (json_extract(receipt, '$.receipt_version') IS 'export-delivery-receipt/2'\n     AND ", new="CHECK ("),
    *(Mutation(f"1BR-receipt-binds-{key}", "1b-A2", f"a delivery receipt's document is no longer bound to its {col} column",
               (D + X + "test_receipt_document_matches_its_columns",), scope="export_delivery_receipts",
               old=f"\n     AND json_extract(receipt, '$.{path}') IS {col}", new="")
      for key, path, col in (("receipt-id", "export_receipt_id", "export_receipt_id"), ("manifest", "manifest_id", "manifest_id"),
                             ("connector-id", "connector.connector_id", "connector_id"), ("connector-type", "connector.connector_type", "connector_type"),
                             ("attempt", "attempt", "attempt"), ("status", "status", "status"), ("tombstones", "tombstones_acknowledged", "tombstones_acknowledged"),
                             ("reconciliation", "reconciliation_required", "reconciliation_required"), ("error-class", "error_class", "error_class"),
                             ("unknown-cause", "unknown_cause", "unknown_cause"), ("capability-fact", "capability_fact_id", "capability_fact_id"),
                             ("written-status", "written.status", "written_status"), ("written-value", "written.value", "written_value"),
                             ("hold", "hold_id", "hold_id"), ("attempted-at", "attempted_at", "attempted_at"), ("acked-at", "acked_at", "acked_at"))),
    *(Mutation(f"1BR-{key}", "1b-A2", desc, (D + X + "test_written_count_rules",), scope="export_delivery_receipts", old=old, new=new)
      for key, desc, old, new in (
          ("written-unknown-with-a-value", "an unknown count may carry a value (RG-U: unknown is never zero)",
           "CHECK ((written_value IS NULL) = (written_status = 'unknown')),", "CHECK (written_value IS NOT NULL OR written_status = 'unknown'),"),
          ("written-observed-without-a-value", "an observed or partial count may have no value",
           "CHECK ((written_value IS NULL) = (written_status = 'unknown')),", "CHECK (written_status != 'unknown' OR written_value IS NULL),"),
          ("written-delivery-not-observed", "a delivery or a skipped delivery may report a count it did not observe",
           "\n  CHECK (status NOT IN ('delivered', 'skipped_superseded') OR written_status = 'observed'),", ""),
          ("written-skipped-wrote", "a skipped delivery may report records written",
           "\n  CHECK (status != 'skipped_superseded' OR written_value = 0),", ""),
          ("written-partial-write-total", "a partial write may claim an observed total",
           "\n  CHECK (status != 'failed' OR error_class IS NOT 'partial_write' OR written_status = 'partial'),", ""),
          ("written-refusal-wrote", "a failure that applied nothing may report records written",
           "(written_status = 'observed' AND written_value = 0)),", "(written_status = 'observed')),"),
          ("written-refusal-partial", "a failure that applied nothing may report a partial count",
           "(written_status = 'observed' AND written_value = 0)),", "(written_value = 0)),"),
          ("written-unknown-observed", "an unknown outcome may claim an observed count (P-7)",
           "\n  CHECK (status != 'outcome_unknown' OR written_status IN ('unknown', 'partial')),", ""),
      )),
    Mutation("1BR-receipt-describes-manifest-dropped", "1b-A2", "a receipt may report another topic, pair or hold than its manifest's",
             (D + X + "test_receipt_describes_its_manifest",), drop_trigger="export_delivery_receipts_describe_their_manifest"),
    *(Mutation(f"1BR-receipt-describes-{key}", "1b-A2", desc, (D + X + "test_receipt_describes_its_manifest",),
               scope="export_delivery_receipts_describe_their_manifest", old=old, new=new)
      for key, desc, old, new in (
          ("topic", "a receipt may report another topic than its manifest's", "\n    AND e.topic_id IS json_extract(NEW.receipt, '$.topic_id')", ""),
          ("generation", "a receipt may report another generation", "\n    AND e.generation IS json_extract(NEW.receipt, '$.generation')", ""),
          ("options-revision", "a receipt may report another options revision", "\n    AND e.options_revision IS json_extract(NEW.receipt, '$.options_revision')", ""),
          ("hold", "a receipt may name a hold that is not recorded",
           "\n    AND (NEW.hold_id IS NULL OR EXISTS (SELECT 1 FROM holds h WHERE h.hold_id = NEW.hold_id AND h.topic_id = e.topic_id)))", ")"),
          ("hold-topic", "a receipt may name another topic's hold", " AND h.topic_id = e.topic_id", ""),
      )),
    Mutation("0D-one-generation-dropped", "0d", "drop the one-generation-one-approved-revision trigger",
             (D + X + "test_one_generation_is_one_approved_revision",), drop_trigger="outbox_events_generation_is_one_approved_revision"),
    Mutation("0D-connectors-declared-dropped", "0d", "drop the declared-connector-type trigger (the store's undeclared-type negative)",
             (D + X + "test_manifest_names_only_declared_connector_types",), drop_trigger="outbox_events_connectors_declared"),
    Mutation("A1-D01-live-lease-replace", "A1", "drop leases delete guard (REPLACE of the live lease)", (D + "LeaseFencingTest.test_one_live_lease_per_topic_and_scope_until_released",),
             drop_trigger="leases_no_delete"),
    # --- A9: capability supersession --------------------------------------
    Mutation("A9-successor-fk-immediate", "A9", "successor FK checked immediately (the documented transaction cannot run)",
             (D + "ObservationTest.test_one_current_capability_fact_supersede_to_transition",),
             old="REFERENCES capability_facts (fact_id) DEFERRABLE INITIALLY DEFERRED", new="REFERENCES capability_facts (fact_id)"),
    Mutation("A9-self-supersession", "A9", "drop the no-self-supersession CHECK",
             (D + "ObservationTest.test_one_current_capability_fact_supersede_to_transition",),
             old=",\n  CHECK (superseded_by_fact_id IS NOT fact_id)\n) STRICT;", new="\n) STRICT;"),
    Mutation("A9-insert-current-same-capability", "A9", "drop the insert-current/same-capability trigger",
             (D + "ObservationTest.test_one_current_capability_fact_supersede_to_transition",), drop_trigger="capability_facts_insert_current_same_capability"),
    Mutation("A9-link-successor", "A9", "drop the successor-link trigger (cross-capability, cyclic)",
             (D + "ObservationTest.test_one_current_capability_fact_supersede_to_transition",), drop_trigger="capability_facts_link_successor"),
    Mutation("A9-fact-provenance-pins", "A9", "capability fact recorded_at/observer no longer pinned",
             (D + "ObservationTest.test_one_current_capability_fact_supersede_to_transition",),
             old="\n  OR NEW.observed_by_invocation_id IS NOT OLD.observed_by_invocation_id OR NEW.recorded_at IS NOT OLD.recorded_at", new=""),
    Mutation("A1-contract-created-at-pin", "A1", "contract created_at no longer pinned",
             (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted",),
             old="  OR NEW.created_at IS NOT OLD.created_at\n  OR (OLD.approved_by_decision_id IS NOT NULL",
             new="  OR (OLD.approved_by_decision_id IS NOT NULL"),
    # --- 0c: the registry/artifact drift gate (task 0c deliverable 2, Gate C) ------
    # Each of these is a way the drift check could stop meaning anything while
    # `make gen2-check` still passed. The named tests must notice every one.
    *(Mutation(f"0C-{key}", "0c-drift", desc, tuple(SC + k for k in killers),
               target="tools/gen_source_catalog.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("comparison-removed", "the check stops comparing the artifacts with the registry (it only reports success)",
           ("test_a_new_credentialled_source_makes_both_artifacts_stale",
            "test_deleting_a_secret_line_from_the_env_example_is_drift",
            "test_a_hand_edited_catalog_is_drift",
            "test_a_registry_change_with_no_secret_effect_is_still_drift"),
           "                if current != expected:", "                if False:"),
          ("missing-artifact-unreported", "a missing artifact is no longer reported (the checker crashes on it instead)",
           ("test_a_missing_artifact_is_reported_not_crashed_on",), "            if not path.exists():", "            if False:"),
          ("env-not-checked", "the check covers only the first artifact, so the .env example may drift freely",
           ("test_deleting_a_secret_line_from_the_env_example_is_drift",
            "test_a_missing_artifact_is_reported_not_crashed_on"),
           "        for path, expected in artifacts:\n            if not path.exists():",
           "        for path, expected in artifacts[:1]:\n            if not path.exists():"),
          ("unknown-auth-accepted", "an auth kind the generator cannot map is accepted instead of refused",
           ("test_an_unknown_auth_kind_is_refused_rather_than_emitted_without_its_key",),
           "        if auth not in AUTH_SECRETS:", "        if False:"),
          ("empty-secret-ref-accepted", "a credentialled source with no secret_ref is accepted (its key vanishes)",
           ("test_a_credentialled_source_without_a_secret_ref_is_refused",),
           "            if AUTH_SECRETS[auth] and not ref:", "            if False:"),
          ("stray-secret-ref-accepted", "a secret_ref on a source that reads no credential is silently dropped",
           ("test_a_secret_ref_on_a_source_that_reads_no_credential_is_refused",),
           "            if not AUTH_SECRETS[auth] and ref:", "            if False:"),
          ("illegal-variable-name-accepted", "a secret_ref that cannot spell an environment variable is accepted",
           ("test_a_secret_ref_that_is_not_a_legal_variable_name_is_refused",),
           "                if not name.replace(\"_\", \"A\").isalnum() or not name[0].isalpha() or name != name.upper():",
           "                if False:"),
          ("shared-ref-conflict-ignored", "one secret_ref shared by sources that read it differently is accepted",
           ("test_one_secret_ref_shared_with_two_different_auth_kinds_is_refused",),
           "        if len(auths) > 1:", "        if False:"),
          ("required-fields-unchecked", "a source missing a required field is rendered with blanks",
           ("test_a_missing_required_field_is_refused",), "            if key not in s:", "            if False:"),
          ("duplicate-id-accepted", "two rows with one id are accepted",
           ("test_a_duplicate_source_id_is_refused",), "        if sid in seen:", "        if False:"),
          ("invalid-problems-ignored", "validation runs but its findings no longer stop generation",
           ("test_an_unknown_auth_kind_is_refused_rather_than_emitted_without_its_key",
            "test_a_credentialled_source_without_a_secret_ref_is_refused",
            "test_a_missing_required_field_is_refused"),
           "    if problems:\n        print(f\"CATALOG ERROR: {registry} cannot produce a complete catalog and .env example:\", file=sys.stderr)",
           "    if False:\n        print(f\"CATALOG ERROR: {registry} cannot produce a complete catalog and .env example:\", file=sys.stderr)"),
          ("optional-emitted-live", "an optional credential is emitted as a live line, so a blank looks configured",
           ("test_required_credentials_are_live_lines_and_optional_ones_are_commented",),
           "            out.append(f\"{'' if s.required else '# '}{s.var}=example-{s.secret_ref.replace('_', '-')}\"",
           "            out.append(f\"{s.var}=example-{s.secret_ref.replace('_', '-')}\""),
          ("multi-field-collapsed", "a multi-field credential emits one unsuffixed variable",
           ("test_multi_field_credentials_emit_one_variable_per_field",),
           '    return f"{name}_{field.upper()}" if field else name', "    return name"),
          ("cost-cap-not-reported", "a recorded cost cap is not reported, so a metered source reads as uncapped",
           ("test_a_cost_cap_in_the_registry_is_reported_as_metered",),
           '    if rate.get("cost_cap_per_day"):', "    if False:"),
      )),
    # --- 0c-repair: schema rules, each with a negative that fails for it alone ----
    # Astra 0c review C1: a negative whose declared (keyword, path) is also
    # produced by another rule survives removal of its own rule. Each mutant
    # deletes one rule from a schema; the whole tree is re-checked with the
    # mutated file, and the named negative must stop behaving as declared (it
    # validates). The bundle's mixed rule is two rules, mutated separately.
    *(Mutation(f"0CR-{key}", finding, desc, tuple(SF + k for k in killers), target=target, old=old, new=new)
      for key, finding, desc, killers, target, old, new in (
          ("mixed-hold-list-not-required", "C1", "a mixed disposition no longer requires its hold list (the review's surviving mutant)",
           ("test_a_mixed_disposition_without_its_hold_list_is_refused",), "gen2/schema/export-bundle.schema.json",
           '"then": {"required": ["open_adjudication_hold_ids"], "properties": {"open_adjudication_hold_ids": {"minItems": 1}}}',
           '"then": {"properties": {"open_adjudication_hold_ids": {"minItems": 1}}}'),
          ("mixed-hold-list-may-be-empty", "A3", "a mixed disposition's hold list may be empty",
           ("test_a_mixed_disposition_with_an_empty_hold_list_is_refused",), "gen2/schema/export-bundle.schema.json",
           '"then": {"required": ["open_adjudication_hold_ids"], "properties": {"open_adjudication_hold_ids": {"minItems": 1}}}',
           '"then": {"required": ["open_adjudication_hold_ids"]}'),
          ("partial-write-count-unconstrained", "A4", "a partial_write failure may report an observed total (the review's substitution)",
           ("test_a_partial_write_claiming_an_observed_total_is_refused",), RECEIPT,
           '"then": {"properties": {"written": {"properties": {"status": {"const": "partial"}}}}}', '"then": {}'),
          ("settled-failure-count-unconstrained", "A2", "a failure other than a partial write may report any count, an unknown one included",
           ("test_a_failure_whose_count_is_unknown_is_refused", "test_a_refusal_claiming_it_wrote_records_is_refused",
            "test_the_reviews_unreadable_response_reproduction_is_refused_twice"), RECEIPT,
           '"then": {"properties": {"written": {"properties": {"status": {"const": "observed"}, "value": {"const": 0}}}}}', '"then": {}'),
          ("unreadable-response-is-a-failure-class", "A2", "unreadable_response is a settled failure's class again",
           ("test_an_unreadable_response_is_not_a_failure_class", "test_the_reviews_unreadable_response_reproduction_is_refused_twice"), RECEIPT,
           '"partial_write"]\n    },\n    "unknown_cause"', '"partial_write", "unreadable_response"]\n    },\n    "unknown_cause"'),
          ("unknown-cause-not-required", "A2", "an unknown outcome need not say why it is unknown",
           ("test_an_unknown_outcome_without_a_cause_is_refused",), RECEIPT,
           '"required": ["capability_fact_id", "unknown_cause"],', '"required": ["capability_fact_id"],'),
          ("unknown-cause-on-a-settled-result", "A2", "a settled result may carry an unknown cause",
           ("test_a_settled_result_carrying_an_unknown_cause_is_refused",), RECEIPT,
           '"if": {"required": ["unknown_cause"]},\n      "then": {"properties": {"status": {"const": "outcome_unknown"}}}',
           '"if": {"required": ["unknown_cause"]},\n      "then": {}'),
          # The audit of every other negative for the same collapse found four
          # (0a fixtures). The checker now counts errors (below); these show
          # each hidden rule is noticed on its own. intake-brief's
          # invalid-version-zero states one floor twice, so it has no mutant.
          ("abstention-artifact-not-required", "C1-audit", "an abstention no longer needs its raw response artifact",
           ("test_an_abstention_that_discards_its_raw_artifact_is_refused_by_both_rules",), "gen2/schema/decision-receipt.schema.json",
           '"then": {"properties": {"raw_response_digest": {"type": "string"}, "raw_response_artifact": {"type": "object"}}}}',
           '"then": {"properties": {"raw_response_digest": {"type": "string"}}}}'),
          ("digest-without-artifact", "C1-audit", "a raw response digest may travel without its artifact",
           ("test_an_abstention_that_discards_its_raw_artifact_is_refused_by_both_rules",), "gen2/schema/decision-receipt.schema.json",
           '"then": {"properties": {"raw_response_artifact": {"type": "object"}}},\n          "else"', '"else"'),
          ("shadow-may-commit", "C1-audit", "shadow_log_only no longer forbids a commit operation",
           ("test_a_shadow_receipt_with_a_commit_is_refused_by_both_rules",), "gen2/schema/decision-receipt.schema.json",
           '"then": {"properties": {"outcome": {"properties": {"commit_operation_id": {"type": "null"}, "proposal_ref": {"type": "null"}, "hold_id": {"type": "null"}}}}}}',
           '"then": {"properties": {"outcome": {"properties": {"proposal_ref": {"type": "null"}, "hold_id": {"type": "null"}}}}}}'),
          ("non-commit-action-may-commit", "C1-audit", "an action other than commit_reversible_action may carry a commit operation",
           ("test_a_shadow_receipt_with_a_commit_is_refused_by_both_rules",), "gen2/schema/decision-receipt.schema.json",
           ',\n         "else": {"properties": {"outcome": {"properties": {"commit_operation_id": {"type": "null"}}}}}}', "}"),
          # Each identity member's removal: its own one-error negative now
          # validates, and the bare-identity count drops from three to two.
          *((f"identity-{member.replace('_', '-')}-not-required", "C1-audit", f"a running invocation's identity no longer requires {member}",
             (IDENTITY_KILLER[member], "test_a_bare_process_identity_is_refused_three_times"), "gen2/schema/invocation.schema.json",
             '"required": ["job_handle", "host_id", "container_id", "boot_id", "start_fingerprint"]',
             '"required": ' + json.dumps([m for m in IDENTITY if m != member]))
            for member in IDENTITY_KILLER),
          # Astra 0c-repair re-review BLOCK 3: drop one member and require
          # another twice. The bare-identity negative still reports three
          # `required` errors, so its count cannot see this (it survives).
          # The dropped member's own negative validates; the doubled one's
          # reports two errors where it declares one. The first is the
          # review's mutant, the other two its rotations.
          *((f"identity-{dropped.replace('_', '-')}-traded-for-a-second-{doubled.replace('_', '-')}", "C1-audit",
             f"identity stops requiring {dropped} and requires {doubled} twice, so the bare-identity count is unchanged",
             (IDENTITY_KILLER[dropped], IDENTITY_KILLER[doubled]), "gen2/schema/invocation.schema.json",
             '"required": ["job_handle", "host_id", "container_id", "boot_id", "start_fingerprint"],',
             '"required": ' + json.dumps([m for m in IDENTITY if m != dropped])
             + ',\n      "allOf": [{"required": ["' + doubled + '"]}],')
            for dropped, doubled in (("host_id", "boot_id"), ("boot_id", "start_fingerprint"), ("start_fingerprint", "host_id"))),
      )),
    # --- 0d: the one export API (operator ruling 2026-09-26) -------------------
    # export-manifest/2 absorbs publication-manifest/1 and export-manifest/1;
    # freshness-envelope/2 is re-scoped to engine reads of the local record.
    # Each mutant removes one rule (or restores a retired one) and the named
    # isolated negative must validate - or, for the over-restriction mutant, the
    # positive it names must stop validating.
    *(Mutation(f"0D-{key}", "0d", desc, tuple(SF + k for k in killers), target=target, old=old, new=new)
      for key, desc, killers, target, old, new in (
          ("connector-types-open-to-a-store-name", "the closed connector vocabulary gains a store kind (the retired named-store-as-sink shape)",
           ("test_an_undeclared_connector_type_is_refused",), "gen2/schema/common.schema.json",
           '"enum": ["sql", "jsonl_file", "webhook", "extension"]', '"enum": ["sql", "jsonl_file", "webhook", "extension", "graph_store"]'),
          ("manifest-connector-type-any-string", "the manifest stops using the closed connector vocabulary",
           ("test_an_undeclared_connector_type_is_refused",), MANIFEST,
           '"connector_type": {"$ref": "common.schema.json#/$defs/connector_type"},', '"connector_type": {"type": "string"},'),
          ("extension-implementation-not-required", "an extension connector need not name its implementation and review",
           ("test_an_extension_connector_without_its_implementation_is_refused",), MANIFEST,
           '{"if": {"properties": {"connector_type": {"const": "extension"}}}, "then": {"required": ["implementation"]}},\n', ''),
          ("reference-connector-may-claim-an-implementation", "a reference connector may name a module and a review",
           ("test_a_reference_connector_claiming_an_implementation_is_refused",), MANIFEST,
           ',\n          {"if": {"properties": {"connector_type": {"enum": ["sql", "jsonl_file", "webhook"]}}},\n           "then": {"not": {"required": ["implementation"]}}}', ''),
          ("connector-id-pattern-dropped", "a connector id need not spell its secret variable's suffix",
           ("test_a_connector_id_that_cannot_spell_its_variable_is_refused",), MANIFEST,
           '"propertyNames": {"$ref": "common.schema.json#/$defs/connector_id"},\n', ''),
          ("export-for-no-connector", "a manifest may name no connector",
           ("test_an_export_for_no_connector_is_refused",), MANIFEST,
           '"minProperties": 1,\n      "maxProperties": 100,', '"maxProperties": 100,'),
          ("approval-not-required", "a manifest need not name its approval (P-5)",
           ("test_an_export_without_an_approval_is_refused",), MANIFEST,
           '    "approval",\n    "bundle",\n', '    "bundle",\n'),
          ("tombstones-without-supersession", "a first manifest may carry tombstones",
           ("test_a_first_manifest_with_tombstones_is_refused",), MANIFEST,
           '"then": {"properties": {"tombstones": {"maxItems": 0}}}', '"then": {}'),
          ("generation-1-may-supersede-another-generation", "generation 1 may supersede a later generation",
           ("test_generation_1_supersedes_only_generation_1",), MANIFEST,
           '"then": {"properties": {"supersedes": {"properties": {"generation": {"const": 1}}}}}', '"then": {}'),
          ("generation-1-supersedes-nothing-restored", "the retired publication rule restored: generation 1 supersedes nothing, refusing a re-export of generation 1",
           ("test_generation_1_supersedes_only_generation_1",), MANIFEST,
           '"then": {"properties": {"supersedes": {"properties": {"generation": {"const": 1}}}}}', '"then": {"properties": {"supersedes": {"type": "null"}}}'),
          ("supersession-without-its-options-revision", "a supersession may name a generation without its options revision",
           ("test_a_supersession_names_its_whole_pair",), MANIFEST,
           '"required": ["manifest_id", "generation", "options_revision"],', '"required": ["manifest_id", "generation"],'),
          ("delivery-state-admitted", "a manifest may carry fields it does not define (delivery state included)",
           ("test_delivery_state_is_not_a_manifest_field",), MANIFEST,
           '"type": "object",\n  "additionalProperties": false,\n  "required": [', '"type": "object",\n  "additionalProperties": true,\n  "required": ['),
          ("publication-manifest-version-admitted", "the retired publication-manifest/1 version is accepted beside export-manifest/2",
           ("test_the_retired_publication_manifest_version_is_refused",), MANIFEST,
           '"manifest_version": {"const": "export-manifest/2"}', '"manifest_version": {"enum": ["export-manifest/2", "publication-manifest/1"]}'),
          ("complete-without-every-connector", "export delivery may be complete while a connector failed (P-4)",
           ("test_complete_export_delivery_needs_every_connector_delivered",), ENVELOPE,
           '"then": {"properties": {"connectors": {"additionalProperties": {"properties": {"status": {"const": "delivered"}}}}}}', '"then": {}'),
          ("delivered-without-its-pair", "a connector may be reported delivered without the pair it holds",
           ("test_a_delivered_connector_names_its_pair",), ENVELOPE,
           '"then": {"properties": {"delivered": {"type": "object"}, "last_successful_delivery_at": {"type": "string"}}}',
           '"then": {"properties": {"last_successful_delivery_at": {"type": "string"}}}'),
          ("projected-revision-restored", "the retired projected_revision field is back, so a read may claim a projection",
           ("test_a_read_cannot_claim_a_projected_revision",), ENVELOPE,
           '    "approval_status": {"enum": ["approved", "no_approved_revision"]},\n',
           '    "approval_status": {"enum": ["approved", "no_approved_revision"]},\n    "projected_revision": {"oneOf": [{"type": "null"}, {"$ref": "common.schema.json#/$defs/revision"}]},\n'),
          ("no-connectors-may-list-one", "no_connectors may list a connector",
           ("test_no_connectors_lists_none",), ENVELOPE,
           '"then": {"properties": {"connectors": {"maxProperties": 0}}},', '"then": {},'),
          ("delivery-status-about-no-connector", "a delivery status other than no_connectors may list no connector",
           ("test_a_delivery_status_is_about_at_least_one_connector",), ENVELOPE,
           '"else": {"properties": {"connectors": {"minProperties": 1}}}', '"else": {}'),
          ("served-without-an-approval", "a read may name an approved revision it served when nothing is approved (P-5)",
           ("test_nothing_approved_means_nothing_served",), ENVELOPE,
           '"then": {"properties": {"approved_revision_served": {"type": "null"}}}', '"then": {}'),
          ("completion-without-a-dossier", "completed may carry no dossier revision (P-4)",
           ("test_completion_is_at_a_dossier_revision",), ENVELOPE,
           '"then": {"properties": {"dossier_revision": {"type": "integer"}, "outcome": {"type": "string"}}}', '"then": {"properties": {"outcome": {"type": "string"}}}'),
          ("current-with-feed-issues", "current currency may list feed issues (P-6)",
           ("test_an_overdue_feed_is_not_current",), ENVELOPE,
           '"then": {"properties": {"as_of": {"type": "string"}, "feed_issues": {"maxProperties": 0}}}', '"then": {"properties": {"as_of": {"type": "string"}}}'),
          ("degraded-without-a-feed", "degraded currency may name no feed (A11)",
           ("test_degraded_currency_names_a_feed",), ENVELOPE,
           '"then": {"properties": {"feed_issues": {"minProperties": 1}}}', '"then": {}'),
          ("feed-reasons-open", "a feed issue may be any string (A11)",
           ("test_feed_issue_reasons_are_closed",), ENVELOPE,
           '"additionalProperties": {"enum": ["overdue", "failed_before_due", "never_ran", "unparseable_payload", "cursor_lost", "unknown"]}',
           '"additionalProperties": {"type": "string"}'),
      )),
    # --- 0d-repair: per-member replacement coverage (Astra 0d review, finding
    # 2). Each rule above had a negative that removed a whole object, so
    # weakening one member of it survived. Each mutant here weakens one member
    # (or restores the retired field in one shape), and its own one-error
    # negative must validate.
    *(Mutation(f"0DR-{key}", "0d-F2", desc, tuple(SF + k for k in killers), target=target, old=old, new=new)
      for key, desc, killers, target, old, new in (
          ("implementation-module-not-required", "an extension's implementation may omit its module (the review's survivor)",
           ("test_an_extension_implementation_names_its_module",), MANIFEST,
           '"required": ["module", "review_ref"],', '"required": ["review_ref"],'),
          ("implementation-review-not-required", "an extension's implementation may omit its review (the review's survivor)",
           ("test_an_extension_implementation_names_its_review",), MANIFEST,
           '"required": ["module", "review_ref"],', '"required": ["module"],'),
          ("mixed-generation-restored-as-a-boolean", "the retired mixed_generation field is back as a boolean (the review's survivor)",
           ("test_a_read_cannot_claim_mixed_generation",), ENVELOPE,
           '    "approval_status": {"enum": ["approved", "no_approved_revision"]},\n',
           '    "approval_status": {"enum": ["approved", "no_approved_revision"]},\n    "mixed_generation": {"type": "boolean"},\n'),
          ("mixed-generation-restored-as-in-envelope-1", "the retired mixed_generation field is back in its freshness-envelope/1 shape",
           ("test_a_read_cannot_claim_mixed_generation",), ENVELOPE,
           '    "approval_status": {"enum": ["approved", "no_approved_revision"]},\n',
           '    "approval_status": {"enum": ["approved", "no_approved_revision"]},\n'
           '    "mixed_generation": {"type": "object", "additionalProperties": false, "required": ["detected", "resolution"],'
           ' "properties": {"detected": {"type": "boolean"}, "resolution": {"enum": ["not_applicable", "pinned", "degraded"]}}},\n'),
          ("delivered-pair-without-its-options-revision", "a delivered pair may omit its options revision (the review's survivor)",
           ("test_a_delivered_pair_names_its_options_revision",), ENVELOPE,
           '"required": ["generation", "options_revision"],', '"required": ["generation"],'),
          ("delivered-pair-without-its-generation", "a delivered pair may omit its generation (the mirror of the review's survivor)",
           ("test_a_delivered_pair_names_its_generation",), ENVELOPE,
           '"required": ["generation", "options_revision"],', '"required": ["options_revision"],'),
      )),
    Mutation("0CR-operator-listen-on-container-loopback", "A6", "the review's defect restored: the engine binds its container's loopback",
             (SC + "test_services_listen_on_their_container_interface",), target="tools/gen_source_catalog.py",
             old='Key("GEN2_OPERATOR_LISTEN", "0.0.0.0:8770",', new='Key("GEN2_OPERATOR_LISTEN", "127.0.0.1:8770",'),
    Mutation("0D-store-specific-setting-added", "0d", "the generator emits a setting for one particular export destination (operator ruling 2026-09-26)",
             (SC + "test_the_engine_settings_name_no_export_destination",), target="tools/gen_source_catalog.py",
             old='            Key("GEN2_CONNECTORS_CONFIG", "/etc/gen2/bundle/connectors.toml", "mounted read-only"),\n',
             new='            Key("GEN2_CONNECTORS_CONFIG", "/etc/gen2/bundle/connectors.toml", "mounted read-only"),\n'
                 '            Key("GEN2_GRAPH_STORE_URL", "https://graph-store.example.org"),\n'),
    Mutation("0CR-checker-errors-collapsed-to-a-set", "C1", "the schema check compares declared and actual errors as sets again, so two rules at one signature pass as one",
             ("test_check_ddl_rules.SchemaFixtureRuleTest.test_two_rules_reporting_one_signature_must_both_be_declared",),
             target="tools/check_gen2_schemas.py", old="            if actual != expected:", new="            if set(actual) != set(expected):"),
    # --- 1b: the router (task 1b) -----------------------------------------------------
    # Each guard of the router boundary removed or weakened in a mutated copy
    # (gen2/router/*.py are "module" targets: the router and the test fixtures
    # are reloaded over the mutant) and killed by its isolated negative. Where
    # the DDL is the second layer the killer pins the router's own reason or
    # detail, so a mutant the store would still catch is killed by the
    # reason changing, not survived.
    *(Mutation(f"1B-{key}", "1b", desc, tuple(killers), target=target, old=old, new=new)
      for key, desc, killers, target, old, new in (
          # replay and identity
          ("replay-any-fingerprint", "a reused operation id replays whatever its content",
           (RC + "ReplayAndIdentityTest.test_the_same_operation_id_with_different_content_is_refused",), SVC,
           '        if row["request_fingerprint"] != fingerprint:', '        if False:'),
          ("replay-never", "a committed operation is not replayed (it is re-run)",
           (RC + "ReplayAndIdentityTest.test_replaying_a_committed_operation_returns_the_identical_receipt",
            RC + "ReplayAndIdentityTest.test_a_lost_reply_is_recovered_by_operation_id"), SVC,
           '        if row is None:\n            return None\n        if row["request_fingerprint"]', '        if True:\n            return None\n        if row["request_fingerprint"]'),
          ("rejection-not-logged", "a rejection is not logged (the audit trail loses refused operations)",
           (RC + "FencingTest.test_a_wrong_expected_revision_is_refused",), SVC,
           '            self._audit("commit_rejected", now,', '            None and self._audit("commit_rejected", now,'),
          # fencing
          ("lease-any", "a commit may name a lease the invocation does not run under",
           (RC + "FencingTest.test_the_gen1_probe_shapes_are_refused",), SVC,
           '        if lease_ref is not None and lease_ref["lease_id"] != lease["lease_id"]:', '        if False:'),
          ("lease-released-ignored", "a released lease still fences nothing (the store's check becomes the only one)",
           (RC + "ReplayAndIdentityTest.test_a_retained_receipt_authorizes_nothing_after_its_lease_ends",
            RC + "FencingTest.test_an_expired_lease_is_fenced_by_its_successor"), SVC,
           '        if lease["released_at"] is not None:\n            raise Refusal("lease_released"', '        if False:\n            raise Refusal("lease_released"'),
          ("generation-ignored", "a stale generation is not the router's refusal",
           (RC + "FencingTest.test_a_stale_generation_is_refused",), SVC,
           '        if lease_ref is not None and lease_ref["generation"] != lease["generation"]:', '        if False:'),
          ("expiry-ignored", "an expired, unreleased lease still commits and launches",
           (RC + "FencingTest.test_an_expired_but_unreleased_lease_is_not_current", RO + "TransitionTest.test_the_final_launch_admission_check"), SVC,
           '        if instant(now) >= instant(lease["expires_at"]):', '        if False:'),
          # time (Astra 1b review A1, C1): the clock is read once the write lock is held, and a lease or
          # deadline is over at its own instant; each lock-wait killer crosses the boundary while its request waits
          ("clock-before-lock", "every operation reads the clock before waiting for the write lock",
           tuple(RT + "LockWaitTest." + t for t in ("test_a_claim_whose_lease_ends_during_the_wait", "test_a_claim_whose_deadline_passes_during_the_wait",
                                                     "test_a_launch_whose_lease_ends_during_the_wait", "test_a_launch_whose_deadline_passes_during_the_wait",
                                                     "test_an_observation_whose_lease_ends_during_the_wait", "test_a_commit_whose_lease_ends_during_the_wait")), SVC,
           '            with self._store.transaction():\n                return body(self._now())',
           '            now = self._now()\n            with self._store.transaction():\n                return body(now)'),
          ("claim-clock-before-lock", "a claim is judged at the time it asked for the lock",
           (RT + "LockWaitTest.test_a_claim_whose_lease_ends_during_the_wait", RT + "LockWaitTest.test_a_claim_whose_deadline_passes_during_the_wait"), SVC,
           '            return self._guarded("request_invalid", lambda now: self._claim_in_transaction(req, now))',
           '            stale = self._now()\n            return self._guarded("request_invalid", lambda now: self._claim_in_transaction(req, stale))'),
          ("transition-clock-before-lock", "a launch is judged at the time it asked for the lock (L-7)",
           (RT + "LockWaitTest.test_a_launch_whose_lease_ends_during_the_wait", RT + "LockWaitTest.test_a_launch_whose_deadline_passes_during_the_wait"), SVC,
           '            return self._guarded("transition_not_allowed", lambda now: self._transition_in_transaction(req, facts, evidence, now))',
           '            stale = self._now()\n            return self._guarded("transition_not_allowed", lambda now: self._transition_in_transaction(req, facts, evidence, stale))'),
          ("observation-clock-before-lock", "an observation is judged at the time it asked for the lock",
           (RT + "LockWaitTest.test_an_observation_whose_lease_ends_during_the_wait",), SVC,
           '            return self._guarded("payload_invalid", lambda now: self._observation_in_transaction(req, now))',
           '            stale = self._now()\n            return self._guarded("payload_invalid", lambda now: self._observation_in_transaction(req, stale))'),
          ("commit-clock-before-lock", "a commit is fenced at the time it asked for the lock",
           (RT + "LockWaitTest.test_a_commit_whose_lease_ends_during_the_wait",), SVC,
           '            status, receipt = self._guarded("payload_invalid", lambda now: self._commit_in_transaction(env, fingerprint, checked, now))',
           '            stale = self._now()\n            status, receipt = self._guarded("payload_invalid", lambda now: self._commit_in_transaction(env, fingerprint, checked, stale))'),
          ("expiry-at-the-instant", "a lease is still current at its expiry instant",
           (RT + "ExactInstantTest.test_a_commit_at_its_lease_expiry_is_refused", RT + "ExactInstantTest.test_a_launch_at_its_lease_expiry_is_refused",
            RT + "ExactInstantTest.test_an_observation_at_its_lease_expiry_is_refused"), SVC,
           '        if instant(now) >= instant(lease["expires_at"]):', '        if instant(now) > instant(lease["expires_at"]):'),
          ("deadline-at-the-instant", "a launch at its deadline instant is admitted (L-7)",
           (RT + "ExactInstantTest.test_a_launch_at_its_deadline_is_refused",), SVC,
           '        if instant(now) >= instant(inv["deadline_at"]):\n            return Refusal("deadline_passed"',
           '        if instant(now) > instant(inv["deadline_at"]):\n            return Refusal("deadline_passed"'),
          ("claim-times-at-the-instant", "a claim whose lease or deadline is the current instant is granted",
           (RT + "ExactInstantTest.test_a_claim_whose_lease_or_deadline_is_now_is_refused",), SVC,
           '            if field in req and instant(req[field]) <= instant(now):', '            if field in req and instant(req[field]) < instant(now):'),
          ("lease-held-at-the-instant", "a lease still holds off its successor at its expiry instant",
           (RT + "ExactInstantTest.test_a_lease_is_superseded_at_its_expiry_and_not_before",), SVC,
           '            if instant(now) < instant(live["expires_at"]):', '            if instant(now) <= instant(live["expires_at"]):'),
          ("state-revision-ignored", "the expected state revision is not compared",
           (RC + "FencingTest.test_a_wrong_expected_revision_is_refused",), SVC,
           '        if topic["state_revision"] != env["expected_state_revision"]:', '        if False:'),
          ("admission-ignored", "the envelope's admission is not compared with the pins",
           (RC + "FencingTest.test_a_stale_admission_or_config_is_refused",), SVC,
           '        if not canonical.canonical_bytes(env["admission"]) == canonical.canonical_bytes(admission):', '        if False:'),
          ("config-ignored", "the envelope's config bundle is not compared with the pin",
           (RC + "FencingTest.test_a_stale_admission_or_config_is_refused",), SVC,
           '        if env["config_bundle_hash"] != inv["config_bundle_hash"]:\n            raise Refusal("config_bundle_mismatch", "the envelope',
           '        if False:\n            raise Refusal("config_bundle_mismatch", "the envelope'),
          ("pause-ignored", "a paused topic still commits",
           (RC + "FencingTest.test_a_paused_topic_commits_nothing",), SVC,
           '        if topic["paused_at"] is not None:\n            raise Refusal("topic_paused", f"paused at {topic[\'paused_at\']}")\n        self._require_current_pins(inv)',
           '        self._require_current_pins(inv)'),
          # task 1d moved the pin check to amendments.py (_pin_status), and 1d-repair to the recorded standing: a superseded pin is taken as current
          ("amendment-ignored", "work pinned to a superseded contract revision still commits (G-1)",
           (RC + "FencingTest.test_work_pinned_to_a_superseded_contract_is_not_committed",), "gen2/router/amendments.py",
           '            return self._standing("contract", inv["topic_id"], inv["contract_revision"]) or "compatible"', '            return "current"'),
          ("brief-amendment-ignored", "pre-contract work pinned to a superseded brief still commits",
           (RC + "FencingTest.test_work_pinned_to_a_superseded_brief_is_not_committed",), "gen2/router/amendments.py",
           '            return self._standing("brief", inv["topic_id"], inv["brief_version"], inv["brief_ref"]) or "lineage_only"', '            return "current"'),
          ("final-twice", "a second final outcome is not the router's refusal",
           (RC + "FencingTest.test_one_final_outcome_per_invocation",), SVC,
           '            if finals:\n                raise Refusal("final_outcome_exists"', '            if False:\n                raise Refusal("final_outcome_exists"'),
          ("final-without-result", "a final outcome commits without a staged result",
           (RC + "FencingTest.test_the_invocation_must_be_in_the_state_the_operation_needs",), SVC,
           '            if inv["state"] != "result_ready" or inv["result_payload_digest"] != env["payload_digest"]:', '            if False:'),
          ("final-other-document", "a final outcome commits a document other than the staged result",
           (RC + "FencingTest.test_the_invocation_must_be_in_the_state_the_operation_needs",), SVC,
           '            if inv["state"] != "result_ready" or inv["result_payload_digest"] != env["payload_digest"]:', '            if inv["state"] != "result_ready":'),
          ("interim-not-running", "an interim transition commits after the result was staged",
           (RC + "FencingTest.test_the_invocation_must_be_in_the_state_the_operation_needs",), SVC,
           '        elif inv["state"] != "running":\n            raise Refusal("invocation_state_invalid", f"an interim',
           '        elif False:\n            raise Refusal("invocation_state_invalid", f"an interim'),
          # authority
          ("capability-any-invocation", "a capability records facts for another invocation",
           (RO + "TransitionTest.test_only_the_invocations_capability_records_its_facts",), SVC,
           '        if inv["invocation_id"] != invocation_id:\n            raise Refusal("capability_invocation_mismatch"',
           '        if False:\n            raise Refusal("capability_invocation_mismatch"'),
          ("document-any-invocation", "an outcome document of another invocation is committed under this capability",
           (RC + "AuthorityTest.test_an_outcome_document_is_its_own_invocations",), SVC,
           '        if payload["invocation_id"] != inv["invocation_id"]:', '        if False:'),
          ("envelope-cross-topic", "an envelope naming another topic is committed to the invocation's",
           (RC + "FencingTest.test_a_cross_topic_write_is_refused", RC + "BoundaryValidationTest.test_an_unknown_topic_reports_no_state_revision"), SVC,
           '        if env["topic_id"] != inv["topic_id"]:', '        if False:'),
          ("document-cross-topic", "an outcome document about another topic is committed",
           (RC + "FencingTest.test_a_cross_topic_write_is_refused",), SVC,
           '        if payload["topic_id"] != inv["topic_id"]:', '        if False:'),
          ("envelope-schema-skipped", "the envelope is not validated (a role label is ignored, not refused)",
           (RC + "AuthorityTest.test_a_role_label_is_refused_not_ignored",), SVC,
           '            boundary.require_schema(self._schemas, env, "commit-outcome.schema.json", "envelope_invalid")\n', ''),
          ("sections-any-kind", "any invocation kind may commit any section",
           (RC + "AuthorityTest.test_a_producer_cannot_verify_its_own_work", RC + "AuthorityTest.test_discovery_and_delegate_work_hold_no_evidence_write_capability",
            RE + "ExportTest.test_only_primary_class_work_commits_exports"), BND,
           '        if kind not in kinds:', '        if False:'),
          ("pre-contract-sections", "pre-contract work commits protocol-bound sections",
           (RE + "ProductionAndAdoptionTest.test_scoping_work_promotes_nothing",), BND,
           '        if admission_context == "pre-contract/1" and section not in PRE_CONTRACT_SECTIONS:', '        if False:'),
          ("next-state-any-kind", "any kind proposes the topic's next queue state",
           (RC + "AuthorityTest.test_only_a_research_pass_proposes_the_next_queue_state",), SVC,
           '        if payload["next_queue_state"] is not None and inv["kind"] != "research_pass":', '        if False:'),
          ("verifier-not-committer", "a verification receipt is committed by an invocation other than its verifier",
           (RC + "AuthorityTest.test_a_producer_cannot_verify_its_own_work",), BND,
           '    if doc["verifier_invocation_id"] != invocation_id or doc["verifier_capability_id"] != capability_id:', '    if False:'),
          ("producer-verifies", "a receipt naming its verifier as the producer is not the router's refusal",
           (RC + "AuthorityTest.test_a_producer_cannot_verify_its_own_work",), BND,
           '    if doc["producer_invocation_id"] == invocation_id:', '    if False:'),
          # boundary validation: bytes, documents, sizes
          ("digest-unchecked", "staged bytes are not re-hashed against their label",
           (RC + "BoundaryValidationTest.test_a_payload_digest_that_does_not_match_the_bytes_is_refused",
            RC + "BoundaryValidationTest.test_a_result_ref_whose_label_is_not_its_bytes_is_refused"), BND,
           '    if digest != content_hash:', '    if False:'),
          ("size-unchecked", "staged sizes are not compared with the declared size",
           (RC + "BoundaryValidationTest.test_a_payload_digest_that_does_not_match_the_bytes_is_refused",), BND,
           '    if size is not None and len(raw) != size:', '    if False:'),
          ("document-schema-skipped", "the outcome document is not validated against its schema",
           (RC + "AuthorityTest.test_a_role_label_in_the_outcome_document_is_refused",), SVC,
           '        boundary.require_schema(self._schemas, payload, "outcome-document.schema.json", "payload_invalid")\n', ''),
          ("operation-kind-unchecked", "a final document is committed as an interim transition",
           (RC + "BoundaryValidationTest.test_the_document_is_for_the_envelopes_operation_kind",), SVC,
           '        if payload["operation_kind"] != env["operation_kind"]:', '        if False:'),
          ("envelope-unbounded", "the envelope's byte cap is not enforced",
           (RC + "BoundaryValidationTest.test_an_oversized_or_non_canonical_envelope_is_refused",), SVC,
           '            if len(canonical.canonical_bytes(env)) > ENVELOPE_MAX_BYTES:', '            if False:'),
          ("artifact-metadata-unchecked", "a reference may disagree with the recorded artifact's size or media type (A10)",
           (RC + "BoundaryValidationTest.test_an_artifact_is_one_record_whoever_references_it",), SVC,
           '            if stored is not None and (stored["size_bytes"], stored["media_type"]) != (ref["size_bytes"], ref["media_type"]):\n                raise Refusal("payload_invalid", f"{content_hash} is recorded as',
           '            if False:\n                raise Refusal("payload_invalid", f"{content_hash} is recorded as'),
          ("artifact-recheck-dropped", "an artifact recorded between validation and commit is not compared again (Astra 1b review A4)",
           (RC + "BoundaryValidationTest.test_an_artifact_recorded_meanwhile_is_held_to_what_was_validated",), SVC,
           '            if stored is not None and (stored["size_bytes"], stored["media_type"]) != (ref["size_bytes"], ref["media_type"]):\n                raise Refusal("payload_invalid", f"{content_hash} was recorded meanwhile',
           '            if False:\n                raise Refusal("payload_invalid", f"{content_hash} was recorded meanwhile'),
          # atomicity is structural (one transaction); the store's refusal must roll back the claim written before it
          ("store-refusal-swallowed", "a write the store refuses is reported as a failure, not a refusal",
           (RC + "AtomicityTest.test_a_store_refusal_inside_the_transaction_rolls_everything_back",), SVC,
           '        except (api.ConstraintViolation, api.StoreWriteError) as exc:', '        except api.StoreWriteError as exc:'),
          # effects
          ("ordinal-any-kind", "every final outcome asks for an ordinal (C-7)",
           (RE + "TriggerAndOrdinalTest.test_only_contract_research_passes_earn_ordinals", RX + "CrashMatrixTest.test_every_boundary_for_every_finalizing_kind"), SVC,
           '        if final and inv["kind"] == "research_pass" and inv["admission_context"] == "contract/1":', '        if final:'),
          ("lease-kept-after-final", "a final outcome does not release its lease",
           (RX + "CrashMatrixTest.test_every_boundary_for_every_finalizing_kind",
            RC + "ReplayAndIdentityTest.test_a_retained_receipt_authorizes_nothing_after_its_lease_ends"), SVC,
           '        if final and inv["kind"] != "delegate":\n            lease_release =', '        if False:\n            lease_release ='),
          ("delegate-releases-parent-lease", "a delegate's final outcome releases its parent's lease",
           (RX + "CrashMatrixTest.test_every_boundary_for_every_finalizing_kind",), SVC,
           '        if final and inv["kind"] != "delegate":\n            lease_release =', '        if final:\n            lease_release ='),
          ("queue-transition-dropped", "a research pass's final outcome leaves its topic active",
           (RC + "AtomicityTest.test_a_fault_at_each_point_leaves_nothing_or_everything",), SVC,
           '        if final and inv["kind"] == "research_pass" and topic["status"] == "active":', '        if False:'),
          ("held-rest-state", "a pass finishing under a hold reports its lease resting idle",
           (RC + "FencingTest.test_a_held_topic_is_left_held",), SVC,
           '        elif topic["status"] == "held":', '        elif False:'),
          ("trigger-reinserted", "a recorded trigger identity is recorded again (RG-1b(e))",
           (RE + "TriggerAndOrdinalTest.test_a_replayed_trigger_opens_nothing_new",), SVC,
           '        new_triggers = list({identity: t for identity, t in triggers if identity not in known}.items())',
           '        new_triggers = list({identity: t for identity, t in triggers}.items())'),
          # claims: production, adoption, promotion (V-10, the 1a review's carried obligation)
          ("claim-revision-gap", "a claim revision may skip numbers",
           (RE + "ProductionAndAdoptionTest.test_a_scoping_claim_is_adopted_by_a_revision_the_admitted_commit_produces",), SVC,
           '            if claim["revision"] != max((row["revision"] for row in prior), default=0) + 1:', '            if False:'),
          ("claim-cross-topic-revision", "a new revision of another topic's claim is recorded under this topic",
           (RC + "FencingTest.test_another_topics_claim_cannot_be_revised_or_promoted",), SVC,
           '            if any(row["topic_id"] != topic_id for row in prior):', '            if False:'),
          ("promotion-cross-topic", "another topic's claim is promoted",
           (RC + "FencingTest.test_another_topics_claim_cannot_be_revised_or_promoted",), SVC,
           '            if row["topic_id"] != topic_id:\n                raise Refusal("cross_topic", f"{promotion', '            if False:\n                raise Refusal("cross_topic", f"{promotion'),
          ("promotion-any-status", "an already accepted revision is promoted again",
           (RE + "ProductionAndAdoptionTest.test_only_a_provisional_or_contested_revision_is_promoted",), SVC,
           '            if row["status"] not in ("provisional", "contested"):', '            if False:'),
          # every artifact reference a document embeds, one rule (A10; Astra 1b review A4)
          ("artifact-ref-unstaged", "an embedded artifact reference need not be staged or recorded",
           (RE + "ProductionAndAdoptionTest.test_a_claims_text_is_staged_or_recorded", RE + "ProviderScreeningTest.test_the_raw_response_must_be_staged"), SVC,
           '            known = artifacts.get(ref["content_hash"]) or recorded_here(ref["content_hash"])', '            known = ref'),
          ("artifact-ref-metadata", "an embedded artifact reference may disagree with its artifact's size or media type",
           (RE + "ProductionAndAdoptionTest.test_a_claims_text_is_staged_or_recorded", RE + "ProviderScreeningTest.test_the_raw_response_reference_has_the_artifacts_size",
            RE + "ProviderScreeningTest.test_the_raw_response_reference_has_the_artifacts_media_type"), SVC,
           '            if (known["size_bytes"], known["media_type"]) != (ref["size_bytes"], ref["media_type"]):', '            if False:'),
          ("text-ref-not-bound", "a claim's text reference is not bound",
           (RE + "ProductionAndAdoptionTest.test_a_claims_text_is_staged_or_recorded",), SVC,
           '            bind(claim["text_ref"], f"{claim[\'claim_id\']}: its text")', '            pass'),
          ("canonical-bytes-unstaged", "reused canonical bytes need not be staged (V-3)",
           (RC + "AuthorityTest.test_canonical_bytes_are_staged_or_recorded",), SVC,
           '            if doc["extraction"]["method"] == "canonical_bytes" and not available(doc["obtained_content_hash"]):', '            if False:'),
          # decisions and screening (A10)
          ("raw-response-not-bound", "a decision's raw response reference is not bound: unstaged, or another size or media type (D-1; Astra 1b review A4)",
           (RE + "ProviderScreeningTest.test_the_raw_response_must_be_staged", RE + "ProviderScreeningTest.test_the_raw_response_reference_has_the_artifacts_size",
            RE + "ProviderScreeningTest.test_the_raw_response_reference_has_the_artifacts_media_type"), SVC,
           '                bind(response["raw_response_artifact"], f"{doc[\'decision_receipt_id\']}: its raw response")', '                pass'),
          ("raw-digest-not-its-artifact", "a raw response digest may differ from its artifact's hash (the DDL becomes the only check)",
           (RE + "ProviderScreeningTest.test_the_raw_response_digest_is_its_artifacts_hash",), SVC,
           '                if response["raw_response_digest"] != response["raw_response_artifact"]["content_hash"]:', '                if False:'),
          ("abstention-hold-unknown", "an abstention may name a hold that does not exist",
           (RE + "ProviderScreeningTest.test_an_abstention_hold_is_one_this_commit_creates_or_one_recorded",), SVC,
           '            if hold is not None and hold not in hold_ids and self._one("holds", {"hold_id": hold}) is None:', '            if False:'),
          ("decision-other-invocation", "a decision receipt of another invocation is committed",
           (RE + "ProviderScreeningTest.test_a_receipt_records_a_call_of_the_committing_invocation",), BND,
           '    if doc["invocation_id"] != invocation_id:', '    if False:'),
          ("spec-hash-untrue", "a stored DecisionSpec's hash is not recomputed (RA6)",
           (RE + "ProviderScreeningTest.test_the_spec_must_hash_to_its_label",), BND,
           '    if canonical.logical_hash(spec_document) != doc["spec"]["spec_hash"]:', '    if False:'),
          ("qualification-unchecked", "a qualification reference is taken as qualification (INVARIANTS §13)",
           (RE + "ProviderScreeningTest.test_no_qualification_record_means_no_qualified_authority",), BND,
           '    if authorization["authority_level"] == "qualified" and not qualifications.is_qualified(', '    if False and not qualifications.is_qualified('),
          ("decision-commit-elsewhere", "a receipt whose action another operation committed is recorded here (D-2)",
           (RE + "ProviderScreeningTest.test_a_receipt_committed_by_another_operation_is_refused",), BND,
           '    if doc["outcome"]["commit_operation_id"] not in (None, operation_id):', '    if False:'),
          ("screening-foreign-criteria", "an assessment may cite criteria its protocol version does not have",
           (RE + "ScreeningTest.test_criterion_results_are_the_protocols_and_consistent",), BND,
           '    criteria = {c["criterion_id"]: c for c in protocol["criteria"]}',
           '    criteria = {c["criterion_id"]: c for c in protocol["criteria"]} | {cid: {"stage": "metadata"} for cid in assessment["criterion_results"]}'),
          ("screening-stage", "a criterion may be decided before its stage",
           (RE + "ScreeningTest.test_criterion_results_are_the_protocols_and_consistent",), BND,
           '        if result != "unknown" and STAGE[criteria[cid]["stage"]] > STAGE[assessment["stage"]]:', '        if False:'),
          ("screening-exclusion-on-unknown", "missing information excludes (an exclusion without a criterion not met)",
           (RE + "ScreeningTest.test_criterion_results_are_the_protocols_and_consistent",), BND,
           '    if assessment["decision"] == "exclude" and not not_met:', '    if False:'),
          ("screening-inclusion-with-not-met", "an inclusion may have criteria not met",
           (RE + "ScreeningTest.test_criterion_results_are_the_protocols_and_consistent",), BND,
           '    if assessment["decision"] == "include" and not_met:', '    if False:'),
          ("screening-answer", "a provider assessment need not be its receipt's answer",
           (RE + "ProviderScreeningTest.test_the_assessment_must_be_the_receipts_answer",), BND,
           '            or answer.get("selected_option_id") != assessment["decision"] or receipt["action"]', '            or receipt["action"]'),
          ("screening-subject", "a provider assessment need not be about its receipt's work",
           (RE + "ProviderScreeningTest.test_the_assessment_must_be_the_receipts_answer",), BND,
           '    if (receipt["decision_class"] != "screening" or receipt["subject"] != {"kind": "work", "ref": assessment["work_id"]}',
           '    if (receipt["decision_class"] != "screening"'),
          ("screening-spec-protocol", "a receipt's spec may be for another protocol version",
           (RE + "ProviderScreeningTest.test_the_spec_is_for_this_invocations_admission",), BND,
           '    if spec_protocol.get("eligibility_protocol_version") != version:', '    if False:'),
          # the spec's protocol context is the committing invocation's admission (C-12, D-1, D-4; Astra 1b review A3)
          ("screening-spec-topic", "a receipt's spec may be for another topic",
           (RE + "ProviderScreeningTest.test_the_spec_is_for_this_invocations_admission",), BND,
           '    if spec_protocol.get("topic_id") != admitted["topic_id"]:', '    if False:'),
          ("screening-spec-contract-revision", "a receipt's spec may name another contract revision than the admitted one",
           (RE + "ProviderScreeningTest.test_the_spec_is_for_this_invocations_admission",), BND,
           '    if contract.get("revision") != admitted["contract"]["revision"]:', '    if False:'),
          ("screening-spec-contract-hash", "a receipt's spec may pin another contract hash than the admitted revision's",
           (RE + "ProviderScreeningTest.test_the_spec_is_for_this_invocations_admission",), BND,
           '    if contract.get("content_hash") != admitted["contract"]["content_hash"]:', '    if False:'),
          # observations (A10, E-2, H-5, RG-U)
          ("observation-count", "an observed count need not be its captured identities (E-2)",
           (RO + "ObservationTest.test_a_complete_count_is_its_captured_identities", RO + "ObservationTest.test_a_partial_set_keeps_what_was_seen_as_a_lower_bound"), BND,
           '    if observation["result_count"] != len(events):', '    if False:'),
          ("observation-unobserved", "an unobserved set may carry records or a count (RG-U)",
           (RO + "ObservationTest.test_unknown_is_not_zero",), BND,
           '        if events or observation["result_count"] is not None:', '        if False:'),
          ("request-identity", "a request identity need not be its request's hash (H-5)",
           (RO + "ObservationTest.test_a_request_identity_is_the_hash_of_its_request",), BND,
           '    if canonical.logical_hash(observation["request"]) != observation["request_identity"]:', '    if False:'),
          ("observation-time-order", "an observation may end before it starts",
           (RO + "ObservationTest.test_impossible_or_contradictory_times_are_refused",), BND,
           '    if observation["ended_at"] is not None and instant(observation["ended_at"]) < instant(observation["started_at"]):', '    if False:'),
          ("observation-duplicate-record", "a record is captured twice for one observation",
           (RO + "ObservationTest.test_a_record_is_captured_once_per_observation",), BND,
           '    if len(set(records)) != len(records):', '    if False:'),
          ("observation-running-only", "a failed invocation records observations",
           (RO + "ObservationTest.test_only_a_running_invocation_records_observations",), SVC,
           '        if inv["state"] != "running":\n            raise Refusal("invocation_state_invalid", f"observations',
           '        if False:\n            raise Refusal("invocation_state_invalid", f"observations'),
          ("observation-lease-unchecked", "a running invocation records observations after its lease expired (Astra 1b review C1)",
           (RO + "ObservationTest.test_a_running_invocation_past_its_lease_records_nothing", RT + "ExactInstantTest.test_an_observation_at_its_lease_expiry_is_refused"), SVC,
           '        self._require_current_lease(inv, now)\n        topic = self._one(', '        topic = self._one('),
          ("observation-pause-unchecked", "a paused topic records observations",
           (RO + "ObservationTest.test_a_paused_topic_records_no_observation",), SVC,
           '        if topic["paused_at"] is not None:\n            raise Refusal("topic_paused", f"paused at {topic[\'paused_at\']}")\n        self._store.insert("search_observations"',
           '        self._store.insert("search_observations"'),
          ("observation-conflict", "an observation id with other content replays",
           (RO + "ObservationTest.test_replay_and_conflict_by_observation_id",), SVC,
           '            if not same:\n                raise Refusal("observation_id_conflict"', '            if False:\n                raise Refusal("observation_id_conflict"'),
          # exports (EXPORT-API.md §5, §7)
          ("extension-admitted-by-name", "an extension connector is admitted by naming a module and review",
           (RE + "ExportTest.test_an_extension_is_admitted_only_by_the_registry",), BND,
           '            if not extensions.is_admitted(module=impl["module"], review_ref=impl["review_ref"]):', '            if False:'),
          ("bundle-not-with-commit", "the bundle may be any staged bytes, not staged with the commit",
           (RE + "ExportTest.test_the_bundle_is_staged_canonical_and_valid",), SVC,
           '            if bundle_hash not in staged:\n                raise Refusal("payload_missing", f"{manifest[\'manifest_id\']}: its bundle {bundle_hash} is not staged with this commit")\n'
           '            manifests.append((manifest, boundary.check_manifest(manifest, inv["topic_id"], self._extensions, staged[bundle_hash], self._schemas)))',
           '            manifests.append((manifest, boundary.check_manifest(manifest, inv["topic_id"], self._extensions, staged.get(bundle_hash) or self._spool.read(bundle_hash, topic_id=inv["topic_id"]), self._schemas)))'),
          ("bundle-not-canonical", "a bundle staged in a non-canonical form is exported",
           (RE + "ExportTest.test_the_bundle_is_staged_canonical_and_valid",), BND,
           '    if canonical.canonical_bytes(bundle) != bundle_raw:', '    if False:'),
          ("bundle-schema-skipped", "the bundle is not validated against export-bundle/1",
           (RE + "ExportTest.test_the_bundle_is_staged_canonical_and_valid",), BND,
           '    require_schema(schemas, bundle, "export-bundle.schema.json", "payload_invalid")', '    pass'),
          ("bundle-identity", "the staged bundle need not be the one the manifest names",
           (RE + "ExportTest.test_the_staged_bundle_is_the_one_the_manifest_names",), BND,
           '    if bundle["bundle_id"] != manifest["bundle"]["bundle_id"] or bundle["topic_id"] != topic_id:', '    if False:'),
          ("manifest-cross-topic", "a manifest of another topic is not the router's refusal",
           (RE + "ExportTest.test_unapproved_or_foreign_material_is_not_exported",), BND,
           '    if manifest["topic_id"] != topic_id:', '    if False:'),
          ("hold-fact-unrecorded", "a capability hold may cite an unrecorded fact (the store's key becomes the only check)",
           (RE + "HoldTest.test_a_capability_hold_cites_a_recorded_fact",), SVC,
           '            if fact is not None and self._one("capability_facts", {"fact_id": fact}) is None:', '            if False:'),
          # claim (leases, admission, delegates)
          ("claim-status-gate", "a lease is granted whatever the topic's status",
           (RO + "ClaimTest.test_topic_state_gates_claims",), SVC,
           '        if topic["status"] not in claimable:', '        if False:'),
          ("lease-held-ignored", "a live lease is superseded as if expired",
           (RO + "ClaimTest.test_one_live_lease_per_topic_and_scope",), SVC,
           '            if instant(now) < instant(live["expires_at"]):', '            if False:'),
          ("expired-lease-kept", "an expired lease is not released before its successor",
           (RO + "ClaimTest.test_an_expired_lease_is_released_and_superseded",), SVC,
           '            self._store.update("leases", {"lease_id": live["lease_id"]}, {"released_at": now, "release_reason": "expired"})', '            pass'),
          ("admission-any-kind", "pre-contract admission is offered to every kind (C-12)",
           (RO + "ClaimTest.test_pre_contract_admission_is_for_scoping_kinds_only",), SVC,
           '        if kind not in ("discovery", "research_pass") or any(c["status"] != "draft" for c in contracts):',
           '        if any(c["status"] != "draft" for c in contracts):'),
          ("claim-replay-after-time-checks", "a lost claim reply is refused once its deadline has passed",
           (RO + "ClaimTest.test_a_lost_claim_reply_is_recovered_by_invocation_id",), SVC,
           '        if existing is not None:\n            return self._claim_replay(req, existing)  # a lost reply gets its grant back, whatever the time now\n'
           '        for field in ("deadline_at", "lease_expires_at"):\n            if field in req and instant(req[field]) <= instant(now):\n'
           '                raise Refusal("request_invalid", f"{field} {req[field]} is not after {now}")\n',
           '        for field in ("deadline_at", "lease_expires_at"):\n            if field in req and instant(req[field]) <= instant(now):\n'
           '                raise Refusal("request_invalid", f"{field} {req[field]} is not after {now}")\n'
           '        if existing is not None:\n            return self._claim_replay(req, existing)  # a lost reply gets its grant back, whatever the time now\n'),
          ("claim-replay-any-request", "an invocation id replays whatever the request",
           (RO + "ClaimTest.test_a_lost_claim_reply_is_recovered_by_invocation_id",), SVC,
           '        if not same:\n            raise Refusal("invocation_id_conflict"', '        if False:\n            raise Refusal("invocation_id_conflict"'),
          ("delegate-parent-state", "a delegate is admitted under a parent that is not running (L-8)",
           (RO + "ClaimTest.test_a_delegate_runs_under_its_running_parent",), SVC,
           '        if parent["kind"] == "delegate" or parent["state"] not in ("launching", "running"):', '        if False:'),
          ("delegate-config", "a delegate is admitted under another config bundle than its parent's",
           (RO + "ClaimTest.test_a_delegate_runs_under_its_running_parent",), SVC,
           '        if parent["config_bundle_hash"] != req["config_bundle_hash"]:', '        if False:'),
          ("delegate-cross-topic", "a delegate's parent may be another topic's",
           (RO + "ClaimTest.test_a_delegate_runs_under_its_running_parent",), SVC,
           '        if parent["topic_id"] != topic["topic_id"]:', '        if False:'),
          # lifecycle facts (L-1, L-2, L-7)
          ("launch-when-paused", "launch skips the pause check (L-7)",
           (RO + "TransitionTest.test_the_final_launch_admission_check", LC + "StatusAndSpoolTest.test_status_reports_the_current_launch_admission_check"), SVC,
           '        if topic["paused_at"] is not None:\n            return Refusal("topic_paused", f"paused at {topic[\'paused_at\']}")\n', ''),
          ("launch-without-lease", "launch skips the lease check (L-7)",
           (RO + "TransitionTest.test_the_final_launch_admission_check", LC + "StatusAndSpoolTest.test_status_reports_the_current_launch_admission_check"), SVC,
           '        try:\n            self._require_current_lease(inv, now)\n        except Refusal as refusal:\n            return refusal\n', ''),
          ("launch-after-deadline", "launch skips the deadline check (L-7)",
           (RO + "TransitionTest.test_launch_after_the_deadline_is_refused", LC + "StatusAndSpoolTest.test_status_reports_the_current_launch_admission_check"), SVC,
           '        if instant(now) >= instant(inv["deadline_at"]):\n            return Refusal("deadline_passed"', '        if False:\n            return Refusal("deadline_passed"'),
          ("result-not-staged", "a result is recorded ready without its bytes staged (C-9)",
           (RO + "TransitionTest.test_a_result_is_ready_only_when_its_bytes_are_staged",), SVC,
           '                boundary.staged(self._spool, facts["result_payload_digest"], topic_id=inv["topic_id"], media_type="application/json")', '                pass'),
          ("result-staged-before-replay", "a recorded result_ready is asked for its staged bytes before it replays or conflicts (Astra 1b-repair review A5-R)",
           (RR + "RestartTest.test_a_committed_result_replays_without_its_staged_bytes",
            RR + "RestartTest.test_a_committed_result_resent_with_an_unstaged_digest_conflicts"), SVC,
           '            replay = self._recorded_transition(req, facts)\n            if replay is not None:\n                return replay\n'
           '            self._fault("transition_checked")\n'
           '            inv = self._capability(req["capability_id"], req["invocation_id"])  # its topic and job handle are write-once\n',
           '            inv = self._capability(req["capability_id"], req["invocation_id"])  # its topic and job handle are write-once\n'
           '            if target == "result_ready":\n'
           '                boundary.staged(self._spool, facts["result_payload_digest"], topic_id=inv["topic_id"], media_type="application/json")\n'
           '            replay = self._recorded_transition(req, facts)\n            if replay is not None:\n                return replay\n'),
          ("failure-keeps-lease", "a failed invocation keeps its lease and its topic active",
           (RO + "TransitionTest.test_a_failure_releases_the_lease_and_requeues",), SVC,
           '        if target in ("failed", "cancelled"):\n            self._release_capacity(inv, now, target)\n', ''),
          ("transition-facts-unchecked", "a lifecycle state is recorded with other facts than its own",
           (RO + "TransitionTest.test_each_state_is_recorded_with_exactly_its_facts",), SVC,
           '            if set(facts) - wanted or wanted - {"container_id"} - set(facts) or ("unknown_cause" in req) != (target == "outcome_unknown"):', '            if False:'),
          ("transition-replay-current-only", "a recorded fact replays only while it is the current state (Astra 1b review A5)",
           (RO + "TransitionTest.test_a_recorded_fact_replays_after_the_invocation_moves_on", RR + "RestartTest.test_recorded_facts_replay_after_a_restart"), SVC,
           '        recorded = self._one("invocation_transitions", {"invocation_id": req["invocation_id"], "to_state": target, "cause": LIFECYCLE_CAUSE[target]})\n'
           '        if recorded is None:\n            return None\n        inv = self._capability(req["capability_id"], req["invocation_id"])\n',
           '        inv = self._capability(req["capability_id"], req["invocation_id"])\n        if inv["state"] != target:\n            return None\n'),
          ("transition-omitted-fact-ignored", "a replay that leaves out a recorded optional fact (container_id) is taken for the same fact",
           (RO + "TransitionTest.test_a_recorded_fact_replays_after_the_invocation_moves_on",), SVC,
           '            facts = {k: facts.get(k) for k in LIFECYCLE_FACTS[target]}  # an omitted container_id is recorded, and compared, as none\n', ''),
          ("transition-conflict-replayed", "a recorded fact is replaced by a conflicting one as a replay",
           (RO + "TransitionTest.test_the_lifecycle_moves_along_l1_only",), SVC,
           '        if any(inv[k] != v for k, v in facts.items()):', '        if False:'),
          # operator decisions (G-13, RA6)
          ("subject-hash-untrue", "a stored subject's hash label is not recomputed before approval (RA6)",
           (RO + "OperatorDecisionTest.test_approval_binds_to_a_hash_that_is_true_of_the_stored_document",), SVC,
           '        if stored is not None and canonical.content_hash(stored["document"]) != stored["content_hash"]:', '        if False:'),
          ("decision-replay-any-content", "a decision id replays whatever the content",
           (RO + "OperatorDecisionTest.test_brief_confirmation_moves_intake_to_scoping",), SVC,
           '            if canonical.canonical_bytes(existing) != canonical.canonical_bytes(row):', '            if False:'),
          ("decision-move-optional", "a decision whose transition the state forbids is recorded anyway",
           (RO + "OperatorDecisionTest.test_a_decision_whose_transition_the_state_forbids_is_refused_whole",), SVC,
           '        if target is None and required:', '        if False:'),
          ("approval-without-supersession", "an amendment approval leaves the earlier revision approved",
           (RO + "OperatorDecisionTest.test_contract_approval_queues_the_topic_and_an_amendment_supersedes",), SVC,
           '            self._store.update("contract_revisions", {**key, "revision": previous["revision"]}, {"status": "superseded"})', '            pass'),
          # delivery receipts (P-2, P-7, H-2)
          ("ack-replay-any-content", "an export receipt id replays whatever the content",
           (RO + "AckDeliveryTest.test_a_delivery_is_recorded_once_and_advances_the_watermark", RO + "AckDeliveryTest.test_a_replay_is_the_same_document"), SVC,
           '            if canonical.canonical_bytes(existing["receipt"]) != canonical.canonical_bytes(doc):', '            if False:'),
          ("ack-replay-projection-only", "a replay compares only the old column projection (Astra 1b review A2: topic, pair, count and references ignored)",
           (RO + "AckDeliveryTest.test_a_replay_is_the_same_document", RR + "RestartTest.test_delivery_receipts_read_back_whole_after_a_restart"), SVC,
           '            if canonical.canonical_bytes(existing["receipt"]) != canonical.canonical_bytes(doc):',
           '            if any(existing[k] != doc.get(k) for k in ("manifest_id", "attempt", "status", "error_class", "unknown_cause", "capability_fact_id", "attempted_at", "acked_at")):'),
          ("ack-hold-unchecked", "a receipt may name a hold that is not recorded (the store's trigger becomes the only check)",
           (RO + "AckDeliveryTest.test_a_named_hold_is_one_of_the_manifests_topic",), SVC,
           '        if hold is not None and self._one("holds", {"hold_id": hold, "topic_id": event["topic_id"]}) is None:', '        if False:'),
          ("ack-hold-any-topic", "a receipt may name another topic's hold",
           (RO + "AckDeliveryTest.test_a_named_hold_is_one_of_the_manifests_topic",), SVC,
           '{"hold_id": hold, "topic_id": event["topic_id"]}', '{"hold_id": hold}'),
          ("ack-manifest-description", "a receipt need not describe its manifest's topic and pair",
           (RO + "AckDeliveryTest.test_a_receipt_must_describe_its_manifest",), SVC,
           '        if doc["topic_id"] != event["topic_id"] or (doc["generation"], doc["options_revision"]) != (event["generation"], event["options_revision"]):', '        if False:'),
          ("ack-attempt-order", "attempts need not be numbered in order",
           (RO + "AckDeliveryTest.test_a_receipt_must_describe_its_manifest",), SVC,
           '        if doc["attempt"] != len(attempts) + 1:', '        if False:'),
          ("watermark-regression", "a delivery of an older pair is recorded without refusal (P-2)",
           (RO + "AckDeliveryTest.test_the_watermark_never_regresses",), SVC,
           '        elif pair < (mark["generation"], mark["options_revision"]):', '        elif False:'),
          ("watermark-not-advanced", "a delivery of a newer pair leaves the watermark behind",
           (RO + "AckDeliveryTest.test_the_watermark_never_regresses",), SVC,
           '        elif pair > (mark["generation"], mark["options_revision"]):', '        elif False:'),
          ("fact-not-transition-only", "a failure raises a new fact while the connector is already failing (H-2)",
           (RO + "AckDeliveryTest.test_failures_raise_capability_facts_on_transitions",), SVC,
           '        elif current is not None and current["state"] == state:', '        elif False:'),
          ("fact-recovery-dropped", "a delivery after a failure records no recovery",
           (RO + "AckDeliveryTest.test_failures_raise_capability_facts_on_transitions",), SVC,
           '            if current is None or current["state"] == state:\n                return', '            if True:\n                return'),
          # instants (task 1b's exact ordering)
          ("instant-fraction-unscaled", "fraction digits are read as an integer, not as nanoseconds",
           (IN.replace("UtcInstantTest.", "UtcInstantOrderTest.") + "test_time_order_is_not_text_order",
            IN.replace("UtcInstantTest.", "UtcInstantOrderTest.") + "test_nanoseconds_since_the_epoch"), "gen2/core/instants.py",
           '+ int(fraction.ljust(9, "0"))', '+ int(fraction or "0")'),
          ("instant-fraction-dropped", "the fraction is ignored",
           (IN.replace("UtcInstantTest.", "UtcInstantOrderTest.") + "test_time_order_is_not_text_order",), "gen2/core/instants.py",
           '    fraction = value[20:-1] if value[19] == "." else ""', '    fraction = ""'),
          ("instant-unvalidated", "an impossible instant is converted instead of refused",
           (IN.replace("UtcInstantTest.", "UtcInstantOrderTest.") + "test_invalid_instants_are_refused",), "gen2/core/instants.py",
           '    if not is_utc_instant(value):\n        raise ValueError', '    if False:\n        raise ValueError'),
      )),
    # the router's validator, against the jsonschema oracle (tools/gen2_schema_oracle.py)
    *(Mutation(f"1B-schema-{key}", "1b", desc, (RS + "DifferentialTest.test_every_fixture_and_its_mutations_get_the_oracles_verdict", *extra),
               target="gen2/router/schemas.py", old=old, new=new)
      for key, desc, extra, old, new in (
          ("additional-properties", "additionalProperties is ignored", (), '            elif "additionalProperties" in schema:', '            elif False:'),
          ("required", "required is ignored", (), "            if key not in value:\n", "            if False:\n"),
          ("one-of-zero", "oneOf accepts a value matching none", (), "            if matched != 1:", "            if matched > 1:"),
          ("if-then", "if/then/else is ignored", (), '            if branch in schema:', '            if False:'),
          ("integer-strict", "an integral float is not an integer (2020-12 says it is)", (),
           "    return _is_number(value) and (isinstance(value, int) or value.is_integer())", "    return _is_number(value) and isinstance(value, int)"),
          ("bool-is-number", "true is a number", (), "    return isinstance(value, (int, float)) and not isinstance(value, bool)", "    return isinstance(value, (int, float))"),
          ("unique", "uniqueItems is ignored", (), "                if key in seen:", "                if False:"),
          ("min-items", "minItems is ignored", (), '        if "minItems" in schema and len(value) < schema["minItems"]:', "        if False:"),
          ("enum", "enum is ignored", (), '        if "enum" in schema and not any(json_equal(value, option) for option in schema["enum"]):', "        if False:"),
          ("not", "not is ignored", (), '        if "not" in schema and self.is_valid(value, schema["not"], base):', "        if False:"),
          ("contains", "minContains is ignored", (), '            if found < schema.get("minContains", 1):', "            if False:"),
          ("property-names", "propertyNames is ignored", (), '            if "propertyNames" in schema:', "            if False:"),
          ("minimum", "minimum is ignored", (), '(("minimum", lambda b: value < b),', '(("minimum", lambda b: False),'),
          ("pattern", "pattern is ignored", (), '        if "pattern" in schema and not self._patterns[schema["pattern"]].search(value):', "        if False:"),
          ("date-time", "date-time is only a shape (February 30 passes)", (RS + "StricterThanOracleTest.test_date_time_is_a_real_instant",),
           '        if schema.get("format") == "date-time" and not instants.is_utc_instant(value):', "        if False:"),
      )),
    Mutation("1B-duplicate-keys-merged-at-the-boundary", "1b", "the router reads a duplicated key's last value instead of refusing the document (C-13; Astra 1b review C2)",
             (RC + "BoundaryValidationTest.test_a_schema_invalid_document_is_refused",), target="gen2/core/canonical.py",
             old="        if key in out:\n            raise CanonicalizationError(f\"duplicate object key {key!r}\")\n", new=""),
    *(Mutation(f"1B-schema-{key}", "1b", desc, (RS + killer,), target="gen2/router/schemas.py", old=old, new=new)
      for key, desc, killer, old, new in (
          ("max-length", "maxLength is ignored", "BoundsTest.test_bounds_at_their_edges", '        if "maxLength" in schema and len(value) > schema["maxLength"]:', "        if False:"),
          ("max-items", "maxItems is ignored", "BoundsTest.test_bounds_at_their_edges", '        if "maxItems" in schema and len(value) > schema["maxItems"]:', "        if False:"),
          ("max-properties", "maxProperties is ignored", "BoundsTest.test_bounds_at_their_edges", '        if "maxProperties" in schema and len(value) > schema["maxProperties"]:', "        if False:"),
          ("exclusive-minimum", "exclusiveMinimum is read as minimum", "BoundsTest.test_bounds_at_their_edges",
           '("exclusiveMinimum", lambda b: value <= b)', '("exclusiveMinimum", lambda b: value < b)'),
          ("maximum", "maximum is ignored", "BoundsTest.test_bounds_at_their_edges", '("maximum", lambda b: value > b)', '("maximum", lambda b: False)'),
      )),
    Mutation("1B-schema-end-anchor-python", "1b", "a pattern's `$` also matches before a trailing newline (Python's reading, not ECMA-262's)",
             (RS + "StricterThanOracleTest.test_a_trailing_newline_does_not_satisfy_an_anchored_pattern",), target="gen2/router/schemas.py",
             old='    body = pattern[:-1] + r"\\Z" if pattern.endswith("$") and not pattern.endswith("\\\\$") else pattern\n    if re.search(r"(?<!\\\\)\\$", body):\n        raise SchemaError(f"pattern {pattern!r}: `$` is supported only at the end")\n', new="    body = pattern\n"),
    # rule 9 of the boundary graph: only the router reaches the store's write primitives
    Mutation("1B-store-writer-rule-dropped", "1b", "the boundary checker no longer reports a store write primitive reached outside the store writers",
             (CB + "test_only_the_store_writers_reach_store_write_primitives", CB + "test_store_writes_are_the_routers_under_the_real_graph"),
             target="tools/check_boundaries.py", old="    violations.extend(store_write_violations(rel, mod, refs, cfg))\n", new=""),
    Mutation("1B-store-writer-defining-module-flagged", "1b", "the store module is reported for using its own primitives (the rule over-restricts)",
             (CB + "test_only_the_store_writers_reach_store_write_primitives",), target="tools/check_boundaries.py",
             old="            if (owner is not None and owner.name != mod.name and (lineno, primitive) not in seen", new="            if (owner is not None and (lineno, primitive) not in seen"),
    Mutation("1B-store-writer-attribute-chains-ignored", "1b", "only imports are checked, not attribute chains (api.Store.insert passes)",
             (CB + "test_only_the_store_writers_reach_store_write_primitives",), target="tools/check_boundaries.py",
             old='        if kind == "builtin":\n            continue\n        for primitive in cfg.store_write_primitives:',
             new='        if kind != "import":\n            continue\n        for primitive in cfg.store_write_primitives:'),
    Mutation("1B-store-writer-config-unchecked", "1b", "a store_writers entry naming no module is accepted",
             (CB + "test_store_rule_configuration_is_checked",), target="tools/check_boundaries.py",
             old='                errors.append(f"{config_rel}: {key} names undeclared module {name!r}")', new="                pass"),
    Mutation("1B-real-graph-writers-widened", "1b", "the real graph lets the composition root write the store",
             (CB + "test_store_writes_are_the_routers_under_the_real_graph",), target="gen2/boundaries.toml",
             old='store_writers = ["router"]', new='store_writers = ["router", "app"]'),
    Mutation("1B-real-graph-primitives-dropped", "1b", "the real graph lists no store write primitive (rule 9 off)",
             (CB + "test_store_writes_are_the_routers_under_the_real_graph",), target="gen2/boundaries.toml",
             old='store_write_primitives = ["gen2.store.api.Store", "gen2.store.api.open_store", "gen2.store.api.adopt_in_memory", "gen2.store.db.connect"]',
             new='store_write_primitives = []\nstore_writers_unused = ["gen2.store.api.Store"]'),
    # task 1c: kills that rest on a child. Each killer below checks what only a
    # fresh interpreter runs (a command's entry point, or the router's replay
    # as seen by a process that shares nothing with the one that committed);
    # with --no-disk the child imports the unmutated tree and each is INVALID
    # (its listed killer passes). Module docstring, "Children".
    Mutation("1C-child-gate-refusal-silent", "1c-runner", "the SQLite gate command refuses without saying so on stderr",
             (SG + "GateCommandTest.test_refusing_gate_exits_nonzero_loudly",), target="gen2/store/compat.py",
             old='    if status:\n        print(f"gen2 SQLite gate REFUSED:', new='    if False:\n        print(f"gen2 SQLite gate REFUSED:', via_child=True),
    Mutation("1C-child-gate-report-dropped", "1c-runner", "the SQLite gate command drops its --report record",
             (SG + "GateCommandTest.test_passing_gate_exits_zero_and_records_the_version",), target="gen2/store/compat.py",
             old='            handle.write(f"### gen-2 SQLite compatibility gate', new='            (lambda _: None)(f"### gen-2 SQLite compatibility gate', via_child=True),
    Mutation("1C-child-importer-status-dropped", "1c-runner", "`python -m gen2.importer` exits 0 whatever the report's verdict",
             ("test_importer.CommandTest.test_python_dash_m_exits_with_the_importers_status",), target="gen2/importer/__main__.py",
             old="raise SystemExit(main())", new="main()"),
    Mutation("1C-child-router-replay-reads-committed", "1c-runner", "a replayed commit is reported as newly committed",
             ("test_router_crash.KilledProcessTest.test_a_process_killed_after_commit_has_committed_once",), target=SVC,
             old='        return {"status": "replayed", "receipt": row["receipt"]}', new='        return {"status": "committed", "receipt": row["receipt"]}', via_child=True),
    # --- task 1c: supervisor, spool, jobs, and the router's lifecycle ends -----------------------------------------
    # Store: how an invocation ended; the episode hold a reconciliation clears (test_store_supervision).
    Mutation("1C-ddl-failure-class-open", "1c", "a failure may carry any class, the agent's own word included",
             (SS + "FailureRecordTest.test_a_failure_class_is_one_of_the_structural_findings",),
             old="  failure_class TEXT CHECK (failure_class IN ('spawn_failed', 'never_started', 'exit_nonzero', 'killed', 'timeout', 'empty_output',\n"
                 "                                              'output_refused', 'output_digest_mismatch', 'result_rejected', 'no_exit_record')),\n",
             new="  failure_class TEXT,\n"),
    Mutation("1C-ddl-failure-class-on-any-state", "1c", "a failure class may sit on work that did not fail",
             (SS + "FailureRecordTest.test_a_failure_class_exists_only_on_a_failed_row",), old="  CHECK (failure_class IS NULL OR state = 'failed'),\n", new=""),
    Mutation("1C-ddl-end-evidence-on-any-state", "1c", "end evidence may sit on work that has not ended",
             (SS + "FailureRecordTest.test_end_evidence_exists_only_on_a_failed_or_cancelled_row",),
             old=",\n  CHECK (end_evidence_ref IS NULL OR state IN ('failed', 'cancelled'))\n) STRICT;", new="\n) STRICT;"),
    Mutation("1C-ddl-end-evidence-unrecorded", "1c", "end evidence need not be a recorded artifact",
             (SS + "FailureRecordTest.test_end_evidence_is_a_recorded_artifact",),
             old="  end_evidence_ref TEXT REFERENCES artifacts (content_hash),\n", new="  end_evidence_ref TEXT,\n"),
    Mutation("1C-ddl-supervisor-cannot-cancel", "1c", "the supervisor may not request a cancellation (over-restricts)",
             (SS + "CancellationRecordTest.test_the_supervisor_may_request_a_cancellation",),
             old="cancel_requested_by IN ('router', 'operator', 'supervisor')", new="cancel_requested_by IN ('router', 'operator')"),
    Mutation("1C-ddl-anyone-cancels", "1c", "a cancellation may name any requester",
             (SS + "CancellationRecordTest.test_the_supervisor_may_request_a_cancellation",),
             old="  cancel_requested_by TEXT CHECK (cancel_requested_by IN ('router', 'operator', 'supervisor')),\n", new="  cancel_requested_by TEXT,\n"),
    *(Mutation(f"1C-ddl-{key}-rewritable", "1c", f"the {what} is no longer write-once", (SS + killer,), scope="invocations_identity_immutable", old=old, new="")
      for key, what, killer, old in (
          ("cancel-request", "cancellation request", "CancellationRecordTest.test_the_cancellation_request_is_write_once",
           "\n  OR (OLD.cancel_requested_at IS NOT NULL AND (NEW.cancel_requested_at IS NOT OLD.cancel_requested_at OR NEW.cancel_requested_by IS NOT OLD.cancel_requested_by))"),
          ("descendant-confirmation", "descendant confirmation", "CancellationRecordTest.test_descendant_confirmation_is_write_once",
           "\n  OR (OLD.descendants_confirmed_at IS NOT NULL AND NEW.descendants_confirmed_at IS NOT OLD.descendants_confirmed_at)"),
          ("failure-class", "failure class", "FailureRecordTest.test_the_failure_record_is_write_once",
           "\n  OR (OLD.failure_class IS NOT NULL AND NEW.failure_class IS NOT OLD.failure_class)"),
          ("end-evidence", "end evidence", "FailureRecordTest.test_the_failure_record_is_write_once",
           "\n  OR (OLD.end_evidence_ref IS NOT NULL AND NEW.end_evidence_ref IS NOT OLD.end_evidence_ref)"))),
    Mutation("1C-ddl-reconciliation-cannot-clear", "1c", "a hold cleared by a reconciliation record fails the clearing CHECK (over-restricts)",
             (SS + "UnknownHoldTest.test_the_episode_record_clears_its_hold",), scope="holds",
             old=" OR cleared_by_reconciliation_id IS NOT NULL),", new="),"),
    Mutation("1C-ddl-hold-created-cleared-by-record", "1c", "a hold may be created already cleared by a reconciliation record",
             (SS + "UnknownHoldTest.test_a_hold_is_not_created_cleared_by_a_record",), scope="holds_created_open",
             old="\n  OR NEW.cleared_by_reconciliation_id IS NOT NULL", new=""),
    Mutation("1C-ddl-reconciliation-clears-anything", "1c", "any reconciliation record clears any hold",
             (SS + "UnknownHoldTest.test_another_episode_is_not_cleared", SS + "UnknownHoldTest.test_another_topics_hold_is_not_cleared",
              SS + "UnknownHoldTest.test_a_hold_another_authority_clears_is_not_cleared"),
             drop_trigger="holds_reconciliation_clears_its_episode"),
    Mutation("1C-ddl-reconciliation-clears-another-authoritys-hold", "1c", "a reconciliation record clears a primary or operator hold",
             (SS + "UnknownHoldTest.test_a_hold_another_authority_clears_is_not_cleared",), scope="holds_reconciliation_clears_its_episode",
             old="NEW.required_authority = 'router' AND ", new=""),
    Mutation("1C-ddl-reconciliation-clears-another-topic", "1c", "a reconciliation record clears a hold of another topic",
             (SS + "UnknownHoldTest.test_another_topics_hold_is_not_cleared",), scope="holds_reconciliation_clears_its_episode",
             old="      AND i.topic_id IS NEW.topic_id\n", new=""),
    Mutation("1C-ddl-reconciliation-clears-another-episode", "1c", "a reconciliation record clears another episode's hold",
             (SS + "UnknownHoldTest.test_another_episode_is_not_cleared",), scope="holds_reconciliation_clears_its_episode",
             old="NEW.subject_ref = 'invocation:' || r.invocation_id || '#unknown:' || r.unknown_episode",
             new="NEW.subject_ref LIKE 'invocation:' || r.invocation_id || '#unknown:%'"),
    Mutation("1C-ddl-reconciliation-clears-another-invocation", "1c", "a reconciliation record clears another invocation's hold",
             (SS + "UnknownHoldTest.test_another_invocations_hold_is_not_cleared",), scope="holds_reconciliation_clears_its_episode",
             old="NEW.subject_ref = 'invocation:' || r.invocation_id || '#unknown:' || r.unknown_episode",
             new="NEW.subject_ref LIKE 'invocation:%#unknown:' || r.unknown_episode"),
    # Schemas: the execution record and an invocation's failure record (isolated negatives, test_schema_counterfactuals).
    *(Mutation(f"1C-schema-{key}", "1c", desc, (SF + killer,), target=target, old=old, new=new)
      for key, desc, killer, target, old, new in (
          ("present-output-unhashed", "collected output need not name its hash", "test_collected_output_names_its_hash", ER,
           '"then": {"properties": {"content_hash": {"type": "string"}, "size_bytes": {"type": "integer"}}},', '"then": {},'),
          ("absent-output-hashed", "uncollected output may name a hash", "test_output_not_collected_names_no_hash", ER,
           '"else": {"properties": {"content_hash": {"type": "null"}, "size_bytes": {"type": "null"}}}', '"else": {}'),
          ("findings-open", "a finding may be any string, the agent's word included", "test_findings_are_structural_classes", ER,
           '"items": {"enum": ["spawn_failed", "never_started", "exit_nonzero", "killed", "timeout", "empty_output", "output_refused", '
           '"output_digest_mismatch", "result_rejected", "no_exit_record"]}', '"items": {"type": "string"}'),
          ("termination-reasonless", "a group termination need not record why", "test_a_group_termination_records_its_reason", ER,
           '"then": {"properties": {"termination": {"type": "object"}}}', '"then": {}'),
          ("terminated-uncounted", "terminated descendants need not be counted", "test_terminated_descendants_are_counted", ER,
           ',\n        {"if": {"properties": {"handling": {"const": "terminated"}}}, "then": {"properties": {"count": {"minimum": 1}}}}', ""),
          ("exit-code-and-signal", "an exit may carry a code and a signal", "test_an_exit_is_a_code_or_a_signal", ER,
           '"properties": {"code": {"type": "integer", "minimum": 0, "maximum": 255}, "signal": {"type": "null"}}}',
           '"properties": {"code": {"type": "integer", "minimum": 0, "maximum": 255}, "signal": {}}}'),
          ("failed-without-record", "a failed invocation need not carry its failure record", "test_a_failed_invocation_carries_its_failure_record", INV,
           '"then": {"properties": {"failure": {"type": "object"}}},', '"then": {},'),
          ("failure-record-on-running", "work that did not fail may carry a failure record", "test_only_a_failed_invocation_carries_a_failure_record", INV,
           '"else": {"properties": {"failure": {"type": "null"}}}', '"else": {}'),
          ("failure-class-open", "a failure class may be any string", "test_a_failure_class_is_a_structural_finding", INV,
           '"class": {"enum": ["spawn_failed", "never_started", "exit_nonzero", "killed", "timeout", "empty_output", "output_refused", '
           '"output_digest_mismatch", "result_rejected", "no_exit_record"]}', '"class": {"type": "string"}'))),
    # Router: the ends the supervisor records (test_router_lifecycle; the spool's read side also test_supervisor_spool).
    *(Mutation(f"1C-router-{key}", "1c", desc, tuple(LC + k for k in killers), target=target, old=old, new=new)
      for key, desc, killers, target, old, new in (
          ("failure-without-record", "a failure is recorded without its class and evidence", ("FailureTest.test_a_failure_without_its_record_is_refused",), SVC,
           '    "failed": ("failure_class", "end_evidence_ref"),', '    "failed": (),'),
          ("reached-state-recorded-again", "a state reached by reconciliation is recorded again as a new fact",
           ("UnknownTest.test_found_result_needs_the_staged_result_of_a_clean_exit",), SVC,
           '        if inv["state"] == target:\n            raise Refusal("transition_not_allowed", f"{inv[\'invocation_id\']} is already {target} (reached another way)")\n', ""),
          ("launch-after-cancel", "launch intent is recorded after a cancellation request (L-7)",
           ("CancellationTest.test_launch_after_a_cancellation_request_is_refused", "StatusAndSpoolTest.test_status_reports_the_current_launch_admission_check"), SVC,
           '        if inv["cancel_requested_at"] is not None:\n            return Refusal("cancel_requested"', '        if False:\n            return Refusal("cancel_requested"'),
          ("status-hides-launch-refusal", "status reports every invocation admitted to launch whatever its current authority (A1)",
           ("StatusAndSpoolTest.test_status_reports_the_current_launch_admission_check",), LIF,
           '        refusal = self._launch_refusal(inv, self._now())', '        refusal = None'),
          ("result-after-cancel", "a result is staged ready after a cancellation request", ("CancellationTest.test_once_requested_no_result_observation_or_commit_is_accepted",), SVC,
           '            if inv["cancel_requested_at"] is not None:  # the cancellation won: the result stays retained, uncommitted (C-10)\n', '            if False:\n'),
          ("commit-after-cancel", "a commit is accepted after a cancellation request", ("CancellationTest.test_once_requested_no_result_observation_or_commit_is_accepted",), SVC,
           '        if inv["cancel_requested_at"] is not None:  # a cancellation, once requested, admits no further effect (L-7; task 1c)\n', '        if False:\n'),
          ("observation-after-cancel", "an observation is recorded after a cancellation request", ("CancellationTest.test_once_requested_no_result_observation_or_commit_is_accepted",), SVC,
           '        if inv["cancel_requested_at"] is not None:\n            raise Refusal("invocation_state_invalid", f"cancellation was requested at {inv[\'cancel_requested_at\']}")\n', ""),
          ("end-evidence-unbound", "an end's evidence is not bound to its job, its descendants or its class",
           ("FailureTest.test_the_evidence_must_be_this_jobs_record_and_support_the_class",
            "CancellationTest.test_launched_work_is_cancelled_by_the_supervisor_with_confirmed_descendants"), SVC,
           '            self._bind_evidence(inv, evidence, failure_class=facts.get("failure_class"))\n', ""),
          ("cancelled-without-request", "launched work is recorded cancelled though no cancellation was requested",
           ("CancellationTest.test_launched_work_is_cancelled_by_the_supervisor_with_confirmed_descendants",), SVC,
           '            if inv["cancel_requested_at"] is None:\n                raise Refusal("transition_not_allowed", f"no cancellation of {inv[\'invocation_id\']} was requested")\n', ""),
          ("cancellation-keeps-capacity", "a cancellation keeps its lease once its descendants are confirmed",
           ("CancellationTest.test_launched_work_is_cancelled_by_the_supervisor_with_confirmed_descendants",), SVC,
           '        if target in ("failed", "cancelled"):\n            self._release_capacity(inv, now, target)\n', '        if target == "failed":\n            self._release_capacity(inv, now, target)\n'),
          ("unknown-without-hold", "entering outcome_unknown opens no hold (a silent park)", ("UnknownTest.test_entering_outcome_unknown_opens_an_owned_deadlined_hold",), SVC,
           '            self._open_unknown_hold(inv, facts["unknown_episode"], req["unknown_cause"], now)', "            pass"),
          ("episode-replay-current-only", "an episode entered earlier is not replayed once another has begun",
           ("UnknownTest.test_an_episode_is_reconciled_only_by_its_own_record",), SVC,
           '            if facts["unknown_episode"] <= inv["unknown_episode"]:', '            if facts["unknown_episode"] == inv["unknown_episode"]:'),
          ("episode-skips-ahead", "an entry may skip ahead of the next episode", ("UnknownTest.test_entering_outcome_unknown_opens_an_owned_deadlined_hold",), SVC,
           '            if facts["unknown_episode"] > inv["unknown_episode"] + 1:', "            if False:"),
          ("spool-media-type-unchecked", "a result reference's media type is not compared with the spool's record",
           ("StatusAndSpoolTest.test_bytes_are_read_under_the_invocations_topic_with_the_spools_media_type",), SVC,
           '            if spooled != ref["media_type"]:  # the spool\'s own record of what it staged for this topic (task 1c)', "            if False:"),
          ("evidence-of-another-invocation", "an execution record of another invocation is taken as evidence",
           ("FailureTest.test_the_evidence_must_be_this_jobs_record_and_support_the_class",), LIF,
           '        if (doc["invocation_id"], doc["topic_id"]) != (inv["invocation_id"], inv["topic_id"]):', "        if False:"),
          ("evidence-unvalidated", "an execution record is not validated", ("FailureTest.test_the_evidence_must_be_this_jobs_record_and_support_the_class",), LIF,
           '        boundary.require_schema(self._schemas, doc, "execution-record.schema.json", "evidence_refused")\n', ""),
          ("evidence-any-media-type", "evidence staged as another media type is read", ("FailureTest.test_the_evidence_must_be_this_jobs_record_and_support_the_class",), LIF,
           'raw = boundary.staged(self._spool, content_hash, topic_id=inv["topic_id"], media_type="application/json")',
           'raw = boundary.staged(self._spool, content_hash, topic_id=inv["topic_id"])'),
          ("evidence-of-another-job", "an execution record of another job is taken as evidence", ("FailureTest.test_the_evidence_must_be_this_jobs_record_and_support_the_class",), LIF,
           '        if inv["job_handle"] is None or doc["job_handle"] != inv["job_handle"]:', '        if inv["job_handle"] is None:'),
          ("capacity-on-unconfirmed-descendants", "capacity is released on unconfirmed descendant handling (L-7)",
           ("FailureTest.test_the_evidence_must_be_this_jobs_record_and_support_the_class",
            "CancellationTest.test_launched_work_is_cancelled_by_the_supervisor_with_confirmed_descendants",
            "UnknownTest.test_a_terminal_resolution_needs_confirmed_descendants_and_a_finding"), LIF,
           '        if terminal and doc["descendants"]["handling"] == "unconfirmed":', "        if False:"),
          ("class-not-a-finding", "a failure class the evidence did not find is recorded",
           ("FailureTest.test_the_evidence_must_be_this_jobs_record_and_support_the_class", "UnknownTest.test_a_terminal_resolution_needs_confirmed_descendants_and_a_finding"), LIF,
           '        if failure_class is not None and failure_class not in doc["findings"]:', "        if False:"),
          ("evidence-not-recorded", "the evidence is named but never recorded as an artifact",
           ("FailureTest.test_a_failure_records_its_class_and_evidence_and_releases_capacity",), LIF,
           '        if stored is None:\n            self._store.insert("artifacts", {"content_hash": evidence["content_hash"]',
           '        if stored is None:\n            (lambda *_: None)("artifacts", {"content_hash": evidence["content_hash"]'),
          ("delegate-releases-its-parents-lease", "a delegate's end releases its parent's lease", ("FailureTest.test_a_delegate_failure_releases_nothing",), LIF,
           '        if inv["kind"] == "delegate":\n            return\n        self._require_delegates_ended(inv)\n        lease = self._one("leases", {"lease_id": inv["lease_id"]})',
           "        lease = self._lease_of(inv)"),
          ("unknown-hold-already-due", "the episode hold is due the moment it opens", ("UnknownTest.test_entering_outcome_unknown_opens_an_owned_deadlined_hold",), LIF,
           '"deadline_at": _after(now, window)', '"deadline_at": now'),
          ("unknown-hold-unowned", "the episode hold is not owned by the station holding the job",
           ("UnknownTest.test_entering_outcome_unknown_opens_an_owned_deadlined_hold",), LIF,
           '"owner": f"supervisor:{station}"', '"owner": "router"'),
          ("unlaunched-not-cancelled", "admitted work is left admitted by its cancellation", ("CancellationTest.test_work_never_launched_is_cancelled_at_once",), LIF,
           '        if inv["state"] == "admitted":  # no launch intent, so nothing was spawned (L-2): no descendant can exist\n'
           '            changes.update(state="cancelled", state_changed_at=now, descendants_confirmed_at=now)\n', ""),
          ("staged-result-cancellable", "a staged result loses the race to a later cancellation request", ("CancellationTest.test_a_staged_result_wins_the_race",), LIF,
           '        if inv["state"] not in ("admitted", "launching", "running", "outcome_unknown"):', '        if inv["state"] in ("committed", "failed", "cancelled"):'),
          ("cancel-requester-replaced", "a second requester's cancellation replays the first's", ("CancellationTest.test_work_never_launched_is_cancelled_at_once",), LIF,
           '            if inv["cancel_requested_by"] != req["requested_by"]:', "            if False:"),
          ("supervisor-cancels-without-capability", "the supervisor cancels an invocation whose capability it does not hold",
           ("CancellationTest.test_the_supervisor_asks_under_the_invocations_capability",), LIF,
           '        if req["requested_by"] == "supervisor":\n            self._capability(req["capability_id"], req["invocation_id"])\n', ""),
          ("reconcile-any-episode", "a record of another episode is taken for the current one", ("UnknownTest.test_an_episode_is_reconciled_only_by_its_own_record",), LIF,
           '        if inv["state"] != "outcome_unknown" or inv["unknown_episode"] != req["unknown_episode"]:', '        if inv["state"] != "outcome_unknown":'),
          ("reconcile-method-unbound", "a reconciliation names a method its evidence did not use", ("UnknownTest.test_found_result_needs_the_staged_result_of_a_clean_exit",), LIF,
           '        if doc["method"] != req["method"]:', "        if False:"),
          ("found-running-unverified", "found_running is recorded without a live process of that identity",
           ("UnknownTest.test_found_running_needs_a_live_process_of_this_identity",), LIF,
           '            if doc["process"] is None or doc["exit"] is not None or {k: doc["process"][k] for k in IDENTITY} != {k: identity.get(k) for k in IDENTITY}:',
           '            if doc["process"] is None:'),
          ("found-result-other-digest", "found_result is recorded for another output than the one collected",
           ("UnknownTest.test_found_result_needs_the_staged_result_of_a_clean_exit",), LIF, ' or output["content_hash"] != req["result_payload_digest"]', ""),
          ("found-result-dirty-exit", "found_result is recorded after a failed exit", ("UnknownTest.test_found_result_needs_the_staged_result_of_a_clean_exit",), LIF,
           ' or doc["exit"] != {"code": 0, "signal": None}', ""),
          ("found-result-with-finding", "found_result is recorded despite a structural finding", ("UnknownTest.test_found_result_needs_the_staged_result_of_a_clean_exit",), LIF,
           ' or doc["findings"] or doc["exit"]', ' or doc["exit"]'),
          ("termination-ignores-cancellation", "a termination under a cancellation request ends failed, not cancelled",
           ("UnknownTest.test_termination_ends_cancelled_only_when_cancellation_was_requested",), LIF,
           '("cancelled" if inv["cancel_requested_at"] is not None else "failed")', '"failed"'),
          ("reconciliation-keeps-hold", "a reconciliation leaves its episode's hold open", ("UnknownTest.test_found_running_records_the_identity_and_clears_the_hold",), LIF,
           '            if hold["cleared_at"] is None:', "            if False:"),
          ("reconciliation-keeps-capacity", "a terminal reconciliation keeps the lease",
           ("UnknownTest.test_a_terminal_resolution_needs_confirmed_descendants_and_a_finding",), LIF,
           '        if terminal:\n            self._release_capacity(inv, now, target)', '        if False:\n            self._release_capacity(inv, now, target)'),
          ("reconciliation-conflict-replayed", "another record for a reconciled episode replays", ("UnknownTest.test_found_running_records_the_identity_and_clears_the_hold",), LIF,
           '        if row["request"] != self._reconciliation_facts(req):', "        if False:"),
          ("found-result-after-cancel", "a result found after a cancellation request is made ready",
           ("UnknownTest.test_a_result_found_after_a_cancellation_request_stays_retained",), LIF,
           '            if inv["cancel_requested_at"] is not None:\n                raise Refusal("cancel_requested", f"cancellation was requested at {inv[\'cancel_requested_at\']}; the result stays retained")\n', ""),
          ("status-without-capability", "status is read for an invocation whose capability the caller does not hold",
           ("StatusAndSpoolTest.test_status_reads_the_invocation_under_its_capability",), LIF,
           '            inv = self._capability(req["capability_id"], req["invocation_id"])\n        except Refusal as refusal:\n            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}\n        lease',
           '            inv = self._one("invocations", {"invocation_id": req["invocation_id"]})\n        except Refusal as refusal:\n            return {"status": "refused", "reason": refusal.reason, "detail": refusal.detail[:500]}\n        lease'))),
    Mutation("1C-router-staged-media-type-unchecked", "1c", "the router takes staged bytes whatever media type the spool recorded",
             ("test_supervisor_spool.RouterReadsThisSpoolTest.test_a_result_staged_as_another_media_type_is_refused",
              LC + "FailureTest.test_the_evidence_must_be_this_jobs_record_and_support_the_class"), target="gen2/router/boundary.py",
             old="    if media_type is not None and spool.media_type(content_hash, topic_id=topic_id) != media_type:", new="    if False:"),
    # The spool (C-9, C-10).
    Mutation("1C-spool-shared-across-topics", "1c", "every topic stages into and reads from one shared directory (cross-topic access)",
             (SP + "StageTest.test_bytes_are_staged_once_under_their_hash_read_only_for_one_topic", SP + "RouterReadsThisSpoolTest.test_another_topics_bytes_are_not_this_topics"),
             target=SPL, old='                    os.mkdir(topic_id, 0o700, dir_fd=root_fd)', new='                    os.mkdir("shared", 0o700, dir_fd=root_fd)',
             also=(('                return os.open(topic_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)',
                    '                return os.open("shared", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)'),)),
    *(Mutation(f"1C-spool-{key}", "1c", desc, tuple(killers), target=SPL, old=old, new=new)
      for key, desc, killers, old, new in (
          ("follows-symlinks", "an agent's symlink is followed out of its scratch directory",
           (SP + "CollectTest.test_what_is_not_the_jobs_own_regular_file_is_refused_unread", SLR + "test_output_is_never_read_through_a_symlink_or_a_hard_link"),
           "            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)\n        except FileNotFoundError:\n            return {\"status\": \"absent\", \"data\": None, \"detail\": None}",
           "            fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK, dir_fd=dir_fd)\n        except FileNotFoundError:\n            return {\"status\": \"absent\", \"data\": None, \"detail\": None}"),
          ("reads-hard-links", "a hard link to another file is read as the job's output",
           (SP + "CollectTest.test_what_is_not_the_jobs_own_regular_file_is_refused_unread", SLR + "test_output_is_never_read_through_a_symlink_or_a_hard_link"),
           "            if info.st_nlink != 1:", "            if False:"),
          ("reads-special-files", "a FIFO or directory is read as output",
           (SP + "CollectTest.test_what_is_not_the_jobs_own_regular_file_is_refused_unread",),
           '            if not stat.S_ISREG(info.st_mode):\n                return {"status": "refused", "data": None, "detail": f"{name} is not a regular file"}\n', ""),
          ("unbounded-scratch", "an output over the bound is not refused as output",
           (SP + "CollectTest.test_what_is_not_the_jobs_own_regular_file_is_refused_unread",),
           "    if len(data) > bound:\n        return {\"status\": \"refused\"", "    if False:\n        return {\"status\": \"refused\""),
          ("follows-symlinked-scratch", "a symlinked scratch directory is followed",
           (SP + "CollectTest.test_a_symlinked_scratch_directory_is_refused",),
           "        dir_fd = os.open(scratch, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)", "        dir_fd = os.open(scratch, os.O_RDONLY | os.O_DIRECTORY)"),
          ("writable-entries", "staged entries are writable", (SP + "StageTest.test_bytes_are_staged_once_under_their_hash_read_only_for_one_topic",),
           "0o444, dir_fd=dir_fd)", "0o644, dir_fd=dir_fd)"),
          ("no-quota", "the spool quota is not enforced", (SP + "StageTest.test_the_bound_and_the_quota_are_infrastructure_failures",),
           "            if used + len(data) > self.quota_bytes:", "            if False:"),
          ("no-artifact-bound", "an artifact over the bound is staged", (SP + "StageTest.test_the_bound_and_the_quota_are_infrastructure_failures",),
           "        if len(data) > self.max_artifact_bytes:\n            raise SpoolFull", "        if False:\n            raise SpoolFull"),
          ("media-conflict-ignored", "the same bytes are staged under a second media type", (SP + "StageTest.test_the_same_bytes_under_another_media_type_are_refused",),
           '            if recorded is not None and recorded["media_type"] != media_type:', "            if False:"),
          ("topic-unchecked", "a topic id is used as a path without being a topic id", (SP + "StageTest.test_a_topic_or_hash_that_is_not_one_is_refused",),
           "        if not isinstance(topic_id, str) or not TOPIC.match(topic_id):", "        if not isinstance(topic_id, str):"),
          ("hash-unchecked", "a content hash is used as a path without being one", (SP + "StageTest.test_a_topic_or_hash_that_is_not_one_is_refused",),
           "        if not isinstance(content_hash, str) or not DIGEST.match(content_hash):", "        if not isinstance(content_hash, str):"))),
    # The job layer (jobs.py in process; jobshim.py only ever runs in a child: its mutants are killed through the child tree).
    *(Mutation(f"1C-jobs-{key}", "1c", desc, tuple(killers), target=JBS, old=old, new=new, via_child=key == "start-unrecorded")
      for key, desc, killers, old, new in (
          ("pid-alone", "a live pid is taken for the launcher whatever its start time (PID adoption, L-3)", (SJ + "IdentityTest.test_a_pid_alone_is_not_the_job",),
           '        alive = stat is not None and stat[0] != "Z" and stat[2] == identity["starttime"]', '        alive = stat is not None and stat[0] != "Z"'),
          ("any-boot", "processes of another boot count as the job's group", (SJ + "IdentityTest.test_a_pid_alone_is_not_the_job",),
           '    if identity.get("boot_id") != boot_id():\n        return []', "    if False:\n        return []"),
          ("members-predate", "processes started before the launcher count as members", (SJ + "IdentityTest.test_members_are_of_the_session_and_started_no_earlier",),
           'stat[1] == identity["session"] and stat[2] >= identity["starttime"]', 'stat[1] == identity["session"]'),
          ("refused-starts-count", "a start the OS refused counts as a start that may have run",
           (SJ + "LookupTest.test_each_verdict_from_the_facts_it_names", SLR + "test_a_launcher_that_cannot_start_fails_within_the_spawn_budget"),
           'if identity is None and (spawn is None or spawn["failed"] >= spawn["attempts"]):', "if identity is None and spawn is None:"),
          ("abandon-ignores-lock", "a start is abandoned while a launcher holds the lock", (SJ + "AbandonTest.test_a_start_without_identity_is_abandoned_only_with_the_lock_free",),
           '        return self._lock_free() and self.read("identity.json") is None', '        return self.read("identity.json") is None'),
          ("abandon-ignores-identity", "a launcher that recorded its identity is abandoned once its lock is free",
           (SJ + "AbandonTest.test_a_launcher_with_an_identity_is_never_abandoned",),
           '        return self._lock_free() and self.read("identity.json") is None', "        return self._lock_free()"),
          ("start-unrecorded", "a start is not recorded before the launcher is started",
           (SCD + "test_crash_after_recording_a_start_that_never_happened",),
           '        self.write("spawn.json", record)\n        before_start()', "        before_start()"))),
    *(Mutation(f"1C-shim-{key}", "1c", desc, tuple(killers), target="gen2/supervisor/jobshim.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("ignores-abandonment", "a launcher starts the executor of an abandoned job (only a child can kill this)",
           (SJ + "AbandonTest.test_a_launcher_started_after_abandonment_starts_nothing",), '    if (job / "abandoned").exists():\n        return 0\n', ""),
          ("signal-as-code", "a signal is recorded as an exit code (only a child can kill this)",
           (SJ + "LookupTest.test_the_launcher_records_how_its_executor_ended", SLR + "test_an_exit_status_or_a_signal_fails"),
           '{"code": code if code >= 0 else None, "signal": -code if code < 0 else None}', '{"code": abs(code), "signal": None}'),
          ("no-exit-record", "the launcher records no exit (only a child can kill this)",
           (SJ + "LookupTest.test_each_verdict_from_the_facts_it_names", SLR + "test_a_clean_end_commits_the_result_with_its_execution_record"),
           '    atomic_write(job / "exit.json",', '    (lambda *_: None)(job / "exit.json",'))),
    # The supervisor's lifecycle (research pass and delegate named; the suite is one implementation run for all five kinds).
    *(Mutation(f"1C-sup-{key}", "1c", desc, tuple(p + k for k in killers for p in (SLR, SLD)), target=SPV, old=old, new=new)
      for key, desc, killers, old, new in (
          ("empty-output-misclassed", "empty output is failed under another class (L-9)", ("test_empty_output_is_a_structural_failure_whatever_the_agent_says",),
           '            findings.append("empty_output")', '            findings.append("exit_nonzero")'),
          ("refused-output-misclassed", "a refused output is failed as empty (C-9)", ("test_output_is_never_read_through_a_symlink_or_a_hard_link",),
           '            findings.append("output_refused")', '            findings.append("empty_output")'),
          ("declared-digest-unchecked", "a declared digest the bytes do not have is ignored", ("test_a_wrong_declared_digest_fails",),
           '        elif declared is not None and declared != found["ref"]["content_hash"]:', "        elif False:"),
          ("exit-code-ignored", "a non-zero exit is not a failure", ("test_an_exit_status_or_a_signal_fails",), '        elif exit_record["code"] != 0:', "        elif False:"),
          ("signal-ignored", "an end by signal is not recorded as killed", ("test_an_exit_status_or_a_signal_fails",),
           '        if exit_record["signal"] is not None:\n            findings.append("killed")', '        if False:\n            findings.append("killed")'),
          ("descendants-left-running", "descendants left after the primary exits are not ended (L-7)", ("test_a_primary_that_exits_leaving_a_descendant",),
           '        left = [pid for pid in jobs.members(identity) if pid != identity["pid"]]', "        left = []"),
          ("no-deadline", "a job past its deadline is left running", ("test_the_deadline_still_ends_work_while_the_router_is_away", "test_timeout_terminates_the_whole_group"),
           '        elif self._past(order["deadline_at"]) and (view["verdict"] == "running" or (view["verdict"] == "vanished" and view["members"])):',
           "        elif False:"),
          ("cancellation-ignored", "a requested cancellation does not end a running job", ("test_cancellation_terminates_the_group_then_releases_capacity",),
           '            if status["cancel_requested"] and view["verdict"] in ("running", "vanished"):', "            if False:"),
          ("spawn-before-launch-intent", "the launcher is started before launch intent is recorded (L-2)", ("test_pause_holds_launch_within_its_budget_then_cancels",),
           '    def _admitted(self, job, order, journal, grant, status) -> str:\n        response = self._transition',
           '    def _admitted(self, job, order, journal, grant, status) -> str:\n        self._children[job.handle] = job.spawn(list(self.launcher))\n        response = self._transition'),
          ("identity-a-bare-pid", "the recorded start fingerprint is a bare pid (L-3)", ("test_a_clean_end_commits_the_result_with_its_execution_record",),
           '"running", **{k: v for k, v in self._process(view["identity"]).items()})',
           '"running", **{**self._process(view["identity"]), "start_fingerprint": str(view["identity"]["pid"])})'),
          ("router-budget-unbounded", "an unreachable router is retried without end (L-6)", ("test_an_unreachable_router_stalls_within_budget_and_delivery_resumes_by_replay",),
           'if not self._spend(job, journal, "router") or self._past(', "if False or self._past("),
          ("stall-ignored", "a stalled job keeps calling the router (the chokepoint's stall gate, task 1c-repair-3)",
           ("test_an_unreachable_router_stalls_within_budget_and_delivery_resumes_by_replay",),
           '        if held.get("incident") or held.get("settled"):', '        if held.get("settled"):'),
          ("recovery-unbudgeted", "resuming a stalled job draws on no budget", ("test_an_unreachable_router_stalls_within_budget_and_delivery_resumes_by_replay",),
           'and not journal.get("settled") and self._spend(job, journal, "recovery"):', 'and not journal.get("settled"):'),
          ("launch-budget-unbounded", "a refused launch is retried without end", ("test_pause_holds_launch_within_its_budget_then_cancels",),
           '            if self._spend(job, journal, "launch"):', '            if True:'),
          ("spawn-budget-unbounded", "a launcher that cannot start is retried without end", ("test_a_launcher_that_cannot_start_fails_within_the_spawn_budget",),
           '            if not self._spend(job, journal, "spawn"):', "            if False:"),
          ("commit-budget-unbounded", "a refused commit is re-sent without end", ("test_a_commit_refused_while_paused_is_resent_within_its_budget",),
           '            if self._spend(job, journal, "commit"):', '            if True:'),
          ("no-start-grace", "a start found after a restart is abandoned at once", ("test_a_slow_start_found_after_a_restart_is_given_its_grace",),
           "            view = self._await_identity(job, self._policy(job).start_grace_s)", "            view = self._await_identity(job, 0.0)"),
          ("vanished-group-terminated", "a group gone without an exit is reconciled by a termination that ends nothing",
           ("test_a_group_gone_without_an_exit_is_reconciled_by_lookup",),
           '        if view["verdict"] == "vanished" and not view["members"] and not cancel:', "        if False:"),
          ("cancelled-work-not-ended", "work cancelled before any start is not ended as cancelled",
           ("test_cancellation_before_any_start_starts_nothing",),
           '            if status["cancel_requested"] or self._past(order["deadline_at"])', '            if self._past(order["deadline_at"])'),
          ("unstarted-work-past-deadline-cancelled", "work past its deadline before any start is cancelled instead of failed as never started",
           ("test_a_deadline_passed_before_any_start_starts_nothing",),
           ' or self._past(order["deadline_at"]) or (refused and refused["reason"] == "deadline_passed"):\n', ':\n'))),
    *(Mutation(f"1C-sup-{key}", "1c", desc, (SCD + killer, SCP + killer), target=SPV, old=old, new=new)
      for key, desc, killer, old, new in (
          ("no-abandon-handshake", "a start that left no identity is settled without marking the job abandoned",
           "test_crash_after_recording_a_start_that_never_happened",
           '            if view["verdict"] == "unstarted" and not job.abandon():', "            if False:"),
          ("running-job-terminated", "a running job found after a restart is terminated instead of reconciled as running",
           "test_crash_between_spawn_and_identity_record_finds_the_job_running",
           '        if view["verdict"] == "running" and not cancel and not self._past(order["deadline_at"]):', "        if False:"))),
    # Task 1c-repair. A1: recorded launch intent is not renewed authority; every actual start (a recovery, a retried start)
    # passes the router's current launch-admission check first.
    Mutation("1C-sup-start-without-admission", "1c-A1", "a recovered or retried start ignores the current launch-admission check",
             (SLR + "test_a_retried_start_is_admitted_again", SLD + "test_a_retried_start_is_admitted_again",
              *(p + k for k in ("test_recovery_starts_nothing_in_a_topic_paused_meanwhile", "test_recovery_starts_nothing_once_the_lease_has_expired",
                                "test_recovery_starts_nothing_once_the_lease_is_released") for p in (SCD, SCP)),
              SCD + "test_recovery_starts_nothing_once_the_lease_is_replaced",
              "test_supervisor_crash.DelegateUnderDiscoveryReplacementTest.test_recovery_starts_no_delegate_once_its_parents_lease_is_replaced"),
             target=SPV, old='            if refused is not None:  # recorded launch intent is not renewed authority: a recovery or a retried start is checked again',
             new='            if False:'),
    # A2: a cancellation after an uncertain spawn reconciles through the owned group, with no failure class invented.
    Mutation("1C-router-terminated-group-class-unbound", "1c-A2", "a terminated group's failure class is not bound to whether a cancellation was requested",
             (LC + "UnknownTest.test_termination_ends_cancelled_only_when_cancellation_was_requested",), target=LIF,
             old='        if resolution == "terminated_group" and ("failure_class" in req) != (target == "failed"):\n', new='        if False:\n'),
    Mutation("1C-router-cancellation-needs-a-class", "1c-A2", "a cancelled group's reconciliation must name a failure class (the supervisor's request is refused)",
             (LC + "UnknownTest.test_termination_ends_cancelled_only_when_cancellation_was_requested",
              SCD + "test_cancellation_after_an_uncertain_spawn_ends_the_live_group", SCP + "test_cancellation_after_an_uncertain_spawn_ends_the_live_group"),
             target=LIF, old='("failure_class" in req) != (target == "failed"):', new='("failure_class" not in req):'),
    Mutation("1C-sup-cancelled-exit-unconfirmed", "1c-A2", "a cancellation of work that already exited is reconciled without confirming its group",
             (SCD + "test_cancellation_after_an_uncertain_spawn_of_work_that_already_exited", SCP + "test_cancellation_after_an_uncertain_spawn_of_work_that_already_exited"),
             target=SPV, old='            if cancel and observation["termination"] is None:\n', new='            if False:\n'),
    # A4: a durable write that fails is budgeted, keeps what was observed, and ends in an owned incident or ControlFailure.
    *(Mutation(f"1C-sup-{key}", "1c-A4", desc, tuple(p + k for k in killers for p in (SBR, SBD)), target=SPV, old=old, new=new)
      for key, desc, killers, old, new in (
          ("write-retries-unbounded", "a failing durable write is retried without end, no incident",
           ("test_an_execution_record_over_the_quota_stalls_with_the_result_kept", "test_enospc_from_the_spool_stalls_with_an_incident"),
           '            if self._spend(job, journal, "write"):', '            if True:'),
          ("observation-made-again", "a termination whose record failed is observed again (its facts lost) instead of retained",
           ("test_a_termination_record_that_cannot_be_written_keeps_the_termination",),
           '        if "observation" in journal.get("observing", {}):', '        if False:'),
          ("pending-request-recomputed", "a reconciliation whose record failed is decided afresh (a different request) instead of resent",
           ("test_a_reconciliation_record_that_cannot_be_written_keeps_the_termination",),
           '        if pending is None or pending["purpose"] != purpose:\n            pending = journal["pending"]', '        if True:\n            pending = journal["pending"]'),
          ("unwritable-incident-swallowed", "a journal that cannot be written is reported as an ordinary retry, not a control failure",
           ("test_a_journal_that_cannot_be_written_is_an_out_of_band_control_failure",),
           '        except OSError as unwritable:\n            raise ControlFailure(', '        except OSError as unwritable:\n            return "write_failed"\n            raise ControlFailure('),
          ("stalled-write-retried", "a job stalled on a failed write retries it on every advance (unbounded), not only on recover()",
           ("test_enospc_from_the_spool_stalls_with_an_incident",),
           '        stalled_on_a_write = bool(journal.get("incident")) and journal["budgets"].get("write", 0) >= self._policy(job).write_attempts',
           '        stalled_on_a_write = False'),
          ("write-budget-never-refunded", "a write that made progress keeps its budget spent",
           ("test_an_execution_record_over_the_quota_stalls_with_the_result_kept",), '        journal["budgets"].pop("write", None)\n', ''))),
    # A5: an outage's budget belongs to the pending write: a read refunds nothing, recovery refills nothing, and time counts too.
    *(Mutation(f"1C-sup-{key}", "1c-A5", desc, tuple(p + k for k in killers for p in (SBR, SBD)), target=SPV, old=old, new=new)
      for key, desc, killers, old, new in (
          ("read-refunds-outage", "a successful status read refunds a failing write's router budget",
           ("test_a_write_that_keeps_failing_stalls_although_reads_succeed",),
           '        if method not in self.READS and (journal["budgets"].get("router") or journal.get("outage")):',
           '        if journal["budgets"].get("router") or journal.get("outage"):'),
          ("recovery-refills-router-budget", "recover() refills an exhausted router budget",
           ("test_a_write_that_keeps_failing_stalls_although_reads_succeed",),
           '                        journal["incident"] = None\n                        self._save(job, journal)',
           '                        journal["incident"] = None\n                        journal["budgets"]["router"] = 0\n                        self._save(job, journal)'),
          ("outage-untimed", "an outage is bounded by attempts only, however long it lasts",
           ("test_an_outage_is_also_bounded_in_time",), ' or self._past(self._after(self._policy(job).router_window_s, outage["since"]))', ''))),
    # A11: an exhausted retry budget is an owned, deadlined incident with its budget, last refusal and result reference.
    *(Mutation(f"1C-sup-{key}", "1c-A11", desc, tuple(p + k for k in killers for p in (SLR, SLD)), target=SPV, old=old, new=new)
      for key, desc, killers, old, new in (
          ("spawn-exhaustion-silent", "an exhausted spawn budget leaves no incident", ("test_a_launcher_that_cannot_start_fails_within_the_spawn_budget",),
           '                self._exhausted(job, journal, "spawn", journal.get("spawn_refused"), None)\n', ''),
          ("commit-exhaustion-silent", "an exhausted commit budget leaves no incident", ("test_a_commit_refused_while_paused_is_resent_within_its_budget",),
           '            self._exhausted(job, journal, "commit", {"reason": response["reason"], "detail": response.get("detail")}, collected["result"])\n', ''),
          ("commit-exhaustion-unreferenced", "an exhausted commit's incident names no result", ("test_a_commit_refused_while_paused_is_resent_within_its_budget",),
           '{"reason": response["reason"], "detail": response.get("detail")}, collected["result"])', '{"reason": response["reason"], "detail": response.get("detail")}, None)'),
          ("launch-exhaustion-silent", "an exhausted launch budget leaves no incident", ("test_pause_holds_launch_within_its_budget_then_cancels",),
           '            self._exhausted(job, journal, "launch", {"reason": reason}, None)\n', ''))),
    # C2 (found intermittent): a lookup asks about the launcher's lock and never takes it.
    Mutation("1C-jobs-probe-takes-the-lock", "1c-C2", "a lookup probes the launcher's lock by taking it (a launcher locking meanwhile gives up)",
             (SJ + "LockProbeTest.test_a_lookup_never_holds_the_lock_a_launcher_needs", SJ + "LookupTest.test_each_verdict_from_the_facts_it_names"),
             target=JBS, old="fcntl.fcntl(fd, fcntl.F_OFD_GETLK,", new="fcntl.fcntl(fd, fcntl.F_OFD_SETLK,"),
    # A9: the local deadline ends a live group whether or not its launcher survives, with no router response.
    Mutation("1C-sup-vanished-group-outlives-deadline", "1c-A9", "a group whose launcher vanished outlives its deadline while the router is away",
             (SLR + "test_the_deadline_ends_a_group_whose_launcher_vanished_while_the_router_is_away",
              SLD + "test_the_deadline_ends_a_group_whose_launcher_vanished_while_the_router_is_away"), target=SPV,
             old='(view["verdict"] == "running" or (view["verdict"] == "vanished" and view["members"]))', new='view["verdict"] == "running"'),
    # A10: a scratch read must be stable (the descriptor unchanged across it); C3: the two guards Astra removed by hand.
    Mutation("1C-spool-read-unchecked-after", "1c-A10", "a file changed while it is read (rewritten, linked) is staged",
             (SP + "CollectTest.test_a_file_changed_while_it_is_read_is_refused",), target=SPL,
             old="    if changed or (len(data) <= bound and len(data) != after.st_size):", new="    if False:"),
    Mutation("1C-spool-link-count-unrechecked", "1c-A10", "a link added while the file is read is not seen as a link",
             (SP + "CollectTest.test_a_file_changed_while_it_is_read_is_refused",), target=SPL,
             old='STABLE = ("st_dev", "st_ino", "st_nlink", ', new='STABLE = ("st_dev", "st_ino", '),
    Mutation("1C-spool-scratch-name-unchecked", "1c-C3", "a scratch name that is not one chosen component (a path, a dot-file) is opened",
             (SP + "CollectTest.test_the_name_is_one_component_the_supervisor_chose",), target=SPL,
             old="    if not NAME.match(name):\n        raise ValueError", new="    if False:\n        raise ValueError"),
    Mutation("1C-spool-topic-dir-followed", "1c-C3", "a symlinked topic directory is followed",
             (SP + "StageTest.test_a_symlinked_topic_directory_is_not_followed",), target=SPL,
             old="                return os.open(topic_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)",
             new="                return os.open(topic_id, os.O_RDONLY | os.O_DIRECTORY, dir_fd=root_fd)"),
    # A8: a recorded lifecycle fact replays only as the identical, complete request; rechecked under the transaction.
    Mutation("1C-router-reconciliation-compares-columns-only", "1c-A8", "a replayed reconciliation is compared on its four columns (identity and class ignored)",
             (LC + "UnknownTest.test_a_reconciled_episode_replays_only_its_identical_facts", LC + "UnknownTest.test_a_failure_class_is_part_of_the_recorded_facts"),
             target=LIF, old='        if row["request"] != self._reconciliation_facts(req):',
             new='        if (row["resolution"], row["method"], row["evidence_ref"], row["result_payload_digest"]) != (req["resolution"], req["method"], req["evidence_ref"], req.get("result_payload_digest")):'),
    Mutation("1C-router-entry-replays-any-cause", "1c-A8", "an outcome_unknown entry replays whatever cause it is sent with",
             (LC + "UnknownTest.test_an_entry_replays_only_with_its_recorded_cause", LC + "UnknownTest.test_a_conflicting_fact_recorded_meanwhile_is_a_conflict"),
             target=SVC, old='                if recorded is None or recorded.get("unknown_cause") != req["unknown_cause"]:', new='                if False:'),
    Mutation("1C-router-entry-cause-unrecorded", "1c-A8", "an outcome_unknown entry's cause is not kept with its transition",
             (LC + "UnknownTest.test_an_entry_replays_only_with_its_recorded_cause",), target=SVC,
             old='{**facts, **({"unknown_cause": req["unknown_cause"]} if target == "outcome_unknown" else {})})', new='facts)'),
    Mutation("1C-router-reconcile-no-transaction-recheck", "1c-A8", "a reconciliation recorded meanwhile is not rechecked in the transaction",
             (LC + "UnknownTest.test_a_conflicting_fact_recorded_meanwhile_is_a_conflict",), target=LIF,
             old='    def _reconcile_in_transaction(self, req: dict, identity: dict, evidence: dict, now: str) -> dict:\n        replay = self._recorded_reconciliation(req)\n        if replay is not None:\n            return replay\n',
             new='    def _reconcile_in_transaction(self, req: dict, identity: dict, evidence: dict, now: str) -> dict:\n'),
    Mutation("1C-ddl-reconciliation-request-unbound", "1c-A8", "a reconciliation's recorded request need not agree with its columns",
             (SS + "RecordedRequestTest.test_a_reconciliation_keeps_the_request_its_columns_record",), scope="invocation_reconciliations",
             old="  CHECK (json_extract(request, '$.resolution') IS resolution AND json_extract(request, '$.method') IS method\n"
                 "         AND json_extract(request, '$.evidence_ref') IS evidence_ref AND json_extract(request, '$.result_payload_digest') IS result_payload_digest),\n", new=""),
    Mutation("1C-ddl-transition-facts-any-json", "1c-A8", "a transition's facts may be any JSON value",
             (SS + "RecordedRequestTest.test_a_transition_keeps_its_facts_as_an_object_or_none",), scope="invocation_transitions",
             old="(json_valid(facts) AND json_type(facts) = 'object')", new="(json_valid(facts))"),
    # A7: an outcome_unknown episode's hold clears only through its reconciliation, in the store and in the router.
    Mutation("1C-ddl-episode-hold-cleared-by-anything", "1c-A7", "an episode hold is cleared by a decision or an operation",
             (SS + "UnknownHoldTest.test_an_episode_hold_clears_only_through_a_reconciliation",), drop_trigger="holds_episode_cleared_only_by_reconciliation"),
    Mutation("1C-ddl-episode-hold-cleared-by-operation", "1c-A7", "an episode hold is cleared by an operation (only decisions refused)",
             (SS + "UnknownHoldTest.test_an_episode_hold_clears_only_through_a_reconciliation",), scope="holds_episode_cleared_only_by_reconciliation",
             old="  AND NEW.cleared_by_reconciliation_id IS NULL\n", new="  AND NEW.cleared_by_decision_id IS NOT NULL\n"),
    Mutation("1C-router-episode-hold-cleared-by-decision", "1c-A7", "the router applies an operator hold_clearance to an episode hold (left to the store)",
             (LC + "UnknownTest.test_an_episode_hold_is_not_cleared_by_an_operator_decision",), target=SVC,
             old="            if hold is not None and is_episode_hold(hold):", new="            if False:"),
    # A6: a recorded hash is not topic authorization; each topic's own work authorizes it (artifact_topics).
    Mutation("1C-router-recorded-hash-any-topic", "1c-A6", "an embedded reference resolves to bytes recorded for any topic",
             (RC + "TopicAuthorizationTest.test_bytes_recorded_only_for_another_topic_are_not_referenced_by_hash",
              RC + "AuthorityTest.test_canonical_bytes_recorded_only_for_another_topic_are_not_this_topics",
              RC + "TopicAuthorizationTest.test_bytes_another_topic_records_meanwhile_do_not_become_this_topics",
              "test_supervisor_spool.RouterReadsThisSpoolTest.test_another_topics_recorded_bytes_are_not_this_topics"), target=SVC,
             old='            return self._recorded_for(content_hash, inv["topic_id"])', new='            return self._one("artifacts", {"content_hash": content_hash})'),
    Mutation("1C-router-recorded-for-unscoped", "1c-A6", "the recorded-for-this-topic lookup does not look at the topic",
             (RC + "TopicAuthorizationTest.test_bytes_recorded_only_for_another_topic_are_not_referenced_by_hash",
              RC + "AuthorityTest.test_canonical_bytes_recorded_only_for_another_topic_are_not_this_topics"), target=SVC,
             old='        if self._one("artifact_topics", {"content_hash": content_hash, "topic_id": topic_id}) is None:\n            return None\n', new=''),
    Mutation("1C-router-staging-authorizes-nothing", "1c-A6", "bytes a topic staged with its commit are not recorded as that topic's",
             (RC + "TopicAuthorizationTest.test_bytes_recorded_for_this_topic_are_referenced_by_hash",
              RC + "TopicAuthorizationTest.test_the_same_bytes_staged_by_this_topic_are_its_own"), target=SVC,
             old="            self._authorize_artifact(content_hash, inv, now)  # staged in this topic's spool with this commit", new="            pass  #"),
    Mutation("1C-router-dedup-authorizes-only-the-first", "1c-A6", "a second topic staging recorded bytes is not authorized for them (dedup over-restricts)",
             (RC + "TopicAuthorizationTest.test_the_same_bytes_staged_by_this_topic_are_its_own",), target=SVC,
             old="            self._authorize_artifact(content_hash, inv, now)  # staged in this topic's spool with this commit",
             new="                self._authorize_artifact(content_hash, inv, now)  # staged in this topic's spool with this commit"),
    Mutation("1C-router-evidence-authorizes-nothing", "1c-A6", "evidence staged in the invocation's topic is not recorded as that topic's",
             (LC + "FailureTest.test_a_failure_records_its_class_and_evidence_and_releases_capacity",), target=LIF,
             old='        self._authorize_artifact(evidence["content_hash"], inv, now)', new='        pass'),
    Mutation("1C-ddl-artifact-topic-by-anyone", "1c-A6", "any invocation authorizes an artifact for any topic",
             (SS + "ArtifactTopicTest.test_a_topic_is_authorized_only_by_its_own_work",), drop_trigger="artifact_topics_by_the_topics_own_work"),
    # A3: a parent's lease is its delegates' too; it is released only once every delegate has ended.
    Mutation("1C-router-parent-release-ignores-delegates", "1c-A3", "a parent's failure, cancellation or terminal reconciliation releases the lease a live delegate runs under",
             (LC + "FailureTest.test_a_parents_lease_is_not_released_while_a_delegate_is_live",
              LC + "FailureTest.test_a_parents_cancellation_or_reconciliation_waits_for_its_delegates"), target=LIF,
             old='        self._require_delegates_ended(inv)\n        lease = self._one("leases", {"lease_id": inv["lease_id"]})',
             new='        lease = self._one("leases", {"lease_id": inv["lease_id"]})'),
    Mutation("1C-router-final-commit-ignores-delegates", "1c-A3", "a parent's final commit releases the lease a live delegate runs under",
             (LC + "FailureTest.test_a_parents_lease_is_not_released_while_a_delegate_is_live",), target=SVC,
             old='            if inv["kind"] != "delegate":  # the lease a final outcome releases is its delegates\' too (L-7, L-8; task 1c-repair A3)\n',
             new='            if False:\n'),
    Mutation("1C-router-ended-delegate-counts-live", "1c-A3", "a failed or cancelled delegate still holds its parent's lease (over-restricts)",
             (LC + "FailureTest.test_a_parents_lease_is_not_released_while_a_delegate_is_live",
              LC + "FailureTest.test_a_parents_cancellation_or_reconciliation_waits_for_its_delegates"), target=LIF,
             old='if d["state"] not in ("committed", "failed", "cancelled"))', new='if d["state"] != "committed")'),
    *(Mutation(f"1C-sup-{key}", "1c-A3", desc, tuple(p + k for k in killers for p in (SDR, SDD)), target=SPV, old=old, new=new)
      for key, desc, killers, old, new in (
          ("parent-commits-over-delegates", "a parent's final commit is sent while its delegate still runs",
           ("test_a_parent_that_completes", "test_a_parent_whose_supervisor_restarts"),
           '        self._settle_delegates(order)\n        response = self._call(job, journal, "commit_outcome", envelope)',
           '        response = self._call(job, journal, "commit_outcome", envelope)'),
          ("parent-ends-over-delegates", "a parent's failure or cancellation is recorded while its delegate still runs",
           ("test_a_parent_that_fails", "test_a_parent_that_is_cancelled"),
           '        if status["cancel_requested"] or observation["findings"]:\n            self._settle_delegates(order)\n', ''),
          ("parent-reconciles-over-delegates", "a parent's terminal reconciliation is sent while its delegate still runs",
           ("test_a_parent_reconciled_after_its_launcher_vanished",),
           '        if (kept or {"resolution": resolution})["resolution"] in ("confirmed_failed", "terminated_group"):\n            self._settle_delegates(order)\n', ''),
          ("parent-unlaunched-end-over-delegates", "a parent that never started ends while its delegate still runs",
           ("test_a_parent_that_never_started",),
           '        self._settle_delegates(order)\n        pending = self._pending(job, order, journal, f"end:{to_state}"',
           '        pending = self._pending(job, order, journal, f"end:{to_state}"'),
          ("delegates-not-cancelled", "a parent's end waits on its delegates without asking them to end",
           ("test_a_parent_that_completes", "test_a_parent_that_fails"),
           '                    if status["state"] not in (*TERMINAL, "result_ready") and status["cancel_requested"] is None:\n                        response = self._call(delegate',
           '                    if False:\n                        response = self._call(delegate'))),
    # A5-R (1c-repair-2): a delegate stalled on an incident passes its own stall gate when its parent ends it — no control call
    # until recover(), its incident kept as raised — and is still advanced, so its deadline is still observed locally.
    *(Mutation(f"1C-sup-{key}", "1c-A5R", desc, tuple(p + k for k in killers for p in (SDR, SDD)), target=SPV, old=old, new=new)
      for key, desc, killers, old, new in (
          ("parent-bypasses-stalled-delegate", "a parent's end makes a stalled delegate's control calls (its spent budget bypassed, its incident renewed; "
           "the chokepoint's stall gate, task 1c-repair-3)",
           ("test_a_delegate_stalled_on_its_status_read_holds_its_parent_without_calls",
            "test_a_delegate_stalled_on_its_cancellation_holds_its_parent_without_calls"),
           '        if held.get("incident") or held.get("settled"):', '        if held.get("settled"):'),
          ("stalled-delegate-unobserved", "a parent waits on a stalled delegate without advancing it (its deadline not observed)",
           ("test_a_stalled_delegate_is_still_ended_at_its_deadline",),
           '                if self.advance(dorder["invocation_id"]) not in (*TERMINAL, "not_admitted"):',
           '                if djournal.get("incident") or self.advance(dorder["invocation_id"]) not in (*TERMINAL, "not_admitted"):'))),
    # 1c-repair-2 (L-6, RG-3): a lifecycle write the router refuses is re-sent within the refusal budget, a conflict stops at
    # once, and exhaustion stalls the job with an owned, deadlined incident; every refusal site draws on that budget.
    *(Mutation(f"1C-sup-{key}", "1c-L6", desc, tuple(p + k for k in killers for p in prefixes), target=SPV, old=old, new=new)
      for key, desc, killers, prefixes, old, new in (
          ("refusal-unbudgeted", "a refused lifecycle write is re-sent on every advance, never stalling",
           ("test_a_refused_end_is_resent_within_its_budget_then_stalls",), (SBR, SBD),
           '        if final or not self._spend(job, journal, "refusal"):', '        if final:'),
          ("final-refusal-retried", "a refusal no retry can change (a conflict) spends the budget instead of stalling at once",
           ("test_a_refusal_no_retry_can_change_stalls_at_once",), (SBR, SBD),
           '        final = refusal["reason"] in FINAL_REFUSALS', '        final = False'),
          ("refusal-never-refunded", "a refused write that is then accepted keeps its refusal budget spent",
           ("test_a_refused_end_accepted_within_its_budget_refunds_it",), (SBR, SBD),
           '            journal["budgets"].pop("refusal", None)\n', ''),
          ("end-refusal-unbudgeted", "a refused end (failed or cancelled) is re-sent on every advance",
           ("test_a_refused_end_is_resent_within_its_budget_then_stalls",), (SBR, SBD),
           '            self._refused(job, journal, "end", response)', '            raise Waiting(f"end_refused:{response.get(\'reason\')}")'),
          ("result-refusal-unbudgeted", "a refused result_ready is re-sent on every advance",
           ("test_a_refused_result_is_budgeted_too",), (SBR, SBD),
           '            self._refused(job, journal, "result_ready", response)', '            raise Waiting(f"result_ready_refused:{response.get(\'reason\')}")'),
          ("unknown-entry-refusal-unbudgeted", "a refused outcome_unknown entry is re-sent on every advance",
           ("test_a_refused_outcome_unknown_entry_is_budgeted_too",), (SBR, SBD),
           '            self._refused(job, journal, "unknown", response)', '            raise Waiting(f"unknown_refused:{response.get(\'reason\')}")'),
          ("sent-refusal-unbudgeted", "a refused pending end or reconciliation is re-sent on every advance",
           ("test_a_refused_reconciliation_is_budgeted_too",), (SBR, SBD),
           '            self._refused(job, journal, write, response)', '            raise Waiting(f"{write}_refused:{response.get(\'reason\')}")'),
          ("self-cancel-refusal-unbudgeted", "the supervisor's refused cancellation of unlaunched work is re-sent on every advance",
           ("test_a_refused_cancellation_of_unlaunched_work_is_budgeted_too",), (SBR, SBD),
           '            self._refused(job, journal, "cancel", response)', '            raise Waiting("launch_refused")'),
          ("delegate-cancel-refusal-ignored", "a delegate's refused cancellation is asked again on every parent advance",
           ("test_a_refused_delegate_cancellation_is_budgeted",), (SDR, SDD),
           '                        if response["status"] not in ("cancelled", "recorded", "replayed"):\n                            self._refused(delegate',
           '                        if False:\n                            self._refused(delegate'),
          # an outcome_unknown episode that cannot be reconciled yet: attempts and time, per episode; its hold stays (L-4)
          ("unknown-unbudgeted", "an unresolved outcome_unknown episode is looked at again on every advance, never stalling",
           ("test_an_unresolved_unknown_episode_stalls_within_its_budget_and_keeps_its_hold",), (SBR, SBD),
           '        if not self._spend(job, journal, "unknown") or self._past(self._after(self._policy(job).unknown_window_s, tried["since"])):',
           '        if False:'),
          ("unknown-untimed", "an unresolved episode is bounded by attempts only, however long it lasts",
           ("test_an_unresolved_unknown_episode_is_also_bounded_in_time",), (SBR, SBD),
           ' or self._past(self._after(self._policy(job).unknown_window_s, tried["since"]))', ''),
          ("unknown-never-refunded", "a reconciled episode keeps its unknown budget spent",
           ("test_an_unknown_episode_reconciled_within_its_budget_refunds_it",), (SBR, SBD),
           '        if journal.pop("unresolved", None) is not None:', '        if False:'))),
    # 1c-repair-3 (L-6, RG-3; Astra 1c re-review 2): every router call goes through one chokepoint, which makes none for a job
    # stalled on an open incident, or settled, as that job's own durable journal says, whoever calls; an open incident is
    # write-once. The stall gate's removal is also 1C-sup-stall-ignored (the job's own advance) and
    # 1C-sup-parent-bypasses-stalled-delegate (its parent ending it): the same edit, checked here against the other callers.
    *(Mutation(f"1C-sup-{key}", "1c-L6R", desc, tuple(p + k for k in killers for p in prefixes), target=SPV, old=old, new=new)
      for key, desc, killers, prefixes, old, new in (
          ("stalled-parent-claimed-for-its-delegate", "a stalled job's calls are made for other callers: its delegate's grant retries its claim",
           ("test_a_delegate_does_not_retry_its_stalled_parents_claim", "test_no_caller_makes_a_stalled_parents_control_call",
            "test_no_caller_makes_a_stalled_delegates_control_call"), (SDR, SDD),
           '        if held.get("incident") or held.get("settled"):', '        if held.get("settled"):'),
          ("settled-job-claimed-again", "a job settled not_admitted is claimed again for its delegate",
           ("test_a_parent_not_admitted_is_never_claimed_again_for_its_delegate",), (SDR, SDD),
           '        if held.get("incident") or held.get("settled"):', '        if held.get("incident"):'),
          ("chokepoint-trusts-the-callers-copy", "the chokepoint reads the caller's job and journal copy, not the durable journal of the job called for",
           ("test_no_caller_makes_a_stalled_parents_control_call", "test_no_caller_makes_a_stalled_delegates_control_call"), (SDR, SDD),
           '        owner = self.job(request["invocation_id"])\n        held = owner.read("journal.json") or {}\n', '        owner, held = job, journal\n'),
          ("unadmitted-parent-strands-its-delegate", "a delegate whose parent ended not_admitted waits on it for ever",
           ("test_a_parent_not_admitted_is_never_claimed_again_for_its_delegate",), (SDR, SDD),
           '                if held.settled is None:', '                if True:'),
          ("incident-renewed", "the incident writer replaces an open incident (a new kind, since and deadline)",
           ("test_no_caller_makes_a_stalled_parents_control_call", "test_no_caller_makes_a_stalled_delegates_control_call"), (SDR, SDD),
           '        if raised:\n            journal[key] = raised\n            return\n', ''),
          ("incident-writer-trusts-the-callers-copy", "the incident writer reads the caller's journal copy, not the durable journal",
           ("test_no_caller_makes_a_stalled_parents_control_call", "test_no_caller_makes_a_stalled_delegates_control_call"), (SDR, SDD),
           '        raised = (job.read("journal.json") or {}).get(key)', '        raised = journal.get(key)'),
          ("stalled-write-retried-under-another-incident", "a failed write is retried on every advance while the job is stalled on another incident",
           ("test_a_write_failing_while_stalled_is_bounded_and_keeps_the_incident",), (SBR, SBD),
           'bool(journal.get("incident")) and journal["budgets"].get("write", 0) >= self._policy(job).write_attempts',
           '(journal.get("incident") or {}).get("kind") == "durable_write_failed"'))),
    # 1c-repair-4 (L-6, RG-3; Astra 1c re-review 3, BLOCK 1): every read-modify-write of a job's journal is one caller's — a
    # per-job lock across the threads and processes of a host, a delegate's parent's taken first — and a write resting on
    # a copy older than the durable journal is refused (the backstop). The locks, their order, and the snapshot under them.
    *(Mutation(f"1C-sup-{key}", "1c-L6S", desc, tuple(p + k for k in killers for p in prefixes), target=SPV, old=old, new=new)
      for key, desc, killers, prefixes, old, new in (
          ("advance-unlocked", "an advance holds no lock: another advance reads the job's journal meanwhile and writes over it",
           ("test_overlapping_advances_on_one_supervisor_paused_in_the_chokepoint", "test_overlapping_advances_on_two_supervisors_paused_in_the_chokepoint",
            "test_overlapping_advances_on_one_supervisor_paused_after_the_snapshot", "test_overlapping_advances_on_two_supervisors_paused_after_the_snapshot"),
           (SSR, SSD),
           '            with self._exclusive(order):\n                journal = self._journal(job)  # read under the lock',
           '            with contextlib.nullcontext():\n                journal = self._journal(job)  # read under the lock'),
          ("journal-read-before-the-lock", "an advance reads its journal before it takes the lock: its writes rest on a copy another advance may change",
           ("test_overlapping_advances_on_one_supervisor_paused_after_the_snapshot", "test_overlapping_advances_on_two_supervisors_paused_after_the_snapshot"),
           (SSR, SSD),
           '            with self._exclusive(order):\n                journal = self._journal(job)  # read under the lock: every write of this advance rests on it (_save)\n',
           '            journal = self._journal(job)  # read under the lock: every write of this advance rests on it (_save)\n            with self._exclusive(order):\n'),
          ("recover-unlocked", "recover() resumes a job holding no lock: another recovery's attempt is lost, and a busy job's budget spent",
           ("test_overlapping_recoveries_are_two_recovery_attempts", "test_waiting_for_the_lock_is_bounded_and_spends_nothing"), (SSR, SSD),
           '                with self._exclusive(order):\n                    journal = self._journal(job)  # read under the lock, as advance() reads it',
           '                with contextlib.nullcontext():\n                    journal = self._journal(job)  # read under the lock, as advance() reads it'),
          ("recover-reads-before-the-lock", "recover() reads the journal it resumes from before it takes the lock",
           ("test_overlapping_recoveries_are_two_recovery_attempts",), (SSR, SSD),
           '                with self._exclusive(order):\n                    journal = self._journal(job)  # read under the lock, as advance() reads it\n',
           '                journal = self._journal(job)  # read under the lock, as advance() reads it\n                with self._exclusive(order):\n'),
          ("delegate-locks-only-itself", "a delegate's advance takes its own lock only, then writes its parent's journal (its grant) unlocked",
           ("test_a_parent_ending_first_holds_its_delegate_off_then_cancels_it", "test_a_delegate_claiming_first_holds_its_parent_off_then_is_ended_by_it"),
           (SSR, SSD),
           '        while parent is not None and parent not in seen:', '        while False:'),
          ("reap-walks-the-live-dict", "reaping walks the live table of launchers another thread's advance may add to",
           ("test_reaping_while_another_advance_starts_a_launcher",), (SSB,),
           '        for popen in list(self._children.values()):', '        for popen in self._children.values():'))),
    Mutation("1C-sup-stale-journal-saved", "1c-L6S", "a journal write resting on an older copy replaces the newer journal (the backstop gone)",
             (SSR + "test_a_caller_not_taking_the_lock_cannot_save_over_the_incident", SSD + "test_a_caller_not_taking_the_lock_cannot_save_over_the_incident",
              SSB + "test_a_write_resting_on_an_older_copy_of_the_journal_is_refused"), target=SPV,
             old='        if durable != revision:\n            raise StaleJournal(', new='        if False:\n            raise StaleJournal('),
    *(Mutation(f"1C-jobs-{key}", "1c-L6S", desc, tuple(p + k for k in killers for p in prefixes), target=JBS, old=old, new=new)
      for key, desc, killers, prefixes, old, new in (
          ("lock-not-taken", "the journal lock is asked about, never taken: no caller excludes another",
           ("test_overlapping_advances_on_one_supervisor_paused_in_the_chokepoint", "test_overlapping_advances_on_two_supervisors_paused_in_the_chokepoint"),
           (SSR, SSD),
           '                    fcntl.fcntl(fd, fcntl.F_OFD_SETLK, struct.pack(FLOCK, fcntl.F_WRLCK, os.SEEK_SET, 0, 0, 0))\n                    break',
           '                    fcntl.fcntl(fd, fcntl.F_OFD_GETLK, struct.pack(FLOCK, fcntl.F_WRLCK, os.SEEK_SET, 0, 0, 0))\n                    break'),
          ("lock-wait-unbounded", "a caller waits for a held journal lock for ever",
           ("test_waiting_for_the_lock_is_bounded_and_spends_nothing",), (SSR, SSD),
           '                if time.monotonic() >= deadline:\n                    raise Taken(self.handle)\n', ''),
          ("lock-not-nested", "a caller holding a job's lock waits on itself when it takes it again (a parent ending its delegates, recover())",
           ("test_a_parent_that_completes",), (SDR, SDD),
           '            if key in held:\n                yield\n                return\n', ''))),
    # --- task 1d: registries, config bundles, reservations, versions, G-1 impact, re-queues -------------------
    # The store's layer (DDL), per guard and per binding dimension, each killed by its isolated negative in
    # test_store_registries.py (the history sweeps take the delete guards, below with the other tables').
    *(Mutation(f"1D-ddl-{key}", "1d", desc, tuple(SR + k for k in killers), scope=scope, old=old, new=new)
      for key, desc, killers, scope, old, new in (
          ("bundle-json-version", "a bundle row's version may differ from its document's", ("ConfigBundleTest.test_a_bundle_row_is_its_document",), "config_bundles",
           " AND json_extract(document, '$.version') IS version)", ")"),
          ("bundle-json-kind", "a bundle row's document may be of another version of the format", ("ConfigBundleTest.test_a_bundle_row_is_its_document",), "config_bundles",
           "json_extract(document, '$.bundle_version') IS 'config-bundle/1' AND ", ""),
          ("bundle-recorded-superseded", "a bundle may be recorded superseded", ("ConfigBundleTest.test_a_bundle_is_recorded_active_newest_and_alone",),
           "config_bundles_recorded_active_and_newest", "WHEN NEW.status IS NOT 'active' OR EXISTS", "WHEN EXISTS"),
          ("bundle-recorded-older", "a bundle may be recorded with a version not above every recorded one", ("ConfigBundleTest.test_a_bundle_is_recorded_active_newest_and_alone",),
           "config_bundles_recorded_active_and_newest", " OR EXISTS (SELECT 1 FROM config_bundles b WHERE b.version >= NEW.version)", ""),
          ("bundle-document-rewritable", "a bundle's document may change", ("ConfigBundleTest.test_a_bundle_never_changes_and_is_never_reactivated",),
           "config_bundles_immutable", " OR NEW.document IS NOT OLD.document", ""),
          ("bundle-version-rewritable", "a bundle's version may change", ("ConfigBundleTest.test_a_bundle_never_changes_and_is_never_reactivated",),
           "config_bundles_immutable", " OR NEW.version IS NOT OLD.version", ""),
          ("bundle-hash-rewritable", "a bundle's identity may change", ("ConfigBundleTest.test_a_bundle_never_changes_and_is_never_reactivated",),
           "config_bundles_immutable", "WHEN NEW.bundle_hash IS NOT OLD.bundle_hash OR ", "WHEN "),
          ("bundle-activation-rewritable", "a bundle's activation time may change", ("ConfigBundleTest.test_a_bundle_never_changes_and_is_never_reactivated",),
           "config_bundles_immutable", "\n  OR NEW.activated_at IS NOT OLD.activated_at OR", "\n  OR"),
          ("bundle-reactivated", "a superseded bundle may be reactivated", ("ConfigBundleTest.test_a_bundle_never_changes_and_is_never_reactivated",),
           "config_bundles_immutable", " OR (OLD.status = 'superseded' AND NEW.status IS NOT 'superseded')", ""),
          ("invocation-pins-any-bundle", "an invocation may pin an unrecorded bundle", ("ConfigBundleTest.test_an_invocation_pins_a_recorded_bundle",), "invocations",
           "  config_bundle_hash TEXT NOT NULL REFERENCES config_bundles (bundle_hash),", "  config_bundle_hash TEXT NOT NULL,"),
          ("question-row-id", "a question row's id may differ from its document's", ("QuestionRegistryTest.test_a_question_is_the_entry_of_its_bundle",), "questions",
           "CHECK (json_extract(document, '$.question_id') IS question_id AND ", "CHECK ("),
          ("question-row-version", "a question row's version may differ from its document's", ("QuestionRegistryTest.test_a_question_is_the_entry_of_its_bundle",), "questions",
           " AND json_extract(document, '$.version') IS version\n", "\n"),
          ("question-row-hash", "a question row's hash may differ from its document's", ("QuestionRegistryTest.test_a_question_is_the_entry_of_its_bundle",), "questions",
           "\n     AND json_extract(document, '$.content_hash') IS content_hash)", ")"),
          ("question-version-rewordable", "a question version may be recorded twice, with another content", ("QuestionRegistryTest.test_a_version_has_one_content_forever",),
           "questions", "  PRIMARY KEY (question_id, version),\n", ""),
          ("spec-question-id", "a spec may pin an unregistered question id", ("QuestionRegistryTest.test_a_spec_pins_a_registered_question_under_its_hash",),
           "decision_specs_question_registered", "  WHERE q.question_id IS json_extract(NEW.document, '$.question.question_id')\n    AND ", "  WHERE "),
          ("spec-question-version", "a spec may pin an unregistered question version", ("QuestionRegistryTest.test_a_spec_pins_a_registered_question_under_its_hash",),
           "decision_specs_question_registered", "    AND q.version IS json_extract(NEW.document, '$.question.version')\n", ""),
          ("spec-question-hash", "a spec may pin an altered question (another hash)", ("QuestionRegistryTest.test_a_spec_pins_a_registered_question_under_its_hash",),
           "decision_specs_question_registered", "\n    AND q.content_hash IS json_extract(NEW.document, '$.question.content_hash'))", ")"),
          ("qualification-revocation-partial", "a revocation may be recorded without its actor or reason", ("QualificationTest.test_revocation_is_recorded_once_and_is_final",),
           "qualifications", ",\n  CHECK ((revoked_by IS NULL) = (revoked_at IS NULL) AND (revoked_at IS NULL) = (revoke_reason IS NULL))", ""),
          ("qualification-born-revoked", "a qualification may be recorded revoked", ("QualificationTest.test_a_record_is_created_live_for_its_specs_provider_and_class",),
           "qualifications_created_live_for_their_spec", "WHEN NEW.revoked_at IS NOT NULL OR NOT EXISTS", "WHEN NOT EXISTS"),
          ("qualification-any-provider", "a qualification may name another provider than its spec's", ("QualificationTest.test_a_record_is_created_live_for_its_specs_provider_and_class",),
           "qualifications_created_live_for_their_spec", " AND s.provider = NEW.provider", ""),
          ("qualification-any-class", "a qualification may name another class than its spec's", ("QualificationTest.test_a_record_is_created_live_for_its_specs_provider_and_class",),
           "qualifications_created_live_for_their_spec", " AND s.decision_class = NEW.decision_class", ""),
          ("qualification-revoked-twice", "a revocation may be rewritten", ("QualificationTest.test_revocation_is_recorded_once_and_is_final",),
           "qualifications_revoked_once", "WHEN OLD.revoked_at IS NOT NULL\n  OR ", "WHEN "),
          ("qualification-spec-rewritable", "a qualification's spec may change", ("QualificationTest.test_revocation_is_recorded_once_and_is_final",),
           "qualifications_revoked_once", "  OR NEW.spec_hash IS NOT OLD.spec_hash OR", "  OR"),
          ("qualification-evaluation-rewritable", "a qualification's evaluation may change", ("QualificationTest.test_revocation_is_recorded_once_and_is_final",),
           "qualifications_revoked_once", " OR NEW.evaluation_ref IS NOT OLD.evaluation_ref", ""),
          ("qualified-by-revoked", "a revoked qualification still qualifies", ("QualificationTest.test_qualified_authority_rests_on_a_live_record_of_exactly_its_spec",),
           "decision_receipts_qualification_live", " AND q.revoked_at IS NULL)", ")"),
          ("qualified-by-another-spec", "another spec's qualification qualifies", ("QualificationTest.test_qualified_authority_rests_on_a_live_record_of_exactly_its_spec",),
           "decision_receipts_qualification_live", " AND q.spec_hash = NEW.spec_hash", ""),
          ("reservation-threshold-any-purpose", "a threshold may be recorded without auto-promotion, and auto-promotion without one", ("ReservationTest.test_a_threshold_is_auto_promotions_alone",),
           "reservations", "  CHECK ((purpose = 'auto_promotion') = (min_band IS NOT NULL)),\n", ""),
          ("reservation-closed-without-reason", "a reservation may close without a reason", ("ReservationTest.test_one_open_reservation_per_purpose_closed_once",),
           "reservations", ",\n  CHECK ((closed_at IS NULL) = (close_reason IS NULL))", ""),
          ("reservation-open-twice", "two reservations of one purpose may be open", ("ReservationTest.test_one_open_reservation_per_purpose_closed_once",), None,
           "CREATE UNIQUE INDEX reservations_one_open_per_purpose ON reservations (topic_id, purpose) WHERE closed_at IS NULL;\n", ""),
          ("reservation-born-closed", "a reservation may be recorded closed", ("ReservationTest.test_a_reservation_is_opened_under_the_approved_revision_as_its_bundle_sizes_it",),
           "reservations_opened_under_the_approved_revision", "WHEN NEW.closed_at IS NOT NULL\n  OR NOT EXISTS (SELECT 1 FROM contract_revisions", "WHEN NOT EXISTS (SELECT 1 FROM contract_revisions"),
          ("reservation-under-a-draft", "a reservation may be opened under an unapproved revision", ("ReservationTest.test_a_reservation_is_opened_under_the_approved_revision_as_its_bundle_sizes_it",),
           "reservations_opened_under_the_approved_revision", " AND c.status = 'approved')", ")"),
          ("reservation-any-size", "a reservation's units may differ from its bundle's", ("ReservationTest.test_a_reservation_is_opened_under_the_approved_revision_as_its_bundle_sizes_it",),
           "reservations_opened_under_the_approved_revision", "      AND json_extract(b.document, '$.policy.router.reservations.' || NEW.purpose || '.units') IS NEW.units\n", ""),
          ("reservation-any-threshold", "a reservation's threshold may differ from its bundle's", ("ReservationTest.test_a_reservation_is_opened_under_the_approved_revision_as_its_bundle_sizes_it",),
           "reservations_opened_under_the_approved_revision", "\n      AND json_extract(b.document, '$.policy.router.reservations.' || NEW.purpose || '.min_band') IS NEW.min_band)", ")"),
          ("reservation-reclosed", "a closed reservation may change", ("ReservationTest.test_one_open_reservation_per_purpose_closed_once",),
           "reservations_close_once", "WHEN OLD.closed_at IS NOT NULL\n  OR ", "WHEN "),
          ("reservation-resized", "a reservation's units may change", ("ReservationTest.test_one_open_reservation_per_purpose_closed_once",),
           "reservations_close_once", " OR NEW.units IS NOT OLD.units", ""),
          ("draw-closed", "a closed reservation may be drawn on", ("ReservationTest.test_each_binding_of_a_draw_refuses_alone",),
           "reservation_draws_within_and_revision_bound", " AND r.closed_at IS NULL", ""),
          ("draw-superseded-revision", "a reservation may be drawn on after its revision is superseded", ("ReservationTest.test_a_draw_under_a_superseded_or_another_revision_is_refused",),
           "reservation_draws_within_and_revision_bound", " AND c.status = 'approved'\n", "\n"),
          ("draw-other-topic", "another topic's work may draw on a reservation", ("ReservationTest.test_each_binding_of_a_draw_refuses_alone",),
           "reservation_draws_within_and_revision_bound", "    AND i.topic_id = r.topic_id AND", "    AND"),
          ("draw-by-a-delegate", "a delegate may draw on its own", ("ReservationTest.test_each_binding_of_a_draw_refuses_alone",),
           "reservation_draws_within_and_revision_bound", " AND i.kind != 'delegate'", ""),
          ("draw-other-revision", "work admitted under another revision may draw on a reservation", ("ReservationTest.test_a_draw_under_a_superseded_or_another_revision_is_refused",),
           "reservation_draws_within_and_revision_bound", " AND i.contract_revision IS r.contract_revision\n", "\n"),
          ("draw-beyond-units", "a reservation may be drawn on beyond its units", ("ReservationTest.test_a_draw_is_within_its_reservation_and_bound_to_its_revision",),
           "reservation_draws_within_and_revision_bound", "    AND (SELECT count(*) FROM reservation_draws d WHERE d.reservation_id = r.reservation_id) < r.units\n", ""),
          ("draw-facet-any-purpose", "an auto-promotion draw needs no facet (an exploration draw naming one is refused by the threshold, which exploration has none of)",
           ("ReservationTest.test_an_auto_promotion_draw_is_inside_a_facet_rated_at_the_threshold",),
           "reservation_draws_within_and_revision_bound", "    AND (r.purpose = 'auto_promotion') = (NEW.facet_id IS NOT NULL)\n", ""),
          ("draw-below-threshold", "an auto-promotion draw may name a facet rated below the threshold", ("ReservationTest.test_a_facet_below_the_threshold_is_refused",),
           "reservation_draws_within_and_revision_bound", "             >= CASE r.min_band WHEN 'critical' THEN 3 WHEN 'important' THEN 2 WHEN 'limited' THEN 1 END)))",
           "             >= 0)))"),
          ("retry-born-claimed", "a re-queue may be recorded already claimed", ("RetryTest.test_a_requeue_is_of_ended_non_delegate_work_one_attempt_on",),
           "retries_of_ended_work_counted", "WHEN NEW.retry_invocation_id IS NOT NULL\n  OR NOT EXISTS", "WHEN NOT EXISTS"),
          ("retry-other-topic", "a re-queue may name another topic than its work's", ("RetryTest.test_a_requeue_is_of_ended_non_delegate_work_one_attempt_on",),
           "retries_of_ended_work_counted", " AND i.topic_id = NEW.topic_id\n", "\n"),
          ("retry-of-a-delegate", "a delegate may be re-queued", ("RetryTest.test_a_requeue_is_of_ended_non_delegate_work_one_attempt_on",),
           "retries_of_ended_work_counted", "                   AND i.kind != 'delegate' AND", "                   AND"),
          ("retry-of-live-work", "work that has not ended may be re-queued", ("RetryTest.test_a_requeue_is_of_ended_non_delegate_work_one_attempt_on",),
           "retries_of_ended_work_counted", " AND i.state IN ('failed', 'cancelled'))", ")"),
          ("retry-attempt-uncounted", "a re-queue's attempt may be any number", ("RetryTest.test_a_requeue_is_of_ended_non_delegate_work_one_attempt_on", "RetryTest.test_a_retry_counts_along_its_chain"),
           "retries_of_ended_work_counted", "\n  OR NEW.attempt IS NOT coalesce((SELECT r.attempt FROM retries r WHERE r.retry_invocation_id = NEW.invocation_id), 1) + 1", ""),
          ("retry-claimed-twice", "a claimed re-queue may be claimed again or unclaimed", ("RetryTest.test_a_requeue_is_claimed_once_by_the_same_topic_and_kind",),
           "retries_claimed_once", "WHEN OLD.retry_invocation_id IS NOT NULL\n  OR ", "WHEN "),
          ("retry-rewritable", "a re-queue's reason may change", ("RetryTest.test_a_requeue_is_claimed_once_by_the_same_topic_and_kind",),
           "retries_claimed_once", " OR NEW.reason IS NOT OLD.reason", ""),
          ("retry-claimed-by-another-kind", "a re-queue may be claimed by another kind's work", ("RetryTest.test_a_requeue_is_claimed_once_by_the_same_topic_and_kind",),
           "retries_claimed_once", " AND n.kind = o.kind)", ")"),
          ("retry-claimed-by-another-topic", "a re-queue may be claimed by another topic's work", ("RetryTest.test_a_retry_of_another_topic_is_refused",),
           "retries_claimed_once", " AND n.topic_id = o.topic_id", ""),
          ("impact-any-classification", "an impact record's classification may not fit its kind", ("AmendmentImpactTest.test_an_impact_record_names_its_row_and_never_changes",),
           "amendment_impacts", "  CHECK ((kind = 'contract') = (classification IN ('compatible', 'protocol_changed', 'reframed'))),\n", ""),
          ("impact-document-unbound", "an impact record's document may name another classification", ("AmendmentImpactTest.test_an_impact_record_names_its_row_and_never_changes",),
           "amendment_impacts", " AND json_extract(document, '$.classification') IS classification)", ")"),
          ("impact-of-a-rejection", "an impact may be recorded for a rejected decision", ("AmendmentImpactTest.test_an_impact_is_of_an_approval_of_its_topic",),
           "amendment_impacts_of_an_approval", " AND d.disposition = 'approved'\n", "\n"),
          ("impact-of-any-kind", "an impact may be recorded for any kind of decision", ("AmendmentImpactTest.test_an_impact_is_of_an_approval_of_its_topic",),
           "amendment_impacts_of_an_approval", "    AND d.kind IN (CASE NEW.kind WHEN 'contract' THEN 'contract_approval' ELSE 'brief_confirmation' END,\n"
           "                   CASE NEW.kind WHEN 'contract' THEN 'amendment_approval' END, CASE NEW.kind WHEN 'contract' THEN 'reframe_approval' END))", ")"),
          ("impact-of-another-topic", "an impact may be recorded for another topic's decision", ("AmendmentImpactTest.test_an_impact_is_of_an_approval_of_its_topic",),
           "amendment_impacts_of_an_approval", " AND d.topic_id = NEW.topic_id", ""),
      )),
    Mutation("1D-ddl-qualified-by-any-string", "1d", "qualified authority needs no qualification record",
             (SR + "QualificationTest.test_qualified_authority_rests_on_a_live_record_of_exactly_its_spec",), drop_trigger="decision_receipts_qualification_live"),
    *(Mutation(f"1D-ddl-{key}-dropped", "1d", desc, tuple(SR + k for k in killers), drop_trigger=trigger)
      for key, desc, killers, trigger in (
          ("bundle-questions-altered", "a bundle may carry another content under a registered question version",
           ("QuestionRegistryTest.test_a_bundle_carries_a_registered_version_only_under_its_content",), "config_bundles_questions_unaltered"),
          ("question-not-its-bundles", "a question row need not be its registering bundle's entry", ("QuestionRegistryTest.test_a_question_is_the_entry_of_its_bundle",),
           "questions_carried_by_their_bundle"),
          ("trigger-any-episode", "a trigger may join another topic's review episode", ("SignalQueueEpisodeTest.test_a_trigger_joins_only_its_topics_episode",),
           "review_triggers_episode_of_their_topic"))),
    Mutation("1D-ddl-config-two-active", "1d", "two bundles may be active", (SR + "ConfigBundleTest.test_a_bundle_is_recorded_active_newest_and_alone",),
             old="CREATE UNIQUE INDEX config_bundles_one_active ON config_bundles (status) WHERE status = 'active';\n", new=""),
    # The router's registries (registries.py).
    *(Mutation(f"1D-registry-{key}", "1d", desc, tuple(killers), target=REG, old=old, new=new)
      for key, desc, killers, old, new in (
          ("duplicate-question", "a bundle may carry one question version twice", (RG + "ConfigBundleTest.test_a_question_version_twice_is_refused",),
           "            if len(set(keys)) != len(keys):", "            if False:"),
          ("question-hash-untrue", "a question's content hash is taken on its word", (RG + "ConfigBundleTest.test_a_question_that_does_not_hash_to_its_label_is_refused",),
           '                if canonical.content_hash(q) != q["content_hash"]:', "                if False:"),
          ("bundle-identity-partial", "a bundle's identity omits its questions", (STC + "test_a_bundles_identity_is_the_hash_of_its_whole_document",),
           "            bundle_hash = canonical.logical_hash(doc)", '            bundle_hash = canonical.logical_hash({**doc, "questions": []})'),
          ("refusal-no-fact", "a refused bundle raises no dated fact", (RG + "ConfigBundleTest.test_a_refusal_is_a_dated_fact_raised_on_the_transition_only",
                                                                        STC + "test_the_station_does_not_start_on_a_refused_bundle"),
           '                self._fact(BUNDLE_CAPABILITY, "failing", ', '                (lambda *_: None)(BUNDLE_CAPABILITY, "failing", '),
          ("superseded-reactivated", "a superseded bundle is replayed as if active", (RG + "ConfigBundleTest.test_a_superseded_bundle_is_never_reactivated",),
           '            if stored["status"] != "active":', "            if False:"),
          ("version-unordered", "a bundle's version need not be above every recorded one", (RG + "ConfigBundleTest.test_a_version_not_above_every_recorded_one_is_refused",),
           '        if doc["version"] <= newest:', "        if False:"),
          ("question-altered", "a bundle may carry another content under a registered question version",
           (RG + "ConfigBundleTest.test_an_altered_question_is_refused_and_a_new_version_is_not",),
           '            if row is not None and row["content_hash"] != q["content_hash"]:', "            if False:"),
          ("active-not-superseded", "activation leaves the active bundle active", (RG + "ConfigBundleTest.test_activation_records_the_bundle_its_questions_and_supersedes_the_last",),
           '        if active is not None:\n            self._store.update("config_bundles"', '        if False:\n            self._store.update("config_bundles"'),
          ("no-recovery-fact", "a valid bundle after a refusal records no recovery", (RG + "ConfigBundleTest.test_a_refusal_is_a_dated_fact_raised_on_the_transition_only",),
           '\n        self._fact(BUNDLE_CAPABILITY, "healthy",', '\n        (lambda *_: None)(BUNDLE_CAPABILITY, "healthy",'),
          # task 1d-repair (finding 5): the active bundle mounted again after a refusal is a recovery
          ("replay-no-recovery", "the active bundle restored by a replay leaves the capability failing",
           (RG + "ConfigBundleTest.test_the_active_bundle_mounted_again_after_a_refusal_is_a_recovery", STC + "test_the_station_does_not_start_on_a_refused_bundle"),
           '\n            self._fact(BUNDLE_CAPABILITY, "healthy",', '\n            (lambda *_: None)(BUNDLE_CAPABILITY, "healthy",'),
          # task 1d-repair-2 (Astra 1d-repair review finding 2): the active bundle restored with nothing mounted is a recovery too
          ("restore-no-recovery", "the active bundle restored with nothing mounted leaves the capability failing (recovery suppressed on that path only)",
           (RG + "ConfigBundleTest.test_restoring_the_active_bundle_after_a_refusal_is_a_recovery", STR + "test_a_restart_with_nothing_mounted_recovers_from_a_refused_mount"),
           '\n                self._fact(BUNDLE_CAPABILITY, "healthy",', '\n                (lambda *_: None)(BUNDLE_CAPABILITY, "healthy",'),
          ("fact-every-refusal", "every refusal raises a fact, not only a transition", (RG + "ConfigBundleTest.test_a_refusal_is_a_dated_fact_raised_on_the_transition_only",),
           '        if (current["state"] if current is not None else "healthy") == state:\n            return\n', ""),
          ("router-policy-shipped-only", "the router's policy ignores the pinned bundle", (RG + "ConfigBundleTest.test_an_episode_holds_window_is_its_pinned_bundles",
                                                                                         SQ + "RequeueTest.test_the_hold_deadline_is_the_pinned_bundles_window"),
           '        return {**ROUTER_DEFAULTS, **self._bundle(bundle_hash)["policy"].get("router", {})}', "        return dict(ROUTER_DEFAULTS)"),
          ("hold-window-default", "the shipped hold window is not one hour", (RG + "ConfigBundleTest.test_an_episode_holds_window_is_its_pinned_bundles",),
           'ROUTER_DEFAULTS = {"hold_window_s": 3600.0}', 'ROUTER_DEFAULTS = {"hold_window_s": 60.0}'),
          ("qualification-conflict-replayed", "another grant under a recorded qualification id replays", (RG + "QualificationRecordTest.test_a_record_replays_and_conflicts_by_its_id",),
           '            if {k: row[k] for k in grant} != grant or row["granted_by"] != req["operator_id"]:', "            if False:"),
          ("qualification-any-spec", "a qualification may name another provider or class than its spec's",
           (RG + "QualificationRecordTest.test_a_record_qualifies_only_its_specs_provider_and_class",),
           '        if spec is None or (spec["provider"], spec["decision_class"]) != (req["provider"], req["decision_class"]):', "        if spec is None:"),
          ("revocation-conflict-replayed", "another revocation of a revoked qualification replays", (RG + "QualificationRecordTest.test_revocation_replays_conflicts_and_needs_a_record",),
           '            if (row["revoked_by"], row["revoke_reason"]) != (req["operator_id"], req["reason"]):', "            if False:"),
          ("revocation-not-recorded", "a revocation is answered and not recorded", (RG + "QualificationRecordTest.test_revocation_takes_effect_and_reinterprets_nothing",),
           '        self._store.update("qualifications", {"qualification_id": req["qualification_id"]},', '        (lambda *_: None)("qualifications", {"qualification_id": req["qualification_id"]},'),
          ("revoked-still-qualified", "a revoked record still qualifies", (RG + "QualificationRecordTest.test_revocation_takes_effect_and_reinterprets_nothing",),
           'return row is not None and row["revoked_at"] is None and (', "return row is not None and ("),
          ("qualified-any-spec", "a record qualifies another spec", (RG + "QualificationRecordTest.test_a_reference_to_another_specs_record_is_not_qualification",),
           ' and (row["provider"], row["decision_class"], row["spec_hash"]) == (provider, decision_class, spec_hash)', ""),
      )),
    # The router's commit and claim paths (service.py, boundary.py, lifecycle.py).
    *(Mutation(f"1D-router-{key}", "1d", desc, tuple(killers), target=target, old=old, new=new)
      for key, desc, killers, target, old, new in (
          ("claim-any-bundle", "new work may pin any bundle", (RG + "ConfigBundleTest.test_new_work_pins_the_active_bundle", RG + "ConfigBundleTest.test_no_active_bundle_admits_no_work"), SVC,
           '        if active is None or active["bundle_hash"] != req["config_bundle_hash"]:', "        if False:"),
          ("lane-ungated", "a lane whose last work ended is claimed without its re-queue", (SQ + "RequeueTest.test_every_kinds_lane_waits_for_a_requeue_within_its_budget",), SVC,
           '        retry = self._admit_lane(req, topic["topic_id"], scope)', "        retry = None"),
          ("retry-unlinked", "a retry's claim is not recorded on its re-queue", (SQ + "RequeueTest.test_every_kinds_lane_waits_for_a_requeue_within_its_budget",), SVC,
           '        if retry is not None:\n            self._store.update("retries"', '        if False:\n            self._store.update("retries"'),
          ("reservation-not-drawn", "a claim under a reservation draws nothing", (SQ + "ReservationTest.test_a_reservation_is_sized_by_the_bundle_and_drawn_within_its_units",), SVC,
           '        if "reservation" in req:\n            self._draw(', '        if False:\n            self._draw('),
          ("replay-ignores-retry", "a claim replays whatever retry it names", (SQ + "RequeueTest.test_a_retry_names_only_the_lanes_waiting_work",), SVC,
           '                    and (retry and retry["invocation_id"]) == req.get("retry_of")\n', ""),
          ("replay-ignores-draw", "a claim replays whatever reservation it names", (SQ + "ReservationTest.test_an_auto_promotion_draw_is_inside_a_facet_rated_at_the_threshold",), SVC,
           '\n                    and (draw and {k: v for k, v in draw.items() if k in ("reservation_id", "facet_id") and v is not None}) == req.get("reservation"))', ")"),
          ("qualification-not-rechecked", "a revocation between validation and the write is not seen by the router", (RG + "QualificationRecordTest.test_a_revocation_between_validation_and_the_write_is_seen",), SVC,
           '            if authorization["authority_level"] == "qualified" and not self.is_qualified(', "            if False and not self.is_qualified("),
          ("policy-version-unpinned", "a receipt records a fixed policy version, not its pinned bundle's", (RG + "ConfigBundleTest.test_admitted_work_keeps_its_pinned_bundle",), SVC,
           '"policy_version": f"config-bundle/{bundle[\'version\']}"', '"policy_version": "router-policy/1"'),
          ("commit-reads-active-bundle", "a commit is judged under the active bundle, not its pinned one",
           (RG + "QuestionPinTest.test_a_spec_whose_question_the_pinned_bundle_lacks_is_refused", RG + "ConfigBundleTest.test_admitted_work_keeps_its_pinned_bundle"), SVC,
           '        bundle = self._bundle(inv["config_bundle_hash"])', '        bundle = self._active_bundle()["document"]'),
          ("stale-claim-promoted", "a claim produced under an incompatibly superseded revision is promoted",
           (AM + "ImpactTest.test_a_stale_claim_is_not_promoted_and_an_adopted_revision_is",), SVC,
           '            if producer["admission_context"] == "contract/1" and self._pin_status(producer) not in ("current", "compatible"):', "            if False:"),
          ("reframe-as-amendment", "a framing change is approved as a plain amendment (and a reframe approval approves anything)",
           (AM + "AmendmentApprovalTest.test_a_framing_change_is_approved_as_a_reframe_and_only_as_one",), SVC,
           '        if reframe != (d["kind"] == "reframe_approval"):', "        if False:"),
          ("amendment-any-parent", "a revision not revising the approved one is approved", (AM + "AmendmentApprovalTest.test_an_amendment_revises_the_approved_revision",), SVC,
           '        if previous is not None and revision["parent_revision"] != previous["revision"]:', "        if False:"),
          ("completed-not-requeued", "an approved amendment leaves a completed topic completed", (AM + "AmendmentApprovalTest.test_an_approved_amendment_requeues_a_completed_topic",), SVC,
           ', "completed_with_qualified_conclusions": "queued"}', "}"),
          ("contract-impact-unrecorded", "an approval superseding a revision records no impact",
           (AM + "ImpactTest.test_an_impact_is_recorded_once_with_its_approval", AM + "ImpactTest.test_a_protocol_change_fences_admitted_work_of_every_kind"), SVC,
           '        if previous is not None:\n            effects.update(self._record_impact(d, "contract"', '        if False:\n            effects.update(self._record_impact(d, "contract"'),
          ("brief-impact-unrecorded", "a confirmation superseding a brief version records no impact", (AM + "BriefImpactTest.test_a_content_change_fences_scoping_work",), SVC,
           "            for row in older:  # G-1:", "            for row in ():  # G-1:"),
          ("question-unpinned", "a spec's question need not be in the pinned bundle's registry", (RG + "QuestionPinTest.test_a_spec_whose_question_the_pinned_bundle_lacks_is_refused",), BND,
           '    if (question["question_id"], question["version"], question["content_hash"]) not in questions:', "    if False:"),
          ("hold-window-unpinned", "an episode hold's window is the shipped hour whatever the pinned bundle", (RG + "ConfigBundleTest.test_an_episode_holds_window_is_its_pinned_bundles",), LIF,
           '        window = self._router_policy(inv["config_bundle_hash"])["hold_window_s"]', "        window = 3600"),
          # task 1d-repair (finding 4): a duration's fraction is kept, to the nanosecond, a finer one rounding up
          ("hold-fraction-dropped", "a hold window's fraction of a second is dropped",
           (RG + "ConfigBundleTest.test_a_fractional_hold_window_is_kept_exactly", SQ + "RequeueTest.test_a_fractional_exhaustion_hold_window_is_kept_exactly"), LIF,
           "math.ceil(Decimal(repr(seconds)) * 10**9)", "int(seconds) * 10**9"),
          ("hold-subnano-floored", "a window finer than a nanosecond becomes no window", (RG + "ConfigBundleTest.test_a_fractional_hold_window_is_kept_exactly",), LIF,
           "math.ceil(Decimal(repr(seconds)) * 10**9)", "math.floor(Decimal(repr(seconds)) * 10**9)"),
          ("hold-microseconds", "a deadline is written to the microsecond, losing nanoseconds", (RG + "ConfigBundleTest.test_a_fractional_hold_window_is_kept_exactly",), LIF,
           'f".{rest:09d}Z"', 'f".{rest // 1000:06d}Z"'),
      )),
    # Brief and contract versions, compatibility and impact (amendments.py).
    *(Mutation(f"1D-amend-{key}", "1d", desc, tuple(killers), target=AMD, old=old, new=new, also=tuple(also))
      for key, desc, killers, old, new, *also in (  # `also`: at most one further (old, new) edit of the same mutation
          ("framing-ignored", "a framing version change alone is not a reframe", (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says",),
           '    if pinned["facet_map"]["framing_version"] != current["facet_map"]["framing_version"] or not _same(framing(pinned), framing(current)):',
           "    if not _same(framing(pinned), framing(current)):"),
          ("protocol-revision-ignored", "a protocol revision change alone is compatible", (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says",),
           '    if pinned["protocol_revision"] != current["protocol_revision"] or not _same(protocol(pinned), protocol(current))',
           "    if not _same(protocol(pinned), protocol(current))"),
          ("protocol-sections-ignored", "an edit of the eligibility, stopping or applicability protocol alone is compatible", (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says",),
           " or not _same(protocol(pinned), protocol(current))", ""),
          ("obligations-ignored", "a shared obligation redefined is compatible", (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says",),
           " \\\n            or any(not _same(old[o], new[o]) for o in old.keys() & new.keys())", ""),
          ("importance-counted", "a change of importance alone is a protocol change", (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says",),
           ' for k, v in o.items() if k != "importance"}', " for k, v in o.items()}"),
          ("brief-content-ignored", "a brief whose content changed is compatible with its predecessor",
           (AM + "CompatibilityRuleTest.test_a_brief_is_compatible_only_in_its_lineage", AM + "BriefImpactTest.test_a_content_change_fences_scoping_work"),
           '    return "lineage_only" if _same(strip(pinned), strip(current)) else "content_changed"', '    return "lineage_only"'),
          ("document-hash-untrue", "a version's document is taken at its hash label", (AM + "BriefVersionTest.test_each_defect_is_refused_alone", AM + "AmendmentProposalTest.test_each_defect_is_refused_alone"),
           '                if canonical.content_hash(req["document"]) != req["document"]["content_hash"]:', "                if False:"),
          ("brief-conflict-replayed", "another version under a written brief version replays", (AM + "BriefVersionTest.test_each_defect_is_refused_alone",),
           '            if not _same(stored["document"], doc) or (stored["owner_operator_id"], stored["review_deadline"]) != (req["owner_operator_id"], req["review_deadline"]):',
           "            if False:"),
          ("brief-first-version", "a brief's first version is written here", (AM + "BriefVersionTest.test_a_closed_or_unknown_brief_takes_no_version",),
           '        if latest is None:\n            raise Refusal("unknown_brief", "a brief\'s first version is intake\'s (Phase 2); this writes the next version of a recorded brief")\n',
           '        latest = latest or {"version": 0, "status": "awaiting_confirmation"}\n'),
          ("brief-any-lineage", "a version need not follow the latest", (AM + "BriefVersionTest.test_each_defect_is_refused_alone",),
           '        if (doc["version"], doc["parent_version"]) != (latest["version"] + 1, latest["version"]):', "        if False:"),
          ("brief-closed-reopened", "a cancelled brief takes a new version", (AM + "BriefVersionTest.test_a_closed_or_unknown_brief_takes_no_version",),
           '        if latest["status"] in ("cancelled", "archived"):', "        if False:"),
          ("brief-created-later", "a version may be created after now", (AM + "BriefVersionTest.test_each_defect_is_refused_alone",),
           '        if instant(doc["created_at"]) > instant(now) or instant(req["review_deadline"]) <= instant(now):',
           '        if instant(req["review_deadline"]) <= instant(now):'),
          ("brief-deadline-past", "a version may be reviewed by a deadline already over", (AM + "BriefVersionTest.test_each_defect_is_refused_alone",),
           '        if instant(doc["created_at"]) > instant(now) or instant(req["review_deadline"]) <= instant(now):',
           '        if instant(doc["created_at"]) > instant(now) or instant(req["review_deadline"]) < instant(now):'),
          ("awaiting-not-superseded", "a version awaiting confirmation stays confirmable after its successor", (AM + "BriefVersionTest.test_a_new_version_supersedes_the_one_awaiting_confirmation",),
           '        if latest["status"] == "awaiting_confirmation":  # it can no longer be confirmed', "        if False:  # it can no longer be confirmed"),
          ("confirmed-superseded-early", "a confirmed version is superseded before its successor is confirmed",
           (AM + "BriefVersionTest.test_a_confirmed_version_stays_confirmed_until_its_successor_is",),
           '        if latest["status"] == "awaiting_confirmation":  # it can no longer be confirmed',
           '        if latest["status"] in ("awaiting_confirmation", "confirmed"):  # it can no longer be confirmed'),
          ("overdue-before-deadline", "a brief is marked overdue before its deadline", (AM + "OverdueTest.test_overdue_is_marked_once_the_deadline_has_passed",),
           '        if instant(now) < instant(row["review_deadline"]):', "        if False:"),
          ("overdue-deadline-exclusive", "a deadline at instant E is not yet over at E", (AM + "OverdueTest.test_overdue_is_marked_once_the_deadline_has_passed",),
           '        if instant(now) < instant(row["review_deadline"]):', '        if instant(now) <= instant(row["review_deadline"]):'),
          ("overdue-any-status", "a brief not awaiting confirmation is marked overdue", (AM + "OverdueTest.test_only_a_version_awaiting_confirmation_is_marked",),
           '        if row["status"] != "awaiting_confirmation":', "        if False:"),
          ("overdue-not-replayed", "marking a marked brief again is refused, not replayed", (AM + "OverdueTest.test_overdue_is_marked_once_the_deadline_has_passed",),
           '        if row["overdue_since"] is not None:\n            return {"status": "replayed", "overdue_since": row["overdue_since"]}\n', ""),
          ("amendment-conflict-replayed", "another document under a written revision replays", (AM + "AmendmentProposalTest.test_each_defect_is_refused_alone",),
           '            if not _same(stored["document"], doc):', "            if False:"),
          ("amendment-any-lineage", "an amendment need not be the next revision of the approved one", (AM + "AmendmentProposalTest.test_each_defect_is_refused_alone",),
           '        if (doc["revision"], doc["parent_revision"]) != (newest + 1, approved["revision"]):', "        if False:"),
          ("amendment-without-facets", "an amendment's facet rows are not written", (AM + "AmendmentProposalTest.test_an_amendment_is_recorded_as_a_draft_with_its_rows",),
           '        for facet in doc["facet_map"]["facets"]:', "        for facet in ():"),
          ("amendment-without-obligations", "an amendment's obligation rows are not written", (AM + "AmendmentProposalTest.test_an_amendment_is_recorded_as_a_draft_with_its_rows",),
           '        for o in doc["obligations"]:', "        for o in ():"),
          ("pins-unchecked", "work whose pins were superseded incompatibly commits",
           (RC + "FencingTest.test_work_pinned_to_a_superseded_contract_is_not_committed", RC + "FencingTest.test_work_pinned_to_a_superseded_brief_is_not_committed",
            AM + "ImpactTest.test_a_protocol_change_fences_admitted_work_of_every_kind"),
           "        status = self._pin_status(inv)\n        if status not in COMPATIBLE:", "        status = self._pin_status(inv)\n        if False:"),
          ("compatible-fenced", "work under a compatibly superseded version is fenced too",
           (AM + "ImpactTest.test_a_compatible_amendment_lets_admitted_work_complete_under_its_pins", AM + "BriefImpactTest.test_a_lineage_only_version_lets_scoping_work_complete"),
           'COMPATIBLE = ("current", "compatible", "lineage_only")', 'COMPATIBLE = ("current",)'),
          ("fenced-not-cancelled", "fenced work's cancellation is not requested", (AM + "ImpactTest.test_a_protocol_change_fences_admitted_work_of_every_kind",),
           '            self._cancel_in_transaction({"invocation_id": inv["invocation_id"], "requested_by": "router"',
           '            (lambda *_: None)({"invocation_id": inv["invocation_id"], "requested_by": "router"'),
          ("staged-result-cancelled", "a staged result's cancellation is requested (and refused, refusing the approval)",
           (AM + "ImpactTest.test_a_protocol_change_fences_admitted_work_of_every_kind",),
           'inv["state"] in ("admitted", "launching", "running", "outcome_unknown"):', 'inv["state"] in ("admitted", "launching", "running", "outcome_unknown", "result_ready"):'),
          ("everything-listed-again", "an impact lists what earlier impacts already made stale",
           (AM + "ImpactTest.test_the_record_lists_what_stood_until_now", AM + "StandingTest.test_a_framing_label_written_back_revives_no_claim"),
           "        stood = {v for v, was in prior.items() if was is None}", "        stood = set(prior)"),
          ("exclusions-not-reopened", "stale exclusions are not reopened", (AM + "ImpactTest.test_a_protocol_change_fences_admitted_work_of_every_kind",
                                                                           AM + "ImpactTest.test_a_reframe_marks_coverage_and_labels_stale_and_reopens_exclusions"),
           ' if a["decision"] == "exclude" and a["disposition"] != "valid"]', " if False]"),
          # task 1d-repair (Astra 1d review finding 1): the framing a framing version names, section by section (G-6)
          *((f"framing-without-{part}", f"a change of {what} alone is compatible", (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says", AM + "VersionBindingTest.test_a_changed_framing_needs_a_new_framing_version"), old, new)
            for part, what, old, new in (
                ("decision-record", "the decision record", '"decision_record": doc.get("decision_record"), ', ""),
                ("framework", "the analytic framework", '"analytic_framework": facet_map.get("analytic_framework"),', ""),
                ("facets", "a facet", '\n            "facets": [{k: v for k, v in facet.items() if k != "importance"} for facet in facet_map.get("facets", ())],', ""),
                ("question-types", "the coverage question types", '"question_types": (facet_map.get("coverage_matrix") or {}).get("question_types"), ', ""),
                ("deliberately-out", "what is deliberately out", ', "deliberately_out": facet_map.get("deliberately_out")}', "}"))),
          ("framing-content-ignored", "framing content changed under the same framing version is compatible", (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says",),
           " or not _same(framing(pinned), framing(current)):", ":"),
          ("framing-counts-facet-importance", "a facet's importance alone is a reframe", (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says",),
           ' for k, v in facet.items() if k != "importance"}', " for k, v in facet.items()}"),
          ("framing-counts-coverage-cells", "filling or dropping a coverage cell is a reframe", (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says",),
           '(facet_map.get("coverage_matrix") or {}).get("question_types")', 'facet_map.get("coverage_matrix")'),
          # task 1d-repair-2 (Astra 1d-repair review finding 1): what a revision withdraws from the approved inventory is protocol_changed
          ("inventory-withdrawal-ignored", "a withdrawal from the approved inventory is compatible (the reviewed defect)",
           (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says", AM + "InventoryImpactTest.test_a_removed_obligation_fences_its_work_coverage_and_claim",
            AM + "InventoryImpactTest.test_a_redefinition_under_a_new_id_is_fenced_the_same", AM + "InventoryImpactTest.test_a_scope_removing_cell_alone_fences"),
           " \\\n            or _withdrawn(pinned, current):", ":"),
          ("inventory-removal-ignored", "an obligation removed, or issued again under another id, is compatible",
           (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says", AM + "InventoryImpactTest.test_an_obligation_removed_alone_fences"),
           "    if _obligations(pinned).keys() - _obligations(current).keys():", "    if False:"),
          ("inventory-cells-ignored", "a coverage cell the revision does not keep is compatible", (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says",),
           "    if any(not any(_kept(was, cell) for cell in new.get(pair, ())) for pair, cells in old.items() for was in cells):", "    if False:"),
          ("inventory-cell-shrink-kept", "a covered cell losing an obligation is kept", (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says",),
           '\n        and set(was.get("obligation_ids", ())) <= set(cell.get("obligation_ids", ())))', ")"),
          ("inventory-cell-entry-change-kept", "a covered cell otherwise changed is kept", (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says",),
           " and _same(rest(was), rest(cell))", ""),
          ("inventory-gap-fill-withdrawn", "a gap filled is a withdrawal, fencing an addition",
           (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says", AM + "InventoryImpactTest.test_a_filled_gap_lets_work_complete_and_its_claim_promote"),
           '        was["state"] == "gap" or was["state"] == "covered"', '        was["state"] == "covered"'),
          ("inventory-out-cell-brought-back-kept", "a deliberately-out cell brought back into scope is kept",
           (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says", AM + "InventoryImpactTest.test_a_restored_obligation_revives_nothing"),
           '        was["state"] == "gap" or was["state"] == "covered"', '        was["state"] in ("gap", "deliberately_out") or was["state"] == "covered"'),
          ("inventory-cell-added-out", "a cell added out of scope is compatible", (AM + "CompatibilityRuleTest.test_a_cell_for_a_pair_not_listed_before_is_added_only_in_scope",),
           '    return any(cell["state"] != "covered" and', '    return False and any(cell["state"] != "covered" and'),
          ("inventory-gap-beside-kept", "a gap added beside a listed pair's cell is compatible",
           (AM + "CompatibilityRuleTest.test_a_cell_for_a_pair_not_listed_before_is_added_only_in_scope",),
           ' and (cell["state"] != "gap" or pair in old)', ' and cell["state"] != "gap"'),
          ("inventory-new-gap-withdrawn", "a gap listed for a pair not listed before is a withdrawal",
           (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says", AM + "CompatibilityRuleTest.test_a_cell_for_a_pair_not_listed_before_is_added_only_in_scope"),
           ' and (cell["state"] != "gap" or pair in old)', ""),
          ("inventory-unchanged-cells-withdrawn", "a gap or deliberately-out cell kept as it was is a withdrawal",
           (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says", AM + "InventoryImpactTest.test_a_filled_gap_lets_work_complete_and_its_claim_promote"),
           " and not any(_same(was, cell) for was in old.get(pair, ()))", ""),
          *((f"protocol-without-{part}", f"an edit of the {what} alone is compatible", (AM + "CompatibilityRuleTest.test_each_section_is_classed_as_the_design_says",),
             'PROTOCOL_SECTIONS = ("eligibility_protocol", "stopping_profiles", "applicability_rules")', new)
            for part, what, new in (("eligibility", "eligibility protocol", 'PROTOCOL_SECTIONS = ("stopping_profiles", "applicability_rules")'),
                                    ("stopping", "stopping profiles", 'PROTOCOL_SECTIONS = ("eligibility_protocol", "applicability_rules")'),
                                    ("applicability", "applicability rules", 'PROTOCOL_SECTIONS = ("eligibility_protocol", "stopping_profiles")'))),
          # a label names one content: an unchanged one keeps its label, a changed one takes a new label above every recorded one
          ("unchanged-relabelled", "an unchanged framing or protocol takes a new label",
           (AM + "VersionBindingTest.test_an_unchanged_framing_keeps_its_version", AM + "VersionBindingTest.test_a_protocol_revision_names_one_protocol"),
           "                if label(doc) != kept:", "                if False:"),
          ("changed-label-kept", "a changed framing or protocol keeps its label",
           (AM + "VersionBindingTest.test_a_changed_framing_needs_a_new_framing_version", AM + "VersionBindingTest.test_a_protocol_revision_names_one_protocol"),
           "            elif label(doc) <= recorded:", "            elif False:"),
          ("label-returns", "an earlier label may name a changed framing or protocol again",
           (AM + "VersionBindingTest.test_a_framing_version_never_names_another_framing", AM + "VersionBindingTest.test_a_protocol_revision_names_one_protocol"),
           "            elif label(doc) <= recorded:", "            elif label(doc) == kept:"),
          ("framing-unbound", "the framing version is bound to nothing", (AM + "VersionBindingTest.test_a_changed_framing_needs_a_new_framing_version",
                                                                       AM + "VersionBindingTest.test_an_unchanged_framing_keeps_its_version"),
           'VERSIONED = (("framing", "framing version", lambda doc: doc["facet_map"]["framing_version"], framing),\n             (', "VERSIONED = ((",
           ('lambda doc: doc["protocol_revision"], protocol))', 'lambda doc: doc["protocol_revision"], protocol),)')),
          ("protocol-unbound", "the protocol revision is bound to nothing", (AM + "VersionBindingTest.test_a_protocol_revision_names_one_protocol",),
           ',\n             ("protocol", "protocol revision", lambda doc: doc["protocol_revision"], protocol))', ",)"),
          # standing: what a recorded impact made stale stays stale (G-1)
          ("pin-rejudged", "a pin is judged against the current revision again, reviving what an impact made stale",
           (AM + "StandingTest.test_a_framing_label_written_back_revives_no_claim", AM + "StandingTest.test_a_restored_obligation_revives_no_work_or_claim",
            AM + "AmendmentRestartTest.test_standing_survives_a_restart"),
           '            return self._standing("contract", inv["topic_id"], inv["contract_revision"]) or "compatible"',
           '            return contract_compatibility(pinned["document"], self._one("contract_revisions", {"topic_id": inv["topic_id"], "status": "approved"})["document"])'),
          ("brief-pin-rejudged", "a brief pin is judged against the current version again", (AM + "BriefImpactTest.test_a_brief_restored_revives_no_scoping_work",),
           '            return self._standing("brief", inv["topic_id"], inv["brief_version"], inv["brief_ref"]) or "lineage_only"',
           '            return brief_compatibility(pinned["document"], current["document"])'),
          ("brief-other-lineage", "a pin to a brief whose lineage is no longer current is judged by that lineage",
           (AM + "BriefLineageTest.test_a_pin_whose_brief_is_no_longer_current_is_fenced",),
           ' and current["brief_id"] == inv["brief_ref"]:  # its own lineage is current', ":  # its own lineage is current"),
          ("standing-any-brief", "another brief's impacts judge a pin", (AM + "BriefLineageTest.test_another_briefs_impacts_do_not_judge_a_pin",),
           '                  if impact["document"].get("brief_id") == brief_id for entry', "                  for entry"),
          ("unrecorded-compatible", "a superseded version no impact lists is taken to be compatible", (AM + "StandingTest.test_a_version_no_impact_lists_is_not_reused",),
           '        if not listed:\n            return "unrecorded"\n', ""),
          ("stale-rejudged", "an impact classes a stale version against the new revision again",
           (AM + "StandingTest.test_a_restored_obligation_revives_no_work_or_claim",),
           'status = {r[key]: prior[r[key]] or compat(r["document"], current["document"])', 'status = {r[key]: compat(r["document"], current["document"])'),
          ("standing-unrecorded", "an impact records no standing", (AM + "ImpactTest.test_a_compatible_amendment_lets_admitted_work_complete_under_its_pins",
                                                                    AM + "BriefImpactTest.test_a_lineage_only_version_lets_scoping_work_complete"),
           '               "standing": [{key: v, "classification": status[v]} for v in sorted(stood)],\n', ""),
          ("brief-impact-unnamed", "a brief impact does not name its brief", (AM + "BriefImpactTest.test_a_lineage_only_version_lets_scoping_work_complete",),
           '        if kind == "brief":\n            doc["brief_id"] = brief_id', '        if False:\n            doc["brief_id"] = brief_id'),
          # Astra 1d review finding 6: each half of a version's lineage, alone
          ("brief-parent-unchecked", "a brief version's parent need not be the latest", (AM + "BriefVersionTest.test_each_defect_is_refused_alone",),
           '        if (doc["version"], doc["parent_version"]) != (latest["version"] + 1, latest["version"]):', '        if doc["version"] != latest["version"] + 1:'),
          ("brief-version-unchecked", "a brief version need not be the next", (AM + "BriefVersionTest.test_each_defect_is_refused_alone",),
           '        if (doc["version"], doc["parent_version"]) != (latest["version"] + 1, latest["version"]):', '        if doc["parent_version"] != latest["version"]:'),
          ("amendment-parent-unchecked", "an amendment's parent need not be the approved revision", (AM + "AmendmentProposalTest.test_each_defect_is_refused_alone",),
           '        if (doc["revision"], doc["parent_revision"]) != (newest + 1, approved["revision"]):', '        if doc["revision"] != newest + 1:'),
          ("amendment-revision-unchecked", "an amendment need not be the next revision", (AM + "AmendmentProposalTest.test_each_defect_is_refused_alone",),
           '        if (doc["revision"], doc["parent_revision"]) != (newest + 1, approved["revision"]):', '        if doc["parent_revision"] != approved["revision"]:'),
          ("reservations-left-open", "an approval leaves the superseded revision's reservations open",
           (SQ + "ReservationTest.test_an_amendment_closes_the_reservations_of_the_revision_it_supersedes",),
           '                if r["closed_at"] is None and r["contract_revision"] != current["revision"]:', "                if False:"),
      )),
    # Re-queues, reservations and the signal queue (scheduling.py).
    *(Mutation(f"1D-sched-{key}", "1d", desc, tuple(killers), target=SCH, old=old, new=new)
      for key, desc, killers, old, new in (
          ("requeue-conflict-replayed", "another re-queue of re-queued work replays", (SQ + "RequeueTest.test_only_a_lanes_last_ended_non_delegate_work_is_requeued",),
           '            if (recorded["requested_by"], recorded["reason"]) != (req["requested_by"], req["reason"]):', "            if False:"),
          ("requeue-live-work", "work that has not ended is re-queued", (SQ + "RequeueTest.test_only_a_lanes_last_ended_non_delegate_work_is_requeued",),
           '        if inv["state"] not in ("failed", "cancelled") or self._lane_last(', "        if self._lane_last("),
          ("requeue-not-the-lanes-last", "ended work its lane moved past, or a delegate's, is re-queued",
           (SQ + "RequeueTest.test_ended_work_its_lane_moved_past_is_not_requeued", SQ + "RequeueTest.test_only_a_lanes_last_ended_non_delegate_work_is_requeued"),
           ' or self._lane_last(inv["topic_id"], boundary.SCOPE_OF_KIND.get(inv["kind"])) != inv["invocation_id"]:', ":"),
          ("requeue-ignores-incident", "work is re-queued while its hold is open", (SQ + "RequeueTest.test_every_kinds_lane_waits_for_a_requeue_within_its_budget",),
           '        if any(h["cleared_at"] is None for h in self._store.select("holds", {"topic_id": inv["topic_id"], "subject_ref": subject})):', "        if False:"),
          ("policy-requeues-operator-cancellation", "policy re-queues work the operator cancelled", (SQ + "RequeueTest.test_policy_requeues_only_transient_ends",),
           'inv["cancel_requested_by"] in ("supervisor", "router")', 'inv["cancel_requested_by"] in ("supervisor", "router", "operator")'),
          ("policy-requeues-any-failure", "policy re-queues a failure class the bundle does not list", (SQ + "RequeueTest.test_policy_requeues_only_transient_ends",),
           ' inv["failure_class"] in policy["failure_classes"]', " True"),
          ("policy-budget-unbounded", "policy re-queues past its budget", (SQ + "RequeueTest.test_every_kinds_lane_waits_for_a_requeue_within_its_budget",),
           '            if policy is None or attempt - 1 > policy["attempts"]:', "            if policy is None:"),
          ("policy-budget-short", "policy's budget is one re-queue short", (SQ + "RequeueTest.test_every_kinds_lane_waits_for_a_requeue_within_its_budget",),
           'attempt - 1 > policy["attempts"]:', 'attempt - 1 >= policy["attempts"]:'),
          ("exhaustion-without-hold", "an exhausted budget opens no hold", (SQ + "RequeueTest.test_every_kinds_lane_waits_for_a_requeue_within_its_budget",),
           '                self._store.insert("holds", {', '                (lambda *_: None)("holds", {'),
          ("lane-gate-never", "a lane whose last work ended is never waiting", (SQ + "RequeueTest.test_every_kinds_lane_waits_for_a_requeue_within_its_budget",),
           '        if ended is not None and ended["state"] in ("failed", "cancelled"):', "        if False:"),
          ("lane-claimed-unnamed", "a re-queued lane is claimed by work not naming the retry", (SQ + "RequeueTest.test_every_kinds_lane_waits_for_a_requeue_within_its_budget",),
           '            if req.get("retry_of") != last or retry is None:', "            if retry is None:"),
          ("lane-claimed-unrequeued", "a lane is claimed as the retry of work not re-queued", (SQ + "RequeueTest.test_every_kinds_lane_waits_for_a_requeue_within_its_budget",),
           '            if req.get("retry_of") != last or retry is None:', '            if req.get("retry_of") != last:'),
          ("retry-of-anything", "a claim names as its retry work not waiting in its lane", (SQ + "RequeueTest.test_a_retry_names_only_the_lanes_waiting_work",),
           '        if req.get("retry_of") is not None:\n            raise Refusal("request_invalid"', '        if False:\n            raise Refusal("request_invalid"'),
          ("reservation-conflict-replayed", "another reservation under a recorded id replays", (SQ + "ReservationTest.test_opening_needs_an_approved_revision_a_size_and_no_open_one_with_units_left",),
           '            if (stored["topic_id"], stored["purpose"]) != (req["topic_id"], req["purpose"]):', "            if False:"),
          ("reservation-without-approval", "a reservation is opened with no approved revision", (SQ + "ReservationTest.test_opening_needs_an_approved_revision_a_size_and_no_open_one_with_units_left",),
           '        if approved is None:\n            raise Refusal("no_approved_contract", "a reservation is bound to an approved contract revision (G-5)")\n',
           '        approved = approved or {"revision": 1}\n'),
          ("reservation-unsized", "a reservation the bundle does not size is opened with a default", (SQ + "ReservationTest.test_opening_needs_an_approved_revision_a_size_and_no_open_one_with_units_left",),
           '        if sized is None:\n            raise Refusal("not_configured", f"the active bundle sizes no {req[\'purpose\']} reservation (G-10)")\n',
           '        sized = sized or {"units": 1}\n'),
          ("reservation-reopened", "a reservation with units left is closed and replaced", (SQ + "ReservationTest.test_opening_needs_an_approved_revision_a_size_and_no_open_one_with_units_left",),
           '            if len(self._store.select("reservation_draws", {"reservation_id": current["reservation_id"]})) < current["units"]:', "            if False:"),
          ("exhausted-left-open", "an exhausted reservation is not closed when the next opens", (SQ + "ReservationTest.test_opening_needs_an_approved_revision_a_size_and_no_open_one_with_units_left",),
           '            self._store.update("reservations", {"reservation_id": current["reservation_id"]}, {"closed_at": now, "close_reason": "exhausted"})', "            pass"),
          ("draw-closed", "a closed reservation is drawn on", (SQ + "ReservationTest.test_an_amendment_closes_the_reservations_of_the_revision_it_supersedes",),
           '        if r is None or r["topic_id"] != topic_id or r["closed_at"] is not None:', "        if r is None:"),
          ("draw-beyond-units", "a reservation is drawn on beyond its units", (SQ + "ReservationTest.test_a_reservation_is_sized_by_the_bundle_and_drawn_within_its_units",),
           '        if len(self._store.select("reservation_draws", {"reservation_id": r["reservation_id"]})) >= r["units"]:', "        if False:"),
          ("draw-below-threshold", "an auto-promotion draw names a facet rated below the threshold",
           (SQ + "ReservationTest.test_an_auto_promotion_draw_is_inside_a_facet_rated_at_the_threshold",),
           '            if facet is None or BAND.get(facet["operator_importance_band"], 0) < BAND[r["min_band"]]:', "            if facet is None:"),
          ("review-without-signal", "a signal-driven review opens with nothing pending", (SQ + "SignalQueueTest.test_a_review_needs_a_pending_signal_a_configured_queue_and_its_own_key",),
           '            if not pending:\n                raise Refusal("no_pending_signal"', '            if False:\n                raise Refusal("no_pending_signal"'),
          ("mandatory-held-back", "a pending mandatory signal is held back by the budget and cooldown",
           (SQ + "SignalQueueTest.test_the_cadence_floor_and_mandatory_signals_are_never_held_back",),
           '        if req["kind"] != "fixed_cadence" and not any(t["reason_code"] in MANDATORY for t in pending):', '        if req["kind"] != "fixed_cadence":'),
          ("floor-held-back", "the fixed cadence floor is held back by the budget and cooldown",
           (SQ + "SignalQueueTest.test_the_cadence_floor_and_mandatory_signals_are_never_held_back",),
           '        if req["kind"] != "fixed_cadence" and not any(t["reason_code"] in MANDATORY for t in pending):', '        if not any(t["reason_code"] in MANDATORY for t in pending):'),
          ("queue-unconfigured-unbounded", "an unconfigured signal queue admits every review",
           (SQ + "SignalQueueTest.test_a_review_needs_a_pending_signal_a_configured_queue_and_its_own_key",),
           '            if queue is None:\n                raise Refusal("not_configured", "the active bundle sets no signal-queue budget; the signals stay queued (G-10)")\n',
           '            queue = queue or {"budget": 1000, "window_s": 1.0, "cooldown_s": 0}\n'),
          ("budget-unbounded", "signal reviews exceed the budget", (SQ + "SignalQueueTest.test_reviews_coalesce_within_budget_and_cooldown_and_drop_nothing",),
           '            if len(recent) >= queue["budget"]:', "            if False:"),
          ("budget-windowless", "every signal review ever opened counts against the budget", (SQ + "SignalQueueTest.test_reviews_coalesce_within_budget_and_cooldown_and_drop_nothing",),
           '            recent = [t for t in opened if t > instant(now) - int(queue["window_s"] * 10**9)]', "            recent = opened"),
          ("cooldown-ignored", "a signal review opens within the cooldown", (SQ + "SignalQueueTest.test_reviews_coalesce_within_budget_and_cooldown_and_drop_nothing",),
           '            if opened and instant(now) < opened[-1] + int(queue["cooldown_s"] * 10**9):', "            if False:"),
          ("signals-dropped", "a review takes one pending signal and leaves the rest", (SQ + "SignalQueueTest.test_reviews_coalesce_within_budget_and_cooldown_and_drop_nothing",),
           "        for trigger in pending:\n", "        for trigger in pending[:1]:\n"),
          ("review-conflict-replayed", "another review under a recorded episode id replays", (SQ + "SignalQueueTest.test_a_review_needs_a_pending_signal_a_configured_queue_and_its_own_key",),
           '            if (stored["topic_id"], stored["kind"]) != (req["topic_id"], req["kind"]):', "            if False:"),
      )),
    # The supervisor's per-job policy and the composition root (supervisor.py, station.py).
    *(Mutation(f"1D-sup-{key}", "1d", desc, tuple(killers), target=target, old=old, new=new)
      for key, desc, killers, target, old, new in (
          ("job-ignores-pinned-bundle", "a job's budgets are the station's, not its pinned bundle's", (STC + "test_a_job_keeps_its_admitted_bundles_policy_across_a_restart",), SPV,
           "        if self._policies is None:\n            return self.policy\n", "        if True:\n            return self.policy\n"),
          ("order-pin-unchecked", "an order pinning no recorded bundle is written", (STC + "test_new_work_pins_the_mounted_bundle",), SPV,
           "        if self._policies is not None:\n            self._policies(order.config_bundle_hash)\n", ""),
          ("bundle-policy-ignored", "a bundle's supervisor values are ignored", (STC + "test_a_job_keeps_its_admitted_bundles_policy_across_a_restart",), SPV,
           '    return replace(Policy(), **bundle["policy"].get("supervisor", {}))', "    return Policy()"),
          ("station-falls-back", "a refused bundle leaves the station running on the previous one", (STC + "test_the_station_does_not_start_on_a_refused_bundle",), APP,
           '        if activated["status"] not in ("activated", "replayed"):\n            router.close()\n            raise StationRefused(f"the config bundle was refused ({activated[\'reason\']}): {activated[\'detail\']}")\n',
           '        if activated["status"] not in ("activated", "replayed"):\n            activated = {"bundle_hash": router._active_bundle()["bundle_hash"]}\n'),
          ("station-policy-shipped", "the station's own policy is the shipped defaults, not the bundle's",
           (STC + "test_a_job_keeps_its_admitted_bundles_policy_across_a_restart", STR + "test_a_restart_with_nothing_mounted_keeps_every_pin"), APP,
           "policy=policies(own), policies=policies", "policy=Policy(), policies=policies"),
          ("station-no-resolver", "the station gives its supervisor no per-job resolver",
           (STC + "test_a_job_keeps_its_admitted_bundles_policy_across_a_restart", STR + "test_a_restart_with_nothing_mounted_keeps_every_pin"), APP,
           "policies=policies, clock=clock", "policies=None, clock=clock"),
          ("station-two-policies", "a station takes both a bundle and a fixture policy", (STC + "test_the_station_does_not_start_on_a_refused_bundle",), APP,
           "        if config_bundle is not None:\n            router.close()\n            raise ValueError(", "        if False:\n            router.close()\n            raise ValueError("),
          # task 1d-repair (Astra 1d review finding 2): every production start resolves pins; nothing to restore refuses the start
          ("unmounted-starts-anyway", "a start with nothing mounted and nothing active goes on",
           (STR + "test_nothing_mounted_and_nothing_recorded_does_not_start",), APP,
           "        if own is None:\n            router.close()\n            raise StationRefused(", "        if False:\n            router.close()\n            raise StationRefused("),
          ("unmounted-restores-nothing", "a start with nothing mounted takes the shipped policy, not the active bundle's",
           (STR + "test_a_restart_with_nothing_mounted_keeps_every_pin",), APP,
           "policy=policies(own), policies=policies", "policy=Policy() if config_bundle is None else policies(own), policies=policies"),
          ("fixture-policy-ignored", "the fixture policy is not the one its jobs run under", (STR + "test_a_fallback_policy_is_only_a_named_fixture",), APP,
           "policy=fixture_policy, policies=None", "policy=Policy(), policies=None"),
          # task 1d-repair-2 (Astra 1d-repair review finding 2): a start with nothing mounted restores the active bundle through the router
          ("unmounted-not-restored", "a start with nothing mounted reads the active bundle and does not restore it",
           (STR + "test_a_restart_with_nothing_mounted_recovers_from_a_refused_mount",), APP,
           "        own = router.restore_config_bundle()", '        own = (router._active_bundle() or {}).get("bundle_hash")'),
          # task 1d-repair (Astra 1d review finding 3): a work order's retry and reservation reach the claim, from the stored order
          ("claim-drops-context", "a claim sends neither the retry nor the reservation its order names",
           (SRQ + "ResearchPassRequeueTest.test_a_failed_run_is_requeued_and_its_retry_runs", SRQ + "DiscoveryRequeueTest.test_a_reservation_is_drawn_by_the_order_naming_it"), SPV,
           '        for context in ("retry_of", "reservation"):', "        for context in ():"),
          ("claim-drops-retry", "a claim does not send the retry its order names",
           (SRQ + "VerificationRequeueTest.test_a_failed_run_is_requeued_and_its_retry_runs", STS + "test_a_requeued_failure_runs_again_through_the_station"), SPV,
           '        for context in ("retry_of", "reservation"):', '        for context in ("reservation",):'),
          ("claim-drops-reservation", "a claim does not send the reservation its order names",
           (SRQ + "CheckpointRequeueTest.test_a_reservation_is_drawn_by_the_order_naming_it", SRQ + "DelegateContextTest.test_a_delegate_is_no_retry_and_draws_nothing"), SPV,
           '        for context in ("retry_of", "reservation"):', '        for context in ("retry_of",):'),
          ("order-context-unstored", "a work order is stored without its retry and reservation",
           (SRQ + "CheckpointRequeueTest.test_the_retry_survives_a_restart_before_its_claim", SRQ + "ResearchPassRequeueTest.test_a_reservation_is_drawn_by_the_order_naming_it"), SPV,
           '"reservation": None if order.reservation is None else dict(order.reservation)})', '"reservation": None, "retry_of": None})'),
      )),
]


# Guards deliberately kept as a second layer behind another guard that
# always fires first for every row that reaches them, so no test can kill
# their removal alone. Listed so a reviewer does not mistake them for missed
# coverage; each names the first layer (which IS in the inventory).
SECOND_LAYER = {
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


def uncovered_triggers(ddl: str) -> list[str]:
    """DDL triggers that no mutation drops, scopes or edits, minus the
    documented second layers. The run fails while this is non-empty, so a new
    guard cannot land without a mutant (CHECK constraints are anonymous in
    SQLite and are not enumerated here; their mutants edit their text)."""
    blocks = {m.group(1): m.group(0) for m in re.finditer(r"CREATE TRIGGER (\w+)\b.*?\nEND;\n", ddl, re.DOTALL)}
    covered: set[str] = set()
    for m in MUTATIONS:
        if m.target != "ddl":
            continue
        if m.drop_trigger:
            covered.add(m.drop_trigger)
        elif m.scope:
            if m.scope in blocks:
                covered.add(m.scope)  # a scoped edit covers its scope only, whatever else shares the text
        else:
            for old in [m.old, *(o for o, _ in m.also)]:
                if old:  # unscoped edits must match the DDL exactly once; credit the trigger holding that match
                    covered.update(name for name, body in blocks.items() if old in body and ddl.count(old) == 1)
    return sorted(set(blocks) - covered - SECOND_LAYER_TRIGGERS)


class _Collector(unittest.TestResult):
    def __init__(self) -> None:
        super().__init__()
        self.failed: set[str] = set()
        self.errored: dict[str, str] = {}
        self.attestations: list[dict] = []  # what the killers' children attested (module docstring, "Children")
        self.expected: str | None = None     # the SHA-256 of the mutant as written into the child tree
        self.tree: Path | None = None
        self.ran: set[str] = set()
        self.skipped: set[str] = set()

    def startTest(self, test) -> None:  # noqa: N802 (unittest API)
        os.environ[ATTEST_TEST] = test.id()  # inherited by every child the test starts from here on
        self.ran.add(test.id())
        super().startTest(test)

    def addSkip(self, test, reason) -> None:  # noqa: N802
        self.skipped.add(test.id())

    def addFailure(self, test, err) -> None:  # noqa: N802 (unittest API)
        self.failed.add(test.id())

    def _record_error(self, test, err) -> None:
        in_setup = any(frame.name in ("setUp", "setUpClass") for frame in traceback.extract_tb(err[2]))
        if issubclass(err[0], sqlite3.IntegrityError) and not in_setup:
            self.failed.add(test.id())
        else:
            self.errored[test.id()] = self._exc_info_to_string(err, test).strip().splitlines()[-1]

    def addError(self, test, err) -> None:  # noqa: N802
        self._record_error(test, err)

    def addSubTest(self, test, subtest, err) -> None:  # noqa: N802
        if err is None:
            return
        if issubclass(err[0], test.failureException):
            self.failed.add(test.id())
        else:
            self._record_error(test, err)


def mutate(text: str, m: Mutation) -> str:
    if m.drop_trigger:
        pattern = re.compile(r"CREATE TRIGGER " + re.escape(m.drop_trigger) + r"\b.*?\nEND;\n", re.DOTALL)
        found = pattern.findall(text)
        if len(found) != 1:
            raise ValueError(f"trigger {m.drop_trigger!r} found {len(found)} times")
        return pattern.sub("", text)
    assert m.old is not None
    prefix, body, suffix = "", text, ""
    if m.scope:
        found = list(re.finditer(r"CREATE TRIGGER " + re.escape(m.scope) + r"\b.*?\nEND;\n", text, re.DOTALL))
        found += list(re.finditer(r"CREATE TABLE " + re.escape(m.scope) + r" \(.*?\n\) STRICT;\n", text, re.DOTALL))
        if len(found) != 1:
            raise ValueError(f"scope {m.scope!r} found {len(found)} times")
        prefix, body, suffix = text[: found[0].start()], found[0].group(0), text[found[0].end():]
    for old, new in ((m.old, m.new), *m.also):
        if body.count(old) != 1:
            raise ValueError(f"mutation text found {body.count(old)} times: {old[:60]!r}")
        body = body.replace(old, new)
    return prefix + body + suffix


def load_suite() -> unittest.TestSuite:
    return unittest.defaultTestLoader.discover(str(TESTS), pattern="test_store_*.py")


def killer_suite(names, modules: dict | None = None) -> unittest.TestSuite:
    """Exactly the named tests (module.Class.method), each once, loaded from
    the given module objects where one is named (a reloaded killer module
    must be the one run), else imported."""
    import importlib

    suite = unittest.TestSuite()
    for name in dict.fromkeys(names):
        module_name, _, rest = name.partition(".")
        module = (modules or {}).get(module_name) or importlib.import_module(module_name)
        suite.addTest(unittest.defaultTestLoader.loadTestsFromName(rest, module))
    return suite


def load_controls(path: Path = CONTROLS_FILE) -> dict[str, dict]:
    """Each mutant's paired controls and why they were chosen (module
    docstring, "Which tests run")."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


_CONTROLS: dict[str, dict] = {}  # bound in main() before workers fork


def controls_of(m: Mutation, controls: dict | None = None) -> tuple[str, ...]:
    return tuple(((_CONTROLS if controls is None else controls).get(m.mid) or {}).get("controls", ()))


def control_problems(mutations, controls: dict) -> list[str]:
    """Why these mutants' paired controls cannot run: a mutant with no entry,
    a control that is also its killer, a control name that is not exactly
    one test."""
    bad = [f"{m.mid}: no entry in {CONTROLS_FILE.name}" for m in mutations if m.mid not in controls]
    bad += [f"{m.mid}: {c} is both a killer and a control" for m in mutations for c in controls_of(m, controls) if c in m.killers]
    bad += [f"{m.mid}: {k} holds the accepted case but is not its killer" for m in mutations for k in (controls.get(m.mid) or {}).get("in_killer", ())
            if k not in m.killers]
    bad += [f"control {name} is not exactly one test" for name in unresolved_tests(c for m in mutations for c in controls_of(m, controls))]
    return bad


def unresolved_killers(mutations) -> list[str]:
    """Killer names that do not resolve to exactly one test of that name."""
    return unresolved_tests(k for m in mutations for k in m.killers)


def unresolved_tests(names) -> list[str]:
    """Test names that do not resolve to exactly one test of that name."""
    def ids(suite):
        for test in suite:
            yield from ids(test) if isinstance(test, unittest.TestSuite) else [test.id()]
    bad = []
    for name in sorted(set(names)):
        try:
            found = list(ids(killer_suite([name])))
        except (ImportError, AttributeError) as exc:
            found = [repr(exc)]
        if found != [name]:
            bad.append(name)
    return bad


def run(fx, ddl: str, connection: str, killers=None) -> _Collector:
    """The store tests over this DDL and connection text: the named killers,
    or (killers None) the whole store suite."""
    fx.DDL_TEXT, fx.CONNECTION_TEXT = ddl, connection
    result = _Collector()
    (load_suite() if killers is None else killer_suite(killers)).run(result)
    return result


_FX = None  # the fixtures module, bound in main() before workers fork


DISK = True  # --no-disk clears it (module docstring, "Children")
CHILD_ROOT = "GEN2_CHILD_ROOT"  # gen2/tests/children.py ROOT_VARIABLE
ATTEST_FILE, ATTEST_TEST = "GEN2_ATTEST_FILE", "GEN2_ATTEST_TEST"
PROLOGUE = ('(lambda os, json, hashlib: os.environ.get("GEN2_ATTEST_FILE") and open(os.environ["GEN2_ATTEST_FILE"], "a").write(json.dumps('
            '{"test": os.environ.get("GEN2_ATTEST_TEST"), "pid": os.getpid(), "file": __file__, '
            '"sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest()}) + "\\n"))(__import__("os"), __import__("json"), __import__("hashlib"))'
            '  # gen2_mutations attestation\n')


def attested(text: str) -> str:
    """The mutant as written into the child tree: its prologue placed after
    the module docstring and any __future__ imports (which must stay first)."""
    import ast

    body, line = ast.parse(text).body, 0
    for node in body:
        docstring = node is body[0] and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        if docstring or (isinstance(node, ast.ImportFrom) and node.module == "__future__"):
            line = node.end_lineno
        else:
            break
    lines = text.splitlines(keepends=True)
    return "".join(lines[:line]) + PROLOGUE + "".join(lines[line:])


def attestations(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _child_tree(tmp: str) -> Path:
    """A copy of the gen2/ package that children import instead of the
    repository's (no bytecode, so nothing compiled from the original is
    reused)."""
    import shutil

    tree = Path(tmp) / "tree"
    shutil.copytree(ROOT / "gen2", tree / "gen2", ignore=shutil.ignore_patterns("__pycache__"))
    return tree


def _loading_control(tree: Path, m: Mutation, text: str) -> None:
    """Before the killers: a child started through gen2/tests/children.py, as
    the killers start theirs, must execute exactly the mutant's bytes — for a
    module target, a probe child imports it and must attest them; a disk
    target (a script only children run) must be the tree's copy, and is
    attested on the killers' own children (_evaluate). Otherwise its kills
    would not be about this mutant (ValueError: INVALID)."""
    from gen2.tests import children

    how, expected = FILE_TARGETS[m.target], hashlib.sha256(text.encode("utf-8")).hexdigest()
    if how[0] == "module":
        record = Path(os.environ[ATTEST_FILE])
        before = len(attestations(record))
        os.environ[ATTEST_TEST] = "loading-control"
        probe = children.python(["-c", f"import {how[1]}"], capture_output=True, text=True, timeout=60)
        attested_now = attestations(record)[before:]
        if probe.returncode != 0 or not any(a["sha256"] == expected and Path(a["file"]).resolve().is_relative_to(tree.resolve()) for a in attested_now):
            raise ValueError(f"loading control: a probe child did not attest the mutant in {tree} (exit {probe.returncode}, attested {attested_now})")
        return
    loaded = children.path(m.target)
    if not loaded.resolve().is_relative_to(tree.resolve()) or loaded.read_text(encoding="utf-8") != text:
        raise ValueError(f"loading control: a child runs {loaded}, not the mutant in {tree}")


def _run_file_mutation(m: Mutation) -> _Collector:
    """Mutate a Python/config file into a temp copy, point the killers' test
    modules at it, run just those modules. Runs in a forked worker (or at the
    end of a serial run), so module state it changes is not reused."""
    import importlib
    import tempfile
    import types

    text = mutate((ROOT / m.target).read_text(encoding="utf-8"), m)
    how = FILE_TARGETS[m.target]
    names = (*m.killers, *controls_of(m))
    modules = sorted({k.split(".")[0] for k in names})
    with tempfile.TemporaryDirectory() as tmp, _child_root(tmp, m, text) as tree:
        if how[0] == "disk":
            loaded = [importlib.import_module(name) for name in modules]
        elif how[0] == "attr":
            path = Path(tmp) / Path(m.target).name
            path.write_text(text, encoding="utf-8")
            loaded = [importlib.import_module(name) for name in modules]
            setattr(importlib.import_module(how[1]), how[2], path)
        else:
            mutant = types.ModuleType(how[1])
            mutant.__file__ = str((tree or ROOT) / m.target)  # file-relative paths (a script it starts) resolve in the child tree
            exec(compile(text, str(ROOT / m.target), "exec"), mutant.__dict__)
            sys.modules[how[1]] = mutant
            parent, _, leaf = how[1].rpartition(".")
            setattr(importlib.import_module(parent), leaf, mutant)
            for dependent in how[2:]:  # modules that bound names from the mutated one at import
                importlib.reload(importlib.import_module(dependent))
            loaded = [importlib.reload(importlib.import_module(name)) for name in modules]
        suite = killer_suite(names, {mod.__name__: mod for mod in loaded})
        result = _Collector()
        suite.run(result)
        if tree is not None:
            result.tree, result.expected = tree, hashlib.sha256((tree / m.target).read_bytes()).hexdigest()
            result.attestations = attestations(Path(tmp) / "attest.jsonl")
        return result


class _child_root:
    """For a module or disk target (with DISK on): the child tree with the
    mutant written in, named in GEN2_CHILD_ROOT and checked by the loading
    control; restored on exit (a serial run reuses this process). Yields the
    tree, or None when children are not redirected."""

    def __init__(self, tmp: str, m: Mutation, text: str | None) -> None:
        self.tmp, self.m, self.text = tmp, m, text

    def __enter__(self) -> Path | None:
        self.saved = {name: os.environ.get(name) for name in (CHILD_ROOT, ATTEST_FILE, ATTEST_TEST)}
        if not DISK or FILE_TARGETS[self.m.target][0] == "attr":
            return None
        tree = _child_tree(self.tmp)
        os.environ[CHILD_ROOT] = str(tree)
        os.environ[ATTEST_FILE] = str(Path(self.tmp) / "attest.jsonl")
        if self.text is not None:
            text = attested(self.text) if self.m.target.endswith(".py") else self.text
            (tree / self.m.target).write_text(text, encoding="utf-8")
            _loading_control(tree, self.m, text)
        return tree

    def __exit__(self, *exc) -> None:
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _run_file_mutation_unmutated(m: Mutation) -> _Collector:
    """The killers against the file as it is (a mutation that finds its text
    is only meaningful if they pass unmutated), in the loading mode its
    mutants use: a module or disk target over an unmutated child tree (one
    run covers every such target, main()); an "attr" target from an
    unmodified temp copy, exactly as its mutants are, so a file that only
    works from its own location (an import resolved relative to itself)
    fails here instead of letting every mutant "die" of it."""
    import importlib
    import tempfile

    modules = sorted({k.split(".")[0] for k in m.killers})
    how = FILE_TARGETS[m.target]
    with tempfile.TemporaryDirectory() as tmp, _child_root(tmp, m, None):  # children run from an unmutated copy, as the mutants' do
        loaded = [importlib.import_module(name) for name in modules]
        if how[0] == "attr":
            path = Path(tmp) / Path(m.target).name
            path.write_text((ROOT / m.target).read_text(encoding="utf-8"), encoding="utf-8")
            holder = importlib.import_module(how[1])
            original = getattr(holder, how[2])
            setattr(holder, how[2], path)
        try:
            suite = killer_suite(m.killers, {mod.__name__: mod for mod in loaded})
            result = _Collector()
            suite.run(result)
        finally:
            if how[0] == "attr":
                setattr(holder, how[2], original)
    return result


def judge_children(m: Mutation, attested: list[dict], tree: Path, expected: str, own_pid: int, controls: tuple[str, ...] = ()) -> str | None:
    """Why the killers' children do not support this mutant's kills, or None
    (module docstring, "Children"): a child that executed other bytes of the
    target, or — for a kill that rests on a child — a declared killer with no
    child that executed the mutant during it; for a disk target, whose mutant
    only children run, a paired control with none either (it would pass
    without meeting the mutant)."""
    children = [a for a in attested if a["pid"] != own_pid]
    foreign = [a for a in children if a["sha256"] != expected or not Path(a["file"]).resolve().is_relative_to(tree.resolve())]
    if foreign:
        return f"a child executed other bytes than the mutant: {foreign[0]}"
    ran_it = lambda name: any(a["test"] and _named(a["test"], name) for a in children)
    if m.via_child or FILE_TARGETS[m.target][0] == "disk":
        unattested = [k for k in m.killers if not ran_it(k)]
        if unattested:
            return f"killer(s) with no child that executed the mutant: {unattested}"
    if FILE_TARGETS[m.target][0] == "disk":
        unattested = [c for c in controls if not ran_it(c)]
        if unattested:
            return f"paired control(s) with no child that executed the mutant: {unattested}"
    return None


def _named(test_id: str, name: str) -> bool:
    return test_id == name or test_id.endswith("." + name)


def verdict(m: Mutation, res: _Collector, controls: tuple[str, ...], own_pid: int | None = None) -> str:
    """The verdict on one mutant from what its killers and its paired
    controls did under it (module docstring)."""
    missing = [k for k in m.killers if not any(_named(f, k) for f in res.failed)]
    if res.tree is not None:
        refused = judge_children(m, res.attestations, res.tree, res.expected, os.getpid() if own_pid is None else own_pid, controls)
        if refused:
            return f"INVALID   {m.mid}: {refused}"
    broken = [c for c in controls if not any(_named(t, c) for t in res.ran) or any(_named(t, c) for t in (*res.failed, *res.errored, *res.skipped))]
    if broken:
        return f"INVALID   {m.mid}: paired control(s) did not pass under the mutant: {broken}"
    if res.errored and (missing or not m.killers):
        return f"INVALID   {m.mid}: {len(res.errored)} test error(s), e.g. {next(iter(res.errored.items()))}"
    if not res.failed:
        return f"SURVIVED  {m.mid}: {m.description}"
    if missing:
        return f"INVALID   {m.mid}: listed killer(s) did not fail: {missing}"
    note = f" ({len(res.errored)} other test(s) errored in setup: the mutant also breaks a shared fixture)" if res.errored else ""
    return f"KILLED    {m.mid} by {len(res.failed)} test(s), {len(controls)} paired control(s) passing{note}"


def _evaluate(m: Mutation) -> str:
    fx = _FX
    ddl0, conn0 = fx.DDL_TEXT, fx.CONNECTION_TEXT
    try:
        if m.target in FILE_TARGETS:
            res = _run_file_mutation(m)
        else:
            ddl = mutate(ddl0, m) if m.target == "ddl" else ddl0
            conn = mutate(conn0, m) if m.target == "connection" else conn0
            try:
                res = run(fx, ddl, conn, (*m.killers, *controls_of(m)))
            finally:
                fx.DDL_TEXT, fx.CONNECTION_TEXT = ddl0, conn0
    except ValueError as exc:
        return f"INVALID   {m.mid}: {exc}"
    return verdict(m, res, controls_of(m))


def main(argv: list[str] | None = None) -> int:
    global _FX
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="run only mutations whose id starts with this prefix (several: comma-separated)")
    parser.add_argument("--list", action="store_true", help="print the inventory and exit")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1),
                        help="worker processes (default: one fewer than the cores, one left for the killers' children)")
    parser.add_argument("--no-disk", action="store_true", help="swap modules in memory only; children import the unmutated tree (shows the 1b gap)")
    args = parser.parse_args(argv)
    global DISK
    DISK = not args.no_disk
    if args.list:
        for m in MUTATIONS:
            print(f"{m.mid:45} {m.finding:6} {m.description}")
        for guard, reason in SECOND_LAYER.items():
            print(f"second layer (not independently killable): {guard}\n    first layer: {reason}")
        return 0
    sys.path[:0] = [str(TESTS), str(ROOT)]
    os.environ["GEN2_TEST_EVIDENCE"] = "off"  # mutants fail tests on purpose: no failure evidence is kept (gen2/tests/supervisor_fixtures.py)
    import gen2.tests.store_fixtures as fx  # noqa: E402 (path set above)

    ddl0, conn0 = fx.DDL_TEXT, fx.CONNECTION_TEXT
    started = time.monotonic()
    base = run(fx, ddl0, conn0)
    if base.failed or base.errored or not base.testsRun:
        print(f"BASELINE NOT GREEN: failed={sorted(base.failed)} errored={base.errored}", file=sys.stderr)
        return 1
    selected = [m for m in MUTATIONS if not args.only or m.mid.startswith(tuple(args.only.split(",")))]
    unresolved = unresolved_killers(selected)
    if unresolved:
        print(f"UNRESOLVED KILLERS (no single test of that name): {unresolved}", file=sys.stderr)
        return 1
    global _CONTROLS
    _CONTROLS = load_controls()
    problems = control_problems(selected, _CONTROLS)
    if problems:
        print(f"PAIRED CONTROLS NOT RUNNABLE (tools/gen2_mutation_controls.py writes them): {problems}", file=sys.stderr)
        return 1
    tested = lambda m: (*m.killers, *controls_of(m))
    tree_targets = sorted({m.target for m in selected if FILE_TARGETS.get(m.target, ("",))[0] in ("module", "disk")})
    baselines = [Mutation("baseline", "-", "unmutated", tuple(k for m in selected if m.target in tree_targets for k in tested(m)), target=tree_targets[0])] \
        if tree_targets else []  # one unmutated child tree covers every module and disk target: the same loading mode
    baselines += [Mutation("baseline", "-", "unmutated", tuple(k for m in selected if m.target == target for k in tested(m)), target=target)
                  for target in sorted({m.target for m in selected if FILE_TARGETS.get(m.target, ("",))[0] == "attr"})]
    for clean in baselines:
        res = _run_file_mutation_unmutated(clean)
        if res.failed or res.errored:
            print(f"BASELINE NOT GREEN ({clean.target if FILE_TARGETS[clean.target][0] == 'attr' else 'the child tree'}): "
                  f"failed={sorted(res.failed)} errored={res.errored}", file=sys.stderr)
            return 1
    held = [m.mid for m in selected if not controls_of(m) and (_CONTROLS.get(m.mid) or {}).get("in_killer")]
    unpaired = [m.mid for m in selected if not controls_of(m) and m.mid not in held]
    print(f"gen2 mutation run: baselines green ({base.testsRun} store tests; {len(baselines)} file-target baseline(s)); "
          f"{len(selected)} mutants on {args.jobs} worker(s); {len(selected) - len(held) - len(unpaired)} with paired controls, "
          f"{len(held)} whose killer holds its accepted case, {len(unpaired)} with neither (reasons in {CONTROLS_FILE.name}): {unpaired}", flush=True)
    ids = [m.mid for m in MUTATIONS]
    if len(set(ids)) != len(ids):
        print("duplicate mutation ids", file=sys.stderr)
        return 1
    missing = uncovered_triggers(ddl0)
    if missing and not args.only:
        print(f"UNCOVERED TRIGGERS (add a mutant or document a second layer): {missing}", file=sys.stderr)
        return 1
    _FX = fx
    bad = 0

    paired = 0

    def report(verdict: str) -> None:  # as each worker finishes
        nonlocal bad, paired
        bad += not verdict.startswith("KILLED")
        paired += verdict.startswith("KILLED") and ", 0 paired control(s)" not in verdict
        print(verdict, flush=True)
    if args.jobs > 1 and len(selected) > 1:
        with multiprocessing.get_context("fork").Pool(args.jobs, maxtasksperchild=1) as pool:
            for verdict in pool.imap_unordered(_evaluate, selected, chunksize=1):
                report(verdict)
    else:
        for m in [m for m in selected if m.target not in FILE_TARGETS] + [m for m in selected if m.target in FILE_TARGETS]:  # file targets may rebind modules: last
            report(_evaluate(m))
    coverage = "" if args.only else f"every DDL trigger covered (second layers: {len(SECOND_LAYER_TRIGGERS)}), "
    print(f"gen2 mutation run: {len(selected) - bad}/{len(selected)} killed, {paired} of them with paired controls passing, "
          f"baseline {base.testsRun} tests green, {coverage}{time.monotonic() - started:.1f}s")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
