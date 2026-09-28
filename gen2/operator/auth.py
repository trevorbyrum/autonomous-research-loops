"""Who is calling the engine's listener (task 1e): principals, authenticated
by bearer token from the mounted secrets surface.

Trace: DEPLOYMENT-CONTRACT.md §1.1 (every route but GET /v1/health requires a
bearer token; two kinds reach the listener: GEN2_OPERATOR_TOKENS, the
operator's, and GEN2_SECRET_EXPORTER_TOKEN, the exporter's, which never
carries operator authority), §2 (secrets are mounted; in the env backend a
change takes effect by restart), §3 and §3.1 (only the env backend is
admissible: vault waits for §3.4); deploy/gen2.env.example
(`GEN2_OPERATOR_TOKENS=name=token,...`; the service refuses to start without
any); BOUNDARIES.md Router (authority is never a caller-supplied label);
INVARIANTS RG-9 (restart and replacement preserve auth-volume access and
permissions); the 1b review's boundary ruling (1e authenticates principals).

A principal is a name and a role: each GEN2_OPERATOR_TOKENS entry is an
operator named by its entry, and GEN2_SECRET_EXPORTER_TOKEN, when set, is the
principal `exporter` with the exporter role. A token names one principal, so
two principals sharing one refuses the start, as does a token too short or
not made of visible ASCII (at least MIN_TOKEN characters).

A presented token is compared in constant time: its SHA-256 digest against
every configured token's digest with hmac.compare_digest, all of them, with
no early exit, so neither the length of the presented token nor which
principal matched changes the work done. Tokens stay in this module: they
are never logged, echoed, returned or stored.

Persistence (RG-9): the principal set is the mounted secrets', read at every
start. A restart or a replacement with the same mount keeps every principal,
its role and so its permissions; a token rotated out of the mount stops
authenticating at the next start (that is how an env-backend token expires).
"""
from __future__ import annotations

import hashlib
import hmac
import re
from typing import Mapping, NamedTuple

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MIN_TOKEN = 16
SCHEME = "bearer "


class CredentialsRefused(ValueError):
    """The mounted secrets give no usable principal set: the engine does not
    start. The message names the variable or principal, never a token."""


class Principal(NamedTuple):
    name: str
    role: str  # "operator" | "exporter"


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8", "surrogatepass")).digest()


def _usable(token: str) -> bool:
    return len(token) >= MIN_TOKEN and all("\x21" <= c <= "\x7e" for c in token)


class Credentials:
    def __init__(self, operators: Mapping[str, str], exporter: str | None = None) -> None:
        if not operators:
            raise CredentialsRefused("no operator token is configured (GEN2_OPERATOR_TOKENS): the engine does not start without one")
        entries = [(Principal(name, "operator"), token) for name, token in operators.items()]
        if exporter is not None:
            entries.append((Principal("exporter", "exporter"), exporter))
        for principal, token in entries:
            if not NAME.fullmatch(principal.name):
                raise CredentialsRefused(f"{principal.name!r} is not an operator name (letters, digits, '.', '_', '-'; at most 64)")
            if not _usable(token):
                raise CredentialsRefused(f"the {principal.role} token of {principal.name} is not usable: at least {MIN_TOKEN} visible ASCII characters")
        digests = [_digest(token) for _, token in entries]
        if len(set(digests)) != len(digests):
            raise CredentialsRefused("two principals share a token: a token names one principal")
        self._entries = [(principal, digest) for (principal, _), digest in zip(entries, digests)]

    @property
    def principals(self) -> list[Principal]:
        return [principal for principal, _ in self._entries]

    def authenticate(self, authorization: str | None) -> Principal | None:
        """The principal a `Bearer <token>` header names, or None (no header,
        another scheme, or a token no principal holds)."""
        if not isinstance(authorization, str) or authorization[:len(SCHEME)].lower() != SCHEME:
            return None
        presented = _digest(authorization[len(SCHEME):])
        found = None
        for principal, digest in self._entries:  # every entry, whatever matched: the time is the same
            if hmac.compare_digest(presented, digest):
                found = principal
        return found

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "Credentials":
        """The deployment contract's names (§1.1, §3.1): GEN2_SECRETS (env only),
        GEN2_OPERATOR_TOKENS (name=token, comma-separated) and
        GEN2_SECRET_EXPORTER_TOKEN (absent or empty: no exporter principal)."""
        backend = environ.get("GEN2_SECRETS", "env")
        if backend != "env":
            raise CredentialsRefused(f"GEN2_SECRETS={backend!r} is not admissible: only the env backend is (DEPLOYMENT-CONTRACT.md §3, §3.4)")
        operators: dict[str, str] = {}
        for entry in (part.strip() for part in environ.get("GEN2_OPERATOR_TOKENS", "").split(",")):
            if not entry:
                continue
            name, sep, token = entry.partition("=")
            if not sep:
                raise CredentialsRefused("GEN2_OPERATOR_TOKENS holds an entry that is not name=token")
            if name in operators:
                raise CredentialsRefused(f"GEN2_OPERATOR_TOKENS names operator {name!r} twice")
            operators[name] = token
        return cls(operators, environ.get("GEN2_SECRET_EXPORTER_TOKEN") or None)
