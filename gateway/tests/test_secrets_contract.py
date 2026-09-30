"""DEPLOYMENT-CONTRACT §3.4: the eight acceptance fixtures for the vault backend, as tests.

Each fixture runs against the gateway with the vault backend selected, reading from a
loopback Vault (tests/fake_vault.py) that answers the way KV v2 does. Fixtures 1 and 2
start the real entrypoint (`python -m research_gateway.api.http`) in a child process
with a controlled HOME and environment; the others drive the assembled service — the
Gateway and its HTTP front door on an ephemeral loopback port — or, where the fixture
is about one read, the backend itself with an injected clock. No provider is called:
provider answers come from FakeTransport. (Task 2b; INVARIANTS H-2, RG-4, RG-U.)

What these cannot show: the run inside the service's container image (the fixture
list's own setting), which needs the dedicated gen-2 gateway deployment (task 2e1);
the child-process fixtures stand in for it with the same entrypoint and environment.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from research_gateway import app
from research_gateway.adapters.base import FakeTransport
from research_gateway.api import http as api
from research_gateway.core import alerts, router, secrets
from tests.fake_vault import FakeVault

GATEWAY_DIR = Path(__file__).resolve().parent.parent
TOKENS = {"engine": "tok-engine-secret"}
T0 = 1790019900.0   # 2026-09-21T19:45:00Z; the outage starts two minutes later
OUTAGE = T0 + 120   # 2026-09-21T19:47:00Z
SECRETS = {"fred": {"api_key": "fred-key-123456"}, "bea": {"key": "bea-key-123456"},
           "census": {"key": "census-key-123456"}, "bls": {"key": "bls-key-123456"},
           "research_gateway": {"tokens": "engine=tok-engine-secret"}}
KEYED_DATA = {"fred": {"series": "GDP"}, "bea": {"method": "GetData", "dataset": "NIPA", "table": "T10101", "frequency": "Q", "year": "2024"},
              "census": {"dataset": "2022/acs/acs1", "get": "NAME"}, "bls": {"series": "CUUR0000SA0"}}
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith(("RESEARCH_GATEWAY_SECRET_", "RESEARCH_GATEWAY_VAULT"))}


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t


def providers() -> FakeTransport:
    t = FakeTransport()
    t.add("GET", "https://api.stlouisfed.org/fred/series/observations?", body={"observations": [{"date": "2026-01-01", "value": "1.0"}]})
    t.add("GET", "https://api.stlouisfed.org/fred/series?", body={"seriess": [{"id": "GDP", "title": "Gross Domestic Product", "notes": "."}]})
    t.add("GET", "https://apps.bea.gov/api/data/?", body={"BEAAPI": {"Results": {
        "Data": [{"TableName": "T10101", "LineDescription": "Gross domestic product", "TimePeriod": "2024", "DataValue": "3.1"}]}}})
    t.add("GET", "https://api.census.gov/data/2022/acs/acs1?", body=[["NAME", "state"], ["North Carolina", "37"]])
    t.add("POST", "https://api.bls.gov/publicAPI/v2/timeseries/data/", body={"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": [
        {"seriesID": "CUUR0000SA0", "data": [{"year": "2026", "period": "M07", "value": "320.1"}]}]}})
    t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [{"DOI": "10.1234/abc", "title": ["T"], "type": "journal-article"}], "total-results": 1}})
    # every lane that needs no secret answers with a record, so "no lane reports searched_empty"
    # in the outage window is a statement about the keyed lanes, not about quiet providers
    t.add("GET", "https://doaj.org/api/search/articles/", body={"results": [{"id": "d1", "bibjson": {
        "title": "T", "identifier": [{"type": "doi", "id": "10.1234/abc"}]}}], "total": 1})
    t.add("GET", "https://www.ebi.ac.uk/europepmc/webservices/rest/search?", body={
        "hitCount": 1, "nextCursorMark": "*", "resultList": {"result": [{"id": "1", "source": "MED", "doi": "10.1234/abc", "title": "T"}]}})
    return t


def backend(vault: FakeVault, *, token_file: str, clock=None, wall=None, **kw) -> secrets.Chain:
    """The vault backend the way from_config('vault') assembles it (env first), with the clocks
    injected: `clock` runs the cache TTLs, `wall` dates the capability fact."""
    return secrets.Chain(secrets.EnvBackend(), secrets.VaultBackend(
        addr=vault.url, token_file=token_file, timeout=kw.pop("timeout", 2.0), environ={},
        clock=clock or time.monotonic, wall=wall or time.time, **kw))


def http(url, method="GET", body=None, token=TOKENS["engine"]):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}",
               "X-Research-Invocation": "inv_secrets001", "X-Research-Attempt": "1"}   # research is attributed (A5)
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class VaultCase(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, CLEAN_ENV, clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.token_file = os.path.join(self.tmp.name, "gateway.token")
        Path(self.token_file).write_text("s.fixture-token-abc\n")
        os.chmod(self.token_file, 0o400)
        self.wall, self.mono = Clock(T0), Clock(1000.0)
        self.vault = FakeVault(secrets=SECRETS, clock=self.wall)
        self.addCleanup(self.vault.close)

    def serve(self, chain):
        gw = app.Gateway(app.Settings(tokens=TOKENS, workers=1, sync_timeout=10, secrets_backend="vault"),
                         use_db=False, transport=providers(), secrets=chain, alerter=alerts.Alerter(None))
        server = api.serve(gw, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()

        def stop():
            server.shutdown()
            server.server_close()
            gw.stop()
        self.addCleanup(stop)
        return gw, f"http://127.0.0.1:{server.server_port}"

    def data(self, url, source):
        status, body = http(f"{url}/v1/data", "POST", {"source": source, "params": KEYED_DATA[source]})
        self.assertEqual(status, 200, body)
        return body

    def start_child(self, env: dict, audit_log: str | None = None) -> subprocess.Popen:
        """The real entrypoint in a child with exactly `env` (plus PATH/PYTHONPATH); with
        audit_log, every file the child opens is appended there by an audit hook."""
        prologue = ("import os, sys\n"
                    "fd = os.open(sys.argv[1], os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)\n"
                    "def hook(event, args):\n"
                    "    if event == 'open' and args and isinstance(args[0], (str, bytes)):\n"
                    "        os.write(fd, (os.fsdecode(args[0]) + '\\n').encode())\n"
                    "sys.addaudithook(hook)\n") if audit_log else ""
        code = "import sys\n" + prologue + "from research_gateway.api.http import main\nsys.exit(main())\n"
        full = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": str(GATEWAY_DIR),
                "RESEARCH_GATEWAY_LISTEN": "127.0.0.1:0", **env}
        args = [sys.executable, "-c", code] + ([audit_log] if audit_log else [])
        return subprocess.Popen(args, cwd=self.tmp.name, env=full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def outcome(self, child: subprocess.Popen, wait: float = 20.0) -> tuple[int | None, str]:
        """(exit status, stderr) — or (None, stderr so far) for a child that started serving."""
        deadline = time.monotonic() + wait
        lines = []
        try:
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    return child.returncode, "".join(lines) + child.stderr.read()
                line = child.stderr.readline()
                lines.append(line)
                if "listening on" in line:
                    return None, "".join(lines)
            return None, "".join(lines)
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(10)
            child.stdout.close()
            child.stderr.close()


class F1NoHomeFallback(VaultCase):
    """1. Token-file variable unset, with a valid ~/.vault-token under HOME: the service
    refuses to start, names the variable, and never opens the home-directory file."""

    def test_refuses_to_start_and_never_opens_the_home_token(self):
        home = Path(self.tmp.name) / "home"
        home.mkdir()
        (home / ".vault-token").write_text("s.fixture-token-abc\n")
        log = os.path.join(self.tmp.name, "opens.log")
        env = {"HOME": str(home), "RESEARCH_GATEWAY_SECRETS": "vault", "RESEARCH_GATEWAY_VAULT_ADDR": self.vault.url}
        status, err = self.outcome(self.start_child(env, audit_log=log))
        self.assertEqual(status, 2, err)
        self.assertIn("refusing to start", err)
        self.assertIn("RESEARCH_GATEWAY_VAULT_TOKEN_FILE", err)
        opened = Path(log).read_text().splitlines()
        self.assertNotIn(str(home / ".vault-token"), opened, "the home-directory token was opened")
        self.assertEqual(self.vault.requests, [], "nothing was read from vault with a token nobody chose")

    def test_control_an_explicit_token_file_starts_the_service(self):
        home = Path(self.tmp.name) / "home"
        home.mkdir()
        (home / ".vault-token").write_text("s.fixture-token-abc\n")
        log = os.path.join(self.tmp.name, "opens.log")
        env = {"HOME": str(home), "RESEARCH_GATEWAY_SECRETS": "vault", "RESEARCH_GATEWAY_VAULT_ADDR": self.vault.url,
               "RESEARCH_GATEWAY_VAULT_TOKEN_FILE": self.token_file}
        status, err = self.outcome(self.start_child(env, audit_log=log))
        self.assertIsNone(status, f"the service did not start: {err}")
        opened = Path(log).read_text().splitlines()
        self.assertIn(self.token_file, opened)
        self.assertNotIn(str(home / ".vault-token"), opened)
        self.assertIn("/v1/secret/data/services/research_gateway", [p for p, _ in self.vault.requests],
                      "the client tokens came from vault")
        self.assertEqual({t for _, t in self.vault.requests}, {"s.fixture-token-abc"}, "with the named file's token")


class F2ExplicitFileUnreadable(VaultCase):
    """2. The token-file variable names a missing path, then an unreadable file — at startup,
    and after the file is removed while running: refused, or each read FAILING, never absent."""

    def env(self, path: str) -> dict:
        return {"HOME": self.tmp.name, "RESEARCH_GATEWAY_SECRETS": "vault", "RESEARCH_GATEWAY_VAULT_ADDR": self.vault.url,
                "RESEARCH_GATEWAY_VAULT_TOKEN_FILE": path}

    def test_a_missing_path_at_startup_is_refused(self):
        missing = os.path.join(self.tmp.name, "no-such-token")
        status, err = self.outcome(self.start_child(self.env(missing)))
        self.assertEqual(status, 2, err)
        self.assertIn(f"RESEARCH_GATEWAY_VAULT_TOKEN_FILE={missing}", err)
        self.assertIn("unreadable", err)

    def test_a_token_read_that_fails_at_startup_is_refused_as_failing(self):
        # the client tokens come from vault (none in the environment) and vault answers 403:
        # the refusal names the failure — never the "no client tokens" of an absent secret
        self.vault.mode = "status:403"
        status, err = self.outcome(self.start_child(self.env(self.token_file)))
        self.assertEqual(status, 2, err)
        self.assertIn("secrets backend failing (HTTP 403)", err)
        self.assertNotIn("without client tokens", err)

    @unittest.skipIf(os.geteuid() == 0, "root reads a 0000 file")
    def test_an_unreadable_file_at_startup_is_refused(self):
        locked = os.path.join(self.tmp.name, "locked-token")
        Path(locked).write_text("s.fixture-token-abc\n")
        os.chmod(locked, 0)
        status, err = self.outcome(self.start_child(self.env(locked)))
        self.assertEqual(status, 2, err)
        self.assertIn("unreadable", err)

    def test_a_file_removed_while_running_makes_each_read_failing(self):
        clock = Clock(100.0)
        chain = backend(self.vault, token_file=self.token_file, clock=clock)
        self.assertEqual(chain.read("fred", "api_key"), secrets.SecretRead(secrets.FOUND, "fred-key-123456"))
        os.chmod(self.token_file, 0o600)
        os.remove(self.token_file)
        clock.t += 901   # past the success TTL: the next read goes to vault, and needs the token
        for _ in range(2):   # the fresh failure, then its cached replay
            read = chain.read("fred", "api_key")
            self.assertEqual((read.state, read.reason), (secrets.FAILING, "token file unreadable (No such file or directory)"))
            with self.assertRaises(secrets.SecretsBackendFailing):
                chain.get("fred", "api_key")
        self.assertEqual(len(self.vault.requests), 1, "no request goes out without the token file")

    def test_through_the_service_the_lane_reports_the_failure(self):
        chain = backend(self.vault, token_file=self.token_file)
        gw, url = self.serve(chain)
        os.chmod(self.token_file, 0o600)
        os.remove(self.token_file)
        lane = self.data(url, "fred")["lanes"][0]
        self.assertEqual((lane["coverage"], lane["error_class"]), ("provider_unavailable", "secrets_backend_failing"))


class F3TransportAndStatus(VaultCase):
    """3. Unreachable, timing out, 403, 5xx, 404 for a mount that does not exist, 200 with an
    unparseable body: each read FAILING, distinct from absent, surfaced as a dated capability
    fact (since = first failure, last_success_at, affected lanes) that alerts on the transition."""

    CASES = (("403", "status:403", None, "HTTP 403", 403),
             ("500", "status:500", None, "HTTP 500", 500),
             ("503", "status:503", None, "HTTP 503", 503),
             ("unparseable 200", "unparseable", None, "unparseable payload", 200),
             ("shapeless 200", "shapeless", None, "payload without a data.data object", 200),
             ("timeout", "stall:1.5", None, "timeout", None),
             ("mount missing", "ok", "kv-typo", "mount or route not found (404)", 404))

    def test_each_failure_is_failing_and_never_absent(self):
        for label, mode, mount, reason, status in self.CASES:
            with self.subTest(label):
                self.vault.mode = mode
                chain = backend(self.vault, token_file=self.token_file, timeout=0.5, **({"mount": mount} if mount else {}))
                read = chain.read("fred", "api_key")
                self.assertEqual((read.state, read.reason, read.status), (secrets.FAILING, reason, status))
                self.assertNotEqual(read.state, secrets.ABSENT)
                self.vault.mode = "ok"

    def test_a_valid_body_under_another_success_status_is_failing(self):
        """A7: only 200 is a KV read; 201/202/204-style successes carry no secret, whatever the body."""
        for status in (201, 202, 203):
            with self.subTest(status):
                self.vault.ok_status = status
                read = backend(self.vault, token_file=self.token_file).read("fred", "api_key")
                self.assertEqual((read.state, read.reason, read.status), (secrets.FAILING, f"unexpected HTTP {status}", status))

    def test_control_the_same_body_under_200_is_the_secret(self):
        self.vault.ok_status = 200
        read = backend(self.vault, token_file=self.token_file).read("fred", "api_key")
        self.assertEqual(read.state, secrets.FOUND)

    def test_unreachable(self):
        self.vault.close()
        chain = backend(self.vault, token_file=self.token_file, timeout=0.5)
        read = chain.read("fred", "api_key")
        self.assertEqual(read.state, secrets.FAILING)
        self.assertTrue(read.reason.startswith("unreachable"), read.reason)

    def test_the_capability_fact_is_dated_names_its_lanes_and_alerts_on_transition(self):
        chain = backend(self.vault, token_file=self.token_file, clock=self.mono, wall=self.wall)
        gw, url = self.serve(chain)
        self.assertEqual(self.data(url, "fred")["lanes"][0]["coverage"], "searched_ok")   # a success first
        self.wall.t = OUTAGE
        self.mono.t += 901   # the success TTL has run out
        self.vault.mode = "status:403"
        for source in ("fred", "bea"):
            body = self.data(url, source)
            self.assertEqual(body["lanes"][0]["error_class"], "secrets_backend_failing")
        fact = gw.capabilities()["secrets"]
        self.assertEqual({k: fact[k] for k in ("capability", "state", "since", "last_success_at", "detail", "affected_lanes")},
                         {"capability": "secrets.vault", "state": "failing", "since": "2026-09-21T19:47:00Z",
                          "last_success_at": "2026-09-21T19:45:00Z", "detail": "403", "affected_lanes": ["bea", "fred"]})
        self.assertEqual(body["capability_facts"][0]["affected_lanes"], ["bea", "fred"])
        self.assertEqual([k for _, k, _ in gw.alerter.history], ["capability:secrets.vault:failing"], "one alert, on the transition")
        self.vault.mode = "ok"
        self.mono.t += 61
        self.assertEqual(self.data(url, "fred")["lanes"][0]["coverage"], "searched_ok")
        self.assertEqual(self.data(url, "bea")["lanes"][0]["coverage"], "searched_ok")
        self.assertEqual(gw.capabilities()["secrets"]["state"], "healthy")
        self.assertEqual([k for _, k, _ in gw.alerter.history][-1], "capability:secrets.vault:healthy", "the recovery alerts too")


class F4GenuinelyAbsent(VaultCase):
    """4. 404 for a path under a mount that exists, or 200 with an entry that lacks the field:
    ABSENT ("no secret configured"), no alarm, and distinct from every case in 3."""

    def test_absent_is_absent_and_does_not_alarm(self):
        chain = backend(self.vault, token_file=self.token_file, clock=self.mono)
        gw, url = self.serve(chain)
        self.assertEqual(chain.read("no_such_secret"), secrets.SecretRead(secrets.ABSENT))
        self.assertEqual(chain.read("fred", "no_such_field"), secrets.SecretRead(secrets.ABSENT))
        self.vault.secrets.pop("fred")
        self.mono.t += 901
        lane = self.data(url, "fred")["lanes"][0]
        self.assertEqual(lane["coverage"], "auth_failed", "a key that is genuinely not configured is an auth problem")
        self.assertNotEqual(lane.get("error_class"), "secrets_backend_failing")
        self.assertEqual(gw.capabilities()["secrets"]["state"], "healthy")
        self.assertNotIn("capability:secrets.vault:failing", [k for _, k, _ in gw.alerter.history])

    def test_control_the_same_path_under_a_missing_mount_is_failing(self):
        chain = backend(self.vault, token_file=self.token_file, mount="kv-typo")
        self.assertEqual(chain.read("no_such_secret").state, secrets.FAILING)


class F5OutcomeSurvivesTheHttpBoundary(VaultCase):
    """5. When a request's lanes needed a failing secret, the gateway's HTTP answer says so per
    lane (secrets_backend_failing), never searched_empty and never "no key configured"; lanes
    that need no secret answer normally beside it. (The engine side of this fixture — the
    observation's error_class and its unknown count — is gen2/tests/test_gateway_client.py,
    run over this service's recorded answers.)"""

    def test_per_lane_outcome_over_http(self):
        self.vault.mode = "status:403"
        gw, url = self.serve(backend(self.vault, token_file=self.token_file))
        body = self.data(url, "fred")
        lane = body["lanes"][0]
        self.assertEqual({k: lane.get(k) for k in ("source", "coverage", "error_class")},
                         {"source": "fred", "coverage": "provider_unavailable", "error_class": "secrets_backend_failing"})
        self.assertNotIn("count", lane, "a lane that could not run reports no count, not a zero")
        self.assertFalse(any("no FRED key" in f for f in body["facts"]), body["facts"])
        self.assertEqual(body["capability_facts"][0]["state"], "failing")
        status, found = http(f"{url}/v1/find", "POST", {"query": "q", "kind": "article"})
        self.assertEqual({ln["source"]: ln["coverage"] for ln in found["lanes"]}["crossref"], "searched_ok",
                         "a lane that needs no secret still answers")

    def test_control_a_readable_secret_answers(self):
        gw, url = self.serve(backend(self.vault, token_file=self.token_file))
        body = self.data(url, "fred")
        self.assertEqual((body["lanes"][0]["coverage"], body["lanes"][0]["count"]), ("searched_ok", 1))
        self.assertNotIn("capability_facts", body)


class F6CacheDoesNotLaunderAFailure(VaultCase):
    """6. A failure cached for its retry interval is replayed as FAILING, not absent; a cached
    success does not outlive a failed re-read; recovery moves the fact back with its
    last_success_at."""

    def test_failure_replay_expiry_and_recovery(self):
        clock = self.mono
        chain = backend(self.vault, token_file=self.token_file, clock=clock, wall=self.wall)
        vault_backend = chain.backends[1]
        self.assertEqual(chain.read("fred", "api_key").state, secrets.FOUND)
        self.vault.mode = "status:403"
        self.assertEqual(chain.read("fred", "api_key").state, secrets.FOUND, "inside its TTL the success is served from cache")
        clock.t += 901
        self.wall.t = OUTAGE
        self.assertEqual(chain.read("fred", "api_key").state, secrets.FAILING, "an expired success is re-read, and the re-read failed")
        asked = len(self.vault.requests)
        clock.t += 30
        replay = chain.read("fred", "api_key")
        self.assertEqual((replay.state, replay.status), (secrets.FAILING, 403), "the cached failure replays as failing")
        self.assertEqual(len(self.vault.requests), asked, "a replay does not ask vault again")
        self.assertEqual(vault_backend.health.fact()["state"], "failing")
        self.vault.mode = "ok"
        clock.t += 31   # past the failure TTL
        self.wall.t = OUTAGE + 600
        self.assertEqual(chain.read("fred", "api_key").state, secrets.FOUND)
        fact = vault_backend.health.fact()
        self.assertEqual((fact["state"], fact["since"], fact["last_success_at"], fact["affected_lanes"]),
                         ("healthy", None, "2026-09-21T19:57:00Z", []))


class F7RedirectsRefused(VaultCase):
    """7. Redirects are refused, so the token is never re-sent elsewhere — and a refused
    redirect is a FAILING read, not an absent one."""

    def test_no_redirect_is_followed(self):
        elsewhere = FakeVault(secrets=SECRETS)
        self.addCleanup(elsewhere.close)
        for code in (301, 302, 307, 308):
            with self.subTest(code):
                self.vault.mode = f"redirect:{code}:{elsewhere.url}"
                read = backend(self.vault, token_file=self.token_file).read("fred", "api_key")
                self.assertEqual((read.state, read.reason, read.status), (secrets.FAILING, f"redirect refused ({code})", code))
        self.assertEqual(elsewhere.requests, [], "the token went nowhere else")


class F8OutageReplay(VaultCase):
    """8. Every read answers 403 from a fixed time. From the first failed read on, operator
    status reads 'secrets backend failing since <that time> (403); N lanes degraded', and no
    lane in that window reports searched_empty or a count."""

    def test_the_outage_reads_as_an_outage(self):
        self.vault.fail_from = OUTAGE
        chain = backend(self.vault, token_file=self.token_file, clock=self.mono, wall=self.wall)
        gw, url = self.serve(chain)
        for source in KEYED_DATA:   # before the outage every keyed lane works
            self.assertEqual(self.data(url, source)["lanes"][0]["coverage"], "searched_ok", source)
        self.assertIsNone(gw.capabilities()["secrets"]["summary"])
        self.wall.t = OUTAGE
        self.mono.t += 901   # the success TTL has run out: the next reads go to vault
        answers = [self.data(url, source) for source in KEYED_DATA]
        answers.append(http(f"{url}/v1/find", "POST", {"query": "q", "kind": "article"})[1])
        degraded = sorted({ln["source"] for a in answers for ln in a["lanes"] if ln.get("error_class") == "secrets_backend_failing"})
        self.assertTrue({"bea", "bls", "census", "fred"} <= set(degraded), degraded)
        keyed = {s["id"] for s in gw.sources if s.get("secret_ref")}
        self.assertTrue(set(degraded) <= keyed, "only lanes that read a secret are degraded")
        status, body = http(f"{url}/v1/status")
        self.assertEqual(body["capabilities"]["secrets"]["summary"],
                         f"secrets backend failing since 2026-09-21T19:47:00Z (403); {len(degraded)} lanes degraded")
        self.assertEqual(body["capabilities"]["secrets"]["affected_lanes"], degraded)
        for answer in answers:
            for lane in answer["lanes"]:
                self.assertNotEqual(lane["coverage"], "searched_empty", lane)
                if lane.get("error_class") == "secrets_backend_failing":
                    self.assertNotIn("count", lane)


class FactRevisions(unittest.TestCase):
    """2b-repair-3 R2: each change of the capability fact is its next revision, so the engine
    can order an episode's snapshots however they reach it — a read that changes nothing is
    the same snapshot, and a return to earlier contents is a later one. An answer carries the
    latest snapshot it met, by revision, whatever order its lanes are collected in."""

    def health(self):
        wall = Clock(OUTAGE)
        lanes = {"fred": ["fred"], "govinfo": ["govinfo"]}
        return secrets.SecretsHealth("secrets.vault", wall=wall, lanes_for=lambda name: lanes[name]), wall

    def test_each_change_is_the_next_revision_and_a_repeat_is_not(self):
        h, wall = self.health()
        f403, f503 = secrets.SecretRead(secrets.FAILING, reason="HTTP 403", status=403), secrets.SecretRead(secrets.FAILING, reason="HTTP 503", status=503)
        seen = []
        for name, read in (("fred", f403), ("fred", f403), ("govinfo", f403), ("fred", f503), ("govinfo", f403)):
            wall.t += 60
            h.failure(name, read)
            seen.append(h.fact())
        self.assertEqual([(f["revision"], f["detail"], f["affected_lanes"]) for f in seen],
                         [(1, "403", ["fred"]), (1, "403", ["fred"]), (2, "403", ["fred", "govinfo"]), (3, "503", ["fred", "govinfo"]),
                          (4, "403", ["fred", "govinfo"])], "a repeat is the same snapshot; a return to earlier contents is the next")
        self.assertEqual({**seen[4], "revision": 2}, seen[2], "the fourth says what the second said")
        self.assertEqual({f["since"] for f in seen}, {"2026-09-21T19:48:00Z"}, "one episode")

    def test_an_answer_keeps_the_latest_snapshot_it_met(self):
        older, newer = {"capability": "secrets.vault", "revision": 2, "detail": "403"}, {"capability": "secrets.vault", "revision": 3, "detail": "503"}
        other = {"capability": "budget", "revision": 1}
        for order in ((older, newer), (newer, older)):
            out = {}
            for fact in (other, *order):
                router._add_fact(out, fact)
            self.assertEqual(out["capability_facts"], [other, newer], "the latest by revision, one per capability")


class UnknownBackendIsRefused(unittest.TestCase):
    def test_a_misspelt_backend_is_a_startup_error_not_env(self):
        with self.assertRaises(secrets.SecretsConfigError):
            secrets.from_config("vaul")


if __name__ == "__main__":
    unittest.main()
