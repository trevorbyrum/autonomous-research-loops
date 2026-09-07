"""OpenCitations: citation links for a DOI (enrichment only)."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi
from .base import Client, check

SOURCE_ID = "opencitations"
CAPABILITIES = ("enrich",)
INDEX = "https://api.opencitations.net/index/v2"
META = "https://api.opencitations.net/meta/v1"


def _doi_of(identity: str) -> str | None:
    return normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)


def _links(rows: list[dict], key: str) -> list[dict]:
    items = []
    for r in rows:
        ref = r.get(key) or ""
        for part in ref.split(" "):
            if part.startswith("doi:"):
                items.append(make_record(identity=f"doi:{normalize_doi(part[4:]) or part[4:]}", kind="citation",
                                         source_id=SOURCE_ID, year=year_from(r.get("creation")),
                                         identifiers={"doi": normalize_doi(part[4:]) or part[4:]},
                                         extra={"oci": r.get("oci"), "timespan": r.get("timespan")},
                                         raw={k: r.get(k) for k in ("oci", "citing", "cited", "creation", "timespan")}))
                break
    return items


def enrich(client: Client, identity: str, what: str = "citations") -> dict:
    """citations: works citing this DOI; references: works this DOI cites; metadata: OpenCitations Meta record."""
    doi = _doi_of(identity)
    if not doi:
        return {"identity": identity, "what": what, "items": []}
    if what == "metadata":
        resp = client.get(SOURCE_ID, "enrich", f"{META}/metadata/doi:{doi}", identity=f"doi:{doi}")
        if not check(SOURCE_ID, resp) or not isinstance(resp.json, list) or not resp.json:
            return {"identity": f"doi:{doi}", "what": what, "items": []}
        m = resp.json[0]
        rec = make_record(identity=f"doi:{doi}", kind="article", source_id=SOURCE_ID, title=m.get("title"),
                          authors=[a.strip() for a in (m.get("author") or "").split(";") if a.strip()],
                          year=year_from(m.get("pub_date")), venue=(m.get("venue") or "").split(" [")[0] or None,
                          identifiers={"doi": doi}, raw=m)
        return {"identity": f"doi:{doi}", "what": what, "items": [rec]}
    if what not in ("citations", "references"):
        return {"identity": f"doi:{doi}", "what": what, "items": []}
    resp = client.get(SOURCE_ID, "enrich", f"{INDEX}/{what}/doi:{doi}", identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp) or not isinstance(resp.json, list):
        return {"identity": f"doi:{doi}", "what": what, "items": []}
    key = "citing" if what == "citations" else "cited"
    return {"identity": f"doi:{doi}", "what": what, "items": _links(resp.json, key)}
