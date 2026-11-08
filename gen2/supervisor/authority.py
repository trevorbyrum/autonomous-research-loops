"""The production `DispatchAuthority`: a verified qualification record, the job's own state, and nothing a caller declares.

Trace: Gate S #7b §5 (obligation: qualification-record loader = DispatchAuthority, plan writer); Astra live-hosting review LH-1 (a
profile is not permission to send: the Router's dispatch protocol decides, over operands this authority supplies) and LH-2 (a plan with
the origins, generation, slots and binds); F1; INVARIANTS C-1, C-9; core.control.DispatchAuthority (the contract). Oracle: the record's
own bytes against the pin the operator set in the engine's environment, and the manifest bytes against the record's manifest pin;
the backend's own `docker-complete.json` for an end. Limits: it verifies pins, the state and the named witnesses' presence and
`passed` flags; it does not re-run a witness, and the receipts' content is lane C's and the verifier's to attest. An unreadable,
stale or mismatched record means no admission at all (None), never a default. Cost is never estimated: `actual_minor_units` is None
until a trusted source exists (the DEBT-052 amendment then charges the configured worst case U). The rejection mapping is the real
route's classifier and lands with it (PR-L2); until then a rejected run reads as an unknown end and stops the trial, fail closed.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Callable, Mapping

from gen2.core import canonical
from gen2.supervisor import jobs
from gen2.supervisor.isolation import LiveProfileRefused

RECORD = "qualification-record/1"
WITNESSES = ("Q1", "Q2", "Q3")
REAL_WITNESSES = (*WITNESSES, "DEBT-004")
Stage = Callable[[str, bytes, str], Mapping]
CID = re.compile(r"[0-9a-f]{64}")   # a Docker network ID: the persistent relay-only bridge is consumed by ID, never created or adopted by name


def verify_record(record: bytes, pin: str, manifest: bytes) -> Mapping | None:
    """The parsed record if it is qualified for exactly this manifest and the operator's pin; otherwise None."""
    try:
        if canonical.bytes_digest(record) != pin:
            return None
        doc = canonical.parse_json_strict(record)
        real = doc["route"] == "real"
        named = {w["name"]: w for w in doc["witnesses"]}
        ok = (doc["record_version"] == RECORD and doc["state"] == "qualified" and doc["route"] in ("fixture", "real")
              and doc["manifest_pin"] == canonical.bytes_digest(manifest)
              and all(named.get(n, {}).get("passed") is True and isinstance(named[n].get("receipt"), str) for n in (REAL_WITNESSES if real else WITNESSES))
              and (not real or all(isinstance(doc.get(k), str) and doc[k] for k in ("deployment_id", "provider_route"))))
        return doc if ok else None
    except (ValueError, KeyError, TypeError):
        return None


