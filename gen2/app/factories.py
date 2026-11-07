"""The child's builder table: purpose -> a factory of the pure builder for it.

Trace: Gate S #7 §5.2 (builders are pure: they read the view, the judgment, and bytes the view names by hash); the T17 brief (a fresh
subprocess builds its own table). Oracle: the builders' own tests. Limits: no reader, exchange handle or spool reaches a builder; the
two inputs a factory gets are the child's `stage` (evidence files in scratch) and `bytes_of` (digest-checked evidence files).
The quote normalization version is the router's `quote_matching.NORMALIZATION`, joined with "/", as the verify builder records it.
"""
from __future__ import annotations

from gen2.exec import challenge, dossier, receipts, research, review, scope
from gen2.router import quote_matching

NORMALIZATION = "/".join(quote_matching.NORMALIZATION)
TABLE = {
    "research_pass/scope": lambda stage, bytes_of: scope.build_scope,
    "research_pass/research": lambda stage, bytes_of: research.research_builder(stage),
    "verification/verify": lambda stage, bytes_of: receipts.make_builder(bytes_of, stage, normalization=NORMALIZATION),
    "checkpoint/challenge": lambda stage, bytes_of: challenge.make_builder(stage),
    "checkpoint/review": lambda stage, bytes_of: review.make_builder(stage),
    "checkpoint/dossier": lambda stage, bytes_of: dossier.build_dossier,
}
