#!/usr/bin/env python3
"""The four DEPLOYMENT-CONTRACT.md §4 auth-volume demonstrations (task 1f),
run against the minimal compose slice (deploy/gen2/compose.yaml) with the
pinned runner (codex 0.153.2, baked in deploy/gen2/Dockerfile).

    python deploy/gen2/demo/auth_demo.py [--only a,b,c,c-control,d1,d2a,d2b,e] [--keep]
    make gen2-auth-demo [DEMOS=a,b]

Each demonstration asserts its outcome mechanically — exit statuses, the
engine's own read-back of its store (operator status, the probe's reply),
file checks inside the containers — and a final read of a copy of the store,
taken once the engine has stopped, checks the whole recorded history against
every reply the run received. Exit 0 only when every demonstration run
passed; 1 when any failed (the summary names which); 2 when the run could not
be set up. Nothing is retried and no failure is softened.

  a   refresh: a credential replaced in the live auth volume is picked up by
      the next probe — same image, same container, no restart
  b   replacement: a restart, then a replacement container (down, up);
      the auth home's access, bytes and permissions survive, the probe agrees
      and the capability's fact carries on unchanged
  c   concurrency: two probes at once against one auth home, twenty rounds;
      both classify correctly each time, the credential's bytes and
      permissions are as before after every round, and in at least one round
      two `codex login status` processes were live at one instant — seen in
      the engine container's own process table (SAMPLER), not inferred from
      the probes' recorded start and end, which bracket the whole probe
  c-control  (c)'s negative control: the same rounds against an engine whose
      probe runs its runner one probe at a time, after each probe's recorded
      start (a lock in a copy of probe.py mounted over the image's); (c)'s
      overlap assertion must fail there, while the processes are seen
  d1  an invalid credential: a dated failing fact and a typed capability hold,
      owned and deadlined, in operator status — never a silent success
  d2a an expired credential that declares its expiry (JWT `exp` in 2001): the
      runner reads it as logged in; the probe reads the declared expiry and
      records a dated degraded fact and the typed hold, labeled as the
      credential's own claim
  d2b the residual of (d): a revoked credential, or one expired without
      declaring it. Neither changes a local byte, so it is modeled by leaving
      a usable credential exactly as it is. The same fact and hold are
      required, and it is NOT met (docs/gen2/AUTH-DEMO.md F1): this
      demonstration fails, and says so, for the operator's disposition
  e   characterization: the pinned runner itself, with no network at all,
      over each throwaway credential shape; the probe's rules applied to its
      output, then the declared expiry read from the same bytes — the
      version-pinned table AUTH-DEMO.md reports

Isolation: its own compose project (gen2-authdemo), so its own containers,
network and volumes; the contract's default host port, checked free first
(127.0.0.1 only); throwaway credentials generated for this run — the operator
token is passed to the CLI in the environment, never on a command line, and
the run checks it appears in no log. It removes only its own project's
resources, at its start (a clean slate) and at its end (unless --keep). It
never reads, writes or mounts any real credential store.

Logs: GEN2_AUTH_DEMO_LOG_DIR (default /var/tmp/gen2-auth-demo)/<UTC time>/:
run.log (every command, exit status and output), summary.json, the engine's
log, the store copy and the characterization outputs.
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import hashlib
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from gen2.app.cli import request as cli_request  # noqa: E402
from gen2.core.instants import utc_instant_ns  # noqa: E402
from gen2.supervisor.probe import RUNNERS, declared_verdict  # noqa: E402

PROJECT = "gen2-authdemo"
IMAGE = "gen2-engine:1f-authdemo"
COMPOSE_FILE = REPO / "deploy/gen2/compose.yaml"
BUNDLE = REPO / "deploy/gen2/demo/bundle.json"
UID = GID = 10001
AUTH_VOLUME = f"{PROJECT}_auth-codex"
STATE_VOLUME = f"{PROJECT}_state"
CAPABILITY = "provider-auth:codex"
DEMOS = ("a", "b", "c", "c-control", "d1", "d2a", "d2b", "e")
ROUNDS = 20
PY = "/opt/gen2/venv/bin/python"
PROBE_IN_IMAGE = "/opt/gen2/src/gen2/supervisor/probe.py"

# Run inside a container (as the service user): the auth home as it stands — every entry's type, mode, owner and, for
# regular files, size and SHA-256 — as JSON on stdout.
STAT = r"""
import hashlib, json, os, stat, sys
root = sys.argv[1]
def one(path):
    s = os.lstat(path)
    out = {"mode": f"{stat.S_IMODE(s.st_mode):04o}", "uid": s.st_uid, "gid": s.st_gid, "ino": s.st_ino,
           "type": "dir" if stat.S_ISDIR(s.st_mode) else "link" if stat.S_ISLNK(s.st_mode) else "file" if stat.S_ISREG(s.st_mode) else "other"}
    if out["type"] == "file":
        with open(path, "rb") as f:
            data = f.read()
        out.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    return out
entries = {".": one(root)}
for dirpath, dirs, files in os.walk(root):
    for name in dirs + files:
        path = os.path.join(dirpath, name)
        entries[os.path.relpath(path, root)] = one(path)
print(json.dumps(entries, sort_keys=True))
"""
# Run in a helper container that mounts the auth volume alone (the operator's act, outside the engine): the credential
# replaced atomically from stdin (a temporary file in the same directory, fsynced, 0600, renamed over), or removed.
WRITE = r"""
import os, sys
home, mode = sys.argv[1], sys.argv[2]
target = os.path.join(home, "auth.json")
if mode == "remove":
    if os.path.exists(target):
        os.remove(target)
else:
    data = sys.stdin.buffer.read()
    tmp = os.path.join(home, ".auth.json.refresh")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.chmod(tmp, int(mode, 8))
    os.replace(tmp, target)
