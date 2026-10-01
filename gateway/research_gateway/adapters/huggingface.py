"""Hugging Face Hub datasets (optional token). Licence is per repository (card metadata / tags)."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from ..core.licenses import allow_listed
from .base import AdapterError, Client, Obj, PayloadError, check, key, listed, members, need, next_link, optional, own_link, plain, quote, text

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


def _license(d: Obj) -> str | None:
    """The repository's licence: its card's, else a `license:` tag; none when it states none. A card or tags that are there and are not
    what they should be (an object, a list) are unreadable, and so is a licence that is not text."""
    lic = plain(optional(SOURCE_ID, d, "cardData", dict).get("license"))
    if isinstance(lic, list) and all(isinstance(x, str) for x in lic):
        lic = ", ".join(lic)
    if lic is not None and not isinstance(lic, str):
        raise PayloadError(f"{SOURCE_ID}: the card's license is not text")
    if lic:
        return lic
    return next((t.split(":", 1)[1] for t in plain(optional(SOURCE_ID, d, "tags")) if isinstance(t, str) and t.startswith("license:")), None)


def _file_count(d: Obj) -> int | None:
    """How many files the Hub lists: none when it leaves `siblings` out, and unknown when it is there and cannot be read — never zero from a
    holder that was not read."""
    try:
        return len(optional(SOURCE_ID, d, "siblings"))
    except PayloadError:
        return None


def _record(d: Obj) -> dict:
    """A dataset's record. Its files are not read here: they are members of their own, listed by fetch() from the
    envelope, each decoded alone — a list of them copied into this record would be read by whatever builds this
    record, and one unreadable file would make the dataset unreadable with them (R7-2)."""
    repo, author = key(SOURCE_ID, d.get("id")), text(SOURCE_ID, d.get("author"))
    return make_record(identity=f"hf:{repo}", kind="dataset", source_id=SOURCE_ID, title=repo,
                       authors=[author] if author else [], year=year_from(text(SOURCE_ID, d.get("lastModified")) or text(SOURCE_ID, d.get("createdAt"))),
                       venue="Hugging Face Hub", identifiers={"repo_id": repo}, links=[f"{BASE}/datasets/{repo}"], license=_license(d),
                       extra={"tags": listed(SOURCE_ID, d, "tags"), "downloads": d.get("downloads"), "likes": d.get("likes"), "gated": d.get("gated", False),
                              "private": d.get("private", False), "description": (text(SOURCE_ID, d.get("description")) or "")[:1000],
                              "file_count": _file_count(d)},
                       raw=d)


def _context(d: Obj) -> dict:
    """What every file of a repository takes from it — its licence, and whether it is gated — and nothing else: the files are listed
    from `siblings`, so a field of the repository that no file needs (its author, its tags' other entries) cannot cost them (R8)."""
    return {"license": _license(d), "gated": d.get("gated", False)}


def _dataset(resp) -> Obj:
    """A dataset envelope from a successful answer, or PayloadError: a 200 without one is unreadable."""
    j = need(SOURCE_ID, resp.json, kind=dict)
    key(SOURCE_ID, j.get("id"))   # a dataset answer that names no dataset is not one
    return j


def _read(client: Client, request_type: str, url: str, identity: str) -> Obj | None:
    """The dataset envelope at `url`, None when the repository (or revision) is not there."""
    resp = client.get(SOURCE_ID, request_type, url, headers=_headers(client), identity=identity)
    return _dataset(resp) if check(SOURCE_ID, resp) else None


def _file(identity: str, repo: str, revision: str, license_: str | None, sibling: Obj) -> dict:
    """One file of the dataset, from the envelope's `siblings` member that names it."""
    name = sibling.get("rfilename")
    if not (isinstance(name, str) and name):
        raise PayloadError(f"{SOURCE_ID}: a file member of the dataset names no file")
    return make_record(identity=f"{identity}#{name}", kind="file", source_id=SOURCE_ID, title=name, license=license_,
                       links=[f"{BASE}/datasets/{repo}/resolve/{revision}/{name}"],
                       extra={"path": name, "revision": revision}, raw=None)


def find(client: Client, query: str, *, limit: int = 20, cursor: str | None = None) -> dict:
    """The Hub pages by its `Link: <url>; rel="next"` header, as its official clients do (huggingface_hub,
    utils/_pagination.py): the next URL already carries its parameters, and no next link is the end
    (docs/PROVIDER-PAGINATION.md). That URL is the lane's continuation, asked verbatim for the next page,
    but only while it stays this search on the Hub's own listing (base.own_link). A next link that
    does not is followed by nothing and ends nothing, and neither does a header that cannot be read
    (base.next_link: `known`): the end is an absence established by reading the whole header."""
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
    # the end is a header read whole that names no next link; one that could not be read is no end (R7-1)
    return {"records": members(SOURCE_ID, items, _record), "total": None,
            "next_cursor": own_link(link.url, listing, search=query), "exhausted": link.url is None and link.known}


def resolve(client: Client, identity: str) -> dict | None:
    repo = _repo(identity)
    d = _read(client, "resolve", f"{BASE}/api/datasets/{quote(repo, safe='/')}", f"hf:{repo}")
    # an HTTP 200 that is not a dataset envelope is not a record (D-24) — and not "no such
    # dataset" either: it is an unreadable answer (task 2b, H-5), which _dataset raises
    return _record(d) if d is not None else None


def fetch(client: Client, target: str, *, path: str | None = None, download: bool = False, revision: str = "main") -> dict:
    """List a dataset's files; with download=True and path, return that file's bytes (never persisted)."""
    repo = _repo(target)
    identity = f"hf:{repo}"
    if download:
        if not path:
            raise AdapterError("huggingface.fetch download needs path")
        # the licence of the EXACT revision being downloaded, not the default branch's (D-24)
        rev_url = f"{BASE}/api/datasets/{quote(repo, safe='/')}" + (f"/revision/{quote(revision, safe='')}" if revision != "main" else "")
        d = _read(client, "fetch", rev_url, f"hf:{repo}@{revision}")
        if d is None:
            return {"identity": identity, "records": [], "capability_fact": f"repository (revision {revision}) not found"}
        rec = _context(d)
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
        d = _read(client, "fetch", rev_url, f"hf:{repo}@{revision}")
        if d is None:
            return {"identity": identity, "records": [], "capability_fact": f"repository (revision {revision}) not found"}
    else:
        d = _read(client, "resolve", f"{BASE}/api/datasets/{quote(repo, safe='/')}", identity)
        if d is None:
            return {"identity": identity, "records": []}
    rec = _context(d)
    # the files are the envelope's `siblings`, each decoded alone: one that cannot be read costs that file only; a `siblings` that is
    # there and is not a list is not a repository with no files
    files = members(SOURCE_ID, optional(SOURCE_ID, d, "siblings"), lambda sibling: _file(identity, repo, revision, rec["license"], sibling))
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
