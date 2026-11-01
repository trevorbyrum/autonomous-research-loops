"""Real entrance, fixed invalid receipts: no live qualification or runtime.

Each field's locally acceptable control still refuses as unqualified. SQL and
all job/spool bytes are compared, including a pre-existing protected journal.
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


class EqualToAnything:
    """A fixed foreign value: neither null nor the internal absent marker."""

    def __eq__(self, other):
        return True


class LiveProfileRefusal(SupervisedTestCase):
    def files(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def refused(self, entrance, order, profile, diagnostic, *, live=True, omit=False):
        before, files = self.state(exclude=()), self.files()
        with mock.patch.object(jobs.Job, "spawn") as launcher, \
                mock.patch.object(jobs.Job, "lookup") as runtime, \
                mock.patch("subprocess.Popen") as process, mock.patch("socket.socket") as socket, \
                mock.patch.object(jobs.Job, "prepare") as prepare, \
                mock.patch.object(self.supervisor, "advance") as advance:
            try:
                entrance(order, live=live, **({} if omit else {"isolation_profile": profile}))
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
        self.supervisor.prepare(order)  # unchanged offline preparation
        self.supervisor.job(order.invocation_id).write("journal.json", {"budgets": {"spawn": 1}, "sentinel": "retain"})
        cases = [(None, "profile_null"), ("placeholder", "profile_invalid_shape"), (EqualToAnything(), "profile_invalid_shape"),
                 ({**UNQUALIFIED, "state": None}, "profile_invalid_state")]
        for field in ("manifest_pin", "source_pin", "qualification_pin"):
            missing = dict(UNQUALIFIED)
            del missing[field]
            cases.append((missing, f"profile_missing_{field}"))
            for value, reason in ((None, "profile_null_pin"), ([], "profile_invalid_pin"), (EqualToAnything(), "profile_invalid_pin"),
                                  *((v, "profile_placeholder") for v in ("", "TODO", "TBD", "pending", "placeholder", "unbuilt")),
                                  ("relay:latest", "profile_unpinned"), ("sha256:" + "a" * 63, "profile_unpinned"),
                                  ("sha256:" + "g" * 64, "profile_unpinned"),
                                  ("sha256:" + "a" * 64 + "\n", "profile_unpinned")):
                cases.append(({**UNQUALIFIED, field: value}, f"{reason}: {field}"))
        for state, reason in (("stale", "profile_stale"), ("invalidated", "profile_invalidated"),
                              ("qualified", "profile_qualification_unavailable"), ("unknown", "profile_qualification_unavailable")):
            cases.append(({**UNQUALIFIED, "state": state}, reason))
        for entrance in (self.supervisor.prepare, self.supervisor.submit):
            for profile, reason in cases:
                with self.subTest(entrance=entrance.__name__, reason=reason, profile=profile):
                    self.refused(entrance, order, dict(UNQUALIFIED), "profile_unqualified")
                    self.refused(entrance, order, profile, reason)
            # An absent profile and a new invocation leave no job directory, too.
            self.refused(entrance, replace(order, invocation_id="inv_newlive001"), None, "profile_null")
            self.refused(entrance, order, None, "profile_absent", omit=True)
            self.refused(entrance, order, None, "profile_null", live=False)
            self.refused(entrance, order, EqualToAnything(), "profile_invalid_shape", live=False)
            self.refused(entrance, order, UNQUALIFIED, "profile_unqualified", live=False)
        self.assertEqual(self.control.calls, 0)

    def test_live_policy_remains_closed(self):
        bundle = copy.deepcopy(rf.BUNDLE)
        bundle["policy"]["live_trial"] = {"isolation_profile": UNQUALIFIED}
        self.assertIn("live_trial", " ".join(SchemaSet().errors(bundle, "config-bundle.schema.json")))
