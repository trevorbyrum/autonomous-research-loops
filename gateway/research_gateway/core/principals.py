"""Who is asking, and under what policy — enforced at the server, on every door (task 2b).

Gen-1 enforced a station's topic policy only in its stdio client (STATION-CONTRACT.md §1):
an agent holding the gateway token could call the HTTP API directly and set its own
posture (design review §9, "Policy and provenance"). Here the policy is a property of the
authenticated principal, and the server applies it to every request on every door.

Two kinds of principal:
  * a configured client token (RESEARCH_GATEWAY_TOKENS) is UNBOUND: an operator, a
    maintenance job, or the engine itself. Names listed in RESEARCH_GATEWAY_GRANTORS may
    mint grants.
  * a GRANT is a bearer credential a grantor mints for one invocation of one topic
    (POST /v1/grants): topic id, commercial posture, per-item acceptance, advisory domain,
    invocation id, expiry — signed with a key that never leaves the gateway process. A
    station agent is handed a grant, never a client token. Everything a grant-bearer asks
    is bound to the grant: the policy fields are injected, a conflicting argument is
    refused (PolicyError, 403 / an in-band tool error), its jobs are its topic's alone, and
    its requests carry the grant's invocation (a different one named in the headers is
    refused). A grant cannot mint grants.

The signing key is random per gateway process, so grants do not outlive a restart: a
station then gets 401 (visible), never a silently widened session. Persisting grants
across restarts belongs with the Phase 3 restart/shutdown repairs.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass, field

GRANT_PREFIX = "gwg1."
ENFORCED = ("topic_id", "commercial", "accept_per_item")   # injected; a conflicting argument is refused
ADVISORY = ("domain",)                                     # injected only when the request says nothing
TOPIC_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
INVOCATION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
MIN_TTL, MAX_TTL, DEFAULT_TTL = 60, 86400, 3600


class PolicyError(ValueError):
    """A request conflicts with the principal's bound policy; refused, never overridden."""


@dataclass(frozen=True)
class Principal:
    name: str                                  # the client id jobs and call rows are attributed to
    policy: dict = field(default_factory=dict)  # bound topic policy; empty = unbound
    invocation_id: str | None = None           # a grant's invocation
    grantor: bool = False                      # may mint grants
    expires_at: float | None = None

    @property
    def bound(self) -> bool:
        return bool(self.policy)


def as_principal(who) -> Principal:
    """A Principal from a Principal or a bare client name (an unbound caller: tests, the CLI)."""
    return who if isinstance(who, Principal) else Principal(name=str(who))


def bind(payload: dict, principal: Principal) -> dict:
    """The principal's policy applied to one request payload (STATION-CONTRACT.md §1, now at
    the server): bound fields injected, a conflicting value refused, advisory fields filled
    only when absent. An unbound principal's payload is returned unchanged."""
    if not principal.bound:
        return payload
    out = dict(payload)
    for key in ENFORCED:
        if key not in principal.policy:
            continue
        if out.get(key) is not None and out[key] != principal.policy[key]:
            raise PolicyError(f"policy-bound: {key} is set by the topic, not the caller")
        out[key] = principal.policy[key]
    for key in ADVISORY:
        if principal.policy.get(key) is not None and out.get(key) is None:
            out[key] = principal.policy[key]
    return out


def bind_correlation(trace: dict, principal: Principal) -> dict:
    """A grant's requests carry the grant's invocation; naming another one is refused."""
    if principal.invocation_id is None:
        return trace
    if trace.get("invocation_id") not in (None, principal.invocation_id):
        raise PolicyError("policy-bound: the invocation is set by the grant, not the caller")
    return {**trace, "invocation_id": principal.invocation_id, "attempt": trace.get("attempt") or 1}


