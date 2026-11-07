"""The driver's fixed program: which step comes next for one topic, and what the operator must do when it is theirs.

Trace: 2e2-min design O17.2, O17.4; Astra T11 decision 7 (mechanical state progression, durable order identity, no scientific
stopping in the driver, unknown-spend and rejection blockers kept); plan §2.3 (the driver only calls prepare/submit/advance/
recover; no screening, stopping or scheduling judgment). Oracle: the table in the tests, one row per topic status and per step
state. Limits: pure; it reads no store and calls no router. Facts come from the caller: the topic's queue status, the open review
episodes, and each step's job state read from the supervisor's journal by its deterministic order id. `max_passes` and
`max_rounds` are execution budgets (G-10) that stop work; they never decide that research is sufficient. A step that failed,
is unknown or is held stops the walk; nothing here retries, requeues or clears a blocker (DEBT-052/053 stay the operator's).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from gen2.exec.common import Refused

MODEL = (("research_pass", "scope"), ("research_pass", "research"), ("verification", "verify"), ("checkpoint", "challenge"), ("checkpoint", "review"))
CODE_ONLY = (("discovery", "search"), ("checkpoint", "dossier"))
# (deadline_s, lease_s, max_input_bytes, max_output_bytes): defaults the operator may override in the bundle they activate
LIMITS = {("research_pass", "scope"): (1800, 2400, 262144, 65536), ("research_pass", "research"): (3600, 4200, 524288, 131072),
          ("verification", "verify"): (3600, 4200, 524288, 131072), ("checkpoint", "challenge"): (3600, 4200, 524288, 131072),
          ("checkpoint", "review"): (1800, 2400, 524288, 65536), ("discovery", "search"): (1800, 2400, 262144, 1048576),
          ("checkpoint", "dossier"): (600, 900, 65536, 65536)}


def executor_entries(pins: Sequence[Mapping], limits: Mapping = LIMITS) -> list[dict]:
    """`policy.executors` for every purpose of the workflow: each pin from tools/gen2_prompt_pins plus its limits. A purpose with no
    pinned prompt file is refused, never defaulted (G-10)."""
    pinned = {(p["kind"], p["purpose"]): p["prompt"] for p in pins}
    missing = sorted(set(limits) - set(pinned))
    if missing:
        raise Refused(f"no pinned prompt file for {missing}")
    return [{"kind": kind, "purpose": purpose, "prompt": pinned[(kind, purpose)], "deadline_s": d, "lease_s": lease,
             "max_input_bytes": i, "max_output_bytes": o} for (kind, purpose), (d, lease, i, o) in sorted(limits.items())]


@dataclass(frozen=True)
class Step:
    """One unit of the program. `context` names the authoritative phase it belongs to (the confirmed brief version for scoping, the
    approved contract revision for research, that plus the checkpoint epoch for the checkpoint), so work of another phase or
    review episode never shares its identity; the empty context is the one a caller with no phases uses."""
    kind: str
    purpose: str
    ordinal: int
    context: str = ""


@dataclass(frozen=True)
class Job:
    """One step's job as the supervisor's journal has it: committed | live | failed | unknown | held; `proposals` is whether the
    committed outcome carried search_proposals."""
    state: str
    proposals: bool = False


@dataclass(frozen=True)
class Issue:
    step: Step


@dataclass(frozen=True)
class Advance:
    step: Step


@dataclass(frozen=True)
class Wait:
    reason: str
    command: str


@dataclass(frozen=True)
class Stop:
    reason: str


@dataclass(frozen=True)
class Done:
    pass


Action = Issue | Advance | Wait | Stop | Done
OPERATOR = {"awaiting_brief_confirmation": ("the intake brief is not confirmed", "apply_operator_decision kind=brief_confirmation"),
            "awaiting_scope_approval": ("the scoping report awaits approval", "apply_operator_decision kind=scope_approval"),
            "awaiting_contract_approval": ("the contract awaits approval", "apply_operator_decision kind=contract_approval")}
COMPLETION_WAIT = ("the dossier and its review await the operator's approval", "apply_operator_decision kind=completion_approval")
BLOCKED = ("held", "capability_blocked", "stopped_for_resources", "awaiting_judgment", "retired")


def _context(prefix: str, *values: object) -> str:
    return "" if all(v is None for v in values) else prefix + ".".join(str(v) for v in values)


def plan(status: str, jobs: Mapping[Step, Job], *, reviews: Sequence[str], max_passes: int = 1, max_rounds: int = 3,
         brief: int | None = None, contract: int | None = None, reviewed: int | None = None) -> Action:
    """The next action for a topic with this queue status, open review episodes and step jobs. `brief` is the confirmed brief's
    version, `contract` the approved contract revision and `reviewed` how many sufficiency reviews the router holds: they give each
    phase and each checkpoint epoch its own step identities (an epoch is one review episode's challenge, dossier and review)."""
    if status == "completed_with_qualified_conclusions":
        return Done()
    if status in OPERATOR:
        return Wait(*OPERATOR[status])
    if status in BLOCKED:
        return Stop(f"the topic is {status}")
    searches = iter(range(1, 10_000))

    def run(step: Step) -> Action | None:
        job = jobs.get(step)
        if job is None:
            return Issue(step)
        if job.state == "live":
            return Advance(step)
        return None if job.state == "committed" else Stop(f"{step.kind}/{step.purpose} #{step.ordinal} is {job.state}")

    def then_search(step: Step) -> Action | None:
        """A committed step that proposed searches is followed by one discovery run, numbered in program order."""
        done = run(step)
        if done is not None or not jobs[step].proposals:
            return done
        return run(Step("discovery", "search", next(searches), step.context))
    if status == "scoping":
        pre = _context("p", brief)
        for round_ in range(1, max_rounds + 1):
            action = then_search(Step("research_pass", "scope", round_, pre))
            if action is not None:
                return action
        return Stop(f"scoping spent its {max_rounds} rounds")
    if status not in ("queued", "active", "resting"):
        return Stop(f"no step is defined for the topic status {status}")
    here = _context("c", contract)
    for number in range(1, max_passes + 1):
        action = then_search(Step("research_pass", "research", number, here))
        if action is not None:
            return action
    action = run(Step("verification", "verify", 1, here))
    if action is not None:
        return action
    epoch = _context("c", contract, None if reviewed is None else f"e{reviewed + 1}")
    first = Step("checkpoint", "challenge", 1, epoch)
    if first not in jobs and not reviews:
        return Wait(*COMPLETION_WAIT) if reviewed else Wait("no review is open for the checkpoint", "open_review")
    action = then_search(first)
    if action is None and jobs[first].proposals:
        action = run(Step("checkpoint", "challenge", 2, epoch))
    for step in (Step("checkpoint", "dossier", 1, epoch), Step("checkpoint", "review", 1, epoch)):
        action = action or run(step)
    return action or Wait(*COMPLETION_WAIT)


def waiting_line(action: Wait, shown: Mapping | None = None) -> str:
    """The one line the driver prints when the next move is the operator's: what is awaited and the command that unblocks it. For
    the completion approval `shown` is core.review_presentation.present, printed whole so the operator reads the review and its
    evidence, an insufficient one included, before approving."""
    line = f"waiting for: {action.reason}; run: {action.command}"
    return line if shown is None else f"{line}\n{shown_text(shown)}"


def shown_text(shown: Mapping) -> str:
    dossier = shown["dossier"]
    lines = [f"dossier revision {dossier['revision']} ({dossier['content_hash']}): {dossier['state']}"]
    lines += [f"  gate {g['gate']}: {g['state']}" for g in dossier["gates"]]
    for review in shown["reviews"]:
        lines.append(f"  review {review['outcome']}: {review['summary']}")
        lines += [f"    evidence {e['content_hash']}{' (cut)' if e['cut'] else ''}: {e['text'] if e['text'] is not None else 'NOT RETAINED'}" for e in review["evidence"]]
    return "\n".join(lines + ([] if shown["reviews"] else ["  no sufficiency review is bound to this revision"]))
