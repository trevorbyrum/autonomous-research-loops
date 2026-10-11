"""Station-owned retained exchange hand-off (V-1/V-3; flow S4 step 8).

The reader is trusted construction-time code, never an agent-supplied capture.
Request bytes are the canonical attempted lane/page/request document; response
bytes are the retained transport octets. Workflow capture execution belongs to 2e2.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RetainedExchange:
    topic_id: str
    invocation_id: str
    attempt: int
    gateway_call_ref: str
    request_bytes: bytes
    response_bytes: bytes


class CaptureReader(Protocol):
    def read(self, *, topic_id: str, invocation_id: str, attempt: int,
             gateway_call_ref: str) -> RetainedExchange | None: ...
