"""Real entrance with no authority wired: no live qualification or runtime.

SQL and all job/spool bytes are compared, including a pre-existing protected journal.
"""
import copy
from dataclasses import replace
from unittest import mock

from gen2.router.schemas import SchemaSet
from gen2.supervisor import jobs
from gen2.supervisor.isolation import LiveProfileRefused
from gen2.tests import router_fixtures as rf
from gen2.tests.supervisor_fixtures import SupervisedTestCase

# Structurally plausible references only; none names qualifying evidence.
UNQUALIFIED = {"manifest_pin": "sha256:" + "1" * 64, "source_pin": "sha256:" + "2" * 64,
               "qualification_pin": "sha256:" + "3" * 64, "state": "unqualified"}


class LiveProfileRefusal(SupervisedTestCase):
    def files(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def refused(self, entrance, order, diagnostic, **kwargs):
        before, files = self.state(exclude=()), self.files()
        with mock.patch.object(jobs.Job, "spawn") as launcher, \
                mock.patch.object(jobs.Job, "lookup") as runtime, \
                mock.patch("subprocess.Popen") as process, mock.patch("socket.socket") as socket, \
                mock.patch.object(jobs.Job, "prepare") as prepare, \
                mock.patch.object(self.supervisor, "advance") as advance:
            try:
                entrance(order, **kwargs)
            except LiveProfileRefused as refusal:
                self.assertRegex(str(refusal), diagnostic)
            except Exception as failure:
                self.fail(f"unexpected refusal error: {failure!r}")
            else:
                self.fail("invalid live profile admitted")
            for spy in (launcher, runtime, process, socket, prepare, advance):
                spy.assert_not_called()
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.files(), files)

    def test_refusal_matrix_at_prepare_and_submit(self):
        order = self.order("research_pass")
        try:
            self.supervisor.prepare(order)  # unchanged offline preparation
        except Exception as failure:
            self.fail(f"offline preparation refused: {failure!r}")
        self.supervisor.job(order.invocation_id).write("journal.json", {"budgets": {"spawn": 1}, "sentinel": "retain"})
        for entrance in (self.supervisor.prepare, self.supervisor.submit):
            with self.subTest(entrance=entrance.__name__):
                self.refused(entrance, order, "profile_absent", live=True)   # no authority wired: closed, whatever the order
                self.refused(entrance, replace(order, invocation_id="inv_newlive001"), "profile_absent", live=True)   # and a new invocation leaves no job directory
                with self.assertRaises(TypeError):   # a caller can no longer supply a profile at all
                    entrance(order, live=True, isolation_profile=UNQUALIFIED)
        self.assertEqual(self.control.calls, 0)

    def test_live_policy_remains_closed(self):
        bundle = copy.deepcopy(rf.BUNDLE)
        bundle["policy"]["live_trial"] = {"isolation_profile": UNQUALIFIED}
        self.assertIn("live_trial", " ".join(SchemaSet().errors(bundle, "config-bundle.schema.json")))
