"""2e1 F1 refusal-only gate (v5 §2/§8; Astra v5 §6).

These dependency-independent receipt pins are necessary, never sufficient.
This is not the complete manifest schema or a qualification verifier. No input
can authorize a live launch; P2-m, content and runtime qualification remain open.
"""
import re

PIN = re.compile(r"sha256:[0-9a-f]{64}")
PLACEHOLDERS = frozenset({"", "TODO", "TBD", "pending", "placeholder", "unbuilt"})


class LiveProfileRefused(ValueError):
    """A fixed diagnostic, raised before job preparation or any runtime call."""


def refuse_live_profile() -> None:
    """No manifest loader, image resolution, wire decoder or launcher is reachable from this gate; it always refuses."""
    raise LiveProfileRefused("profile_absent")
