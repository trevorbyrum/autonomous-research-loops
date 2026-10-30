"""Receipt support predicates over select-only rows; V-4/V-6/V-8.

Callers own the snapshot or writer fence. No core, transaction or write handle
is needed, including for detached completion-gate operands.
"""
from typing import Callable, Mapping, Protocol

from gen2.core import canonical
from gen2.router import boundary
from gen2.router.boundary import Refusal

CANONICAL = frozenset({"canonical_bytes"})  # the extraction method that reads the artifact bytes themselves


class Rows(Protocol):
    def select(self, table: str, where: "Mapping[str, object] | None" = None) -> list[dict]: ...


def require_support(rows: Rows, claim: dict, capture_valid: Callable[[dict], bool]) -> None:
    """V-4/V-8 consumption in the existing writer transaction.

    Detailed records, basis and governed capture qualify on one candidate,
    independently of SQL support views.
    """
    if not claim["load_bearing"]:
        return
    for row in rows.select("verification_receipts", {
            "claim_id": claim["claim_id"], "claim_revision": claim["revision"]}):
        if (row["verdict"] != "supports" or row["use"] != "load_bearing"
                or row["required_access_tier"] != claim["required_access_tier"]
                or boundary.TIER[row["access_tier"]] < boundary.TIER[claim["required_access_tier"]]):
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
            require_receipt(rows, doc)
        except Refusal:
            continue
        if not has_basis(rows, row, boundary.TIER):
            continue
        if not capture_valid(doc):
            continue
        return
    raise Refusal("payload_invalid", "support requires exactly bound performed detailed checks (V-4, V-8)")


def has_basis(rows: Rows, row: dict, rank: dict) -> bool:
    """Promotion also excludes extraction alarms; membership alone does not."""
    if (row["extraction_method"] in ("verifier_extraction", "validated_extraction")
            and row["receipt"]["checks"].get("tier0", {}).get("signal") in ("alarm",)):
        return False
    return basis_member(rows, row, rank)


def basis_member(rows: Rows, row: dict, rank: dict) -> bool:
    """Re-read SQL 15/32/33/34 operands; admission owns their authentication."""
    method = row["extraction_method"]
    basis = None if method in CANONICAL else extraction_basis(rows, row, rank)
    if method not in CANONICAL and basis is None:
        return False
    acquisitions = rows.select("source_acquisitions", {k: row[k] for k in
        ("topic_id", "work_id", "source_version", "verifier_invocation_id")})
    for acquired in acquisitions:
        if (acquired["content_hash"] != row["obtained_content_hash"]
                or acquired["gateway_call_ref"] != row["acquisition"]["gateway_call_ref"]
                or acquired["retrieved_at"] != row["acquisition"]["retrieved_at"]
                or f"gateway:{acquired['lane']}" != row["acquisition"]["route"]
                or content_rank(rows, acquired) < rank[row["access_tier"]]):
            continue
        if method in CANONICAL:
            if acquired["acquired_by_invocation_id"] == row["extraction_invocation_id"]:
                return True
        elif all(basis[k] == acquired[k] for k in
                ("topic_id", "work_id", "source_version", "event_id", "verifier_invocation_id")):
            return True
    return False


def extraction_basis(rows: Rows, row: dict, rank: dict) -> "dict | None":
    method = row["extraction_method"]
    validation = None
    if method == "validated_extraction":
        validations = rows.select("extraction_validations_v2", {
            "validation_id": row["extraction_validation_ref"]})
        validation = next(iter(validations), None)
        if (validation is None or validation["method"] != "independent_extraction"
                or validation["policy_version"] != 2 or validation["outcome"] != "succeeded"
                or validation["validator_invocation_id"] != row["verifier_invocation_id"]):
            return None
        independent = rows.select("source_extractions", {
            "extraction_id": validation["validator_extraction_id"]})
        if not independent or rank[independent[0]["supported_tier"]] < rank[row["access_tier"]]:
            return None
    if method not in ("verifier_extraction", "validated_extraction"):
        return None
    extraction_id = (validation["target_extraction_id"] if validation else
        row["receipt"]["extraction"].get("extraction_id"))
    if not isinstance(extraction_id, str):
        return None
    bases = rows.select("source_extractions", {"extraction_id": extraction_id})
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


