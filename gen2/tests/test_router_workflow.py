"""The router's workflow write paths (task 2a), and one topic end to end.

Trace: docs/gen2/tasks/2a.md; flow S1 (a topic enters at intake; the brief's
first version awaits the operator's confirmation), S3 (contract drafts, the
operator's ratings, approval blocked by an uncovered critical facet), S4
(retrieved records deduplicated into works; claim-source-obligation links),
S5 (a checkpoint closes its review episode; mandatory signals); INVARIANTS
G-2, G-3, G-4, G-12, G-13, C-9, C-12, E-2, E-3, V-9, RG-1b(e); the 1b
review's bootstrap ruling (topic, brief and first-draft creation, and work
registration, left to Phase 2), the 1d-repair-2 review (the claim-source
link had no outcome operation: it was fixture-seeded), gen2/router/README.md
(review closure and code-policy signals: Phase 2).

Oracles: expectations written by hand; raw SQL read-back, of the whole store
(every table but the audit log) around each refusal; a new work's id and a
signal's trigger identity written out here from their JCS bytes with
hashlib, not with the router's helpers.

Seeding: the unit tests start from the shared fixtures (router_fixtures),
which still seed their two topics, and in some worlds a brief and a first
contract draft, by raw SQL — the fixtures predate these paths, and the older
suites depend on them as they are. What a test here is about goes through the
router. EndToEndTest uses no seeding the router now provides: its one raw-SQL
step is the scoping -> awaiting_scope_approval queue move, which stands for
the committed scoping report (flow S2's hand-off), for which the router has
no path yet (not among task 2a's operations).

Structural limits: work runs at the router with fixture invocations standing
in for executors, except in EndToEndTest, where the research pass and the
checkpoint are real fake-executor subprocesses under the supervisor; there,
too, the test performs the capture steps the supervisor does not yet make
(an observation, a work registration and an interim claim capture, under the
running job's own capability). Identity dedup is exact: normalizing an
identity is the dedup method's, recorded by its version, and not tested
here. Nothing here tests that a link, a closure or a signal is
scientifically right; only who may write it, when, and what is kept.
"""
from __future__ import annotations

import hashlib
import json

from gen2.core import canonical
from gen2.tests import router_fixtures as rf
from gen2.tests import supervisor_fixtures as sf
from gen2.tests.router_fixtures import OTHER, TOPIC, RouterTestCase, empty_outcome, h, jcs
from gen2.tests.test_router_amendments import contract_doc  # the schema-valid example contract, as a topic's revision

REVIEW_BY = "2026-10-01T00:00:00Z"
NEW = "fleet-b:t9"


def jcs_hash(text: str) -> str:
    """SHA-256 over JCS bytes written out by hand in the test (keys sorted, no whitespace)."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def work_of(scheme: str, value: str) -> str:
    return "wrk_" + jcs_hash(f'{{"identity_scheme":"{scheme}","identity_value":"{value}"}}').split(":", 1)[1]


def contract(revision: int, parent: int | None, *, topic: str = TOPIC, rated: bool = True, edit=None) -> dict:
    """The example contract as `topic`'s revision, its ratings citing opd_rate0001 (the example's), its hash true."""
    def change(doc: dict) -> None:
        doc["topic_id"] = topic
        if edit is not None:
            edit(doc)
    return contract_doc(revision, parent, rated=rated, edit=change)


def ratings(doc: dict) -> dict:
    """A rating_approval's payload: exactly the ratings `doc` carries."""
    rating = lambda entry: {"band": entry["importance"]["operator_rating"]["band"], "score": entry["importance"]["operator_rating"].get("score")}  # noqa: E731
    return {"facets": {f["facet_id"]: rating(f) for f in doc["facet_map"]["facets"]}, "obligations": {o["obligation_id"]: rating(o) for o in doc["obligations"]}}


def uncover_effect(doc: dict) -> None:
    """O-1, the one obligation tagging the critical facet F-effect, withdrawn; its cell a gap."""
    doc["obligations"] = [o for o in doc["obligations"] if o["obligation_id"] != "O-1"]
    for cell in doc["facet_map"]["coverage_matrix"]["cells"]:
        if cell["facet_id"] == "F-effect" and cell["question_type"] == "effect":
            cell.clear()
            cell.update(facet_id="F-effect", question_type="effect", state="gap", rationale="O-1 withdrawn")


def link(claim: str = "clm_00000001", revision: int = 1, work: str | None = None, obligation: str = "O-1") -> dict:
    return {"claim_id": claim, "claim_revision": revision, "work_id": work or work_of("doi", "10.1/x"), "source_version": "v1", "obligation_id": obligation,
            "spans": [{"start": 10, "end": 42, "locator": {"kind": "page", "value": "3"}}], "contribution": "answer",
            "evidence_origin_lineage": "study-1", "analytical_method": None}