dfd = os.open(home, os.O_RDONLY)
os.fsync(dfd); os.close(dfd)
print("written" if mode != "remove" else "removed")
"""
# Run in a network-less container: the pinned runner, exactly as the probe runs it, over one credential shape
# written from stdin into a fresh 0700 auth home (on its own tmpfs at /auth, never under /tmp: codex warns about a
# home there, and the engine's is a volume at /auth/codex); its raw exits and outputs as JSON (characterization, e).
CHARACTERIZE = r"""
import json, os, subprocess, sys, tempfile
shape = sys.argv[1]
home = "/auth/codex"
os.mkdir(home, 0o700)
data = sys.stdin.buffer.read()
if shape != "absent":
    path = os.path.join(home, "auth.json")
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, 0o000 if shape == "unreadable" else 0o600)
env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": tempfile.mkdtemp(prefix="ws-"), "CODEX_HOME": home}
out = {}
for key, argv in (("version", ["codex", "--version"]), ("status", ["codex", "login", "status"])):
    p = subprocess.run(argv, env=env, capture_output=True, timeout=20)
    out[key] = {"code": p.returncode, "stdout": p.stdout.decode("utf-8", "replace"), "stderr": p.stderr.decode("utf-8", "replace")}
print(json.dumps(out))
"""
# Run inside the engine container (its PID namespace) during (c)'s rounds, until its stdin closes (or argv[1] seconds): every
# codex `login status` process seen live — its exec'd command line read from /proc, its state not a zombie's — and every
# instant two of them were live together. Sound for each pair it reports: the first process was read live, then the
# second, then the first again, the same process (pid and start time); a process lives over one interval, so both were
# live when the second was read. A process that lived and ended between two scans is not seen at all.
SAMPLER = r"""
import json, os, sys, threading, time
STATUS = b"codex\x00login\x00status\x00"
stop = threading.Event()
threading.Thread(target=lambda: (sys.stdin.buffer.read(), stop.set()), daemon=True).start()
def live(pid):
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            fields = f.read().rsplit(b")", 1)[1].split()
    except (OSError, IndexError):
        return None
    return None if fields[0] in (b"Z", b"X", b"x") else int(fields[19])  # its state; then its start time, in ticks after boot
seen, together, scans = {}, {}, 0
deadline = time.monotonic() + float(sys.argv[1])
print("sampling", flush=True)
while not stop.is_set() and time.monotonic() < deadline:
    scans += 1
    found = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/cmdline", "rb") as f:
                if f.read() != STATUS:
                    continue
        except OSError:
            continue
        start = live(name)
        if start is not None:
            found.append((f"{name}:{start}", time.time_ns()))
    for key, at in found:
        seen.setdefault(key, [at, at])[1] = at
    if len(found) >= 2 and live(found[0][0].split(":")[0]) == int(found[0][0].split(":")[1]):
        for key, at in found[1:]:
            pair = together.setdefault(found[0][0] + " " + key, [at, at, 0])
            pair[1], pair[2] = at, pair[2] + 1
