"""G-8/G-13: fresh review preparation and mutable operator hand-off blockers.

The receipt chooses one transition; review-only payloads cannot hide a new
scientific effect. Hashing happens outside the writer; blockers are rechecked.
"""
from gen2.core import canonical
from gen2.router import material
from gen2.router.accounting import records


def candidate(core, inputs, payload):
    allowed = {"outcome_version", "invocation_id", "topic_id", "operation_kind", "completion_records", "review_closures"}
    reviews = payload.get("completion_records", [])
    if any(value for key, value in payload.items() if key not in allowed) or len(reviews) != 1:
        return False
    review = reviews[0]
    if review["kind"] != "sufficiency_review" or review["assessment"]["outcome"] != "sufficient":
        return False
    row = max(records(inputs.raw, "dossiers"), key=lambda r: r["dossier_revision"], default=None)
    if row is None or (row["dossier_revision"], row["content_hash"], row["contract_revision"]) != (
            review["subject_revision"], review["subject_hash"], inputs.coverage.inventory.current_contract_revision):
        return False
    doc = core._one("dossiers", {"topic_id": inputs.raw.topic_id, "dossier_revision": row["dossier_revision"]})["document"]
    return (not core._schemas.errors(doc, "dossier-v2.schema.json") and canonical.content_hash(doc) == row["content_hash"]
            and doc["evaluator_version"] == material.EVALUATOR and doc["result"]["state"] == "satisfied"
            and doc.get("material_digest") == material.digest(inputs.raw, doc["history"]))


def blocked(core, topic_id, *, ending=None, closing=()):
    """Only the committing final invocation/validated closures may be subtracted; never a hold or new signal."""
    topic = core._one("queue_entries", {"topic_id": topic_id})
    return (topic["paused_at"] is not None
            or any(h["cleared_at"] is None and h["topic_id"] in (None, topic_id) for h in core._store.select("holds"))
            or any(i["invocation_id"] != ending and i["state"] not in ("committed", "failed", "cancelled") for i in core._store.select("invocations", {"topic_id": topic_id}))
            or any(t["handled_at"] is None and t["episode_id"] not in closing for t in core._store.select("review_triggers", {"topic_id": topic_id}))
            or any(e["closed_at"] is None and e["episode_id"] not in closing for e in core._store.select("review_episodes", {"topic_id": topic_id})))
