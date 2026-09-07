"""One module per source. A module declares CAPABILITIES and implements only
those functions, each taking the metered client first (PLAN.md I-1, I-2)."""
from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

_SKIP = {"base"}


def load_all() -> dict[str, ModuleType]:
    """Import every adapter module in this package, keyed by source id."""
    out: dict[str, ModuleType] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name in _SKIP or info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        out[getattr(mod, "SOURCE_ID", info.name)] = mod
    return out
