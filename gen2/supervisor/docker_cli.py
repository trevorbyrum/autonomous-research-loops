"""2e1 v7 §3: finite CLI/collection primitives; traces I/L/E/D.

The productive supervisor entrance remains closed by isolation.py. The later
finite qualification lane supplies protected manifest bytes and original end
end proof (the daemon's own final inspect, Gate S #7c); none of these primitives grants Router dispatch authority.
"""
import contextlib
import errno
import hashlib
import json
import os
import re
import selectors
import subprocess
import time
from datetime import datetime
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

from gen2.core.instants import utc_instant_ns
from gen2.supervisor import jobs, rejection
from gen2.supervisor.isolation import LiveProfileRefused, PIN, PLACEHOLDERS
from gen2.supervisor.spool import read_scratch

CLI = "/usr/bin/docker"
CLI_SHA = "adbc67ecdc2cd2d350c01a5964a205bd81470b485aba1fb90c2f559de9e4584f"
SOCKET = "/run/user/1000/gen2-2e1/docker.sock"
CID = re.compile(r"[0-9a-f]{64}")
ROLES = frozenset({"engine", "runner", "relay", "gateway", "db", "fixture"})
BATCH = 32 << 20
COMMANDS = frozenset({"create", "start", "wait", "inspect", "info", "logs", "stop", "kill", "rm"})
# The installed runtime the end proof is bound to (T9 receipt, `docker info` of the dedicated daemon). A container's cgroup is destroyed
# before the daemon reports it stopped, so "exited, PID 0, no error" in a private PID namespace is the end of every descendant (Gate S #7c).
RUNTIME = {"ServerVersion": "29.9.0", "CgroupVersion": "2", "CgroupDriver": "systemd", "LiveRestoreEnabled": False}
RUNTIME_IDS = {"ContainerdCommit": "f2551031d7276a770f65f98c9b52e57e7dad07e8", "RuncCommit": "v1.5.2-0-g29dd3dc2"}
DRAIN_SECONDS, DRAIN_LIMIT = 8, 10   # the bounded wait after ingress closes (reports waiting, not quiescence); the whole step must finish within the limit
SEAL = "admission-closed.json"
RESERVE_S, LATE_END_S = 90, 50   # the runner's allowance ends RESERVE_S before the order's deadline (a normal-path reserve for the tail, not a guarantee); a relay removed later than LATE_END_S past it is outside the qualified send window
# The relay's real-route files, plan key -> destination (relay only, read-only): its key include and its CA bundle. Destinations are lane C's D16 contract.
RELAY_PROVIDER = {"provider_auth": "etc/gen2/provider-auth.conf", "provider_ca": "etc/gen2/provider-ca.pem"}
MODEL = "gpt-6.1-terra"
NETWORKS = {"job": "172.31.254.0/29", "fixture": "172.31.252.0/29"}
EGRESS_FIELDS = ("network_id", "name", "subnet", "gateway")


def require(ok, reason):
    if not ok:
        raise LiveProfileRefused(reason)


