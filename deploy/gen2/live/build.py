"""I02/F01: explicit docker-driver builder only; execution belongs to T9."""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from gen2.supervisor.docker_cli import CLI, CLI_SHA, SOCKET, free_space

BUILDX_VERSION = "github.com/docker/buildx v0.38.0 0dbe87f36ed472fe36b6796c3f70b4210a731fc5"
BUILDER_LIST = ("buildx", "ls", "--format", "json")


def checked(argv, **kwargs):
    """Retain the real interface's failure, never parse a failed command as evidence."""
    try:
        return subprocess.check_output(argv, stderr=subprocess.PIPE, **kwargs)
    except subprocess.CalledProcessError as error:
        raise ValueError(error.stderr.decode("utf-8", "replace")) from error


def bake_command(builder, targets=("runner", "engine", "gateway", "fixture")):
    return [CLI, "--context", builder, "buildx", "bake", "--builder", builder, "--file",
            "deploy/gen2/live/docker-bake.hcl", *targets]


def buildx_preflight(version, bake, env):
    """Print validates configuration, not execution: the context argv is separately fixed."""
    if version.strip() != BUILDX_VERSION:
        raise ValueError("Buildx version/commit pin")
    if bake != bake_command(bake[2]):
        raise ValueError("canonical dedicated-context Bake argv required")
    subprocess.run([*bake, "--print"], env=env, check=True, stdout=subprocess.DEVNULL, timeout=30)
    subprocess.run(bake_command(bake[2], ("cli-contract",)), env=env, check=True, stdout=subprocess.DEVNULL, timeout=30)


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
    if endpoint == builder:
        endpoint = contexts.get(builder)
    if endpoint not in (SOCKET, "unix://" + SOCKET):
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
        return checked([*cli, *args], env=env, timeout=10).decode("utf-8")
    def read(*args):
        return json.loads(text(*args))
    version = text("buildx", "version")
    contexts = {c["Name"]: c["Endpoints"]["docker"]["Host"] for c in read("context", "inspect", sys.argv[1])}
    builder_gate(sys.argv[1], builder_view(sys.argv[1], text(*BUILDER_LIST)), contexts)
    bake = bake_command(sys.argv[1])
    buildx_preflight(version, bake, env)
    subprocess.run(bake, env=env, check=True, timeout=1800)
    images = {role: read("image", "inspect", "gen2-2e1-" + role + ":offline")[0]["Id"] for role in ("runner", "engine", "gateway", "fixture")}
    if any(not re.fullmatch("sha256:[0-9a-f]{64}", pin) for pin in images.values()):
        raise ValueError("missing immutable custom image IDs")
    print(json.dumps({"digest_kind": "engine-image-id", "images": images, "builder": sys.argv[1], "qualification": None}))
