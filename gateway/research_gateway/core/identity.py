"""Identifier normalisation and typed identities (PLAN.md §2, R-1).

An identity is a string `<scheme>:<value>` with a normalised value:
  doi:10.1000/abc   issn:1234-5678   arxiv:2301.10140   handle:1234/5678
  series:fred:GDP   url:https://...   title:<normalised title>
"""
from __future__ import annotations

import re

from . import schema as S
from .payload import PayloadError

_DOI_RE = re.compile(r"10\.\d{4,9}/\S+", re.I)
_ISSN_RE = re.compile(r"^\d{4}-?\d{3}[\dXx]$")
_ARXIV_NEW = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
_ARXIV_OLD = re.compile(r"^[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?$")
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,15}$")
KNOWN_SCHEMES = {"doi", "issn", "arxiv", "handle", "series", "url", "title", "pmid", "dataset", "repo",
                 # namespaces the gateway itself emits: index kinds, table identities, and per-source
                 # labels for records that carry no portable identifier (D-23)
                 "venue", "repository", "table", "s2", "doaj", "openaire", "datacite", "europepmc", "govinfo"}


_PLACEHOLDERS = frozenset({"none", "null", "undefined", "nan"})


def meaningful(identity) -> bool:
    """An identity that names something (task 2b-repair A4): `<scheme>:<value>` whose value
    does not end empty and has no `:`- or `#`-separated part that is a stringified missing
    value — never `url:None`, `openml:` or `series:fred:null` built from a provider member
    that carried no identifier, which would be a fabricated candidate. (An empty middle
    part stays: OpenAIRE's own ids read `50|doi_dedup___::0123...`.)"""
    if not isinstance(identity, str) or ":" not in identity:
        return False
    scheme, value = identity.split(":", 1)
    parts = re.split(r"[:#]", value)
    return (bool(scheme) and not any(c.isspace() for c in scheme) and bool(parts[-1].strip())
            and not any(part.strip().lower() in _PLACEHOLDERS for part in parts))


def register_schemes(schemes) -> None:
    """Adapters declare the identity schemes they serve (hf, openml, kaggle, ...); the router
    registers them at start-up so parse()/canonical() recognise them."""
    for s in schemes:
        s = str(s).lower()
        if _SCHEME_RE.match(s) and s not in {"http", "https", "ftp"}:
            KNOWN_SCHEMES.add(s)
_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/", "doi:", "DOI:")


def _identifier(value) -> str:
    """The text of an identifier a provider sent, "" when it sent none (missing, null). Anything that is not text — a number, `false`, a list —
    is not an identifier that happens to be empty, and no member of an answer may take it for one: PayloadError."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PayloadError(f"{type(value).__name__} where an identifier belongs")
    return value


def normalize_doi(value: str | None) -> str | None:
    """Lower-cased DOI without resolver prefix, or None if it is not a DOI (or there is none). Not text at all is unreadable."""
    value = _identifier(value)
    if not value:
        return None
    v = value.strip()
    for p in _DOI_PREFIXES:
        if v.startswith(p):
            v = v[len(p):]
    v = v.strip().rstrip(".,;)")
    m = _DOI_RE.search(v)
    if not m or m.start() != 0:
        return None
    return m.group(0).lower()


def normalize_issn(value: str | None) -> str | None:
    value = _identifier(value)
    if not value:
        return None
    v = value.strip().upper().replace(" ", "")
    if not _ISSN_RE.match(v):
        return None
    v = v.replace("-", "")
    return f"{v[:4]}-{v[4:]}"


def normalize_arxiv(value: str | None) -> str | None:
    value = _identifier(value)
    if not value:
        return None
    v = value.strip()
    for p in ("arxiv:", "arXiv:", "https://arxiv.org/abs/", "http://arxiv.org/abs/"):
        if v.startswith(p):
            v = v[len(p):]
    v = re.sub(r"v\d+$", "", v)
    if _ARXIV_NEW.match(v) or _ARXIV_OLD.match(v):
        return v
    return None


def normalize_title(value: str | None) -> str:
    """Lower-case, alphanumerics only, single-spaced; for fuzzy matching and cache keys."""
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def parse(identity: str) -> tuple[str, str]:
    """Split 'scheme:value'; bare DOIs/ISSNs/arXiv ids are recognised without a scheme."""
    s = identity.strip()
    if ":" in s:
        scheme, _, value = s.partition(":")
        scheme = scheme.lower()
        value = value.strip()
        # only declared schemes count (built-ins plus what the registry's adapters register),
        # so a title such as "AI:ML systems" or "Reranking: a survey" is never mistaken for one
        if scheme in KNOWN_SCHEMES and value:
            return scheme, value
    if normalize_doi(s):
        return "doi", normalize_doi(s)
    if normalize_issn(s):
        return "issn", normalize_issn(s)
    if normalize_arxiv(s):
        return "arxiv", normalize_arxiv(s)
    return "title", normalize_title(s)


def canonical(identity: str) -> str:
    """Normalised 'scheme:value' form used as the record/cache key."""
    scheme, value = parse(identity)
    if scheme == "doi":
        return f"doi:{normalize_doi(value) or value.lower()}"
    if scheme == "issn":
        return f"issn:{normalize_issn(value) or value.upper()}"
    if scheme == "arxiv":
        return f"arxiv:{normalize_arxiv(value) or value}"
    if scheme == "title":
        return f"title:{normalize_title(value)}"
    return f"{scheme}:{value}"


def doi_prefix(doi: str) -> str:
    return doi.split("/", 1)[0]


# doi.org/ra answers one object per DOI asked: the agency is its `RA` text, and `unknown` when it names none (a DOI doi.org does not know has no `RA`).
# An `RA` that is there and is not text — `false`, `0`, `[]`, `{}`, a number — is unreadable, not an unknown agency (and a number or a list is not an agency's name).
RA_ROWS = S.members(S.obj({"RA": S.text()}))


class RegistrationAgencies:
    """Which agency issued a DOI (Crossref, DataCite, mEDRA, ...) via doi.org/ra,
    cached by prefix — the prefix, not the suffix, determines the agency.
    The lookup itself is an outbound call and goes through the metered client."""

    URL = "https://doi.org/ra/"
    _shared: dict[str, str] = {}   # prefix → agency, shared by every instance in the process

    def __init__(self, client, cache: dict[str, str] | None = None):
        self._client = client
        self._cache = self._shared if cache is None else cache

    def agency(self, doi: str) -> str:
        prefix = doi_prefix(doi)
        if prefix in self._cache:
            return self._cache[prefix]
        resp = self._client.get("doi_org", "resolve", self.URL + doi, identity=f"doi:{doi}")
        if not resp.ok:
            return "unknown"   # a failed lookup is not remembered as the prefix's answer (task 2b)
        rows = resp.json   # an unreadable 200 raises PayloadError: the caller reports it, nothing is cached
        agency = None
        if isinstance(rows, list):   # one object per DOI asked, and one was: its first result, read like any lookup's
            try:
                agency = S.decode("doi.org", RA_ROWS, rows).first(lambda row: row["RA"] or "unknown")
            except PayloadError:   # a first result that is not an object, or whose `RA` is there and is not text, names no agency — and is not remembered as one
                return "unknown"
        agency = agency or "unknown"
        self._cache[prefix] = agency
        return agency
