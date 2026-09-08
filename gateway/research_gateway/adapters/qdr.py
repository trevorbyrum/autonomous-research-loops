"""Qualitative Data Repository (a Dataverse instance): interviews, field notes. Personal use only."""
from __future__ import annotations

from . import harvard_dataverse as dv
from .base import Client

SOURCE_ID = "qdr"
SMOKE = {'capability': 'find', 'query': 'interview', 'limit': 1}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve")
SCHEMES = ("doi",)
BASE = "https://data.qdr.syr.edu"


def find(client: Client, query: str, *, limit: int = 20, page: int = 1) -> dict:
    return dv.find_in(client, BASE, SOURCE_ID, SOURCE_ID, query, limit=limit, page=page)


def resolve(client: Client, identity: str) -> dict | None:
    d = dv.get_dataset(client, BASE, SOURCE_ID, SOURCE_ID, identity, "resolve")
    return dv.dataset_record(BASE, SOURCE_ID, d) if d else None


def download_request(record: dict, target: str) -> dict | None:
    return dv.download_request(record, target)
