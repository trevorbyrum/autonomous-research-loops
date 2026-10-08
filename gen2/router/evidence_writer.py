"""The evidence and governance rows of one commit: `_write_evidence` and the five helpers task 2q-b9 split out of it, moved here by task 2q-b10. A collaborator of
service.Router ("Router composition", BOUNDARIES.md). It runs inside the transaction `_commit_in_transaction` already holds (the core's `_guarded`: BEGIN IMMEDIATE, the
clock read once the lock is held, rollback and refusal as before) and opens no transaction and reads no clock of its own: the instant, the committing invocation and
operation, the checked payload and the commit's new triggers and outbox events are passed in.

Trace: BOUNDARIES.md Router ("write through any path other than its own transactions"); INVARIANTS V-10, RG-5, G-12 (producer, verifier, recorder and signal source are
the committing invocation and operation, never a document field), and the ones the moved code's own comments name.
"""
from __future__ import annotations

from typing import Mapping, Protocol

from gen2.core import canonical
from gen2.router.boundary import Refusal


class Rows(Protocol):
    """The router's store as the evidence writer uses it (store/api.py Store): inside the transaction the core holds."""
    def select(self, table: str, where: Mapping[str, object] | None = None) -> list[dict]: ...
    def insert(self, table: str, row: Mapping[str, object]) -> None: ...
    def update(self, table: str, key: Mapping[str, object], changes: Mapping[str, object]) -> None: ...


class EvidenceCore(Protocol):
    """What the evidence writer takes of the router core, and nothing else; service.Router implements it without inheriting it. Every member is the core's own
    (service.py; `_pin_status` is its delegate to amendments.py), so no comment names another owner."""
    _store: Rows
    def _one(self, table: str, where: Mapping[str, object]) -> dict | None: ...
    def _pin_status(self, inv: dict) -> str: ...
    def _work_of_topic(self, work_id: str, topic_id: str) -> bool: ...


