"""doi.org registration-agency lookup: routes a DOI to the registry that issued it (R-1). Not a content source."""
from __future__ import annotations

from ..core.identity import RegistrationAgencies, doi_prefix, normalize_doi
from .base import Client

SOURCE_ID = "doi_org"
SMOKE = {'capability': 'resolve', 'identity': 'doi:10.1038/nature12373'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("resolve",)


def _adapter_for(agency: str) -> str | None:
    """Which adapter declares this agency in AGENCIES — derived, never a table here (I-2, D-16)."""
    from . import load_all  # inside the function: adapters package imports this module
    fallback = None
    for sid, mod in load_all().items():
        declared = getattr(mod, "AGENCIES", ())
        if agency in declared:
            return sid
        if "*" in declared:
            fallback = sid
    return fallback


def resolve(client: Client, identity: str) -> dict | None:
    """{'identity', 'prefix', 'agency', 'adapter'}; agency 'unknown' when doi.org cannot say."""
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi:
        return None
    agency = RegistrationAgencies(client).agency(doi)
    return {"identity": f"doi:{doi}", "prefix": doi_prefix(doi), "agency": agency, "adapter": _adapter_for(agency)}