class Workflow(RouterTestCase):
    """Router paths for S1-S3, and the capture helpers of S4-S5."""

    def open_brief(self, tid: str = TOPIC, version: int = 1, deadline: str = REVIEW_BY, **changes) -> dict:
        return self.router.open_brief({"document": self.brief_document(tid, version, **changes), "owner_operator_id": "user", "review_deadline": deadline})

    def confirm(self, tid: str = TOPIC, version: int = 1, doc: dict | None = None) -> None:
        doc = doc or self.brief_document(tid, version)
        out = self.decide(f"opd_brief{tid[-2:]}{version:02d}", "brief_confirmation", {"kind": "intake_brief", "ref": "brief-1", "revision": version,
                                                                                     "hash": doc["content_hash"]}, tid)
        assert out["status"] == "applied", out

    def draft(self, doc: dict) -> dict:
        return self.router.draft_contract({"document": doc})

    def rate(self, rated: dict, tid: str = TOPIC) -> dict:
        """The operator rates draft 1 of `tid`, as `rated` states the ratings."""
        r1 = self.value("SELECT content_hash FROM contract_revisions WHERE topic_id = ? AND revision = 1", tid)
        return self.decide("opd_rate0001", "rating_approval", {"kind": "contract_revision", "revision": 1, "hash": r1}, tid, payload=ratings(rated))

    def rated_drafts(self, tid: str = TOPIC) -> dict:
        """S1 and S3's drafts through the router: the brief opened and
        confirmed, draft 1 unrated, the operator's rating of it, draft 2
        carrying the ratings."""
        assert self.open_brief(tid)["status"] == "recorded"
        self.confirm(tid)
        r2 = contract(2, 1, topic=tid)
        assert self.draft(contract(1, None, topic=tid, rated=False))["status"] == "recorded"
        assert self.rate(r2, tid)["status"] == "applied"
        assert self.draft(r2)["status"] == "recorded"
        return r2

    def scope_approved(self, tid: str = TOPIC) -> None:
        """Raw SQL for the committed scoping report (no router path yet), then the operator's scope approval."""
        self.x("UPDATE queue_entries SET status = 'awaiting_scope_approval', state_revision = state_revision + 1 WHERE topic_id = ?", tid)
        out = self.decide(f"opd_scope{tid[-2:]}01", "scope_approval", {"kind": "scoping_report", "ref": "scope-1", "revision": 1, "hash": h("5")}, tid)
        assert out["status"] == "applied", out

    def approve(self, doc: dict, tid: str = TOPIC, did: str | None = None) -> dict:
        return self.decide(did or f"opd_cntr{tid[-2:]}{doc['revision']:02d}", "contract_approval",
                           {"kind": "contract_revision", "revision": doc["revision"], "hash": doc["content_hash"]}, tid)

    def approved(self, tid: str = TOPIC) -> dict:
        r2 = self.rated_drafts(tid)
        self.scope_approved(tid)
        out = self.approve(r2, tid)
        assert out["status"] == "applied", out
        return r2

    # -- S4 capture ------------------------------------------------------------------
    def observe(self, grant: dict, observation_id: str, records: tuple[str, ...]) -> list[str]:
        """A successful search of the grant's topic capturing `records`; returns the retrieval event ids."""
        request = {"q": observation_id}
        events = [{"event_id": f"rev_{observation_id[4:]}{n:02d}", "provider_record_id": record, "rank": n, "captured_at": "2026-09-27T10:00:00Z"}
                  for n, record in enumerate(records, 1)]
        observation = {"observation_id": observation_id, "request": request, "request_identity": canonical.logical_hash(request), "attempt": 1, "lane": "crossref",
                       "obligation_ids": ["O-1"], "started_at": "2026-09-27T10:00:00Z", "ended_at": "2026-09-27T10:00:01Z", "coverage_state": "searched_ok",
                       "result_count": len(events), "completeness": "complete", "error_class": None, "capability_fact_id": None, "policy_version": "pol-1",
                       "cost_units": None, "gateway_call_ref": None}
        out = self.router.record_observation({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "observation": observation,
                                              "retrieval_events": events})
        assert out["status"] == "recorded", out
        return [e["event_id"] for e in events]

    def register(self, grant: dict, works: list[tuple[str, str, list[str]]], version: str = "dedup-1") -> dict:
        return self.router.register_works({"capability_id": grant["capability_id"], "invocation_id": grant["invocation_id"], "dedup_method_version": version,
                                           "works": [{"identity_scheme": s, "identity_value": v, "event_ids": list(e)} for s, v, e in works]})

    def capture(self, grant: dict, op: str, claim: str = "clm_00000001", revision: int = 1, **sections) -> dict:
        """An interim commit under `grant` capturing a claim (unless claim is None), with any other sections."""
        outcome = empty_outcome(grant["invocation_id"], "interim_transition", topic=grant["topic_id"])
        refs = []
        if claim is not None:
            text = self.artifact(f"{claim} r{revision}".encode())
            outcome["claims"] = [{"claim_id": claim, "revision": revision, "text_ref": text, "load_bearing": False, "required_access_tier": None}]
            refs = [text]
        outcome.update(sections)
        return self.router.commit_outcome(self.envelope(grant, op, outcome, refs=refs))

    def refused_commit(self, grant: dict, op: str, reason: str, detail: str, **sections) -> None:
        before = self.state()
        out = self.capture(grant, op, claim=None, **sections)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", reason), out)
        self.assertIn(detail, out.get("detail", ""))
        self.assertEqual(self.state(), before)


# ---------------------------------------------------------------------------
# topics
# ---------------------------------------------------------------------------
class TopicTest(Workflow):
    def test_a_topic_is_created_at_intake(self) -> None:
        self.assertEqual(self.router.create_topic({"topic_id": NEW, "priority": 3}), {"status": "created", "topic_id": NEW})
        self.assertEqual(self.rows("SELECT fleet_id, priority, status, state_revision, active_contract_revision, status_decision_id, paused_at, "
                                   "created_at = updated_at FROM queue_entries WHERE topic_id = ?", NEW),
                         [("fleet-b", 3, "awaiting_brief_confirmation", 0, None, None, None, 1)])
        before = self.state()
        self.assertEqual(self.router.create_topic({"topic_id": NEW, "priority": 3}), {"status": "replayed", "topic_id": NEW})
        self.assertEqual(self.state(), before)

    def test_another_request_under_a_topic_id_is_a_conflict(self) -> None:
        self.router.create_topic({"topic_id": NEW, "priority": 3})
        before = self.state()
        out = self.router.create_topic({"topic_id": NEW, "priority": 4})
        self.assertEqual((out["status"], out.get("reason")), ("refused", "topic_conflict"), out)
        self.assertEqual(self.state(), before)

    def test_a_replay_is_answered_whatever_the_topic_has_done_since(self) -> None:
        self.to_scoping()  # the seeded TOPIC (priority 1) has moved on
        before = self.state()
        self.assertEqual(self.router.create_topic({"topic_id": TOPIC, "priority": 1})["status"], "replayed")
        self.assertEqual(self.state(), before)

    def test_a_malformed_request_creates_nothing(self) -> None:
        for label, request in (("no fleet prefix", {"topic_id": "t9", "priority": 1}), ("an upper-case fleet", {"topic_id": "Fleet:t9", "priority": 1}),
                               ("a negative priority", {"topic_id": NEW, "priority": -1}),
                               ("a status of its own", {"topic_id": NEW, "priority": 1, "status": "queued"}),
                               ("a state revision of its own", {"topic_id": NEW, "priority": 1, "state_revision": 4})):
            with self.subTest(label):
                before = self.state()
                out = self.router.create_topic(request)
                self.assertEqual((out["status"], out.get("reason")), ("refused", "request_invalid"), out)
                self.assertEqual(self.state(), before)


