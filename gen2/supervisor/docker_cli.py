"""2e1 v7 §3: finite CLI/collection primitives; traces I/L/E/D.

The productive supervisor entrance remains closed by isolation.py. The later
finite qualification lane supplies protected manifest bytes and original end
observers; none of these primitives grants Router dispatch authority.
"""
import hashlib
import json
import os
import re
import selectors
import subprocess
import time
from pathlib import Path

from gen2.supervisor import jobs
from gen2.supervisor.isolation import LiveProfileRefused, PIN, PLACEHOLDERS
from gen2.supervisor.spool import SpoolFull, read_scratch

CLI = "/usr/bin/docker"
CLI_SHA = "adbc67ecdc2cd2d350c01a5964a205bd81470b485aba1fb90c2f559de9e4584f"
SOCKET = "/run/user/1000/gen2-2e1/docker.sock"
CID = re.compile(r"[0-9a-f]{64}")
ROLES = frozenset({"engine", "runner", "relay", "gateway", "db", "fixture"})
BATCH = 32 << 20
COMMANDS = frozenset({"create", "start", "wait", "inspect", "logs", "stop", "kill", "rm"})
NETWORKS = {"job": "172.31.254.0/29", "fixture": "172.31.252.0/29"}


def require(ok, reason):
    if not ok:
        raise LiveProfileRefused(reason)


def manifest_gate(manifest, retained, tree):
    """Check retained operands, not qualification. Live admission still refuses."""
    require(isinstance(manifest, dict), "manifest_shape")
    require(manifest.get("version") == 1 and manifest.get("tree") == tree, "manifest_tree")
    require(manifest.get("socket") == SOCKET and manifest.get("cli_sha256") == CLI_SHA, "manifest_runtime")
    require(manifest.get("platform") == "linux/amd64" and manifest.get("route") == "fixture", "manifest_route")
    for key in ("daemon_version", "credential_ref", "credential_version"):
        require(isinstance(manifest.get(key), str) and manifest[key] not in PLACEHOLDERS, "manifest_" + key)
    for key in ("images", "configurations"):
        values = manifest.get(key)
        require(isinstance(values, dict) and set(values) == ROLES, "manifest_roles")
        for role, value in values.items():
            pin = value.get("pin") if isinstance(value, dict) else None
            require(isinstance(pin, str) and PIN.fullmatch(pin), "manifest_pin")
            if key == "images":
                require(value.get("kind") in {"repo-digest", "engine-image-id"}, "manifest_digest_kind")
            else:
                data = retained(pin)
                require(isinstance(data, bytes) and "sha256:" + hashlib.sha256(data).hexdigest() == pin, "manifest_retained")
    return manifest


def capture(job, argv, env, deadline, bounds):
    """Bound both pipes while running; a CLI end never proves container end."""
    require(time.monotonic() < deadline, "cli_deadline")
    child = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True, close_fds=True)
    state = jobs.proc_stat(child.pid)
    identity = {"pid": child.pid, "session": child.pid, "starttime": state[2], "boot_id": jobs.boot_id()} if state else None
    outputs = [bytearray(), bytearray()]
    try:
        require(identity is not None, "cli_identity")
        job.write("docker-cli.json", identity)
        with selectors.DefaultSelector() as poll:
            for index, pipe in enumerate((child.stdout, child.stderr)):
                poll.register(pipe, selectors.EVENT_READ, index)
            while poll.get_map():
                remaining = deadline - time.monotonic()
                require(remaining > 0, "cli_deadline")
                for key, _ in poll.select(remaining):
                    index = key.data
                    chunk = os.read(key.fd, min(65536, bounds[index] + 1 - len(outputs[index])))
                    outputs[index].extend(chunk)
                    require(len(outputs[index]) <= bounds[index], "cli_overflow")
                    if not chunk:
                        poll.unregister(key.fileobj)
            code = child.wait(timeout=max(0.001, deadline - time.monotonic()))
        return code, bytes(outputs[0]), bytes(outputs[1])
    finally:
        for pipe in (child.stdout, child.stderr):
            pipe.close()
        if identity is None:
            child.kill()
            child.wait(timeout=5)
        else:
            ended = job.terminate(identity, term_grace=0, kill_grace=5, reap=child.poll)
            require(ended["confirmed"], "cli_end_unconfirmed")


