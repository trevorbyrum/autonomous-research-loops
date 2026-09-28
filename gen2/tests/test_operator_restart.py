"""Restart and replacement keep principals, permissions, pins and the waiting
answers (task 1e; INVARIANTS RG-9, DEPLOYMENT-CONTRACT.md §2 "what restart
means": the same volumes and the same mounted secrets), and the CLI is a
client of the same routes.

RestartTest restarts the engine in this process over the same state
directory. ReplacementTest runs the engine as its own process
(`python -m gen2.app.engine`, through children.py so it imports the code
tree under test), with the deployment contract's environment names, and
drives it with the CLI as its own process: the engine is stopped (SIGTERM,
which ends it where it stands) and a new process takes its place. CliTest
runs the CLI's main() against the in-process engine, for its exit codes.
Read-backs are raw SQL.
"""
from __future__ import annotations

import io
import json
import os
import select
import socket
import subprocess
import threading
import unittest

from gen2.app import cli
from gen2.tests import children
from gen2.tests import operator_fixtures as of
from gen2.tests import router_fixtures as rf
from gen2.tests.router_fixtures import OTHER, TOPIC


def without_time(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k != "at"}


class RestartTest(of.CommandWorld):
    def test_a_restart_keeps_principals_permissions_pins_and_the_waiting_answers(self) -> None:
        bodies = self.bodies()
        for name in ("apply_operator_decision", "request_cancel", "requeue", "activate_config_bundle"):
            self.assertEqual(self.command(name, bodies[name])[0], 200)
        before = without_time(self.status_doc())
        self.restart()
        self.assertEqual(without_time(self.status_doc()), before)
        self.assertEqual(self.value("SELECT version FROM config_bundles WHERE status = 'active'"), 2)
        self.assertEqual(self.value("SELECT config_bundle_hash FROM invocations WHERE invocation_id = ?", of.RUNNING), rf.CONFIG)
        self.assertEqual(self.command("close_brief", bodies["close_brief"], token=of.EXPORTER_TOKEN)[0], 403)
        self.assertEqual(self.command("close_brief", bodies["close_brief"], token=of.OTHER_OPERATOR_TOKEN)[1]["status"], "closed")
        self.assertEqual(self.command("ack_delivery", bodies["ack_delivery"], token=of.EXPORTER_TOKEN)[1]["status"], "recorded")
        self.assertEqual(self.rows("SELECT closed_by FROM intake_briefs WHERE topic_id = ? AND status = 'archived'", TOPIC), [("bob",)])


