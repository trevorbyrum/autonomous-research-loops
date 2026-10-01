"""Hugging Face Hub datasets (optional token). Licence is per repository (card metadata / tags)."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from ..core.licenses import allow_listed
from .base import AdapterError, Client, PayloadError, check, members, need, next_link, own_link, quote

SOURCE_ID = "huggingface"
SMOKE = {'capability': 'resolve', 'identity': 'stanfordnlp/imdb'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve", "fetch")
SCHEMES = ("hf",)
BASE = "https://huggingface.co"


def _headers(client: Client) -> dict:
    tok = client.secret("huggingface")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _repo(target: str) -> str:
    repo = target.split(":", 1)[-1] if target.startswith("hf:") else target
    if not repo or repo.startswith("/") or repo.endswith("/"):
        raise AdapterError("huggingface target must be 'hf:<owner>/<name>' or a dataset id")
    return repo


def _license(d: dict) -> str | None:
    card = d.get("cardData") or {}
    lic = card.get("license")
    if isinstance(lic, list):
        lic = ", ".join(str(x) for x in lic)
    if lic:
        return str(lic)
    return next((t.split(":", 1)[1] for t in d.get("tags") or [] if t.startswith("license:")), None)


def _record(d: dict) -> dict:
    repo = d.get("id")
    return make_record(identity=f"hf:{repo}", kind="dataset", source_id=SOURCE_ID, title=repo,
                       authors=[d.get("author")] if d.get("author") else [], year=year_from(d.get("lastModified") or d.get("createdAt")),
                       venue="Hugging Face Hub", identifiers={"repo_id": repo}, links=[f"{BASE}/datasets/{repo}"], license=_license(d),
                       extra={"tags": d.get("tags") or [], "downloads": d.get("downloads"), "likes": d.get("likes"), "gated": d.get("gated", False),
                              "private": d.get("private", False), "description": (d.get("description") or "")[:1000],
                              "files": [s.get("rfilename") for s in d.get("siblings") or []]},
                       raw=d)


def _dataset(resp) -> dict:
    """A dataset envelope from a successful answer, or PayloadError: a 200 without one is unreadable."""
    j = need(SOURCE_ID, resp.json, kind=dict)
    if not j.get("id"):
        raise PayloadError(f"{SOURCE_ID}: the dataset answer carries no id")
    return j


def find(client: Client, query: str, *, limit: int = 20, cursor: str | None = None) -> dict:
    """The Hub pages by its `Link: <url>; rel="next"` header, as its official clients do (huggingface_hub,
    utils/_pagination.py): the next URL already carries its parameters, and no next link is the end
    (docs/PROVIDER-PAGINATION.md). That URL is the lane's continuation, asked verbatim for the next page,
    but only while it stays this search on the Hub's own listing (base.own_link). A next link that
    does not is followed by nothing and ends nothing."""
    listing = f"{BASE}/api/datasets"
    if cursor is None:
        url, params = listing, {"search": query, "limit": min(limit, 100), "full": "true"}
    else:
        url, params = own_link(cursor, listing, search=query), None
        if url is None:
            raise ValueError(f"{SOURCE_ID}: not a continuation this lane gave")
    resp = client.get(SOURCE_ID, "find", url, params=params, headers=_headers(client), query=query)
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    items = need(SOURCE_ID, resp.json)
    link = next_link(resp)
    return {"records": members(SOURCE_ID, items, _record), "total": None,
            "next_cursor": own_link(link, listing, search=query), "exhausted": link is None}


def resolve(client: Client, identity: str) -> dict | None:
    repo = _repo(identity)
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/api/datasets/{quote(repo, safe='/')}", headers=_headers(client), identity=f"hf:{repo}")
    if not check(SOURCE_ID, resp):
        return None
    j = need(SOURCE_ID, resp.json, kind=dict)
    if not j.get("id"):
        # an HTTP 200 that is not a dataset envelope is not a record (D-24) — and not "no such
        # dataset" either: it is an unreadable answer (task 2b, H-5)
        raise PayloadError(f"{SOURCE_ID}: the dataset answer carries no id")
    return _record(j)


def fetch(client: Client, target: str, *, path: str | None = None, download: bool = False, revision: str = "main") -> dict:
    """List a dataset's files; with download=True and path, return that file's bytes (never persisted)."""
    repo = _repo(target)
    identity = f"hf:{repo}"
    if download:
        if not path:
            raise AdapterError("huggingface.fetch download needs path")
        # the licence of the EXACT revision being downloaded, not the default branch's (D-24)
        rev_url = f"{BASE}/api/datasets/{quote(repo, safe='/')}" + (f"/revision/{quote(revision, safe='')}" if revision != "main" else "")
        meta = client.get(SOURCE_ID, "fetch", rev_url, headers=_headers(client), identity=f"hf:{repo}@{revision}")
        if not check(SOURCE_ID, meta):
            return {"identity": identity, "records": [], "capability_fact": f"repository (revision {revision}) not found"}
        rec = _record(_dataset(meta))
        if client.commercial and not allow_listed(rec["license"]):
            return {"identity": identity, "records": [],
                    "capability_fact": f"download refused before fetching: licence {rec['license'] or 'unknown'} is not usable commercially (R-8)"}
        url = f"{BASE}/datasets/{quote(repo, safe='/')}/resolve/{quote(revision, safe='')}/{quote(path, safe='/')}"
        resp = client.get(SOURCE_ID, "fetch", url, headers={**_headers(client), "Accept": "*/*"}, identity=f"{identity}#{path}")
        if not check(SOURCE_ID, resp, allow_html=True):  # raw file download: an HTML document can be legitimate content here
            return {"identity": identity, "records": []}
        return {"identity": identity, "records": [], "content": resp.body,
                "content_type": resp.headers.get("content-type"), "license": rec["license"], "gated": rec["gated"]}
    if revision != "main":
        # the LISTING must come from the requested revision too — reading main and
        # stamping the requested revision generated downloads of files that revision
        # does not contain (D-32a finding 1)
        rev_url = f"{BASE}/api/datasets/{quote(repo, safe='/')}/revision/{quote(revision, safe='')}"
        meta = client.get(SOURCE_ID, "fetch", rev_url, headers=_headers(client), identity=f"hf:{repo}@{revision}")
        if not check(SOURCE_ID, meta):
            return {"identity": identity, "records": [], "capability_fact": f"repository (revision {revision}) not found"}
        rec = _record(_dataset(meta))
    else:
        rec = resolve(client, identity)
    if rec is None:
        return {"identity": identity, "records": []}
    files = [make_record(identity=f"{identity}#{f}", kind="file", source_id=SOURCE_ID, title=f, license=rec["license"],
                         links=[f"{BASE}/datasets/{repo}/resolve/{revision}/{f}"],
                         extra={"path": f, "revision": revision}, raw=None) for f in rec["files"]]
    return {"identity": identity, "records": files, "gated": rec["gated"]}


def download_request(record: dict, target: str) -> dict | None:
    """The COMPLETE research_download call for one listed file (D-31a): parent repo target,
    the file's path, and the REVISION the listing was taken at (the licence check is
    revision-exact, D-24)."""
    path = record.get("path") or (record.get("extra") or {}).get("path")
    if not path:
        return None
    revision = record.get("revision") or (record.get("extra") or {}).get("revision") or "main"
    return {"target": target, "params": {"path": path, "revision": revision}}