class DockerCLI:
    def __init__(self, job, manifest, retained, tree, *, execute=capture, now=time.monotonic):
        self.manifest = manifest_gate(manifest, retained, tree)
        self.job, self.execute, self.now = job, execute, now
        self.deadline = now() + 120
        self.plan = job.read("docker-plan.json")
        require(isinstance(self.plan, dict) and bool(self.plan.get("origin")), "launch_originals")

    def call(self, args, *, mutation=False, seconds=5, bound=65536, end=False, logs=False):
        require(args[0] in COMMANDS or (args[0] == "network" and args[1] in {"create", "connect", "disconnect", "inspect", "rm"}), "cli_command")
        # I/D: rehash at use; never resolve a tag or inherit Docker/proxy config.
        require(hashlib.sha256(Path(CLI).read_bytes()).hexdigest() == CLI_SHA, "cli_pin")
        argv = (CLI, "--host", "unix://" + SOCKET, *args)
        key = hashlib.sha256(json.dumps(args).encode()).hexdigest()
        journal = self.job.read("docker.json") or {}
        if mutation:
            require(key not in journal, "mutation_already_intended")
            self.job.write("docker.json", {**journal, key: {"intent": list(argv)}})
        limit = self.now() + seconds
        deadline = limit if end else min(limit, self.deadline)
        require(deadline > self.now(), "cli_deadline")
        code, out, err = self.execute(self.job, argv, {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                                                      "DOCKER_CONFIG": str(self.job.dir / "docker-config")}, deadline, (bound, 4 << 20 if logs else 4096))
        require(code == 0 and (logs or not err) and len(out) <= bound and len(err) <= (4 << 20 if logs else 4096), "cli_failed")
        if mutation:
            self.job.write("docker.json", {**journal, key: {"intent": list(argv), "stdout": out.decode("ascii")}})
        return (out, err) if logs else out

    def network(self, generation, role="job"):
        require(role in NETWORKS, "network_role")
        require(re.fullmatch(r"[0-9a-f]{32}", generation), "network_generation")
        network = self.call(("network", "create", "--internal", "--driver", "bridge", "--subnet", NETWORKS[role],
                             "--opt", "com.docker.network.bridge.gateway_mode_ipv4=isolated", "gen2-2e1-live-" + role + "-" + generation), mutation=True).strip().decode()
        require(CID.fullmatch(network), "network_identity")
        view = json.loads(self.call(("network", "inspect", network)))[0]
        require(view["Id"] == network and view["Internal"] and not view["EnableIPv6"] and view["Driver"] == "bridge", "network_inspect")
        require(view["IPAM"]["Config"] == [{"Subnet": NETWORKS[role]}] and not view["Containers"], "network_members")
        self.job.write("network-" + role + ".json", view)
        return network

    def endpoint(self, action, network, cid, ip=None):
        require(action in {"connect", "disconnect"} and CID.fullmatch(network) and CID.fullmatch(cid), "endpoint_identity")
        return self.call(("network", action, *(("--ip", ip) if ip else ()), network, cid), mutation=True)

    def create_runner(self, network, binds):
        require(CID.fullmatch(network) and set(binds) == {"out", "inputs", "seed"}, "runner_bindings")
        require(binds == self.plan.get("binds") and network == (self.job.read("network-job.json") or {}).get("Id"), "runner_originals")
        args = ["create", "--cidfile", str(self.job.dir / "runner.cid"), "--pull=never", "--restart=no", "--read-only",
                "--user", "10001:10001", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "64",
                "--memory", "1g", "--memory-swap", "1g", "--cpus", "1", "--ulimit", "fsize=16777216:16777216",
                "--ulimit", "nofile=256:256", "--ulimit", "core=0:0", "--dns", "127.0.0.1", "--ipc=private",
                "--cgroupns=private", "--no-healthcheck", "--log-driver", "local", "--log-opt", "max-size=4m",
                "--log-opt", "max-file=1", "--network", network, "--ip", "172.31.254.3"]
        for name, size, mode in (("work", "128m", "0700"), ("auth/codex", "16m", "0700"), ("tmp", "64m", "1777"), ("run", "4m", "0700")):
            args.extend(("--tmpfs", f"/{name}:rw,nodev,nosuid,size={size},mode={mode},uid=10001,gid=10001"))
        for name, source in binds.items():
            require(Path(source).is_absolute() and "," not in source, "runner_bind_path")
            args.extend(("--mount", f"type=bind,src={source},dst=/{name}" + ("" if name == "out" else ",readonly")))
        args.append(self.manifest["images"]["runner"]["pin"])
        require(not (self.job.dir / "runner.cid").exists(), "cidfile_exists")
        cid = self.call(tuple(args), mutation=True, bound=4096).strip().decode("ascii")
        found = read_scratch(self.job.dir, "runner.cid", 4096)
        require(CID.fullmatch(cid) and found["status"] == "present" and found["data"].strip() == cid.encode(), "create_identity")
        record = self.inspect(cid)
        require(record["Id"] == cid and record["Image"] == args[-1], "create_inspect")
        self.job.write("runner.json", record)
        return cid

    def inspect(self, cid):
        require(isinstance(cid, str) and CID.fullmatch(cid), "container_identity")
        records = json.loads(self.call(("inspect", cid)))
        require(isinstance(records, list) and len(records) == 1 and records[0].get("Id") == cid, "inspect_identity")
        return records[0]

    def start(self, cid):
        free_space(self.plan["paths"], 16 << 30)
        original = self.job.read("runner.json")
        require(original is not None and self.inspect(cid) == original, "start_identity")
        self.call(("start", cid), mutation=True, bound=4096)
        self.job.write("runner-start.json", self.inspect(cid))

    def end(self, cid, descendants_ended):
        waited = self.call(("wait", cid), seconds=120, bound=4096).strip()
        original, observed = self.job.read("runner-start.json"), self.inspect(cid)
        require(original is not None, "end_original")
        for key in ("Id", "Image", "Config", "HostConfig", "NetworkSettings"):
            require(observed[key] == original[key], "end_binding")
        state = observed["State"]
        require(state["StartedAt"] == original["State"]["StartedAt"] and not any(state[k] for k in ("Running", "Restarting", "Paused", "OOMKilled")), "end_state")
        require(waited == str(state["ExitCode"]).encode() and descendants_ended(original), "end_unconfirmed")
        self.job.write("runner-end.json", observed)
        return observed

    def logs(self, cid):
        require((self.job.read("runner-end.json") or {}).get("Id") == cid, "logs_before_end")
        require(self.job.read("runner-logs.json") is None, "logs_already_intended")
        self.job.write("runner-logs.json", {"intent": cid})
        return self.call(("logs", cid), seconds=10, bound=4 << 20, end=True, logs=True)

    def contain(self, cid, *, kill=False):
        require((self.job.read("runner.json") or {}).get("Id") == cid, "contain_original")
        return self.call(("kill", cid) if kill else ("stop", "--time", "5", cid), mutation=True, seconds=10, end=True)

    def remove(self, cid, ack):
        require(ack and (self.job.read("runner-end.json") or {}).get("Id") == cid, "remove_before_ack")
        return self.call(("rm", cid), mutation=True, end=True)


