"""World Management Survey public data, served from Harvard Dataverse under its own rate row."""
from __future__ import annotations

from . import harvard_dataverse as dv
from .base import Client

SOURCE_ID = "wms"
CAPABILITIES = ("fetch",)
DOI = "10.7910/DVN/OY6CBK"


def fetch(client: Client, target: str | None = None, *, file_id=None, download: bool = False) -> dict:
    """target is ignored except to confirm the WMS DOI; the survey lives at one dataset."""
    if target and dv._doi(target) != DOI.lower():
        return {"identity": f"doi:{DOI.lower()}", "records": [], "capability_fact": f"wms only serves doi:{DOI}"}
    return dv.fetch_in(client, dv.BASE, SOURCE_ID, None, f"doi:{DOI}", file_id=file_id, download=download)
