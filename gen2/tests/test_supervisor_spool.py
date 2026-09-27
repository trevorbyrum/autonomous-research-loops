"""The protected spool (task 1c; INVARIANTS C-9, C-10; design review §5
"Artifacts and the sole-writer promise").

What these show: bytes are staged under their SHA-256, once, read-only, for
one topic, and read back only under that topic; staging the same bytes again
changes nothing; the same bytes under another media type are refused;
an artifact over the size bound and a stage past the quota are refused as
an infrastructure failure (SpoolFull), leaving nothing staged; collecting a
job's output refuses a symlink (to a file or as the scratch directory), a
hard link, a FIFO and an oversized file, never staging their bytes, and
never opens a path the agent chose (names are single components); the
router, handed this spool, refuses another topic's bytes and a media type
the spool did not record. Oracles: SHA-256 computed here with hashlib; file
modes and links read with os.lstat; expected refusals by hand.

What they cannot show: isolation from another process of the same user
(the spool is protected by being the station's directory, not by the OS:
deployment's, 1e), or behaviour on a full disk (the quota stands in for it).
"""
from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import unittest
from pathlib import Path

from gen2.supervisor.spool import Spool, SpoolConflict, SpoolFull, read_scratch
from gen2.tests.router_fixtures import OTHER, TOPIC, RouterTestCase, empty_outcome, jcs


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class SpoolTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.spool = Spool(self.root / "spool", max_artifact_bytes=64, quota_bytes=200)
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def entries(self) -> list[str]:
        return sorted(str(p.relative_to(self.root / "spool")) for p in (self.root / "spool").rglob("*") if p.is_file())


class StageTest(SpoolTestCase):
    def test_bytes_are_staged_once_under_their_hash_read_only_for_one_topic(self) -> None:
        ref = self.spool.stage(TOPIC, b"a claim's text", "text/plain")
        self.assertEqual(ref, {"content_hash": sha(b"a claim's text"), "size_bytes": 14, "media_type": "text/plain"})
        path = self.root / "spool" / TOPIC / ref["content_hash"][7:]
        info = os.lstat(path)
        self.assertEqual((stat.S_ISREG(info.st_mode), stat.S_IMODE(info.st_mode) & 0o222, info.st_nlink), (True, 0, 1))
        self.assertEqual(self.spool.read(ref["content_hash"], topic_id=TOPIC), b"a claim's text")
        self.assertEqual(self.spool.media_type(ref["content_hash"], topic_id=TOPIC), "text/plain")
        self.assertIsNone(self.spool.read(ref["content_hash"], topic_id=OTHER))  # topic-scoped
        self.assertIsNone(self.spool.media_type(ref["content_hash"], topic_id=OTHER))
        before = self.entries()
        self.assertEqual(self.spool.stage(TOPIC, b"a claim's text", "text/plain"), ref)
        self.assertEqual(self.entries(), before)
        self.assertEqual(self.spool.stage(OTHER, b"a claim's text", "text/plain"), ref)  # another topic stages its own copy
        self.assertEqual(self.spool.read(ref["content_hash"], topic_id=OTHER), b"a claim's text")

    def test_the_same_bytes_under_another_media_type_are_refused(self) -> None:
        self.spool.stage(TOPIC, b"{}", "application/json")
        before = self.entries()
        with self.assertRaises(SpoolConflict):
            self.spool.stage(TOPIC, b"{}", "text/plain")
        self.assertEqual(self.entries(), before)
        self.assertEqual(self.spool.media_type(sha(b"{}"), topic_id=TOPIC), "application/json")

    def test_the_bound_and_the_quota_are_infrastructure_failures(self) -> None:
        with self.assertRaises(SpoolFull):
            self.spool.stage(TOPIC, b"x" * 65, "text/plain")
        self.assertEqual(self.entries(), [])
        self.spool.stage(TOPIC, b"a" * 64, "text/plain")  # the bound itself is admitted
        self.spool.stage(TOPIC, b"b" * 64, "text/plain")
        self.spool.stage(TOPIC, b"c" * 64, "text/plain")
        before = self.entries()
        with self.assertRaises(SpoolFull):
            self.spool.stage(OTHER, b"d" * 64, "text/plain")  # 256 > the 200-byte quota, whichever topic
        self.assertEqual(self.entries(), before)
        self.assertEqual(self.spool.stage(TOPIC, b"a" * 64, "text/plain")["size_bytes"], 64)  # already staged: no new bytes

    def test_a_topic_or_hash_that_is_not_one_is_refused(self) -> None:
        for bad in ("../escape", "fleet-a:t1/../../x", "Fleet:t", ""):
            with self.subTest(bad), self.assertRaises(ValueError):
                self.spool.stage(bad, b"x", "text/plain")
        for bad in ("sha256:../../etc", "md5:" + "0" * 32, sha(b"x").upper()):
            with self.subTest(bad), self.assertRaises(ValueError):
                self.spool.read(bad, topic_id=TOPIC)

    def test_a_symlinked_topic_directory_is_not_followed(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / "spool" / OTHER).symlink_to(outside)
        with self.assertRaises(OSError):
            self.spool.stage(OTHER, b"x", "text/plain")
        self.assertEqual(list(outside.iterdir()), [])


