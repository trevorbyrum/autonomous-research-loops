"""doi.org registration-agency lookup: routes a DOI to the registry that issued it (R-1). Not a content source."""
from __future__ import annotations

from ..core.identity import RegistrationAgencies, doi_prefix, normalize_doi
from .base import Client

SOURCE_ID = "doi_org"
CAPABILITIES = ("resolve",)

_ADAPTER_FOR = {"Crossref": "crossref", "DataCite": "datacite", "mEDRA": "openaire"}


def resolve(client: Client, identity: str) -> dict | None:
    """{'identity', 'prefix', 'agency', 'adapter'}; agency 'unknown' when doi.org cannot say."""
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi:
        return None
    agency = RegistrationAgencies(client).agency(doi)
    return {"identity": f"doi:{doi}", "prefix": doi_prefix(doi), "agency": agency, "adapter": _ADAPTER_FOR.get(agency)}
