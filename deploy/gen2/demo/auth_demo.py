#!/usr/bin/env python3
"""The four DEPLOYMENT-CONTRACT.md §4 auth-volume demonstrations (task 1f),
run against the minimal compose slice (deploy/gen2/compose.yaml) with the
pinned runner (codex 0.153.2, baked in deploy/gen2/Dockerfile).

    python deploy/gen2/demo/auth_demo.py [--only a,b,c,d1,d2,e] [--keep]
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
      permissions are unchanged, and at least one round's two runner runs
      overlapped in time (read from the probes' own recorded instants)
  d1  an invalid credential: a dated failing fact and a typed capability hold,
      owned and deadlined, in operator status — never a silent success
  d2  an expired credential, as the contract words (d): the same fact and
      hold required. With this runner it is NOT met (docs/gen2/AUTH-DEMO.md):
      this demonstration fails, and says so
  e   characterization: the pinned runner itself, with no network at all,
      over each throwaway credential shape; the probe's rules applied to its
      output — the version-pinned table AUTH-DEMO.md reports

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
from gen2.supervisor.probe import RUNNERS  # noqa: E402

PROJECT = "gen2-authdemo"
IMAGE = "gen2-engine:1f-authdemo"
COMPOSE_FILE = REPO / "deploy/gen2/compose.yaml"
BUNDLE = REPO / "deploy/gen2/demo/bundle.json"
UID = GID = 10001
AUTH_VOLUME = f"{PROJECT}_auth-codex"
STATE_VOLUME = f"{PROJECT}_state"
CAPABILITY = "provider-auth:codex"
DEMOS = ("a", "b", "c", "d1", "d2", "e")
ROUNDS = 20
PY = "/opt/gen2/venv/bin/python"

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


def chatgpt_tokens(exp: int) -> bytes:
    """Throwaway ChatGPT-mode tokens (unsigned; nothing here is a real account)."""
    claims = {"exp": exp, "iat": exp - 3600, "email": "throwaway@example.invalid",
              "https://api.openai.com/auth": {"chatgpt_plan_type": "plus", "chatgpt_account_id": "acct-throwaway"}}
    return json.dumps({"OPENAI_API_KEY": None, "last_refresh": "2001-09-09T00:00:00Z",
                       "tokens": {"id_token": jwt(claims), "access_token": jwt(claims), "refresh_token": "rt-throwaway-" + secrets.token_hex(8),
                                  "account_id": "acct-throwaway"}}).encode()


def api_key() -> bytes:
    return json.dumps({"OPENAI_API_KEY": "sk-throwaway-1f-" + secrets.token_hex(16)}).encode()


SHAPES = {  # characterization (e): shape -> (bytes, the outcome the probe's rules give for codex 0.153.2, is it a gap)
    "absent": (lambda: b"", "unusable_credential", None),
    "api_key": (api_key, "usable", None),
    "api_key_empty": (lambda: b'{"OPENAI_API_KEY": ""}', "usable", "an empty API key reads as a credential"),
    "empty_object": (lambda: b"{}", "usable", "an empty object reads as ChatGPT tokens"),
    "chatgpt_unexpired": (lambda: chatgpt_tokens(4102444800), "usable", None),
    "chatgpt_expired": (lambda: chatgpt_tokens(1000000000), "usable", "tokens that expired in 2001 read as usable: expiry is not checked locally"),
    "id_token_garbage": (lambda: b'{"OPENAI_API_KEY": null, "tokens": {"id_token": "not-a-jwt", "access_token": "x", "refresh_token": "y", "account_id": "z"}}',
                         "unusable_credential", None),
    "malformed_json": (lambda: b"{not json", "unusable_credential", None),
    "empty_file": (lambda: b"", "unusable_credential", None),
    "unreadable": (api_key, "unusable_credential", None),
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
        return self.sh(["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE_FILE), *args], **kw)

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

    def demo_c(self) -> None:
        self.begin("c", f"two simultaneous probes against one auth home, {ROUNDS} rounds")
        start = self.probe()
        self.check(start["outcome"] == "usable", "precondition: the credential is usable")
        before = self.credential_state(self.auth_home())
        overlapped, replies = 0, []
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
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.check(not errors, f"round {round_no}: both probe calls answered", errors=errors)
            self.replies.extend(pair)
            replies.extend(pair)
            self.check(all(r["status"] == "recorded" and r["outcome"] == "usable" for r in pair),
                       f"round {round_no}: both probes classify the credential usable", outcomes=[r["outcome"] for r in pair])
            windows = [(ns(r["started_at"]), ns(r["observed_at"])) for r in pair]  # the runner's run, as the router recorded it
            if max(w[0] for w in windows) < min(w[1] for w in windows):
                overlapped += 1
            self.log(f"  round {round_no}: runner windows {[(w[1] - w[0]) // 1000 for w in windows]} us, overlap={max(w[0] for w in windows) < min(w[1] for w in windows)}")
        after = self.credential_state(self.auth_home())
        self.check(after == before, "the credential's bytes, mode, owner and inode are unchanged after every round", before=before, after=after)
        self.check(overlapped >= 1, "at least one round's two runner runs overlapped in time (the probes' own recorded instants)",
                   overlapped=overlapped, rounds=ROUNDS)
        status = self.status()
        self.check(self.fact(status)["fact_id"] == start["fact"]["fact_id"] and self.holds(status) == [],
                   "operator status: the fact carries on unchanged, no hold opened", fact=self.fact(status))
        self.check(all(r["fact"]["fact_id"] == start["fact"]["fact_id"] and not r["fact"]["transition"] for r in replies),
                   "no probe of the rounds moved the fact")
        self.current["evidence"] = {"rounds": ROUNDS, "overlapped": overlapped}

    def demo_d(self, name: str, title: str, data: bytes, gap: str | None) -> None:
        self.begin(name, title)
        start = self.probe()
        self.check(start["outcome"] == "usable", "precondition: the credential is usable")
        self.write_credential(data)
        called = utc()
        reply = self.probe()
        try:
            self.check(reply["outcome"] != "usable" and reply["fact"]["state"] != "healthy",
                       "never a silent success: the probe does not record the credential usable", outcome=reply["outcome"],
                       fact=reply["fact"], **({"known_gap": gap} if gap else {}))
            self.check(reply["outcome"] == "unusable_credential" and reply["fact"]["state"] == "failing" and reply["fact"]["transition"],
                       "a failing capability fact is recorded", fact=reply["fact"])
            self.check(ns(called) <= ns(reply["fact"]["since"]), "the fact is dated at the probe", since=reply["fact"]["since"], called=called)
            status = self.status()
            fact, holds = self.fact(status), self.holds(status)
            self.check(fact == {**fact, "fact_id": reply["fact"]["fact_id"], "state": "failing", "since": reply["fact"]["since"]},
                       "operator status shows the dated failing fact", fact=fact)
            self.check(fact["last_success_at"] is not None and ns(fact["last_success_at"]) <= ns(fact["since"]),
                       "the fact names its last success", last_success_at=fact["last_success_at"])
            self.check(len(holds) == 1 and holds[0]["hold_id"] == reply["hold"]["hold_id"], "operator status is waiting on the capability's hold",
                       holds=holds)
            hold = holds[0]
            self.check(hold["hold_class"] == "capability" and hold["owner"] == "operator" and hold["required_authority"] == "operator"
                       and hold["capability_fact_id"] == reply["fact"]["fact_id"] and ns(hold["deadline_at"]) > ns(reply["fact"]["since"])
                       and not hold["deadline_passed"] and hold["clears_when"] and hold["recoverability"] == "needs_remediation",
                       "the hold is typed (capability), owned (operator), deadlined, bound to the fact, and says what clears it", hold=hold)
        finally:  # the next demonstration starts from a usable credential and no open hold, whatever happened here
            self.write_credential(api_key())
            restored = self.cli("call", "probe_capability", body={"provider": "codex"})
            self.replies.append(restored)
            for hold in self.holds(self.cli("status")):
                self.cli("call", "apply_operator_decision", body={
                    "decision_id": "opd_" + secrets.token_hex(12), "topic_id": None, "kind": "hold_clearance", "disposition": "approved",
                    "subject": {"kind": "hold", "ref": hold["hold_id"], "revision": None, "hash": None}, "decided_at": utc(),
                    "notes": "restored after the demonstration", "payload": None})

    def demo_e(self) -> None:
        self.begin("e", "characterization: the pinned runner's own verdicts, no network, per credential shape")
        runner = RUNNERS["codex"]
        table = {}
        for shape, (make, expected, gap) in SHAPES.items():
            done = self.sh(["docker", "run", "--rm", "--network", "none", "--user", f"{UID}:{GID}", "--read-only", "--tmpfs", "/tmp:mode=1777",
                            "--tmpfs", f"/auth:mode=0700,uid={UID},gid={GID}", "-i", "--entrypoint", PY, IMAGE, "-c", CHARACTERIZE, shape],
                           stdin=make())
            raw = json.loads(done.stdout)
            self.check(raw["version"]["code"] == 0 and raw["version"]["stdout"] == runner.version_stdout, f"{shape}: the runner is {runner.version}")
            outcome, detail = runner.classify(raw["status"]["code"], raw["status"]["stdout"], raw["status"]["stderr"])
            table[shape] = {"exit": raw["status"]["code"], "stderr": raw["status"]["stderr"].strip(), "outcome": outcome, "detail": detail, "gap": gap}
            self.check(outcome == expected, f"{shape}: the probe's rules give {expected}" + (f" — KNOWN GAP: {gap}" if gap else ""),
                       exit=raw["status"]["code"], outcome=outcome)
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
        self.check(all(h[1] == "capability" and h[2] in failing for h in holds), "every capability hold is bound to a failing or unknown fact",
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
            ("a", demo.demo_a), ("b", demo.demo_b), ("c", demo.demo_c),
            ("d1", lambda: demo.demo_d("d1", "an invalid credential: a dated fact and a typed capability hold in status",
                                       SHAPES["id_token_garbage"][0](), None)),
            ("d2", lambda: demo.demo_d("d2", "an expired credential (the contract's (d) case): a dated fact and a typed capability hold in status",
                                       SHAPES["chatgpt_expired"][0](), SHAPES["chatgpt_expired"][2])),
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
