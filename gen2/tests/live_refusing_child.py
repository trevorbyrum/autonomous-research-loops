"""The live-order executor child for the collection-refusal composition test: the PRODUCTION child (`gen2.app.child.main`) with the PRODUCTION live agent
(`live.agent_for`), whose `DockerCLI.run` talks to a daemon-free transport that writes real cidfiles and returns inspect shapes and then refuses at collection
(nothing was written to the out directory). The refusal leaves through `live.agent_for` -> `child.main` as the child's own exit status; the generated end
fact comes from the production `contain_job` that `run` calls. Run by path in the job's scratch directory; not collected as tests; no Docker, no provider."""
import hashlib
import json
import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gen2.app import child, live   # noqa: E402
from gen2.core import canonical   # noqa: E402
from gen2.core.instants import utc_instant_ns   # noqa: E402
from gen2.supervisor import docker_cli, jobs   # noqa: E402

NET, EGRESS, IMAGE = "b" * 64, "c" * 64, "sha256:" + "1" * 64
FAKE_SHA = hashlib.sha256(b"fake").hexdigest()
PIN = "sha256:" + hashlib.sha256(b"configuration").hexdigest()


def transport(root):
    """What the pinned `docker` shows: `create` writes its --cidfile, `inspect` returns the created container's shape; every call is logged to the station root."""
    ids, names = {}, {"initializer": "1", "relay": "2", "runner": "3"}

    def run(target, argv, env, deadline, bounds):
        args = argv[3:]
        with open(root / "calls.jsonl", "a") as log:
            log.write(json.dumps(args) + "\n")
        if args[0] == "create":
            path = Path(args[args.index("--cidfile") + 1])
            ids[path.stem] = names[path.stem] * 64
            path.write_text(ids[path.stem])
            return 0, ids[path.stem].encode(), b""
        if args[0] == "inspect":
            role = {v: k for k, v in ids.items()}[args[1]]
            networks = ({target.read("network-job.json")["Name"]: {"NetworkID": "", "IPAMConfig": {"IPv4Address": "172.31.254.2"}}, "egress": {"NetworkID": "", "IPAMConfig": None}}
                        if role == "relay" else {})
            return 0, json.dumps([{"Id": args[1], "Image": IMAGE, "Config": {"Image": IMAGE}, "HostConfig": {}, "NetworkSettings": {"Networks": networks}}]).encode(), b""
        if args[:2] == ("network", "inspect") or list(args[:2]) == ["network", "inspect"]:
            view = {"Id": EGRESS, "Name": "egress", "Internal": False, "Containers": {}} if args[2] == EGRESS else {"Id": NET, "Containers": {"2" * 64: {}}}
            return 0, json.dumps([view]).encode(), b""
        return 0, b"", b""   # kill, rm, stop
    return run


def main(argv):
    directory = Path(argv[0]) if argv else Path.cwd()
    root = directory.parent.parent.parent
    job = jobs.Job(directory.parent.parent, directory.parent.name)
    manifest = {"version": 1, "tree": "t", "platform": "linux/amd64", "route": "real", "socket": docker_cli.SOCKET, "cli_sha256": FAKE_SHA, "daemon_version": "29.0.0",
                "credential_ref": "dummy-seed", "credential_version": "v1", "supervision": "supervised", "qualification_state": "qualified", "qualification_ref": PIN,
                "images": {r: {"pin": IMAGE, "kind": "engine-image-id"} for r in docker_cli.ROLES - {"fixture"}},
                "configurations": {r: {"pin": PIN} for r in docker_cli.ROLES - {"fixture"}}}
    retained = root / "retained"
    retained.mkdir(exist_ok=True)
    (retained / PIN.removeprefix("sha256:")).write_bytes(b"configuration")
    (root / "manifest.json").write_bytes(canonical.canonical_bytes(manifest))
    inputs = directory / "inputs"
    inputs.mkdir(exist_ok=True)
    raw = canonical.canonical_bytes({"purpose": "scope", "limits": {"max_output_bytes": 1 << 20}})
    (inputs / "prompt.md").write_bytes(b"prompt")
    (inputs / "input.json").write_bytes(raw)
    env = {"GEN2_PURPOSE": "research_pass/scope", "GEN2_INPUT_DIGEST": canonical.bytes_digest(raw), "GEN2_MANIFEST": str(root / "manifest.json"), "GEN2_RETAINED_DIR": str(retained)}
    for name in ("out", "evidence"):
        (root / name).mkdir(exist_ok=True)
    real = docker_cli.DockerCLI

    def build(*args, **kwargs):   # the fixture orders' deadlines are fixed dates: the backend's clock reads 300 s before this order's
        cli = real(*args, **kwargs, clock=lambda: utc_instant_ns(job.read("order.json")["deadline_at"]) / 1e9 - 300)
        for name in ("out", "evidence"):
            (root / name / cli.plan["generation"]).mkdir(parents=True, exist_ok=True)
        cli.plan.update(slots={n: str(root / n) for n in ("out", "evidence")}, binds={**cli.plan["binds"], "out": str(root / "out" / cli.plan["generation"])})
        return cli
    table = {"research_pass/scope": lambda stage, bytes_of: (lambda work, judgment: {})}
    create = jobs.Job.create
    withhold = (root / "no-publish").exists()   # the counterfactual: the fallback end fact is never published
    with mock.patch.object(jobs.Job, "create", lambda self, name, value: True if withhold and name == "docker-complete.json" else create(self, name, value)), \
            mock.patch.object(docker_cli, "CLI_SHA", FAKE_SHA), \
            mock.patch.object(docker_cli.Path, "read_bytes", lambda path, real=Path.read_bytes: b"fake" if str(path) == docker_cli.CLI else real(path)), \
            mock.patch.object(docker_cli, "free_space"), mock.patch.object(docker_cli, "DockerCLI", build), \
            mock.patch.object(real, "network", lambda self, g: job.write("network-job.json", {"Id": NET, "Name": "gen2-2e1-live-job-" + g}) or NET), \
            mock.patch.object(real, "runtime"), mock.patch.object(real, "endpoint"), mock.patch.object(real, "start"), mock.patch.object(real, "drain"), \
            mock.patch.object(real, "logs", lambda self, *a, **k: (b"events", b"diagnostics")), \
            mock.patch.object(real, "end", lambda self, cid, role="runner": {"State": {"ExitCode": 0}}):
        agent = live.agent_for(directory, env, execute=transport(root))   # the production live agent; collection refuses because the out directory holds no judgment
        return child.main([str(directory)], env=env, table=table, agent=agent)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
