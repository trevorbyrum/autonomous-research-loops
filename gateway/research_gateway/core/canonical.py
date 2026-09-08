"""Canonical record shape returned by every adapter (PLAN.md §2, I-7, I-8).

A record never carries full text. `raw` is the source's payload (or the
relevant slice of it), kept so nothing is lost to normalisation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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


def member_summary(member: dict) -> dict:
    out = {k: member[k] for k in PROVENANCE_SUMMARY_FIELDS if isinstance(member.get(k), str) and member[k]}
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
