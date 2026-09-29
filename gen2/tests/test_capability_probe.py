"""Capability probes (task 1f): the station supervisor's probe of a provider's
auth home (gen2/supervisor/probe.py), the router's record of it
(gen2/router/capabilities.py), and the operator's probe_capability command
over the engine's listener (gen2/app/engine.py).

Trace: DEPLOYMENT-CONTRACT.md §4 (testing requirement (d); fresh workspace and
allowlisted environment per invocation; auth homes 0700, service-owned);
BOUNDARIES.md Station supervisor (capability probes) and Router (holds typed,
owned, deadlined); INVARIANTS H-2, H-3, RG-3, G-13.

The runner here is a fake: a small Python program named `codex`, the only
thing on the probe's PATH (this host may have a real codex elsewhere; no
test runs it), whose answers each test writes by hand into its auth home
(behaviour.json) — the pinned runner's real answers are characterized by
the deployment demonstration (deploy/gen2/demo/auth_demo.py, (e)), not here.
Every expected outcome, fact and hold field is written by hand from the
rules the modules state; read-backs are raw SQL on the test's own
connection, or HTTP to the engine.

Declared expiry (task 1f-repair): the credentials are hand-built JSON whose
JWTs are unsigned and whose instants are chosen against the test's clock;
every expected instant is written by hand. The fake runner answers usable
whatever the file holds, so these tests show what the probe reads beside the
runner, not what the pinned runner accepts ((e) characterizes that).

Structural limits: the fake runner cannot show what the real runner does
with a real credential; process-group termination is shown for a child in
the runner's own session only.
"""
from __future__ import annotations

import base64
import json
import os
import signal
import stat
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

from gen2.core.instants import utc_instant_ns
from gen2.supervisor import probe
from gen2.supervisor.probe import CapabilityProbe, Runner, claude_declared, codex_declared, codex_status, epoch_instant, jwt_exp
from gen2.tests import operator_fixtures as of
from gen2.tests import router_fixtures as rf

CAP = "provider-auth:codex"
KEY_LINE = "Logged in using an API key - sk-SECRETPART***TAILPART\n"

FAKE_RUNNER = f"""#!{sys.executable}
import json, os, signal, subprocess, sys, time
home = os.environ.get("CODEX_HOME", "")
with open(os.path.join(home, "behaviour.json")) as f:
    b = json.load(f)
with open(os.path.join(home, "calls.log"), "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:] == ["--version"]:
    sys.stdout.write(b.get("version", "codex-cli 0.153.2\\n"))
    sys.exit(0)
environ = open("/proc/self/environ", "rb").read().decode().split("\\0")  # as exec'd: the interpreter's own locale coercion is not the probe's
seen = {{"env": dict(e.split("=", 1) for e in environ if e), "cwd": os.getcwd(), "home_entries": sorted(os.listdir(os.environ["HOME"])),
        "home_mode": oct(os.stat(os.environ["HOME"]).st_mode & 0o777), "pid": os.getpid()}}
with open(os.path.join(home, f"seen-{{os.getpid()}}.json"), "w") as f:
    json.dump(seen, f)
if b.get("child"):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(os.path.join(home, "child.pid"), "w") as f:
        f.write(str(child.pid))
if b.get("wait_for_peer"):
    peers = os.path.join(home, "peers")
    os.makedirs(peers, exist_ok=True)
    open(os.path.join(peers, str(os.getpid())), "w").close()
    deadline = time.monotonic() + 10
    while len(os.listdir(peers)) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    if len(os.listdir(peers)) < 2:
        sys.stderr.write("alone\\n")
        sys.exit(1)
if b.get("sleep"):
    time.sleep(b["sleep"])
if b.get("kill"):
    os.kill(os.getpid(), signal.SIGKILL)
sys.stdout.write(b.get("stdout", ""))
sys.stderr.write(b.get("stderr", ""))
sys.exit(b.get("code", 0))
"""


def observation(pid: str, outcome: str, observed: str, *, started: str | None = None, detail: str = "by hand", declared: dict | None = None) -> dict:
    return {"probe_id": "probe_" + pid.ljust(32, "0"), "capability": CAP, "outcome": outcome, "detail": detail, "declared_expiry": declared,
            "started_at": started or observed, "observed_at": observed, "runner": {"name": "codex", "version": "0.153.2"},
            "affected_lanes": ["station:station-1"], "requested_by": "alice"}


def jwt(claims: object) -> str:
    part = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")  # noqa: E731
    return f"{part({'alg': 'none', 'typ': 'JWT'})}.{part(claims)}.UNSIGNEDSIG"


def chatgpt(access: object, id_token: object, *, refresh: object = "rt-REFRESHPART", key: object = None) -> dict:
    """codex's auth.json in ChatGPT mode; access and id_token are an `exp` (a JWT is made) or a token string as given."""
    token = lambda exp: exp if isinstance(exp, str) else jwt({"exp": exp, "email": "t@example.invalid"})  # noqa: E731
    return {"OPENAI_API_KEY": key, "tokens": {"id_token": token(id_token), "access_token": token(access), "refresh_token": refresh,
                                              "account_id": "acct-x"}}


EXP_2001, EXP_2100 = 1000000000, 4102444800  # 2001-09-09T01:46:40Z and 2100-01-01T00:00:00Z, as RFC 7519 NumericDate


