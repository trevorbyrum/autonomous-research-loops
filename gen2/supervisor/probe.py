"""Capability probes (task 1f): the station supervisor's structural check of a
provider's auth home as the pinned runner sees it.

Trace: BOUNDARIES.md Station supervisor (owns structural telemetry, capability
probes among it); DEPLOYMENT-CONTRACT.md §4 (pinned runner CLIs are baked;
each provider's auth home is its own volume at a fixed path, owned by the
service user, 0700; every invocation gets a fresh workspace and an
allowlisted environment; testing requirement (d)), §1.2 (a dependency's
failure is a capability fact); INVARIANTS H-2, RG-3.

A probe runs the provider's pinned runner (RUNNERS: baked, like the runner
itself) against its auth home, <auth root>/<provider>, in a mode that makes
no network call and spends no quota — for codex 0.153.2, `codex --version`
then `codex login status` — and classifies what it saw by fixed rules:
  usable               the runner reports a credential it can read;
  declared_expired     the runner reports a credential it can read, and
                       that credential's own access token declares an
                       expiry at or before the probe's observation;
  unusable_credential  the auth home is not a 0700 directory (not a link)
                       of this service user, or the runner finds no
                       credential or one it cannot read;
  runner_error         the runner is not the pinned version, could not
                       start, ran past the probe timeout, was killed, or
                       printed what its rules do not know.
Only fixed details leave the probe. Nothing the runner printed is recorded or
logged: its text can carry part of a credential (codex prints a masked key).
Of the credential itself, only the instants it declares leave, and whether it
holds a refresh credential.

What it establishes is the pinned runner's own local judgment of the
credential it finds, and what that credential declares of its own expiry,
nothing more. Neither asks the provider. docs/gen2/AUTH-DEMO.md records which
cases this runner version tells apart.

Declared expiry (task 1f-repair; Astra 1f review finding 1). Once the runner
reads the credential as usable, the probe reads the same file for what it
says of its own expiry, in the runner's format (Runner.declared: codex's
auth.json, the `exp` claims of its ChatGPT access and ID tokens, RFC 7519
§4.1.4; claude_declared reads a claude credential's `expiresAt`, for a
claude runner once one is pinned). The observation records it as
`declared_expiry`: each token's declared instant (null: it declares none — an
API key, an opaque token), and whether a refresh credential is present; null
when nothing was read. Only the access token's instant decides, since that
is the token presented to the provider; the ID token's is recorded and
decides nothing. It is a claim read, not verified: the probe cannot tell an
expired access token the runner would renew from its refresh credential on
next use (that needs the provider), and a revoked credential, or an expired
one that declares no expiry, still reads as usable, since no local byte of
it changed.

The runner gets a fresh workspace (its HOME and working directory, removed
after) and an environment of exactly PATH, HOME and its auth-home variable:
no operator token, store path or engine secret reaches it (§4). The
observation is handed to `record`, the router's record_capability_probe. In
the engine the composition root runs that on the router's owner thread and
the runner on the caller's, so two probes run their runners at once and are
recorded one after the other (gen2/app/engine.py).
"""
from __future__ import annotations

import base64
import json
import math
import os
import secrets
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from gen2.core.instants import utc_instant_ns

PATH = "/usr/local/bin:/usr/bin:/bin"
REQUEST = frozenset({"provider", "requested_by"})
MAX_CREDENTIAL = 1 << 20      # bytes: a larger credential file is not read for its declared expiry
LAST_SECOND = 253402300799    # 9999-12-31T23:59:59Z, the last instant a timestamp names


@dataclass(frozen=True)
class Runner:
    name: str
    version: str                   # the pinned version: any other is a runner_error, its behaviour unknown
    version_argv: tuple[str, ...]
    version_stdout: str            # exactly what version_argv prints for the pinned version
    status_argv: tuple[str, ...]
    home_env: str                  # the variable naming the runner's auth home
    classify: Callable[[int, str, str], tuple[str, str]]  # (exit code, stdout, stderr) -> (outcome, detail)
    credential: str = ""           # the credential file in its auth home
    declared: Callable[[object], dict] | None = None  # that file, parsed -> what it declares of its own expiry