class CollectTest(SpoolTestCase):
    def test_a_regular_file_is_staged_as_found(self) -> None:
        (self.scratch / "outcome.json").write_bytes(b'{"ok": 1}')
        found = self.spool.collect(TOPIC, self.scratch, "outcome.json", "application/json")
        self.assertEqual((found["status"], found["ref"]["content_hash"]), ("present", sha(b'{"ok": 1}')))
        self.assertEqual(self.spool.read(sha(b'{"ok": 1}'), topic_id=TOPIC), b'{"ok": 1}')

    def test_absent_and_empty_output_are_told_apart_and_nothing_is_staged(self) -> None:
        self.assertEqual(self.spool.collect(TOPIC, self.scratch, "outcome.json", "application/json")["status"], "absent")
        (self.scratch / "outcome.json").write_bytes(b"")
        self.assertEqual(self.spool.collect(TOPIC, self.scratch, "outcome.json", "application/json")["status"], "empty")
        self.assertEqual(self.entries(), [])

    def test_what_is_not_the_jobs_own_regular_file_is_refused_unread(self) -> None:
        secret = self.root / "secret.json"
        secret.write_bytes(b'{"secret": 1}')
        cases = {
            "a symlink": lambda path: path.symlink_to(secret),
            "a hard link": lambda path: os.link(secret, path),
            "a FIFO": lambda path: os.mkfifo(path),
            "over the bound": lambda path: path.write_bytes(b"x" * 65),
            "a directory": lambda path: path.mkdir(),
        }
        for name, make in cases.items():
            with self.subTest(name):
                target = self.scratch / "outcome.json"
                if target.is_dir() and not target.is_symlink():
                    target.rmdir()
                elif target.exists() or target.is_symlink():
                    target.unlink()
                make(target)
                found = self.spool.collect(TOPIC, self.scratch, "outcome.json", "application/json")
                self.assertEqual((found["status"], found["ref"]), ("refused", None), found)
        self.assertEqual(self.entries(), [])
        self.assertIsNone(self.spool.read(sha(b'{"secret": 1}'), topic_id=TOPIC))

    def test_a_symlinked_scratch_directory_is_refused(self) -> None:
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "outcome.json").write_bytes(b'{"ok": 1}')
        link = self.root / "linked-scratch"
        link.symlink_to(elsewhere)
        self.assertEqual(read_scratch(link, "outcome.json", 64)["status"], "refused")
        self.assertEqual(read_scratch(elsewhere, "outcome.json", 64)["status"], "present")  # the same file, not through a link

    def test_the_name_is_one_component_the_supervisor_chose(self) -> None:
        for bad in ("../outcome.json", "sub/outcome.json", ".hidden", "", "/etc/passwd"):
            with self.subTest(bad), self.assertRaises(ValueError):
                read_scratch(self.scratch, bad, 64)


class RouterReadsThisSpoolTest(RouterTestCase):
    """The router handed the real spool: another topic's bytes are not staged
    for this invocation, and the spool's media type is the one that counts."""

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.spool = Spool(Path(self._tmp.name))
        self.router = self.make_router()
        self.to_queued()
        self.grant = self.started("inv_research01")

    def tearDown(self) -> None:
        super().tearDown()
        self._tmp.cleanup()

    def test_another_topics_bytes_are_not_this_topics(self) -> None:
        outcome = jcs(empty_outcome("inv_research01"))
        self.spool.stage(OTHER, outcome, "application/json")
        request = {"capability_id": self.grant["capability_id"], "invocation_id": "inv_research01", "to_state": "result_ready", "result_payload_digest": sha(outcome)}
        before = self.state(exclude=())
        self.assertEqual(self.router.record_transition(request)["reason"], "payload_missing")
        self.assertEqual(self.state(exclude=()), before)
        self.spool.stage(TOPIC, outcome, "application/json")
        self.assertEqual(self.router.record_transition(request)["status"], "recorded")

    def test_a_result_staged_as_another_media_type_is_refused(self) -> None:
        outcome = jcs(empty_outcome("inv_research01"))
        self.spool.stage(TOPIC, outcome, "text/plain")
        request = {"capability_id": self.grant["capability_id"], "invocation_id": "inv_research01", "to_state": "result_ready", "result_payload_digest": sha(outcome)}
        before = self.state(exclude=())
        self.assertEqual(self.router.record_transition(request)["reason"], "payload_invalid")
        self.assertEqual(self.state(exclude=()), before)


if __name__ == "__main__":
    unittest.main()