class ProbeRecordTest(rf.RouterTestCase):
    """The router's record of one observation (capabilities.py), each case by hand."""

    def facts(self) -> list[tuple]:
        return self.rows("SELECT fact_id, state, since, last_success_at, superseded_by_fact_id FROM capability_facts WHERE capability = ? ORDER BY rowid", CAP)

    def holds(self) -> list[dict]:
        cols = ("hold_id", "topic_id", "subject_ref", "hold_class", "cause", "recoverability", "required_authority", "owner", "deadline_at",
                "clears_when", "capability_fact_id", "created_at", "cleared_at")
        return [dict(zip(cols, r)) for r in self.rows(f"SELECT {', '.join(cols)} FROM holds WHERE subject_ref = ? ORDER BY rowid", "capability:" + CAP)]

    def record(self, obs: dict) -> dict:
        return self.router.record_capability_probe(obs)

    def test_the_first_observation_is_a_transition_even_when_usable(self):
        reply = self.record(observation("a1", "usable", "2026-09-27T10:00:05Z"))
        self.assertEqual(reply["status"], "recorded")
        self.assertEqual(reply["fact"]["state"], "healthy")
        self.assertTrue(reply["fact"]["transition"])
        self.assertEqual(self.facts(), [(reply["fact"]["fact_id"], "healthy", "2026-09-27T10:00:05Z", None, None)])
        self.assertIsNone(reply["hold"])
        self.assertEqual(self.holds(), [])

    def test_the_fact_moves_on_a_transition_only_and_names_its_last_success(self):
        first = self.record(observation("b1", "usable", "2026-09-27T10:00:05Z"))
        second = self.record(observation("b2", "usable", "2026-09-27T10:00:06Z"))
        self.assertEqual(second["fact"]["fact_id"], first["fact"]["fact_id"])
        self.assertFalse(second["fact"]["transition"])
        failing = self.record(observation("b3", "unusable_credential", "2026-09-27T10:00:07Z", detail="the runner finds no credential"))
        again = self.record(observation("b4", "unusable_credential", "2026-09-27T10:00:08Z"))
        self.assertEqual(again["fact"]["fact_id"], failing["fact"]["fact_id"])
        self.assertEqual(self.facts(), [
            (first["fact"]["fact_id"], "healthy", "2026-09-27T10:00:05Z", None, failing["fact"]["fact_id"]),
            (failing["fact"]["fact_id"], "failing", "2026-09-27T10:00:07Z", "2026-09-27T10:00:06Z", None)])  # the last usable observation, not the fact's since
        self.assertEqual(self.value("SELECT detail FROM capability_facts WHERE fact_id = ?", failing["fact"]["fact_id"]),
                         "unusable_credential: the runner finds no credential")

    def test_an_unusable_credential_opens_one_typed_owned_deadlined_hold_bound_to_its_fact(self):
        failing = self.record(observation("c1", "unusable_credential", "2026-09-27T10:00:05Z", detail="the runner cannot parse the credential"))
        again = self.record(observation("c2", "unusable_credential", "2026-09-27T10:00:06Z"))
        self.assertTrue(failing["hold"]["opened"])
        self.assertEqual(again["hold"], {"hold_id": failing["hold"]["hold_id"], "opened": False})
        [hold] = self.holds()
        created = hold["created_at"]
        self.assertEqual(hold, {
            "hold_id": failing["hold"]["hold_id"], "topic_id": None, "subject_ref": "capability:" + CAP, "hold_class": "capability",
            "cause": CAP + " unusable_credential: the runner cannot parse the credential", "recoverability": "needs_remediation",
            "required_authority": "operator", "owner": "operator",
            "deadline_at": hold["deadline_at"], "clears_when": hold["clears_when"], "capability_fact_id": failing["fact"]["fact_id"],
            "created_at": created, "cleared_at": None})
        self.assertEqual(utc_instant_ns(hold["deadline_at"]) - utc_instant_ns(created), 3600 * 10**9)  # the router's shipped hold window
        self.assertIn("hold_clearance", hold["clears_when"])

    def test_a_runner_error_is_an_unknown_fact_and_a_hold_whose_remedy_is_unknown(self):
        reply = self.record(observation("d1", "runner_error", "2026-09-27T10:00:05Z", detail="login status ran past the probe timeout"))
        self.assertEqual(reply["fact"]["state"], "unknown")
        self.assertEqual([(h["hold_class"], h["recoverability"], h["capability_fact_id"]) for h in self.holds()],
                         [("capability", "unknown", reply["fact"]["fact_id"])])

    def test_a_declared_expiry_is_a_degraded_fact_and_a_hold_to_remedy(self):
        usable = self.record(observation("d21", "usable", "2026-09-27T10:00:05Z"))
        declared = {"access_token": "2001-09-09T01:46:40Z", "id_token": None, "refresh_credential": True}
        reply = self.record(observation("d22", "declared_expired", "2026-09-27T10:00:06Z", detail="its access token declares it expired",
                                        declared=declared))
        self.assertEqual((reply["outcome"], reply["declared_expiry"], reply["fact"]["state"], reply["fact"]["transition"]),
                         ("declared_expired", declared, "degraded", True))
        self.assertEqual(self.facts()[-1], (reply["fact"]["fact_id"], "degraded", "2026-09-27T10:00:06Z", "2026-09-27T10:00:05Z", None))
        self.assertEqual(self.value("SELECT detail FROM capability_facts WHERE fact_id = ?", reply["fact"]["fact_id"]),
                         "declared_expired: its access token declares it expired")
        self.assertEqual([(h["hold_class"], h["recoverability"], h["owner"], h["required_authority"], h["capability_fact_id"], h["cause"])
                          for h in self.holds()],
                         [("capability", "needs_remediation", "operator", "operator", reply["fact"]["fact_id"],
                           CAP + " declared_expired: its access token declares it expired")])
        self.assertIsNone(usable["hold"])

    def test_a_declared_expired_observation_names_its_access_expiry_at_or_before_it_was_observed(self):
        before = self.state(exclude=())
        at = "2026-09-27T10:00:06Z"
        for declared in (None, {"access_token": None, "id_token": "2001-09-09T01:46:40Z", "refresh_credential": False},
                         {"access_token": "2026-09-27T10:00:07Z", "id_token": None, "refresh_credential": False}):
            with self.subTest(declared=declared):
                self.assertEqual(self.record(observation("d31", "declared_expired", at, declared=declared)),
                                 {"status": "refused", "reason": "request_invalid",
                                  "detail": "declared_expired names the access token's declared expiry, at or before the observation"})
        self.assertEqual(self.state(exclude=()), before)
        exact = self.record(observation("d32", "declared_expired", at, declared={"access_token": at, "id_token": None, "refresh_credential": False}))
        self.assertEqual((exact["status"], exact["fact"]["state"]), ("recorded", "degraded"))  # at the instant itself: RFC 7519, on or after

    def test_a_usable_probe_clears_no_hold_an_operator_clearance_does_and_a_later_failure_opens_a_new_one(self):
        failing = self.record(observation("e1", "unusable_credential", "2026-09-27T10:00:05Z"))
        usable = self.record(observation("e2", "usable", "2026-09-27T10:00:06Z"))
        self.assertEqual(usable["fact"]["state"], "healthy")
        self.assertIsNone(usable["hold"])
        self.assertIsNone(self.holds()[0]["cleared_at"])  # a probe clears nothing
        self.assertEqual(self.decide("opd_clearprobe01", "hold_clearance", {"kind": "hold", "ref": failing["hold"]["hold_id"]}, tid=None)["status"], "applied")
        self.assertIsNotNone(self.holds()[0]["cleared_at"])
        later = self.record(observation("e3", "unusable_credential", "2026-09-27T10:00:07Z"))
        holds = self.holds()
        self.assertEqual([(h["hold_id"], h["cleared_at"] is None) for h in holds], [(failing["hold"]["hold_id"], False), (holds[-1]["hold_id"], True)])
        self.assertEqual(later["hold"], {"hold_id": holds[1]["hold_id"], "opened": True})

    def test_a_hold_cleared_while_the_capability_still_fails_is_opened_again_by_the_next_failure(self):
        failing = self.record(observation("f1", "unusable_credential", "2026-09-27T10:00:05Z"))
        self.assertEqual(self.decide("opd_clearprobe02", "hold_clearance", {"kind": "hold", "ref": failing["hold"]["hold_id"]}, tid=None)["status"], "applied")
        again = self.record(observation("f2", "unusable_credential", "2026-09-27T10:00:06Z"))
        self.assertFalse(again["fact"]["transition"])  # still failing: no new fact ...
        holds = self.holds()
        self.assertEqual([h["cleared_at"] is None for h in holds], [False, True])  # ... and a hold again
        self.assertEqual(again["hold"], {"hold_id": holds[1]["hold_id"], "opened": True})

    def test_an_older_observation_is_kept_and_moves_nothing(self):
        newer = self.record(observation("7a1", "usable", "2026-09-27T10:00:09Z"))
        older = self.record(observation("7a2", "unusable_credential", "2026-09-27T10:00:08Z"))
        self.assertEqual(older["status"], "recorded")
        self.assertFalse(older["applied"])
        self.assertEqual(older["fact"]["fact_id"], newer["fact"]["fact_id"])
        self.assertIsNone(older["hold"])
        self.assertEqual([f[1] for f in self.facts()], ["healthy"])
        self.assertEqual(self.holds(), [])
        self.assertEqual(self.value("SELECT count(*) FROM audit_events WHERE kind = 'capability_probe'"), 2)

    def test_the_same_observation_replays_its_answer_and_another_under_its_id_is_a_conflict(self):
        obs = observation("8a1", "unusable_credential", "2026-09-27T10:00:05Z")
        first = self.record(obs)
        self.assertEqual(self.record(obs), {**first, "status": "replayed"})
        self.assertEqual(self.record({**obs, "outcome": "usable"}),
                         {"status": "refused", "reason": "probe_conflict", "detail": f"{obs['probe_id']} was recorded with another observation"})
        self.assertEqual(len(self.facts()), 1)
        self.assertEqual(len(self.holds()), 1)
        recorded = json.loads(self.value("SELECT detail FROM audit_events WHERE audit_event_id = ?", "aud_" + obs["probe_id"]))
        self.assertEqual(recorded, {"observation": obs, "reply": first})

    def test_a_lost_reply_is_answered_again_from_the_record(self):
        obs = observation("8b1", "unusable_credential", "2026-09-27T10:00:05Z")
        first = self.record(obs)
        before = self.state(exclude=())
        self.assertEqual(self.record(obs), {**first, "status": "replayed"})
        self.assertEqual(self.state(exclude=()), before)  # the replay writes nothing

    def test_a_malformed_observation_is_refused_and_writes_nothing(self):
        before = self.state(exclude=())
        good = observation("9a1", "usable", "2026-09-27T10:00:05Z")
        for bad in ({**good, "capability": "config-bundle"}, {**good, "outcome": "fine"}, {**good, "probe_id": "probe_short"},
                    {**good, "started_at": "2026-09-27T10:00:06Z"}, {**good, "extra": 1}, {k: v for k, v in good.items() if k != "requested_by"},
                    {k: v for k, v in good.items() if k != "declared_expiry"}, {**good, "declared_expiry": {"access_token": None, "id_token": None}},
                    {**good, "declared_expiry": {"access_token": "2001-09-31T00:00:00Z", "id_token": None, "refresh_credential": False}},
                    {**good, "declared_expiry": {"access_token": None, "id_token": None, "refresh_credential": 1}}):
            with self.subTest(bad=bad):
                self.assertEqual(self.record(bad).get("reason"), "request_invalid")
        self.assertEqual(self.state(exclude=()), before)

    def test_status_lists_the_open_holds_of_no_topic_and_the_current_fact(self):
        failing = self.record(observation("aa1", "unusable_credential", "2026-09-27T10:00:05Z"))
        self.x("INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, deadline_at, clears_when, created_at) "
               "VALUES ('hold_topicheld01', ?, 'topic:x', 'scope', 'c', 'needs_decision', 'operator', 'operator', '2026-09-28T00:00:00Z', 'w', '2026-09-27T09:00:00Z')", rf.TOPIC)
        facts = self.router.status({})
        self.assertEqual([h["hold_id"] for h in facts["holds"]], [failing["hold"]["hold_id"]])  # not the topic's hold
        self.assertEqual(facts["holds"][0]["capability_fact_id"], failing["fact"]["fact_id"])
        self.assertFalse(facts["holds"][0]["deadline_passed"])
        self.assertEqual([(f["capability"], f["state"]) for f in facts["capability_facts"] if f["capability"] == CAP], [(CAP, "failing")])


