"""The live agent step: the child runs `DockerCLI` for its own job and carries the one judgment file back to `job.run`.

Trace: Gate S #7b §5 (child adapter); Astra LH-2 (name the trusted collaborators, publish evidence without handing the child Router authority),
LH-3; the T17 brief (no alternate runner). Oracle: `DockerCLI.run`'s own checks and its `docker-complete.json`. Limits: the observers are NOT
written here. `close_admission`, `descendants_ended` and `drain` are answered by lane C's host-side observer through a host-owned read-only
response directory; `Mailbox` is only the in-engine side of that exchange and answers True only on a matching host answer, never by default.
With no observers configured the agent refuses `observers_unavailable` and writes nothing. The child holds no spool and no Router handle: its
raw evidence is set aside as scratch files that the supervisor stages (core.evidence_media), and the judgment bytes are what `job.run` validates.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Callable, Mapping

from gen2.core import canonical
from gen2.core.evidence_media import evidence_name
from gen2.exec.common import Refused
from gen2.supervisor import docker_cli, jobs
from gen2.supervisor.isolation import LiveProfileRefused
from gen2.supervisor.spool import read_scratch


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


class Mailbox:
    """The in-engine side of the host-side observer: requests go to a directory the host reads, answers come back through a host-owned read-only
    response directory keyed by nonce, attempt and the original CID. No answer, a malformed one, or one for another key is `False`."""

    def __init__(self, requests: Path, responses: Path, nonce: str, attempt: int, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self.requests, self.responses, self.nonce, self.attempt, self._sleep = Path(requests), Path(responses), nonce, attempt, sleep

    def _ask(self, op: str, cid: str | None) -> None:
        name = f"{self.nonce}-{self.attempt}-{cid or 'attempt'}-{op}.json"
        (self.requests / name).write_bytes(canonical.canonical_bytes({"op": op, "nonce": self.nonce, "attempt": self.attempt, "cid": cid}))

    def _answer(self, op: str, cid: str | None) -> Mapping | None:
        found = read_scratch(self.responses, f"{self.nonce}-{self.attempt}-{cid or 'attempt'}-{op}.json", 4096)
        try:
            doc = canonical.parse_json_strict(found["data"]) if found["status"] == "present" else None
        except ValueError:
            return None
        return doc if isinstance(doc, dict) and (doc.get("nonce"), doc.get("attempt"), doc.get("cid"), doc.get("op")) == (self.nonce, self.attempt, cid, op) else None

    def close_admission(self) -> None:
        self._ask("close_admission", None)   # registers this one attempt against any further start; no Router write

    def descendants_ended(self, original: Mapping) -> bool:
        cid = original["Id"]
        self._ask("ended", cid)
        answer = self._answer("ended", cid)
        return bool(answer and answer.get("ended") is True)

    def drain(self, seconds: float) -> bool:
        self._ask("drain", None)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            answer = self._answer("drain", None)
            if answer is not None:
                return answer.get("drained") is True
            self._sleep(0.2)
        return False


def agent_for(directory: Path, env: Mapping[str, str], *, execute=docker_cli.capture):
    """The live agent for a live job (one whose job directory holds a plan), or a refusal naming what is missing. Everything it needs is a protected
    path the driver placed in the order's environment: the manifest, the retained configuration directory and the observer mailbox."""
    job = jobs.Job(Path(directory).parent.parent, Path(directory).parent.name)
    plan = job.read("docker-plan.json")
    names = ("GEN2_MANIFEST", "GEN2_RETAINED_DIR", "GEN2_MAILBOX_REQUESTS", "GEN2_MAILBOX_RESPONSES")
    if plan is None:
        raise Refused("the live runner entrance is closed: a model purpose needs an injected agent step")
    if not all(env.get(name) for name in names):
        raise Refused("observers_unavailable")
    manifest = canonical.parse_json_strict(Path(env["GEN2_MANIFEST"]).read_bytes())
    retained_dir = Path(env["GEN2_RETAINED_DIR"])
    retained = lambda pin: (retained_dir / pin.removeprefix("sha256:")).read_bytes()
    mailbox = Mailbox(Path(env["GEN2_MAILBOX_REQUESTS"]), Path(env["GEN2_MAILBOX_RESPONSES"]), plan["generation"], 1)

    def agent(prompt: bytes, raw_input: bytes, out: Path) -> int:
        batch = ScratchBatch(directory)
        try:
            docker_cli.DockerCLI(job, manifest, retained, manifest.get("tree"), execute=execute).run(
                mailbox.close_admission, mailbox.descendants_ended, lambda: None, mailbox.drain, batch)
        except LiveProfileRefused as refused:
            raise Refused(f"the live backend refused: {refused}") from None
        if job.read("docker-complete.json")["disposition"]["disposition"] == "credentials_rejected":
            raise CredentialsRejected("credentials rejected")
        if "judgment" not in batch.held:
            raise Refused("the live run produced no judgment")
        (out / "judgment.json").write_bytes(batch.held["judgment"])
        return 0
    return agent
