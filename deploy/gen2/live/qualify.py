"""Q1–Q3: paired live controls over T9 originals; no provisioning or Q PASS.
The independent verifier owns final namespace/route interpretation.
"""
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

from deploy.gen2.live import fixture
from deploy.gen2.live.q_net import ROLES, TARGETS, model_request
from gen2.supervisor import jobs
from gen2.supervisor.docker_cli import CLI, CLI_SHA, SOCKET, require
from gen2.supervisor.spool import read_scratch

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
    require(all(after[role] == before[role] + int(role in delivered) for role in OBSERVERS), "delivery_counts")


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


if __name__ == "__main__":
    path = Path(sys.argv[1])
    require(path.parent == Path("/home/trevor/.config/gen2-2e1"), "approved_plan_directory")
    kept = read_scratch(path.parent, path.name, 1 << 20)
    require(kept["status"] == "present", "protected_plan")
    p = json.loads(kept["data"])
    require(len(p["nonce"]) == 32 and set(p["nonce"]) <= set("0123456789abcdef"), "original_nonce")
    require(hashlib.sha256(Path(CLI).read_bytes()).hexdigest() == CLI_SHA, "cli_pin")
    deadline = p["started"] + 600
    cli, env = [CLI, "--host", SOCKET], {"PATH": "/usr/local/bin:/usr/bin:/bin"}
    def run(argv):
        require(time.monotonic() < deadline, "Q_window")
        data = subprocess.check_output(argv, env=env, timeout=min(10, deadline - time.monotonic()))
        require(len(data) <= 4 << 20, "Q_output_bound")
        return data
    def inspect(cid):
        v = json.loads(run(cli + ["inspect", cid]))[0]
        require(v["Id"] == cid and v["State"]["Running"], "original_live_CID")
        return dict(image=v["Image"], start=v["State"]["StartedAt"], pid=v["State"]["Pid"], networks=v["NetworkSettings"]["Networks"],
                    policy={k: v["HostConfig"].get(k) for k in ("Dns", "Sysctls", "NetworkMode", "CapDrop", "SecurityOpt", "ReadonlyRootfs", "Privileged", "PortBindings")})
    def execute(actor, arguments):
        if actor == "host":
            prefix = [sys.executable, str(Path(__file__).with_name("q_net.py"))]
        elif actor == "child":
            state = jobs.proc_stat(p["child"]["pid"])
            require(state and str(state[2]) == p["child"]["start"] and jobs.boot_id() == p["child"]["boot"] and os.readlink(f"/proc/{p['child']['pid']}/ns/net") == p["child"]["netns"], "original_child")
            prefix = ["/usr/bin/sudo", "-n", "/usr/bin/nsenter", "--target", str(p["child"]["pid"]), "--user", "--net", "--", "/usr/bin/python3", str(Path(__file__).resolve().with_name("q_net.py"))]
        else:
            require(actor in p["bindings"] and inspect(actor) == p["bindings"][actor], "actor_binding")
            prefix = cli + ["exec", "--user", "10001:10001", actor, "python3", "/opt/live/q_net.py"]
        return json.loads(run(prefix + arguments))
    def snapshot():
        observer_set(p)
        result = {}
        for role, observer in p["observers"].items():
            if "cid" in observer:
                require(inspect(observer["cid"]) == p["bindings"][observer["cid"]], "observer_binding")
                data = run(cli + ["logs", observer["cid"]])
            else:
                kept = read_scratch(observer["directory"], "q-" + role + ".jsonl", 1 << 20)
                require(kept["status"] == "present", "observer_present")
                data = kept["data"]
            result[role] = counts(data, p["nonce"], observer["origin"])
        for role, cid in p["services"].items():
            require(cid in p["bindings"] and inspect(cid) == p["bindings"][cid], "service_observer_binding")
            result[role] = service_count(run(cli + ["exec", cid, "/bin/cat", "/proc/net/tcp", "/proc/net/snmp"]), role)
        return result
    network = json.loads(run(cli + ["network", "inspect", p["job"]]))[0]
    require(network["Id"] == p["job"] and network["Internal"] and not network["EnableIPv6"] and set(network["Containers"]) == {p["runner"], p["relay"]}, "two_member_job")
    require(network["Containers"][p["runner"]]["IPv4Address"] == "172.31.254.3/29" and network["Containers"][p["relay"]]["IPv4Address"] == "172.31.254.2/29", "job_addresses")
    require(network["Options"].get("com.docker.network.bridge.gateway_mode_ipv4") == "isolated", "isolated_job")
    cases = [(name, "tcp", ["host" if name == "host_alias" else name]) for name in ("host_alias", "host", "child", "lan", "outside", "peer", "fixture", "service", "db")]
    cases += [(name, protocol, ["resolver", "outside"]) for name in ("local_dns", "embedded_dns", "resolver", "alternate_dns") for protocol in ("udp", "tcp")]
    receipts = []
    def probe(actor, target, protocol):
        address, port = TARGETS[target]
        return execute(actor, ["relay" if target == "relay" else "probe", address, p["nonce"][:16] + secrets.token_hex(8), str(port), protocol])
    snapshot()  # fail on absent/unstarted observers before any positive or negative probe
    allowed = probe(p["runner"], "relay", "tcp")
    relay_response(allowed)
    fixture_cid = p["services"]["fixture"]
    fixture_raw = run(cli + ["exec", fixture_cid, "/bin/cat", "/evidence/raw.jsonl"])
    fixture_record = run(cli + ["exec", fixture_cid, "/bin/cat", "/evidence/fixture.json"])
    relay_record(allowed, fixture_raw, fixture_record)
    for target, protocol, controls in cases:
        for phase in ("before", "after"):
            counters = snapshot()
            for role in controls:
                positive = "alternate_dns" if role == "outside" and TARGETS[target][1] == 53 else role
                answer = probe(p["controls"][role], positive, protocol)
                require(answer["connected"] and (bytes.fromhex(answer["answer"]).endswith(b"\x7f\x00\x00\x2a") if TARGETS[positive][1] == 53 else True), "live_positive")
            delivery_delta(counters, snapshot(), controls)
            if phase == "before":
                before = snapshot()
                negative = probe(p["runner"], target, protocol)
                require(not negative["connected"] if TARGETS[target][1] != 53 else not bytes.fromhex(negative["answer"]).endswith(b"\x7f\x00\x00\x2a"), "denied_probe")
                delivery_delta(before, snapshot(), [])
        receipts.append(dict(target=target, protocol=protocol, before=before, after=snapshot(), negative=negative))
    require(all(inspect(cid) == binding for cid, binding in p["bindings"].items()), "final_originals")
    print(json.dumps(dict(qualification=None, namespace_review_required=True, relay_probe=allowed, fixture_raw=fixture_raw.decode(), fixture_record=json.loads(fixture_record), probes=receipts, network=network, routes=execute(p["runner"], ["inspect"]),
        relay_namespace=run(cli + ["exec", p["relay"], "/bin/cat", "/proc/sys/net/ipv4/ip_forward", "/proc/sys/net/ipv6/conf/all/forwarding", "/proc/net/route", "/proc/net/ipv6_route"]).decode())))
