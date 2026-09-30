"""Secrets: logical names in the registry, values from outside the tree (PLAN.md I-5).

Backends:
  env    RESEARCH_GATEWAY_SECRET_<NAME>[_<FIELD>]  (public default)
  vault  HashiCorp KV v2 over HTTP; address, token file and path prefix all
         come from the environment, never from this repository.

Every read has one of three outcomes (docs/gen2/DEPLOYMENT-CONTRACT.md §3.3,
task 2b): FOUND (a value), ABSENT (the backend answered and holds nothing for
this name — "no secret configured") and FAILING (the backend could not answer:
transport error, timeout, non-200, a 404 for a mount that does not exist, an
unreadable token file, an unparseable body, a refused redirect). A failing read
is never reported as an absent one: `read()` returns the typed outcome and
`get()` raises SecretsBackendFailing instead of answering None. Each vault
backend keeps a dated capability fact (`SecretsHealth`): failing since the
first failed read of the episode, with the last successful read and the lanes
whose secrets could not be read, alerting on each transition (INVARIANTS H-2).

The vault backend refuses to be constructed without an explicit address and an
explicit, readable token file: there is no home-directory fallback (rule 1).
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

FOUND, ABSENT, FAILING = "found", "absent", "failing"
ADDR_VAR, TOKEN_FILE_VAR = "RESEARCH_GATEWAY_VAULT_ADDR", "RESEARCH_GATEWAY_VAULT_TOKEN_FILE"


@dataclass(frozen=True)
class SecretRead:
    """One read's outcome. `reason` says why a read failed; `status` is the HTTP status of a
    failing read when the backend answered with one (the capability fact shows it)."""
    state: str
    value: str | None = None
    reason: str | None = None
    status: int | None = None


class SecretsConfigError(RuntimeError):
    """The backend cannot run as configured; the service refuses to start (the message names
    the variable). Never a silent degradation to another source of credentials."""


class SecretsBackendFailing(RuntimeError):
    """A read failed. Raised by get() and by the metered client's secret(): whatever asked
    for the secret learns the backend is failing, never that no key is configured."""

    def __init__(self, name: str, read: SecretRead, fact: dict | None = None):
        super().__init__(f"secrets backend failing reading {name!r}: {read.reason}")
        self.name, self.read, self.fact = name, read, fact


class Backend(Protocol):
    def read(self, name: str, field: str | None = None) -> SecretRead: ...
    def get(self, name: str, field: str | None = None) -> str | None: ...


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _value(read: SecretRead, name: str, fact: Callable[[], dict | None] = lambda: None) -> str | None:
    if read.state == FAILING:
        raise SecretsBackendFailing(name, read, fact())
    return read.value if read.state == FOUND else None


class EnvBackend:
    """Reads the process environment: a value is present or absent; no read can fail."""
    PREFIX = "RESEARCH_GATEWAY_SECRET_"
    health = None

    def read(self, name: str, field: str | None = None) -> SecretRead:
        key = self.PREFIX + name.upper().replace("-", "_")
        if field:
            key += "_" + field.upper()
        value = os.environ.get(key)
        return SecretRead(FOUND, value) if value else SecretRead(ABSENT)

    def get(self, name: str, field: str | None = None) -> str | None:
        return _value(self.read(name, field), name)


def parse_aliases(text: str | None) -> dict[str, str]:
    """'logical=vault-name,other=name' → {logical: vault-name}; deployments whose Vault
    paths do not match the registry's logical names set RESEARCH_GATEWAY_VAULT_ALIASES."""
    out = {}
    for pair in (text or "").split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
    return out