class ReplacementTest(of.OperatorTestCase):
    ENV = {"GEN2_SECRETS": "env", "GEN2_OPERATOR_LISTEN": "127.0.0.1:0", "GEN2_OPERATOR_TOKENS": f"alice={of.OPERATOR_TOKEN},bob={of.OTHER_OPERATOR_TOKEN}",
           "GEN2_SECRET_EXPORTER_TOKEN": of.EXPORTER_TOKEN}

    def setUp(self) -> None:
        super().setUp()
        self.engine.close()  # this test's engines are processes of their own
        self.engine = None
        self.brief()
        self.outputs: list[str] = []

    def spawn(self, **env) -> tuple[subprocess.Popen, str | None]:
        """Start the engine process; (the process, its URL), or (the ended
        process, None) if it printed no address."""
        log = open(self.root / f"engine-{len(self.outputs)}.log", "w+")
        self.addCleanup(log.close)
        environ = {k: v for k, v in {**os.environ, **self.ENV, **env}.items() if v is not None}
        process = children.popen(["-m", "gen2.app.engine", "--root", str(self.root), "--station-id", "station-1", "--host-id", "host-1"],
                                 env=environ, stdout=subprocess.PIPE, stderr=log, text=True)
        self.addCleanup(self.stop, process, log)
        ready, _, _ = select.select([process.stdout], [], [], 30)
        line = process.stdout.readline() if ready else ""
        return process, (f"http://{line.split()[-1]}" if line.startswith("listening on ") else None)

    def stop(self, process: subprocess.Popen, log) -> None:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=30)
        log.seek(0)
        self.outputs.append(log.read() + (process.stdout.read() or ""))
        process.stdout.close()

    def cli(self, url: str, token: str | None, *args: str, body: dict | None = None) -> tuple[int, object]:
        environ = {**os.environ, "GEN2_OPERATOR_URL": url, "GEN2_OPERATOR_TOKEN": token or ""}
        done = children.python(["-m", "gen2.app.cli", *args], env=environ, input=None if body is None else json.dumps(body),
                               capture_output=True, text=True, timeout=60)
        self.outputs.append(done.stdout + done.stderr)
        return done.returncode, json.loads(done.stdout) if done.stdout.strip() else None

    def test_a_replacement_process_serves_the_same_principals_permissions_and_state(self) -> None:
        confirm = self.decision("opd_brief0001", "brief_confirmation", {"kind": "intake_brief", "ref": "brief-1", "revision": 1,
                                                                        "hash": self.value("SELECT content_hash FROM intake_briefs WHERE topic_id = ?", TOPIC)})
        first, url = self.spawn()
        self.assertIsNotNone(url, "the engine printed no address")
        self.assertEqual(self.cli(url, None, "health"), (0, {"status": "ok"}))
        self.assertEqual(self.cli(url, of.EXPORTER_TOKEN, "call", "apply_operator_decision", body=confirm)[0], 2)  # 403
        self.assertEqual(self.cli(url, None, "status")[0], 2)  # 401
        self.assertEqual(self.cli(url, of.OPERATOR_TOKEN, "call", "apply_operator_decision", body={**confirm, "subject": {**confirm["subject"], "hash": rf.h("0")}})[0], 1)
        code, reply = self.cli(url, of.OPERATOR_TOKEN, "call", "apply_operator_decision", body=confirm)
        self.assertEqual((code, reply["status"]), (0, "applied"))
        code, answered = self.cli(url, of.OPERATOR_TOKEN, "status", "--topic", TOPIC)
        self.assertEqual((code, answered["topics"][0]["status"]), (0, "scoping"))
        first.terminate()
        first.wait(timeout=30)

        second, url = self.spawn()
        self.assertIsNotNone(url)
        code, again = self.cli(url, of.OPERATOR_TOKEN, "status", "--topic", TOPIC)
        self.assertEqual((code, without_time(again)), (0, without_time(answered)))
        self.assertEqual(self.cli(url, of.EXPORTER_TOKEN, "status")[0], 2)
        other = self.decision("opd_brief0002", "brief_confirmation", {"kind": "intake_brief", "ref": "brief-1", "revision": 1, "hash": rf.h("0")}, OTHER)
        self.assertEqual(self.cli(url, of.OTHER_OPERATOR_TOKEN, "call", "apply_operator_decision", body=other)[0], 1)  # bob, heard and refused by the router
        self.assertEqual(self.rows("SELECT decision_id, operator_id FROM operator_decisions ORDER BY decision_id"), [("opd_brief0001", "alice")])
        second.terminate()
        second.wait(timeout=30)

        rotated = "op-token-alice-rotated-0123456789"
        third, url = self.spawn(GEN2_OPERATOR_TOKENS=f"alice={rotated},bob={of.OTHER_OPERATOR_TOKEN}")
        self.assertEqual(self.cli(url, of.OPERATOR_TOKEN, "status")[0], 2)
        self.assertEqual(self.cli(url, rotated, "status")[0], 0)
        third.terminate()
        third.wait(timeout=30)
        self.assert_no_token_in_any_output(rotated)

    def test_an_engine_without_usable_secrets_does_not_start(self) -> None:
        for label, env in (("no operator token", {"GEN2_OPERATOR_TOKENS": ""}), ("vault", {"GEN2_SECRETS": "vault"}),
                           ("a shared token", {"GEN2_SECRET_EXPORTER_TOKEN": of.OPERATOR_TOKEN})):
            with self.subTest(label=label):
                process, url = self.spawn(**env)
                self.assertIsNone(url)
                self.assertEqual(process.wait(timeout=30), 1)
        self.assert_no_token_in_any_output()
        self.assertTrue(all("refused to start" in out for out in self.outputs[-3:]), self.outputs[-3:])

    def assert_no_token_in_any_output(self, *extra: str) -> None:
        for process_output in self.outputs:
            for token in (*of.TOKENS, *extra):
                self.assertNotIn(token, process_output)