class EvidenceWriter:
    def __init__(self, core: EvidenceCore) -> None:
        self._core = core

    def _write_evidence(self, env: dict, inv: dict, checked: dict, now: str, new_triggers: list, outbox: list) -> dict:
        """The evidence and governance rows of one commit. Producer, verifier,
        recorder and signal source are the committing invocation and
        operation — never a document field (V-10, RG-5, G-12)."""
        payload, op_id, topic_id = checked["payload"], env["operation_id"], inv["topic_id"]
        claims = self._write_claims(payload, topic_id, inv, now)
        for hold in payload["holds"]:
            self._core._store.insert("holds", {**hold, "topic_id": topic_id, "created_at": now, "created_by_operation_id": op_id})
        for doc in payload["verification_receipts"]:
            self._core._store.insert("verification_receipts", {
                "verification_receipt_id": doc["verification_receipt_id"], "topic_id": doc["topic_id"], "claim_id": doc["claim"]["claim_id"],
                "claim_revision": doc["claim"]["claim_revision"], "work_id": doc["source"]["work_id"], "source_version": doc["source"]["source_version"],
                "cited_spans": doc["cited_spans"], "obtained_content_hash": doc["obtained_content_hash"], "access_tier": doc["access_tier"],
                "use": doc["requested_for"]["use"], "required_access_tier": doc["requested_for"]["required_access_tier"], "acquisition": doc["acquisition"],
                "extraction_method": doc["extraction"]["method"], "extraction_invocation_id": doc["extraction"]["produced_by_invocation_id"],
                "extraction_validation_ref": doc["extraction"]["validation_ref"], "producer_invocation_id": doc["producer_invocation_id"],
                "verifier_invocation_id": doc["verifier_invocation_id"], "quote_check_id": doc["quote_check_id"], "verdict": doc["verdict"],
                "receipt": doc, "verified_at": doc["verified_at"]})
        for doc in payload["decision_receipts"]:
            response, outcome = doc["provider_response"], doc["outcome"]
            self._core._store.insert("decision_receipts", {
                "decision_receipt_id": doc["decision_receipt_id"], "invocation_id": doc["invocation_id"], "topic_id": doc["topic_id"],
                "spec_hash": doc["spec"]["spec_hash"], "decision_class": doc["decision_class"], "provider": doc["provider"],
                "input_status": doc["input_manifest"]["input_status"], "response_status": response["status"],
                "raw_response_digest": response["raw_response_digest"], "answer": response["answer"], "subject_kind": doc["subject"]["kind"],
                "subject_ref": doc["subject"]["ref"], "policy_id": doc["policy"]["policy_id"], "policy_version": doc["policy"]["version"],
                "authority_level": doc["authorization"]["authority_level"], "qualification_ref": doc["authorization"]["qualification_ref"],
                "action": doc["action"], "commit_operation_id": outcome["commit_operation_id"], "hold_id": outcome["hold_id"],
                "proposal_ref": outcome["proposal_ref"], "blind_sample": doc["blind_sample"]["selected"], "receipt": doc, "decided_at": doc["decided_at"]})
        for assessment in payload["screening_assessments"]:
            contract = self._core._one("contract_revisions", {"topic_id": topic_id, "revision": inv["contract_revision"]})
            self._core._store.insert("screening_assessments", {
                **{k: assessment[k] for k in ("assessment_id", "work_id", "stage", "decision", "reason_code", "criterion_results", "actor_kind",
                                              "decision_receipt_id", "supersedes_assessment_id")},
                "topic_id": topic_id, "contract_revision": inv["contract_revision"], "framing_version": contract["framing_version"],
                "eligibility_protocol_version": checked["protocol"]["protocol_version"], "invocation_id": inv["invocation_id"],
                "operator_decision_id": None, "recorded_by_operation_id": op_id, "created_at": now})
        promotions, links = self._promote_and_link_claims(payload, topic_id, inv, now)
        self._write_scoping_reports(payload, topic_id, inv, op_id, now)
        self._write_source_proposals(payload, topic_id, inv, op_id, now)
        for identity, trigger in new_triggers:
            self._core._store.insert("review_triggers", {"trigger_identity": identity, "topic_id": topic_id, "reason_code": trigger["reason_code"],
                                                         "signal_source": "primary_observation", "cause_ref": trigger["cause_ref"],
                                                         "observed_at": trigger["observed_at"], "recorded_by_operation_id": op_id})
        self._close_review_episodes(payload, topic_id, inv, op_id, now)
        for outbox_id, manifest, manifest_hash in outbox:
            supersedes = manifest["supersedes"] or {}
            self._core._store.insert("outbox_events", {
                "outbox_event_id": outbox_id, "topic_id": topic_id, "manifest_id": manifest["manifest_id"], "manifest_hash": manifest_hash,
                "artifact_kind": manifest["artifact_kind"], "generation": manifest["generation"], "options_revision": manifest["options_revision"],
                "supersedes_generation": supersedes.get("generation"), "supersedes_options_revision": supersedes.get("options_revision"),
                "source_revision": manifest["source"]["revision"], "source_content_hash": manifest["source"]["content_hash"],
                "approval_decision_id": manifest["approval"]["operator_decision_id"], "bundle_content_hash": manifest["bundle"]["content_hash"],
                "expected_connectors": manifest["expected_connectors"], "manifest": manifest, "committed_by_operation_id": op_id, "created_at": now})
        return {"claims": claims, "claim_promotions": promotions, "claim_source_links": links,
                "scoping_reports": [[r["report_id"], r["version"]] for r in payload["scoping_reports"]],
                "source_proposals": [p["proposal_id"] for p in payload["source_proposals"]],
                "review_closures": [c["episode_id"] for c in payload["review_closures"]],
                "verification_receipts": [d["verification_receipt_id"] for d in payload["verification_receipts"]],
                "screening_assessments": [a["assessment_id"] for a in payload["screening_assessments"]],
                "artifacts": sorted(checked["artifacts"])}

    def _write_claims(self, payload: dict, topic_id: str, inv: dict, now: str) -> list:
        claims = []
        for claim in payload["claims"]:
            prior = self._core._store.select("claims", {"claim_id": claim["claim_id"]})
            if any(row["topic_id"] != topic_id for row in prior):
                raise Refusal("cross_topic", f"{claim['claim_id']} is another topic's claim")
            if claim["revision"] != max((row["revision"] for row in prior), default=0) + 1:
                raise Refusal("payload_invalid", f"{claim['claim_id']}: the next revision is {len(prior) + 1}")
            self._core._store.insert("claims", {"claim_id": claim["claim_id"], "revision": claim["revision"], "topic_id": topic_id,
                                                "text_ref": claim["text_ref"]["content_hash"], "producer_invocation_id": inv["invocation_id"],
                                                "load_bearing": claim["load_bearing"], "required_access_tier": claim["required_access_tier"],
                                                "status": "provisional", "created_at": now})
            claims.append([claim["claim_id"], claim["revision"]])
        return claims

    def _promote_and_link_claims(self, payload: dict, topic_id: str, inv: dict, now: str) -> tuple[list, list]:
        promotions = []
        for promotion in payload["claim_promotions"]:
            row = self._core._one("claims", {"claim_id": promotion["claim_id"], "revision": promotion["revision"]})
            if row is None:
                raise Refusal("payload_invalid", f"{promotion['claim_id']} revision {promotion['revision']} is not recorded")
            if row["topic_id"] != topic_id:
                raise Refusal("cross_topic", f"{promotion['claim_id']} is another topic's claim")
            if row["status"] not in ("provisional", "contested"):
                raise Refusal("payload_invalid", f"{promotion['claim_id']} revision {promotion['revision']} is {row['status']}")
            producer = self._core._one("invocations", {"invocation_id": row["producer_invocation_id"]})
            if producer["admission_context"] == "contract/1" and self._core._pin_status(producer) not in ("current", "compatible"):
                raise Refusal("amendment_pending", f"{promotion['claim_id']} revision {promotion['revision']} was produced under a revision an amendment made "
                                                   "incompatible; contract-admitted work adopts it as a new revision (V-10, G-1)")
            self._core._store.update("claims", {"claim_id": promotion["claim_id"], "revision": promotion["revision"]}, {"status": "accepted_support"})
            promotions.append([promotion["claim_id"], promotion["revision"]])
        links = []
        for link in payload["claim_source_links"]:  # task 2a: the claim's admission (C-12) and the topic's own retrieval of the work (C-9's rule)
            claim, what = self._core._one("claims", {"claim_id": link["claim_id"], "revision": link["claim_revision"]}), f"{link['claim_id']} revision {link['claim_revision']}"
            if claim is None:
                raise Refusal("payload_invalid", f"{what} is not recorded")
            if claim["topic_id"] != topic_id:
                raise Refusal("cross_topic", f"{what} is another topic's claim")
            if self._core._one("invocations", {"invocation_id": claim["producer_invocation_id"]})["contract_revision"] != inv["contract_revision"]:
                raise Refusal("payload_invalid", f"{what} was not produced by work admitted under contract revision {inv['contract_revision']}, "
                                                 "whose obligation the link names (C-12)")
            if self._core._one("obligations", {"topic_id": topic_id, "contract_revision": inv["contract_revision"], "obligation_id": link["obligation_id"]}) is None:
                raise Refusal("payload_invalid", f"{link['obligation_id']} is not an obligation of contract revision {inv['contract_revision']}")
            if not self._core._work_of_topic(link["work_id"], topic_id):
                raise Refusal("cross_topic" if self._core._one("works", {"work_id": link["work_id"]}) else "payload_invalid",
                              f"no record {topic_id} retrieved is linked to {link['work_id']}: a work's row is not the topic's authorization to cite it")
            self._core._store.insert("claim_source_links", {**link, "topic_id": topic_id, "contract_revision": inv["contract_revision"], "created_at": now})
            links.append([link["claim_id"], link["claim_revision"], link["work_id"], link["obligation_id"]])
        return promotions, links

    def _write_scoping_reports(self, payload: dict, topic_id: str, inv: dict, op_id: str, now: str) -> None:
        for report in payload["scoping_reports"]:  # task 2a: the next version of its report, each coverage fact the cited observations' own (RG-4)
            key = {"topic_id": topic_id, "report_id": report["report_id"]}
            latest = max((r["version"] for r in self._core._store.select("scoping_reports", key)), default=None)
            if (report["version"], report["parent_version"]) != ((1, None) if latest is None else (latest + 1, latest)):
                raise Refusal("payload_invalid", f"{report['report_id']}: the next version is {1 if latest is None else latest + 1}, with parent {latest}")
            for fact in report["coverage"]:
                observed = [self._core._one("search_observations", {"observation_id": o}) for o in fact["observation_ids"]]
                if any(o is None or (o["topic_id"], o["lane"], o["coverage_state"]) != (topic_id, fact["lane"], fact["coverage_state"]) for o in observed):
                    raise Refusal("payload_invalid", f"{report['report_id']}: {fact['lane']} {fact['coverage_state']} is not what the cited observations of {topic_id} recorded")
            self._core._store.insert("scoping_reports", {**key, "version": report["version"], "parent_version": report["parent_version"], "content_hash": report["content_hash"],
                                                         "document": report, "brief_id": report["brief"]["brief_id"], "brief_version": report["brief"]["version"],
                                                         "brief_hash": report["brief"]["content_hash"], "invocation_id": inv["invocation_id"],
                                                         "committed_by_operation_id": op_id, "created_at": now})

    def _write_source_proposals(self, payload: dict, topic_id: str, inv: dict, op_id: str, now: str) -> None:
        for proposal in payload["source_proposals"]:  # task 2a: retained, authorizing nothing (SOURCE-GOVERNANCE.md step 1)
            blocked = proposal["motivation"]["blocked_obligation_ids"]
            if inv["admission_context"] == "contract/1" and any(self._core._one("obligations", {"topic_id": topic_id, "contract_revision": inv["contract_revision"],
                                                                                                  "obligation_id": o}) is None for o in blocked):
                raise Refusal("payload_invalid", f"{proposal['proposal_id']} names a blocked obligation contract revision {inv['contract_revision']} lacks")
            superseded = proposal.get("supersedes_proposal_id")
            if superseded is not None and self._core._one("source_proposals", {"proposal_id": superseded}) is None:
                raise Refusal("payload_invalid", f"{proposal['proposal_id']} supersedes {superseded}, which is not recorded")
            self._core._store.insert("source_proposals", {"proposal_id": proposal["proposal_id"], "topic_id": topic_id, "content_hash": canonical.logical_hash(proposal),
                                                          "document": proposal, "proposed_by_invocation_id": inv["invocation_id"], "committed_by_operation_id": op_id,
                                                          "supersedes_proposal_id": superseded, "created_at": now})

    def _close_review_episodes(self, payload: dict, topic_id: str, inv: dict, op_id: str, now: str) -> None:
        for closure in payload["review_closures"]:  # task 2a: the checkpoint closes an episode opened for it to review, its triggers handled (S5, RG-1b(e))
            episode = self._core._one("review_episodes", {"episode_id": closure["episode_id"]})
            if episode is None or episode["topic_id"] != topic_id:
                raise Refusal("cross_topic" if episode else "payload_invalid", f"{closure['episode_id']} is not a review episode of {topic_id}")
            if episode["closed_at"] is not None:
                raise Refusal("payload_invalid", f"{closure['episode_id']} was closed by {episode['closed_by_operation_id']}")
            if self._core._one("leases", {"lease_id": inv["lease_id"]})["generation"] <= episode["opened_after_generation"]:  # commit order, not wall time (2a-repair F2)
                raise Refusal("payload_invalid", f"{closure['episode_id']} opened after {inv['invocation_id']} was admitted: a checkpoint closes only an "
                                                 "episode it was admitted to review, so no signal is marked handled unreviewed (G-12)")
            self._core._store.update("review_episodes", {"episode_id": closure["episode_id"]}, {"closed_at": now, "closed_by_operation_id": op_id})
            for trigger in self._core._store.select("review_triggers", {"episode_id": closure["episode_id"]}):
                self._core._store.update("review_triggers", {"trigger_identity": trigger["trigger_identity"]}, {"handled_at": now})
