"""GovInfo (api.data.gov key): primary federal documents — bills, budgets, reports, regulations."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from .base import NO_MEMBERS, OMIT, AdapterError, Client, Obj, PayloadError, check, counts_nothing, key, members, need, optional, plain, quote, text, token, total

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
    pid = key(SOURCE_ID, p.get("packageId"))
    dl = plain(optional(SOURCE_ID, p, "download", dict))   # a package that lists no formats has no `download`; one whose is not an object is unreadable
    links = [f"https://www.govinfo.gov/app/details/{pid}"] + [u for u in (text(SOURCE_ID, v) for v in dl.values()) if u]
    return make_record(identity=f"govinfo:{pid}", kind="document", source_id=SOURCE_ID, title=p.get("title"),
                       authors=[a for a in (text(SOURCE_ID, p.get("governmentAuthor1")), text(SOURCE_ID, p.get("governmentAuthor2"))) if a],
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
    results = need(SOURCE_ID, j, "results") if j.get("results") is not None or not counts_nothing(j.get("count")) else NO_MEMBERS
    # GovInfo documents only the continuation — `*` first, then the answer's offsetMark — and no last
    # page, nor what `count` counts: a mark that moves continues, and nothing here ever ends the lane
    # (docs/PROVIDER-PAGINATION.md); a mark handed back unchanged would only repeat this page
    mark = token(j.get("offsetMark"))
    nxt = mark if mark not in (None, offset_mark) else None
    return {"records": members(SOURCE_ID, results, _record), "total": total(j.get("count"), len(results)), "next_offset_mark": nxt,
            "exhausted": False}


def _summary(client: Client, pid: str, hdrs: dict, request_type: str) -> Obj | None:
    """The package's summary, None when there is no such package; an answer that is not one is unreadable."""
    resp = client.get(SOURCE_ID, request_type, f"{BASE}/packages/{quote(pid, safe='')}/summary", headers=hdrs, identity=f"govinfo:{pid}")
    if not check(SOURCE_ID, resp):
        return None
    summary = need(SOURCE_ID, resp.json, kind=dict)
    if not summary.get("packageId"):
        raise PayloadError(f"{SOURCE_ID}: the package summary carries no packageId")
    return summary


def resolve(client: Client, identity: str) -> dict | None:
    hdrs = _headers(client)
    if not hdrs:   # an unconfigured key is an auth fact, never "no such package"
        return {"capability_fact": "no api.data.gov key configured"}
    summary = _summary(client, _package_id(identity), hdrs, "resolve")
    return _record(summary) if summary is not None else None


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
        # the files are the formats the summary's `download` lists, each entry its own member, and need the package's title and nothing else of
        # it: its authors and dates cannot cost them
        summary = _summary(client, pid, hdrs, "resolve")
        if summary is None:
            return {"identity": identity, "records": []}
        title = text(SOURCE_ID, summary.get("title"))

        def file(entry: Obj):
            name = entry["key"]
            if not (name.endswith("Link") and name[:-4] in FORMATS):   # a link that is not one of the formats a download is asked for
                return OMIT
            f = name[:-4]
            return make_record(identity=f"{identity}#{f}", kind="file", source_id=SOURCE_ID, title=f"{title} ({f})" if title else f,
                               links=[f"{BASE}/packages/{pid}/{f}"], license="US Government work (public domain)", extra={"format": f}, raw=None)
        files = members(SOURCE_ID, optional(SOURCE_ID, summary, "download", dict).entries(), file)
        return {"identity": identity, "records": sorted(files, key=lambda r: (r is None, r["identity"] if r else ""))}
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