# ---------------------------------------------------------------------------
# a brief's first version
# ---------------------------------------------------------------------------
class BriefIntakeTest(Workflow):
    def test_a_first_version_is_written_awaiting_confirmation(self) -> None:
        doc = self.brief_document()
        self.assertEqual(self.open_brief(), {"status": "recorded", "topic_id": TOPIC, "brief_id": "brief-1", "version": 1, "superseded": None})
        self.assertEqual(self.rows("SELECT version, parent_version, content_hash, owner_operator_id, status, created_at, review_deadline, overdue_since, "
                                   "confirmed_by_decision_id, closed_at FROM intake_briefs WHERE topic_id = ?", TOPIC),
                         [(1, None, doc["content_hash"], "user", "awaiting_confirmation", "2026-09-27T09:00:00Z", REVIEW_BY, None, None, None)])
        self.assertEqual(json.loads(self.value("SELECT document FROM intake_briefs WHERE topic_id = ?", TOPIC)), doc)
        before = self.state()
        self.assertEqual(self.open_brief()["status"], "replayed")
        self.assertEqual(self.state(), before)

    def test_it_is_versioned_and_confirmed_through_the_existing_paths(self) -> None:
        self.open_brief()
        v2 = self.brief_document(version=2, feeds="rebuild, patch or leave")
        self.assertEqual(self.router.version_brief({"document": v2, "owner_operator_id": "user", "review_deadline": REVIEW_BY})["status"], "recorded")
        self.confirm(version=2, doc=v2)
        self.assertEqual(self.rows("SELECT version, status FROM intake_briefs WHERE topic_id = ? ORDER BY version", TOPIC), [(1, "superseded"), (2, "confirmed")])
        self.assertEqual(self.status(), "scoping")

    def test_open_brief_writes_no_later_version(self) -> None:
        self.open_brief()
        before = self.state()
        out = self.router.open_brief({"document": self.brief_document(version=2), "owner_operator_id": "user", "review_deadline": REVIEW_BY})
        self.assertEqual((out["status"], out.get("reason")), ("refused", "brief_exists"), out)
        self.assertEqual(self.state(), before)

    def test_version_brief_writes_no_first_version(self) -> None:
        before = self.state()
        out = self.router.version_brief({"document": self.brief_document(), "owner_operator_id": "user", "review_deadline": REVIEW_BY})
        self.assertEqual((out["status"], out.get("reason")), ("refused", "unknown_brief"), out)
        self.assertEqual(self.state(), before)

    def test_each_defect_is_refused_alone(self) -> None:
        def unparented_two() -> dict:
            doc = self.brief_document(version=2)
            doc["parent_version"] = None
            doc["content_hash"] = canonical.content_hash({k: v for k, v in doc.items() if k != "content_hash"})
            return doc
        untrue = {**self.brief_document(), "content_hash": h("9")}
        cases = (("numbered 2", {"document": self.brief_document(version=2)}, "request_invalid", "is 1, with parent None"),
                 ("numbered 2 with no parent", {"document": unparented_two()}, "request_invalid", "is 1, with parent None"),
                 ("created after now", {"document": self.brief_document(created_at="2026-09-27T11:00:00Z")}, "request_invalid", "created by now"),
                 ("reviewed by a deadline already over", {"document": self.brief_document(), "review_deadline": "2026-09-27T09:59:59Z"}, "request_invalid",
                  "reviewed after now"),
                 ("of an unknown topic", {"document": self.brief_document("fleet-a:t9")}, "unknown_topic", "fleet-a:t9"),
                 ("with an untrue hash", {"document": untrue}, "request_invalid", "does not hash to its content hash"))
        for label, request, reason, detail in cases:
            with self.subTest(label):
                before = self.state()
                out = self.router.open_brief({"owner_operator_id": "user", "review_deadline": REVIEW_BY, **request})
                self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
                self.assertIn(detail, out.get("detail", ""))
                self.assertEqual(self.state(), before)


