"""Q1–Q3 evidence from the production runner, bracketed by independent controls.

The operator collects original snapshots; the verifier owns namespace review.
"""
from collections import Counter
import json
import re

from deploy.gen2.live import fixture
from deploy.gen2.live.q_net import ROLES, TARGETS, model_request
from gen2.supervisor.docker_cli import require

SERVICES = {role: TARGETS[role] for role in ("fixture", "service", "db")}
OBSERVERS = set(ROLES) | set(SERVICES)


def observer_set(plan):
    require(set(plan.get("observers", {})) == set(ROLES), "required_observers")
    require(set(plan.get("services", {})) == set(SERVICES), "required_service_observers")
    require(set(plan.get("controls", {})) == OBSERVERS, "required_controls")


def service_count(data, role):
    """Original service namespace: live listening socket and kernel TCP deliveries.
    Namespace-wide noise refuses a pair; this is not an application ACK.
    """
    lines = data.decode().splitlines()
    address, port = SERVICES[role]
    local = bytes(map(int, address.split(".")))[::-1].hex().upper()
    require(any(len(parts := line.split()) > 3 and parts[1] in (f"{local}:{port:04X}", f"00000000:{port:04X}")
                and parts[3] == "0A" for line in lines), "service_observer_ready")
    tcp = [line.split()[1:] for line in lines if line.startswith("Tcp:")]
    require(len(tcp) == 2 and len(tcp[0]) == len(tcp[1]), "service_observer_counter")
    count = int(dict(zip(*tcp))["PassiveOpens"])
    require(count >= 0, "service_observer_counter")
    return count


def delivery_delta(before, after, delivered):
    require(set(before) == set(after) == OBSERVERS and set(delivered) <= OBSERVERS, "required_observer_counts")
    expected = Counter(delivered)
    require(all(after[role] == before[role] + expected[role] for role in OBSERVERS), "delivery_counts")


def relay_response(answer):
    request = model_request(answer["nonce"])
    require(answer.get("connected") and answer.get("status") == 200 and answer.get("media") == "text/event-stream"
            and bytes.fromhex(answer.get("body", "")) == fixture.response("accepted", 1, request)[2], "relay_ingress")


def relay_record(answer, raw, independent):
    rows, record = [json.loads(line) for line in raw.splitlines()], json.loads(independent)
    require(len(rows) == 1, "relay_fixture_count")
    row = rows[0]
    require(row["ordinal"] == 1 and row["method"] == "POST" and row["route"] == "/v1/responses"
            and row["status"] == 200 and row["case"] == "accepted" and row["request"] == model_request(answer["nonce"])
            and bool(re.fullmatch("[0-9a-f]{32}", row["id"])) and row["id"] != answer["nonce"], "relay_fixture_request")
    require(record == {"v": 1, "requests": [dict(id=row["id"], route="/v1/responses", model="gpt-5.4", credential="accepted")]}, "relay_fixture_record")


def counts(data, nonce, origin):
    rows = [json.loads(line) for line in data.splitlines()]
    require(bool(rows) and len(rows) <= 65 and rows[0]["event"] == "ready", "observer_ready")
    require(all(r["nonce"] == nonce and r["origin"] == origin for r in rows), "observer_originals")
    require(all(r["event"] == "delivery" and r["count"] == i and r["forwarded"] == 0 for i, r in enumerate(rows[1:], 1)), "observer_delivery")
    return len(rows) - 1


PROTECTED = {"/var/lib/gen2/control", "/evidence/access.jsonl", "/root/.codex/auth.json", "/inputs/other-topic",
             "/etc/gen2/provider-auth.conf", "/etc/gen2/provider-ca.pem"}
POSITIVES = {(role, "tcp") for role in OBSERVERS - {"resolver"}} | {
    (target, protocol) for target in ("resolver", "alternate_dns") for protocol in ("udp", "tcp")}
DENIALS = {(target, "tcp") for target in ("host_alias", "host", "child", "lan", "outside", "peer", "fixture", "service", "db")} | {
    (target, protocol) for target in ("local_dns", "embedded_dns", "resolver", "alternate_dns") for protocol in ("udp", "tcp")}


def bracket(view):
    """One original attempt between two live controls; no absent observer or synthetic PASS."""
    plan, probe, network = view["plan"], view["probe"], view["network"]
    observer_set(plan)
    require(probe["nonce"] == plan["nonce"] and re.fullmatch("[0-9a-f]{32}", probe["nonce"]), "probe_nonce")
    require(network["Id"] == plan["job"] and network["Internal"] and not network["EnableIPv6"]
            and set(network["Containers"]) == {plan["runner"], plan["relay"]}, "two_member_job")
    for role, address in (("runner", "172.31.254.3/29"), ("relay", "172.31.254.2/29")):
        require(network["Containers"][plan[role]]["IPv4Address"] == address, "job_addresses")
    require(network["Options"].get("com.docker.network.bridge.gateway_mode_ipv4") == "isolated", "isolated_job")
    for phase in ("before", "after"):
        control = view["controls"][phase]
        require({(a["target"], a["protocol"]) for a in control["answers"]} == POSITIVES
                and len(control["answers"]) == len(POSITIVES), "required_controls")
        delivered = []
        for answer in control["answers"]:
            target = answer["target"]
            require(answer["connected"] is True and (TARGETS[target][1] != 53 or
                    bytes.fromhex(answer["answer"]).endswith(b"\x7f\x00\x00\x2a")), "live_positive")
            delivered.append("outside" if target == "alternate_dns" else target)
        delivery_delta(control["before"], control["after"], delivered)
    require(set(probe["denials"]) == {target + "/" + protocol for target, protocol in DENIALS}, "required_probes")
    for key, answer in probe["denials"].items():
        target, protocol = key.split("/")
        require(answer["nonce"] == plan["nonce"] and (answer["address"], answer["port"], protocol) == (*TARGETS[target], answer["protocol"]), "probe_binding")
        require(answer["connected"] is False if TARGETS[target][1] != 53 else
                not bytes.fromhex(answer["answer"]).endswith(b"\x7f\x00\x00\x2a"), "denied_probe")
    require(type(probe["docker_socket"]) is int and probe["docker_socket"] != 0 and set(probe["files"]) == PROTECTED
            and all(value == "denied" for value in probe["files"].values()), "runner_isolation")
    require(view["before"] == view["controls"]["before"]["after"] and view["after"] == view["controls"]["after"]["before"], "bracket_order")
    raw, independent = [json.loads(line) for line in view["raw"].splitlines()], json.loads(view["independent"])
    require(len(raw) == 2 and len({r["id"] for r in raw}) == 2 and [r["ordinal"] for r in raw] == [1, 2]
            and all(r["method"] == "POST" and r["route"] == "/v1/responses" and r["status"] == 200
                    and r["model"] == "gpt-5.4" and re.fullmatch("[0-9a-f]{32}", r["id"]) for r in raw), "relay_fixture_request")
    require(independent == {"v": 1, "requests": [dict(id=r["id"], route=r["route"], model=r["model"], credential="accepted") for r in raw]}, "relay_fixture_record")
    delivery_delta(view["before"], view["after"], ["fixture", "fixture"])
    return dict(qualification=None, namespace_review_required=True, probe=probe, network=network, fixture_record=independent)