class SecretsHealth:
    """The dated `secrets.<backend>` capability fact. The fact is failing while any secret
    name's latest FRESH read failed (cached replays do not move it): `since` is the first
    failed read of the episode, `last_success_at` the latest fresh successful read, and the
    affected lanes are the sources whose secret names are failing. `revision` counts the
    fact's changes, so each snapshot has its place in this gateway's reports and a return to
    earlier contents is a later snapshot, never the earlier one again (task 2b-repair-3 R2).
    `on_transition(fact)` is called on every state change (the gateway alerts on it); a
    listener's error is its own."""

    def __init__(self, capability: str, *, wall: Callable[[], float] = time.time,
                 lanes_for: Callable[[str], list[str]] | None = None,
                 on_transition: Callable[[dict], None] | None = None):
        self.capability, self._wall = capability, wall
        self.lanes_for = lanes_for or (lambda name: [])
        self.on_transition = on_transition
        self._lock = threading.Lock()
        self._failing: dict[str, SecretRead] = {}   # name -> its latest fresh failed read
        self.since: float | None = None
        self.last_success_at: float | None = None
        self.last_failure: SecretRead | None = None
        self.state = "unknown"   # until the first fresh read: nothing has been observed
        self.revision = 0

    def success(self, name: str) -> None:
        with self._lock:
            before = self._content()
            self.last_success_at = self._wall()
            self._failing.pop(name, None)
            alert = self._settle(before)
        self._notify(alert)

    def failure(self, name: str, read: SecretRead) -> None:
        with self._lock:
            before = self._content()
            if not self._failing:
                self.since = self._wall()
            self._failing[name] = read
            self.last_failure = read
            alert = self._settle(before)
        self._notify(alert)

    def _settle(self, before: dict) -> bool:
        """Settle the state and count a change of the fact; True on a transition worth an
        alert: into failing, or a recovery out of it (the first healthy read after startup is
        not news)."""
        state = "failing" if self._failing else "healthy"
        if state == "healthy":
            self.since = None
        alert = state != self.state and (state == "failing" or self.state == "failing")
        self.state = state
        if self._content() != before:
            self.revision += 1
        return alert

    def _notify(self, alert: bool) -> None:
        if alert and self.on_transition is not None:
            try:
                self.on_transition(self.fact())
            except Exception:
                pass

    def _content(self) -> dict:
        lanes = sorted({lane for name in self._failing for lane in self.lanes_for(name)})
        last = self.last_failure if self._failing else None
        return {"capability": self.capability, "state": self.state, "since": _iso(self.since),
                "last_success_at": _iso(self.last_success_at),
                "detail": (str(last.status) if last.status else last.reason) if last else None,
                "affected_lanes": lanes}

    def fact(self) -> dict:
        with self._lock:
            return {**self._content(), "revision": self.revision}

    def summary(self) -> str | None:
        """The operator's status line while failing (DEPLOYMENT-CONTRACT §3.4 test 8)."""
        f = self.fact()
        if f["state"] != "failing":
            return None
        return f"secrets backend failing since {f['since']} ({f['detail']}); {len(f['affected_lanes'])} lanes degraded"