class FakeRunnerCase(unittest.TestCase):
    """A probe over a temporary auth root, its runner the fake above."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "codex").write_text(FAKE_RUNNER)
        (self.bin / "codex").chmod(0o755)
        self.auth = self.root / "auth"
        self.auth.mkdir()
        self.home = self.auth / "codex"
        self.home.mkdir(mode=0o700)
        self.behave(stderr=KEY_LINE)
        self.recorded: list[dict] = []
        self.clock = rf.Clock()
        self.timeout = 20.0

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def behave(self, **b) -> None:
        (self.home / "behaviour.json").write_text(json.dumps(b))

    def probe(self, **options) -> CapabilityProbe:
        return CapabilityProbe(options.pop("auth_root", self.auth), record=lambda obs: self.recorded.append(obs) or {"status": "recorded", "observation": obs},
                               clock=self.clock, timeout_s=lambda: self.timeout, station_id="station-1", path=str(self.bin), **options)

    def run_probe(self, **options) -> dict:
        reply = self.probe(**options).run({"provider": "codex", "requested_by": "alice"})
        self.assertEqual(reply["status"], "recorded", reply)
        return reply["observation"]

    def calls(self) -> list[str]:
        path = self.home / "calls.log"
        return path.read_text().splitlines() if path.exists() else []

    def seen(self) -> list[dict]:
        return [json.loads(p.read_text()) for p in sorted(self.home.glob("seen-*.json"))]


class ProbeRunTest(FakeRunnerCase):
    def test_each_answer_of_the_runner_is_classified_by_its_rules(self):
        cases = [  # (behaviour, outcome, detail) — codex 0.153.2's login status, by hand
            ({"stderr": KEY_LINE}, "usable", "the runner reads a credential (an API key)"),
            ({"stderr": "Logged in using ChatGPT\n"}, "usable", "the runner reads a credential (ChatGPT tokens)"),
            ({"stderr": "Not logged in\n", "code": 1}, "unusable_credential", "the runner finds no credential"),
            ({"stderr": "Error checking login status: key must be a string at line 1 column 2\n", "code": 1}, "unusable_credential",
             "the runner cannot parse the credential"),
            ({"stderr": "Error checking login status: Permission denied (os error 13)\n", "code": 1}, "unusable_credential",
             "the runner cannot read the credential (permission denied)"),
            ({"stderr": "Not logged in\n", "code": 0}, "runner_error", "login status exited 0 with output its rules do not know"),
            ({"stderr": KEY_LINE, "code": 1}, "runner_error", "login status exited 1 with output its rules do not know"),
            ({"stderr": "WARNING: something\n" + KEY_LINE}, "runner_error", "login status exited 0 with output its rules do not know"),
            ({"stderr": KEY_LINE, "stdout": "x"}, "runner_error", "login status exited 0 with output its rules do not know"),
            ({"stderr": "", "code": 0}, "runner_error", "login status exited 0 with output its rules do not know"),
            ({"stderr": "Not logged in\n", "code": 2}, "runner_error", "login status exited 2 with output its rules do not know"),
        ]
        for behaviour, outcome, detail in cases:
            with self.subTest(behaviour=behaviour):
                self.behave(**behaviour)
                obs = self.run_probe()
                self.assertEqual((obs["outcome"], obs["detail"]), (outcome, detail))

    def test_the_observation_is_the_router_request_and_carries_nothing_the_runner_printed(self):
        obs = self.run_probe()
        self.assertEqual(set(obs), {"probe_id", "capability", "outcome", "detail", "declared_expiry", "started_at", "observed_at", "runner",
                                    "affected_lanes", "requested_by"})
        self.assertEqual((obs["capability"], obs["runner"], obs["affected_lanes"], obs["requested_by"]),
                         (CAP, {"name": "codex", "version": "0.153.2"}, ["station:station-1"], "alice"))
        self.assertLess(utc_instant_ns(obs["started_at"]), utc_instant_ns(obs["observed_at"]))
        text = json.dumps(obs)
        self.assertNotIn("SECRETPART", text)
        self.assertNotIn("TAILPART", text)

    def test_another_runner_version_is_a_runner_error_and_its_status_is_never_run(self):
        self.behave(stderr=KEY_LINE, version="codex-cli 0.154.0\n")
        obs = self.run_probe()
        self.assertEqual((obs["outcome"], obs["detail"]), ("runner_error", "the runner is not codex 0.153.2: its behaviour is not known here"))
        self.assertEqual(self.calls(), ["--version"])

    def test_a_runner_that_cannot_start_is_a_runner_error(self):
        (self.bin / "codex").unlink()
        obs = self.run_probe()
        self.assertEqual((obs["outcome"], obs["detail"]), ("runner_error", "codex --version could not start (FileNotFoundError)"))

    def test_a_runner_past_the_timeout_is_ended_with_its_session_and_is_a_runner_error(self):
        self.timeout = 0.5
        self.behave(stderr=KEY_LINE, sleep=30, child=True)
        started = time.monotonic()
        obs = self.run_probe()
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual((obs["outcome"], obs["detail"]), ("runner_error", "codex login ran past the probe timeout"))
        child = int((self.home / "child.pid").read_text())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        with self.assertRaises(ProcessLookupError):  # the runner's own child, in its session, ended with it
            os.kill(child, 0)

    def test_a_runner_killed_by_a_signal_is_a_runner_error(self):
        self.behave(kill=True)
        obs = self.run_probe()
        self.assertEqual((obs["outcome"], obs["detail"]), ("runner_error", "codex login was killed by signal 9"))

    def test_the_runner_gets_exactly_the_allowlisted_environment_and_a_fresh_workspace(self):
        os.environ["GEN2_OPERATOR_TOKENS"] = "alice=must-not-reach-the-runner"
        try:
            self.run_probe()
            self.run_probe()
        finally:
            del os.environ["GEN2_OPERATOR_TOKENS"]
        first, second = self.seen()
        for seen in (first, second):
            self.assertEqual(set(seen["env"]), {"PATH", "HOME", "CODEX_HOME"})
            self.assertEqual(seen["env"]["CODEX_HOME"], str(self.home))
            self.assertEqual(seen["env"]["PATH"], str(self.bin))
            self.assertEqual(seen["cwd"], seen["env"]["HOME"])
            self.assertEqual((seen["home_entries"], seen["home_mode"]), ([], "0o700"))
            self.assertFalse(Path(seen["env"]["HOME"]).exists())  # removed after
        self.assertNotEqual(first["env"]["HOME"], second["env"]["HOME"])

    def test_an_auth_home_not_as_the_contract_fixes_it_is_unusable_and_the_runner_never_runs(self):
        uid = os.geteuid()
        target = self.root / "target"
        target.mkdir(mode=0o700)
        cases = {  # name -> (how the case's auth home is made, the detail by hand)
            "missing": (lambda home: None, "the auth home is not mounted"),
            "open mode": (lambda home: (home.mkdir(), home.chmod(0o755)),
                          f"the auth home is not a 0700 directory of this service user (a directory, mode 0755, uid {uid})"),
            "a link": (lambda home: home.symlink_to(target), f"the auth home is not a 0700 directory of this service user (not a directory, mode 0777, uid {uid})"),
            "a file": (lambda home: (home.write_text("{}"), home.chmod(0o700)),
                       f"the auth home is not a 0700 directory of this service user (not a directory, mode 0700, uid {uid})"),
        }
        for name, (make, detail) in cases.items():
            with self.subTest(case=name):
                root = self.root / name.replace(" ", "-")
                root.mkdir()
                make(root / "codex")
                obs = self.run_probe(auth_root=root)
                self.assertEqual((obs["outcome"], obs["detail"]), ("unusable_credential", detail))
        with self.subTest(case="another user's"), unittest.mock.patch.object(probe.os, "geteuid", return_value=uid + 1):
            obs = self.run_probe()
            self.assertEqual((obs["outcome"], obs["detail"]),
                             ("unusable_credential", f"the auth home is not a 0700 directory of this service user (a directory, mode 0700, uid {uid})"))
        self.assertEqual(list(self.root.rglob("calls.log")) + list(self.root.rglob("seen-*.json")), [])  # no runner ran

    def test_a_request_the_probe_refuses_runs_and_records_nothing(self):
        for request, reason in (({"provider": "codex"}, "request_invalid"), ({"provider": "codex", "requested_by": 1}, "request_invalid"),
                                ({"provider": "codex", "requested_by": "a", "x": 1}, "request_invalid"),
                                ({"provider": "claude", "requested_by": "a"}, "unknown_provider")):
            with self.subTest(request=request):
                self.assertEqual(self.probe().run(request)["reason"], reason)
        self.assertEqual(self.probe(auth_root=None).run({"provider": "codex", "requested_by": "a"})["reason"], "no_auth_homes")
        self.assertEqual((self.recorded, self.calls()), ([], []))

    def test_a_record_given_to_the_run_is_used_instead_of_the_probe_own(self):
        given = []
        reply = self.probe().run({"provider": "codex", "requested_by": "a"}, record=lambda obs: given.append(obs) or {"status": "given"})
        self.assertEqual((reply, len(given), self.recorded), ({"status": "given"}, 1, []))

    def test_the_codex_rules_alone(self):
        self.assertEqual(codex_status(0, "", "Logged in using an API key - ***"), ("usable", "the runner reads a credential (an API key)"))
        self.assertEqual(codex_status(0, "", "Logged in using an API key"), ("runner_error", "login status exited 0 with output its rules do not know"))
        self.assertEqual(codex_status(1, "", "Error checking login status: x Permission denied (os error 13) y\n"),
                         ("unusable_credential", "the runner cannot parse the credential"))  # the permission text is the line's end, nowhere else


class DeclaredExpiryTest(FakeRunnerCase):
    """What the credential declares of its own expiry, read beside the
    runner's verdict (probe.py, task 1f-repair). The fake runner answers
    "Logged in using ChatGPT" unless a test says otherwise."""

    def setUp(self) -> None:
        super().setUp()
        self.behave(stderr="Logged in using ChatGPT\n")

    def credential(self, value: object, name: str = "auth.json") -> None:
        (self.home / name).write_text(json.dumps(value))

    def test_an_access_token_declared_expired_is_declared_expired_labeled_as_its_own_claim(self):
        for refresh, present in (("rt-REFRESHPART", "present"), ("", "absent")):
            with self.subTest(refresh=refresh):
                self.credential(chatgpt(EXP_2001, EXP_2001, refresh=refresh))
                obs = self.run_probe()
                self.assertEqual((obs["outcome"], obs["detail"], obs["declared_expiry"]), (
                    "declared_expired", "the runner reads the credential, but its access token declares it expired at 2001-09-09T01:46:40Z: "
                                        f"the credential's own claim, not the provider's answer; a refresh credential is {present}",
                    {"access_token": "2001-09-09T01:46:40Z", "id_token": "2001-09-09T01:46:40Z", "refresh_credential": refresh != ""}))
                text = json.dumps(obs)
                for part in ("UNSIGNEDSIG", "REFRESHPART", "example.invalid", jwt({"exp": EXP_2001, "email": "t@example.invalid"}).split(".")[1]):
                    self.assertNotIn(part, text)  # the instants leave; no byte of a token does

    def test_only_the_access_token_decides_and_the_id_token_is_recorded(self):
        cases = [  # (access, id_token) -> (outcome, declared access, declared id)
            ((EXP_2100, EXP_2001), ("usable", "2100-01-01T00:00:00Z", "2001-09-09T01:46:40Z")),
            (("opaque-access", EXP_2001), ("usable", None, "2001-09-09T01:46:40Z")),
            ((EXP_2001, "opaque-id"), ("declared_expired", "2001-09-09T01:46:40Z", None)),
            ((EXP_2100, EXP_2100), ("usable", "2100-01-01T00:00:00Z", "2100-01-01T00:00:00Z")),
        ]
        for (access, id_token), (outcome, declared_access, declared_id) in cases:
            with self.subTest(access=access, id_token=id_token):
                self.credential(chatgpt(access, id_token))
                obs = self.run_probe()
                self.assertEqual((obs["outcome"], obs["declared_expiry"]),
                                 (outcome, {"access_token": declared_access, "id_token": declared_id, "refresh_credential": True}))
                if outcome == "usable":
                    self.assertEqual(obs["detail"], "the runner reads a credential (ChatGPT tokens)")

    def test_a_credential_that_declares_no_expiry_rests_on_the_runner_verdict(self):
        nothing = {"access_token": None, "id_token": None, "refresh_credential": False}
        cases = [  # (auth.json, the runner's line): codex uses an API key string over its tokens, an empty one too ((e), AUTH-DEMO.md)
            ({"OPENAI_API_KEY": "sk-KEYPART"}, KEY_LINE), (chatgpt(EXP_2001, EXP_2001, key="sk-KEYPART"), KEY_LINE),
            (chatgpt(EXP_2001, EXP_2001, key=""), KEY_LINE), ({}, "Logged in using ChatGPT\n")]
        for value, line in cases:
            with self.subTest(value=value):
                self.behave(stderr=line)
                self.credential(value)
                obs = self.run_probe()
                self.assertEqual((obs["outcome"], obs["declared_expiry"]), ("usable", nothing))

    def test_the_access_expiry_decides_at_or_before_the_observation(self):
        epoch = utc_instant_ns("2026-09-27T10:00:00Z") // 10**9
        cases = [(epoch, "declared_expired", "2026-09-27T10:00:00Z"), (epoch + 1, "usable", "2026-09-27T10:00:01Z"),
                 (epoch + 0.5, "usable", "2026-09-27T10:00:01Z"), (epoch - 0.5, "declared_expired", "2026-09-27T10:00:00Z")]
        for exp, outcome, declared in cases:  # observed at 10:00:00.000Z exactly: the clock's second reading from 09:59:59.998Z
            with self.subTest(exp=exp):
                self.clock.set("2026-09-27T09:59:59.998Z")
                self.credential(chatgpt(exp, EXP_2100))
                obs = self.run_probe()
                self.assertEqual((obs["observed_at"], obs["outcome"], obs["declared_expiry"]["access_token"]),
                                 ("2026-09-27T10:00:00.000Z", outcome, declared))

    def test_a_credential_file_not_to_read_declares_nothing(self):
        target = self.root / "elsewhere.json"
        target.write_text(json.dumps(chatgpt(EXP_2001, EXP_2001)))
        cases = {  # each in an auth home of its own; the fake runner answers usable whatever is there
            "a link": lambda path: path.symlink_to(target),
            "past the size bound": lambda path: path.write_text(json.dumps(chatgpt(EXP_2001, EXP_2001)) + " " * probe.MAX_CREDENTIAL),
            "not JSON": lambda path: path.write_text("{not json"),
            "absent": lambda path: None,
            "unreadable": lambda path: (path.write_text(json.dumps(chatgpt(EXP_2001, EXP_2001))), path.chmod(0o000)),
        }
        for name, make in cases.items():
            with self.subTest(case=name):
                root = self.root / name.replace(" ", "-")
                (root / "codex").mkdir(parents=True, mode=0o700)
                (root / "codex" / "behaviour.json").write_text(json.dumps({"stderr": "Logged in using ChatGPT\n"}))
                make(root / "codex" / "auth.json")
                obs = self.run_probe(auth_root=root)
                self.assertEqual((obs["outcome"], obs["declared_expiry"]), ("usable", None))

    def test_nothing_is_read_when_the_runner_does_not_read_the_credential_as_usable(self):
        self.credential(chatgpt(EXP_2001, EXP_2001))
        for behaviour, outcome in (({"stderr": "Not logged in\n", "code": 1}, "unusable_credential"),
                                   ({"stderr": "Error checking login status: missing field `refresh_token`\n", "code": 1}, "unusable_credential"),
                                   ({"stderr": "Logged in using ChatGPT\n", "code": 2}, "runner_error")):
            with self.subTest(behaviour=behaviour):
                self.behave(**behaviour)
                obs = self.run_probe()
                self.assertEqual((obs["outcome"], obs["declared_expiry"]), (outcome, None))  # a runner's rejection stands: never made merely degraded

    def test_a_claude_format_is_read_for_its_expires_at(self):
        claude = Runner("codex", "0.153.2", ("codex", "--version"), "codex-cli 0.153.2\n", ("codex", "login", "status"), "CODEX_HOME", codex_status,
                        ".credentials.json", claude_declared)  # the fake runner, answering as codex; the file read the way a claude runner's is
        self.credential({"claudeAiOauth": {"accessToken": "sk-ant-oat-ACCESSPART", "refreshToken": "sk-ant-ort-REFRESHPART",
                                           "expiresAt": EXP_2001 * 1000}}, ".credentials.json")
        obs = self.run_probe(runners={"codex": claude})
        self.assertEqual((obs["outcome"], obs["declared_expiry"]),
                         ("declared_expired", {"access_token": "2001-09-09T01:46:40Z", "id_token": None, "refresh_credential": True}))
        self.assertNotIn("PART", json.dumps(obs))

    def test_a_claude_credential_stating_no_expiry_declares_none(self):
        claude = Runner("codex", "0.153.2", ("codex", "--version"), "codex-cli 0.153.2\n", ("codex", "login", "status"), "CODEX_HOME", codex_status,
                        ".credentials.json", claude_declared)
        self.credential({"claudeAiOauth": {"accessToken": "sk-ant-oat-ACCESSPART", "refreshToken": "sk-ant-ort-REFRESHPART"}}, ".credentials.json")
        obs = self.run_probe(runners={"codex": claude})
        self.assertEqual((obs["outcome"], obs["declared_expiry"]), ("usable", {"access_token": None, "id_token": None, "refresh_credential": True}))

    def test_the_readers_alone(self):
        self.assertEqual(jwt_exp(jwt({"exp": EXP_2001})), "2001-09-09T01:46:40Z")
        for token in (jwt({"exp": True}), jwt({"exp": "1000000000"}), jwt({"exp": -1}), jwt({"exp": 253402300800}), jwt({"exp": 10**30}),
                      jwt({"iat": EXP_2001}), jwt([EXP_2001]), jwt({"exp": EXP_2001}) + ".a.b", "a.%%%.c", "a." + "W" * 10 + ".c", "a.b", None, 7):
            with self.subTest(token=token):
                self.assertIsNone(jwt_exp(token))
        self.assertEqual(jwt_exp("x." + base64.urlsafe_b64encode(b'{"exp": NaN}').decode() + ".y"), None)  # Python's json reads NaN
        self.assertEqual((epoch_instant(EXP_2001 + 0.25), epoch_instant(253402300799), epoch_instant(0)),
                         ("2001-09-09T01:46:41Z", "9999-12-31T23:59:59Z", "1970-01-01T00:00:00Z"))
        self.assertEqual(codex_declared([]), {"access_token": None, "id_token": None, "refresh_credential": False})
        self.assertEqual(codex_declared({"tokens": {"access_token": jwt({"exp": EXP_2001}), "refresh_token": "r"}}),
                         {"access_token": "2001-09-09T01:46:40Z", "id_token": None, "refresh_credential": True})
        for ms, instant in ((EXP_2001 * 1000, "2001-09-09T01:46:40Z"), (EXP_2001 * 1000 + 1, "2001-09-09T01:46:41Z"), (True, None),
                            ("1000000000000", None), (10**400, None), (float("inf"), None)):
            with self.subTest(expires_at=ms):
                self.assertEqual(claude_declared({"claudeAiOauth": {"expiresAt": ms, "refreshToken": ""}}),
                                 {"access_token": instant, "id_token": None, "refresh_credential": False})


class StationProbeTest(FakeRunnerCase):
    """The composition root's probe (gen2/app/station.py): its timeout is the
    mounted bundle's supervisor policy (G-10), and it records through the router."""

    def test_the_probe_timeout_is_the_bundle_policy_and_the_record_is_the_router_own(self):
        from gen2.app.station import open_station
        bundle = {"bundle_version": "config-bundle/1", "version": 1, "questions": [], "policy": {"supervisor": {"probe_timeout_s": 0.5}}}
        station = open_station(self.root / "state", station_id="station-1", host_id="host-1", clock=rf.Clock(), config_bundle=bundle, create=True,
                               auth_root=self.auth, probe_options={"path": str(self.bin)})
        try:
            self.behave(stderr=KEY_LINE, sleep=5)  # a runner that answers usable, after the bundle's timeout
            started = time.monotonic()
            reply = station.probe.run({"provider": "codex", "requested_by": "alice"})
            self.assertLess(time.monotonic() - started, 4.5)
            self.assertEqual((reply["status"], reply["outcome"], reply["fact"]["state"]), ("recorded", "runner_error", "unknown"))
            self.assertEqual(station.router.status({})["capability_facts"][-1]["detail"], "runner_error: codex login ran past the probe timeout")
        finally:
            station.close()


