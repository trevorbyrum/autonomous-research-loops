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
no early exit, so which principal matched does not change the work done (the
presented token's length does: SHA-256 reads all of it). Tokens stay in this
module: they are never logged, echoed, returned or stored. The configured
ones are kept here, in memory, for one purpose: redact() takes each of them
out of whatever the listener is about to write — a reply, a log line — so a
token a request carries in its path or body is not reflected back or logged
(Astra 1e review finding 3), in each form a reply can carry it: as it is,
JSON-escaped (a token holding `"` or `\\`, inside JSON text a reply nests),
percent-encoded, JSON-unescaped, or as the decimal digits of a number (Astra
1e-repair re-review finding 2); and dumps() checks the JSON text itself as it
is written, where serialization can re-form a token no value holds (Astra
1e-repair-2 re-review finding 1). Both read a text a run at a time — the text
between two spaces, which no token spans — so the bound on decodings is a
run's, and a text dumps() wrote is one redact() keeps (Astra 1e-repair-3
re-review finding 1).

Persistence (RG-9): the principal set is the mounted secrets', read at every
start. A restart or a replacement with the same mount keeps every principal,
its role and so its permissions; a token rotated out of the mount stops
authenticating at the next start (that is how an env-backend token expires).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Mapping, NamedTuple
from urllib.parse import unquote

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MIN_TOKEN = 16
SCHEME = "bearer "
REDACTED = "[credential]"
MAX_DECODINGS = 256  # the most decodings of one text _carries() reads: past them, the text counts as showing a token
ESCAPE = re.compile(r'\\(?:u([0-9A-Fa-f]{4})|(["\\/bfnrt]))')  # a JSON string's escape
ESCAPED = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


class CredentialsRefused(ValueError):
    """The mounted secrets give no usable principal set: the engine does not
    start. The message names the variable or principal, never a token."""


class Unwritable(ValueError):
    """An answer no redaction of its values writes without a configured
    token (dumps()): only a token made of JSON's punctuation and REDACTED
    can stand in what is left. It is not written."""


class Principal(NamedTuple):
    name: str
    role: str  # "operator" | "exporter"


def _digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8", "surrogatepass")).digest()


def _usable(token: str) -> bool:
    return len(token) >= MIN_TOKEN and all("\x21" <= c <= "\x7e" for c in token)


