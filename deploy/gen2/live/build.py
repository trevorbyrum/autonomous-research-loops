"""I02/F01: explicit docker-driver builder only; execution belongs to T9."""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from gen2.supervisor.docker_cli import CLI_SHA, SOCKET, free_space


def builder_gate(builder, view, contexts):
    if not re.fullmatch(r"gen2-2e1-[a-z0-9-]+", builder) or view.get("Driver") != "docker" or len(view.get("Nodes", [])) != 1:
        raise ValueError("explicit dedicated docker-driver builder required; no BuildKit image pull")
    endpoint = view["Nodes"][0]["Endpoint"]
    if endpoint != SOCKET and contexts.get(endpoint) != SOCKET:
        raise ValueError("builder endpoint is not the dedicated daemon")


if __name__ == "__main__":
    if len(sys.argv) != 2 or any(os.environ.get(k) for k in ("BUILDX_BUILDER", "BUILDKIT_HOST", "DOCKER_HOST", "DOCKER_CONTEXT")):
        raise ValueError("pass the dedicated builder explicitly; ambient selection refused")
    if hashlib.sha256(Path("/usr/bin/docker").read_bytes()).hexdigest() != CLI_SHA:
        raise ValueError("Docker CLI pin")
    root = Path("/home/trevor/.local/share/gen2-2e1/storage")
    free_space([str(root / p) for p in ("outputs", "relay-evidence", "spool", "control", "docker")], 16 << 30)
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "DOCKER_CONFIG": "/home/trevor/.config/gen2-2e1/buildx"}
    cli = ["/usr/bin/docker", "--host", SOCKET]
    def read(*args):
        return json.loads(subprocess.check_output([*cli, *args], env=env, timeout=10))
    contexts = {c["Name"]: c["Endpoints"]["docker"]["Host"] for c in read("context", "inspect", sys.argv[1])}
    builder_gate(sys.argv[1], read("buildx", "inspect", sys.argv[1], "--format", "{{json .}}"), contexts)
    subprocess.run([*cli, "buildx", "bake", "--builder", sys.argv[1], "--file", "deploy/gen2/live/docker-bake.hcl",
                    "runner", "engine", "gateway", "fixture"], env=env, check=True, timeout=1800)
    images = {role: read("image", "inspect", "gen2-2e1-" + role + ":offline")[0]["Id"] for role in ("runner", "engine", "gateway", "fixture")}
    if any(not re.fullmatch("sha256:[0-9a-f]{64}", pin) for pin in images.values()):
        raise ValueError("missing immutable custom image IDs")
    print(json.dumps({"digest_kind": "engine-image-id", "images": images, "builder": sys.argv[1], "qualification": None}))
