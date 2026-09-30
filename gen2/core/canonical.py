"""Canonical hashing for gen-2: RFC 8785 JCS for logical JSON, raw bytes kept raw.

Trace: Astra 0a ruling R1 (ACCEPT RFC 8785 JCS for logical JSON hashes; one
small pinned implementation behind a pure helper; published and
cross-implementation vectors; reject duplicate keys, non-finite numbers,
invalid Unicode and unsupported numeric precision before hashing; bound
integers to the interoperable range; keep raw provider-response and artifact
byte hashes separate and never canonicalized; version the contract);
ruling R2.6; Astra re-review RA8 (identity bounds by value, any notation);
gen2/store/README.md "Hashing contract"; INVARIANTS C-13.

Two kinds of digest, never mixed:
  * content_hash / request_fingerprint / logical_hash: SHA-256 over the JCS
    serialization of a *logical* JSON value (contracts, envelopes, specs,
    manifests, internally produced JSON artifacts);
  * bytes_digest: SHA-256 over bytes exactly as retained (raw provider
    responses, acquired/staged artifacts). Canonicalizing a response and
    calling the result a digest of the response would be a false provenance
    claim, so bytes_digest never parses its input.

The JCS algorithm itself is the pinned `rfc8785` package (gen2/requirements.txt,
hash-locked; declared for module core in gen2/boundaries.toml). This module
only validates inputs, excludes the declared non-identity fields and
formats the digest.
"""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, InvalidOperation

import rfc8785

CANONICALIZATION = "jcs-rfc8785/1"
FINGERPRINT_CONTRACT = "commit-fingerprint/1"  # JCS over the commit envelope minus submitted_at
CONTENT_HASH_EXCLUDES = ("content_hash",)
FINGERPRINT_EXCLUDES = ("submitted_at",)
INT_BOUND = 2**53 - 1  # I-JSON / RFC 8785 note 1: larger identities travel as strings


class CanonicalizationError(ValueError):
    """The value cannot be hashed as logical JSON without losing meaning."""


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise CanonicalizationError(f"duplicate object key {key!r}")
        out[key] = value
    return out


def _reject_constant(name: str) -> object:
    raise CanonicalizationError(f"non-finite number {name} is not JSON")


def _exact_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise CanonicalizationError(f"number {text} overflows a double")
    try:
        if Decimal(repr(value)) != Decimal(text):
            raise CanonicalizationError(f"number {text} is not exactly representable (it would hash as {value!r})")
    except InvalidOperation as exc:  # pragma: no cover - json only hands us valid numerals
        raise CanonicalizationError(f"bad number {text}") from exc
    return value


def parse_json_strict(text: str | bytes) -> object:
    """Parse JSON text (bytes are UTF-8) for hashing: duplicate keys,
    NaN/Infinity, integer-notation numerals outside +/-(2**53-1) and numerals
    a double cannot hold exactly (underflow to zero included) are errors,
    never silently rounded or merged. Any other number is an IEEE binary64
    value, as in JCS — 1e30 and 9007199254740992.0 are legitimate numbers —
    so identity bounds are not this parser's: see identity_integer."""
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CanonicalizationError(f"JSON bytes are not UTF-8: {exc}") from exc
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant, parse_float=_exact_float)
    except json.JSONDecodeError as exc:
        raise CanonicalizationError(f"not JSON: {exc}") from exc
    _validate(value)
    return value


def _validate(value: object, path: str = "$") -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > INT_BOUND:
            raise CanonicalizationError(f"{path}: integer {value} outside +/-(2**53-1); encode it as a string")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError(f"{path}: non-finite number")
        return
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise CanonicalizationError(f"{path}: string is not valid Unicode (lone surrogate)") from exc
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(f"{path}: object key {key!r} is not a string")
            _validate(key, f"{path}.<key>")
            _validate(item, f"{path}.{key}")
        return
    raise CanonicalizationError(f"{path}: {type(value).__name__} is not a JSON value")


def identity_integer(value: object, *, minimum: int = 0) -> int:
    """An identity, revision or generation number, bounded BY VALUE (Astra
    re-review RA8): an int, or an integral float, in [minimum, 2**53-1] —
    whatever notation it arrived in (9007199254740991, 9007199254740991.0,
    9.007199254740991e15 all pass; their +1 all fail) and whichever Python
    type the parser produced. Identities that need more travel as strings.
    The schemas state the same bound as `maximum` on revision, state_revision
    and generation."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CanonicalizationError(f"identity {value!r} is not a JSON number")
    if isinstance(value, float) and not (math.isfinite(value) and value.is_integer()):
        raise CanonicalizationError(f"identity {value!r} is not an integer")
    if not minimum <= value <= INT_BOUND:
        raise CanonicalizationError(f"identity {value!r} outside [{minimum}, 2**53-1]; encode larger identities as strings")
    return int(value)


def canonical_bytes(value: object) -> bytes:
    """The RFC 8785 serialization (UTF-8 bytes) of a logical JSON value."""
    _validate(value)
    try:
        return rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, UnicodeEncodeError) as exc:
        raise CanonicalizationError(str(exc)) from exc


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def logical_hash(value: object) -> str:
    """SHA-256 of the JCS form of a logical JSON value."""
    return _sha256(canonical_bytes(value))


def gateway_fact_id(fact: dict) -> str:
    """A gateway-reported capability fact's id (tasks 2b, 2b-repair A6, 2b-repair-2 R2,
    2b-repair-3 R2): one SNAPSHOT of an episode — the episode is the capability, its state and
    the instant that state began, which its snapshots never change; the snapshot adds its
    revision (the gateway's count of its fact's changes: the snapshot's place in the gateway's
    reports) and what the gateway said then (detail, last success, the affected lanes as a
    set) — whoever reports it. So the router can check that an id is its content's, a re-report
    replays, an ongoing outage that widens or changes its detail is a new snapshot of the same
    episode, never a conflict, and a return to earlier contents is a later snapshot, never the
    earlier one replayed."""
    return "fact_" + hashlib.sha256(canonical_bytes(
        ["capability", fact["capability"], fact["since"], fact["state"], fact["revision"], fact["detail"], fact["last_success_at"],
         sorted(fact["affected_lanes"])])).hexdigest()[:32]


def _without(document: dict, excluded: tuple[str, ...]) -> dict:
    if not isinstance(document, dict):
        raise CanonicalizationError("a hashed document is a JSON object")
    return {key: value for key, value in document.items() if key not in excluded}


def content_hash(document: dict) -> str:
    """A document's content hash: JCS over every field except content_hash
    itself (contracts, specs, manifests carry their own hash)."""
    return logical_hash(_without(document, CONTENT_HASH_EXCLUDES))


def request_fingerprint(envelope: dict) -> str:
    """The commit_outcome request fingerprint (FINGERPRINT_CONTRACT): JCS over
    every envelope field except submitted_at, so a replay is identical only
    if every authority-bearing field matches (design review §5 step 3)."""
    return logical_hash(_without(envelope, FINGERPRINT_EXCLUDES))


def bytes_digest(raw: bytes) -> str:
    """SHA-256 over bytes exactly as retained. Never parses or canonicalizes."""
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError("bytes_digest hashes retained bytes; pass bytes, not a decoded value")
    return _sha256(bytes(raw))
