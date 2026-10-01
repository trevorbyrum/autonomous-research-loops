"""GovInfo (api.data.gov key): primary federal documents — bills, budgets, reports, regulations."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from .base import AdapterError, Client, PayloadError, check, members, need, quote

SOURCE_ID = "govinfo"
SMOKE = {'capability': 'find', 'query': 'artificial intelligence', 'limit': 1}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve", "fetch")
BASE = "https://api.govinfo.gov"
FORMATS = ("pdf", "htm", "xml", "txt", "zip")


def _headers(client: Client) -> dict | None:
    key = client.secret("api_data_gov")
    return {"X-Api-Key": key} if key else None


def _package_id(target: str) -> str:
    return target.split(":", 1)[-1] if target.startswith("govinfo:") else target


def _record(p: dict) -> dict:
    pid = p.get("packageId")
    dl = p.get("download") or {}
    links = [f"https://www.govinfo.gov/app/details/{pid}"] + [v for v in dl.values() if isinstance(v, str)]
    return make_record(identity=f"govinfo:{pid}", kind="document", source_id=SOURCE_ID, title=p.get("title"),
                       authors=[a for a in (p.get("governmentAuthor1"), p.get("governmentAuthor2")) if a],
                       year=year_from(p.get("dateIssued")), venue=p.get("collectionCode"),
                       identifiers={"package_id": pid}, links=links, license="US Government work (public domain)",
                       extra={"date_issued": p.get("dateIssued"), "last_modified": p.get("lastModified"),
                              "doc_class": p.get("docClass"),
                              "formats": sorted(k[:-4] for k in dl if k.endswith("Link") and k[:-4] in FORMATS)},
                       raw=p)


def find(client: Client, query: str, *, limit: int = 20, offset_mark: str = "*", collection: str | None = None) -> dict:
    hdrs = _headers(client)
    if not hdrs:
        return {"records": [], "total": 0, "next_offset_mark": None, "capability_fact": "no api.data.gov key configured"}
    q = f"{query} collection:({collection})" if collection else query
    body = {"query": q, "pageSize": min(limit, 100), "offsetMark": offset_mark,
            "sorts": [{"field": "score", "sortOrder": "DESC"}]}
    resp = client.post(SOURCE_ID, "find", f"{BASE}/search", body=body, headers=hdrs, query=query)
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    j = need(SOURCE_ID, resp.json, kind=dict)
    # an answer may leave `results` out only when it counts nothing
    results = need(SOURCE_ID, j, "results") if j.get("results") is not None or j.get("count") != 0 else []
    # GovInfo documents only the continuation — `*` first, then the answer's offsetMark — and no last
    # page, nor what `count` counts: a mark that moves continues, and nothing here ever ends the lane
    # (docs/PROVIDER-PAGINATION.md); a mark handed back unchanged would only repeat this page
    nxt = j.get("offsetMark") if j.get("offsetMark") not in (None, offset_mark) else None
    return {"records": members(SOURCE_ID, results, _record), "total": j.get("count"), "next_offset_mark": nxt,
            "exhausted": False}


def resolve(client: Client, identity: str) -> dict | None:
    hdrs = _headers(client)
    if not hdrs:   # an unconfigured key is an auth fact, never "no such package"
        return {"capability_fact": "no api.data.gov key configured"}
    pid = _package_id(identity)
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/packages/{quote(pid, safe='')}/summary", headers=hdrs, identity=f"govinfo:{pid}")
    if not check(SOURCE_ID, resp):
        return None
    summary = need(SOURCE_ID, resp.json, kind=dict)
    if not summary.get("packageId"):
        raise PayloadError(f"{SOURCE_ID}: the package summary carries no packageId")
    return _record(summary)


def fetch(client: Client, target: str, *, fmt: str = "pdf", download: bool = False) -> dict:
    """List a package's download links; with download=True return the bytes of one format (never persisted)."""
    if fmt not in FORMATS:
        raise AdapterError(f"govinfo.fetch fmt must be one of {FORMATS}")
    pid = _package_id(target)
    identity = f"govinfo:{pid}"
    hdrs = _headers(client)
    if not hdrs:
        return {"identity": identity, "records": [], "capability_fact": "no api.data.gov key configured"}
    if not download:
        rec = resolve(client, identity)
        if rec is None or rec.get("capability_fact"):
            return {"identity": identity, "records": [], **({"capability_fact": rec["capability_fact"]} if rec else {})}
        files = [make_record(identity=f"{identity}#{f}", kind="file", source_id=SOURCE_ID, title=f"{rec['title']} ({f})",
                             links=[f"{BASE}/packages/{pid}/{f}"], license=rec["license"], extra={"format": f}, raw=None)
                 for f in rec["formats"] if f in FORMATS]
        return {"identity": identity, "records": files}
    resp = client.get(SOURCE_ID, "fetch", f"{BASE}/packages/{quote(pid, safe='')}/{fmt}", headers={**hdrs, "Accept": "*/*"}, identity=identity)
    if not check(SOURCE_ID, resp, allow_html=True):  # raw file download: an HTML document can be legitimate content here
        return {"identity": identity, "records": []}
    return {"identity": identity, "records": [], "content": resp.body, "content_type": resp.headers.get("content-type"),
            "format": fmt, "license": "US Government Work"}


def download_request(record: dict, target: str) -> dict | None:
    """The COMPLETE research_download call for one listed format (D-31a): the PARENT
    target plus this adapter's own selector — never a fragment-mangled identity."""
    fmt = record.get("format") or (record.get("extra") or {}).get("format")
    return {"target": target, "params": {"fmt": fmt}} if fmt else None