def validate_egress(egress):
    """Refuse an incomplete or inconsistent approved bridge before any Docker action."""
    reason = "profile_egress_network"
    require(isinstance(egress, dict) and all(isinstance(egress.get(k), str) for k in EGRESS_FIELDS), reason)
    require(CID.fullmatch(egress["network_id"]) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", egress["name"]), reason)
    try:
        subnet, gateway = IPv4Network(egress["subnet"]), IPv4Address(egress["gateway"])
    except ValueError:
        raise LiveProfileRefused(reason) from None
    require(str(subnet) == egress["subnet"] and subnet.prefixlen <= 30
            and subnet.network_address < gateway < subnet.broadcast_address and gateway != subnet[2], reason)


def _binding(record):
    return {key: record[key] for key in ("Id", "Image", "Config", "HostConfig")}, {
        name: {key: network.get(key) for key in ("NetworkID", "IPAMConfig", "Aliases")}
        for name, network in record["NetworkSettings"]["Networks"].items()}


START_CHANGES = {"OomScoreAdj": (0, 200), "OomKillDisable": (False, None)}   # the real daemon's only create->start HostConfig changes: {field: (created, started)} (T9 log probe)


def _started(record, started, expected):
    """The created record as the daemon reports it after start: only the pinned fields, only from their exact created value (type included: 0 is not
    False). Every attached network's ID is empty until start (created state, the retained native inspects) and then must be EXACTLY the expected ID of
    that network name (`expected`: the job network and the upstream network, the backend's own); the `none` network has no ID the plan knows, so
    any 64-hex ID the daemon shows. A network not named here keeps its created value, so it must be unchanged."""
    host = dict(record["HostConfig"])
    for key, (before, after) in START_CHANGES.items():
        if key in host and host[key] == before and type(host[key]) is type(before):
            host[key] = after
    want = {**expected, "none": (((started.get("NetworkSettings") or {}).get("Networks") or {}).get("none") or {}).get("NetworkID")}
    networks = {name: {**value, "NetworkID": want[name]} if value.get("NetworkID") == "" and CID.fullmatch(str(want.get(name))) else value
                for name, value in record["NetworkSettings"]["Networks"].items()}
    return {**record, "HostConfig": host, "NetworkSettings": {**record["NetworkSettings"], "Networks": networks}}


def _when(text, reason):
    """A daemon timestamp (RFC 3339, up to nanoseconds, Z) as a datetime; a zero date, a malformed one or a non-string refuses."""
    found = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z", text) if isinstance(text, str) else None
    try:
        moment = datetime.fromisoformat(found[1] + "." + (found[2] or "0")[:6].ljust(6, "0")) if found else None
    except ValueError:
        moment = None
    require(moment is not None and moment.year > 1, reason)
    return moment


def manifest_gate(manifest, retained, tree):
    """Check retained operands, not qualification. Live admission still refuses."""
    require(isinstance(manifest, dict), "manifest_shape")
    require(manifest.get("version") == 1 and manifest.get("tree") == tree, "manifest_tree")
    require(manifest.get("socket") == SOCKET and manifest.get("cli_sha256") == CLI_SHA, "manifest_runtime")
    require(manifest.get("platform") == "linux/amd64" and manifest.get("route") in ("fixture", "real"), "manifest_route")
    roles = ROLES if manifest["route"] == "fixture" else ROLES - {"fixture"}   # a real route has no fixture container, so no fixture image or configuration
    # Seam e: productive dispatch needs a supervised profile with a pinned qualified claim; a claim is not proof (v7 §2).
    require(manifest.get("supervision") == "supervised", "manifest_not_supervised")
    require(manifest.get("qualification_state") == "qualified" and isinstance(manifest.get("qualification_ref"), str)
            and bool(PIN.fullmatch(manifest["qualification_ref"])), "manifest_not_qualified")
    for key in ("daemon_version", "credential_ref", "credential_version"):
        require(isinstance(manifest.get(key), str) and manifest[key] not in PLACEHOLDERS, "manifest_" + key)
    for key in ("images", "configurations"):
        values = manifest.get(key)
        require(isinstance(values, dict) and set(values) == roles, "manifest_roles")
        for role, value in values.items():
            pin = value.get("pin") if isinstance(value, dict) else None
            require(isinstance(pin, str) and PIN.fullmatch(pin), "manifest_pin")
            if key == "images":
                require(value.get("kind") in {"repo-digest", "engine-image-id"}, "manifest_digest_kind")
            else:
                data = retained(pin)
                require(isinstance(data, bytes) and "sha256:" + hashlib.sha256(data).hexdigest() == pin, "manifest_retained")
    return manifest


BOOT = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")


def _identity(record):
    """Whether `record` is a `docker-cli.json` identity this producer writes: positive pid, its own session, a start time, a boot ID of the kernel's form
    (any boot, an older one included), and a `confirmed` that is absent or exactly True."""
    return (isinstance(record, dict) and all(type(record.get(k)) is int and record[k] > 0 for k in ("pid", "session", "starttime")) and record["session"] == record["pid"]
            and isinstance(record.get("boot_id"), str) and bool(BOOT.fullmatch(record["boot_id"])) and record.get("confirmed", True) is True)


def capture(job, argv, env, deadline, bounds):
    """Bound both pipes while running; a CLI end never proves container end."""
    require(time.monotonic() < deadline, "cli_deadline")
    try:
        previous = job.read("docker-cli.json")
    except (OSError, ValueError):
        previous = {}   # unreadable: unconfirmed, never overwritten
    if previous is not None:   # a CLI killed with its launcher mid-command: end it by its recorded identity; any record this producer could not have written stays, unconfirmed
        require(_identity(previous), "cli_previous_unconfirmed")
        if previous.get("confirmed") is not True:
            ended = job.terminate(previous, term_grace=0, kill_grace=max(0.001, min(5, deadline - time.monotonic())), reap=lambda: None)
            require(ended["confirmed"], "cli_previous_unconfirmed")
    job.write("docker-cli.json", {"intent": list(argv)})
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
            child.wait(timeout=5)
            job.write("docker-cli.json", {**identity, "confirmed": True})


class DockerCLI:
    def __init__(self, job, manifest, retained, tree, *, execute=capture, now=time.monotonic, sleep=time.sleep, clock=time.time):
        self.manifest = manifest_gate(manifest, retained, tree)
        self.job, self.execute, self.now, self.sleep, self.clock = job, execute, now, sleep, clock
        self.plan = _read(job, "docker-plan.json")
        require(isinstance(self.plan, dict) and bool(self.plan.get("origin")), "launch_originals")   # absent, null, malformed or origin-less: no launch
        remaining = _deadline(job) - self.clock()   # the pinned order's absolute deadline, as time left now
        require(remaining > RESERVE_S, "backend_deadline_passed")
        self.absolute = now() + remaining
        self.deadline = self.absolute - RESERVE_S

    def _command(self, args, long=False):
        operation = args[1] if args[0] == "network" else args[0]
        require(args[0] in COMMANDS or (args[0] == "network" and operation in {"create", "connect", "disconnect", "inspect", "rm"}), "cli_command")
        mutation, logs = operation not in {"wait", "inspect", "info", "logs"}, args[0] == "logs"
        seconds = {"wait": 10, "logs": 10, "stop": 10, "kill": 10}.get(operation, 5)
        bound = (4 << 20) if logs else (4096 if operation in {"create", "start", "wait"} else 65536)
        # I/D: rehash at use; never resolve a tag or inherit Docker/proxy config.
        require(hashlib.sha256(Path(CLI).read_bytes()).hexdigest() == CLI_SHA, "cli_pin")
        argv = (CLI, "--host", "unix://" + SOCKET, *args)
        key = hashlib.sha256(json.dumps(args).encode()).hexdigest()
        journal = _read(self.job, "docker.json")   # absent after the attempt began is unknown, as is anything but an intact history
        require(journal is not None and journal is not False and _history(journal), "journal_unknown")
        if mutation:
            require(key not in journal, "mutation_already_intended")
            self.job.write("docker.json", {**journal, key: {"intent": list(argv)}})
        limit = self.now() + seconds
        deadline = self.deadline if long else limit if operation in {"logs", "stop", "kill", "rm"} else min(limit, self.deadline)
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
        network = self._command(("network", "create", "--internal", "--driver", "bridge", "--subnet", NETWORKS[role],
                                 "--opt", "com.docker.network.bridge.gateway_mode_ipv4=isolated", "gen2-2e1-live-" + role + "-" + generation)).strip().decode()
        require(CID.fullmatch(network), "network_identity")
        view = json.loads(self._command(("network", "inspect", network)))[0]
        require(view["Id"] == network and view["Internal"] and not view["EnableIPv6"] and view["Driver"] == "bridge", "network_inspect")
        require(view["IPAM"]["Config"] == [{"Subnet": NETWORKS[role]}] and not view["Containers"], "network_members")
        self.job.write("network-" + role + ".json", view)
        return network

    def endpoint(self, action, network, cid, ip=None):
        require(action in {"connect", "disconnect"} and CID.fullmatch(network) and CID.fullmatch(cid), "endpoint_identity")
        return self._command(("network", action, *(("--ip", ip) if ip else ()), network, cid))

    def create_runner(self, network, binds):
        require(CID.fullmatch(network) and set(binds) == {"out", "inputs", "seed"}, "runner_bindings")
        require(binds == self.plan.get("binds") and network == (self.job.read("network-job.json") or {}).get("Id"), "runner_originals")
        args = ["create", "--cidfile", str(self.job.dir / "runner.cid"), "--pull=never", "--restart=no", "--read-only",
                "--user", "10001:10001", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "64",
                "--memory", "1g", "--memory-swap", "1g", "--cpus", "1", "--ulimit", "fsize=16777216:16777216",
                "--ulimit", "nofile=256:256", "--ulimit", "core=0:0", "--dns", "127.0.0.1", "--ipc=private",
                "--cgroupns=private", "--no-healthcheck", "--log-driver", "local", "--log-opt", "max-size=4m",
                "--log-opt", "max-file=1", "--log-opt", "compress=false", "--network", network, "--ip", "172.31.254.3"]
        invocation = self.plan["origin"].get("invocation_id")
        require(isinstance(invocation, str) and re.fullmatch(r"[\w.:-]{1,256}", invocation), "runner_invocation")
        args.extend(("--env", "GEN2_INVOCATION_ID=" + invocation))   # the one variable the pinned runner image lacks and runner.launch reads; no credential, capability or token
        for name, size, mode in (("work", "128m", "0700"), ("auth/codex", "16m", "0700"), ("tmp", "64m", "1777"), ("run", "4m", "0700")):
            args.extend(("--tmpfs", f"/{name}:rw,nodev,nosuid,size={size},mode={mode},uid=10001,gid=10001"))
        for name, source in binds.items():
            require(Path(source).is_absolute() and "," not in source, "runner_bind_path")
            args.extend(("--mount", f"type=bind,src={source},dst=/{name}" + ("" if name == "out" else ",readonly")))
        args.append(self.manifest["images"]["runner"]["pin"])
        return self._create("runner", args)

    def _create(self, role, args):
        require(not (self.job.dir / (role + ".cid")).exists(), "cidfile_exists")
        cid = self._command(tuple(args)).strip().decode("ascii")
        found = read_scratch(self.job.dir, role + ".cid", 4096)
        require(CID.fullmatch(cid) and found["status"] == "present" and found["data"].strip() == cid.encode(), "create_identity")
        record, image = self.inspect(cid), self.manifest["images"]["engine" if role == "initializer" else role]
        require(record["Config"]["Image"] == image["pin"] and (image["kind"] == "repo-digest" or record["Image"] == image["pin"]), "create_inspect")
        self.job.write(role + ".json", record)
        return cid

    def inspect(self, cid):
        require(isinstance(cid, str) and CID.fullmatch(cid), "container_identity")
        records = json.loads(self._command(("inspect", cid)))
        require(isinstance(records, list) and len(records) == 1 and records[0].get("Id") == cid, "inspect_identity")
        return records[0]

    def runtime(self):
        """The dedicated daemon is the installed runtime this proof was qualified on, else no start."""
        info = json.loads(self._command(("info", "--format", "{{json .}}")))
        require(isinstance(info, dict) and all(info.get(k) == v for k, v in RUNTIME.items()) and all(
            (info.get(k) or {}).get("ID") == v for k, v in RUNTIME_IDS.items()), "runtime_identity")

    def start(self, cid, role="runner"):
        free_space(self.plan["paths"], 16 << 30)
        original = self.job.read(role + ".json")
        expected = self.plan.get("expected", {}).get(role)
        require(expected and set(expected) == {"Config", "HostConfig"} and all(original[section].get(key) == value
                for section, fields in expected.items() for key, value in fields.items()), "start_configuration")
        require(expected["HostConfig"].get("PidMode") == "" and original["HostConfig"].get("PidMode") == "", "start_pid_mode")   # private PID namespace, pinned by the plan: absence refuses
        require(_binding(self.inspect(cid)) == _binding(original), "start_identity")
        with self.job.hold(self.deadline, .01):   # the seal check and the start cannot interleave with the seal write
            require(read_scratch(self.job.dir, SEAL, 4096)["status"] == "absent", "start_after_seal")
            self._command(("start", cid))
        started = self.inspect(cid)
        expected = {v["Name"]: v["Id"] for v in (self.job.read(name) for name in ("network-job.json", "network-upstream.json")) if v}
        require(_binding(started) == _binding(_started(original, started, expected)), "start_changed")
        _when(started["State"].get("StartedAt"), "start_changed")
        self.job.write(role + "-start.json", started)

    def end(self, cid, role="runner"):
        """The one end proof: a bounded wait, then the SAME exact container's inspect must show it exited with no process and no runtime error."""
        waited = self._command(("wait", cid), long=role == "runner").strip()   # only the model turn waits long, up to the allowance; every other wait is short
        if role == "runner":
            self.deadline = self.absolute   # the model turn is over: its final inspect and the whole tail run under the order's deadline
        original, observed = self.job.read(role + "-start.json"), self.inspect(cid)
        require(original is not None, "end_original")
        require(_binding(observed) == _binding(original), "end_binding")
        state = observed["State"]
        require(state.get("StartedAt") == original["State"]["StartedAt"] and state.get("Status") == "exited" and type(state.get("Pid")) is int and state["Pid"] == 0
                and state.get("Error") == "" and all(state.get(k) is False for k in ("Running", "Restarting", "Paused", "OOMKilled")), "end_state")
        require(_when(state.get("FinishedAt"), "end_state") >= _when(original["State"]["StartedAt"], "end_state"), "end_state")
        require(type(state.get("ExitCode")) is int and waited == str(state["ExitCode"]).encode(), "end_unconfirmed")
        self.job.write(role + "-end.json", observed)
        return observed

    def _end_egress(self, network, cid, ended):
        """Prove the original pair is clear before publishing any reusable end."""
        with self.job.hold(self.deadline, .01):
            original = self.job.read("network-upstream.json")
            approval = self.plan["egress"]
            name = approval["name"]
            ipam = {"Subnet": approval["subnet"], "Gateway": approval["gateway"]}
            subnet = IPv4Network(ipam["Subnet"])
            relay_ip = str(subnet[2])
            expected = _binding(ended)
            expected[1].pop(name, None)
            receipt = {"network_id": network, "relay_id": cid, "confirmed": False}
            try:
                for phase in ("before", "after"):
                    pair = receipt[phase] = {}
                    views = json.loads(self._command(("network", "inspect", network)))
                    require(isinstance(views, list) and len(views) == 1 and isinstance(views[0], dict), "egress_inspect")
                    bridge = pair["bridge"] = views[0]
                    relay = self.inspect(cid)
                    networks = pair["relay_networks"] = relay["NetworkSettings"]["Networks"]
                    binding = _binding(relay)
                    binding[1].pop(name, None)
                    require(binding == expected and relay["State"] == ended["State"], "egress_relay_changed")
                    members, endpoint = bridge.get("Containers"), networks.get(name)
                    require(bridge["Id"] == network and bridge["Name"] == name
                            and bridge["Driver"] == "bridge" and bridge["Scope"] == "local" and bridge["Internal"] is False
                            and bridge["EnableIPv4"] is True and bridge["EnableIPv6"] is False and bridge["IPAM"]["Config"] == [ipam]
                            and bridge["Options"].get("com.docker.network.bridge.gateway_mode_ipv4") == "nat", "egress_bridge_properties")
                    require({k: v for k, v in bridge.items() if k not in {"Containers", "Status"}} ==
                            {k: v for k, v in original.items() if k not in {"Containers", "Status"}}, "egress_bridge_changed")
                    require(isinstance(members, dict) and set(members) <= {cid}, "egress_members")
                    absent = name not in networks or (endpoint["NetworkID"] == network and endpoint["EndpointID"] == ""
                                                      and endpoint["IPAddress"] == "" and endpoint["GlobalIPv6Address"] == "")
                    if phase == "before" and members:
                        endpoint_id = self.job.read("relay-start.json")["NetworkSettings"]["Networks"][name]["EndpointID"]
                        require(endpoint and endpoint["NetworkID"] == network and members[cid]["IPv4Address"] == f"{relay_ip}/{subnet.prefixlen}"
                                and CID.fullmatch(endpoint_id) and endpoint["EndpointID"] == members[cid]["EndpointID"] == endpoint_id
                                and endpoint["IPAddress"] == relay_ip, "egress_endpoint")
                        self.endpoint("disconnect", network, cid)
                    else:
                        require(not members and absent, "egress_not_empty")
                receipt["confirmed"] = True
            finally:
                self.job.write("containment.json", {"egress": receipt})

    def close_admission(self):
        """The sole launcher's own durable seal, after the last permitted start; every later start refuses it. A failed write contains and keeps uncertainty."""
        with self.job.hold(self.deadline, .01):
            self.job.write(SEAL, {"origin": self.plan["origin"]})

    def drain(self):
        """The fixed grace after ingress closes: bounded waiting on the monotonic clock, refused if it overran or was cut short."""
        before = self.now()
        self.sleep(DRAIN_SECONDS)
        require(self.now() - before <= DRAIN_LIMIT, "relay_drain")

    def logs(self, cid):
        require((self.job.read("runner-end.json") or {}).get("Id") == cid, "logs_before_end")
        require(self.job.read("runner-logs.json") is None, "logs_already_intended")
        self.job.write("runner-logs.json", {"intent": cid})
        return self._command(("logs", cid))

    def contain(self, cid, *, kill=False, role="runner"):
        require((self.job.read(role + ".json") or {}).get("Id") == cid, "contain_original")
        return self._command(("kill", cid) if kill else ("stop", "--time", "5", cid))

    def create_auxiliary(self, role, network=None):
        require(role in {"initializer", "relay"}, "auxiliary_role")
        generation, slots = self.plan["generation"], self.plan["slots"]
        require(re.fullmatch(r"[0-9a-f]{32}", generation), "auxiliary_generation")
        require(set(slots) == {"out", "evidence"}, "auxiliary_slots")
        require(role == "initializer" or network == (self.job.read("network-job.json") or {}).get("Id"), "relay_network")
        args = ["create", "--cidfile", str(self.job.dir / (role + ".cid")), "--pull=never", "--restart=no", "--read-only",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "32", "--memory", "128m",
                "--memory-swap", "128m", "--cpus", ".25", "--no-healthcheck", "--ipc=private", "--cgroupns=private",
                "--log-driver", "local", "--log-opt", "max-size=4m", "--log-opt", "max-file=1", "--log-opt", "compress=false",
                "--tmpfs", "/tmp:rw,nodev,nosuid,size=16m,mode=0700,uid=10001,gid=10001", "--network", "none" if role == "initializer" else network]
        real = self.plan.get("route") == "real"
        require(role == "initializer" or {k for k in RELAY_PROVIDER if k in self.plan} == (set(RELAY_PROVIDER) if real else set()), "relay_provider_files")
        mounts = slots if role == "initializer" else {"evidence": str(Path(slots["evidence"]) / generation), "etc/nginx/nginx.conf": self.plan["relay_config"],
                                                      **{dst: self.plan[key] for key, dst in RELAY_PROVIDER.items() if key in self.plan}}
        for name, source in mounts.items():
            require(Path(source).is_absolute() and "," not in source, "auxiliary_bind_path")
            args.extend(("--mount", f"type=bind,src={source},dst=/{name}" + (",readonly" if name.startswith("etc/") else "")))
        if role == "initializer":
            args.extend(("--user", "0:0", "--cap-add", "CHOWN", "--entrypoint", "/usr/local/bin/python",   # the engine image's own ENTRYPOINT is gen2.app.engine
                         self.manifest["images"]["engine"]["pin"], "-m", "gen2.supervisor.docker_cli", generation))
        else:   # an explicit command: the image's CMD (`nginx -g "daemon off;"`) would duplicate the directive the mounted conf already carries
            args.extend(("--user", "10001:10001", "--sysctl", "net.ipv4.ip_forward=0", "--ip", "172.31.254.2", self.manifest["images"]["relay"]["pin"],
                         "nginx", "-c", "/etc/nginx/nginx.conf"))
        return self._create(role, args)

    def run(self, batch):
        """I/L/E: supervised finite lane; the end proof is the daemon's own final inspect, raw evidence only. The plan's route (it must be the manifest's) selects the
        fixture lane or the real one: a real lane has no fixture container, joins the relay to the plan's persistent egress bridge BY ID, and
        classifies against the plan's upstream. Any partial start is contained (every journaled CID killed and removed) before the error leaves."""
        route = self.plan.get("route", "fixture")
        real = route == "real"
        require(route == self.manifest["route"], "plan_route")
        if real:
            validate_egress(self.plan.get("egress"))
        require(self.plan["binds"]["out"] == str(Path(self.plan["slots"]["out"]) / self.plan["generation"]), "backend_output_generation")
        identity = self.job.read("identity.json")
        require(identity is not None and os.getpid() in jobs.members(identity), "backend_unsupervised")
        with self.job.hold(self.deadline, .01):   # the one fresh-attempt transition: the intact-empty history and the attempt marker are born together, only if truly absent
            require(_read(self.job, "docker-complete.json") is None, "backend_already_complete")   # an end fact in ANY state (valid, null, list, malformed) means no further attempt
            require(_read(self.job, "docker-attempt.json") is None, "backend_already_intended")   # present (valid or not) is a started attempt, never rewritten
            if _read(self.job, "docker.json") is None:
                self.job.create("docker.json", {})
            self.job.write("docker-attempt.json", {"origin": self.plan["origin"]})
        try:
            return self._run(batch, real)
        except BaseException:
            contain_job(self.job, execute=self.execute, now=self.now, clock=self.clock)   # whatever was started is ended before the failure leaves; a failure here refuses louder
            raise

    def _run(self, batch, real):
        self.runtime()
        initializer = self.create_auxiliary("initializer")
        self.start(initializer, "initializer")
        require(self.end(initializer, "initializer")["State"]["ExitCode"] == 0, "initializer_failed")
        output = "judgment" if self.plan.get("output") == "judgment" else "outcome"
        network = self.network(self.plan["generation"])
        if real:
            upstream = self.plan["egress"]["network_id"]
            view = json.loads(self._command(("network", "inspect", upstream)))[0]
            require(view["Id"] == upstream and not view["Internal"] and not view["Containers"], "egress_original")   # the persistent bridge, empty between jobs
        else:   # the fixture's network is lane C's, per attempt: the fixture was created ON it at .3 (a `none`-mode container can join nothing), and only the relay joins
            fixture = self.plan["fixture"]
            mounts = [m for m in fixture.get("Mounts", []) if m.get("Destination") == "/evidence"]
            require(len(mounts) == 1 and mounts[0].get("Type") == "bind", "fixture_evidence_mount")
            fixture_directory = Path(mounts[0]["Source"])
            require(fixture_directory.parent == Path(self.plan["slots"]["evidence"]) and re.fullmatch(r"[0-9a-f]{32}", fixture_directory.name), "fixture_evidence_mount")
            require(not fixture["HostConfig"].get("Binds") and [m for m in fixture["HostConfig"].get("Mounts", []) if m.get("Target") == "/evidence"] ==
                    [{"Type": "bind", "Source": str(fixture_directory), "Target": "/evidence"}], "fixture_evidence_mount")
            require(fixture["HostConfig"].get("PidMode") == "" and fixture["HostConfig"].get("RestartPolicy") == {"Name": "no", "MaximumRetryCount": 0}, "fixture_runtime")
            _when(fixture["State"].get("StartedAt"), "fixture_original")
            self.job.write("fixture.json", fixture)
            self.job.write("fixture-start.json", fixture)
            live = self.inspect(fixture["Id"])
            require(_binding(live) == _binding(fixture), "fixture_original")
            require([(m.get("Type"), m.get("Source")) for m in live.get("Mounts", []) if m.get("Destination") == "/evidence"] == [("bind", str(fixture_directory))], "fixture_evidence_mount")   # the daemon's effective mount, not only the plan's two representations
            members = list(fixture["NetworkSettings"]["Networks"].values())
            require(len(members) == 1 and (members[0].get("IPAMConfig") or {}).get("IPv4Address") == "172.31.252.3" and CID.fullmatch(str(members[0].get("NetworkID"))), "fixture_network")
            upstream = members[0]["NetworkID"]
            view = json.loads(self._command(("network", "inspect", upstream)))[0]
            require(view["Id"] == upstream and view["Internal"] and not view["EnableIPv6"] and view["Driver"] == "bridge"
                    and view["IPAM"]["Config"] == [{"Subnet": NETWORKS["fixture"]}] and set(view["Containers"]) == {fixture["Id"]}, "fixture_network_members")
        originals = {}
        for kind, directory in {output: Path(self.plan["binds"]["out"]), "access": Path(self.plan["slots"]["evidence"]) / self.plan["generation"],
                                **({"fixture": fixture_directory} if not real else {})}.items():
            with _generation_open():
                fd = slot(str(directory))
            try:
                info = os.fstat(fd)
                originals[kind] = (info.st_dev, info.st_ino)
            finally:
                os.close(fd)
        self.job.write("docker-generations.json", originals)
        self.job.write("network-upstream.json", view)   # its Name pairs the expected ID with the per-name view the daemon shows before start
        relay = self.create_auxiliary("relay", network)
        self.endpoint("connect", upstream, relay, None if real else "172.31.252.2")
        observed = self.inspect(relay)
        require(_binding(observed)[0] == _binding(self.job.read("relay.json"))[0], "relay_changed")
        shown, names = observed["NetworkSettings"]["Networks"], {self.job.read("network-job.json")["Name"]: network, view["Name"]: upstream}
        address = lambda name: (shown[name].get("IPAMConfig") or {}).get("IPv4Address")
        require(set(shown) == set(names) and all(shown[n].get("NetworkID") in ("", i) for n, i in names.items())   # created, not started: by name, no ID yet
                and address(next(iter(names))) == "172.31.254.2" and (real or address(view["Name"]) == "172.31.252.2"), "relay_topology")
        self.job.write("relay.json", observed)
        self.start(relay, "relay")
        runner = self.create_runner(network, self.plan["binds"])
        self.start(runner)
        started = self.now()
        self.close_admission()
        ended = self.end(runner)
        elapsed = self.now() - started
        self.endpoint("disconnect", network, runner)
        view = json.loads(self._command(("network", "inspect", network)))[0]
        require(view["Id"] == network and set(view["Containers"]) == {relay}
                and network not in {n["NetworkID"] for n in self.inspect(runner)["NetworkSettings"]["Networks"].values()}, "ingress_not_closed")
        self.drain()
        self.contain(relay, role="relay")
        relay_end = self.end(relay, "relay")
        if real:
            self._end_egress(upstream, relay, relay_end)
        require(relay_end["State"]["ExitCode"] == 0, "relay_stop_failed")
        refs = []
        if not real:
            self.contain(fixture["Id"], role="fixture")
            self.end(fixture["Id"], "fixture")
            fd = slot(self.plan["slots"]["evidence"])
            try:
                refs.append(batch.collect(fd, fixture_directory.name, originals["fixture"], writers_ended=True, kind="fixture"))
            finally:
                os.close(fd)
        refs.extend(batch.stage(data, "application/octet-stream", kind) for kind, data in zip(("events", "diagnostics"), self.logs(runner)))
        code = ended["State"]["ExitCode"]
        for kind, name in ((output, "out"), ("access", "evidence")):
            if kind == "judgment" and code != 0:
                continue   # a failed run's answer file is never opened: success is exit 0 plus a non-empty answer, collected below
            fd = slot(self.plan["slots"][name])
            try:
                refs.append(batch.collect(fd, self.plan["generation"], originals[kind], writers_ended=True, kind=kind))
            finally:
                os.close(fd)
        held = batch.held
        disposition = rejection.classify(held["access"], held.get("fixture"), code, model=MODEL,
                                         route="real" if real else "fixture", upstream=self.plan.get("upstream"))
        try:   # usage is optional normalization: the classified disposition and the raw references are retained whether or not it can be built
            refs.append(batch.stage(json.dumps(rejection.usage_record(
                {"origin": self.plan["origin"]}, held["events"], elapsed=elapsed, gateway_refs=[], raw_refs=list(refs),
                observed_model=None if real else _observed_model(held["fixture"]), configured_model=MODEL, observed=not real), sort_keys=True).encode(), "application/json"))
            usage = "recorded"
        except LiveProfileRefused:
            usage = "refused"
        require(self.job.create("docker-complete.json", {"origin": self.plan["origin"], "refs": refs, "disposition": disposition, "usage": usage}), "backend_already_complete")   # create-only: an existing end fact is retained
        return refs

    def remove(self, cid, ack):
        require(ack and (self.job.read("runner-end.json") or {}).get("Id") == cid, "remove_before_ack")
        return self._command(("rm", cid))


def _deadline(job):
    """The pinned order's absolute deadline, in epoch seconds."""
    try:
        return utc_instant_ns((job.read("order.json") or {}).get("deadline_at")) / 1e9
    except (OSError, ValueError):
        raise LiveProfileRefused("backend_deadline_missing") from None


def _observed_model(fixture):
    """The one model the fixture saw in the actual requests, else None (the usage record then refuses)."""
    try:
        models = {request.get("model") for request in json.loads(fixture)["requests"]}
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return models.pop() if len(models) == 1 else None


def free_space(paths, floor):
    require(bool(paths), "free_space_paths")
    for path in paths:
        info = os.statvfs(path)
        require(info.f_bavail * info.f_frsize >= floor, "free_space_floor")


@contextlib.contextmanager
def _generation_open():
    """A generation directory that is a link or no directory is not the original: the collection refusal, before anything is staged. Any other OS error is infrastructure and escapes."""
    try:
        yield
    except OSError as error:
        if error.errno in (errno.ENOTDIR, errno.ELOOP):
            raise LiveProfileRefused("collection_generation") from None
        raise


def slot(path):
    """Pin every fixed ancestor without following links; caller retains the fd."""
    require(Path(path).is_absolute(), "slot_absolute")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in Path(path).parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


class EvidenceBatch:
    """E: enforced aggregate cap, including channels and all fixed files."""
    def __init__(self, spool, topic):
        require(spool.quota_bytes <= 64 << 20, "evidence_spool_quota")
        self.spool, self.topic, self.used, self.held = spool, topic, 0, {}

    def stage(self, data, media, kind=None):
        require(self.used + len(data) <= BATCH, "collection_batch_cap")
        free_space([self.spool.root], (2 << 30) + self.used + len(data))
        ref = self.spool.stage(self.topic, data, media)
        self.used += len(data)
        if kind:
            self.held[kind] = data  # bytes the classifier reads; the same bytes that were published
        return ref

    def collect(self, slot_fd, generation, identity, *, writers_ended, kind="outcome"):
        require(writers_ended, "collection_writers_live")
        require(re.fullmatch(r"[0-9a-f]{32}", generation), "collection_generation")
        name, bound, media = {"outcome": ("outcome.json", 16 << 20, "application/json"),
                              "access": ("access.jsonl", 16 << 20, "application/x-ndjson"),
                              "fixture": ("fixture.json", 1 << 20, "application/json"),
                              "judgment": ("judgment.json", 1 << 20, "application/json")}[kind]   # the live agent's one output; the plan chooses, the caller names no file
        with _generation_open():
            fd = os.open(generation, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=slot_fd)
        try:
            info = os.fstat(fd)
            require((info.st_dev, info.st_ino) == identity, "collection_identity")
            found = read_scratch(fd, name, bound)
            after = os.stat(generation, dir_fd=slot_fd, follow_symlinks=False)
            require((after.st_dev, after.st_ino) == identity, "collection_replaced")
            require(found["status"] == "present", "collection_" + found["status"])
            return self.stage(found["data"], media, kind)
        finally:
            os.close(fd)


def initialize(generation):
    """I: exclusive original generations, no credentials or networking."""
    require(re.fullmatch(r"[0-9a-f]{32}", generation), "initialize_generation")
    for root in ("/out", "/evidence"):
        directory = Path(root) / generation
        directory.mkdir(mode=0o700)
        if root == "/evidence":
            fd = os.open(directory / "access.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.fchown(fd, 10001, 10001)
            os.close(fd)
        os.chown(directory, 10001, 10001)


if __name__ == "__main__":
    import sys
    initialize(sys.argv[1])


class ContainFailed(LiveProfileRefused):
    """At least one journaled container could not be shown ended; `outcomes` has every attempt, the failures included."""

    def __init__(self, outcomes: list[dict]) -> None:
        super().__init__("contain_failed")
        self.outcomes = outcomes


def contain_job(job, *, execute=capture, now=time.monotonic, clock=time.time) -> list[dict]:
    """Kill and remove every original this attempt has, from the one place both the failed child and the supervisor's deadline or cancellation
    end: the relay FIRST (the only sender; a runner that will not die must not leave it running), then the runner, the initializer and, on a
    fixture route, the protected plan's fixture (its ID from the plan: a route that owes one without it is unknown). EVERY role is attempted, kill and
    removal independently, whatever happened to the others, and each outcome is journaled in `containment.json`. A container already gone is
    fine. A role with no cidfile is `never_created` only if the mutation journal shows no create for it, else `created_unrecorded`. A global
    trust failure (the CLI pin) stops everything; any other failure is raised AFTER all attempts as `ContainFailed`. When every role is ended or
    was never created and the relay's removal came within LATE_END_S of the order's deadline, the end fact `docker-complete.json` is published
    create-only (it cannot replace a normal one), its disposition unknown. Returns the outcomes."""
    start, wall, outcomes = now(), clock(), []
    plan, journal, attempt = _read(job, "docker-plan.json"), _read(job, "docker.json"), _read(job, "docker-attempt.json")
    # Before the attempt transition (no marker, no history: e.g. a `backend_unsupervised` refusal) nothing could have been created, so the backend roles are
    # never_created. From the marker on, only an intact history proves an absence: absent, null or malformed history, or an invalid marker, is unknown.
    unknown = (journal is False or (journal is not None and not _history(journal)) or attempt is False
               or (attempt is not None and (journal is None or not attempt.get("origin"))))
    failed = plan is False or unknown or _read(job, "docker-complete.json") is False   # a present-invalid end fact is no end, and is never replaced
    for role in ("relay", "runner", "initializer", "fixture"):
        if role == "fixture":
            if not plan or plan.get("route", "fixture") == "real":
                continue   # no plan, or a real route: there is no fixture to end
            found = {"status": "present", "data": str((plan.get("fixture") or {}).get("Id")).encode()}
        else:
            found = read_scratch(job.dir, role + ".cid", 4096)
        entry = {"role": role, "cid": None, "kill": "not_attempted", "rm": "not_attempted"}
        outcomes.append(entry)
        if found["status"] == "absent":   # a create that was journaled without its cidfile is an unknown end, not a clean absence
            created = unknown or any(str(job.dir / (role + ".cid")) in v["intent"] for v in (journal or {}).values())
            entry["kill"] = entry["rm"] = "created_unrecorded" if created else "never_created"
            failed = failed or created
            continue
        cid = found["data"].strip().decode("ascii", "replace") if found["status"] == "present" else ""
        if not CID.fullmatch(cid):
            entry["kill"] = entry["rm"] = "journal_unreadable"
            failed = True
            continue
        entry["cid"] = cid
        try:
            require(hashlib.sha256(Path(CLI).read_bytes()).hexdigest() == CLI_SHA, "cli_pin")   # the pinned CLI only; a failure here is not retried around
        except OSError:
            raise LiveProfileRefused("cli_pin") from None
        for step, args in (("kill", ("kill", cid)), ("rm", ("rm", "-f", cid))):
            try:
                code, out, err = execute(job, (CLI, "--host", "unix://" + SOCKET, *args), {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                                         "DOCKER_CONFIG": str(job.dir / "docker-config")}, now() + 10, (65536, 4096))
            except (OSError, LiveProfileRefused):
                entry[step], failed = "error", True
                continue
            gone = b"No such container" in err or b"is not running" in err
            entry[step] = "ok" if code == 0 else "gone" if gone else "failed"
            failed = failed or entry[step] == "failed"
        entry["at"] = now()
    record = _read(job, "docker-cli.json")   # read after the attempts: a recovery inside them may have resolved it
    failed = failed or (record is not None and not (_identity(record) and record.get("confirmed") is True))   # an unresolved CLI (intent only, malformed, unreadable or unconfirmed) keeps the end unknown even when no original is recorded
    try:   # the monotonic instant LATE_END_S past the order's deadline, from the wall clock read at entry
        limit = start + _deadline(job) - wall + LATE_END_S
    except LiveProfileRefused:
        limit = None
    late = limit is None or any(e["role"] == "relay" and e.get("at", start) > limit for e in outcomes)
    record = {"outcomes": outcomes, "limit": limit, "late": late}
    if plan and plan.get("route") == "real":
        receipt = (_read(job, "containment.json") or {}).get("egress")
        if receipt is not None:
            record["egress"] = receipt
        # A connect intent can have taken effect even if the CLI never reported success.
        for entry in (journal or {}).values() if not unknown else ():
            intent = entry["intent"]
            if intent[3:5] == ["network", "connect"]:
                failed = failed or not (isinstance(receipt, dict) and receipt.get("confirmed") is True
                                        and [receipt.get("network_id"), receipt.get("relay_id")] == intent[-2:])
    job.write("containment.json", record)
    if failed:
        raise ContainFailed(outcomes)
    if plan and plan.get("origin") and not late:
        job.create("docker-complete.json", {"origin": plan["origin"], "refs": [], "usage": "refused",
                                            "disposition": {"disposition": "unknown", "reason": "contained_without_collection"}})
    return outcomes


def _history(journal):
    """Whether a mutation journal is an object whose every entry is an object with a non-empty list of strings as its `intent`."""
    return isinstance(journal, dict) and all(isinstance(v, dict) and isinstance(v.get("intent"), list) and bool(v["intent"]) and all(isinstance(a, str) for a in v["intent"])
                                             for v in journal.values())


def _read(job, name):
    """A file's object, None only when truly absent; False when present but unreadable or not an object (an unknown, never an absence)."""
    try:
        return job.read(name)
    except (OSError, ValueError):
        return False
