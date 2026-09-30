"""Canonical record shape returned by every adapter (PLAN.md §2, I-7, I-8).

A record never carries full text. `raw` is the source's payload (or the
relevant slice of it), kept so nothing is lost to normalisation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

class PayloadError(ValueError):
    """An answer that is not the shape its adapter requires — an empty or unparseable body, or
    a parsed body without the container its results live in. The lane is unavailable with
    error_class payload_invalid: an unreadable answer is never zero results (INVARIANTS H-5,
    RG-4; design review §9, task 2b). Adapters use it through adapters.base."""


KINDS = ("article", "dataset", "software", "document", "series", "citation", "oa_location", "full_text", "file",
         "venue", "repository")  # venue = journal/conference/book series; repository = data or publication repository


def make_record(*, identity: str, kind: str, source_id: str, title: str | None = None,
                authors: list[str] | None = None, year: int | None = None, venue: str | None = None,
                identifiers: dict[str, str] | None = None, links: list[str] | None = None,
                license: str | None = None, attribution: str | None = None, extra: dict | None = None,
                raw: Any = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown record kind {kind!r}")
    rec = {
        "identity": identity,
        "kind": kind,
        "source_id": source_id,
        "title": title,
        "authors": authors or [],
        "year": year,
        "venue": venue,
        "identifiers": identifiers or {},
        "links": links or [],
        "license": license,
        "attribution": attribution,
        # when THIS source's answer was obtained — a citation's retrieval date, never a
        # verification date (verification is the reviewing agent's act, STATION-CONTRACT.md)
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if extra:
        rec.update({k: v for k, v in extra.items() if k not in rec})
    rec["raw"] = raw
    return rec


PROVENANCE_SUMMARY_FIELDS = ("source_id", "identity", "license", "retrieved_at", "attribution", "link")
# what a stored/persisted provenance member may say (8a): citation ingredients as SCALAR
# STRINGS only — a nested object in a whitelisted name can never smuggle a raw payload
# (D-30). Shared by job-result storage (router) and cache persistence.


PERMISSION_FACTS = {"availability": ("content", "metadata"), "access": ("commercial_use", "personal_use"),
                    "storage": ("persist", "transient"), "redistribution": ("permitted", "conditional", "prohibited", "unknown")}


# a source's own statements about ONE member (its terms forbid redistribution; it carries
# third-party restrictions): booleans, never payloads, and inputs of the member's permission
# facts — kept by every stored summary so a reload re-derives the same restriction (2b-repair A3)
MEMBER_RESTRICTIONS = ("redistributable", "third_party_restricted")
# what a member stored by an earlier writer shows without saying why (registry/migrate.py): it
# was personal use. Inferred from that legacy data, never a statement of its source; no current
# writer produces it
INFERRED_RESTRICTIONS = ("inferred_personal_use",)


def member_summary(member: dict) -> dict:
    out = {k: member[k] for k in PROVENANCE_SUMMARY_FIELDS + ("metadata_license", "freshness_lag")
           if isinstance(member.get(k), str) and member[k]}
    out.update({k: member[k] for k in MEMBER_RESTRICTIONS + INFERRED_RESTRICTIONS if isinstance(member.get(k), bool)})
    perms = member.get("permissions")
    if isinstance(perms, dict) and set(perms) == set(PERMISSION_FACTS) and all(perms[k] in v for k, v in PERMISSION_FACTS.items()):
        out["permissions"] = {k: perms[k] for k in PERMISSION_FACTS}   # four enum facts, never a nested payload (task 2b)
    return out or {"source_id": member.get("source_id") if isinstance(member.get("source_id"), str) else None}


def year_from(text: str | None) -> int | None:
    """First 4-digit year in a date-ish string, or None."""
    if not text:
        return None
    s = str(text)
    for i in range(len(s) - 3):
        chunk = s[i:i + 4]
        if chunk.isdigit() and 1500 <= int(chunk) <= 2100:
            return int(chunk)
    return None


def first(*values):
    for v in values:
        if v:
            return v
    return None
