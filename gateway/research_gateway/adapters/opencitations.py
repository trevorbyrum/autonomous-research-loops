"""OpenCitations: citation links for a DOI (enrichment only)."""
from __future__ import annotations

from ..core import schema as S
from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi
from .base import OMIT, Client, check, decode, first_member, members

SOURCE_ID = "opencitations"
SMOKE = {'capability': 'enrich', 'identity': 'doi:10.1162/qss_a_00023', 'what': 'references'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("enrich",)
ENRICHES = ("citations", "references", "metadata")
INDEX = "https://api.opencitations.net/index/v2"
META = "https://api.opencitations.net/meta/v1"

# What an answer must be: a list of rows. A citation row names the work on its `citing` end (citations) or its `cited` end (references); the other end is the
# DOI that was asked about.
def _row(end: str) -> S.Spec:
    return S.obj({end: S.text(), "creation": S.text(), "oci": S.any_(), "timespan": S.any_()})


CITATIONS, REFERENCES = S.members(_row("citing")), S.members(_row("cited"))
METADATA = S.members(S.obj({"title": S.text(), "author": S.text(), "pub_date": S.text(), "venue": S.text()}))
SCHEMAS = {"enrich:citations": CITATIONS, "enrich:references": REFERENCES, "enrich:metadata": METADATA}


def _doi_of(identity: str) -> str | None:
    return normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)


def _link(key: str, row):
    """One citation row: the work on its `key` end, or OMIT when that end names no DOI."""
    doi = next((part[4:] for part in (row[key] or "").split(" ") if part.startswith("doi:")), None)
    if doi is None:
        return OMIT
    doi = normalize_doi(doi) or doi
    return make_record(identity=f"doi:{doi}", kind="citation", source_id=SOURCE_ID, year=year_from(row["creation"]),
                       identifiers={"doi": doi}, extra={"oci": row["oci"], "timespan": row["timespan"]}, raw=row.raw)


def _article(doi: str, m) -> dict:
    """OpenCitations Meta's record for `doi`."""
    return make_record(identity=f"doi:{doi}", kind="article", source_id=SOURCE_ID, title=m["title"],
                       authors=[a.strip() for a in (m["author"] or "").split(";") if a.strip()],
                       year=year_from(m["pub_date"]), venue=(m["venue"] or "").split(" [")[0] or None,
                       identifiers={"doi": doi}, raw=m.raw)


def enrich(client: Client, identity: str, what: str = "citations") -> dict:
    """citations: works citing this DOI; references: works this DOI cites; metadata: OpenCitations Meta record."""
    doi = _doi_of(identity)
    if not doi:
        return {"identity": identity, "what": what, "items": []}
    if what == "metadata":
        resp = client.get(SOURCE_ID, "enrich", f"{META}/metadata/doi:{doi}", identity=f"doi:{doi}")
        if not check(SOURCE_ID, resp):
            return {"identity": f"doi:{doi}", "what": what, "items": []}
        # a list, empty when OpenCitations Meta has no record; its first result is read like any lookup's
        rec = first_member(SOURCE_ID, decode(SOURCE_ID, METADATA, resp.json), lambda m: _article(doi, m))
        return {"identity": f"doi:{doi}", "what": what, "items": [rec] if rec else []}
    if what not in ("citations", "references"):
        return {"identity": f"doi:{doi}", "what": what, "items": []}
    resp = client.get(SOURCE_ID, "enrich", f"{INDEX}/{what}/doi:{doi}", identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return {"identity": f"doi:{doi}", "what": what, "items": []}
    key = "citing" if what == "citations" else "cited"
    rows = decode(SOURCE_ID, SCHEMAS[f"enrich:{what}"], resp.json)
    return {"identity": f"doi:{doi}", "what": what, "items": members(SOURCE_ID, rows, lambda row: _link(key, row))}