print(json.dumps({"scans": scans, "processes": seen, "together": together, "stopped_by": "stdin" if stop.is_set() else "deadline"}))
"""
# (c)'s negative control: the probe of the image with its runner runs serialized after each probe's recorded start
# (Astra 1f review finding 2's counterexample). Applied to a copy of the repository's probe.py, mounted read-only over the
# image's; the needle must be found exactly once.
SERIALIZE = ("    def _probe(self, runner: Runner, home: Path) -> tuple[str, str]:\n",
             "    def _probe(self, runner: Runner, home: Path) -> tuple[str, str]:\n"
             "        with _SERIALIZED:  # c-control: one probe's runner at a time\n"
             "            return self._probe_serialized(runner, home)\n\n"
             "    def _probe_serialized(self, runner: Runner, home: Path) -> tuple[str, str]:\n")


class SetupFailed(Exception):
    pass


class Failed(Exception):
    pass


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def ns(instant: str) -> int:
    return utc_instant_ns(instant)


def jwt(claims: dict) -> str:
    part = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")  # noqa: E731
    return f"{part({'alg': 'none', 'typ': 'JWT'})}.{part(claims)}.throwaway-signature"


EXPIRED, UNEXPIRED = 1000000000, 4102444800  # JWT exp: 2001-09-09T01:46:40Z, 2100-01-01T00:00:00Z


def chatgpt_tokens(exp: int, id_exp: int | str | None = None, *, refresh: bool = True, key: str | None = None) -> bytes:
    """Throwaway ChatGPT-mode tokens (unsigned; nothing here is a real account): an access token expiring at `exp` (a
    string: an opaque token), an ID token at `id_exp` (the same by default)."""
    def token(at: int | str) -> str:
        return at if isinstance(at, str) else jwt({"exp": at, "iat": at - 3600, "email": "throwaway@example.invalid",
                                                   "https://api.openai.com/auth": {"chatgpt_plan_type": "plus", "chatgpt_account_id": "acct-throwaway"}})
    return json.dumps({"OPENAI_API_KEY": key, "last_refresh": "2001-09-09T00:00:00Z",
                       "tokens": {"id_token": token(exp if id_exp is None else id_exp), "access_token": token(exp),
                                  "refresh_token": "rt-throwaway-" + secrets.token_hex(8) if refresh else "", "account_id": "acct-throwaway"}}).encode()


def api_key() -> bytes:
    return json.dumps({"OPENAI_API_KEY": "sk-throwaway-1f-" + secrets.token_hex(16)}).encode()


@dataclasses.dataclass(frozen=True)
class Shape:  # characterization (e): one throwaway credential shape
    make: object          # () -> its bytes
    runner: str           # the outcome the probe's rules give codex 0.153.2's own answer
    probe: str            # the probe's outcome: that, then the declared expiry read from the same bytes
    gap: str | None = None  # where the probe's outcome is a false positive, or rests on a claim, said plainly


SHAPES = {
    "absent": Shape(lambda: b"", "unusable_credential", "unusable_credential"),
    "api_key": Shape(api_key, "usable", "usable"),
    "api_key_empty": Shape(lambda: b'{"OPENAI_API_KEY": ""}', "usable", "usable", "an empty API key reads as a credential"),
    "empty_object": Shape(lambda: b"{}", "usable", "usable", "an empty object reads as ChatGPT tokens"),
    "chatgpt_unexpired": Shape(lambda: chatgpt_tokens(UNEXPIRED), "usable", "usable"),
    "chatgpt_expired": Shape(lambda: chatgpt_tokens(EXPIRED), "usable", "declared_expired",
                             "the runner's command reads tokens that expired in 2001 as logged in; the probe's verdict is the tokens' own declared "
                             "expiry, not the provider's answer (a refresh token is present)"),
    "chatgpt_expired_no_refresh": Shape(lambda: chatgpt_tokens(EXPIRED, refresh=False), "usable", "declared_expired",
                                        "as chatgpt_expired, with an empty refresh token"),
    "access_expired_id_unexpired": Shape(lambda: chatgpt_tokens(EXPIRED, UNEXPIRED), "usable", "declared_expired",
                                         "the access token's declared expiry decides"),
    "access_opaque_id_expired": Shape(lambda: chatgpt_tokens("opaque-access-token", EXPIRED), "usable", "usable",
                                      "an opaque access token declares no expiry; the ID token's, passed, decides nothing"),
    "api_key_beside_expired_tokens": Shape(lambda: chatgpt_tokens(EXPIRED, key="sk-throwaway-1f-" + secrets.token_hex(16)), "usable", "usable",
                                           "codex uses the API key, which declares no expiry; the tokens beside it are not its credential"),
    "id_token_garbage": Shape(lambda: b'{"OPENAI_API_KEY": null, "tokens": {"id_token": "not-a-jwt", "access_token": "x", "refresh_token": "y", '
                                      b'"account_id": "z"}}', "unusable_credential", "unusable_credential"),
    "malformed_json": Shape(lambda: b"{not json", "unusable_credential", "unusable_credential"),
    "empty_file": Shape(lambda: b"", "unusable_credential", "unusable_credential"),
    "unreadable": Shape(api_key, "unusable_credential", "unusable_credential"),
}


class Demo:
    def __init__(self, run_dir: Path, port: int) -> None:
        self.dir = run_dir
        self.log_file = open(run_dir / "run.log", "w", encoding="utf-8")
        self.port = port
        self.token = "op-demo-" + secrets.token_urlsafe(24)
        self.exporter = "ex-demo-" + secrets.token_urlsafe(24)
        self.env_file = run_dir / "gen2.env"
        self.replies: list[dict] = []  # every probe reply the run received
        self.results: list[dict] = []
        self.current: dict | None = None
        self.env = {**os.environ, "GEN2_ENV_FILE": str(self.env_file), "GEN2_BUNDLE": str(BUNDLE), "GEN2_HOST_ID": "gen2-authdemo-host",
                    "GEN2_ENGINE_PORT": str(port), "GEN2_IMAGE": IMAGE}
        self.compose_files = [COMPOSE_FILE]  # c-control adds its override while it runs

    # -- logging and commands ------------------------------------------------
    def log(self, line: str) -> None:
        text = f"{utc()} {line}"
        print(text, flush=True)
        self.log_file.write(text + "\n")
        self.log_file.flush()

    def sh(self, argv: list[str], *, stdin: bytes | None = None, env: dict | None = None, ok: tuple[int, ...] = (0,), quiet: bool = False,
           timeout: float = 600) -> subprocess.CompletedProcess:
        self.log("$ " + " ".join(argv))
        done = subprocess.run(argv, input=stdin, env=env or self.env, capture_output=True, timeout=timeout, cwd=REPO)
        out, err = done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")
        self.log(f"  exit {done.returncode}")
        for name, text in (("stdout", out), ("stderr", err)):
            if text.strip():
                self.log_file.write(f"  --- {name}\n{text.rstrip()}\n")  # in full, always
                if not quiet:
                    print(f"  --- {name}\n{text.rstrip()}", flush=True)
        self.log_file.flush()
        if done.returncode not in ok:
            raise Failed(f"{argv[0]} {' '.join(argv[1:4])} ... exited {done.returncode}")
        return done

    def compose(self, *args: str, **kw) -> subprocess.CompletedProcess:
        return self.sh(["docker", "compose", "-p", PROJECT, *(a for f in self.compose_files for a in ("-f", str(f))), *args], **kw)

    def check(self, condition: bool, what: str, **evidence) -> None:
        line = ("  ASSERT ok   " if condition else "  ASSERT FAIL ") + what + (f"  {json.dumps(evidence, sort_keys=True)}" if evidence else "")
        self.log(line)
        if self.current is not None:
            self.current["assertions"].append({"ok": bool(condition), "what": what, **({"evidence": evidence} if evidence else {})})
        if not condition:
            raise Failed(what)

    # -- the engine, through the operator CLI (the host's client of the published listener) -----
    def cli(self, *args: str, body: dict | None = None, expect: int = 0) -> dict:
        env = {**os.environ, "GEN2_OPERATOR_URL": f"http://127.0.0.1:{self.port}", "GEN2_OPERATOR_TOKEN": self.token}
        done = self.sh([sys.executable, "-m", "gen2.app.cli", *args], stdin=None if body is None else json.dumps(body).encode(), env=env,
                       ok=(expect,))
        return json.loads(done.stdout)

    def probe(self) -> dict:
        before = utc()
        reply = self.cli("call", "probe_capability", body={"provider": "codex"})
        after = utc()
        self.replies.append(reply)
        self.check(reply.get("status") == "recorded", "the probe was recorded by the router", status=reply.get("status"))
        self.check(ns(before) <= ns(reply["fact"]["since"]) <= ns(after) or not reply["fact"]["transition"],
                   "a new fact is dated within the probe call", since=reply["fact"]["since"], called=[before, after])
        return reply

    def status(self) -> dict:
        reply = self.cli("status")
        self.check(reply.get("status") == "ok", "operator status answers")
        return reply

    def fact(self, status: dict) -> dict | None:
        return next((f for f in status["capability_facts"] if f["capability"] == CAPABILITY), None)

    def holds(self, status: dict) -> list[dict]:
        return [w for w in status["waiting"] if w["reason"] == "hold" and w["subject_ref"] == f"capability:{CAPABILITY}"]

    def clear_hold(self, hold_id: str) -> None:
        reply = self.cli("call", "apply_operator_decision", body={
            "decision_id": "opd_" + secrets.token_hex(12), "topic_id": None, "kind": "hold_clearance", "disposition": "approved",
            "subject": {"kind": "hold", "ref": hold_id, "revision": None, "hash": None}, "decided_at": utc(),
            "notes": "the capability's probe records it usable (auth demo)", "payload": None})
        self.check(reply.get("status") == "applied", "the operator's hold_clearance is applied", hold_id=hold_id, status=reply.get("status"))

    # -- the auth volume --------------------------------------------------------
    def write_credential(self, data: bytes | None, mode: str = "0600") -> None:
        """The operator's credential refresh: a helper container mounting the auth volume alone, as the service user."""
        self.sh(["docker", "run", "--rm", "--network", "none", "--user", f"{UID}:{GID}", "--read-only", "-i",
                 "-v", f"{AUTH_VOLUME}:/auth/codex", "--entrypoint", PY, IMAGE, "-c", WRITE, "/auth/codex", "remove" if data is None else mode],
                stdin=data or b"")

    def auth_home(self) -> dict:
        """The auth home as the engine container's service user sees it."""
        return json.loads(self.compose("exec", "-T", "engine", PY, "-c", STAT, "/auth/codex").stdout)

    def credential_state(self, home: dict) -> dict:
        return {k: home[k] for k in (".", "auth.json") if k in home}

    def container(self) -> dict:
        cid = self.compose("ps", "-q", "engine").stdout.decode().strip()
        self.check(bool(cid), "the engine container exists")
        # only these fields: the whole inspect document carries the container's environment, the env-file secrets among it
        info = json.loads(self.sh(["docker", "inspect", "--format", '{"Id": {{json .Id}}, "Image": {{json .Image}}, "StartedAt": {{json .State.StartedAt}}, '
                                   '"RestartCount": {{json .RestartCount}}, "Mounts": {{json .Mounts}}}', cid]).stdout)
        return {"id": info["Id"], "image": info["Image"], "started_at": info["StartedAt"], "restarts": info["RestartCount"],
                "mounts": sorted((m.get("Name") or m.get("Source"), m["Destination"], m["RW"]) for m in info["Mounts"])}

    def volumes(self) -> dict:
        out = {}
        for name in (STATE_VOLUME, AUTH_VOLUME):
            info = json.loads(self.sh(["docker", "volume", "inspect", name]).stdout)[0]
            out[name] = {"created": info["CreatedAt"], "project": info["Labels"].get("com.docker.compose.project")}
        return out

    def wait_healthy(self, timeout: float = 90) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            cid = self.compose("ps", "-q", "engine", quiet=True).stdout.decode().strip()
            state = self.sh(["docker", "inspect", "--format", "{{.State.Health.Status}}", cid], quiet=True).stdout.decode().strip() if cid else ""
            if state == "healthy":
                self.check(self.cli("health").get("status") == "ok", "the engine answers health on host loopback", port=self.port)
                return
            time.sleep(1)
        raise Failed("the engine did not become healthy")

    # -- setup and teardown ---------------------------------------------------
    def setup(self) -> None:
        self.log(f"run directory {self.dir}")
        self.sh(["docker", "version", "--format", "{{.Server.Version}}"])
        self.sh(["docker", "compose", "version"])
        before = self.sh(["docker", "ps", "-a", "--filter", f"label=com.docker.compose.project={PROJECT}", "--format", "{{.Names}}"])
        self.log(f"this project's containers before the run: {before.stdout.decode().split() or 'none'}")
        self.compose("--profile", "init", "down", "-v", "--remove-orphans")  # this project's resources only: a clean slate
        with socket.socket() as s:  # the contract: a published port is checked free on the deploying host, never shared
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # a listener refuses the bind; a closed connection's TIME-WAIT does not
            try:
                s.bind(("127.0.0.1", self.port))
                s.listen(1)
            except OSError as taken:
                raise SetupFailed(f"127.0.0.1:{self.port} is in use ({taken}); set GEN2_ENGINE_PORT to a free port") from None
        fd = os.open(self.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:  # throwaway secrets for this run (§3.1: one env file, 0400)
            f.write(f"GEN2_SECRETS=env\nGEN2_OPERATOR_TOKENS=demo={self.token}\nGEN2_SECRET_EXPORTER_TOKEN={self.exporter}\n")
        os.chmod(self.env_file, 0o400)
        self.compose("build", "engine", quiet=True, timeout=1800)
        image = json.loads(self.sh(["docker", "image", "inspect", IMAGE]).stdout)[0]
        self.image_id = image["Id"]
        self.log(f"image {IMAGE} {self.image_id} labels {json.dumps(image['Config']['Labels'], sort_keys=True)}")
        version = self.sh(["docker", "run", "--rm", "--network", "none", "--entrypoint", "codex", "-e", "CODEX_HOME=/tmp", IMAGE, "--version"])
        self.runner_version = version.stdout.decode().strip()
        self.compose("--profile", "init", "run", "--rm", "init-store")
        self.compose("up", "-d", "engine")
        self.wait_healthy()

    def teardown(self, keep: bool) -> None:
        try:
            logs = self.compose("logs", "--no-color", "--timestamps", "engine", quiet=True).stdout
            (self.dir / "engine.log").write_bytes(logs)
        except Exception as failure:  # noqa: BLE001 - teardown reports, never hides the run's own result
            self.log(f"engine log not kept: {failure}")
        if not keep:
            self.compose("--profile", "init", "down", "-v", "--remove-orphans")

    # -- the demonstrations --------------------------------------------------------
    def begin(self, name: str, title: str) -> None:
        self.log(f"=== ({name}) {title}")
        self.current = {"demo": name, "title": title, "status": "RUNNING", "assertions": [], "started": utc()}
        self.results.append(self.current)

    def baseline(self) -> None:
        """The run's first probe finds the fresh auth home empty; a credential written, the next finds it usable."""
        self.begin("setup", "a fresh auth volume, then a first credential")
        home = self.auth_home()
        self.check(home["."]["mode"] == "0700" and (home["."]["uid"], home["."]["gid"]) == (UID, GID) and set(home) == {"."},
                   "the fresh auth volume is an empty 0700 directory of the service user", home=home["."])
        first = self.probe()
        self.check(first["outcome"] == "unusable_credential" and first["fact"]["state"] == "failing" and first["fact"]["transition"],
                   "with no credential, the first probe records a failing fact", reply=first)
        self.write_credential(api_key())
        usable = self.probe()
        self.check(usable["outcome"] == "usable" and usable["fact"]["state"] == "healthy" and usable["fact"]["transition"],
                   "a credential written, the next probe records the recovery", fact=usable["fact"])
        self.clear_hold(first["hold"]["hold_id"])
        self.check(self.holds(self.status()) == [], "no capability hold is open")

    def demo_a(self) -> None:
        self.begin("a", "a credential refresh in the live auth volume is picked up without a rebuild")
        engine = self.container()
        self.write_credential(None)
        broken = self.probe()
        self.check(broken["outcome"] == "unusable_credential" and broken["fact"]["state"] == "failing" and broken["hold"]["opened"],
                   "precondition: the credential removed, the probe records it failing and opens the capability's hold", reply=broken)
        refreshed_bytes = api_key()
        refreshed_at = utc()
        self.write_credential(refreshed_bytes)
        after = self.probe()
        self.check(after["outcome"] == "usable" and after["fact"]["state"] == "healthy" and after["fact"]["transition"],
                   "the next probe picks up the refreshed credential: a new healthy fact", fact=after["fact"])
        self.check(ns(after["fact"]["since"]) >= ns(refreshed_at), "the recovery is dated after the refresh",
                   since=after["fact"]["since"], refreshed_at=refreshed_at)
        home = self.auth_home()
        self.check(home["auth.json"]["sha256"] == hashlib.sha256(refreshed_bytes).hexdigest() and home["auth.json"]["mode"] == "0600"
                   and (home["auth.json"]["uid"], home["auth.json"]["gid"]) == (UID, GID),
                   "the engine container sees exactly the refreshed bytes, 0600, the service user's", auth_json=home["auth.json"])
        now = self.container()
        self.check(now == engine, "the same container, never recreated or restarted, on the same image", before=engine, after=now)
        self.check(now["image"] == self.image_id, "the image is the one built at setup: no rebuild", image=now["image"])
        status = self.status()
        self.check(self.fact(status)["fact_id"] == after["fact"]["fact_id"] and self.fact(status)["state"] == "healthy",
                   "operator status shows the recovery fact", fact=self.fact(status))
        open_holds = self.holds(status)
        self.check([h["hold_id"] for h in open_holds] == [broken["hold"]["hold_id"]],
                   "the hold stays open until the operator clears it: a usable probe clears nothing", holds=open_holds)
        self.clear_hold(broken["hold"]["hold_id"])
        self.check(self.holds(self.status()) == [], "cleared by the operator, no capability hold is open")

    def demo_b(self) -> None:
        self.begin("b", "restart and container replacement preserve auth-volume access and permissions")
        start = self.probe()
        self.check(start["outcome"] == "usable", "precondition: the credential is usable", reply=start)
        engine, volumes, home = self.container(), self.volumes(), self.auth_home()
        bundle = self.status()["config_bundles"]["active"]
        self.compose("restart", "engine")
        self.wait_healthy()
        restarted = self.container()
        self.check(restarted["id"] == engine["id"] and restarted["started_at"] != engine["started_at"],
                   "restart: the same container, started again", before=engine["started_at"], after=restarted["started_at"])
        self.check(self.credential_state(self.auth_home()) == self.credential_state(home),
                   "restart: the auth home and credential are as they were (bytes, mode, owner, inode)")
        again = self.probe()
        self.check(again["outcome"] == "usable" and again["fact"]["fact_id"] == start["fact"]["fact_id"] and not again["fact"]["transition"],
                   "restart: the probe agrees, and the capability's fact carries on", fact=again["fact"])
        self.compose("down")  # the container and network removed; the volumes kept
        self.compose("up", "-d", "engine")
        self.wait_healthy()
        replaced = self.container()
        self.check(replaced["id"] != engine["id"], "replacement: a new container", before=engine["id"], after=replaced["id"])
        self.check(replaced["mounts"] == engine["mounts"], "replacement: the same volumes at the same paths", mounts=replaced["mounts"])
        self.check(self.volumes() == volumes, "replacement: the volumes are the ones created at setup (not re-created)", volumes=volumes)
        after = self.auth_home()
        self.check(after["."] == home["."] and after["."]["mode"] == "0700" and (after["."]["uid"], after["."]["gid"]) == (UID, GID),
                   "replacement: the auth home is the same 0700 directory of the service user", before=home["."], after=after["."])
        self.check(self.credential_state(after) == self.credential_state(home),
                   "replacement: the credential's bytes, mode, owner and inode are unchanged", auth_json=after.get("auth.json"))
        probed = self.probe()
        self.check(probed["outcome"] == "usable" and probed["fact"]["fact_id"] == start["fact"]["fact_id"] and not probed["fact"]["transition"],
                   "replacement: the new container's probe agrees, and the fact recorded before replacement carries on", fact=probed["fact"])
        self.check(self.status()["config_bundles"]["active"] == bundle, "replacement: the active config bundle pin is unchanged", bundle=bundle)

    def sampler(self) -> subprocess.Popen:
        """SAMPLER, started in the engine container, answering once it samples."""
        argv = ["docker", "compose", "-p", PROJECT, *(a for f in self.compose_files for a in ("-f", str(f))), "exec", "-T", "engine", PY, "-c", SAMPLER, "900"]
        self.log("$ " + " ".join(argv[:-3]) + " -c SAMPLER 900  (in the background)")
        child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, cwd=REPO)
        first = child.stdout.readline()
        if first != b"sampling\n":
            child.kill()
            raise Failed(f"the process sampler did not start: {first!r} {child.stderr.read().decode('utf-8', 'replace')[-500:]}")
        return child

    def sampled(self, child: subprocess.Popen) -> dict:
        """The sampler's record, its stdin closed; its exit status is checked, never assumed."""
        child.stdin.close()
        out, err = child.stdout.read(), child.stderr.read()
        code = child.wait(timeout=60)
        self.log(f"  sampler exit {code}")
        if err.strip():
            self.log_file.write(f"  --- stderr\n{err.decode('utf-8', 'replace').rstrip()}\n")
        self.check(code == 0, "the process sampler ran to its end", exit=code)
        return json.loads(out)

    def rounds(self, name: str) -> dict:
        """ROUNDS rounds of two probe_capability requests leaving a barrier together, the engine container's processes
        sampled throughout; per round, both replies and the credential's state are checked."""
        start = self.probe()
        self.check(start["outcome"] == "usable", "precondition: the credential is usable")
        before = self.credential_state(self.auth_home())
        replies, windows, whole = [], [], 0
        sampler = self.sampler()
        try:
            for round_no in range(1, ROUNDS + 1):
                barrier, pair, errors = threading.Barrier(2), [None, None], []

                def one(slot: int) -> None:  # the CLI's own client function, in this process: both requests leave at the barrier
                    try:
                        barrier.wait(timeout=30)
                        code, reply = cli_request(f"http://127.0.0.1:{self.port}", self.token, "POST", "/v1/commands/probe_capability",
                                                  b'{"provider": "codex"}')
                        self.log(f"  round {round_no} slot {slot}: HTTP {code} {json.dumps(reply, sort_keys=True)}")
                        pair[slot] = reply if code == 200 else {"status": f"http_{code}"}
                    except BaseException as failure:  # noqa: BLE001 - reported below as this round's failure
                        errors.append(repr(failure))
                threads = [threading.Thread(target=one, args=(slot,)) for slot in (0, 1)]
                begun = time.time_ns()
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                windows.append((begun, time.time_ns()))
                self.check(not errors, f"round {round_no}: both probe calls answered", errors=errors)
                self.replies.extend(pair)
                replies.extend(pair)
                self.check(all(r["status"] == "recorded" and r["outcome"] == "usable" for r in pair),
                           f"round {round_no}: both probes classify the credential usable", outcomes=[r["outcome"] for r in pair])
                probes = [(ns(r["started_at"]), ns(r["observed_at"])) for r in pair]  # each whole probe, as recorded: not its runner's run
                whole += max(w[0] for w in probes) < min(w[1] for w in probes)
                self.log(f"  round {round_no}: whole-probe windows {[(w[1] - w[0]) // 1000 for w in probes]} us (auth-home check, workspace, "
                         f"--version, login status, declared-expiry read, cleanup), intersecting={max(w[0] for w in probes) < min(w[1] for w in probes)}")
                now = self.credential_state(self.auth_home())
                self.check(now == before, f"round {round_no}: the credential's bytes, mode, owner and inode are as before (read after the round)",
                           **({} if now == before else {"before": before, "after": now}))
        except BaseException:  # the round's own failure is the one reported: the sampler is ended, unread
            sampler.kill()
            sampler.wait()
            raise
        seen = self.sampled(sampler)
        (self.dir / f"{name}-processes.json").write_text(json.dumps({"windows_ns": windows, **seen}, indent=2, sort_keys=True))
        in_round = lambda at: next((n for n, (b, e) in enumerate(windows, 1) if b <= at <= e), None)  # noqa: E731
        together = sorted({in_round(first) for first, _last, _count in seen["together"].values()} - {None})
        processes = [sum(1 for first, _last in seen["processes"].values() if in_round(first) == n) for n in range(1, ROUNDS + 1)]
        self.log(f"  sampler: {seen['scans']} scans, {len(seen['processes'])} login status processes seen (per round {processes}); "
                 f"two live at one instant in rounds {together}; whole-probe windows intersected in {whole} rounds")
        status = self.status()
        self.check(self.fact(status)["fact_id"] == start["fact"]["fact_id"] and self.holds(status) == [],
                   "operator status: the fact carries on unchanged, no hold opened", fact=self.fact(status))
        self.check(all(r["fact"]["fact_id"] == start["fact"]["fact_id"] and not r["fact"]["transition"] for r in replies),
                   "no probe of the rounds moved the fact")
        return {"rounds": ROUNDS, "together": together, "processes_per_round": processes, "whole_probe_windows_intersecting": whole,
                "scans": seen["scans"], "pairs": len(seen["together"])}

    @staticmethod
    def overlapped(evidence: dict) -> bool:
        """(c)'s overlap assertion: in at least one round, two login status processes were live at one instant."""
        return len(evidence["together"]) >= 1

    def demo_c(self) -> None:
        self.begin("c", f"two simultaneous probes against one auth home, {ROUNDS} rounds")
        evidence = self.rounds("c")
        self.check(self.overlapped(evidence), "in at least one round two codex login status processes were live at one instant "
                   "(the engine container's process table, sampled)", rounds=evidence["together"], pairs=evidence["pairs"])
        self.current["evidence"] = evidence

    def demo_c_control(self) -> None:
        self.begin("c-control", "(c)'s negative control: the runner serialized after each probe's start; (c)'s overlap assertion must fail")
        source = (REPO / "gen2/supervisor/probe.py").read_text()
        needle, patched = SERIALIZE
        if source.count(needle) != 1 or source.count("\nimport time\n") != 1 or "\nimport threading\n" in source:
            raise Failed("the serializing patch does not apply to gen2/supervisor/probe.py as it stands")
        patched = source.replace(needle, patched).replace("\nimport time\n", "\nimport threading\nimport time\n\n_SERIALIZED = threading.Lock()\n", 1)
        control = self.dir / "c-control"
        control.mkdir()
        (control / "probe.py").write_text(patched)
        (control / "probe.py").chmod(0o644)
        (control / "compose.override.yaml").write_text(
            f"services:\n  engine:\n    volumes:\n      - {control / 'probe.py'}:{PROBE_IN_IMAGE}:ro\n")
        self.compose_files = [COMPOSE_FILE, control / "compose.override.yaml"]
        try:
            self.compose("up", "-d", "engine")
            self.wait_healthy()
            running = self.compose("exec", "-T", "engine", "sha256sum", PROBE_IN_IMAGE).stdout.decode().split()[0]
            self.check(running == hashlib.sha256(patched.encode()).hexdigest(), "the engine runs the serialized probe", sha256=running)
            evidence = self.rounds("c-control")
            self.check(sum(evidence["processes_per_round"]) >= ROUNDS and all(evidence["processes_per_round"]),
                       "the sampler saw login status processes in every round", per_round=evidence["processes_per_round"])
            self.check(not self.overlapped(evidence), "(c)'s overlap assertion fails with the runner serialized: no two login status processes "
                       "live at one instant", rounds=evidence["together"], whole_probe_windows_intersecting=evidence["whole_probe_windows_intersecting"])
            self.current["evidence"] = evidence
        finally:  # the image's own probe again, whatever happened here
            self.compose_files = [COMPOSE_FILE]
            self.compose("up", "-d", "engine")
            self.wait_healthy()
            running = self.compose("exec", "-T", "engine", "sha256sum", PROBE_IN_IMAGE).stdout.decode().split()[0]
            self.check(running == hashlib.sha256(source.encode()).hexdigest(), "the engine runs the repository's probe again", sha256=running)

    def demo_d(self, name: str, title: str, data: bytes | None, outcome: str | None, state: str | None, gap: str | None = None) -> dict:
        """A credential written (data None: the usable one left exactly as it is), then the contract's (d): a dated fact
        and the typed capability hold, never a silent success — the fact `state` from `outcome`, where the probe's outcome
        is known (None: any not usable, any not healthy)."""
        self.begin(name, title)
        start = self.probe()
        self.check(start["outcome"] == "usable", "precondition: the credential is usable")
        before = self.credential_state(self.auth_home())
        if data is None:
            self.log("  the credential is left as it is: a revocation, or an expiry it does not declare, changes no local byte")
        else:
            self.write_credential(data)
        called = utc()
        reply = self.probe()
        try:
            if data is None:
                self.check(self.credential_state(self.auth_home()) == before, "the credential is byte for byte the one just probed usable")
            self.check(reply["outcome"] != "usable" and reply["fact"]["state"] != "healthy",
                       "never a silent success: the probe does not record the credential usable", outcome=reply["outcome"],
                       fact=reply["fact"], **({"known_gap": gap} if gap else {}))
            outcome, state = outcome or reply["outcome"], state or reply["fact"]["state"]
            self.check(reply["outcome"] == outcome and reply["fact"]["state"] == state and reply["fact"]["transition"],
                       f"a {state} capability fact is recorded ({outcome})", fact=reply["fact"])
            self.check(ns(called) <= ns(reply["fact"]["since"]), "the fact is dated at the probe", since=reply["fact"]["since"], called=called)
            status = self.status()
            fact, holds = self.fact(status), self.holds(status)
            self.check(fact == {**fact, "fact_id": reply["fact"]["fact_id"], "state": state, "since": reply["fact"]["since"]},
                       f"operator status shows the dated {state} fact", fact=fact)
            self.check(fact["last_success_at"] is not None and ns(fact["last_success_at"]) <= ns(fact["since"]),
                       "the fact names its last success", last_success_at=fact["last_success_at"])
            self.check(len(holds) == 1 and holds[0]["hold_id"] == reply["hold"]["hold_id"], "operator status is waiting on the capability's hold",
                       holds=holds)
            hold = holds[0]
            self.check(hold["hold_class"] == "capability" and hold["owner"] == "operator" and hold["required_authority"] == "operator"
                       and hold["capability_fact_id"] == reply["fact"]["fact_id"] and ns(hold["deadline_at"]) > ns(reply["fact"]["since"])
                       and not hold["deadline_passed"] and hold["clears_when"] and hold["recoverability"] == "needs_remediation",
                       "the hold is typed (capability), owned (operator), deadlined, bound to the fact, and says what clears it", hold=hold)
            return {"reply": reply, "fact": fact}
        finally:  # the next demonstration starts from a usable credential and no open hold, whatever happened here
            self.write_credential(api_key())
            restored = self.cli("call", "probe_capability", body={"provider": "codex"})
            self.replies.append(restored)
            for hold in self.holds(self.cli("status")):
                self.cli("call", "apply_operator_decision", body={
                    "decision_id": "opd_" + secrets.token_hex(12), "topic_id": None, "kind": "hold_clearance", "disposition": "approved",
                    "subject": {"kind": "hold", "ref": hold["hold_id"], "revision": None, "hash": None}, "decided_at": utc(),
                    "notes": "restored after the demonstration", "payload": None})

    def demo_d2a(self) -> None:
        shape = SHAPES["chatgpt_expired"]
        seen = self.demo_d("d2a", "an expired credential that declares its expiry: a dated degraded fact and a typed capability hold in status",
                           shape.make(), "declared_expired", "degraded", shape.gap)
        reply, fact = seen["reply"], seen["fact"]
        self.check(reply["declared_expiry"] == {"access_token": "2001-09-09T01:46:40Z", "id_token": "2001-09-09T01:46:40Z", "refresh_credential": True},
                   "the record names the declared expiries (access and ID token, from their JWT exp) and that a refresh credential is present",
                   declared_expiry=reply["declared_expiry"])
        self.check(fact["detail"].startswith("declared_expired: the runner reads the credential, but its access token declares it expired at "
                                             "2001-09-09T01:46:40Z: the credential's own claim, not the provider's answer"),
                   "the fact says the expiry is the credential's own claim, not the provider's answer", detail=fact["detail"])

    def demo_e(self) -> None:
        self.begin("e", "characterization: the pinned runner's own verdicts, no network, per credential shape; then the declared expiry")
        runner = RUNNERS["codex"]
        table = {}
        for name, shape in SHAPES.items():
            data = shape.make()
            done = self.sh(["docker", "run", "--rm", "--network", "none", "--user", f"{UID}:{GID}", "--read-only", "--tmpfs", "/tmp:mode=1777",
                            "--tmpfs", f"/auth:mode=0700,uid={UID},gid={GID}", "-i", "--entrypoint", PY, IMAGE, "-c", CHARACTERIZE, name],
                           stdin=data)
            raw = json.loads(done.stdout)
            self.check(raw["version"]["code"] == 0 and raw["version"]["stdout"] == runner.version_stdout, f"{name}: the runner is {runner.version}")
            outcome, detail = runner.classify(raw["status"]["code"], raw["status"]["stdout"], raw["status"]["stderr"])
            declared = runner.declared(json.loads(data)) if outcome == "usable" else None  # the probe's own reader, over the same bytes
            verdict = declared_verdict(declared, utc()) or (outcome, detail)
            table[name] = {"exit": raw["status"]["code"], "stderr": raw["status"]["stderr"].strip(), "runner_outcome": outcome,
                           "declared_expiry": declared, "probe_outcome": verdict[0], "detail": verdict[1], "gap": shape.gap}
            self.check(outcome == shape.runner, f"{name}: the probe's rules give the runner's answer {shape.runner}", exit=raw["status"]["code"],
                       outcome=outcome)
            self.check(verdict[0] == shape.probe, f"{name}: the probe records {shape.probe}" + (f" — {shape.gap}" if shape.gap else ""),
                       declared_expiry=declared)
        (self.dir / "characterization.json").write_text(json.dumps(table, indent=2, sort_keys=True))
        self.current["evidence"] = table

    # -- the store, read back after the engine stops ------------------------------
    def store_readback(self) -> None:
        self.begin("z", "the store's whole record, read from a copy taken after the engine stopped")
        self.compose("stop", "engine")
        copy = self.dir / "store"
        copy.mkdir()
        for suffix in ("", "-wal", "-shm"):  # the store and, if the engine left them, its WAL files: a quiescent copy, the engine stopped
            self.compose("cp", f"engine:/var/lib/gen2/state/store.sqlite3{suffix}", str(copy / f"store.sqlite3{suffix}"), ok=(0,) if not suffix else (0, 1))
        left = sorted(p.name for p in copy.iterdir() if p.name != "store.sqlite3")
        self.check(left == [], "the stop (SIGINT) ran the engine's own close: the store's connection closed, no WAL left behind", left=left)
        db = sqlite3.connect(copy / "store.sqlite3")  # this run's private copy: nothing else opens it
        try:
            audits = {json.loads(d)["observation"]["probe_id"]: json.loads(d)
                      for (d,) in db.execute("SELECT detail FROM audit_events WHERE kind = 'capability_probe' ORDER BY rowid")}
            facts = [dict(zip(("fact_id", "state", "since", "superseded_by_fact_id"), row)) for row in
                     db.execute("SELECT fact_id, state, since, superseded_by_fact_id FROM capability_facts WHERE capability = ? ORDER BY rowid", (CAPABILITY,))]
            holds = db.execute("SELECT hold_id, hold_class, capability_fact_id, cleared_at, cleared_by_decision_id FROM holds "
                               "WHERE subject_ref = ? ORDER BY rowid", (f"capability:{CAPABILITY}",)).fetchall()
        finally:
            db.close()
        self.check(sorted(audits) == sorted(r["probe_id"] for r in self.replies), "every probe reply the run received is recorded, and nothing else",
                   recorded=len(audits), replies=len(self.replies))
        self.check(all(audits[r["probe_id"]]["reply"] == {**r, "status": "recorded"} for r in self.replies),
                   "each recorded reply is the reply the run received")
        self.check(all(a["state"] != b["state"] and a["superseded_by_fact_id"] == b["fact_id"] for a, b in zip(facts, facts[1:]))
                   and facts[-1]["superseded_by_fact_id"] is None, "the fact history is one chain of transitions, each a change of state",
                   states=[f["state"] for f in facts])
        failing = {f["fact_id"] for f in facts if f["state"] != "healthy"}
        self.check(all(h[1] == "capability" and h[2] in failing for h in holds), "every capability hold is bound to a fact not healthy",
                   holds=len(holds))
        self.check(all(h[3] is not None and h[4] is not None for h in holds), "every hold the run opened was cleared by an operator decision")
        self.current["evidence"] = {"probes": len(audits), "facts": [f["state"] for f in facts], "holds": len(holds)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auth_demo.py")
    parser.add_argument("--only", help=f"comma-separated subset of {','.join(DEMOS)}")
    parser.add_argument("--keep", action="store_true", help="keep this project's containers and volumes after the run")
    args = parser.parse_args(argv)
    chosen = DEMOS if not args.only else tuple(args.only.split(","))
    if set(chosen) - set(DEMOS):
        parser.error(f"unknown demonstrations: {sorted(set(chosen) - set(DEMOS))}")
    root = Path(os.environ.get("GEN2_AUTH_DEMO_LOG_DIR", "/var/tmp/gen2-auth-demo"))
    run_dir = root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, mode=0o700)
    demo = Demo(run_dir, int(os.environ.get("GEN2_ENGINE_PORT", "8770")))
    code = 0
    try:
        demo.setup()
        steps = [("setup", demo.baseline)] + [(name, step) for name, step in (
            ("a", demo.demo_a), ("b", demo.demo_b), ("c", demo.demo_c), ("c-control", demo.demo_c_control),
            ("d1", lambda: demo.demo_d("d1", "an invalid credential: a dated failing fact and a typed capability hold in status",
                                       SHAPES["id_token_garbage"].make(), "unusable_credential", "failing")),
            ("d2a", demo.demo_d2a),
            ("d2b", lambda: demo.demo_d("d2b", "a revoked credential, or one expired without declaring it (the residual of (d)): a dated fact and a "
                                               "typed capability hold in status", None, None, None,
                                        "revocation, and an expiry the credential does not declare, change no local byte: no local probe sees them "
                                        "(AUTH-DEMO.md F1, the operator's)")),
            ("e", demo.demo_e)) if name in chosen] + [("z", demo.store_readback)]
        for name, step in steps:
            try:
                step()
                demo.current["status"] = "PASS"
            except Failed as failure:
                demo.current["status"] = "FAIL"
                demo.current["failure"] = str(failure)
                demo.log(f"  ({name}) FAILED: {failure}")
                code = 1
                if name == "setup":
                    break
    except (SetupFailed, Failed, subprocess.TimeoutExpired, OSError) as failure:
        demo.log(f"SETUP FAILED: {failure}")
        code = 2
    finally:
        demo.teardown(args.keep)
        if demo.env_file.exists():
            os.remove(demo.env_file)
        results = [{k: r[k] for k in ("demo", "title", "status") if k in r} | ({"failure": r["failure"]} if "failure" in r else {}) for r in demo.results]
        summary = {"runner": getattr(demo, "runner_version", None), "image": getattr(demo, "image_id", None), "port": demo.port, "results": results}
        (run_dir / "summary.json").write_text(json.dumps({**summary, "detail": demo.results}, indent=2, sort_keys=True))
        demo.log("SUMMARY " + json.dumps(results))
        leaked = sorted(str(p.relative_to(run_dir)) for p in run_dir.rglob("*") if p.is_file() and demo.token.encode() in p.read_bytes())
        demo.log(f"the operator token appears in {leaked or 'no'} kept file (run log, engine log, summary, characterization, store copy)")
        if leaked:
            code = code or 1
        demo.log(f"exit {code}; logs in {run_dir}")
        demo.log_file.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