def codex_status(code: int, out: str, err: str) -> tuple[str, str]:
    """codex 0.153.2 `login status`: one line on stderr, nothing on stdout;
    exit 0 when it reads a credential, 1 when it finds none or cannot read
    the one it finds."""
    line = err[:-1] if err.endswith("\n") else err
    if out or "\n" in line:
        return "runner_error", f"login status exited {code} with output its rules do not know"
    if code == 0 and (line.startswith("Logged in using an API key - ") or line == "Logged in using ChatGPT"):
        return "usable", "the runner reads a credential (" + ("an API key" if "API key" in line else "ChatGPT tokens") + ")"
    if code == 1 and line == "Not logged in":
        return "unusable_credential", "the runner finds no credential"
    if code == 1 and line.startswith("Error checking login status: "):
        if line.endswith("Permission denied (os error 13)"):
            return "unusable_credential", "the runner cannot read the credential (permission denied)"
        return "unusable_credential", "the runner cannot parse the credential"
    return "runner_error", f"login status exited {code} with output its rules do not know"


def epoch_instant(seconds: object) -> str | None:
    """Seconds since 1970 as a timestamp, a fraction rounded up (a declared
    expiry is never made earlier); None for anything else or past 9999."""
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 <= seconds <= LAST_SECOND:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(math.ceil(seconds)))


def jwt_exp(token: object) -> str | None:
    """The expiry a JWS compact token's `exp` claim declares (RFC 7519
    §4.1.4), read and never verified; None when it is not such a token or
    declares none."""
    if not isinstance(token, str) or token.count(".") != 2:
        return None
    payload = token.split(".")[1]
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, RecursionError):
        return None
    return epoch_instant(claims.get("exp")) if isinstance(claims, dict) else None


def codex_declared(credential: object) -> dict:
    """codex 0.153.2's auth.json. An OPENAI_API_KEY string, empty or not, is
    the credential it uses, and declares nothing; otherwise its ChatGPT
    tokens, whose access and ID tokens are JWTs (AUTH-DEMO.md (e))."""
    auth = credential if isinstance(credential, dict) else {}
    tokens = auth.get("tokens") if not isinstance(auth.get("OPENAI_API_KEY"), str) and isinstance(auth.get("tokens"), dict) else {}
    return {"access_token": jwt_exp(tokens.get("access_token")), "id_token": jwt_exp(tokens.get("id_token")),
            "refresh_credential": isinstance(tokens.get("refresh_token"), str) and tokens["refresh_token"] != ""}


