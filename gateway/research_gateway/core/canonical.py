"""Canonical record shape returned by every adapter (PLAN.md §2, I-7, I-8).

A record never carries full text. `raw` is the source's payload (or the
relevant slice of it), kept so nothing is lost to normalisation.

A record is a plain dict whose PROVENANCE IS STILL OPAQUE (2b-repair-13c, Astra R13A-2; core/payload.py "Where a sealed value becomes plain"): `raw` is a `Sealed`, and an
`extra` value built from a decoded `any_()` field is still the `Passive` it was. Adapter code that builds, returns or inspects records can therefore read none of it, so no
selection or coverage decision can depend on provenance. `router.execute` and `harvest/index.upsert` turn a record into plain data where it is serialized or stored. The typed
fields (title, venue, licence, identifiers ...) are plain, and refuse an opaque value.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .payload import PayloadError, Sealed, detach, plain, refuse_opaque  # noqa: F401 (PayloadError: re-exported, it lives with the decoded values now)
from .schema import year_value


KINDS = ("article", "dataset", "software", "document", "series", "citation", "oa_location", "full_text", "file",
         "venue", "repository")  # venue = journal/conference/book series; repository = data or publication repository


def _typed(name: str, value):
    """The plain data of a typed field's value. The field is read and decided on (the merge, the licence gate, the identity), so an opaque value — a Passive, a Sealed — is a
    programming error (PassiveRead, SealedRead: not a malformed member): it would hand a record's reader what no adapter may read. Whatever else is not plain (an Unreadable, a
    decoded Rec) is converted, and fails the kind check that follows."""
    refuse_opaque(value, f"a record's {name}")
    return plain(value)


def _text(name: str, value) -> str | None:
    """A canonical text field: text, or nothing. Any other kind is an unreadable member (PayloadError) — never a title of 5, a venue of
    `false` or a licence that is a list, which every later reader of a record (the merge, the licence gate) would take for text."""
    value = _typed(name, value)
    if value is None or isinstance(value, str):
        return value
    raise PayloadError(f"a record's {name} is {type(value).__name__}, not text")


def _texts(name: str, value) -> list[str]:
    """A canonical list of text (authors, links): the text in it, with a missing entry left out; a list that holds anything else, or a
    value that is not a list, is unreadable."""
    value = _typed(name, value)
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or not all(v is None or isinstance(v, str) for v in value):
        raise PayloadError(f"a record's {name} is not a list of text")
    return [v for v in value if v is not None]


def _year(value) -> int | None:
    """A canonical year: a whole number, or the digits of one a provider sent as text; nothing when it names none. Anything else is unreadable (the rule is the
    decoder's: core/schema.py year_value)."""
    try:
        return year_value(_typed("year", value))
    except PayloadError as e:
        raise PayloadError(f"a record's {e}") from None


def _identifiers(value) -> dict:
    value = _typed("identifiers", value)
    if value is None:
        return {}
    if not isinstance(value, dict) or not all(isinstance(k, str) and (v is None or isinstance(v, str)) for k, v in value.items()):
        raise PayloadError("a record's identifiers are not a map of text")
    return {k: v for k, v in value.items() if v is not None}


def make_record(*, identity: str, kind: str, source_id: str, title: str | None = None,
                authors: list[str] | None = None, year: int | None = None, venue: str | None = None,
                identifiers: dict[str, str] | None = None, links: list[str] | None = None,
                license: str | None = None, attribution: str | None = None, extra: dict | None = None,
                raw: Any = None) -> dict:
    """The one constructor of a canonical record. Its typed fields are checked here, whatever the adapter passed: a value of the wrong
    kind makes the member that carried it unreadable (PayloadError; members() drops and counts it), instead of travelling on as a
    title that is a number to code that calls `.lower()` on it (R8: one such member made the whole request raise).

    What is not typed is provenance, and stays opaque: `raw` (a Sealed object — the member as sent, or any plain value, sealed here) and the values of `extra` (a copy of their
    plain structure, with every Passive in it left as it is). The record is plain data only where the router or the index serializes it (core/payload.py)."""
    if kind not in KINDS:
        raise ValueError(f"unknown record kind {kind!r}")
    refuse_opaque(identity, "a record's identity")
    title, venue, license, attribution = _text("title", title), _text("venue", venue), _text("license", license), _text("attribution", attribution)
    authors, links, year, identifiers = _texts("authors", authors), _texts("links", links), _year(year), _identifiers(identifiers)
    rec = {
        "identity": identity,
        "kind": kind,
        "source_id": source_id,
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "identifiers": identifiers,
        "links": links,
        "license": license,
        "attribution": attribution,
        # when THIS source's answer was obtained — a citation's retrieval date, never a
        # verification date (verification is the reviewing agent's act, STATION-CONTRACT.md)
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if extra:
        rec.update({k: detach(v) for k, v in extra.items() if k not in rec})
    rec["raw"] = raw if raw is None or isinstance(raw, Sealed) else Sealed(plain(raw), _issued=True)
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
    """First 4-digit year in a date-ish string, or None when there is none (or no string). Anything that is not text — a number, a boolean, a
    list — is unreadable, not a date that names no year."""
    if text is not None and not isinstance(text, str):
        raise PayloadError(f"{type(text).__name__} where a date belongs")
    if not text:
        return None
    s = text
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
