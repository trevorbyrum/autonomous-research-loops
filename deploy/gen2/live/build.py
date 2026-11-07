"""I02/F01: explicit docker-driver builder only; execution belongs to T9."""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from gen2.supervisor.docker_cli import CLI_SHA, SOCKET, free_space

BUILDX_VERSION = "github.com/docker/buildx v0.38.0 0dbe87f36ed472fe36b6796c3f70b4210a731fc5"
BUILDER_LIST = ("buildx", "ls", "--format", "json")


def buildx_preflight(version, help_text):
    """Pinned CLI contract: real version/help precede builder inspection or build."""
    if version.strip() != BUILDX_VERSION:
        raise ValueError("Buildx version/commit pin")
    for command, args in ((BUILDER_LIST[1], BUILDER_LIST[2:]), ("bake", ("--builder", "--file"))):
        for flag in (arg for arg in args if arg.startswith("--")):
            if not re.search(rf"(?m)^\s*(?:-\w,\s*)?{re.escape(flag)}(?:\s|$)", help_text.get(command, "")):
                raise ValueError("Buildx help missing required flag: " + flag)


def builder_view(builder, listing):
    """Native v0.38 JSON lines; exactly one named view, no text/table fallback."""
    views = [json.loads(line) for line in listing.splitlines()]
    if any(not isinstance(v, dict) or not isinstance(v.get("Name"), str) for v in views):
        raise ValueError("unexpected Buildx JSON view")
    matches = [v for v in views if v["Name"] == builder]
    if len(matches) != 1:
        raise ValueError("expected exactly one named Buildx view")
    return matches[0]


def builder_gate(builder, view, contexts):
    nodes = view.get("Nodes")
    if not re.fullmatch(r"gen2-2e1-[a-z0-9-]+", builder) or view.get("Driver") != "docker" or not isinstance(nodes, list) or len(nodes) != 1:
        raise ValueError("explicit dedicated docker-driver builder required; no BuildKit image pull")
    if not isinstance(nodes[0], dict) or nodes[0].get("Status") != "running" or nodes[0].get("Error") or view.get("Error"):
        raise ValueError("unexpected Buildx node state")
    endpoint = nodes[0].get("Endpoint")
    if not isinstance(endpoint, str):
        raise ValueError("missing Buildx node endpoint")
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
    def text(*args):
        return subprocess.check_output([*cli, *args], env=env, timeout=10).decode("utf-8")
    def read(*args):
        return json.loads(text(*args))
    buildx_preflight(text("buildx", "version"), {cmd: text("buildx", cmd, "--help") for cmd in (BUILDER_LIST[1], "bake")})
    contexts = {c["Name"]: c["Endpoints"]["docker"]["Host"] for c in read("context", "inspect", sys.argv[1])}
    builder_gate(sys.argv[1], builder_view(sys.argv[1], text(*BUILDER_LIST)), contexts)
    subprocess.run([*cli, "buildx", "bake", "--builder", sys.argv[1], "--file", "deploy/gen2/live/docker-bake.hcl",
                    "runner", "engine", "gateway", "fixture"], env=env, check=True, timeout=1800)
    images = {role: read("image", "inspect", "gen2-2e1-" + role + ":offline")[0]["Id"] for role in ("runner", "engine", "gateway", "fixture")}
    if any(not re.fullmatch("sha256:[0-9a-f]{64}", pin) for pin in images.values()):
        raise ValueError("missing immutable custom image IDs")
    print(json.dumps({"digest_kind": "engine-image-id", "images": images, "builder": sys.argv[1], "qualification": None}))
