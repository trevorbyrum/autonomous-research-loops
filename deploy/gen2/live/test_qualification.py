"""T8-1/2/3: offline recipe and orchestration witnesses, never host qualification.
Fake Docker replies expose missing evidence and denied routes without sockets.
"""
import contextlib
import io
import json
import runpy
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from deploy.gen2.live import fixture, q_net, qualify

OBSERVER_ROLES = set(q_net.ROLES) | {"fixture", "service", "db"}


class Driver:
    def __init__(self, *, missing=(), unstarted=None, denied=False):
        roles = list(qualify.ROLES) + ["fixture", "service", "db", "runner", "relay", "control"]
        self.ids = {role: f"{i:064x}" for i, role in enumerate(roles, 1)}
        self.values = dict.fromkeys(roles, 0)
        self.probes, self.raw, self.record = [], b"", b""
        self.unstarted, self.denied = unstarted, denied
        self.views = {cid: dict(Id=cid, Image="sha256:" + "f" * 64, State=dict(Running=True, StartedAt="original", Pid=i),
                               NetworkSettings=dict(Networks={}), HostConfig={}) for i, cid in enumerate(self.ids.values(), 1)}
        bindings = {cid: dict(image=v["Image"], start=v["State"]["StartedAt"], pid=v["State"]["Pid"], networks={},
                              policy=dict.fromkeys(("Dns", "Sysctls", "NetworkMode", "CapDrop", "SecurityOpt", "ReadonlyRootfs", "Privileged", "PortBindings")))
                    for cid, v in self.views.items()}
        self.plan = dict(nonce="a" * 32, started=0, runner=self.ids["runner"], relay=self.ids["relay"], job="e" * 64,
                         bindings=bindings, services={r: self.ids[r] for r in ("fixture", "service", "db")},
                         controls={r: self.ids["control"] for r in OBSERVER_ROLES},
                         observers={r: dict(cid=self.ids[r], origin=dict(role=r)) for r in qualify.ROLES if r not in missing})

    def logs(self, role):
        if role == self.unstarted:
            return b""
        rows = [dict(event="ready", nonce=self.plan["nonce"], origin=dict(role=role))]
        rows += [dict(event="delivery", nonce=self.plan["nonce"], origin=dict(role=role), count=i, forwarded=0)
                 for i in range(1, self.values[role] + 1)]
        return "\n".join(map(json.dumps, rows)).encode()

    def check_output(self, argv, **_kwargs):
        operation, args = argv[3], argv[4:]
        if operation == "inspect":
            return json.dumps([self.views[args[0]]]).encode()
        if operation == "network":
            members = {self.ids[r]: dict(IPv4Address=ip + "/29") for r, ip in (("runner", "172.31.254.3"), ("relay", "172.31.254.2"))}
            return json.dumps([dict(Id=self.plan["job"], Internal=True, EnableIPv6=False, Containers=members,
                                    Options={"com.docker.network.bridge.gateway_mode_ipv4": "isolated"})]).encode()
        if operation == "logs":
            role = next(r for r in qualify.ROLES if self.ids[r] == args[0])
            return self.logs(role)
        if operation != "exec":
            raise AssertionError(argv)
        if args[1] == "/bin/cat":
            role = next(r for r, cid in self.ids.items() if cid == args[0])
            if args[2] == "/evidence/raw.jsonl":
                return self.raw
            if args[2] == "/evidence/fixture.json":
                return self.record
            if role == "relay":
                return b"0\n0\n"
            address, port = q_net.TARGETS[role]
            local = bytes(map(int, address.split(".")))[::-1].hex().upper()
            return (f"0: {local}:{port:04X} 00000000:0000 0A\n"
                    f"Tcp: RtoAlgorithm PassiveOpens\nTcp: 1 {self.values[role]}\n").encode()
        actor, command = args[2], args[5:]
        if command == ["inspect"]:
            return b"{}"
        mode, address, nonce, port, protocol = command
        self.probes.append((actor, address, int(port), protocol))
        target = (address, int(port))
        if target == q_net.TARGETS["relay"]:
            request = dict(model="gpt-5.4", stream=True, input=nonce,
                           tools=[dict(name=name) for name in ("exec_command", "write_stdin", "apply_patch")])
            rid = "c" * 32
            self.raw = json.dumps(dict(ordinal=1, id=rid, method="POST", route="/v1/responses", model="gpt-5.4",
                                       status=200, case="accepted", request=request)).encode()
            self.record = json.dumps({"v": 1, "requests": [dict(id=rid, route="/v1/responses", model="gpt-5.4", credential="accepted")]}).encode()
            self.values["fixture"] += 1
            # Legacy GET deliberately receives 403; the old driver accepted it.
            return json.dumps(dict(connected=True, nonce=nonce, answer=b"HTTP/1.1 403 Forbidden\r\n\r\n".hex(),
                                   status=403 if self.denied else 200, media="text/event-stream",
                                   body=fixture.response("accepted", 1, request)[2].hex())).encode()
        connected = actor != self.ids["runner"]
        if connected:
            role = "outside" if target == q_net.TARGETS["alternate_dns"] else next(r for r in OBSERVER_ROLES if q_net.TARGETS[r] == target)
            self.values[role] += 1
        return json.dumps(dict(connected=connected, answer=(b"\x7f\x00\x00\x2a" if connected else b"").hex())).encode()

    def run(self):
        output = io.StringIO()
        with patch.object(sys, "argv", [qualify.__file__, "/home/trevor/.config/gen2-2e1/q-test.json"]), \
                patch("gen2.supervisor.spool.read_scratch", return_value=dict(status="present", data=json.dumps(self.plan).encode())), \
                patch("pathlib.Path.read_bytes", return_value=b"mock CLI bytes"), \
                patch("hashlib.sha256") as digest, patch("time.monotonic", return_value=1), \
                patch("subprocess.check_output", side_effect=self.check_output), contextlib.redirect_stdout(output):
            digest.return_value.hexdigest.return_value = qualify.CLI_SHA
            runpy.run_path(qualify.__file__, run_name="__main__")
        return json.loads(output.getvalue())


