"""2e1 F1 refusal-only gate (v5 §2/§8; Astra v5 §6).

These dependency-independent receipt pins are necessary, never sufficient.
This is not the complete manifest schema or a qualification verifier. No input
can authorize a live launch; P2-m, content and runtime qualification remain open.
"""
from collections.abc import Mapping
import re

PIN = re.compile(r"sha256:[0-9a-f]{64}")
PLACEHOLDERS = frozenset({"", "TODO", "TBD", "pending", "placeholder", "unbuilt"})
STATE_REFUSALS = {"unqualified": "profile_unqualified", "stale": "profile_stale", "invalidated": "profile_invalidated"}


class LiveProfileRefused(ValueError):
    """A fixed diagnostic, raised before job preparation or any runtime call."""


def refuse_live_profile(profile: object) -> None:
    """Inspect only immutable manifest/source/qualification references; always refuse.

    A claimed qualified state is not trusted evidence. No manifest loader,
    image resolution, wire decoder or launcher is reachable from this gate.
    """
    if profile is None:
        raise LiveProfileRefused("profile_absent_or_null")
    if not isinstance(profile, Mapping):
        raise LiveProfileRefused("profile_invalid_shape")
    for field in ("manifest_pin", "source_pin", "qualification_pin"):
        if field not in profile:
            raise LiveProfileRefused(f"profile_missing_{field}")
        pin = profile[field]
        if pin is None:
            raise LiveProfileRefused(f"profile_null_pin: {field}")
        if not isinstance(pin, str):
            raise LiveProfileRefused(f"profile_invalid_pin: {field}")
        if pin in PLACEHOLDERS:
            raise LiveProfileRefused(f"profile_placeholder: {field}")
        if not PIN.fullmatch(pin):
            raise LiveProfileRefused(f"profile_unpinned: {field}")
    state = profile.get("state")
    if not isinstance(state, str):
        raise LiveProfileRefused("profile_invalid_state")
    if state in STATE_REFUSALS:
        raise LiveProfileRefused(STATE_REFUSALS[state])
    # Even a receipt claiming qualification cannot open this refusal-only gate.
    raise LiveProfileRefused("profile_qualification_unavailable")