def claude_declared(credential: object) -> dict:
    """claude 2.1.283's .credentials.json (AUTH-DEMO.md appendix): its OAuth
    access token's `expiresAt`, in milliseconds; it has no ID token. No
    claude runner is pinned in RUNNERS: this is the reader one would name."""
    oauth = credential.get("claudeAiOauth") if isinstance(credential, dict) else None
    oauth = oauth if isinstance(oauth, dict) else {}
    ms = oauth.get("expiresAt")
    return {"access_token": epoch_instant(-(-ms // 1000)) if isinstance(ms, (int, float)) and not isinstance(ms, bool) else None,  # whole seconds, up
            "id_token": None, "refresh_credential": isinstance(oauth.get("refreshToken"), str) and oauth["refreshToken"] != ""}


def declared_verdict(declared: dict | None, observed: str) -> tuple[str, str] | None:
    """declared_expired, with its detail, when the access token declares an
    expiry at or before `observed` (RFC 7519: not to be accepted on or after
    it); None when it declares none, or a later one."""
    if declared is None or declared["access_token"] is None or utc_instant_ns(declared["access_token"]) > utc_instant_ns(observed):
        return None
    return "declared_expired", (f"the runner reads the credential, but its access token declares it expired at {declared['access_token']}: "
                                "the credential's own claim, not the provider's answer; a refresh credential is "
                                + ("present" if declared["refresh_credential"] else "absent"))


RUNNERS = {"codex": Runner("codex", "0.153.2", ("codex", "--version"), "codex-cli 0.153.2\n", ("codex", "login", "status"), "CODEX_HOME",
                           codex_status, "auth.json", codex_declared)}


class CapabilityProbe:
    def __init__(self, auth_root: str | Path | None, *, record: Callable[[dict], dict], clock: Callable[[], str], timeout_s: Callable[[], float],
                 station_id: str, runners: Mapping[str, Runner] = RUNNERS, path: str = PATH) -> None:
        self._auth_root = None if auth_root is None else Path(auth_root)
        self._record, self._clock, self._timeout_s = record, clock, timeout_s
        self._station_id, self._runners, self._path = station_id, runners, path

    def run(self, request: Mapping, *, record: Callable[[dict], dict] | None = None) -> dict:
        """{provider, requested_by}: probe that provider's auth home and hand
        the observation to `record` (this probe's own unless one is given),
        returning its answer. Refused, with nothing run or recorded: a request
        not of this shape, a provider with no pinned runner, a station with no
        auth homes mounted."""
        if not isinstance(request, Mapping) or set(request) != REQUEST or not all(
                isinstance(request[k], str) and 0 < len(request[k]) <= 500 for k in REQUEST):
            return {"status": "refused", "reason": "request_invalid", "detail": "a probe names provider and requested_by, each a string"}
        runner = self._runners.get(request["provider"])
        if runner is None:
            return {"status": "refused", "reason": "unknown_provider", "detail": f"no pinned runner here for {request['provider'][:80]!r}"}
        if self._auth_root is None:
            return {"status": "refused", "reason": "no_auth_homes", "detail": "this station has no auth homes mounted"}
        started, home = self._clock(), self._auth_root / runner.name
        outcome, detail = self._home(home) or self._probe(runner, home)
        declared = self._declared(runner, home) if outcome == "usable" else None
        observed = self._clock()
        outcome, detail = declared_verdict(declared, observed) or (outcome, detail)
        return (record or self._record)({
            "probe_id": "probe_" + secrets.token_hex(16), "capability": f"provider-auth:{runner.name}", "outcome": outcome, "detail": detail,
            "declared_expiry": declared, "started_at": started, "observed_at": observed, "runner": {"name": runner.name, "version": runner.version},
            "affected_lanes": [f"station:{self._station_id}"], "requested_by": request["requested_by"]})

    @staticmethod
    def _home(home: Path) -> tuple[str, str] | None:
        """The auth home as §4 fixes it: a directory, not a link, of this
        service user, mode 0700. None when it is."""
        try:
            found = os.lstat(home)
        except FileNotFoundError:
            return "unusable_credential", "the auth home is not mounted"
        except OSError as failure:
            return "unusable_credential", f"the auth home cannot be examined ({type(failure).__name__})"
        mode = stat.S_IMODE(found.st_mode)
        if not stat.S_ISDIR(found.st_mode) or mode != 0o700 or found.st_uid != os.geteuid():
            kind = "a directory" if stat.S_ISDIR(found.st_mode) else "not a directory"
            return "unusable_credential", f"the auth home is not a 0700 directory of this service user ({kind}, mode {mode:04o}, uid {found.st_uid})"
        return None

    @staticmethod
    def _declared(runner: Runner, home: Path) -> dict | None:
        """What the credential the runner just read declares of its own
        expiry, read from its file; its bytes go nowhere else. None when the
        runner's format declares nothing, or the file is not one to read: a
        link, unreadable, past MAX_CREDENTIAL bytes, not JSON. Read after the
        runner's own read, so one replaced in between is read as replaced."""
        if runner.declared is None:
            return None
        try:
            fd = os.open(home / runner.credential, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as file:
                data = file.read(MAX_CREDENTIAL + 1)
            if len(data) > MAX_CREDENTIAL:
                return None
            credential = json.loads(data)
        except (OSError, ValueError, RecursionError):
            return None
        return runner.declared(credential)

    def _probe(self, runner: Runner, home: Path) -> tuple[str, str]:
        workspace = tempfile.mkdtemp(prefix="gen2-probe-")  # 0700, this probe's alone
        env = {"PATH": self._path, "HOME": workspace, runner.home_env: str(home)}
        try:
            version = self._exec(runner.version_argv, env, workspace)
            if isinstance(version, str):
                return "runner_error", version
            if version[0] != 0 or version[1] != runner.version_stdout:
                return "runner_error", f"the runner is not {runner.name} {runner.version}: its behaviour is not known here"
            status = self._exec(runner.status_argv, env, workspace)
            return ("runner_error", status) if isinstance(status, str) else runner.classify(*status)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def _exec(self, argv: tuple[str, ...], env: dict, cwd: str) -> tuple[int, str, str] | str:
        """(exit code, stdout, stderr) of one run, or what went wrong. Its own
        session, ended whole at the timeout."""
        name = " ".join(argv[:2])
        try:
            child = subprocess.Popen(argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     start_new_session=True)
        except OSError as failure:
            return f"{name} could not start ({type(failure).__name__})"
        try:
            out, err = child.communicate(timeout=self._timeout_s())
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:  # the group ended on its own meanwhile
                pass
            child.communicate()
            return f"{name} ran past the probe timeout"
        if child.returncode < 0:
            return f"{name} was killed by signal {-child.returncode}"
        return child.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