# ---------------------------------------------------------------------------
# contract construction's drafts, through approval
# ---------------------------------------------------------------------------
class ContractDraftTest(Workflow):
    def test_a_first_draft_and_its_rated_successor_are_written_with_their_rows(self) -> None:
        self.open_brief()
        self.confirm()
        r1, r2 = contract(1, None, rated=False), contract(2, 1)
        self.assertEqual(self.draft(r1), {"status": "recorded", "topic_id": TOPIC, "revision": 1, "against_approved": None})
        self.rate(r2)
        self.assertEqual(self.draft(r2)["status"], "recorded")
        self.assertEqual(self.rows("SELECT revision, parent_revision, protocol_revision, framing_version, content_hash, status, approved_by_decision_id "
                                   "FROM contract_revisions WHERE topic_id = ? ORDER BY revision", TOPIC),
                         [(1, None, 1, 1, r1["content_hash"], "draft", None), (2, 1, 1, 1, r2["content_hash"], "draft", None)])
        self.assertEqual(self.rows("SELECT contract_revision, facet_id, operator_importance_band, operator_importance_score, operator_rating_decision_id "
                                   "FROM facets WHERE topic_id = ? ORDER BY contract_revision, facet_id", TOPIC),
                         [(1, "F-cost", None, None, None), (1, "F-effect", None, None, None),
                          (2, "F-cost", "important", None, "opd_rate0001"), (2, "F-effect", "critical", 8, "opd_rate0001")])
        self.assertEqual(self.rows("SELECT contract_revision, obligation_id, operator_importance_band FROM obligations WHERE topic_id = ? ORDER BY 1, 2", TOPIC),
                         [(1, "O-1", None), (1, "O-2", None), (2, "O-1", "critical"), (2, "O-2", "important")])
        before = self.state()
        self.assertEqual(self.draft(r2)["status"], "replayed")
        self.assertEqual(self.state(), before)

    def test_the_rated_draft_is_approved_and_the_topic_queued(self) -> None:
        r2 = self.rated_drafts()
        self.scope_approved()
        self.assertEqual(self.approve(r2)["status"], "applied")
        self.assertEqual(self.rows("SELECT status, active_contract_revision FROM queue_entries WHERE topic_id = ?", TOPIC), [("queued", 2)])
        self.assertEqual(self.rows("SELECT revision, status, approved_by_decision_id FROM contract_revisions WHERE topic_id = ? ORDER BY revision", TOPIC),
                         [(1, "draft", None), (2, "approved", "opd_cntrt102")])

    def test_a_first_approval_is_the_s3_hand_off(self) -> None:
        """A topic's first approval moves it awaiting_contract_approval ->
        queued, and only that: approved while still scoping, it would hold an
        approved contract no work can be claimed under."""
        r2 = self.rated_drafts()
        before = self.state()
        out = self.approve(r2)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "decision_refused"), out)
        self.assertIn("the topic is scoping; this decision moves it only from ['awaiting_contract_approval'", out.get("detail", ""))
        self.assertEqual(self.state(), before)
        self.scope_approved()
        self.assertEqual(self.approve(r2)["status"], "applied")
        self.assertEqual(self.status(), "queued")

    def test_an_unrated_draft_is_not_approved(self) -> None:
        """G-2/G-3: approval needs every facet operator-rated."""
        self.open_brief()
        self.confirm()
        r1 = contract(1, None, rated=False)
        self.draft(r1)
        self.scope_approved()
        before = self.state()
        out = self.approve(r1)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "decision_refused"), out)
        self.assertIn("every facet operator-rated", out.get("detail", ""))
        self.assertEqual(self.state(), before)

    def test_an_uncovered_critical_facet_blocks_approval_and_covering_it_lifts_the_block(self) -> None:
        """G-3: a critical facet no obligation tags is representable as a
        draft and blocks its approval; the next draft, tagging it again, is
        approved."""
        self.open_brief()
        self.confirm()
        self.draft(contract(1, None, rated=False))
        self.rate(contract(2, 1))
        bare = contract(2, 1, edit=uncover_effect)
        self.assertEqual(self.draft(bare)["status"], "recorded")
        self.assertEqual(self.rows("SELECT facet_id FROM uncovered_critical_facets WHERE topic_id = ? AND contract_revision = 2", TOPIC), [("F-effect",)])
        self.scope_approved()
        before = self.state()
        out = self.approve(bare)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "decision_refused"), out)
        self.assertIn("no uncovered critical facet (G-3)", out.get("detail", ""))
        self.assertEqual(self.state(), before)
        covered = contract(3, 2)
        self.assertEqual(self.draft(covered)["status"], "recorded")
        self.assertEqual(self.approve(covered)["status"], "applied")
        self.assertEqual(self.rows("SELECT status, active_contract_revision FROM queue_entries WHERE topic_id = ?", TOPIC), [("queued", 3)])

    def test_a_rating_is_exactly_what_the_operator_rated(self) -> None:
        """G-2: a draft's rating cites the operator's rating of a draft it
        descends from, with exactly its band and score."""
        self.open_brief()
        self.confirm()
        def rerated(doc: dict) -> None:
            doc["facet_map"]["facets"][0]["importance"]["operator_rating"] = {"band": "important", "score": 5, "operator_decision_id": "opd_rate0001"}
        with self.subTest("a first draft carrying a rating: no draft was rated before it"):
            before = self.state()
            out = self.draft(contract(1, None))
            self.assertEqual((out["status"], out.get("reason")), ("refused", "request_invalid"), out)
            self.assertIn("exactly what the operator rated", out.get("detail", ""))
            self.assertEqual(self.state(), before)
        self.draft(contract(1, None, rated=False))
        self.rate(contract(2, 1))
        with self.subTest("a band and score the operator did not give"):
            before = self.state()
            out = self.draft(contract(2, 1, edit=rerated))
            self.assertEqual((out["status"], out.get("reason")), ("refused", "request_invalid"), out)
            self.assertIn("exactly what the operator rated", out.get("detail", ""))
            self.assertEqual(self.state(), before)
        self.assertEqual(self.draft(contract(2, 1))["status"], "recorded")

    def test_each_defect_is_refused_alone(self) -> None:
        def reworded(doc: dict) -> None:  # a framing change under the framing version it had
            doc["facet_map"]["analytic_framework"]["links"][0]["key_question"] = "Which facets does intake design cause to be missed?"
        before = self.state()
        out = self.draft(contract(1, None, topic=OTHER, rated=False))
        self.assertEqual((out["status"], out.get("reason")), ("refused", "brief_unconfirmed"), out)  # OTHER is at intake
        self.assertEqual(self.state(), before)
        self.open_brief()
        self.confirm()
        cases = [("a first draft numbered 2", contract(2, 1, rated=False), "request_invalid", "this draft is revision 1, with parent None"),
                 ("of an unknown topic", contract(1, None, topic="fleet-a:t9", rated=False), "unknown_topic", "fleet-a:t9"),
                 ("with an untrue hash", {**contract(1, None, rated=False), "content_hash": h("9")}, "request_invalid", "does not hash")]
        for label, doc, reason, detail in cases:
            with self.subTest(label):
                before = self.state()
                out = self.draft(doc)
                self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
                self.assertIn(detail, out.get("detail", ""))
                self.assertEqual(self.state(), before)
        self.draft(contract(1, None, rated=False))
        self.rate(contract(2, 1))
        self.draft(contract(2, 1))
        cases = [("a draft not revising the newest", contract(3, 1), "request_invalid", "this draft is revision 3, with parent 2"),
                 ("a draft skipping a revision", contract(4, 2), "request_invalid", "this draft is revision 3, with parent 2"),
                 ("a changed framing under its version", contract(3, 2, edit=reworded), "request_invalid", "takes a new framing version")]
        for label, doc, reason, detail in cases:
            with self.subTest(label):
                before = self.state()
                out = self.draft(doc)
                self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
                self.assertIn(detail, out.get("detail", ""))
                self.assertEqual(self.state(), before)
        self.assertEqual(self.draft(contract(3, 2))["status"], "recorded")  # the accepted draft beside them

    def test_drafting_ends_at_the_first_approval_and_amending_starts_there(self) -> None:
        self.open_brief()
        self.confirm()
        self.draft(contract(1, None, rated=False))
        self.rate(contract(2, 1))
        before = self.state()
        out = self.router.propose_amendment({"document": contract(2, 1)})
        self.assertEqual((out["status"], out.get("reason")), ("refused", "no_approved_contract"), out)
        self.assertEqual(self.state(), before)
        r2 = contract(2, 1)
        self.draft(r2)
        self.scope_approved()
        self.approve(r2)
        before = self.state()
        out = self.draft(contract(3, 2))
        self.assertEqual((out["status"], out.get("reason")), ("refused", "contract_approved"), out)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.router.propose_amendment({"document": contract(3, 2)})["status"], "recorded")


