"""The operator's serialized-byte boundary (Trevor's option A, 2026-10-29).

Check the bytes that will be sent, including tokens formed by JSON escaping.
Repair whole field values in the structure, never text inside serialized JSON.
Tool replies pass here before nesting and the complete envelope passes again.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable

REDACTED = "[credential]"
# Atoms in our own json.dumps output: quoted strings and primitive values.
ATOMS = re.compile(rb'"(?:\\.|[^"\\])*"|[^\s{}\[\],:]+')


class UnsafeReply(ValueError):
    """Repair left a credential in the bytes: the transport sends its fixed fault."""


def _spelling(token: str) -> re.Pattern[bytes]:
    parts = []
    for char in token:
        hexadecimal = f"{ord(char):02x}".encode("ascii")
        # Hex case is insignificant; the token's literal case is significant.
        # JSON nesting doubles backslashes, so accept any positive slash count.
        parts.append(rb"(?:" + re.escape(char.encode("utf-8", "surrogatepass")) + rb"|%(?i:" + hexadecimal
                     + rb")|\\+u00(?i:" + hexadecimal + rb"))")
    return re.compile(b"".join(parts))


def _replace_values(value, bad):
    if isinstance(value, dict):
        return {key: _replace_values(item, bad) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_values(item, bad) for item in value]
    return REDACTED if value in bad else value


class TokenBoundary:
    def __init__(self, tokens: Iterable[str]) -> None:
        self._patterns = tuple(_spelling(token) for token in tokens)

    def forbidden(self, raw: bytes) -> bool:
        """Raw, mixed percent and JSON-unicode spellings in the actual bytes.

        Short escapes are left intact: their n/t/r/b/f can begin a raw token,
        which is exactly the serialization-created case that values miss.
        """
        return any(pattern.search(raw) for pattern in self._patterns)

    def encode(self, value, sort_keys: bool = True) -> bytes:
        raw = json.dumps(value, sort_keys=sort_keys).encode("utf-8")
        if self.forbidden(raw):
            # Tokens use only the admitted alphabet: no spelling can cross a
            # JSON delimiter. Find offending atoms in these exact serialized
            # bytes, then replace their original field values in the structure.
            bad = {json.loads(atom.group()) for atom in ATOMS.finditer(raw)
                   if self.forbidden(atom.group())}
            raw = json.dumps(_replace_values(value, bad), sort_keys=sort_keys).encode("utf-8")
            if self.forbidden(raw):
                # A sensitive field name cannot be repaired by changing its
                # value. Do not rename protocol members or emit unsafe bytes.
                raise UnsafeReply("reply cannot be serialized safely")
        return raw

    def diagnostic(self, line: str) -> str:
        """Plain diagnostics use the same byte check; suppress a whole line."""
        return REDACTED if self.forbidden(line.encode("utf-8")) else line
