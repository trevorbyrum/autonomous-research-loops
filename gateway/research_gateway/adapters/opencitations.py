"""OpenCitations: citation links for a DOI (enrichment only)."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi
from .base import OMIT, Client, check, members, need

SOURCE_ID = "opencitations"
SMOKE = {'capability': 'enrich', 'identity': 'doi:10.1162/qss_a_00023', 'what': 'references'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("enrich",)
ENRICHES = ("citations", "references", "metadata")
INDEX = "https://api.opencitations.net/index/v2"
META = "https://api.opencitations.net/meta/v1"


def _doi_of(identity: str) -> str | None:
    return normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)


def _link(key: str, row: dict):
    """One citation row: the work on its `key` end, or OMIT when that end names no DOI."""
    doi = next((part[4:] for part in (row.get(key) or "").split(" ") if part.startswith("doi:")), None)
    if doi is None:
        return OMIT
    doi = normalize_doi(doi) or doi
    return make_record(identity=f"doi:{doi}", kind="citation", source_id=SOURCE_ID, year=year_from(row.get("creation")),
                       identifiers={"doi": doi}, extra={"oci": row.get("oci"), "timespan": row.get("timespan")}, raw=row)


def enrich(client: Client, identity: str, what: str = "citations") -> dict:
    """citations: works citing this DOI; references: works this DOI cites; metadata: OpenCitations Meta record."""
    doi = _doi_of(identity)
    if not doi:
        return {"identity": identity, "what": what, "items": []}
    if what == "metadata":
        resp = client.get(SOURCE_ID, "enrich", f"{META}/metadata/doi:{doi}", identity=f"doi:{doi}")
        if not check(SOURCE_ID, resp):
            return {"identity": f"doi:{doi}", "what": what, "items": []}
        rows = need(SOURCE_ID, resp.json)   # a list; empty when OpenCitations Meta has no record
        if not rows:
            return {"identity": f"doi:{doi}", "what": what, "items": []}
        m = need(SOURCE_ID, rows[0], kind=dict)
        rec = make_record(identity=f"doi:{doi}", kind="article", source_id=SOURCE_ID, title=m.get("title"),
                          authors=[a.strip() for a in (m.get("author") or "").split(";") if a.strip()],
                          year=year_from(m.get("pub_date")), venue=(m.get("venue") or "").split(" [")[0] or None,
                          identifiers={"doi": doi}, raw=m)
        return {"identity": f"doi:{doi}", "what": what, "items": [rec]}
    if what not in ("citations", "references"):
        return {"identity": f"doi:{doi}", "what": what, "items": []}
    resp = client.get(SOURCE_ID, "enrich", f"{INDEX}/{what}/doi:{doi}", identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return {"identity": f"doi:{doi}", "what": what, "items": []}
    key = "citing" if what == "citations" else "cited"
    return {"identity": f"doi:{doi}", "what": what, "items": members(SOURCE_ID, need(SOURCE_ID, resp.json), lambda row: _link(key, row))}
