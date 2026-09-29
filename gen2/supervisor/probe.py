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
  unusable_credential  the auth home is not a 0700 directory (not a link)
                       of this service user, or the runner finds no
                       credential or one it cannot read;
  runner_error         the runner is not the pinned version, could not
                       start, ran past the probe timeout, was killed, or
                       printed what its rules do not know.
Only fixed details leave the probe. Nothing the runner printed is recorded or
logged: its text can carry part of a credential (codex prints a masked key).

What it establishes is the pinned runner's own local judgment of the
credential it finds, nothing more. That judgment reads the credential file;
it does not ask the provider. A credential the provider has revoked, or an
expired one the runner can still read, reads as usable (docs/gen2/AUTH-DEMO.md
records which cases this runner version tells apart).

The runner gets a fresh workspace (its HOME and working directory, removed
after) and an environment of exactly PATH, HOME and its auth-home variable:
no operator token, store path or engine secret reaches it (§4). The
observation is handed to `record`, the router's record_capability_probe. In
the engine the composition root runs that on the router's owner thread and
the runner on the caller's, so two probes run their runners at once and are
recorded one after the other (gen2/app/engine.py).
"""
from __future__ import annotations

import os
import secrets
import shutil
import signal
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

PATH = "/usr/local/bin:/usr/bin:/bin"
REQUEST = frozenset({"provider", "requested_by"})


@dataclass(frozen=True)
class Runner:
    name: str
    version: str                   # the pinned version: any other is a runner_error, its behaviour unknown
    version_argv: tuple[str, ...]
    version_stdout: str            # exactly what version_argv prints for the pinned version
    status_argv: tuple[str, ...]
    home_env: str                  # the variable naming the runner's auth home
    classify: Callable[[int, str, str], tuple[str, str]]  # (exit code, stdout, stderr) -> (outcome, detail)


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


RUNNERS = {"codex": Runner("codex", "0.153.2", ("codex", "--version"), "codex-cli 0.153.2\n", ("codex", "login", "status"), "CODEX_HOME",
                           codex_status)}


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
        started = self._clock()
        outcome, detail = self._home(self._auth_root / runner.name) or self._probe(runner, self._auth_root / runner.name)
        return (record or self._record)({
            "probe_id": "probe_" + secrets.token_hex(16), "capability": f"provider-auth:{runner.name}", "outcome": outcome, "detail": detail,
            "started_at": started, "observed_at": self._clock(), "runner": {"name": runner.name, "version": runner.version},
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