def content_rank(rows: Rows, acquired: dict) -> int:
    try:
        response = canonical.parse_json_strict(acquired["response_bytes"])
    except (ValueError, UnicodeDecodeError):
        return 1
    records = response.get("records") if isinstance(response, dict) else None
    if not isinstance(records, list):
        return 1
    observations = rows.select("search_observations", {"observation_id": acquired["observation_id"]})
    searched = bool(observations and observations[0]["coverage_state"] == "searched_ok")
    tiers = [1]
    for record in records:
        if isinstance(record, dict) and record.get("identity") == acquired["provider_record_id"]:
            if searched and record.get("kind") == "full_text" and nonblank(record.get("text")):
                tiers.append(3)
            elif nonblank(record.get("abstract")):
                tiers.append(2)
    return max(tiers)


def nonblank(value: object) -> bool:
    # recorded-nonblank/1+ucd17.0.0, exactly the SQL16 pinned ranges.
    ranges = ((9,13),(32,32),(133,133),(160,160),(5760,5760),(8192,8202),(8232,8233),
        (8239,8239),(8287,8287),(12288,12288),(173,173),(847,847),(1564,1564),
        (4447,4448),(6068,6069),(6155,6159),(8203,8207),(8234,8238),(8288,8303),
        (12644,12644),(65024,65039),(65279,65279),(65440,65440),(65520,65528),
        (113824,113827),(119155,119162),(917504,921599))
    # SQLite's GLOB stops at NUL; retain that recorded-content interpretation.
    return isinstance(value, str) and any(not any(lo <= ord(c) <= hi for lo, hi in ranges)
        for c in value.split("\0", 1)[0])


def require_receipt(rows: Rows, doc: dict) -> None:
    """Current admission policy plus exact, explicitly projected bindings."""
    require_performed_references(doc)
    projection = {"succeeded": "checked_ok", "failed": "checked_problem",
        "not_applicable": "not_applicable", "not_checked": "not_checked", "unavailable": "unavailable"}
    for kind, entry in doc.get("detailed_checks", {}).items():
        if projection[entry["outcome"]] != doc["checks"][kind]:
            raise Refusal("payload_invalid", "detailed receipt summary projection mismatch")
        if "record_id" not in entry:
            continue
        checks = rows.select("detailed_check_records", {"check_id": entry["record_id"]})
        sources = rows.select("source_artifacts", {"topic_id": doc["topic_id"], **doc["source"]})
        if not checks or not sources:
            raise Refusal("payload_invalid", "receipt detailed check binding")

        row, report = checks[0], checks[0]["assessment"]
        artifact_hash = doc["obtained_content_hash"]
        if doc["extraction"]["method"] not in CANONICAL:
            extraction_id = doc["extraction"].get("extraction_id")
            if doc["extraction"]["method"] == "validated_extraction":
                validations = rows.select("extraction_validations_v2", {"validation_id": doc["extraction"]["validation_ref"]})
                extraction_id = validations[0]["target_extraction_id"] if validations else None
            extractions = rows.select("source_extractions", {"extraction_id": extraction_id})
            artifact_hash = extractions[0]["output_ref"]["content_hash"] if extractions else None
        expected = {**doc["claim"], **doc["source"], "kind": kind, "outcome": entry["outcome"],
            "cited_spans": doc["cited_spans"], "source_artifact_hash": sources[0]["content_hash"]}
        if (row["topic_id"] != doc["topic_id"] or row["performer_invocation_id"] != doc["verifier_invocation_id"]
                or any(report[k] != v for k, v in expected.items())
                or report["examined_artifact_ref"]["content_hash"] != artifact_hash):
            raise Refusal("payload_invalid", "receipt detailed check binding")


def require_performed_references(doc: dict) -> None:
    if doc["requested_for"]["use"] == "load_bearing" and doc["verdict"] in ("supports", "partially_supports"):
        if any("record_id" not in doc.get("detailed_checks", {}).get(kind, {})
                for kind in ("numeric_units", "denominators", "negation", "qualifications")
                if doc["checks"][kind] in ("checked_ok", "checked_problem", "not_applicable")):
            raise Refusal("payload_invalid", "load-bearing support requires detailed check records")


def capture_checks(rows: Rows, claim_id: str, revision: int) -> list[dict]:
    """A claim revision is a capture; re-capture never replaces its checks."""
    return [q for q in rows.select("quote_checks", {"claim_id": claim_id, "claim_revision": revision})
            if q["match_result"] is not None]


def quote_receipt_valid(rows: Rows, doc: dict) -> bool:
    checks = capture_checks(rows, doc["claim"]["claim_id"], doc["claim"]["claim_revision"])
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


def quote_support_valid(rows: Rows, doc: dict) -> bool:
    """DetailedChecks applies this to its same, stored-column candidate."""
    if not capture_checks(rows, doc["claim"]["claim_id"], doc["claim"]["claim_revision"]):
        return True
    return doc["extraction"]["method"] in CANONICAL and quote_receipt_valid(rows, doc)
