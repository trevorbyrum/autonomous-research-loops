"""The executor child: the process a supervised order runs, and the helper that sets evidence aside for the supervisor.

Trace: 2e2-min design §1.2; ticket plan wrapper contract (`inputs/prompt.md` and `inputs/input.json` read-only, `out/judgment.json`
written, exit 0 = ran, `outcome.json` in the job's scratch for the supervisor to collect); Astra T11 decision 7 and the T17 brief
(no alternate live runner). Oracle: exec.job.run's digest and judgment checks and the judgment schemas. Limits: the agent step is
injected. Offline it is T18's fixture agent; live there is none, because the productive runner entrance is closed (isolation.py)
until the qualification lane opens it, so a model purpose without an agent refuses and writes nothing. The code-only dossier
purpose needs no agent. The directory is the job's scratch: the executor's working directory, where the driver wrote `inputs/`,
and where the supervisor collects `outcome.json` and the `evidence-<sha256>.json` files; there is one location and no copy.
Discovery has its own child (gen2.discovery.child). The builder table is filled by the composition as the kits land.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence

from gen2.app import factories
from gen2.core import canonical
from gen2.core.evidence_media import EVIDENCE_MEDIA, evidence_name
from gen2.exec import job
from gen2.exec.common import Refused
from gen2.router.schemas import SchemaSet

JUDGMENT = {"research_pass/scope": "judgment-scope", "research_pass/research": "judgment-research", "verification/verify": "judgment-verify",
            "checkpoint/challenge": "judgment-challenge", "checkpoint/review": "judgment-review"}
CODE_ONLY = ("checkpoint/dossier",)
Stage = Callable[[bytes, str], Mapping]
BytesOf = Callable[[str], bytes]
Factory = Callable[[Stage, BytesOf], job.Builder]


def evidence_stage(directory: Path) -> Stage:
    """Stage by setting the bytes aside in `directory` as `evidence-<sha256 hex><ext>` (core.evidence_media: JSON or text, the
    extension fixing the media), the only form the supervisor stages. The caller names no path; the returned ref is the bytes' own."""
    def stage(data: bytes, media_type: str) -> dict:
        try:
            name = evidence_name(canonical.bytes_digest(data), media_type)
        except ValueError as error:
            raise Refused(str(error)) from None
        (Path(directory) / name).write_bytes(data)
        return {"content_hash": canonical.bytes_digest(data), "size_bytes": len(data), "media_type": media_type}
    return stage


def bytes_of(directory: Path) -> BytesOf:
    """The retained bytes a view names by hash, read from the evidence files the driver set aside, each checked against its name."""
    def read(content_hash: str) -> bytes:
        for extension in EVIDENCE_MEDIA:
            path = Path(directory) / f"evidence-{content_hash.removeprefix('sha256:')}{extension}"
            if path.is_file() and not path.is_symlink():
                data = path.read_bytes()
                if canonical.bytes_digest(data) != content_hash:
                    raise Refused(f"{path.name} does not hash to its name")
                return data
        raise Refused(f"no retained bytes were set aside for {content_hash}")
    return read


def validator(key: str, schemas: SchemaSet | None = None) -> Callable[[str, object], None]:
    """job.run calls this with the bare purpose; the schema is the order's own kind/purpose."""
    schemas = schemas or SchemaSet()

    def validate(_purpose: str, judgment: object) -> None:
        errors = schemas.errors(judgment, JUDGMENT[key] + ".schema.json")
        if errors:
            raise Refused(f"the judgment does not fit {JUDGMENT[key]}: {errors[0]}")
    return validate


def _no_judgment(prompt: bytes, raw_input: bytes, out: Path) -> int:
    (out / job.JUDGMENT).write_bytes(b"{}")   # a code-only purpose has no model; job.run's own checks still apply
    return 0


def run(key: str, directory: Path, *, input_digest: str, table: Mapping[str, Factory] | None = None,
        agent: job.Agent | None = None, validate: Callable[[str, object], None] | None = None) -> Path:
    """Run one order's purpose in `directory` and return the written outcome.json path."""
    factory = (factories.TABLE if table is None else table).get(key)
    if factory is None:
        raise Refused(f"no builder is installed for {key}")
    code_only = key in CODE_ONLY
    if agent is None and not code_only:
        raise Refused("the live runner entrance is closed: a model purpose needs an injected agent step")
    kind, purpose = key.split("/")
    return job.run(purpose, Path(directory), input_digest=input_digest, agent=_no_judgment if code_only else agent,
                   builder=factory(evidence_stage(Path(directory)), bytes_of(Path(directory))), validate=(lambda *_: None) if code_only else (validate or validator(key)))


def main(argv: Sequence[str], *, env: Mapping[str, str] | None = None, table: Mapping[str, Factory] | None = None, agent: job.Agent | None = None) -> int:
    """`python -m gen2.app.child <directory>`; the purpose and the input digest come from the order's environment."""
    env = os.environ if env is None else env
    try:
        if len(argv) != 1:
            raise Refused("usage: gen2.app.child <directory>")
        key = env["GEN2_PURPOSE"]
        run(key, Path(argv[0]), input_digest=env["GEN2_INPUT_DIGEST"], table=table, agent=agent)
    except (Refused, KeyError, OSError, ValueError) as error:
        print(f"gen2.app.child: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