class VaultBackend:
    """KV v2: GET {addr}/v1/{mount}/data/{prefix}/{name}; field defaults to a loose match on
    key/token/secret/api_key so hand-stored secrets work.

    What each answer means (Vault's KV v2 behaviour): 200 with a `data.data` object is the
    secret; 404 with an empty `errors` list is a path with nothing stored under an existing
    mount (ABSENT); 404 naming a missing route ("no handler for route") is a mount or prefix
    that does not exist, which would make every key look absent (FAILING); anything else —
    403, 5xx, any other success status (a 201 or 204 is not a KV read, whatever its body
    says), a refused redirect, an unparseable or mis-shaped body, a timeout, an
    unreachable address, an unreadable token file — is FAILING. Outcomes are cached per
    name: successes (found or absent) for 15 minutes, failures for 1 minute, and a cached
    failure replays as FAILING (a failure is never laundered into an absence)."""

    success_ttl, failure_ttl = 900.0, 60.0   # rotation lands within 15 min; a hiccup retries within 1 (D-23)

    def __init__(self, addr: str | None = None, token_file: str | None = None, mount: str | None = None,
                 prefix: str | None = None, aliases: dict[str, str] | None = None, *, environ: dict | None = None,
                 timeout: float = 10.0, clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time):
        env = os.environ if environ is None else environ
        self.addr = (addr or env.get(ADDR_VAR) or "").rstrip("/")
        if not self.addr:
            raise SecretsConfigError(f"{ADDR_VAR} is not set: the vault backend has no address to read from")
        self.token_file = token_file or env.get(TOKEN_FILE_VAR) or ""
        if not self.token_file:
            raise SecretsConfigError(f"{TOKEN_FILE_VAR} is not set: the vault backend needs an explicit token file "
                                     "(there is no home-directory fallback)")
        problem = self._token()[1]
        if problem:
            raise SecretsConfigError(f"{TOKEN_FILE_VAR}={self.token_file}: {problem}")
        self.mount = mount or env.get("RESEARCH_GATEWAY_VAULT_MOUNT") or "secret"
        self.prefix = prefix or env.get("RESEARCH_GATEWAY_VAULT_PREFIX") or "services"
        self.aliases = aliases if aliases is not None else parse_aliases(env.get("RESEARCH_GATEWAY_VAULT_ALIASES"))
        self.timeout, self._clock = timeout, clock
        self._cache: dict[str, tuple[float, str, dict | SecretRead | None]] = {}
        self._cache_lock = threading.Lock()
        self.health = SecretsHealth("secrets.vault", wall=wall)

    class _Opener(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # a vault never redirects a KV read; following one could re-send the token elsewhere

    _opener = urllib.request.build_opener(_Opener)

    def _token(self) -> tuple[str | None, str | None]:
        """(token, None) or (None, why the token file cannot be used). Read on every fetch:
        a file removed while running makes the next read fail, never fall back."""
        try:
            with open(self.token_file, encoding="utf-8") as f:
                token = f.read().strip()
        except (OSError, UnicodeDecodeError) as e:
            return None, f"token file unreadable ({getattr(e, 'strerror', None) or type(e).__name__})"
        return (token, None) if token else (None, "token file is empty")

    def _fetch(self, name: str) -> tuple[str, dict | SecretRead | None]:
        """One uncached read: ("ok", data) | ("absent", None) | ("failing", SecretRead)."""
        token, problem = self._token()
        if problem:
            return "failing", SecretRead(FAILING, reason=problem)
        req = urllib.request.Request(f"{self.addr}/v1/{self.mount}/data/{self.prefix}/{name}",
                                     headers={"X-Vault-Token": token})
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:
                body = b""
            if e.code == 404:
                return self._not_found(body)
            if 300 <= e.code < 400:
                return "failing", SecretRead(FAILING, reason=f"redirect refused ({e.code})", status=e.code)
            return "failing", SecretRead(FAILING, reason=f"HTTP {e.code}", status=e.code)
        except (TimeoutError, socket.timeout):
            return "failing", SecretRead(FAILING, reason="timeout")
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            kind = "timeout" if isinstance(reason, (TimeoutError, socket.timeout)) else "unreachable"
            return "failing", SecretRead(FAILING, reason=f"{kind} ({type(reason).__name__})")
        if status != 200:   # a KV read answers 200: any other success status is not a read, whatever its body says
            return "failing", SecretRead(FAILING, reason=f"unexpected HTTP {status}", status=status)
        try:
            doc = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return "failing", SecretRead(FAILING, reason="unparseable payload", status=200)
        data = (doc.get("data") or {}).get("data") if isinstance(doc, dict) and isinstance(doc.get("data"), dict) else None
        if not isinstance(data, dict):
            return "failing", SecretRead(FAILING, reason="payload without a data.data object", status=200)
        return "ok", data

    @staticmethod
    def _not_found(body: bytes) -> tuple[str, SecretRead | None]:
        try:
            errors = json.loads(body).get("errors")
        except (ValueError, UnicodeDecodeError, AttributeError):
            errors = None
        if errors == []:
            return "absent", None
        return "failing", SecretRead(FAILING, reason="mount or route not found (404)", status=404)

    def _entry(self, name: str) -> tuple[str, dict | SecretRead | None]:
        vault_name = self.aliases.get(name, name)
        now = self._clock()
        with self._cache_lock:
            hit = self._cache.get(vault_name)
        if hit and hit[0] > now:
            if hit[1] == "failing":
                self.health.failure(name, hit[2])   # still failing: its lanes stay affected
            return hit[1], hit[2]
        kind, payload = self._fetch(vault_name)
        ttl = self.failure_ttl if kind == "failing" else self.success_ttl
        with self._cache_lock:
            self._cache[vault_name] = (self._clock() + ttl, kind, payload)
        if kind == "failing":
            self.health.failure(name, payload)
        else:
            self.health.success(name)
        return kind, payload

    def read(self, name: str, field: str | None = None) -> SecretRead:
        kind, payload = self._entry(name)
        if kind == "failing":
            return payload
        if kind == "absent":
            return SecretRead(ABSENT)
        if field:
            v = payload.get(field)
            return SecretRead(FOUND, str(v)) if v else SecretRead(ABSENT)
        for k in ("api_key", "key", "token", "secret", "personal_access_token"):
            if payload.get(k):
                return SecretRead(FOUND, str(payload[k]))
        for k, v in payload.items():
            if v and any(t in k.lower() for t in ("key", "token", "secret")):
                return SecretRead(FOUND, str(v))
        return SecretRead(ABSENT)

    def get(self, name: str, field: str | None = None) -> str | None:
        return _value(self.read(name, field), name, self.health.fact)


class Chain:
    """First backend with a value wins; env first so a deployment can override. A failing
    backend after the env miss makes the read failing: its absence is not known."""

    def __init__(self, *backends):
        self.backends = backends
        self.health = next((b.health for b in backends if getattr(b, "health", None) is not None), None)

    def read(self, name: str, field: str | None = None) -> SecretRead:
        outcome = SecretRead(ABSENT)
        for b in self.backends:
            outcome = read_from(b, name, field)
            if outcome.state != ABSENT:
                return outcome
        return outcome

    def get(self, name: str, field: str | None = None) -> str | None:
        return _value(self.read(name, field), name, (self.health.fact if self.health else lambda: None))


def read_from(backend, name: str, field: str | None = None) -> SecretRead:
    """The typed outcome from any backend; one with only get() (a test stub) answers found or
    absent, and one that raises SecretsBackendFailing answers failing."""
    if hasattr(backend, "read"):
        return backend.read(name, field)
    try:
        value = backend.get(name, field)
    except SecretsBackendFailing as e:
        return e.read
    return SecretRead(FOUND, str(value)) if value else SecretRead(ABSENT)


def from_config(backend: str = "env") -> Backend:
    """Raises SecretsConfigError when the selected backend cannot run (the caller refuses to start)."""
    if backend == "vault":
        return Chain(EnvBackend(), VaultBackend())
    if backend != "env":
        raise SecretsConfigError(f"RESEARCH_GATEWAY_SECRETS={backend!r}: unknown secrets backend (env or vault)")
    return EnvBackend()
