"""Controller-backed checkpoint execution and accounting.

Checkpoint work is a distinct execution kind.  This package intentionally has
no topic-directory scheduler or ordinary-iteration prompt dependency.
"""

from .runner import CheckpointRunner, CheckpointResultError
from .service import CheckpointError, apply_decision, accept_research_completion, reserve_delegate_launch

__all__ = [
    "CheckpointError",
    "CheckpointResultError",
    "CheckpointRunner",
    "accept_research_completion",
    "reserve_delegate_launch",
    "apply_decision",
]
