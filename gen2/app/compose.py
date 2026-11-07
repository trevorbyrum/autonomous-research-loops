"""Composition for the supervised workflow: the seven kits, the three recorders and the topic-filtered exchange index.

Trace: Gate S #7 §5.2 and the PR3b brief (views carry the refs their builders cite; the driver sets the retained bytes aside; builders
are pure); 2e2-min design O17.1; Astra #127 F1 (a proposal's provenance is bound to the committed outcome and its receipt); DEBT-051
(the exchange index is the production capture reader). Oracle: the merged views, builders and recorders; this module only chooses
which rows and which handles each is given. Limits: no domain logic and no scientific decision lives here; the exchange index lists a
topic's discovery scratch directories from the supervisor's own orders (topic and discovery purpose, both), never from a bare step name.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping, Sequence

from gen2.app import support_gate
from gen2.app.driver import Context
from gen2.discovery import binding, recorder as discovery_recorder
from gen2.discovery.exchanges import ExchangeIndex
from gen2.exec import challenge, dossier, review, verify, verify_record, views
from gen2.exec.common import Refused
from gen2.supervisor import jobs as supervisor_jobs


@dataclass(frozen=True)
class View:
    """One kit: the families its view reads and the function that builds the view from them."""
    families: Sequence[str]
    build: Callable[[Context, Mapping, list], dict]

    def view(self, context: Context, records: Mapping, truncation: list[dict]) -> dict:
        return self.build(context, records, truncation)


def discovery_scratches(station, topic_id: str) -> Callable[[], list[Path]]:
    """The scratch directories of this topic's discovery jobs, from the supervisor's durable orders (topic and purpose both)."""
    def listing() -> list[Path]:
        root = Path(station.supervisor.jobs_root)
        found = []
        for path in sorted(root.iterdir()) if root.is_dir() else ():
            job = supervisor_jobs.Job(root, path.name)
            order = job.read("order.json") or {}
            if order.get("topic_id") == topic_id and (order.get("env") or {}).get("GEN2_PURPOSE") == "discovery/search":
                found.append(job.scratch)
        return found
    return listing


class Composition:
    """The station's collaborators that need the station itself (its spool and orders) but must be handed to `open_station` first:
    the recorders and the router's capture reader. `bind` gives them the opened station; before that they refuse to run."""

    def __init__(self, topic_id: str) -> None:
        self.topic_id, self.station = topic_id, None

    def bind(self, station) -> "Composition":
        self.station = station
        return self

    def exchanges(self, topic_id: str | None = None) -> ExchangeIndex:
        topic = topic_id or self.topic_id
        return ExchangeIndex(self.station.spool, topic, discovery_scratches(self.station, topic))

    @property
    def captures(self):
        """`Router(gateway_captures=...)`: the index, read lazily."""
        return type("Captures", (), {"read": lambda _, **key: self.exchanges(key["topic_id"]).read(**key)})()

    def recorders(self) -> dict:
        """`Supervisor(recorders=...)`: the three purposes the supervisor refuses to submit without one (RECORDED)."""
        return {"discovery/search": discovery_recorder.recorder(lambda topic, data, media: self.station.spool.stage(topic, data, media)),
                "verification/verify": verify_record.recorder(self.exchanges),
                "checkpoint/dossier": dossier.record}

    def kits(self, *, lanes: Sequence[str], gateway: Mapping, validate: Callable[[str, object], None]) -> dict:
        """The kit of every purpose. `gateway` is the discovery child's policy view ({commercial, accept_per_item, policy_version})."""
        spool, topic_id, exchanges = self.station.spool, self.topic_id, self.exchanges()
        read = lambda ref: spool.read(ref["content_hash"], topic_id=topic_id)
        text_of = lambda content_hash: (spool.read(content_hash, topic_id=topic_id) or b"").decode("utf-8", "replace") or None

        def challenge_view(c: Context, records: Mapping, truncation: list[dict]) -> dict:
            proposals, proposed_by = [], None
            if c.step.ordinal == 2:   # pass 2: the searches pass 1 proposed, executed by discovery under that pass's identity
                first = replace(c.step, ordinal=1)
                proposals, proposed_by = (c.outcome(first) or {}).get("search_proposals", []), c.invocation_of(first)
            return challenge.challenge_view(c.admission, records, text_of, exchanges, invocation_id=c.invocation_id, review_episodes=c.episodes,
                                            proposals=proposals, proposed_by=proposed_by, as_of=c.as_of, truncation=truncation)

        def discovery_view(c: Context, records: Mapping, truncation: list[dict]) -> dict:
            if c.proposer is None:
                raise Refused("a discovery run needs the step whose proposals it executes")
            committed = binding.assemble(binding.TopicReceipts(self.station.router, topic_id), spool, topic_id, c.invocation_of(c.proposer), validate,
                                         max_bytes=1 << 20)
            return {**committed, "gateway": dict(gateway), "attempt": 1}

        return {
            ("research_pass", "scope"): View(views.SCOPE_FAMILIES, lambda c, r, t: views.scope_view(c.admission, r, list(lanes), c.as_of, t)),
            ("research_pass", "research"): View(views.RESEARCH_FAMILIES, lambda c, r, t: views.research_view(
                c.admission, r, exchanges, text_of, c.as_of, c.state_revision, t)),
            ("verification", "verify"): View(verify.FAMILIES, lambda c, r, t: verify.verify_view(
                c.admission, r, support_gate.RouterSupport(), exchanges, text_of, c.as_of, t)),
            ("checkpoint", "challenge"): View(challenge.FAMILIES, challenge_view),
            ("checkpoint", "review"): View(review.FAMILIES, lambda c, r, t: review.review_view(
                c.admission, r, text_of, read, invocation_id=c.invocation_id, dossier_revision=c.dossier_revision)),
            ("checkpoint", "dossier"): View((), lambda c, r, t: {}),
            ("discovery", "search"): View((), discovery_view),
        }
