"""The live agent step: the child runs `DockerCLI` for its own job and carries the one judgment file back to `job.run`.

Trace: Gate S #7b §5 (child adapter); Astra LH-2 (name the trusted collaborators, publish evidence without handing the child Router authority),
LH-3; the T17 brief (no alternate runner). Oracle: `DockerCLI.run`'s own checks and its `docker-complete.json`. Limits: the end proof is the
backend's own (the daemon's final inspect, a durable admission seal and a bounded drain; Gate S #7c), so no host observer or mailbox exists. The child holds no spool and no Router handle: its
raw evidence is set aside as scratch files that the supervisor stages (core.evidence_media), and the judgment bytes are what `job.run` validates.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

from gen2.core import canonical
from gen2.core.evidence_media import evidence_name
from gen2.exec.common import Refused
from gen2.supervisor import docker_cli, jobs
from gen2.supervisor.isolation import LiveProfileRefused


class CredentialsRejected(Refused):
    """The backend classified the end as a rejected credential: the child exits 1, which is what the Router's rejection evidence requires."""


class ScratchBatch(docker_cli.EvidenceBatch):
    """The evidence batch with no spool: each collected or logged file is set aside in scratch under its digest, bounded, for the supervisor to stage."""

    def __init__(self, directory: Path) -> None:
        self.directory, self.used, self.held = Path(directory), 0, {}

    def stage(self, data: bytes, media: str, kind: str | None = None) -> dict:
        docker_cli.require(self.used + len(data) <= docker_cli.BATCH, "collection_batch_cap")
        try:
            name = evidence_name(canonical.bytes_digest(data), media)
        except ValueError:
            raise LiveProfileRefused("evidence_media") from None
        (self.directory / name).write_bytes(data)
        self.used += len(data)
        if kind:
            self.held[kind] = data
        return {"content_hash": canonical.bytes_digest(data), "size_bytes": len(data), "media_type": media}


def agent_for(directory: Path, env: Mapping[str, str], *, execute=docker_cli.capture):
    """The live agent for a live job (one whose job directory holds a plan), or a refusal naming what is missing. Everything it needs is a protected
    path the driver placed in the order's environment: the manifest and the retained configuration directory."""
    job = jobs.Job(Path(directory).parent.parent, Path(directory).parent.name)
    plan = job.read("docker-plan.json")
    names = ("GEN2_MANIFEST", "GEN2_RETAINED_DIR")
    if plan is None:
        raise Refused("the live runner entrance is closed: a model purpose needs an injected agent step")
    if not all(env.get(name) for name in names):
        raise Refused("the live backend's protected paths are not set")
    manifest = canonical.parse_json_strict(Path(env["GEN2_MANIFEST"]).read_bytes())
    retained_dir = Path(env["GEN2_RETAINED_DIR"])
    retained = lambda pin: (retained_dir / pin.removeprefix("sha256:")).read_bytes()

    def agent(prompt: bytes, raw_input: bytes, out: Path) -> int:
        batch = ScratchBatch(directory)
        try:
            docker_cli.DockerCLI(job, manifest, retained, manifest.get("tree"), execute=execute).run(batch)
        except LiveProfileRefused as refused:
            raise Refused(f"the live backend refused: {refused}") from None
        if job.read("docker-complete.json")["disposition"]["disposition"] == "credentials_rejected":
            raise CredentialsRejected("credentials rejected")
        if "judgment" not in batch.held:
            raise Refused("the live run produced no judgment")
        (out / "judgment.json").write_bytes(batch.held["judgment"])
        return 0
    return agent