def _unescape(text: str) -> str:
    """text with each JSON escape in it decoded, as json.loads reads a
    string's content; a backslash that starts none is kept."""
    return ESCAPE.sub(lambda m: chr(int(m[1], 16)) if m[1] else ESCAPED[m[2]], text)


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
        self._tokens = tuple(token for _, token in entries)
        # each token as it is and JSON-escaped, the longest first: none is left half-redacted
        self._forms = tuple(sorted({form for token in self._tokens for form in (token, json.dumps(token)[1:-1])}, key=len, reverse=True))

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

    def redact(self, value):
        """`value` — a JSON value (dicts, lists, strings, numbers) or a log
        line — with every configured token taken out wherever it appears in
        a string, a key included: as it is or JSON-escaped, replaced by
        REDACTED; a string that still shows one in a run of it — only once
        decoded (_carries()), or re-formed by those replacements — and a
        number whose decimal text holds one, replaced whole by REDACTED. A
        value that carries no configured token is returned as it was. These
        are the values; dumps() checks the text they are written as. A
        string is read run by run, as _shows() reads that text: read whole,
        runs each within MAX_DECODINGS could pass it together, and a tool's
        text dumps() wrote, or an id _mcp took, be replaced after the fact
        (Astra 1e-repair-3 re-review finding 1)."""
        if isinstance(value, str):
            for form in self._forms:
                value = value.replace(form, REDACTED)
            return REDACTED if any(self._carries(run) for run in value.split(" ")) else value
        if isinstance(value, dict):
            return {self.redact(k): self.redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, (int, float)) and any(token in str(value) for token in self._tokens):  # True/False hold no token
            return REDACTED
        return value

    def writes(self, value) -> bool:
        """Whether value is written as it is: nothing in its JSON text for
        dumps() to take out. Not whether redact() keeps it: the quote written
        after a string can end the escape a decoding of it leaves (`..%5C`,
        written `..%5C"`, decodes to `..\\"`), and a token the string shows
        ending in that `\\` is not in its text."""
        return not self._shows(json.dumps(value, sort_keys=True), False)

    def dumps(self, value, *, nested: bool = False) -> str:
        """value's JSON text (json.dumps, keys sorted), checked as the text
        it is: serialization can re-form a token no value holds — with an
        escape it writes (the `\\` before a `"` or a `\\`, `\\n`, `\\u00e9`)
        or the punctuation it joins to a value (a `"`, `{`, `[`, `]`, `}`,
        `,` or `:`). Each value — a key, a string, a number, true, false,
        null, an empty object or list — whose run shows one (_shows()) is
        replaced whole by REDACTED and the text written again, until none
        does: never the text's bytes, which would cut through its
        punctuation and leave it no JSON. `nested`: the text is to be
        nested as a string in other JSON (a tool's reply in MCP's answer),
        and is checked escaped once more as well. Unwritable if replacing
        values leaves one standing (Astra 1e-repair-2 re-review finding 1)."""
        text = json.dumps(value, sort_keys=True)
        while self._shows(text, nested):
            redacted = self._runs_redacted(value, nested, "", "")
            if redacted == value:
                raise Unwritable("no redaction of the answer's values writes it without a configured token")
            value, text = redacted, json.dumps(redacted, sort_keys=True)
        return text

    def _runs_redacted(self, value, nested: bool, before: str, after: str):
        """value with each of its values whose run shows a token replaced by
        REDACTED; a value's run is its JSON text with the punctuation
        json.dumps joins to it: `before`, the `{` and `[` that open on it,
        `after`, the `}` and `]` that close after it and the `,` or `:`."""
        if isinstance(value, dict) and value:
            keys, redacted = sorted(value), {}
            for i, key in enumerate(keys):
                shown = self._shows((before + "{" if i == 0 else "") + json.dumps(key) + ":", nested)
                redacted[REDACTED if shown else key] = self._runs_redacted(value[key], nested, "", "}" + after if i == len(keys) - 1 else ",")
            return redacted
        if isinstance(value, list) and value:
            return [self._runs_redacted(item, nested, before + "[" if i == 0 else "", "]" + after if i == len(value) - 1 else ",")
                    for i, item in enumerate(value)]
        return REDACTED if self._shows(before + json.dumps(value) + after, nested) else value

    def _shows(self, text: str, nested: bool) -> bool:
        """Whether JSON text shows a token in a run of it — the text between
        two spaces, the most a token can span: a token holds no space, JSON
        writes one after each `,` and `:`, and no decoding takes one out —
        as the run is (_carries()) or, nested, escaped once more."""
        return any(self._carries(run) or (nested and self._carries(json.dumps(run)[1:-1])) for run in text.split(" "))

    def _carries(self, text: str) -> bool:
        """Whether text shows a configured token, as it is or JSON-escaped,
        itself or once decoded: percent-decoded and JSON-unescaped, each
        again and again, in every order (`%5Cu0022` is a `"` only
        percent-decoded, then unescaped). Each decoding is shorter than what
        it decodes, so there are finitely many; past MAX_DECODINGS the text
        counts as showing one."""
        seen, pending = {text}, [text]
        while pending:
            current = pending.pop()
            if any(form in current for form in self._forms):
                return True
            for decoded in (unquote(current), _unescape(current)):
                if decoded not in seen:
                    if len(seen) >= MAX_DECODINGS:
                        return True
                    seen.add(decoded)
                    pending.append(decoded)
        return False

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