# ---------------------------------------------------------------------------
# works
# ---------------------------------------------------------------------------
class WorkRegistrationTest(Workflow):
    def setUp(self) -> None:
        super().setUp()
        self.to_queued()
        self.grant = self.started("inv_research01")
        self.events = self.observe(self.grant, "obs_t1search01", ("rec-1", "rec-2"))

    def test_records_are_linked_to_their_work_by_identity(self) -> None:
        wid = work_of("doi", "10.1/x")
        out = self.register(self.grant, [("doi", "10.1/x", self.events)])
        self.assertEqual(out, {"status": "recorded", "works": [{"work_id": wid, "identity_scheme": "doi", "identity_value": "10.1/x"}]})
        self.assertEqual(self.rows("SELECT work_id, identity_scheme, identity_value, study_group_id FROM works"), [(wid, "doi", "10.1/x", None)])
        self.assertEqual(self.rows("SELECT event_id, work_id, dedup_method_version FROM record_work_links ORDER BY event_id"),
                         [(self.events[0], wid, "dedup-1"), (self.events[1], wid, "dedup-1")])
        before = self.state()
        self.assertEqual(self.register(self.grant, [("doi", "10.1/x", self.events)]), {**out, "status": "replayed"})
        self.assertEqual(self.state(), before)

    def test_a_work_two_topics_retrieve_is_one_row(self) -> None:
        self.to_queued(OTHER)
        other = self.started("inv_research02", tid=OTHER)
        theirs = self.observe(other, "obs_t2search01", ("rec-1",))
        self.register(self.grant, [("doi", "10.1/x", self.events)])
        self.assertEqual(self.register(other, [("doi", "10.1/x", theirs)]).get("works", [{}])[0].get("work_id"), work_of("doi", "10.1/x"))
        self.assertEqual(self.value("SELECT count(*) FROM works"), 1)
        self.assertEqual(self.rows("SELECT e.topic_id, count(*) FROM record_work_links l JOIN retrieval_events e USING (event_id) GROUP BY 1 ORDER BY 1"),
                         [(TOPIC, 2), (OTHER, 1)])

    def test_a_recorded_identity_keeps_its_id(self) -> None:
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000001', 'doi', '10.1/y', '2026-09-27T09:00:00Z')")
        out = self.register(self.grant, [("doi", "10.1/y", self.events[:1])])
        self.assertEqual((out["status"], out.get("works", [{}])[0].get("work_id")), ("recorded", "wrk_00000001"), out)
        self.assertEqual(self.value("SELECT count(*) FROM works"), 1)

    def test_a_record_maps_to_one_work(self) -> None:
        self.register(self.grant, [("doi", "10.1/x", self.events)])
        for label, works, version in (("to another work", [("doi", "10.1/z", self.events[:1])], "dedup-1"),
                                      ("under another dedup method", [("doi", "10.1/x", self.events[:1])], "dedup-2")):
            with self.subTest(label):
                before = self.state()
                out = self.register(self.grant, works, version)
                self.assertEqual((out["status"], out.get("reason")), ("refused", "work_link_conflict"), out)
                self.assertEqual(self.state(), before)

    def test_each_defect_is_refused_alone(self) -> None:
        self.to_queued(OTHER)
        theirs = self.observe(self.started("inv_research02", tid=OTHER), "obs_t2search01", ("rec-9",))
        cases = (("another topic's record", [("doi", "10.1/x", theirs)], "cross_topic", theirs[0]),
                 ("an unknown record", [("doi", "10.1/x", ["rev_nothere0001"])], "unknown_event", "rev_nothere0001"),
                 ("a record in two works", [("doi", "10.1/x", self.events[:1]), ("doi", "10.1/z", self.events[:1])], "request_invalid",
                  "each retrieved record maps to one work"),
                 ("a work named twice", [("doi", "10.1/x", self.events[:1]), ("doi", "10.1/x", self.events[1:])], "request_invalid", "each work is named once"),
                 ("a work of no record", [("doi", "10.1/x", [])], "request_invalid", "router-commands#/$defs/works"),
                 ("an identity scheme of no kind", [("isni", "0000", self.events)], "request_invalid", "router-commands#/$defs/works"))
        for label, works, reason, detail in cases:
            with self.subTest(label):
                before = self.state()
                out = self.register(self.grant, works)
                self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
                self.assertIn(detail, out.get("detail", ""))
                self.assertEqual(self.state(), before)

    def refused(self, reason: str, detail: str) -> None:
        before = self.state()
        out = self.register(self.grant, [("doi", "10.1/x", self.events)])
        self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
        self.assertIn(detail, out.get("detail", ""))
        self.assertEqual(self.state(), before)

    def test_a_paused_topic_registers_nothing(self) -> None:
        self.x("UPDATE queue_entries SET paused_at = '2026-09-27T10:00:00Z' WHERE topic_id = ?", TOPIC)
        self.refused("topic_paused", TOPIC)

    def test_work_past_its_lease_registers_nothing(self) -> None:
        self.clock.set(rf.EXPIRES)
        self.refused("lease_not_current", "expired")

    def test_work_asked_to_cancel_registers_nothing(self) -> None:
        self.assertEqual(self.router.request_cancel({"invocation_id": "inv_research01", "requested_by": "operator", "reason": "stop"})["status"], "recorded")
        self.refused("invocation_state_invalid", "cancellation")

    def test_work_no_longer_running_registers_nothing(self) -> None:
        self.ready(self.grant, self.stage(empty_outcome("inv_research01"))[0])
        self.refused("invocation_state_invalid", "not result_ready")

    def test_a_lost_reply_is_answered_after_the_work_ended(self) -> None:
        first = self.register(self.grant, [("doi", "10.1/x", self.events)])
        self.assertEqual(self.finish(self.grant, "op_final000001")["status"], "committed")
        before = self.state()
        self.assertEqual(self.register(self.grant, [("doi", "10.1/x", self.events)]), {**first, "status": "replayed"})
        self.assertEqual(self.state(), before)


# ---------------------------------------------------------------------------
# claim-source links
# ---------------------------------------------------------------------------
class ClaimSourceLinkTest(Workflow):
    """The link outcome operation, under revision 2 (drafted and approved
    through the router): a research pass has retrieved and registered
    doi 10.1/x."""

    def setUp(self) -> None:
        super().setUp()
        self.approved()
        self.grant = self.started("inv_research01")
        self.register(self.grant, [("doi", "10.1/x", self.observe(self.grant, "obs_t1search01", ("rec-1",)))])

    def test_a_link_is_written_for_a_claim_of_the_pinned_revision(self) -> None:
        out = self.capture(self.grant, "op_capture0001", claim_source_links=[link()])
        self.assertEqual(out["status"], "committed", out)
        self.assertEqual(self.rows("SELECT claim_id, claim_revision, work_id, source_version, topic_id, contract_revision, obligation_id, spans, contribution, "
                                   "evidence_origin_lineage, analytical_method, created_at IS NOT NULL FROM claim_source_links"),
                         [("clm_00000001", 1, work_of("doi", "10.1/x"), "v1", TOPIC, 2, "O-1", '[{"end":42,"locator":{"kind":"page","value":"3"},"start":10}]',
                           "answer", "study-1", None, 1)])
        checkpoint = self.started("inv_checkpt01", "checkpoint")  # another primary of the revision links the claim to another obligation
        self.assertEqual(self.capture(checkpoint, "op_linkckpt01", claim=None, claim_source_links=[link(obligation="O-2")])["status"], "committed")
        self.assertEqual(self.value("SELECT count(*) FROM claim_source_links"), 2)

    def test_each_defect_is_refused_alone(self) -> None:
        self.to_queued(OTHER)
        other = self.started("inv_research02", tid=OTHER)
        self.assertEqual(self.capture(other, "op_othercap01", claim="clm_other00001")["status"], "committed")
        self.register(other, [("doi", "10.1/z", self.observe(other, "obs_t2search01", ("rec-9",)))])
        self.assertEqual(self.capture(self.grant, "op_capture0001")["status"], "committed")
        cases = (("an unrecorded claim", link(claim="clm_nothere0001"), "payload_invalid", "is not recorded"),
                 ("another topic's claim", link(claim="clm_other00001"), "cross_topic", "another topic's claim"),
                 ("an obligation of no pinned revision", link(obligation="O-9"), "payload_invalid", "O-9 is not an obligation of contract revision 2"),
                 ("an unregistered work", link(work="wrk_nothere00001"), "payload_invalid", "no record fleet-a:t1 retrieved"),
                 ("a work only another topic retrieved", link(work=work_of("doi", "10.1/z")), "cross_topic", "no record fleet-a:t1 retrieved"))
        for n, (label, entry, reason, detail) in enumerate(cases):
            with self.subTest(label):
                self.refused_commit(self.grant, f"op_badlink{n:04d}", reason, detail, claim_source_links=[entry])
        with self.subTest("a verifier"):
            verifier = self.started("inv_verify001", "verification")
            self.refused_commit(verifier, "op_verlink0001", "kind_not_permitted", "cannot commit claim_source_links", claim_source_links=[link()])



