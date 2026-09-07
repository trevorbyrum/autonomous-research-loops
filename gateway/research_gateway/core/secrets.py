"""Secrets: logical names in the registry, values from outside the tree (PLAN.md I-5).

Backends:
  env    RESEARCH_GATEWAY_SECRET_<NAME>[_<FIELD>]  (public default)
  vault  HashiCorp KV v2 over HTTP; address, token file and path prefix all
         come from the environment, never from this repository.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Protocol


class Backend(Protocol):
    def get(self, name: str, field: str | None = None) -> str | None: ...


class EnvBackend:
    PREFIX = "RESEARCH_GATEWAY_SECRET_"

    def get(self, name: str, field: str | None = None) -> str | None:
        key = self.PREFIX + name.upper().replace("-", "_")
        if field:
            key += "_" + field.upper()
        return os.environ.get(key) or None


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


class VaultBackend:
    """KV v2: GET {addr}/v1/{mount}/data/{prefix}/{name}; field defaults to a
    loose match on key/token/secret/api_key so hand-stored secrets work."""

    def __init__(self, addr: str | None = None, token_file: str | None = None, mount: str | None = None,
                 prefix: str | None = None, aliases: dict[str, str] | None = None):
        self.addr = addr or os.environ.get("RESEARCH_GATEWAY_VAULT_ADDR") or ""
        self.token_file = token_file or os.environ.get("RESEARCH_GATEWAY_VAULT_TOKEN_FILE") or os.path.expanduser("~/.vault-token")
        self.mount = mount or os.environ.get("RESEARCH_GATEWAY_VAULT_MOUNT") or "secret"
        self.prefix = prefix or os.environ.get("RESEARCH_GATEWAY_VAULT_PREFIX") or "services"
        self.aliases = aliases if aliases is not None else parse_aliases(os.environ.get("RESEARCH_GATEWAY_VAULT_ALIASES"))
        self._cache: dict[str, tuple[float, dict]] = {}
        self.success_ttl, self.failure_ttl = 900.0, 60.0   # rotation lands within 15 min; a hiccup retries within 1 (D-23)

    class _Opener(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # a vault never redirects a KV read; following one could re-send the token elsewhere

    _opener = urllib.request.build_opener(_Opener)

    def _read(self, name: str) -> dict:
        name = self.aliases.get(name, name)
        hit = self._cache.get(name)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        if not self.addr:
            return {}
        try:
            with open(self.token_file) as f:
                token = f.read().strip()
            req = urllib.request.Request(f"{self.addr}/v1/{self.mount}/data/{self.prefix}/{name}",
                                         headers={"X-Vault-Token": token})
            with self._opener.open(req, timeout=10) as resp:
                data = (json.load(resp).get("data") or {}).get("data") or {}
            ttl = self.success_ttl
        except (OSError, ValueError):
            data, ttl = {}, self.failure_ttl
        self._cache[name] = (time.monotonic() + ttl, data)
        return data

    def get(self, name: str, field: str | None = None) -> str | None:
        data = self._read(name)
        if not data:
            return None
        if field:
            v = data.get(field)
            return str(v) if v else None
        for k in ("api_key", "key", "token", "secret", "personal_access_token"):
            if data.get(k):
                return str(data[k])
        for k, v in data.items():
            if v and any(t in k.lower() for t in ("key", "token", "secret")):
                return str(v)
        return None


class Chain:
    """First backend with a value wins; env first so a deployment can override."""

    def __init__(self, *backends: Backend):
        self.backends = backends

    def get(self, name: str, field: str | None = None) -> str | None:
        for b in self.backends:
            v = b.get(name, field)
            if v:
                return v
        return None


def from_config(backend: str = "env") -> Backend:
    if backend == "vault":
        return Chain(EnvBackend(), VaultBackend())
    return EnvBackend()
