"""GLOBE project: static data files on globeproject.com (commercial verdict unknown → fails closed)."""
from __future__ import annotations

from ..core.canonical import make_record
from .base import AdapterError, Client, check

SOURCE_ID = "globe"
SMOKE = {'local': 'static files; nothing to probe without a file URL'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("fetch",)
SCHEMES = ("url",)
HOST = "https://globeproject.com/"
DATA_PAGE = HOST + "data/"


def fetch(client: Client, target: str | None = None, *, download: bool = False) -> dict:
    """Without a target: the record for the data page. With a globeproject.com URL and download=True: that file's bytes."""
    if not target:
        rec = make_record(identity="url:" + DATA_PAGE, kind="dataset", source_id=SOURCE_ID, title="GLOBE Project data files",
                          links=[DATA_PAGE], extra={"note": "file list is maintained on the page; pass a file URL to fetch one"}, raw=None)
        return {"identity": rec["identity"], "records": [rec]}
    url = target.split(":", 1)[-1] if target.startswith("url:") else target
    if not url.startswith(HOST):
        raise AdapterError("globe.fetch only serves globeproject.com URLs")
    identity = "url:" + url
    if not download:
        rec = make_record(identity=identity, kind="file", source_id=SOURCE_ID, title=url.rsplit("/", 1)[-1], links=[url], raw=None)
        return {"identity": identity, "records": [rec]}
    resp = client.get(SOURCE_ID, "fetch", url, headers={"Accept": "*/*"}, identity=identity)
    if not check(SOURCE_ID, resp, allow_html=True):  # raw file download: an HTML document can be legitimate content here
        return {"identity": identity, "records": []}
    return {"identity": identity, "records": [], "content": resp.body, "content_type": resp.headers.get("content-type")}


def download_request(record: dict, target: str) -> dict | None:
    """The COMPLETE research_download call for one listed file (D-31a)."""
    link = (record.get("links") or [None])[0]
    return {"target": link, "params": {}} if link else None