class EngineProbeTest(of.OperatorTestCase):
    """probe_capability over the engine's listener: the operator's command, the
    station's probe, the router's record, and status."""

    def setUp(self) -> None:
        self._probe_tmp = tempfile.TemporaryDirectory()
        base = Path(self._probe_tmp.name)
        self.bin, self.auth = base / "bin", base / "auth"
        self.bin.mkdir()
        (self.bin / "codex").write_text(FAKE_RUNNER)
        (self.bin / "codex").chmod(0o755)
        self.home = self.auth / "codex"
        self.home.mkdir(parents=True, mode=0o700)
        (self.home / "behaviour.json").write_text(json.dumps({"stderr": KEY_LINE}))
        super().setUp()

    def tearDown(self) -> None:
        super().tearDown()
        self._probe_tmp.cleanup()

    def start_engine(self, creds=None, **station):
        return super().start_engine(creds, auth_root=self.auth, probe_options={"path": str(self.bin)}, **station)

    def test_the_operator_probe_is_recorded_and_status_shows_the_fact_and_the_hold(self):
        (self.home / "behaviour.json").write_text(json.dumps({"stderr": "Not logged in\n", "code": 1}))
        code, reply, _ = self.http("POST", "/v1/commands/probe_capability", {"provider": "codex"})
        self.assertEqual((code, reply["status"]), (200, "recorded"), reply)
        self.assertEqual((reply["outcome"], reply["fact"]["state"], reply["hold"]["opened"]), ("unusable_credential", "failing", True))
        requested = json.loads(self.value("SELECT detail FROM audit_events WHERE audit_event_id = ?", "aud_" + reply["probe_id"]))["observation"]["requested_by"]
        self.assertEqual(requested, "alice")  # the principal's name, from the token
        code, status, _ = self.http("GET", "/v1/status")
        self.assertEqual(code, 200)
        self.assertEqual([(w["reason"], w["hold_id"], w["hold_class"], w["owner"], w["capability_fact_id"]) for w in status["waiting"]],
                         [("hold", reply["hold"]["hold_id"], "capability", "operator", reply["fact"]["fact_id"])])
        [fact] = [f for f in status["capability_facts"] if f["capability"] == CAP]
        self.assertEqual((fact["fact_id"], fact["state"], fact["since"]), (reply["fact"]["fact_id"], "failing", reply["observed_at"]))

    def test_a_declared_expired_credential_is_a_degraded_fact_and_a_hold_in_status(self):
        (self.home / "behaviour.json").write_text(json.dumps({"stderr": "Logged in using ChatGPT\n"}))
        (self.home / "auth.json").write_text(json.dumps(chatgpt(EXP_2001, EXP_2001)))
        code, reply, _ = self.http("POST", "/v1/commands/probe_capability", {"provider": "codex"})
        self.assertEqual((code, reply["status"], reply["outcome"], reply["fact"]["state"], reply["hold"] and reply["hold"]["opened"]),
                         (200, "recorded", "declared_expired", "degraded", True), reply)
        self.assertEqual(reply["declared_expiry"], {"access_token": "2001-09-09T01:46:40Z", "id_token": "2001-09-09T01:46:40Z", "refresh_credential": True})
        code, status, _ = self.http("GET", "/v1/status")
        [fact] = [f for f in status["capability_facts"] if f["capability"] == CAP]
        self.assertEqual((fact["fact_id"], fact["state"]), (reply["fact"]["fact_id"], "degraded"))
        self.assertTrue(fact["detail"].startswith("declared_expired: the runner reads the credential, but its access token declares it expired at "
                                                  "2001-09-09T01:46:40Z: the credential's own claim, not the provider's answer"), fact["detail"])
        self.assertEqual([(w["hold_id"], w["hold_class"], w["recoverability"], w["capability_fact_id"]) for w in status["waiting"]],
                         [(reply["hold"]["hold_id"], "capability", "needs_remediation", reply["fact"]["fact_id"])])

    def test_who_asks_is_the_principal_and_only_an_operator_may(self):
        code, reply, _ = self.http("POST", "/v1/commands/probe_capability", {"provider": "codex", "requested_by": "mallory"})
        self.assertEqual((code, reply.get("reason")), (400, "authority_in_request"))
        code, reply, _ = self.http("POST", "/v1/commands/probe_capability", {"provider": "codex"}, token=of.EXPORTER_TOKEN)
        self.assertEqual((code, reply.get("reason")), (403, "forbidden"))
        self.assertEqual(self.value("SELECT count(*) FROM audit_events WHERE kind = 'capability_probe'"), 0)

    def test_two_probes_run_their_runners_at_once(self):
        (self.home / "behaviour.json").write_text(json.dumps({"stderr": KEY_LINE, "wait_for_peer": True}))  # each run waits for the other's
        replies, barrier = [None, None], threading.Barrier(2)

        def one(slot: int) -> None:
            barrier.wait()
            replies[slot] = self.http("POST", "/v1/commands/probe_capability", {"provider": "codex"})[1]
        threads = [threading.Thread(target=one, args=(slot,)) for slot in (0, 1)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual([r["outcome"] for r in replies], ["usable", "usable"])  # serialized, the first would have waited alone: a runner_error
        windows = [(utc_instant_ns(r["started_at"]), utc_instant_ns(r["observed_at"])) for r in replies]
        self.assertLess(max(w[0] for w in windows), min(w[1] for w in windows))
        self.assertEqual(self.value("SELECT count(*) FROM audit_events WHERE kind = 'capability_probe'"), 2)

    def test_the_probe_is_a_tool_over_mcp(self):
        code, reply, _ = self.http("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                    "params": {"name": "probe_capability", "arguments": {"provider": "codex"}}})
        self.assertEqual((code, reply["result"]["isError"]), (200, False), reply)
        self.assertEqual(json.loads(reply["result"]["content"][0]["text"]).get("outcome"), "usable")


if __name__ == "__main__":
    unittest.main()