class Qualification(unittest.TestCase):
    def test_runner_recipe_contains_invoked_probe(self):
        recipe = Path(qualify.__file__).with_name("Dockerfile").read_text()
        stage = recipe.split("FROM base AS runner\n", 1)[1].split("\nFROM ", 1)[0]
        self.assertIn("deploy/gen2/live/q_net.py /opt/live/q_net.py", stage)
        self.assertIn('"/opt/live/q_net.py"', Path(qualify.__file__).read_text())

    def test_paired_driver_requires_observers_before_probes(self):
        for missing, unstarted in ((tuple(qualify.ROLES), None), (("resolver",), None), ((), "outside")):
            with self.subTest(missing=missing, unstarted=unstarted):
                driver = Driver(missing=missing, unstarted=unstarted)
                with self.assertRaisesRegex(ValueError, "required_observers|observer_ready"):
                    driver.run()
                self.assertEqual(driver.probes, [])
        driver = Driver()
        result = driver.run()
        self.assertIsNone(result["qualification"])
        self.assertEqual(len(result["probes"]), 17)
        self.assertEqual(set(result["probes"][0]["before"]), OBSERVER_ROLES)

    def test_denied_relay_fails_driver(self):
        with self.assertRaisesRegex(ValueError, "relay_ingress"):
            Driver(denied=True).run()

    def test_service_and_counter_refusals(self):
        before = dict.fromkeys(qualify.OBSERVERS, 0)
        qualify.delivery_delta(before, before | {"resolver": 1}, ["resolver"])
        for after in ({}, before | {"outside": 1}):
            with self.subTest(after=after), self.assertRaises(ValueError):
                qualify.delivery_delta(before, after, [])
        with self.assertRaisesRegex(ValueError, "service_observer_ready"):
            qualify.service_count(b"Tcp: PassiveOpens\nTcp: 0\n", "db")
        plan = Driver().plan
        plan["services"].pop("db")
        with self.assertRaisesRegex(ValueError, "required_service_observers"):
            qualify.observer_set(plan)
        rows = [dict(event="ready", nonce="a", origin={}), dict(event="delivery", nonce="a", origin={}, count=1, forwarded=1)]
        with self.assertRaisesRegex(ValueError, "observer_delivery"):
            qualify.counts("\n".join(map(json.dumps, rows)), "a", {})

    def test_fixed_post_and_independent_fixture_record(self):
        nonce = "a" * 32
        connection = MagicMock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.getheader.return_value = "text/event-stream"
        connection.getresponse.return_value.read.return_value = fixture.response("accepted", 1, q_net.model_request(nonce))[2]
        output = io.StringIO()
        with patch.object(q_net.http.client, "HTTPConnection", return_value=connection), contextlib.redirect_stdout(output):
            q_net.relay(nonce)
        method, route, body, headers = connection.request.call_args.args
        self.assertEqual((method, route, json.loads(body)), ("POST", "/v1/responses", q_net.model_request(nonce)))
        self.assertEqual(headers["Authorization"], "Bearer 2e1-fixture-accepted")
        answer = json.loads(output.getvalue())
        qualify.relay_response(answer)
        output = io.StringIO()
        socket = MagicMock()
        socket.__enter__.return_value.recv.return_value = b"HTTP/1.1 403 Forbidden\r\n\r\n"
        with patch.object(q_net.socket, "socket", return_value=socket), contextlib.redirect_stdout(output):
            q_net.probe(*q_net.TARGETS["relay"], nonce, "tcp")
        self.assertTrue(socket.__enter__.return_value.sendall.call_args.args[0].startswith(b"GET /"))
        with self.assertRaisesRegex(ValueError, "relay_ingress"):
            qualify.relay_response(json.loads(output.getvalue()))
        for change in (dict(status=403), dict(body=b"denied".hex())):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "relay_ingress"):
                qualify.relay_response(answer | change)
        driver = Driver()
        driver.run()
        allowed = dict(nonce=json.loads(driver.raw)["request"]["input"])
        qualify.relay_record(allowed, driver.raw, driver.record)
        for independent in (b'{"v":1,"requests":[]}', driver.record.replace(b'accepted', b'rejected')):
            with self.subTest(independent=independent), self.assertRaisesRegex(ValueError, "relay_fixture_record"):
                qualify.relay_record(allowed, driver.raw, independent)