class CliTest(of.CommandWorld):
    def run_cli(self, *args: str, token: str | None = of.OPERATOR_TOKEN, body: dict | None = None) -> tuple[int, object, str]:
        host, port = self.engine.address
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(args), environ={"GEN2_OPERATOR_URL": f"http://{host}:{port}", **({} if token is None else {"GEN2_OPERATOR_TOKEN": token})},
                        stdin=io.StringIO("" if body is None else json.dumps(body)), stdout=out, stderr=err)
        return code, json.loads(out.getvalue()) if out.getvalue().strip() else None, err.getvalue()

    def test_the_cli_sends_the_body_and_prints_the_reply(self) -> None:
        body = self.bodies()["request_cancel"]
        code, reply, _ = self.run_cli("call", "request_cancel", body=body)
        self.assertEqual((code, reply), (0, {"status": "recorded", "invocation_id": of.RUNNING, "state": "running"}))
        path = self.root / "body.json"
        path.write_text(json.dumps(self.bodies()["requeue"]))
        self.assertEqual(self.run_cli("call", "requeue", str(path))[:2], (0, {"status": "requeued", "invocation_id": of.FAILED, "attempt": 2}))
        code, reply, _ = self.run_cli("status", "--topic", OTHER)
        self.assertEqual((code, [t["topic_id"] for t in reply["topics"]]), (0, [OTHER]))

    def test_health_is_asked_without_a_token(self) -> None:
        self.assertEqual(self.run_cli("health", token=None)[:2], (0, {"status": "ok"}))

    def test_the_exit_code_says_who_refused(self) -> None:
        code, reply, _ = self.run_cli("call", "request_cancel", body={"invocation_id": of.FAILED, "reason": "stop"})
        self.assertEqual((code, reply.get("reason")), (1, "not_cancellable"))
        code, reply, err = self.run_cli("call", "request_cancel", token=of.EXPORTER_TOKEN, body=self.bodies()["request_cancel"])
        self.assertEqual((code, reply.get("reason")), (2, "forbidden"))
        self.assertIn("HTTP 403", err)
        self.assertEqual(self.run_cli("status", token=None)[0], 2)
        self.assertEqual(self.run_cli("health", token=None)[:2], (0, {"status": "ok"}))
        host, port = self.engine.address
        self.engine.close()  # nothing listens at its address any more
        self.engine = None
        out, err_stream = io.StringIO(), io.StringIO()
        code = cli.main(["status"], environ={"GEN2_OPERATOR_URL": f"http://{host}:{port}", "GEN2_OPERATOR_TOKEN": of.OPERATOR_TOKEN},
                        stdin=io.StringIO(""), stdout=out, stderr=err_stream)
        self.assertEqual((code, out.getvalue()), (2, ""))
        self.assertIn("no answer from the engine", err_stream.getvalue())
        self.assertNotIn(of.OPERATOR_TOKEN, err_stream.getvalue())


class Answering:
    """A loopback server that answers every request with `answer`, exactly
    those bytes, then closes the connection: a reply cut short, one that is
    not HTTP, one that is not JSON. `requests` counts what it was sent."""

    def __init__(self, answer: bytes) -> None:
        self.answer, self.requests, self._stop = answer, 0, threading.Event()
        self._listener = socket.create_server(("127.0.0.1", 0))
        self._listener.settimeout(0.05)  # accept() wakes to see the stop
        self.url = "http://127.0.0.1:%d" % self._listener.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except TimeoutError:
                continue
            with conn:
                conn.settimeout(5)
                received = b""
                while b"\r\n\r\n" not in received:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    received += chunk
                head, _, body = received.partition(b"\r\n\r\n")
                declared = next((int(line.split(b":")[1]) for line in head.split(b"\r\n") if line.lower().startswith(b"content-length:")), 0)
                while len(body) < declared:
                    body += conn.recv(65536)
                self.requests += 1
                conn.sendall(self.answer)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self._listener.close()


