"""Q1–Q3 finite observers/probes; exchanges are evidence, never qualification."""
import json
import http.client
import os
import re
import select
import socket
import struct
import sys
import time
from pathlib import Path

ROLES = {"host": ("127.0.0.1", 18870), "child": ("172.31.254.1", 18080),
         "lan": ("172.31.247.3", 18080), "outside": ("172.31.246.3", 18080),
         "resolver": ("172.31.245.3", 53), "peer": ("172.31.248.3", 18080)}
TARGETS = ROLES | {"host_alias": ("10.0.2.2", 18870), "local_dns": ("127.0.0.1", 53),
    "embedded_dns": ("127.0.0.11", 53), "alternate_dns": ("172.31.246.3", 53), "relay": ("172.31.254.2", 8080),
    "fixture": ("172.31.252.3", 8081), "service": ("172.31.250.3", 8765), "db": ("172.31.249.3", 5432)}


def model_request(nonce):
    return dict(model="gpt-5.4", stream=True, input=nonce,
                tools=[dict(name=name) for name in ("exec_command", "write_stdin", "apply_patch")])


def relay(nonce):
    connection = http.client.HTTPConnection(*TARGETS["relay"], timeout=2)
    answer = dict(connected=False, nonce=nonce)
    try:
        connection.request("POST", "/v1/responses", json.dumps(model_request(nonce)).encode(),
                           {"Authorization": "Bearer 2e1-fixture-accepted", "Content-Type": "application/json",
                            "Accept": "text/event-stream", "X-Request-ID": nonce, "Connection": "close"})
        response = connection.getresponse()
        body = response.read((1 << 20) + 1)
        if len(body) > 1 << 20:
            raise ValueError("relay response bound")
        answer.update(connected=True, status=response.status, media=response.getheader("Content-Type"), body=body.hex())
    except (OSError, http.client.HTTPException):
        pass
    finally:
        connection.close()
    print(json.dumps(answer))


def dns_reply(packet, nonce):
    if not 12 < len(packet) <= 512 or nonce[:16].encode() not in packet[12:] or not packet.endswith(b"\x07invalid\x00\x00\x01\x00\x01"):
        raise ValueError("finite .invalid query required")
    return packet[:2] + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00" + packet[12:] + b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x00\x00\x04\x7f\x00\x00\x2a"


def observe(role, nonce):
    address, port = ROLES[role]
    bindings = [(socket.SOCK_STREAM, port)] + ([(socket.SOCK_DGRAM, 53), (socket.SOCK_STREAM, 53)] if role == "outside" else [])
    if role == "resolver":
        bindings.append((socket.SOCK_DGRAM, 53))
    sockets = []
    origin = dict(pid=os.getpid(), boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                  start=Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19], netns=os.readlink("/proc/self/ns/net"), userns=os.readlink("/proc/self/ns/user"))
    try:
        for kind, number in bindings:
            endpoint = socket.socket(socket.AF_INET, kind)
            endpoint.bind((address, number))
            if kind == socket.SOCK_STREAM:
                endpoint.listen(8)
            sockets.append(endpoint)
        print(json.dumps(dict(event="ready", role=role, nonce=nonce, origin=origin)), flush=True)
        deadline, delivered = time.monotonic() + 600, 0
        while time.monotonic() < deadline and delivered < 64:
            for endpoint in select.select(sockets, [], [], 1)[0]:
                tcp = endpoint.type == socket.SOCK_STREAM
                connection, peer = endpoint.accept() if tcp else (endpoint, None)
                connection.settimeout(2)
                try:
                    dns = endpoint.getsockname()[1] == 53
                    packet, peer = (connection.makefile("rb").read(60) if dns else connection.recv(1024), peer) if tcp else connection.recvfrom(512)
                    answer = dns_reply(packet[2:] if tcp and dns else packet, nonce) if dns else nonce.encode()
                    if not dns and not packet.startswith(("GET /" + nonce[:16]).encode()):
                        raise ValueError("finite nonce GET required")
                    delivered += 1
                    print(json.dumps(dict(event="delivery", role=role, nonce=nonce, origin=origin, count=delivered,
                                          peer=peer, protocol="tcp" if tcp else "udp", forwarded=0, request=packet.hex())), flush=True)
                    if tcp:
                        connection.sendall(struct.pack("!H", len(answer)) + answer if dns else b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: 32\r\n\r\n" + answer)
                    else:
                        connection.sendto(answer, peer)
                finally:
                    if tcp:
                        connection.close()
    finally:
        for endpoint in sockets:
            endpoint.close()


def probe(address, port, nonce, protocol):
    if (address, port) not in TARGETS.values() or protocol not in {"tcp", "udp"} or (protocol == "udp" and port != 53):
        raise ValueError("unapproved Q target")
    question = b"".join(bytes([len(p)]) + p.encode() for p in (nonce, "invalid")) + b"\x00\x00\x01\x00\x01"
    packet = b"\xa5\x5a\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + question if port == 53 else ("GET /" + nonce + " HTTP/1.1\r\nHost: fixture\r\nConnection: close\r\n\r\n").encode()
    connected, answer = False, b""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if protocol == "udp" else socket.SOCK_STREAM) as endpoint:
        endpoint.settimeout(2)
        try:
            endpoint.connect((address, port))
            connected = True
            endpoint.sendall(struct.pack("!H", len(packet)) + packet if protocol == "tcp" and port == 53 else packet)
            answer = endpoint.recv(1024)
        except OSError:
            pass
    print(json.dumps(dict(connected=connected, answer=answer.hex(), nonce=nonce, address=address, port=port, protocol=protocol)))


if __name__ == "__main__":
    if sys.argv[1] == "inspect":
        print(json.dumps({name: Path("/proc/net/" + name).read_text() for name in ("route", "ipv6_route", "tcp", "udp")}))
        sys.exit(0)
    if not re.fullmatch("[0-9a-f]{32}", sys.argv[3]):
        raise ValueError("original challenge required")
    if sys.argv[1] == "observe":
        observe(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "probe":
        probe(sys.argv[2], int(sys.argv[4]), sys.argv[3], sys.argv[5])
    elif sys.argv[1] == "relay" and (sys.argv[2], int(sys.argv[4]), sys.argv[5]) == (*TARGETS["relay"], "tcp"):
        relay(sys.argv[3])
    else:
        raise ValueError("finite Q operation required")