class ScopingClaimLinkTest(Workflow):
    def test_a_scoping_claim_is_linked_only_once_admitted_work_adopts_it(self) -> None:
        """C-12, V-10: a claim captured by pre-contract scoping links to no
        obligation; the contract-admitted revision adopting it does."""
        self.open_brief()
        self.confirm()
        scoping = self.started("inv_scoping01")  # pre-contract/1: the topic is scoping
        with self.subTest("scoping work links nothing"):
            self.refused_commit(scoping, "op_scopelnk01", "kind_not_permitted", "pre-contract/1 work records scoping material only",
                                claim_source_links=[link(claim="clm_scope00001")])
        self.assertEqual(self.capture(scoping, "op_scopecap01", claim="clm_scope00001")["status"], "committed")
        self.assertEqual(self.finish(scoping, "op_scopefin01")["status"], "committed")
        r2 = contract(2, 1)
        self.draft(contract(1, None, rated=False))
        self.rate(r2)
        self.draft(r2)
        self.scope_approved()
        self.approve(r2)
        admitted = self.started("inv_research01")
        self.register(admitted, [("doi", "10.1/x", self.observe(admitted, "obs_t1search01", ("rec-1",)))])
        with self.subTest("admitted work links the scoping revision"):
            self.refused_commit(admitted, "op_scopelnk02", "payload_invalid", "was not produced by work admitted under contract revision 2",
                                claim_source_links=[link(claim="clm_scope00001")])
        adopted = self.capture(admitted, "op_adopt00001", claim="clm_scope00001", revision=2, claim_source_links=[link(claim="clm_scope00001", revision=2)])
        self.assertEqual(adopted["status"], "committed", adopted)
        self.assertEqual(self.rows("SELECT claim_id, claim_revision, contract_revision FROM claim_source_links"), [("clm_scope00001", 2, 2)])


# ---------------------------------------------------------------------------
# review closure and code-policy signals
# ---------------------------------------------------------------------------
def signal(cause: str = "retraction-notice-7", *, reason: str = "retraction", source: str = "deterministic", revision: int = 1,
           observed: str = "2026-09-27T09:50:00Z", tid: str = TOPIC) -> dict:
    return {"topic_id": tid, "reason_code": reason, "signal_source": source, "cause_ref": cause, "source_revision": revision, "observed_at": observed}


class SignalTest(Workflow):
    def setUp(self) -> None:
        super().setUp()
        self.to_queued()

    def test_a_signal_is_queued_pending_and_opens_its_review(self) -> None:
        identity = jcs_hash('{"cause_ref":"retraction-notice-7","reason_code":"retraction","source_revision":1,"topic_id":"fleet-a:t1"}')
        self.assertEqual(self.router.raise_signal(signal()), {"status": "recorded", "trigger_identity": identity, "episode_id": None, "handled_at": None})
        self.assertEqual(self.rows("SELECT trigger_identity, topic_id, reason_code, signal_source, cause_ref, observed_at, recorded_by_operation_id, episode_id, "
                                   "handled_at FROM review_triggers"),
                         [(identity, TOPIC, "retraction", "deterministic", "retraction-notice-7", "2026-09-27T09:50:00Z", None, None, None)])
        out = self.router.open_review({"episode_id": "rev_episode0001", "topic_id": TOPIC, "kind": "method_fit"})  # the bundle sets no signal-queue budget
        self.assertEqual((out["status"], out["triggers"]), ("opened", [identity]), out)

    def test_the_operator_raises_a_decision_record_change(self) -> None:
        self.assertEqual(self.router.raise_signal(signal("brief-1 feeds changed", reason="decision_record_change", source="operator"))["status"], "recorded")
        self.assertEqual(self.rows("SELECT reason_code, signal_source FROM review_triggers"), [("decision_record_change", "operator")])

    def test_the_same_signal_reported_again_collides(self) -> None:
        first = self.router.raise_signal(signal())
        before = self.state()
        self.assertEqual(self.router.raise_signal(signal(observed="2026-09-27T09:55:00Z")), {**first, "status": "replayed"})
        self.assertEqual(self.state(), before)
        self.assertEqual(self.router.raise_signal(signal(revision=2))["status"], "recorded")  # another source revision is another signal
        self.assertEqual(self.value("SELECT count(*) FROM review_triggers"), 2)

    def test_each_defect_is_refused_alone(self) -> None:
        cases = (("a model's observation", signal(source="primary_observation"), "request_invalid", "router-commands#/$defs/signal"),
                 ("a discretionary reason", signal(reason="persistent_contradiction"), "request_invalid", "router-commands#/$defs/signal"),
                 ("observed after now", signal(observed="2026-09-27T11:00:00Z"), "request_invalid", "observed by now"),
                 ("of an unknown topic", signal(tid="fleet-a:t9"), "unknown_topic", "fleet-a:t9"),
                 ("already attached to an episode", {**signal(), "episode_id": "rev_episode0001"}, "request_invalid", "router-commands#/$defs/signal"))
        for label, request, reason, detail in cases:
            with self.subTest(label):
                before = self.state()
                out = self.router.raise_signal(request)
                self.assertEqual((out["status"], out.get("reason")), ("refused", reason), out)
                self.assertIn(detail, out.get("detail", ""))
                self.assertEqual(self.state(), before)