def http_answer(status: str, body: bytes, declared: int | None = None) -> bytes:
    return f"HTTP/1.0 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(body) if declared is None else declared}\r\n\r\n".encode() + body


class CliTransportTest(unittest.TestCase):
    """What the CLI makes of a reply that is not a usable answer (Astra 1e
    review finding 6): a real socket answering with exactly the bytes given.
    Every one is exit 2 — no answer to give — with a one-line diagnostic and
    nothing on stdout; exit 1 stays the router's refusal and 0 its answer."""

    def run_cli(self, server: Answering, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(list(args), environ={"GEN2_OPERATOR_URL": server.url, "GEN2_OPERATOR_TOKEN": of.OPERATOR_TOKEN},
                        stdin=io.StringIO('{"invocation_id": "inv_running0001", "reason": "stop"}'), stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def serve(self, answer: bytes) -> Answering:
        server = Answering(answer)
        self.addCleanup(server.close)
        return server

    def test_a_reply_cut_short_or_malformed_is_no_answer(self) -> None:
        cases = {"a body cut short": http_answer("200 OK", b'{"status": ', declared=80),
                 "a closed connection": b"", "a status line that is not HTTP": b"garbage\r\n\r\n",
                 "a status line too long": b"HTTP/1.0 200 " + b"x" * 70000 + b"\r\n\r\n",
                 "a body that is not JSON": http_answer("200 OK", b"<html>ok</html>"),
                 "a list": http_answer("200 OK", b"[]"), "null": http_answer("200 OK", b"null"), "an empty body": http_answer("200 OK", b""),
                 "an object without a status": http_answer("200 OK", b'{"applied": true}'), "a status not a string": http_answer("200 OK", b'{"status": 1}')}
        for label, answer in cases.items():
            for args in (("status",), ("call", "request_cancel")):
                with self.subTest(label=label, command=args[0]):
                    server = self.serve(answer)
                    code, out, err = self.run_cli(server, *args)
                    self.assertEqual((code, out), (2, ""), err)
                    self.assertEqual((server.requests, err.count("\n")), (1, 1), err)  # sent once, never retried; one line
                    self.assertTrue(err.startswith(f"no answer from the engine at {server.url}: "), err)
                    self.assertNotIn("Traceback", err)
                    self.assertNotIn(of.OPERATOR_TOKEN, err)

    def test_the_controls_answered_and_refused(self) -> None:
        for label, answer, code in (("answered", http_answer("200 OK", b'{"status": "recorded"}'), 0), ("refused by the router", http_answer("200 OK", b'{"status": "refused", "reason": "not_cancellable"}'), 1),
                                    ("refused by the transport", http_answer("403 Forbidden", b'{"status": "refused", "reason": "forbidden"}'), 2)):
            with self.subTest(label=label):
                got, out, _ = self.run_cli(self.serve(answer), "call", "request_cancel")
                self.assertEqual((got, json.loads(out)["status"]), (code, "recorded" if code == 0 else "refused"))

    def test_the_cli_process_itself_exits_2_on_a_reply_cut_short(self) -> None:
        """The review's reproduction: `python -m gen2.app.cli status`, as its own
        process, against a 200 declaring 80 bytes and closing after 10."""
        server = self.serve(http_answer("200 OK", b'{"status":', declared=80))
        done = children.python(["-m", "gen2.app.cli", "status"], env={**os.environ, "GEN2_OPERATOR_URL": server.url, "GEN2_OPERATOR_TOKEN": of.OPERATOR_TOKEN},
                               capture_output=True, text=True, timeout=60)
        self.assertEqual((done.returncode, done.stdout), (2, ""), done.stderr)
        self.assertEqual(done.stderr, f"no answer from the engine at {server.url}: IncompleteRead\n")


if __name__ == "__main__":
    unittest.main()
