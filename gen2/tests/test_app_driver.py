"""The driver's walk (T17 PR2). Oracle: the fake supervisor's durable job records (what was submitted, in which order, under which
id) and the printed lines; the real order builder and input writer run unmodified. Limits: the station is a fake with the
router/supervisor/spool calls the driver makes; the real supervisor lifecycle and router commits are T12-B's and T18's witnesses,
and the kits (views, agent step, builders) are stubs.
"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gen2.app import driver, workflow
from gen2.app.workflow import Step
from gen2.core import canonical
from gen2.exec.common import Refused
from gen2.supervisor import jobs as supervisor_jobs

TOPIC = "fleet:topic"
BUNDLE = "sha256:" + "b" * 64
NOW = datetime(2026, 11, 8, 9, 0, 0, tzinfo=timezone.utc)
HASH = "sha256:" + "a" * 64


def scope(n=1):
    return Step("research_pass", "scope", n, "p2")           # brief version 2


def contract(kind, purpose, n=1, context="c1"):
    return Step(kind, purpose, n, context)                  # contract revision 1


def checkpoint(purpose, n=1, episode="rev_one"):
    return Step("checkpoint", purpose, n, f"c1.{episode}")   # the router's review episode id, with the contract revision


def episode(name, opened=1):
    return {"episode_id": name, "kind": "fixed_cadence", "opened_at": f"2026-11-08T0{opened}:00:00Z"}


class Router:
    def __init__(self, world):
        self.world = world

    def status(self, request):
        return {"status": "ok", "topics": [self.world.topic]}

    def config_bundle(self, bundle_hash):
        return self.world.bundle

    def topic_records(self, request):
        if "dossiers" in request["families"] and "dossier_revision" in request:
            if request["dossier_revision"] not in self.world.dossiers:
                return {"status": "refused", "reason": "unknown_dossier"}
        return {"status": "ok", "topic_id": TOPIC, "records": {f: self.world.records.get(f, []) for f in request["families"]}}


class Supervisor:
    def __init__(self, world):
        self.world, self.submitted, self.recovered, self.script = world, [], 0, {}

    jobs_root = property(lambda self: self.world.root / "jobs")

    def job(self, invocation_id):
        return supervisor_jobs.Job(self.jobs_root, "job-" + invocation_id)   # the real durable job files

    def submit(self, order):
        if self.world.fail_submit:
            raise OSError("disk full")
        self.job(order.invocation_id).prepare({"invocation_id": order.invocation_id, "topic_id": order.topic_id, "env": dict(order.env)})
        self.submitted.append(order)
        return "running"

    def advance(self, invocation_id):
        result = self.script.get(invocation_id, "running")
        if result == "committed":
            self.job(invocation_id).write("journal.json", {"settled": "committed", "collected": {"result": {"content_hash": f"sha256:{invocation_id}"}}})
        return result

    def recover(self):
        self.recovered += 1


class Spool:
    def __init__(self, world):
        self.world = world

    def read(self, content_hash, *, topic_id):
        return self.world.blobs.get(content_hash)


class World:
    """One topic, its records, and the stations a driver is built over (a restart is a new station over the same world)."""

    def __init__(self, directory):
        self.root = Path(directory)
        (self.root / "prompts").mkdir()
        pins = []
        for kind, purpose in workflow.LIMITS:
            data = f"prompt for {kind}.{purpose}".encode()
            (self.root / "prompts" / f"{kind}.{purpose}.md").write_bytes(data)
            pins.append({"kind": kind, "purpose": purpose, "prompt": {"version": 1, "content_hash": canonical.bytes_digest(data)}})
        self.bundle = {"policy": {"executors": workflow.executor_entries(pins)}}
        self.topic = {"status": "scoping", "holds": [], "reviews": [], "active_contract_revision": None}
        self.records = {"intake_briefs": [{"brief_id": "brief1", "version": 2, "content_hash": HASH, "status": "confirmed", "confirmed_by_decision_id": "opd_aaaaaaaa"}],
                        "contract_revisions": [{"revision": 1, "content_hash": HASH}]}
        self.blobs, self.dossiers, self.fail_submit, self.said = {}, {}, False, []

    def station(self):
        class Station:
            pass
        station = Station()
        station.router, station.supervisor, station.spool = Router(self), Supervisor(self), Spool(self)
        return station

    def driver(self, station=None, **options):
        class Kit:
            families = ("intake_briefs",)

            def view(self, context, records, truncation):
                return {"step": [context.step.purpose, context.step.ordinal], "admission": context.admission["context"]}
        kits = {key: Kit() for key in workflow.LIMITS}
        return driver.Driver(station or self.station(), topic_id=TOPIC, bundle_hash=BUNDLE, kits=kits, prompt_dir=self.root / "prompts",
                             present=lambda records, read, dossier_revision: {"dossier": {"revision": dossier_revision, "content_hash": HASH, "state": "satisfied", "gates": []},
                                                                              "reviews": [{"outcome": "insufficient", "summary": "claim 2 unsearched", "evidence": []}], "approvable": True},
                             clock=lambda: NOW, sleep=lambda s: None, say=self.said.append, **options)


class DriverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)

    def test_the_first_tick_issues_the_scope_pass_with_its_input_pinned_in_the_order(self):
        station = self.world.station()
        d = self.world.driver(station)
        self.assertEqual(d.tick(), workflow.Issue(scope(1)))
        (order,) = station.supervisor.submitted
        directory = Path(order.command[-1])
        self.assertEqual(directory, station.supervisor.job(order.invocation_id).scratch)   # the one location: the executor's cwd and the collection point
        raw = (directory / "inputs" / "input.json").read_bytes()
        self.assertEqual(order.env["GEN2_INPUT_DIGEST"], canonical.bytes_digest(raw))
        document = json.loads(raw)
        self.assertEqual((document["view"], document["admission"]["context"], document["admission"]["brief"]["version"]),
                         ({"step": ["scope", 1], "admission": "pre-contract/1"}, "pre-contract/1", 2))
        self.assertEqual(order.env["GEN2_PURPOSE"], "research_pass/scope")
        self.assertEqual((directory / "inputs" / "prompt.md").read_bytes(), b"prompt for research_pass.scope")

    def test_a_restart_advances_the_existing_job_and_never_issues_a_second_order(self):
        first = self.world.station()
        self.world.driver(first).tick()
        again = self.world.station()
        d = self.world.driver(again)
        self.assertEqual(d.tick(), workflow.Advance(scope(1)))
        self.assertEqual((len(first.supervisor.submitted), len(again.supervisor.submitted)), (1, 0))

    def test_a_crash_before_the_order_is_durable_leaves_no_job_and_the_same_order_is_built_again(self):
        self.world.fail_submit = True
        with self.assertRaises(OSError):
            self.world.driver().tick()
        self.assertEqual(list((self.world.root / "jobs").glob("*/order.json")), [])   # inputs may be written; no order is durable
        self.world.fail_submit = False
        station = self.world.station()
        self.world.driver(station).tick()
        (order,) = station.supervisor.submitted
        self.assertEqual(order.invocation_id, self.world.driver().invocation_id(scope(1)))

    def test_a_committed_scope_pass_that_proposed_searches_is_followed_by_one_discovery_run(self):
        station = self.world.station()
        d = self.world.driver(station)
        d.tick()
        iid = d.invocation_id(scope(1))
        station.supervisor.script[iid] = "committed"
        self.world.blobs[f"sha256:{iid}"] = canonical.canonical_bytes({"search_proposals": [{"proposal_id": "p1"}]})
        self.assertEqual(d.tick(), workflow.Advance(scope(1)))   # settles the job
        self.assertEqual(d.tick(), workflow.Issue(Step("discovery", "search", 1, "p2")))
        self.assertEqual([o.env["GEN2_PURPOSE"] for o in station.supervisor.submitted], ["research_pass/scope", "discovery/search"])

    def test_a_failed_or_incident_holding_job_stops_the_walk_instead_of_being_retried(self):
        d = self.world.driver()
        iid = d.invocation_id(scope(1))
        for journal, state in (({"settled": "failed"}, "failed"), ({"exhausted": {"kind": "retry_exhausted"}}, "held"), ({"incident": {"kind": "x"}}, "held"),
                               ({"settled": "cancelled"}, "failed"), ({}, "live")):
            with self.subTest(journal):
                self.put(iid, journal)
                self.assertEqual(d.get(scope(1)).state, state)
        self.put(iid, {"exhausted": {"kind": "retry_exhausted"}})
        self.assertEqual(d.tick(), workflow.Stop("research_pass/scope #1 is held"))

    def test_an_open_hold_stops_the_walk_before_anything_is_issued(self):
        self.world.topic["holds"] = [{"hold_id": "hold_unknownspend", "clears_when": "an operator resolves the unknown spend"}]
        station = self.world.station()
        action = self.world.driver(station).tick()
        self.assertEqual(action, workflow.Stop("open hold hold_unknownspend: an operator resolves the unknown spend"))
        self.assertEqual(station.supervisor.submitted, [])

    def test_a_step_that_needs_a_person_stops_the_walk_and_a_running_one_keeps_it_going(self):
        station = self.world.station()
        d = self.world.driver(station)
        d.tick()
        iid = d.invocation_id(scope(1))
        for result in driver.HALTS:
            with self.subTest(result):
                station.supervisor.script[iid] = result
                self.assertIsInstance(d.tick(), workflow.Stop)
        station.supervisor.script[iid] = "running"
        self.assertIn("still working after 3 ticks", d.run(max_ticks=3))

    def test_run_recovers_first_and_prints_the_wait_for_the_operator(self):
        self.world.topic["status"] = "awaiting_scope_approval"
        station = self.world.station()
        text = self.world.driver(station).run()
        line = "waiting for: the scoping report awaits approval; run: apply_operator_decision kind=scope_approval"
        self.assertEqual((station.supervisor.recovered, text, self.world.said), (1, line, [line]))

    REVIEW = {"kind": "sufficiency_review", "subject_ref": TOPIC, "subject_revision": 2, "subject_hash": HASH}

    def put(self, iid, journal):
        """A job's journal as the supervisor would leave it. The order is whatever the driver submitted, or a bare one for a job it
        never issued; this helper adds no field to an order."""
        job = supervisor_jobs.Job(self.world.root / "jobs", "job-" + iid)
        if job.read("order.json") is None:
            job.prepare({"invocation_id": iid, "topic_id": TOPIC, "env": {}})
        job.write("journal.json", journal)

    def settle(self, d, step, proposals=False):
        iid = d.invocation_id(step)
        self.put(iid, {"settled": "committed", "collected": {"result": {"content_hash": f"sha256:{iid}"}}})
        if proposals:
            self.world.blobs[f"sha256:{iid}"] = canonical.canonical_bytes({"search_proposals": [{"proposal_id": "p1"}]})

    def commit(self, d, *steps, proposals=()):
        """Each step is ISSUED through the driver's own submission path, then only the journal says it settled."""
        for step in steps:
            d.issue(step, self.world.topic)
            self.settle(d, step, step in proposals)

    def test_the_completion_wait_prints_the_review_and_its_evidence_for_the_dossier_the_review_is_bound_to(self):
        self.world.topic.update(status="resting", active_contract_revision=1, reviews=[])
        self.world.dossiers = {1: {}, 2: {}, 3: {}}      # a later dossier exists; the review, and so the approval, is of revision 2
        self.world.records["completion_records"] = [self.REVIEW]
        d = self.world.driver()
        self.commit(d, contract("research_pass", "research"), contract("verification", "verify"), checkpoint("challenge"), checkpoint("dossier"), checkpoint("review"))
        text = d.run()
        for fragment in ("run: apply_operator_decision kind=completion_approval", "dossier revision 2", "review insufficient: claim 2 unsearched"):
            self.assertIn(fragment, text)

    def test_a_completion_wait_that_cannot_show_the_review_is_refused_not_printed_bare(self):
        self.world.topic.update(status="resting", active_contract_revision=1)
        d = self.world.driver()
        self.commit(d, contract("research_pass", "research"), contract("verification", "verify"), checkpoint("challenge"), checkpoint("dossier"), checkpoint("review"))
        self.assertIn("stopped: cannot show the review for approval: no sufficiency review is recorded", d.run())   # no review row
        self.world.records["completion_records"] = [self.REVIEW]
        self.world.dossiers = {}                                                                                      # review bound to a dossier the router lacks
        self.assertIn("stopped: cannot show the review for approval", d.run())

    def test_the_latest_dossier_is_found_past_fifty_and_only_unknown_dossier_ends_the_history(self):
        self.world.dossiers = dict.fromkeys(range(1, 61), {})
        self.assertEqual(self.world.driver().dossier_revision(), 60)
        self.world.dossiers = {}
        self.assertIsNone(self.world.driver().dossier_revision())
        d = self.world.driver()
        d.station.router.topic_records = lambda request: {"status": "refused", "reason": "store_busy"}
        with self.assertRaises(Refused):
            d.dossier_revision()

    def test_the_scoping_and_research_phases_do_not_share_a_discovery_identity(self):
        """Scoping discovery #1 is committed; the contract's research proposed searches, so ITS discovery #1 is next, not verification."""
        d = self.world.driver()
        self.commit(d, scope(1), Step("discovery", "search", 1, "p2"), contract("research_pass", "research"), proposals=[scope(1), contract("research_pass", "research")])
        self.world.topic.update(status="queued", active_contract_revision=1)
        self.assertEqual(d.tick(), workflow.Issue(Step("discovery", "search", 1, "c1")))
        self.assertNotEqual(d.invocation_id(Step("discovery", "search", 1, "p2")), d.invocation_id(Step("discovery", "search", 1, "c1")))

    def finished_epoch(self, d, name="rev_old"):
        self.commit(d, contract("research_pass", "research"), contract("verification", "verify"),
                    *[checkpoint(p, episode=name) for p in ("challenge", "dossier", "review")])

    def test_a_different_episode_with_an_unchanged_review_count_starts_a_new_checkpoint(self):
        """The router's episode id, not any count of records, says which checkpoint this is."""
        self.world.topic.update(status="resting", active_contract_revision=1, reviews=[episode("rev_new")])
        self.world.records["completion_records"] = [self.REVIEW]
        d = self.world.driver()
        self.finished_epoch(d)
        self.assertEqual(d.tick(), workflow.Issue(checkpoint("challenge", episode="rev_new")))
        self.world.records["completion_records"] = []                                   # the count differs, the answer does not
        self.assertEqual(self.world.driver().tick(), workflow.Advance(checkpoint("challenge", episode="rev_new")))

    def test_one_challenge_issued_by_tick_is_followed_through_closure_dossier_and_review_settlement(self):
        """Everything is issued by tick(); between ticks only router/journal facts change: the episode closes, a review row appears."""
        self.world.topic.update(status="queued", active_contract_revision=1, reviews=[episode("rev_one")])
        self.world.records["completion_records"] = []
        d = self.world.driver()
        issued, action = [], None
        for _ in range(12):
            action = d.tick()
            if not isinstance(action, workflow.Issue):
                break
            issued.append(action.step)
            self.settle(d, action.step)
            if action.step == checkpoint("challenge"):
                self.world.topic["reviews"] = []                      # the challenge commit closed its episode
            if action.step == checkpoint("review"):
                self.world.records["completion_records"] = [self.REVIEW]
        self.assertEqual(issued, [contract("research_pass", "research"), contract("verification", "verify"), checkpoint("challenge"),
                                  checkpoint("dossier"), checkpoint("review")])
        self.assertEqual(action, workflow.Wait(*workflow.COMPLETION_WAIT))
        stored = self.world.driver(self.world.station()).station.supervisor.job(d.invocation_id(checkpoint("challenge"))).read("order.json")
        self.assertEqual({k: stored["env"][k] for k in ("GEN2_CONTEXT", "GEN2_STEP", "GEN2_PURPOSE")},
                         {"GEN2_CONTEXT": "c1.rev_one", "GEN2_STEP": "checkpoint/challenge#1", "GEN2_PURPOSE": "checkpoint/challenge"})
        self.assertIn("GEN2_INPUT_DIGEST", stored["env"])      # the entries build_order set are kept beside the binding

    def test_with_no_new_episode_the_finished_checkpoint_waits_for_approval_not_for_a_review(self):
        self.world.topic.update(status="resting", active_contract_revision=1, reviews=[])
        d = self.world.driver()
        self.finished_epoch(d)
        self.assertEqual(d.tick(), workflow.Wait(*workflow.COMPLETION_WAIT))

    def test_a_review_recorded_while_the_same_episode_is_open_does_not_change_the_job_followed(self):
        self.world.topic.update(status="resting", active_contract_revision=1, reviews=[episode("rev_one")])
        d = self.world.driver()
        self.commit(d, contract("research_pass", "research"), contract("verification", "verify"), checkpoint("challenge"), checkpoint("dossier"))
        d.issue(checkpoint("review"), self.world.topic)                                       # the review job is issued and unsettled
        for records in ([], [self.REVIEW], [self.REVIEW, self.REVIEW]):                       # any number of sufficiency rows
            with self.subTest(rows=len(records)):
                self.world.records["completion_records"] = records
                self.assertEqual(d.tick(), workflow.Advance(checkpoint("review")))

    def test_a_restart_across_the_episode_closing_and_the_review_settling_follows_the_issued_job(self):
        self.world.topic.update(status="resting", active_contract_revision=1, reviews=[episode("rev_one")])
        d = self.world.driver()
        self.commit(d, contract("research_pass", "research"), contract("verification", "verify"), checkpoint("challenge"))
        self.assertEqual(d.tick(), workflow.Issue(checkpoint("dossier")))
        self.world.topic["reviews"] = []                                                      # the challenge commit closed the episode
        restarted = self.world.driver(self.world.station())
        self.commit(restarted, checkpoint("dossier"))
        self.assertEqual(restarted.tick(), workflow.Issue(checkpoint("review")))              # read from the order issued, not the open list
        restarted.issue(checkpoint("review"), self.world.topic)   # (tick above only decided; this is the production submission)
        self.assertEqual(self.world.driver(self.world.station()).tick(), workflow.Advance(checkpoint("review")))
        self.commit(self.world.driver(), checkpoint("review"))                                # settled
        self.assertEqual(self.world.driver(self.world.station()).tick(), workflow.Wait(*workflow.COMPLETION_WAIT))

    def test_with_several_episodes_open_the_oldest_without_a_checkpoint_is_taken(self):
        self.world.topic.update(status="resting", active_contract_revision=1, reviews=[episode("rev_a", 3), episode("rev_z", 1), episode("rev_m", 1)])
        d = self.world.driver()
        self.commit(d, contract("research_pass", "research"), contract("verification", "verify"))
        self.assertEqual(d.tick(), workflow.Issue(checkpoint("challenge", episode="rev_m")))   # oldest opened_at, ties by id

    def test_work_issued_under_another_contract_revision_that_has_not_settled_stops_the_walk(self):
        self.world.topic.update(status="resting", active_contract_revision=2, reviews=[episode("rev_one")])
        self.world.records["contract_revisions"].append({"revision": 2, "content_hash": HASH})
        d = self.world.driver()
        self.world.topic["active_contract_revision"] = 1
        self.assertEqual(d.tick(), workflow.Issue(contract("research_pass", "research")))     # production issuance under c1
        self.world.topic["active_contract_revision"] = 2                                      # the contract is amended; c1 work never settled
        action = d.tick()
        self.assertIsInstance(action, workflow.Stop)
        self.assertIn("issued under c1 and has not settled", action.reason)
        self.put(d.invocation_id(contract("research_pass", "research")), {"settled": "failed"})
        self.assertNotIsInstance(d.tick(), workflow.Stop)

    def test_the_same_context_gives_the_same_identity_after_a_restart(self):
        step = checkpoint("challenge", episode="rev_two")
        self.assertEqual(self.world.driver().invocation_id(step), self.world.driver(self.world.station()).invocation_id(step))
        self.assertNotEqual(self.world.driver().invocation_id(step), self.world.driver().invocation_id(checkpoint("challenge", episode="rev_one")))

    def test_a_missing_kit_or_active_contract_is_refused_not_guessed(self):
        d = self.world.driver()
        d.kits.pop(("research_pass", "scope"))
        with self.assertRaises(Refused):
            d.tick()
        self.world.topic.update(status="queued", active_contract_revision=None)
        with self.assertRaises(Refused):
            self.world.driver().tick()
