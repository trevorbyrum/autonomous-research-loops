"""The driver: walk one topic through the fixed program of workflow.plan, one durable order at a time.

Trace: 2e2-min design O17.1, O17.3, O17.4; Astra T11 decision 7 and plan §2.3 (the driver only calls prepare/submit/advance/
recover; durable order identity; no scientific stopping; unknown-spend and rejection blockers kept); L-4, L-8 (a restart finds the
same job by its id), RG-9. Oracle: the supervisor's own journal (settled / incident), read per step by its deterministic order id,
and the router's status; the driver keeps no state of its own. Limits: the per-purpose views, and the agent and builder behind each
order's command, are `Kit`s the composition supplies (T13-T16 own them); the driver chooses no content, only which step is next.
`present` is core.review_presentation.present, injected until it is merged. Any open hold of the topic (the unknown-spend and rejection blockers are holds) stops it; it clears nothing and requeues nothing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from gen2.app import workflow
from gen2.app.workflow import Advance, Done, Issue, Job, Step, Stop, Wait
from gen2.core import canonical
from gen2.exec import orders
from gen2.exec.common import Refused
from gen2.supervisor import jobs as supervisor_jobs
from gen2.supervisor.supervisor import WorkOrder

HALTS = ("unknown_unresolved", "stalled", "not_admitted", "backend_end_unconfirmed", "router_unavailable")  # advance results that need a person
COMPLETION = "apply_operator_decision kind=completion_approval"


@dataclass(frozen=True)
class Context:
    """What a kit's view may use besides the records: nothing it could choose the step's content from."""
    step: Step
    invocation_id: str
    topic_id: str
    admission: Mapping
    episodes: Sequence[str]   # the review episode this checkpoint step belongs to (from its context), else empty
    dossier_revision: int | None
    outcome: Callable[[Step], dict | None]   # a committed step's outcome document, or None
    as_of: str


class Kit(Protocol):
    families: Sequence[str]

    def view(self, context: Context, records: Mapping[str, Sequence[Mapping]], truncation: list[dict]) -> dict: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Driver:
    def __init__(self, station, *, topic_id: str, bundle_hash: str, kits: Mapping[tuple[str, str], Kit], prompt_dir: Path,
                 present: Callable[..., dict], max_passes: int = 1, max_rounds: int = 3, clock: Callable[[], datetime] = _now, sleep: Callable[[float], None] = time.sleep,
                 say: Callable[[str], None] = print) -> None:
        self.station, self.topic_id, self.bundle_hash, self.kits = station, topic_id, bundle_hash, dict(kits)
        self.prompt_dir, self.max_passes, self.max_rounds = Path(prompt_dir), max_passes, max_rounds
        self.clock, self.sleep, self.say, self.present = clock, sleep, say, present   # present: core.review_presentation.present

    # -- facts ------------------------------------------------------------------
    def topic(self) -> dict:
        answer = self.station.router.status({"topic_id": self.topic_id})
        if answer.get("status") != "ok":
            raise Refused(f"status refused: {answer.get('reason')}")
        return answer["topics"][0]

    def _bundle(self) -> Mapping:
        bundle = self.station.router.config_bundle(self.bundle_hash)
        if bundle is None:
            raise Refused(f"config bundle {self.bundle_hash} is not recorded")
        return bundle

    def _order(self, step: Step, digest: str, directory: str = ""):
        """The one identity of a step: its kind, purpose and ordinal within its phase context (build_order hashes the ordinal as text, so
        the context rides in it). Job lookup, outcome lookup, input assembly and submission all come through here."""
        ordinal = f"{step.context}#{step.ordinal}" if step.context else step.ordinal
        return orders.build_order(bundle=self._bundle(), bundle_hash=self.bundle_hash, kind=step.kind, purpose=step.purpose, topic_id=self.topic_id,
                                  ordinal=ordinal, now=self.clock(), directory=directory, input_digest=digest)

    def invocation_id(self, step: Step) -> str:
        return self._order(step, "").invocation_id

    def outcome(self, step: Step) -> dict | None:
        journal = self.station.supervisor.job(self.invocation_id(step)).read("journal.json") or {}
        result = (journal.get("collected") or {}).get("result")
        data = self.station.spool.read(result["content_hash"], topic_id=self.topic_id) if result else None
        return None if data is None else canonical.parse_json_strict(data)

    def get(self, step: Step, default=None):
        """The step's job from the supervisor's journal: never started, live, held (an open incident), failed or committed."""
        job = self.station.supervisor.job(self.invocation_id(step))
        if job.read("order.json") is None:
            return default
        journal = job.read("journal.json") or {}
        if journal.get("settled") == "committed":
            return Job("committed", proposals=bool((self.outcome(step) or {}).get("search_proposals")))
        if journal.get("settled"):
            return Job("failed")
        return Job("held" if journal.get("exhausted") or journal.get("incident") else "live")

    def __getitem__(self, step: Step) -> Job:
        job = self.get(step)
        if job is None:
            raise KeyError(step)
        return job

    def __contains__(self, step: Step) -> bool:
        return self.get(step) is not None

    def dossier_revision(self) -> int | None:
        """The latest recorded dossier revision: ask the router for 1, 2, ... until it answers `unknown_dossier` (the end of the
        history). Any other refusal is an error, never taken as the end."""
        found, revision = None, 1
        while True:
            answer = self.station.router.topic_records({"topic_id": self.topic_id, "families": ["dossiers"], "dossier_revision": revision})
            if answer.get("status") == "ok":
                found, revision = revision, revision + 1
            elif answer.get("reason") == "unknown_dossier":
                return found
            else:
                raise Refused(f"topic_records refused dossier {revision}: {answer.get('reason')}")

    def _orders(self):
        """The orders of this topic that the supervisor holds (its own durable journal); each carries the context it was issued under."""
        root = Path(self.station.supervisor.jobs_root)
        for path in sorted(root.iterdir()) if root.is_dir() else ():
            order = supervisor_jobs.Job(root, path.name).read("order.json")
            if order and order.get("topic_id") == self.topic_id and "GEN2_CONTEXT" in (order.get("env") or {}):
                yield order

    def follow(self, topic: Mapping) -> tuple[str | None, bool]:
        """The checkpoint context to follow: the router's own review episode with the approved contract revision (`c<rev>.<episode_id>`).
        An epoch already begun is followed until its review settles, whether or not its episode is still open (read from the order
        issued, not the open list). Otherwise the oldest open episode (by opened_at, then id) that has no epoch yet begins one. Returns
        (context or None, whether an epoch has finished)."""
        prefix = f"c{topic['active_contract_revision']}."
        begun = sorted({o["env"]["GEN2_CONTEXT"] for o in self._orders() if o["env"].get("GEN2_STEP") == "checkpoint/challenge#1"
                        and o["env"]["GEN2_CONTEXT"].startswith(prefix)})
        done = [c for c in begun if (self.get(Step("checkpoint", "review", 1, c)) or Job("none")).state == "committed"]
        for context in begun:
            if context not in done:
                return context, bool(done)
        taken = {c[len(prefix):] for c in begun}
        fresh = [e["episode_id"] for e in sorted(topic["reviews"], key=lambda e: (e["opened_at"], e["episode_id"])) if e["episode_id"] not in taken]
        return (prefix + fresh[0] if fresh else None), bool(done)

    def unsettled_elsewhere(self, topic: Mapping) -> str | None:
        """Work issued under another contract revision that has not settled: the driver stops rather than orphan it or start beside it."""
        current = f"c{topic['active_contract_revision']}"
        for order in self._orders():
            context = order["env"]["GEN2_CONTEXT"]
            if context.startswith("c") and context.split(".")[0] != current:
                journal = self.station.supervisor.job(order["invocation_id"]).read("journal.json") or {}
                if not journal.get("settled"):
                    return f"{order['env'].get('GEN2_STEP')} was issued under {context.split('.')[0]} and has not settled; the contract is now {current}"
        return None

    def facts(self, topic: Mapping) -> dict:
        """The authoritative context of the program: the confirmed brief's version (scoping), the approved contract revision and the
        checkpoint epoch. Read from the router and the supervisor's journal; the driver keeps none of it."""
        records = self.station.router.topic_records({"topic_id": self.topic_id, "families": ["intake_briefs"]})["records"]
        confirmed = [b["version"] for b in records["intake_briefs"] if b["status"] == "confirmed"]
        epoch, finished = self.follow(topic) if topic["active_contract_revision"] is not None else ("", False)
        return {"brief": max(confirmed, default=None), "contract": topic["active_contract_revision"], "epoch": epoch, "finished": finished}

    def admission(self, topic: Mapping) -> dict:
        records = self.station.router.topic_records({"topic_id": self.topic_id, "families": ["intake_briefs", "contract_revisions"]})["records"]
        if topic["status"] == "scoping":
            brief = max((b for b in records["intake_briefs"] if b["status"] == "confirmed"), key=lambda b: b["version"], default=None)
            if brief is None:
                raise Refused("a scoping topic has no confirmed brief")
            return {"context": "pre-contract/1", "brief": {k: brief[k] for k in ("brief_id", "version", "content_hash")},
                    "brief_confirmation_decision_id": brief["confirmed_by_decision_id"]}
        contract = next((c for c in records["contract_revisions"] if c["revision"] == topic["active_contract_revision"]), None)
        if contract is None:
            raise Refused("the topic has no active contract revision")
        return {"context": "contract/1", "contract": {"revision": contract["revision"], "content_hash": contract["content_hash"]}}

    # -- acting -----------------------------------------------------------------
    def issue(self, step: Step, topic: Mapping) -> None:
        """Assemble the step's input, write it, build its order from the bundle's pins and submit it. Nothing is durable until the
        supervisor's prepare, so a crash before it leaves no job and the step is issued again from the same facts."""
        kit = self.kits.get((step.kind, step.purpose))
        if kit is None:
            raise Refused(f"no kit is installed for {step.kind}/{step.purpose}")
        entry = orders.executor_entry(self._bundle(), step.kind, step.purpose)
        prompt = orders.mounted_prompt(self.prompt_dir, entry)
        invocation = self.invocation_id(step)
        records = self.station.router.topic_records({"topic_id": self.topic_id, "families": list(kit.families)})["records"] if kit.families else {}
        admission, truncation = self.admission(topic), []
        episode = step.context.partition(".")[2] if step.kind == "checkpoint" else ""
        context = Context(step, invocation, self.topic_id, admission, [episode] if episode else [], self.dossier_revision(),
                          self.outcome, self.clock().strftime("%Y-%m-%dT%H:%M:%SZ"))
        document = orders.work_input(kind=step.kind, purpose=step.purpose, invocation_id=invocation, topic_id=self.topic_id, admission=admission,
                                     entry=entry, view=kit.view(context, records, truncation), truncation=truncation)
        directory = self.station.supervisor.job(invocation).scratch   # the executor's cwd and where the supervisor collects outcome.json: one location
        digest = orders.write_inputs(directory, entry=entry, prompt=prompt, document=document)
        spec = self._order(step, digest, str(directory))   # prepare() accepts a job directory that already holds the inputs
        self.station.supervisor.submit(WorkOrder(invocation_id=spec.invocation_id, kind=spec.kind, topic_id=spec.topic_id,
                                                 config_bundle_hash=spec.config_bundle_hash, deadline_at=spec.deadline_at,
                                                 lease_expires_at=spec.lease_expires_at, command=spec.command,
                                                 env={**spec.env, "GEN2_CONTEXT": step.context, "GEN2_STEP": f"{step.kind}/{step.purpose}#{step.ordinal}"}))

    def tick(self) -> workflow.Action:
        """One decision, and its one act. `present` is core.review_presentation.present, injected until it is merged. Any open hold of the topic stops the walk before anything is issued or advanced."""
        topic = self.topic()
        if topic["holds"]:
            hold = topic["holds"][0]
            return Stop(f"open hold {hold['hold_id']}: {hold.get('clears_when')}")
        if (stray := self.unsettled_elsewhere(topic)) is not None and topic["active_contract_revision"] is not None:
            return Stop(stray)
        action = workflow.plan(topic["status"], self, reviews=[r["episode_id"] for r in topic["reviews"]],
                               max_passes=self.max_passes, max_rounds=self.max_rounds, **self.facts(topic))
        if isinstance(action, Issue):
            self.issue(action.step, topic)
        elif isinstance(action, Advance):
            result = self.station.supervisor.advance(self.invocation_id(action.step))
            if result in HALTS:
                return Stop(f"{action.step.kind}/{action.step.purpose} #{action.step.ordinal}: {result}")
        return action

    def run(self, max_ticks: int = 200) -> str:
        """Recover, then walk until the next move is the operator's, the topic is done, or a step stops it. Returns what was said."""
        self.station.supervisor.recover()
        for _ in range(max_ticks):
            action = self.tick()
            if isinstance(action, (Wait, Stop, Done)):
                return self._say(action)
            self.sleep(0.2)
        return self._say(Stop(f"still working after {max_ticks} ticks; run the driver again"))

    def _shown(self) -> dict:
        """present() for the dossier revision the newest sufficiency review is bound to: the exact one the operator would approve."""
        reviews = self.station.router.topic_records({"topic_id": self.topic_id, "families": ["completion_records"]})["records"]["completion_records"]
        bound = [r["subject_revision"] for r in reviews if r["kind"] == "sufficiency_review"]
        if not bound:
            raise Refused("no sufficiency review is recorded")
        answer = self.station.router.topic_records({"topic_id": self.topic_id, "dossier_revision": bound[-1], "families": ["dossiers", "completion_records"]})
        if answer.get("status") != "ok":
            raise Refused(f"dossier {bound[-1]}: {answer.get('reason')}")
        return self.present(answer["records"], lambda ref: self.station.spool.read(ref["content_hash"], topic_id=self.topic_id), dossier_revision=bound[-1])

    def _say(self, action: workflow.Action) -> str:
        if isinstance(action, Wait):
            try:
                shown = self._shown() if action.command == COMPLETION else None
            except (Refused, ValueError, KeyError) as error:   # never a bare approval wait: the operator must see the review first
                return self._say(Stop(f"cannot show the review for approval: {error}"))
            text = workflow.waiting_line(action, shown)
        else:
            text = "done" if isinstance(action, Done) else f"stopped: {action.reason}"
        self.say(text)
        return text
