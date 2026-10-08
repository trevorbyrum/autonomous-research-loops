"""The mutation record and the names the inventory's families share: test
module and class prefixes (a killer is prefix + test), target paths, and a
few value tables. Moved verbatim from tools/gen2_mutations.py (task 2r).
"""
from __future__ import annotations

from dataclasses import dataclass


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


H = "test_store_history."
DI, DE, DX, DK = "test_store_ddl_invocations.", "test_store_ddl_evidence.", "test_store_ddl_export.", "test_store_ddl_contracts."  # task 2r: test_store_ddl.py by concern
FI = "test_store_ddl_contracts.FacetImportanceTest."
AD = "test_store_ddl_invocations.AdmissionAndLeaseTest."
IL = "test_store_ddl_invocations.InvocationLifecycleTest."
VT = "test_store_ddl_evidence.VerificationTest."
CS = "test_store_ddl_evidence.ContractAdmittedSupportTest."
LT = "test_store_ddl_invocations.InvocationLifecycleTest."
DC = "test_store_ddl_evidence.DecisionReceiptConsistencyTest."
SD = "test_store_ddl_evidence.ScreeningAndDecisionTest."
OB = "test_store_ddl_evidence.ObservationTest."
VO = "test_store_ddl_contracts.DraftVocabularyTransitionTest."
CB = "test_check_boundaries.BoundaryCheckerTest."
DR = "test_check_ddl_rules.DdlRuleTest."
IN = "test_instants.UtcInstantTest."
CN = "test_canonical."
RI = "test_store_history.RecordIdentityTest."
EX = "test_store_examples.ExampleWorldTest."
CG = "test_store_ddl_contracts.ContractGovernanceTest."
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
EVW = "gen2/router/evidence_writer.py"
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
# task 1e: the operator surface
OPA, OPS, OPT, RST, ENG, CLI = "gen2/operator/auth.py", "gen2/operator/service.py", "gen2/operator/status.py", "gen2/router/status.py", "gen2/app/engine.py", "gen2/app/cli.py"
OAU, OAZ, OAF, OBD, OCR, OHL, OSE = ("test_operator_auth.AuthenticationTest.", "test_operator_auth.AuthorizationTest.", "test_operator_auth.AuthorityFieldTest.",
                                     "test_operator_auth.BodyTest.", "test_operator_auth.CredentialsTest.", "test_operator_auth.HealthTest.",
                                     "test_operator_auth.SecrecyTest.")
OTW, OIW, OEW, ORO = ("test_operator_status.TopicWaitingTest.", "test_operator_status.InvocationWaitingTest.", "test_operator_status.EngineWideTest.",
                      "test_operator_status.ReadOnlyTest.")
OCM, OCL, OMC = "test_operator_commands.", "test_operator_restart.CliTest.", "test_operator_mcp.McpTest."
# task 1e-repair (Astra 1e review findings 2-8)
ORC, ORD, OHI = "test_operator_recovery.DiscoveryRecoveryTest.", "test_operator_recovery.DelegateRecoveryTest.", "test_operator_status.HistoricalIncidentTest."
OEN, ODS, OUB = "test_operator_mcp.McpEnvelopeTest.", "test_operator_auth.DiagnosticSecrecyTest.", "test_operator_auth.UnreadBodyTest."
OCT, ORP = "test_operator_restart.CliTransportTest.", "test_operator_restart.ReplacementTest."
# task 1e-repair-2 (Astra 1e-repair re-review findings 1-3)
ORR, OCF = "test_operator_recovery.ResearchPassReplacedRecoveryTest.", "test_operator_auth.CarriedFormsTest."
# task 1f: capability probes
CAPS, PRB = "gen2/router/capabilities.py", "gen2/supervisor/probe.py"
CPR, CPN, CPE = "test_capability_probe.ProbeRecordTest.", "test_capability_probe.ProbeRunTest.", "test_capability_probe.EngineProbeTest."
CPD = "test_capability_probe.DeclaredExpiryTest."
# task 2a: the workflow write paths
WTP, WBI, WCD, WWR = "test_router_workflow.TopicTest.", "test_router_workflow.BriefIntakeTest.", "test_router_workflow.ContractDraftTest.", "test_router_workflow.WorkRegistrationTest."
WCL, WSC, WSG, WRC = ("test_router_workflow.ClaimSourceLinkTest.", "test_router_workflow.ScopingClaimLinkTest.", "test_router_workflow.SignalTest.",
                      "test_router_workflow.ReviewClosureTest.")
# task 2a's expansion (Astra's Phase 2 plan audit, findings 4 and 8)
WSR, WSD, WSP, WRF, WTR = ("test_router_workflow.ScopingReportTest.", "test_router_workflow.ScopeDecisionTest.", "test_router_workflow.SourceProposalTest.",
                           "test_router_workflow.ReferentialCheckTest.", "test_router_workflow.TemplateRegistryTest.")
SWR, SWP = "test_store_workflow.ScopingReportTest.", "test_store_workflow.SourceProposalTest."
WBS = "test_router_workflow.BriefStandingTest."  # task 2a-repair F1
WBB, IBR = "test_router_brief_basis.BriefBasisTest.", "test_store_intake.BriefReplacementTest."  # task 2a-repair-3
LCT, SZ = "tools/gen2_linecount.py", "test_size_rules.SizeRuleTest."  # task 2r: the size rules
RECEIPT = "gen2/schema/export-delivery-receipt.schema.json"
MANIFEST = "gen2/schema/export-manifest.schema.json"
ENVELOPE = "gen2/schema/freshness-envelope.schema.json"
IDENTITY = ("job_handle", "host_id", "container_id", "boot_id", "start_fingerprint")
IDENTITY_KILLER = {  # each identity member's own one-error negative (0c-repair-2)
    "host_id": "test_a_process_identity_without_its_host_is_refused",
    "boot_id": "test_a_process_identity_without_its_boot_id_is_refused",
    "start_fingerprint": "test_a_process_identity_without_its_start_fingerprint_is_refused",
}
