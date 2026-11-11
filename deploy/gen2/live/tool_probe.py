"""Q11 tool payload: production-namespace denials and the Q8 live descendant."""
import contextlib
import io
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/opt/live")
import q_net

assert Path("/inputs/approved.txt").read_text() == "2e1-approved\n"
nonce = Path("/inputs/q-nonce").read_text().strip()
assert len(nonce) == 32 and set(nonce) <= set("0123456789abcdef")
results = dict(nonce=nonce, files={}, denials={})
for path in ("/var/lib/gen2/control", "/evidence/access.jsonl", "/root/.codex/auth.json", "/inputs/other-topic",
             "/etc/gen2/provider-auth.conf", "/etc/gen2/provider-ca.pem"):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        os.close(fd)
        results["files"][path] = "reachable"
    except OSError:
        results["files"][path] = "denied"
targets = [(name, "tcp") for name in ("host_alias", "host", "child", "lan", "outside", "peer", "fixture", "service", "db")]
targets += [(name, protocol) for name in ("local_dns", "embedded_dns", "resolver", "alternate_dns") for protocol in ("udp", "tcp")]
for target, protocol in targets:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        q_net.probe(*q_net.TARGETS[target], nonce, protocol)
    results["denials"][target + "/" + protocol] = json.loads(output.getvalue())
with socket.socket(socket.AF_UNIX) as probe:
    results["docker_socket"] = probe.connect_ex("/run/user/1000/gen2-2e1/docker.sock")
results["namespace"] = {name: Path("/proc/net", name).read_text() for name in ("route", "ipv6_route", "tcp", "udp")}
child = subprocess.Popen(["/bin/sleep", "600"], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
results["descendant_pid"] = child.pid
Path("/out/tool-sentinel.json").write_text(json.dumps(results))
print(json.dumps(results))
print("2e1-tool-ok")
