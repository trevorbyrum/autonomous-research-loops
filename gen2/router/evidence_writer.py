"""The evidence and governance rows of one commit: `_write_evidence` and the five helpers task 2q-b9 split out of it, moved here by task 2q-b10. A collaborator of
service.Router ("Router composition", BOUNDARIES.md). Its writes run inside the transaction `_commit_in_transaction` already holds (the core's `_guarded`: BEGIN IMMEDIATE, the
clock read once the lock is held, rollback and refusal as before) and opens no transaction and reads no clock of its own: the instant, the committing invocation and
operation, the checked payload and the commit's new triggers and outbox events are passed in. Validation helpers run before that transaction; `check_quotes` reads
authenticated source bytes and computes the pure matcher result outside the writer lock (V-6, C-8).

Trace: BOUNDARIES.md Router ("write through any path other than its own transactions"); INVARIANTS V-10, RG-5, G-12 (producer, verifier, recorder and signal source are
the committing invocation and operation, never a document field), and the ones the moved code's own comments name.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Callable, Mapping, Protocol

from gen2.core import canonical
from gen2.router import boundary, quote_matching
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
    _spool: object
    def _one(self, table: str, where: Mapping[str, object]) -> dict | None: ...
    def _pin_status(self, inv: dict) -> str: ...
    def _work_of_topic(self, work_id: str, topic_id: str) -> bool: ...
    def _write_verification_holds(self, payload: dict, op_id: str, now: str) -> dict: ...  # delegate to Verification


class EvidenceWriter:
    def __init__(self, core: EvidenceCore) -> None:
        self._core = core

    def check_quotes(self, payload: dict, inv: dict, bind: Callable[[dict, str], None]) -> list[dict]:
        """V-6 computation outside the lock; labels and attribution are not operands."""
        records = payload.get("quote_checks", [])
        if records and (inv["kind"] != "verification" or inv["admission_context"] != "contract/1"):
            raise Refusal("kind_not_permitted", "quote checks require contract-admitted verification")
        checked = []
        for record in records:
            claim = self._core._one("claims", {"claim_id": record["claim_id"], "revision": record["claim_revision"]})
            if claim is None or claim["topic_id"] != inv["topic_id"]:
                raise Refusal("payload_invalid", "quote check needs a recorded claim revision of this topic")
            source = self._core._one("source_artifacts", {"topic_id": inv["topic_id"], "work_id": record["work_id"], "source_version": record["source_version"]})
            if source is None:
                raise Refusal("payload_invalid", "quote check needs a recorded work/source version")
            ref = record["artifact_ref"]
            bind(ref, "quote source")
            artifact = boundary.staged(self._core._spool, ref["content_hash"], ref["size_bytes"], topic_id=inv["topic_id"], media_type=ref["media_type"])
            result = quote_matching.check_quote(record["quoted_text"].encode("utf-8"), artifact,
                record["span_start"], record["span_end"], source["content_hash"])
            document = asdict(result)
            document["quoted_bytes_hex"] = document.pop("quoted_bytes").hex()
            document["source_span_bytes_hex"] = document.pop("source_span_bytes").hex()
            checked.append({**{k: record[k] for k in ("check_id", "claim_id", "claim_revision", "work_id", "source_version")},
                "topic_id": inv["topic_id"], "source_artifact_hash": source["content_hash"],
                "span_start": result.span_start, "span_end": result.span_end,
                "normalization_version": "/".join(result.normalization),
                "exact_match": "mismatch" if result.quote_quarantined else "matched", "quote_quarantined": result.quote_quarantined,
                "nli_signal": "not_run", "match_result": document})
        return checked

    def _write_quote_checks(self, checked: dict, inv: dict, op_id: str, now: str) -> dict:
        records = checked["quote_checks"]
        for record in records:
            self._core._store.insert("quote_checks", {**record, "verifier_invocation_id": inv["invocation_id"],
                "recorded_by_operation_id": op_id, "checked_at": now})
            if record["quote_quarantined"]:
                self._notify_capture_owner(record, op_id, now)
        return {"quote_checks": [r["check_id"] for r in records], "quote_holds": self.quote_hold_ids(checked)} if records else {}

    def quote_hold_ids(self, checked: dict) -> list[str]:
        return ["hold_quote_" + q["check_id"] for q in checked["quote_checks"] if q["quote_quarantined"]]

    def _notify_capture_owner(self, check: dict, op_id: str, now: str) -> None:
        """V-6 attention uses the existing owned holds and status projection."""
        claim = self._core._one("claims", {"claim_id": check["claim_id"], "revision": check["claim_revision"]})
        producer = self._core._one("invocations", {"invocation_id": claim["producer_invocation_id"]})
        lease = self._core._one("leases", {"lease_id": producer["lease_id"]})
        self._core._store.insert("holds", {
            "hold_id": "hold_quote_" + check["check_id"], "topic_id": check["topic_id"], "subject_ref": "quote:" + check["check_id"],
            "hold_class": "judgment", "cause": "quote quarantine: " + check["match_result"]["reason"],
            "recoverability": "needs_remediation", "required_authority": "primary", "owner": "primary:" + lease["station_id"],
            "deadline_at": producer["deadline_at"], "clears_when": "matching re-capture as a new claim revision; the old capture remains quarantined",
            "created_at": now, "created_by_operation_id": op_id})

    def _require_quote_adjudication(self, doc: dict) -> None:
        if doc.get("adjudication") is not None and (doc["checks"]["exact_quote"]["status"] == "mismatch" or any(
                q["quote_quarantined"] and (q["exact_match"] != "matched" or q["nli_signal"] != "alarm")
                and (q["match_result"] is not None or q["check_id"] == doc["quote_check_id"])
                for q in self._core._store.select("quote_checks", {
                    "claim_id": doc["claim"]["claim_id"], "claim_revision": doc["claim"]["claim_revision"]}))):
            raise Refusal("payload_invalid", "byte-mismatch quarantine cannot be adjudicated (V-6)")

    def require_quote_hold_clearance(self, decision: dict) -> None:
        if decision["kind"] == "hold_clearance" and decision["disposition"] == "approved":
            hold = self._core._one("holds", {"hold_id": decision["subject_ref"]})
            if hold is not None and hold["subject_ref"].startswith("quote:"):
                check = self._core._one("quote_checks", {"check_id": hold["subject_ref"][6:]})
                if check is not None and check["quote_quarantined"] and (check["exact_match"] != "matched" or check["nli_signal"] != "alarm"):
                    raise Refusal("decision_refused", "byte-mismatch quarantine cannot be adjudicated (V-6)")

    def _capture_checks(self, claim_id: str, revision: int) -> list[dict]:
        """A claim revision is a capture; re-capture never replaces its checks."""
        return [q for q in self._core._store.select("quote_checks", {"claim_id": claim_id, "claim_revision": revision})
                if q["match_result"] is not None]

    def _quote_receipt_valid(self, doc: dict) -> bool:
        checks = self._capture_checks(doc["claim"]["claim_id"], doc["claim"]["claim_revision"])
        if not checks:
            return True
        support = doc["verdict"] in ("supports", "partially_supports")
        if support and any(q["quote_quarantined"] for q in checks):
            return False
        exact = doc["checks"]["exact_quote"]
        bound = [q for q in checks if (q["topic_id"], q["work_id"], q["source_version"], q["source_artifact_hash"],
            q["match_result"]["artifact_hash"], q["normalization_version"], q["exact_match"]) ==
            (doc["topic_id"], doc["source"]["work_id"], doc["source"]["source_version"], exact["source_artifact_hash"],
             doc["obtained_content_hash"], exact["normalization_version"], exact["status"])
            and (not support or (q["exact_match"] == "matched" and not q["quote_quarantined"]))]
        spans = {(s["start"], s["end"]) for s in doc["cited_spans"]}
        return (any(q["check_id"] == doc["quote_check_id"] and (q["span_start"], q["span_end"]) in spans for q in bound)
                and spans <= {(q["span_start"], q["span_end"]) for q in bound})

    def _require_quote_support(self, claim: dict) -> None:
        checks = self._capture_checks(claim["claim_id"], claim["revision"])
        if any(q["quote_quarantined"] for q in checks):
            raise Refusal("payload_invalid", "governed quarantined quote cannot supply support (V-6)")
        if checks and claim["load_bearing"]:
            receipts = self._core._store.select("verification_receipts", {"claim_id": claim["claim_id"], "claim_revision": claim["revision"]})
            if not any(v["verdict"] == "supports" and v["use"] == "load_bearing" and v["extraction_method"] == "canonical_bytes"
                    and self._quote_receipt_valid(v["receipt"]) for v in receipts):
                raise Refusal("payload_invalid", "support needs a receipt bound to this governed capture (V-1, V-6)")

    def bind_source_artifacts(self, payload: dict, inv: dict, bind: Callable[[dict, str], None]) -> None:
        records = payload.get("source_artifacts", [])
        if records and (inv["kind"] not in ("research_pass", "checkpoint") or inv["admission_context"] != "contract/1"):
            raise Refusal("kind_not_permitted", "source artifacts require contract-admitted primary work")
        for record in records:
            if not self._core._work_of_topic(record["work_id"], inv["topic_id"]):
                raise Refusal("cross_topic", "source artifact work was not retrieved by this topic")
            bind(record["artifact_ref"], "source artifact")

    def _write_source_artifacts(self, payload: dict, inv: dict, op_id: str, now: str) -> dict:
        recorded = []
        for record in payload.get("source_artifacts", []):
            key = {"topic_id": inv["topic_id"], "work_id": record["work_id"], "source_version": record["source_version"]}
            prior = self._core._one("source_artifacts", key)
            content_hash = record["artifact_ref"]["content_hash"]
            if prior is not None:
                if prior["content_hash"] != content_hash:
                    raise Refusal("payload_invalid", "source version already identifies different bytes; record a new version")
            else:
                self._core._store.insert("source_artifacts", {**key, "content_hash": content_hash, "invocation_id": inv["invocation_id"],
                    "recorded_by_operation_id": op_id, "created_at": now})
            recorded.append([record["work_id"], record["source_version"], content_hash])
        return {"source_artifacts": recorded} if recorded else {}

    def _write_evidence(self, env: dict, inv: dict, checked: dict, now: str, new_triggers: list, outbox: list) -> dict:
        """The evidence and governance rows of one commit. Producer, verifier,
        recorder and signal source are the committing invocation and
        operation — never a document field (V-10, RG-5, G-12)."""
        payload, op_id, topic_id = checked["payload"], env["operation_id"], inv["topic_id"]
        sources = self._write_source_artifacts(payload, inv, op_id, now)
        claims = self._write_claims(payload, topic_id, inv, now)
        quotes = self._write_quote_checks(checked, inv, op_id, now)
        for hold in payload["holds"]:
            self._core._store.insert("holds", {**hold, "topic_id": topic_id, "created_at": now, "created_by_operation_id": op_id})
        for doc in payload["verification_receipts"]:
            self._require_quote_adjudication(doc)
            if not self._quote_receipt_valid(doc):
                raise Refusal("payload_invalid", "receipt is detached from its governed capture; governed quarantined quote cannot supply support (V-1, V-6)")
            self._core._store.insert("verification_receipts", {
                "verification_receipt_id": doc["verification_receipt_id"], "topic_id": doc["topic_id"], "claim_id": doc["claim"]["claim_id"],
                "claim_revision": doc["claim"]["claim_revision"], "work_id": doc["source"]["work_id"], "source_version": doc["source"]["source_version"],
                "cited_spans": doc["cited_spans"], "obtained_content_hash": doc["obtained_content_hash"], "access_tier": doc["access_tier"],
                "use": doc["requested_for"]["use"], "required_access_tier": doc["requested_for"]["required_access_tier"], "acquisition": doc["acquisition"],
                "extraction_method": doc["extraction"]["method"], "extraction_invocation_id": doc["extraction"]["produced_by_invocation_id"],
                "extraction_validation_ref": doc["extraction"]["validation_ref"], "producer_invocation_id": doc["producer_invocation_id"],
                "verifier_invocation_id": doc["verifier_invocation_id"], "quote_check_id": doc["quote_check_id"], "verdict": doc["verdict"],
                "receipt": doc, "verified_at": doc["verified_at"]})
            self._require_own_extraction(doc)
        verification = self._core._write_verification_holds(payload, op_id, now)
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
        return {**sources, **quotes, **verification, "claims": claims, "claim_promotions": promotions, "claim_source_links": links,
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
            self._require_quote_support(row)
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

    def _require_own_extraction(self, doc: dict) -> None:
        # Inside the existing writer fence, after same-outcome extractions.
        if doc["extraction"]["method"] != "verifier_extraction":
            return
        rank = {"bibliographic": 1, "abstract": 2, "full_text": 3, "reproduced": 4}
        acquisitions = [a for a in self._core._store.select("source_acquisitions", {
            **doc["source"], "verifier_invocation_id": doc["verifier_invocation_id"], "content_hash": doc["obtained_content_hash"]})
            if a["gateway_call_ref"] == doc["acquisition"]["gateway_call_ref"]
            and a["retrieved_at"] == doc["acquisition"]["retrieved_at"] and "gateway:" + a["lane"] == doc["acquisition"]["route"]]
        extraction = self._core._one("source_extractions", {"extraction_id": doc["extraction"].get("extraction_id")})
        if extraction is None or not any(all(extraction[k] == a[k] for k in
                ("topic_id", "work_id", "source_version", "event_id", "verifier_invocation_id")) for a in acquisitions) or (
                extraction["topic_id"] != doc["topic_id"] or extraction["extracting_invocation_id"] != doc["extraction"]["produced_by_invocation_id"]
                or extraction["extractor_identity"] != doc["extraction"]["extractor"] or extraction["extractor_registry_version"] is None
                or rank[extraction["supported_tier"]] < rank[doc["access_tier"]]):
            raise Refusal("payload_invalid", "receipt needs its verifier durable extraction")
