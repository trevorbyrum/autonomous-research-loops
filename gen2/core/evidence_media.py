"""The one table of evidence-file forms: `evidence-<sha256 hex><extension>` names the bytes' own digest and fixes their media type.

Trace: Gate S #7 §5.2, Astra PR3b review (a shared constant, so the writer and the collector cannot drift); #131's evidence contract.
Oracle: the file's own bytes hashed against its name. Limits: four forms only (JSON, text, and the live backend's raw logs as ndjson and octet-stream); the Router accepts other media on a
ref, but the collector admits only these, and a new form is added here, once.
"""
from __future__ import annotations

import re

EVIDENCE_MEDIA = {".json": "application/json", ".txt": "text/plain", ".ndjson": "application/x-ndjson", ".bin": "application/octet-stream"}
EXTENSION = {media: extension for extension, media in EVIDENCE_MEDIA.items()}
EVIDENCE = re.compile(r"\Aevidence-([0-9a-f]{64})(" + "|".join(re.escape(e) for e in EVIDENCE_MEDIA) + r")\Z")


def evidence_name(digest: str, media_type: str) -> str:
    """The scratch file name for bytes with this `sha256:` digest and media type; an unsupported media type is refused."""
    if media_type not in EXTENSION:
        raise ValueError(f"evidence is set aside as {sorted(EXTENSION)}, not {media_type}")
    return f"evidence-{digest.removeprefix('sha256:')}{EXTENSION[media_type]}"
