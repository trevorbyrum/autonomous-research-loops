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
        return {"status": "ok", "topics": [self.world.topic], "config_bundles": {"active": {"bundle_hash": BUNDLE}}}

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

    def submit(self, order, live=False):
        if self.world.fail_submit:
            raise OSError("disk full")
        self.job(order.invocation_id).prepare({"invocation_id": order.invocation_id, "topic_id": order.topic_id, "env": dict(order.env)})
        self.submitted.append(order)
        return "running"

    def advance(self, invocation_id, live_start=False):
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
            closed = False

            def close(self):
                self.closed = True
        station = Station()
        station.router, station.supervisor, station.spool = Router(self), Supervisor(self), Spool(self)
        return station

    def driver(self, station=None, **options):
        class Kit:
            families = ("intake_briefs",)

            def view(self, context, records, truncation):
                shape = {("research_pass", "research"): {"works": []}, ("verification", "verify"): {"claims": []}, ("checkpoint", "challenge"): {"searches": []}}
                return {"step": [context.step.purpose, context.step.ordinal], "admission": context.admission["context"], **shape.get((context.step.kind, context.step.purpose), {})}
        kits = {key: Kit() for key in workflow.LIMITS}
        return driver.Driver(station or self.station(), topic_id=TOPIC, bundle_hash=BUNDLE, kits=kits, prompt_dir=self.root / "prompts",
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
            d.issue(step, self.world.topic, proposer=scope(1) if step.kind == "discovery" else None)
            self.settle(d, step, step in proposals)

    SHOWN = {"dossier": {"revision": 2, "content_hash": HASH, "state": "satisfied", "gates": []}, "approvable": True,
             "reviews": [{"outcome": "insufficient", "summary": "claim 2 unsearched", "evidence": []}]}

    def test_the_completion_wait_prints_the_status_review_block_with_the_review_and_its_evidence(self):
        self.world.topic.update(status="resting", active_contract_revision=1, reviews=[], review=self.SHOWN)
        d = self.world.driver()
        self.commit(d, contract("research_pass", "research"), contract("verification", "verify"), checkpoint("challenge"), checkpoint("dossier"), checkpoint("review"))
        text = d.run()
        for fragment in ("run: apply_operator_decision kind=completion_approval", "dossier revision 2", "review insufficient: claim 2 unsearched"):
            self.assertIn(fragment, text)

    def test_a_completion_wait_without_a_reviewed_status_block_is_refused_not_printed_bare(self):
        self.world.topic.update(status="resting", active_contract_revision=1, reviews=[])
        d = self.world.driver()
        self.commit(d, contract("research_pass", "research"), contract("verification", "verify"), checkpoint("challenge"), checkpoint("dossier"), checkpoint("review"))
        for review in (None, {**self.SHOWN, "approvable": False, "reviews": []}):
            with self.subTest(review=review):
                self.world.topic["review"] = review
                self.assertIn("stopped: cannot show the review for approval", d.run())

    def test_the_review_kit_is_given_the_status_blocks_latest_dossier_revision(self):
        seen = []
        self.world.topic.update(status="resting", active_contract_revision=1, reviews=[], review=self.SHOWN)
        d = self.world.driver()
        d.kits[("checkpoint", "review")].view = lambda context, records, truncation: seen.append(context.dossier_revision) or {}
        d.issue(checkpoint("review"), self.world.topic)
        self.assertEqual(seen, [2])

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

    def ref(self, data: bytes, media="application/json"):
        self.world.blobs[canonical.bytes_digest(data)] = data
        return {"content_hash": canonical.bytes_digest(data), "size_bytes": len(data), "media_type": media}

    def aside(self, step, view, directory=None):
        directory = directory or self.world.root / "scratch"
        self.world.driver().set_aside(step, view, directory)
        return directory

    def test_only_the_views_named_fields_are_set_aside_as_evidence_files_named_by_digest(self):
        one, two, text = self.ref(b'{"a": 1}'), self.ref(b'{"b": 2}'), self.ref(b"abstract words", "text/plain")
        stray = self.ref(b"not named")
        for step, view in ((contract("research_pass", "research"), {"works": [{"artifact_ref": one}, {"artifact_ref": one}, {"artifact_ref": text}], "elsewhere": {"artifact_ref": stray}}),
                           (contract("verification", "verify"), {"claims": [{"sources": [{"artifact_ref": one}]}, {"sources": [{"artifact_ref": two}]}]}),
                           (checkpoint("challenge"), {"searches": [{"observations": [{"artifact_ref": one}, {"artifact_ref": None}]}]})):
            with self.subTest(step.purpose):
                directory = self.aside(step, view)
                names = sorted(p.name for p in directory.iterdir())
                expected = {"research": 2, "verify": 2, "challenge": 1}[step.purpose]
                self.assertEqual(len(names), expected)
                self.assertTrue(all(n.startswith("evidence-") for n in names))
                self.assertNotIn(stray["content_hash"].removeprefix("sha256:"), " ".join(names))
                for p in directory.iterdir():
                    p.unlink()

    def test_text_evidence_gets_the_text_form(self):
        text = self.ref(b"abstract words", "text/plain")
        directory = self.aside(contract("research_pass", "research"), {"works": [{"artifact_ref": text}]})
        self.assertEqual([p.name for p in directory.iterdir()], [f"evidence-{text['content_hash'].removeprefix('sha256:')}.txt"])

    def test_a_view_with_a_named_field_missing_or_malformed_is_refused_and_nothing_is_written(self):
        good = self.ref(b"x")
        for case, step, view in (("no list", contract("research_pass", "research"), {}),
                                 ("entry without the field", contract("research_pass", "research"), {"works": [{"work_id": "w"}]}),
                                 ("not a ref", contract("research_pass", "research"), {"works": [{"artifact_ref": "sha256:" + "0" * 64}]}),
                                 ("extra key", contract("research_pass", "research"), {"works": [{"artifact_ref": {**good, "x": 1}}]}),
                                 ("bad digest", contract("research_pass", "research"), {"works": [{"artifact_ref": {**good, "content_hash": "sha256:zz"}}]}),
                                 ("nested list missing", contract("verification", "verify"), {"claims": [{"text": "t"}]}),
                                 ("unsupported media", contract("research_pass", "research"), {"works": [{"artifact_ref": self.ref(b"bin", "application/octet-stream")}]})):
            with self.subTest(case), self.assertRaises(Refused):
                self.aside(step, view, self.world.root / f"s-{case.replace(' ', '-')}")

    def test_retained_bytes_that_are_missing_or_do_not_match_their_reference_refuse(self):
        good = self.ref(b"hello")
        for case, ref in (("not retained", {**good, "content_hash": "sha256:" + "1" * 64}), ("wrong size", {**good, "size_bytes": 99})):
            with self.subTest(case), self.assertRaises(Refused):
                self.aside(contract("research_pass", "research"), {"works": [{"artifact_ref": ref}]}, self.world.root / f"m-{case.replace(' ', '-')}")
        self.world.blobs[good["content_hash"]] = b"tampered"
        with self.assertRaises(Refused):
            self.aside(contract("research_pass", "research"), {"works": [{"artifact_ref": good}]}, self.world.root / "m-tampered")

    def test_the_count_and_total_bytes_are_bounded_by_the_supervisors_caps(self):
        from gen2.supervisor import supervisor
        many = [{"artifact_ref": self.ref(f"r{n}".encode())} for n in range(supervisor.MAX_EVIDENCE + 1)]
        with self.assertRaisesRegex(Refused, "resource"):
            self.aside(contract("research_pass", "research"), {"works": many}, self.world.root / "many")
        huge = {"content_hash": "sha256:" + "2" * 64, "size_bytes": supervisor.MAX_EVIDENCE_BYTES + 1, "media_type": "application/json"}
        with self.assertRaisesRegex(Refused, "resource"):
            self.aside(contract("research_pass", "research"), {"works": [{"artifact_ref": huge}]}, self.world.root / "huge")

    def test_the_set_aside_files_exist_before_the_order_is_durable(self):
        one = self.ref(b'{"a": 1}')
        station = self.world.station()
        d = self.world.driver(station)
        d.kits[("research_pass", "research")].view = lambda context, records, truncation: {"works": [{"artifact_ref": one}]}
        self.world.topic.update(status="queued", active_contract_revision=1)
        self.world.fail_submit = True
        with self.assertRaises(OSError):
            d.issue(contract("research_pass", "research"), self.world.topic)
        scratch = station.supervisor.job(d.invocation_id(contract("research_pass", "research"))).scratch
        self.assertTrue(list(scratch.glob("evidence-*.json")))                                   # written first
        self.assertEqual(list((self.world.root / "jobs").glob("*/order.json")), [])               # no order was made durable

    def test_the_issued_commands_run_in_fresh_processes_and_both_refuse_the_live_route_writing_nothing(self):
        """The routing is exercised by running what the driver submitted: each entry exists, takes the scratch directory, and is fenced pre-T19."""
        from gen2.discovery import child as discovery_child
        from gen2.tests import children
        station = self.world.station()
        gateway = {"GEN2_GATEWAY_URL": "http://gateway.invalid", "GEN2_SECRET_GATEWAY_TOKEN_FILE": str(self.world.root / "no-such-token")}
        d = self.world.driver(station, discovery_env=gateway)
        topic = {**self.world.topic, "status": "queued", "active_contract_revision": 1}
        d.issue(contract("research_pass", "research"), topic)
        d.issue(Step("discovery", "search", 1, "c1"), topic, proposer=contract("research_pass", "research"))
        research, discovery = station.supervisor.submitted
        self.assertEqual((research.command[1:3], discovery.command[1:3]), (("-m", "gen2.app.child"), ("-m", "gen2.discovery.child")))
        self.assertNotIn("GEN2_GATEWAY_URL", research.env)                                       # discovery's variables go to discovery alone
        self.assertEqual({k: discovery.env[k] for k in gateway}, gateway)
        for order, line in ((research, "the live runner entrance is closed"), (discovery, discovery_child.CLOSED)):
            with self.subTest(order.command[2]):
                before = sorted(p.name for p in Path(order.command[3]).iterdir())
                done = children.python(["-m", order.command[2], order.command[3]], cwd=order.command[3], env={**order.env}, capture_output=True, text=True)
                self.assertEqual(done.returncode, 2, done.stderr)                                # not a silent 0: the entry runs and refuses
                self.assertIn(line, done.stderr)
                self.assertEqual(sorted(p.name for p in Path(order.command[3]).iterdir()), before)   # nothing was written
                self.assertNotIn("no-such-token", done.stderr + done.stdout)                     # the token file was neither read nor named
        for case, env in (("the token itself", {"GEN2_SECRET_GATEWAY_TOKEN": "s3cret"}), ("any token variable", {"GEN2_TOKEN": "x"})):
            with self.subTest(case), self.assertRaises(Refused):
                self.world.driver(discovery_env=env)

    def test_a_discovery_run_needs_its_proposer_and_the_context_carries_it(self):
        station = self.world.station()
        d = self.world.driver(station)
        seen = []
        d.kits[("discovery", "search")].view = lambda context, records, truncation: seen.append(context.proposer) or {}
        topic = {**self.world.topic, "status": "queued", "active_contract_revision": 1}
        with self.assertRaises(Refused):
            d.issue(Step("discovery", "search", 1, "c1"), topic)
        d.issue(Step("discovery", "search", 1, "c1"), topic, proposer=contract("research_pass", "research"))
        self.assertEqual(seen, [contract("research_pass", "research")])

    def test_a_missing_kit_or_active_contract_is_refused_not_guessed(self):
        d = self.world.driver()
        d.kits.pop(("research_pass", "scope"))
        with self.assertRaises(Refused):
            d.tick()
        self.world.topic.update(status="queued", active_contract_revision=None)
        with self.assertRaises(Refused):
            self.world.driver().tick()