class ReviewClosureTest(Workflow):
    """A research pass has observed a contradiction, code policy raised a
    retraction, and a method-fit review took both; a checkpoint admitted
    after it opened closes it."""

    def setUp(self) -> None:
        super().setUp()
        self.to_queued()
        self.research = self.started("inv_research01")
        trigger = {"reason_code": "persistent_contradiction", "cause_ref": "clm_a vs clm_b", "source_revision": 0, "observed_at": "2026-09-27T09:55:00Z"}
        self.assertEqual(self.capture(self.research, "op_trigger0001", claim=None, review_triggers=[trigger])["status"], "committed")
        self.router.raise_signal(signal())
        self.triggers = self.router.open_review({"episode_id": "rev_episode0001", "topic_id": TOPIC, "kind": "method_fit"})["triggers"]
        self.checkpoint = self.started("inv_checkpt01", "checkpoint")

    def test_the_checkpoint_closes_its_episode_and_handles_its_triggers(self) -> None:
        later = {"reason_code": "definitional_disagreement", "cause_ref": "term X", "source_revision": 2, "observed_at": "2026-09-27T09:58:00Z"}
        self.capture(self.research, "op_trigger0002", claim=None, review_triggers=[later])  # after the episode opened: it waits for the next
        out = self.capture(self.checkpoint, "op_closure0001", claim=None, review_closures=[{"episode_id": "rev_episode0001"}])
        self.assertEqual(out["status"], "committed", out)
        closed = self.rows("SELECT closed_at, closed_by_operation_id FROM review_episodes WHERE episode_id = 'rev_episode0001'")
        self.assertEqual(closed[0][1], "op_closure0001")
        self.assertEqual(sorted(self.rows("SELECT trigger_identity, episode_id, handled_at FROM review_triggers WHERE episode_id IS NOT NULL")),
                         sorted((t, "rev_episode0001", closed[0][0]) for t in self.triggers))
        self.assertEqual(self.rows("SELECT reason_code, episode_id, handled_at FROM review_triggers WHERE episode_id IS NULL"), [("definitional_disagreement", None, None)])

    def test_each_defect_is_refused_alone(self) -> None:
        self.to_queued(OTHER)
        self.router.open_review({"episode_id": "rev_episode0002", "topic_id": OTHER, "kind": "fixed_cadence"})
        self.router.open_review({"episode_id": "rev_episode0003", "topic_id": TOPIC, "kind": "fixed_cadence"})  # opened after the checkpoint was admitted
        cases = ((self.research, "a research pass", "rev_episode0001", "kind_not_permitted", "cannot commit review_closures"),
                 (self.checkpoint, "an unknown episode", "rev_nothere0001", "payload_invalid", "is not a review episode of fleet-a:t1"),
                 (self.checkpoint, "another topic's episode", "rev_episode0002", "cross_topic", "is not a review episode of fleet-a:t1"),
                 (self.checkpoint, "an episode opened after the checkpoint's admission", "rev_episode0003", "payload_invalid", "opened after inv_checkpt01"))
        for n, (grant, label, episode, reason, detail) in enumerate(cases):
            with self.subTest(label):
                self.refused_commit(grant, f"op_badclose{n:03d}", reason, detail, review_closures=[{"episode_id": episode}])
        self.assertEqual(self.capture(self.checkpoint, "op_closure0001", claim=None, review_closures=[{"episode_id": "rev_episode0001"}])["status"], "committed")
        with self.subTest("an episode already closed"):
            self.refused_commit(self.checkpoint, "op_closure0002", "payload_invalid", "was closed by op_closure0001", review_closures=[{"episode_id": "rev_episode0001"}])

    def test_a_handled_signal_reported_again_opens_nothing(self) -> None:
        """RG-1b(e): after the episode closed, the same retraction and the same
        observation collide with their handled triggers; no review opens."""
        self.capture(self.checkpoint, "op_closure0001", claim=None, review_closures=[{"episode_id": "rev_episode0001"}])
        before = self.state()
        replay = self.router.raise_signal(signal(observed="2026-09-27T09:59:00Z"))
        self.assertEqual((replay["status"], replay.get("episode_id")), ("replayed", "rev_episode0001"))
        self.assertIsNotNone(replay.get("handled_at"))
        trigger = {"reason_code": "persistent_contradiction", "cause_ref": "clm_a vs clm_b", "source_revision": 0, "observed_at": "2026-09-27T09:59:00Z"}
        self.assertEqual(self.capture(self.research, "op_trigger0003", claim=None, review_triggers=[trigger])["receipt"]["effects"]["trigger_identities"], [])
        out = self.router.open_review({"episode_id": "rev_episode0009", "topic_id": TOPIC, "kind": "method_fit"})
        self.assertEqual((out["status"], out.get("reason")), ("refused", "no_pending_signal"), out)
        self.assertEqual(self.rows("SELECT count(*), count(handled_at) FROM review_triggers"), [(2, 2)])
        after = self.state()
        self.assertEqual([after[t] for t in ("review_triggers", "review_episodes")], [before[t] for t in ("review_triggers", "review_episodes")])


# ---------------------------------------------------------------------------
# one topic, end to end
# ---------------------------------------------------------------------------
E2E = "fleet-e:intake-latency"
RESEARCH, CHECKPOINT = "inv_e2eresearch1", "inv_e2echeckpt01"