def job_visible(job: dict, principal: Principal) -> bool:
    """A job is its creator's alone; a bound principal additionally reads only jobs of its own
    topic created under the posture in force NOW (a tightened posture never reads results
    obtained under a looser one — the stdio client's rule, now at the server)."""
    if job.get("client_id") != principal.name:
        return False
    if not principal.bound:
        return True
    payload = job.get("payload") or {}
    if principal.policy.get("topic_id") is not None and payload.get("topic_id") != principal.policy["topic_id"]:
        return False
    return all(bool(payload.get(k)) == principal.policy[k] for k in ("commercial", "accept_per_item") if k in principal.policy)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Grants:
    """Mints and verifies grants. `key` is random per process unless a test supplies one."""

    def __init__(self, key: bytes | None = None, clock=time.time):
        self._key = key or os.urandom(32)
        self._clock = clock

    def _sign(self, body: str) -> str:
        return _b64(hmac.new(self._key, (GRANT_PREFIX + body).encode("ascii"), hashlib.sha256).digest())

    def mint(self, grantor: Principal, request: dict) -> dict:
        """{"token", "expires_at", "client_id", "policy", "invocation_id"} for a valid request
        from a grantor; PolicyError otherwise (the caller answers 403 or 400)."""
        if not grantor.grantor or grantor.bound:
            raise PolicyError("only a configured grantor may mint grants (a grant never mints)")
        problem = _mint_problem(request)
        if problem:
            raise ValueError(problem)
        exp = int(self._clock()) + int(request.get("ttl_seconds") or DEFAULT_TTL)
        claims = {"g": grantor.name, "t": request["topic_id"], "c": request["commercial"], "a": request["accept_per_item"],
                  "d": request.get("domain"), "i": request["invocation_id"], "exp": exp, "n": _b64(os.urandom(9))}
        body = _b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
        principal = self._principal(claims)
        return {"token": f"{GRANT_PREFIX}{body}.{self._sign(body)}", "expires_at": exp, "client_id": principal.name,
                "policy": principal.policy, "invocation_id": principal.invocation_id}

    def verify(self, token: str) -> Principal | None:
        """The grant's principal, or None for anything forged, altered, malformed or expired."""
        if not token.startswith(GRANT_PREFIX):
            return None
        body, _, sig = token[len(GRANT_PREFIX):].partition(".")
        if not body or not sig or not hmac.compare_digest(sig, self._sign(body)):
            return None
        try:
            claims = json.loads(_unb64(body))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(claims, dict) or not isinstance(claims.get("exp"), int) or claims["exp"] <= self._clock():
            return None
        return self._principal(claims)

    @staticmethod
    def _principal(claims: dict) -> Principal:
        policy = {"topic_id": claims["t"], "commercial": claims["c"], "accept_per_item": claims["a"]}
        if claims.get("d") is not None:
            policy["domain"] = claims["d"]
        return Principal(name=f"{claims['g']}@{claims['t']}", policy=policy, invocation_id=claims["i"],
                         expires_at=float(claims["exp"]))


def _mint_problem(req) -> str | None:
    if not isinstance(req, dict):
        return "a grant request is a JSON object"
    unknown = set(req) - {"topic_id", "commercial", "accept_per_item", "domain", "invocation_id", "ttl_seconds"}
    if unknown:
        return f"unknown grant field(s): {', '.join(sorted(unknown))}"
    if not isinstance(req.get("topic_id"), str) or not TOPIC_RE.fullmatch(req["topic_id"]):
        return "topic_id: 1-128 characters of A-Z a-z 0-9 . _ : - (starting alphanumeric)"
    if not isinstance(req.get("invocation_id"), str) or not INVOCATION_RE.fullmatch(req["invocation_id"]):
        return "invocation_id: 1-128 characters of A-Z a-z 0-9 . _ : - (starting alphanumeric)"
    for key in ("commercial", "accept_per_item"):
        if not isinstance(req.get(key), bool):
            return f"{key} must be stated explicitly (true or false): a grant's posture is never a default"
    if req.get("domain") is not None and not isinstance(req["domain"], str):
        return "domain must be a string"
    ttl = req.get("ttl_seconds")
    if ttl is not None and (isinstance(ttl, bool) or not isinstance(ttl, int) or not MIN_TTL <= ttl <= MAX_TTL):
        return f"ttl_seconds must be an integer from {MIN_TTL} to {MAX_TTL}"
    return None
