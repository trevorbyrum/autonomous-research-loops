"""Attributed V-8 assessment admission; operator ruling 2026-10-17.

C-9 byte authentication precedes the writer lock. SQL 35 binds relationships;
receipt references bind exactly; load-bearing support must consume records.
"""
from typing import Callable

from gen2.core import canonical
from gen2.router import boundary
from gen2.router.boundary import Refusal
from gen2.router.extractions import ExtractionCore


class DetailedChecks:
    def __init__(self, core: ExtractionCore) -> None:
        self._core = core

    def require_support(self, claim: dict, capture_valid: Callable[[dict], bool]) -> None:
        """V-4/V-8 consumption in the existing writer transaction.

        Detailed records, basis and governed capture qualify on one candidate,
        independently of SQL support views.
        """
        if not claim["load_bearing"]:
            return
        rank = {"bibliographic": 1, "abstract": 2, "full_text": 3, "reproduced": 4}
        for row in self._core._store.select("verification_receipts", {
                "claim_id": claim["claim_id"], "claim_revision": claim["revision"]}):
            if (row["verdict"] != "supports" or row["use"] != "load_bearing"
                    or row["required_access_tier"] != claim["required_access_tier"]
                    or rank[row["access_tier"]] < rank[claim["required_access_tier"]]):
                continue
            # Consumption binds the stored columns, including retained history,
            # rather than letting a detached JSON label choose the operands.
            doc = {**row["receipt"], "topic_id": row["topic_id"],
                "claim": {"claim_id": row["claim_id"], "claim_revision": row["claim_revision"]},
                "source": {"work_id": row["work_id"], "source_version": row["source_version"]},
                "cited_spans": row["cited_spans"], "verifier_invocation_id": row["verifier_invocation_id"],
                "quote_check_id": row["quote_check_id"],
                "obtained_content_hash": row["obtained_content_hash"], "acquisition": row["acquisition"], "extraction": {
                    **row["receipt"]["extraction"], "method": row["extraction_method"],
                    "produced_by_invocation_id": row["extraction_invocation_id"],
                    "validation_ref": row["extraction_validation_ref"]}}
            entries = doc.get("detailed_checks")
            if (doc.get("receipt_version") != "verification-receipt/2" or not isinstance(entries, dict)
                    or set(entries) != {"numeric_units", "denominators", "negation", "qualifications"}):
                continue
            if any(not isinstance(entry, dict) or not entry.get("record_id")
                    or entry.get("outcome") not in ("succeeded", "failed", "not_applicable")
                    for entry in entries.values()):
                continue
            try:
                self.require_receipt(doc)
            except Refusal:
                continue
            if not self._has_basis(row, rank):
                continue
            if not capture_valid(doc):
                continue
            return
        raise Refusal("payload_invalid", "support requires exactly bound performed detailed checks (V-4, V-8)")

    def _has_basis(self, row: dict, rank: dict) -> bool:
        """Promotion also excludes extraction alarms; membership alone does not."""
        if (row["extraction_method"] in ("verifier_extraction", "validated_extraction")
                and row["receipt"]["checks"].get("tier0", {}).get("signal") in ("alarm",)):
            return False
        return self._basis_member(row, rank)

    def _basis_member(self, row: dict, rank: dict) -> bool:
        """Re-read SQL 15/32/33/34 operands; admission owns their authentication."""
        method = row["extraction_method"]
        basis = None if method == "canonical_bytes" else self._extraction_basis(row, rank)
        if method != "canonical_bytes" and basis is None:
            return False
        acquisitions = self._core._store.select("source_acquisitions", {k: row[k] for k in
            ("topic_id", "work_id", "source_version", "verifier_invocation_id")})
        for acquired in acquisitions:
            if (acquired["content_hash"] != row["obtained_content_hash"]
                    or acquired["gateway_call_ref"] != row["acquisition"]["gateway_call_ref"]
                    or acquired["retrieved_at"] != row["acquisition"]["retrieved_at"]
                    or "gateway:" + acquired["lane"] != row["acquisition"]["route"]
                    or self._content_rank(acquired) < rank[row["access_tier"]]):
                continue
            if method == "canonical_bytes":
                if acquired["acquired_by_invocation_id"] == row["extraction_invocation_id"]:
                    return True
            elif all(basis[k] == acquired[k] for k in
                    ("topic_id", "work_id", "source_version", "event_id", "verifier_invocation_id")):
                return True
        return False

    def _extraction_basis(self, row: dict, rank: dict) -> dict | None:
        method = row["extraction_method"]
        validation = None
        if method == "validated_extraction":
            validations = self._core._store.select("extraction_validations_v2", {
                "validation_id": row["extraction_validation_ref"]})
            validation = next(iter(validations), None)
            if (validation is None or validation["method"] != "independent_extraction"
                    or validation["policy_version"] != 2 or validation["outcome"] != "succeeded"
                    or validation["validator_invocation_id"] != row["verifier_invocation_id"]):
                return None
            independent = self._core._store.select("source_extractions", {
                "extraction_id": validation["validator_extraction_id"]})
            if not independent or rank[independent[0]["supported_tier"]] < rank[row["access_tier"]]:
                return None
        if method not in ("verifier_extraction", "validated_extraction"):
            return None
        extraction_id = (validation["target_extraction_id"] if validation else
            row["receipt"]["extraction"].get("extraction_id"))
        if not isinstance(extraction_id, str):
            return None
        bases = self._core._store.select("source_extractions", {"extraction_id": extraction_id})
        if not bases:
            return None
        basis = bases[0]
        if (basis["extractor_registry_version"] is None
                or basis["extracting_invocation_id"] != row["extraction_invocation_id"]
                or basis["extractor_identity"] != row["receipt"]["extraction"]["extractor"]
                or rank[basis["supported_tier"]] < rank[row["access_tier"]]
                or (method == "verifier_extraction" and basis["extracting_invocation_id"] != row["verifier_invocation_id"])):
            return None
        return basis

    def _content_rank(self, acquired: dict) -> int:
        try:
            response = canonical.parse_json_strict(acquired["response_bytes"])
        except (ValueError, UnicodeDecodeError):
            return 1
        records = response.get("records") if isinstance(response, dict) else None
        if not isinstance(records, list):
            return 1
        observations = self._core._store.select("search_observations", {"observation_id": acquired["observation_id"]})
        searched = bool(observations and observations[0]["coverage_state"] == "searched_ok")
        tiers = [1]
        for record in records:
            if isinstance(record, dict) and record.get("identity") == acquired["provider_record_id"]:
                tiers.append(3 if searched and record.get("kind") == "full_text" and self._nonblank(record.get("text"))
                    else 2 if self._nonblank(record.get("abstract")) else 1)
        return max(tiers)

    @staticmethod
    def _nonblank(value: object) -> bool:
        # recorded-nonblank/1+ucd17.0.0, exactly the SQL16 pinned ranges.
        ranges = ((9,13),(32,32),(133,133),(160,160),(5760,5760),(8192,8202),(8232,8233),
            (8239,8239),(8287,8287),(12288,12288),(173,173),(847,847),(1564,1564),
            (4447,4448),(6068,6069),(6155,6159),(8203,8207),(8234,8238),(8288,8303),
            (12644,12644),(65024,65039),(65279,65279),(65440,65440),(65520,65528),
            (113824,113827),(119155,119162),(917504,921599))
        # SQLite's GLOB stops at NUL; retain that recorded-content interpretation.
        return isinstance(value, str) and any(not any(lo <= ord(c) <= hi for lo, hi in ranges)
            for c in value.split("\0", 1)[0])

    def authenticate(self, payload: dict, inv: dict, bind: Callable[[dict, str], None]) -> None:
        records = payload.get("detailed_check_records", [])
        if records and (inv["admission_context"] != "contract/1" or inv["kind"] != "verification"
                or inv["parent_invocation_id"] is not None):
            raise Refusal("kind_not_permitted", "detailed checks require independent contract verification")
        for record in records:
            report = record["assessment"]
            if report["outcome"] in ("succeeded", "failed", "not_applicable") and not all(
                    self._nonblank(report[field]) for field in ("assessment", "context_examined")):
                raise Refusal("payload_invalid", "performed detailed check needs nonblank assessment and context")
            if report["outcome"] in ("not_applicable",) and not self._nonblank(report["applicability_reason"]):
                raise Refusal("payload_invalid", "detailed check exemption needs nonblank applicability reason")
            boundary.check_span_offsets(report["cited_spans"] + report["context_spans"])
            for ref in (report["examined_artifact_ref"], record["evidence_ref"]):
                if ref is None:
                    continue
                bind(ref, "detailed check artifact")
                raw = boundary.staged(self._core._spool, ref["content_hash"], ref["size_bytes"],
                    topic_id=inv["topic_id"], media_type=ref["media_type"])
                if ref is record["evidence_ref"]:
                    evidence = boundary.normalize(raw, "payload_invalid", member_domain=True)
                    if canonical.canonical_bytes(evidence) != canonical.canonical_bytes(report):
                        raise Refusal("payload_invalid", "detailed check evidence must retain the exact assessment report")

    def write(self, payload: dict, inv: dict, operation_id: str, now: str) -> dict:
        records = payload.get("detailed_check_records", [])
        for record in records:
            report = record["assessment"]
            claims = self._core._store.select("claims", {"claim_id": report["claim_id"], "revision": report["claim_revision"]})
            sources = self._core._store.select("source_artifacts", {"topic_id": inv["topic_id"],
                "work_id": report["work_id"], "source_version": report["source_version"]})
            if not claims or not sources or claims[0]["topic_id"] != inv["topic_id"]:
                raise Refusal("payload_invalid", "detailed check needs exact claim/source topic")
            if (claims[0]["producer_invocation_id"] == inv["invocation_id"]
                    or sources[0]["invocation_id"] == inv["invocation_id"]
                    or sources[0]["content_hash"] != report["source_artifact_hash"]):
                raise Refusal("payload_invalid", "detailed check needs independent verifier and exact source hash")
            self._core._store.insert("detailed_check_records", {**record, "topic_id": inv["topic_id"],
                "performer_invocation_id": inv["invocation_id"], "recorded_by_operation_id": operation_id, "created_at": now})
        for doc in payload["verification_receipts"]:
            self.require_receipt(doc)
        return {"detailed_check_records": [r["check_id"] for r in records]} if records else {}

    def require_receipt(self, doc: dict) -> None:
        """Current admission policy plus exact, explicitly projected bindings."""
        self._require_performed_references(doc)
        projection = {"succeeded": "checked_ok", "failed": "checked_problem",
            "not_applicable": "not_applicable", "not_checked": "not_checked", "unavailable": "unavailable"}
        for kind, entry in doc.get("detailed_checks", {}).items():
            if projection[entry["outcome"]] != doc["checks"][kind]:
                raise Refusal("payload_invalid", "detailed receipt summary projection mismatch")
            if "record_id" not in entry:
                continue
            rows = self._core._store.select("detailed_check_records", {"check_id": entry["record_id"]})
            sources = self._core._store.select("source_artifacts", {"topic_id": doc["topic_id"], **doc["source"]})
            if not rows or not sources:
                raise Refusal("payload_invalid", "receipt detailed check binding")

            row, report = rows[0], rows[0]["assessment"]
            artifact_hash = doc["obtained_content_hash"]
            if doc["extraction"]["method"] != "canonical_bytes":
                extraction_id = doc["extraction"].get("extraction_id")
                if doc["extraction"]["method"] == "validated_extraction":
                    validations = self._core._store.select("extraction_validations_v2", {"validation_id": doc["extraction"]["validation_ref"]})
                    extraction_id = validations[0]["target_extraction_id"] if validations else None
                extractions = self._core._store.select("source_extractions", {"extraction_id": extraction_id})
                artifact_hash = extractions[0]["output_ref"]["content_hash"] if extractions else None
            expected = {**doc["claim"], **doc["source"], "kind": kind, "outcome": entry["outcome"],
                "cited_spans": doc["cited_spans"], "source_artifact_hash": sources[0]["content_hash"]}
            if (row["topic_id"] != doc["topic_id"] or row["performer_invocation_id"] != doc["verifier_invocation_id"]
                    or any(report[k] != v for k, v in expected.items())
                    or report["examined_artifact_ref"]["content_hash"] != artifact_hash):
                raise Refusal("payload_invalid", "receipt detailed check binding")

    def _require_performed_references(self, doc: dict) -> None:
        if doc["requested_for"]["use"] == "load_bearing" and doc["verdict"] in ("supports", "partially_supports"):
            if any("record_id" not in doc.get("detailed_checks", {}).get(kind, {})
                    for kind in ("numeric_units", "denominators", "negation", "qualifications")
                    if doc["checks"][kind] in ("checked_ok", "checked_problem", "not_applicable")):
                raise Refusal("payload_invalid", "load-bearing support requires detailed check records")