class EndToEndTest(sf.SupervisedTestCase, Workflow):
    """Topic -> brief -> contract drafts -> approval -> admitted research ->
    claim -> link -> review closure, on a durable store and the real spool,
    through router operations only but one raw-SQL step (the committed
    scoping report: module docstring). The research pass and the checkpoint
    are fake-executor subprocesses under the supervisor; while the research
    pass runs, the test performs, under the job's own capability, the capture
    steps the supervisor does not make yet (a search observation, a work
    registration, an interim claim capture). The decision layer is disabled:
    no decision spec or receipt exists anywhere."""

    def seed(self) -> None:  # only the bundle, activated through the router: no seeded topic
        assert self.router.activate_config_bundle(rf.BUNDLE)["status"] == "activated"

    def to_queued(self, tid: str = TOPIC) -> str:  # the test walks S1-S3 itself
        return ""

    def envelope(self, grant: dict, op: str, outcome: dict, *, refs=(), expected: int | None = None, **overrides) -> dict:
        ref = self.spool.stage(grant["topic_id"], jcs(outcome), "application/json")
        return {"envelope_version": "commit-outcome/1", "operation_id": op, "operation_kind": outcome["operation_kind"], "invocation_id": grant["invocation_id"],
                "capability_id": grant["capability_id"], "topic_id": grant["topic_id"], "admission": grant["admission"],
                "config_bundle_hash": grant["config_bundle_hash"], "lease": {"lease_id": grant["lease"]["lease_id"], "generation": grant["lease"]["generation"]},
                "expected_state_revision": self.state_revision(grant["topic_id"]), "payload_digest": ref["content_hash"], "payload_size_bytes": ref["size_bytes"],
                "result_refs": list(refs), "submitted_at": "2026-09-27T10:30:00Z", **overrides}

    def artifact(self, text: bytes, media_type: str = "text/plain") -> dict:
        return self.spool.stage(E2E, text, media_type)

    def outcome_text(self, inv: str, **sections) -> str:
        return canonical.canonical_bytes({**empty_outcome(inv, topic=E2E), **sections}).decode("utf-8")

    def test_one_topic_from_intake_to_a_closed_review(self) -> None:
        r = self.router
        wid = work_of("doi", "10.1/x")
        # S1: the topic and its brief
        self.assertEqual(r.create_topic({"topic_id": E2E, "priority": 1})["status"], "created")
        self.assertEqual(self.open_brief(E2E)["status"], "recorded")
        self.confirm(E2E)
        self.assertEqual(self.status(E2E), "scoping")
        # S3: drafts, the operator's rating, approval (G-2, G-3)
        r2 = self.rated_drafts_after_confirmation(E2E)
        self.scope_approved(E2E)
        self.assertEqual(self.status(E2E), "awaiting_contract_approval")
        self.assertEqual(self.approve(r2, E2E)["status"], "applied")
        self.assertEqual(self.rows("SELECT status, active_contract_revision FROM queue_entries WHERE topic_id = ?", E2E), [("queued", 2)])
        # S4: an admitted research pass; its final outcome links the claim it captured
        trigger = {"reason_code": "persistent_contradiction", "cause_ref": "clm_e2e0000001 vs its source", "source_revision": 4, "observed_at": "2026-09-27T09:59:00Z"}
        final = self.outcome_text(RESEARCH, next_queue_state="resting", claim_source_links=[link(claim="clm_e2e0000001", work=wid)], review_triggers=[trigger])
        self.supervisor.prepare(self.order("research_pass", [{"op": "wait_for", "name": "gate", "seconds": 60},
                                                             {"op": "write", "name": "outcome.json", "text": final}], inv=RESEARCH, topic=E2E))
        self.assertEqual(self.supervisor.run(RESEARCH, until=("running",)), "running")
        grant = self.journal(RESEARCH)["grant"]
        self.assertEqual(grant["admission"]["context"], "contract/1")
        events = self.observe(grant, "obs_e2esearch1", ("rec-1", "rec-2"))
        self.assertEqual(self.register(grant, [("doi", "10.1/x", events)])["status"], "recorded")
        self.assertEqual(self.capture(grant, "op_e2ecapture1", claim="clm_e2e0000001")["status"], "committed")
        self.gate(RESEARCH)
        self.assertEqual(self.supervisor.run(RESEARCH), "committed")
        self.assertEqual(self.status(E2E), "resting")
        # S5: code policy raises a retraction; a method-fit review takes both signals; a checkpoint closes it
        self.assertEqual(r.raise_signal(signal(wid, tid=E2E))["status"], "recorded")
        opened = r.open_review({"episode_id": "rev_e2eepisode1", "topic_id": E2E, "kind": "method_fit"})
        self.assertEqual(len(opened["triggers"]), 2, opened)
        closure = self.outcome_text(CHECKPOINT, review_closures=[{"episode_id": "rev_e2eepisode1"}])
        self.supervisor.prepare(self.order("checkpoint", [{"op": "write", "name": "outcome.json", "text": closure}], inv=CHECKPOINT, topic=E2E))
        self.assertEqual(self.supervisor.run(CHECKPOINT), "committed")

        # the whole store, read back
        self.assertEqual(self.rows("SELECT status, active_contract_revision, fleet_id FROM queue_entries"), [("resting", 2, "fleet-e")])
        self.assertEqual(self.rows("SELECT version, status FROM intake_briefs"), [(1, "confirmed")])
        self.assertEqual(self.rows("SELECT revision, status FROM contract_revisions ORDER BY revision"), [(1, "draft"), (2, "approved")])
        self.assertEqual(self.rows("SELECT invocation_id, kind, admission_context, contract_revision, state FROM invocations ORDER BY admitted_at"),
                         [(RESEARCH, "research_pass", "contract/1", 2, "committed"), (CHECKPOINT, "checkpoint", "contract/1", 2, "committed")])
        self.assertEqual(self.rows("SELECT claim_id, revision, producer_invocation_id, status FROM claims"), [("clm_e2e0000001", 1, RESEARCH, "provisional")])
        self.assertEqual(self.rows("SELECT work_id, identity_value FROM works"), [(wid, "10.1/x")])
        self.assertEqual(self.value("SELECT count(*) FROM record_work_links WHERE work_id = ?", wid), 2)
        self.assertEqual(self.rows("SELECT claim_id, work_id, topic_id, contract_revision, obligation_id FROM claim_source_links"),
                         [("clm_e2e0000001", wid, E2E, 2, "O-1")])
        checkpoint_op = self.value("SELECT operation_id FROM operation_receipts WHERE invocation_id = ?", CHECKPOINT)
        self.assertEqual(self.rows("SELECT episode_id, closed_by_operation_id FROM review_episodes"), [("rev_e2eepisode1", checkpoint_op)])
        self.assertEqual(self.rows("SELECT reason_code, signal_source, handled_at IS NOT NULL FROM review_triggers ORDER BY reason_code"),
                         [("persistent_contradiction", "primary_observation", 1), ("retraction", "deterministic", 1)])
        self.assertEqual(self.rows("SELECT count(*) FROM decision_specs UNION ALL SELECT count(*) FROM decision_receipts"), [(0,), (0,)])
        self.assertEqual(self.rows("SELECT DISTINCT kind FROM audit_events ORDER BY kind"),
                         [(k,) for k in sorted(("config_bundle_activated", "topic_created", "brief_versioned", "operator_decision", "contract_drafted", "claim",
                                                "transition", "observation", "works_registered", "commit_outcome", "signal_raised", "review_opened"))])
        # the handled retraction reported again opens nothing (RG-1b(e))
        self.assertEqual(r.raise_signal(signal(wid, tid=E2E, observed="2026-09-27T09:58:00Z"))["status"], "replayed")
        refused = r.open_review({"episode_id": "rev_e2eepisode2", "topic_id": E2E, "kind": "method_fit"})
        self.assertEqual((refused["status"], refused.get("reason")), ("refused", "no_pending_signal"))

    def rated_drafts_after_confirmation(self, tid: str) -> dict:
        r2 = contract(2, 1, topic=tid)
        self.assertEqual(self.draft(contract(1, None, topic=tid, rated=False))["status"], "recorded")
        self.assertEqual(self.rate(r2, tid)["status"], "applied")
        self.assertEqual(self.draft(r2)["status"], "recorded")
        return r2