class QualifiedAuthority:
    def __init__(self, jobs_root: str | Path, *, record: bytes, pin: str, manifest: bytes, stage: Stage, epoch: str | None = None) -> None:
        self.epoch = epoch or uuid.uuid4().hex   # fixed for this process, so a restart is a new epoch (no admission survives it unchecked)
        self._jobs, self._stage = Path(jobs_root), stage
        self._record_bytes, self._manifest = record, manifest
        self._doc = verify_record(record, pin, manifest)
        self.run_id = self._doc["policy"]["run_id"] if self._doc else ""   # fixed at load, so a retired record still names the run it refused
        self._manifest_ref = canonical.bytes_digest(manifest)

    @property
    def qualified(self) -> bool:
        return self._doc is not None

    def retire(self) -> None:
        """Invalidate the loaded record (a later start then reads `is_current` false); a new record needs a new process."""
        self._doc = None

    def _job(self, handle: str) -> jobs.Job:
        return jobs.Job(self._jobs, handle)

    def plan(self, order: Mapping) -> dict:
        """The backend's plan for one live order, from the protected template in the record and this job's own facts."""
        if self._doc is None:
            raise LiveProfileRefused("profile_qualification_unavailable")
        doc, template, invocation = self._doc, self._doc["plan"], order["invocation_id"]
        generation = hashlib.sha256(invocation.encode()).hexdigest()[:32]
        origin = {"invocation_id": invocation, "topic_id": order["topic_id"], "config_bundle_hash": order["config_bundle_hash"],
                  "job_handle": "job-" + invocation, "manifest_ref": self._manifest_ref, "credential_ref": doc["credential_ref"], "route": doc["route"],
                  "backend": doc["backend"], "evidence_generation": generation,
                  **({"deployment_id": doc["deployment_id"], "provider_route": doc["provider_route"]} if doc["route"] == "real" else {})}
        inputs = self._job("job-" + invocation).scratch / "inputs"
        prefix = Path(template["engine_jobs"])
        if prefix not in (inputs, *inputs.parents) or ".." in inputs.parts:
            raise LiveProfileRefused("profile_unmapped_path")
        slots, egress = template["slots"], template.get("egress_network_id")
        if (doc["route"] == "real") != (egress is not None) or (egress is not None and not CID.fullmatch(str(egress))):
            raise LiveProfileRefused("profile_egress_network")   # a real route names its protected, pre-existing bridge by ID; a fixture route has none
        return {"origin": origin, "generation": generation, "route": doc["route"], "slots": slots, "paths": template.get("paths", []),
                "binds": {"inputs": str(Path(template["host_jobs"]) / inputs.relative_to(prefix)), "out": str(Path(slots["out"]) / generation),
                          "seed": template["seed"]},
                "expected": template.get("expected", {}), "relay_config": template.get("relay_config"),
                **({"fixture": template["fixture"]} if "fixture" in template else {}), **({"egress": {"network_id": egress}} if egress else {})}

    def _origin(self, job: jobs.Job) -> dict | None:
        plan, grant = job.read("docker-plan.json"), (job.read("journal.json") or {}).get("grant")
        if plan is None or not grant:
            return None
        return {**plan["origin"], "lease_id": grant["lease"]["lease_id"], "generation": grant["lease"]["generation"], "epoch": self.epoch}

    def admission(self, invocation_id: str, run_id: str, attempt: int) -> Mapping | None:
        job = self._job("job-" + invocation_id)
        origin, order = self._origin(job), job.read("order.json")
        if self._doc is None or origin is None or order is None or run_id != self.run_id:
            return None
        refs = [dict(self._stage(order["topic_id"], data, "application/json")) for data in (self._manifest, self._record_bytes)]
        return {"origin": origin, "policy": {**self._doc["policy"], "topic_id": order["topic_id"], "max_concurrent_attempts": 1},
                "upper_minor_units": self._doc["upper_minor_units"], "artifacts": refs}

    def is_current(self, origin: Mapping) -> bool:
        """Local, no I/O: the loaded record still stands and the origin names its manifest, credential, route and this epoch."""
        doc = self._doc
        return (doc is not None and origin.get("epoch") == self.epoch and origin.get("manifest_ref") == self._manifest_ref
                and origin.get("credential_ref") == doc["credential_ref"] and origin.get("route") == doc["route"])

    def result(self, admission_ref: str, evidence_ref: str) -> Mapping | None:
        """The authenticated end of the job whose retained execution record is `evidence_ref`: the backend's own complete file, no estimate."""
        for path in sorted(self._jobs.iterdir()) if self._jobs.is_dir() else ():
            job = self._job(path.name)
            collected = (job.read("journal.json") or {}).get("collected") or {}
            record = collected.get("record") or {}
            if record.get("content_hash") != evidence_ref:
                continue
            origin, plan, complete = self._origin(job), job.read("docker-plan.json"), job.read("docker-complete.json") or {}
            if origin is None or plan is None:
                return None
            ended = complete.get("origin") == plan["origin"] and collected["observation"]["descendants"]["handling"] != "unconfirmed"
            return {"origin": origin, "admission_ref": admission_ref, "evidence_ref": evidence_ref, "confirmed_end": bool(ended),
                    "actual_minor_units": None, "artifacts": [*complete.get("refs", []), record]}
        return None
