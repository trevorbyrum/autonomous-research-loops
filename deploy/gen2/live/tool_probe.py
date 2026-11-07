"""Q11 actual exec_command payload; independent working observers are Q1–Q3's oracle."""
import json
import socket
from pathlib import Path

assert Path("/inputs/approved.txt").read_text() == "2e1-approved\n"
results = {}
for path in ("/var/lib/gen2/control", "/evidence/access.jsonl", "/root/.codex/auth.json", "/inputs/other-topic"):
    try:
        Path(path).read_bytes()
        results[path] = "reachable"
    except OSError:
        results[path] = "denied"
for address in (("10.0.2.2", 18870), ("172.31.254.1", 18080), ("172.31.252.3", 8081),
                ("172.31.248.3", 18080), ("172.31.250.3", 8765), ("172.31.249.3", 5432)):
    with socket.socket() as probe:
        probe.settimeout(2)
        results[str(address)] = "reachable" if probe.connect_ex(address) == 0 else "denied"
with socket.socket(socket.AF_UNIX) as probe:
    results["docker_socket"] = probe.connect_ex("/run/user/1000/gen2-2e1/docker.sock")
Path("/out/tool-sentinel.json").write_text(json.dumps(results))
print("2e1-tool-ok")
