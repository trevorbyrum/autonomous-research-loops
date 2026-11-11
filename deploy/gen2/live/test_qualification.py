"""Pure Q receipt predicates and protocol refusals; native qualification is separate."""
import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from deploy.gen2.live import fixture, q_net, qualify

class Qualification(unittest.TestCase):
    def test_runner_recipe_contains_invoked_probe(self):
        recipe = Path(qualify.__file__).with_name("Dockerfile").read_text()
        stage = recipe.split("FROM base AS runner\n", 1)[1].split("\nFROM ", 1)[0]
        self.assertIn("deploy/gen2/live/q_net.py /opt/live/q_net.py", stage)
        self.assertIn('"/opt/live"', Path(qualify.__file__).with_name("tool_probe.py").read_text())

    def test_service_and_counter_refusals(self):
        before = dict.fromkeys(qualify.OBSERVERS, 0)
        qualify.delivery_delta(before, before | {"resolver": 1}, ["resolver"])
        for after in ({}, before | {"outside": 1}):
            with self.subTest(after=after), self.assertRaises(ValueError):
                qualify.delivery_delta(before, after, [])
        with self.assertRaisesRegex(ValueError, "service_observer_ready"):
            qualify.service_count(b"Tcp: PassiveOpens\nTcp: 0\n", "db")
        plan = dict(observers=dict.fromkeys(qualify.ROLES), services=dict.fromkeys(qualify.SERVICES), controls=dict.fromkeys(qualify.OBSERVERS))
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
        request = q_net.model_request(nonce)
        raw = json.dumps(dict(ordinal=1, method="POST", route="/v1/responses", status=200, case="accepted", id="c" * 32, request=request)).encode()
        independent = json.dumps({"v": 1, "requests": [dict(id="c" * 32, route="/v1/responses", model="gpt-5.4", credential="accepted")]}).encode()
        qualify.relay_record(dict(nonce=nonce), raw, independent)
        for changed in (b'{"v":1,"requests":[]}', independent.replace(b"accepted", b"rejected")):
            with self.subTest(independent=changed), self.assertRaisesRegex(ValueError, "relay_fixture_record"):
                qualify.relay_record(dict(nonce=nonce), raw, changed)

    def test_bracket_rejects_missing_observation_and_runner_access(self):
        """Own receipt operands exercise the predicate; native identities require the Q run."""
        counts = dict.fromkeys(qualify.OBSERVERS, 0)
        plan = dict(nonce="a" * 32, job="job", runner="runner", relay="relay", observers=dict.fromkeys(qualify.ROLES),
                    services=dict.fromkeys(qualify.SERVICES), controls=dict.fromkeys(qualify.OBSERVERS))
        network = dict(Id="job", Internal=True, EnableIPv6=False, Options={"com.docker.network.bridge.gateway_mode_ipv4": "isolated"},
                       Containers={role: dict(IPv4Address=ip) for role, ip in (("runner", "172.31.254.3/29"), ("relay", "172.31.254.2/29"))})
        answers = [dict(target=target, protocol=protocol, connected=True, answer="7f00002a") for target, protocol in qualify.POSITIVES]
        delivered = ["outside" if a["target"] == "alternate_dns" else a["target"] for a in answers]
        after = {role: counts[role] + delivered.count(role) for role in counts}
        control = dict(before=counts, after=after, answers=answers)
        ended = after | {"fixture": after["fixture"] + 2}
        final_control = dict(before=ended, after={role: ended[role] + delivered.count(role) for role in counts}, answers=answers)
        probe = dict(nonce=plan["nonce"], docker_socket=2, files=dict.fromkeys(qualify.PROTECTED, "denied"),
                     denials={target + "/" + protocol: dict(nonce=plan["nonce"], address=qualify.TARGETS[target][0],
                              port=qualify.TARGETS[target][1], protocol=protocol, connected=False, answer="") for target, protocol in qualify.DENIALS})
        rows = [dict(ordinal=i, method="POST", route="/v1/responses", status=200, model="gpt-5.4", id=str(i) * 32) for i in (1, 2)]
        independent = {"v": 1, "requests": [dict(id=r["id"], route=r["route"], model=r["model"], credential="accepted") for r in rows]}
        view = dict(plan=plan, probe=probe, network=network, controls=dict(before=control, after=final_control),
                    before=after, after=ended, raw="\n".join(map(json.dumps, rows)), independent=json.dumps(independent))
        self.assertIsNone(qualify.bracket(view)["qualification"])
        reachable = probe["denials"] | {"host/tcp": probe["denials"]["host/tcp"] | {"connected": True}}
        dead = [answer | {"connected": False} for answer in answers]
        for changed in (view | {"after": {}}, view | {"controls": dict(before=control | {"answers": []}, after=final_control)},
                        view | {"probe": probe | {"files": {}}}, view | {"probe": probe | {"docker_socket": 0}},
                        view | {"independent": '{"v":1,"requests":[]}'}, view | {"probe": probe | {"denials": reachable}},
                        view | {"controls": dict(before=control | {"answers": dead}, after=final_control)}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                qualify.bracket(changed)