def free_space(paths, floor):
    require(bool(paths), "free_space_paths")
    for path in paths:
        info = os.statvfs(path)
        require(info.f_bavail * info.f_frsize >= floor, "free_space_floor")


def slot(path):
    """Pin every fixed ancestor without following links; caller retains the fd."""
    require(Path(path).is_absolute(), "slot_absolute")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in Path(path).parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return os.dup(fd)
    finally:
        os.close(fd)


class EvidenceBatch:
    """E: enforced aggregate cap, including channels and all fixed files."""
    def __init__(self, spool, topic):
        require(spool.quota_bytes <= 64 << 20, "evidence_spool_quota")
        self.spool, self.topic, self.used = spool, topic, 0

    def stage(self, data, media):
        require(self.used + len(data) <= BATCH, "collection_batch_cap")
        free_space([self.spool.root], (2 << 30) + self.used + len(data))
        ref = self.spool.stage(self.topic, data, media)
        self.used += len(data)
        return ref

    def collect(self, slot_fd, generation, identity, *, writers_ended, kind="outcome"):
        require(writers_ended, "collection_writers_live")
        require(re.fullmatch(r"[0-9a-f]{32}", generation), "collection_generation")
        name, bound, media = {"outcome": ("outcome.json", 16 << 20, "application/json"),
                              "access": ("access.jsonl", 16 << 20, "application/x-ndjson"),
                              "fixture": ("fixture.json", 1 << 20, "application/json")}[kind]
        fd = os.open(generation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=slot_fd)
        try:
            info = os.fstat(fd)
            require((info.st_dev, info.st_ino) == identity, "collection_identity")
            found = read_scratch(fd, name, bound)
            require(found["status"] == "present", "collection_" + found["status"])
            after = os.stat(generation, dir_fd=slot_fd, follow_symlinks=False)
            require((after.st_dev, after.st_ino) == identity, "collection_replaced")
            require(kind != "access" or found["data"].count(b"\n") <= 1024, "collection_rows")
            return self.stage(found["data"], media)
        finally:
            os.close(fd)
