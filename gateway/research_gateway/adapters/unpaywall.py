"""Unpaywall: open-access location for a DOI (enrichment only, never discovery)."""
from __future__ import annotations

from ..core.canonical import make_record
from ..core.identity import normalize_doi
from .base import Client, check

SOURCE_ID = "unpaywall"
CAPABILITIES = ("enrich",)
BASE = "https://api.unpaywall.org/v2"


def enrich(client: Client, identity: str, what: str = "oa_location") -> dict:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi or what != "oa_location":
        return {"identity": identity, "what": what, "items": []}
    resp = client.get(SOURCE_ID, "enrich", f"{BASE}/{doi}", params={"email": client.contact_email},
                      identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return {"identity": f"doi:{doi}", "what": what, "items": []}
    j = resp.json or {}
    items = []
    best = j.get("best_oa_location") or {}
    locations = j.get("oa_locations") or ([best] if best else [])
    for loc in locations:
        url = loc.get("url_for_pdf") or loc.get("url")
        if not url:
            continue
        items.append(make_record(
            identity=f"doi:{doi}", kind="oa_location", source_id=SOURCE_ID, title=j.get("title"),
            year=j.get("year"), venue=j.get("journal_name"), identifiers={"doi": doi}, links=[url],
            license=loc.get("license"),
            extra={"is_oa": j.get("is_oa"), "oa_status": j.get("oa_status"), "host_type": loc.get("host_type"),
                   "version": loc.get("version"), "is_best": loc is best or loc == best},
            raw={k: loc.get(k) for k in ("url", "url_for_pdf", "license", "host_type", "version", "evidence")},
        ))
    return {"identity": f"doi:{doi}", "what": what, "items": items,
            "is_oa": j.get("is_oa"), "oa_status": j.get("oa_status")}
