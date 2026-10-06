"""Hugging Face Hub datasets (optional token). Licence is per repository (card metadata / tags)."""
from __future__ import annotations

from ..core import schema as S
from ..core.canonical import make_record, year_from
from ..core.licenses import allow_listed
from ._links import next_link, own_link
from .base import AdapterError, Client, PayloadError, check, decode, members, quote

SOURCE_ID = "huggingface"
SMOKE = {'capability': 'resolve', 'identity': 'stanfordnlp/imdb'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve", "fetch")
SCHEMES = ("hf",)
BASE = "https://huggingface.co"

# What an answer must be. A repository's licence is its card's, else a `license:` tag: both places are declared, so both are decoded before one is chosen (R10-1).
# A card's licence is text or a list of text; the tags are a list the repository's other entries may fill with anything. A listing needs only a dataset's name and
# its licence and gating from the repository (R8): its files are the `siblings` members, each decoded alone, so a field no file needs cannot cost them.
# A repository's tags are text where they are text and anything else where they are not (a licence is read from the text ones; the others are only stored), and it is gated or not
# (`false`, `true`, or the Hub's own `"auto"`/`"manual"`). The flag is returned to the caller, so it is a kind (2b-repair-13a, R12-1); `soft`, because one that cannot be read says
# nothing (None: gating unknown) and costs no file beside it.
_LICENSED = {"cardData": S.obj({"license": S.oneof(S.text(), S.own(S.text()))}), "tags": S.own(S.oneof(S.text(), S.any_())), "gated": S.soft(S.oneof(S.flag(), S.text()))}
DATASET = S.obj({"id": S.key(), "author": S.text(), "lastModified": S.text(), "createdAt": S.text(), **_LICENSED, "downloads": S.any_(), "likes": S.any_(),
                 "private": S.any_(default=False), "description": S.text(),
                 "siblings": S.soft(S.own(S.any_()))},   # only counted: a list that cannot be read is a count that is unknown, never zero
                alts=(("lastModified", "createdAt"), ("cardData.license", "tags")))
FILES = S.obj({"id": S.key(), **_LICENSED, "siblings": S.members(S.obj({"rfilename": S.text()}))}, alts=(("cardData.license", "tags"),))
SCHEMAS = {"find": S.members(DATASET), "resolve": DATASET, "fetch": FILES}


def _headers(client: Client) -> dict:
    tok = client.secret("huggingface")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def _repo(target: str) -> str:
    repo = target.split(":", 1)[-1] if target.startswith("hf:") else target
    if not repo or repo.startswith("/") or repo.endswith("/"):
        raise AdapterError("huggingface target must be 'hf:<owner>/<name>' or a dataset id")
    return repo


def _license(d) -> str | None:
    """The repository's licence: its card's, else a `license:` tag; none when it states none. Both places were decoded (a card licence that is not text,
    a tags list that is not a list) before either is chosen (R10-1)."""
    lic = d["cardData"]["license"]
    if isinstance(lic, list):
        lic = ", ".join(lic)
    tagged = next((t.split(":", 1)[1] for t in d["tags"] if isinstance(t, str) and t.startswith("license:")), None)
    return lic or tagged


def _record(d) -> dict:
    """A dataset's record. Its files are not read here: they are members of their own, listed by fetch() from the
    envelope, each decoded alone — a list of them copied into this record would be read by whatever builds this
    record, and one unreadable file would make the dataset unreadable with them (R7-2)."""
    repo, author = str(d["id"]), d["author"]
    return make_record(identity=f"hf:{repo}", kind="dataset", source_id=SOURCE_ID, title=repo,
                       authors=[author] if author else [], year=year_from(d["lastModified"] or d["createdAt"]),
                       venue="Hugging Face Hub", identifiers={"repo_id": repo}, links=[f"{BASE}/datasets/{repo}"], license=_license(d),
                       extra={"tags": d["tags"], "downloads": d["downloads"], "likes": d["likes"], "gated": d["gated"],
                              "private": d["private"], "description": (d["description"] or "")[:1000],
                              "file_count": None if d["siblings"] is None else len(d["siblings"])},
                       raw=d.raw)


def _context(d) -> dict:
    """What every file of a repository takes from it — its licence, and whether it is gated — and nothing else: the files are listed
    from `siblings`, so a field of the repository that no file needs (its author, its tags' other entries) cannot cost them (R8)."""
    return {"license": _license(d), "gated": d["gated"]}


def _read(client: Client, request_type: str, url: str, identity: str, schema):
    """The dataset envelope at `url` as `schema` decodes it, None when the repository (or revision) is not there. A 200 without a dataset is unreadable."""
    resp = client.get(SOURCE_ID, request_type, url, headers=_headers(client), identity=identity)
    return decode(SOURCE_ID, schema, resp) if check(SOURCE_ID, resp) else None


def _file(identity: str, repo: str, revision: str, license_: str | None, sibling) -> dict:
    """One file of the dataset, from the envelope's `siblings` member that names it."""
    name = sibling["rfilename"]
    if not name:
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
    items = decode(SOURCE_ID, SCHEMAS["find"], resp)
    link = next_link(resp)
    # the end is a header read whole that names no next link; one that could not be read is no end (R7-1)
    return {"records": members(SOURCE_ID, items, _record), "total": None,
            "next_cursor": own_link(link.url, listing, search=query), "exhausted": link.url is None and link.known}


def resolve(client: Client, identity: str) -> dict | None:
    repo = _repo(identity)
    d = _read(client, "resolve", f"{BASE}/api/datasets/{quote(repo, safe='/')}", f"hf:{repo}", SCHEMAS["resolve"])
    # an HTTP 200 that is not a dataset envelope is not a record (D-24) — and not "no such
    # dataset" either: it is an unreadable answer (task 2b, H-5), which the schema's required `id` makes it
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
        d = _read(client, "fetch", rev_url, f"hf:{repo}@{revision}", FILES)
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
        return {"identity": identity, "records": [], "content": resp.download(),
                "content_type": resp.headers.get("content-type"), "license": rec["license"], "gated": rec["gated"]}
    if revision != "main":
        # the LISTING must come from the requested revision too — reading main and
        # stamping the requested revision generated downloads of files that revision
        # does not contain (D-32a finding 1)
        rev_url = f"{BASE}/api/datasets/{quote(repo, safe='/')}/revision/{quote(revision, safe='')}"
        d = _read(client, "fetch", rev_url, f"hf:{repo}@{revision}", FILES)
        if d is None:
            return {"identity": identity, "records": [], "capability_fact": f"repository (revision {revision}) not found"}
    else:
        d = _read(client, "resolve", f"{BASE}/api/datasets/{quote(repo, safe='/')}", identity, FILES)
        if d is None:
            return {"identity": identity, "records": []}
    rec = _context(d)
    # the files are the envelope's `siblings`, each decoded alone: one that cannot be read costs that file only; a `siblings` that is
    # there and is not a list is not a repository with no files
    files = members(SOURCE_ID, d["siblings"], lambda sibling: _file(identity, repo, revision, rec["license"], sibling))
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
