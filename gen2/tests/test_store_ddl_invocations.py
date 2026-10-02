"""Constraint tests for the gen-2 store DDL draft: leases, invocations and
their lifecycle, commit receipts and ordinals, admission, and the hash
contract a receipt records (mostly
gen2/store/schema/02-invocations-and-records.sql).

Split from test_store_ddl.py by concern (task 2r): the classes, their
methods and assertions are unchanged.

Trace: task 0a deliverable 3 ("Uniqueness/fencing constraints expressed in
DDL where SQLite allows"); invariant IDs refer to docs/gen2/INVARIANTS.md.

What these tests show: the named constraint or trigger rejects the stated
row. Where a test also shows the same write minus the violation being
accepted, that control rules out an unrelated failure (such as a missing
foreign key); the few tests without such a control say so. Every
connection applies gen2/store/connection.sql (store_fixtures.connect). What
they cannot show: that the router uses these tables correctly, that crash recovery or
replay behave (RG-1a/RG-1b need Phase 1 fault-injection tests against the
router), or anything about concurrency. They test the draft schema only.
"""
from __future__ import annotations

import json
import sqlite3
import unittest

from gen2.tests import store_fixtures
from gen2.tests.store_fixtures import DROP, FIND_REQUEST, OTHER, STORE_DIR, TOPIC, StoreTestCase, T, connect, facet, h, obligation


class LeaseFencingTest(StoreTestCase):
    def test_one_live_lease_per_topic_and_scope_until_released(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.lease("lease_vvvvvvvv", 2, scope="verification")  # another scope is independent
        self.rejects("UNIQUE constraint failed: leases.topic_id, leases.scope",
                     "INSERT INTO leases (lease_id, topic_id, scope, generation, station_id, granted_at, expires_at) VALUES ('lease_bbbbbbbb', ?, 'research', 3, 'st2', ?, ?)", TOPIC, T, T)
        # A1: REPLACE would resolve the one-live-lease conflict by deleting the live lease
        self.rejects("leases are never deleted",
                     "INSERT OR REPLACE INTO leases (lease_id, topic_id, scope, generation, station_id, granted_at, expires_at) VALUES ('lease_bbbbbbbb', ?, 'research', 3, 'st2', ?, ?)", TOPIC, T, T)
        self.assertEqual(self.rows("SELECT lease_id FROM leases WHERE scope = 'research' AND released_at IS NULL"), [("lease_aaaaaaaa",)])
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_aaaaaaaa'", T)
        self.lease("lease_bbbbbbbb", 3)

    def test_generation_strictly_increases_per_topic(self) -> None:
        self.lease("lease_aaaaaaaa", 5)
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_aaaaaaaa'", T)
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)  # generations are per topic
        self.rejects("lease generation must exceed", "INSERT INTO leases (lease_id, topic_id, scope, generation, station_id, granted_at, expires_at) VALUES ('lease_bbbbbbbb', ?, 'research', 5, 'st1', ?, ?)", TOPIC, T, T)
        self.rejects("lease generation must exceed", "INSERT INTO leases (lease_id, topic_id, scope, generation, station_id, granted_at, expires_at) VALUES ('lease_bbbbbbbb', ?, 'research', 4, 'st1', ?, ?)", TOPIC, T, T)
        self.lease("lease_bbbbbbbb", 6)

    def test_release_is_write_once(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.x("UPDATE leases SET expires_at = '2026-09-25T13:00:00Z' WHERE lease_id = 'lease_aaaaaaaa'")  # renewal allowed while live
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_aaaaaaaa'", T)
        self.rejects("a released lease is final", "UPDATE leases SET released_at = NULL, release_reason = NULL WHERE lease_id = 'lease_aaaaaaaa'")
        self.rejects("a released lease is final", "UPDATE leases SET release_reason = 'again' WHERE lease_id = 'lease_aaaaaaaa'")


class InvocationLifecycleTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)

    def test_invocations_start_admitted(self) -> None:
        self.rejects("invocations are created admitted", *self.raw_invocation(invocation_id="inv_pppppppp", state="committed", launch_intent_at=T, job_handle="job-1",
                                                                              result_payload_digest=h("d"), result_staged_at=T))
        self.invocation("inv_pppppppp")

    def test_full_chain_allowed_but_skips_rejected(self) -> None:
        self.invocation("inv_pppppppp")
        self.rejects("invocation state transition not allowed", "UPDATE invocations SET state = 'committed', launch_intent_at = ?, result_payload_digest = ?, result_staged_at = ? WHERE invocation_id = 'inv_pppppppp'", T, h("d"), T)
        self.to_running("inv_pppppppp")
        self.x("UPDATE invocations SET state = 'result_ready', result_payload_digest = ?, result_staged_at = ? WHERE invocation_id = 'inv_pppppppp'", h("d"), T)
        self.x("UPDATE invocations SET state = 'committed' WHERE invocation_id = 'inv_pppppppp'")

    # Hand-written from INVARIANTS L-1 (not read from the DDL): the oracle.
    ALLOWED = {
        "admitted": {"launching", "cancelled"},
        "launching": {"running", "failed", "cancelled", "outcome_unknown"},
        "running": {"result_ready", "failed", "cancelled", "outcome_unknown"},
        "result_ready": {"committed", "failed", "outcome_unknown"},
        "outcome_unknown": {"running", "result_ready", "committed", "failed", "cancelled"},
        "committed": set(), "cancelled": set(), "failed": set(),
    }
    KINDS = ("research_pass", "discovery", "delegate", "verification", "checkpoint")
    SCOPE = {"research_pass": "research", "discovery": "discovery", "verification": "verification", "checkpoint": "checkpoint"}

    def fresh(self, kind: str, n: int) -> str:
        """A new invocation of this kind, owning a fresh lease (or under a running parent)."""
        iid = f"inv_{kind[:4]}{n:04d}"
        if kind == "delegate":
            if not self.rows("SELECT 1 FROM invocations WHERE invocation_id = 'inv_parent00'"):
                self.owned("research_pass", "inv_parent00", "lease_parent00")
                self.to_running("inv_parent00")
            self.invocation(iid, kind="delegate", lease=None, parent="inv_parent00")
            return iid
        self.owned(kind, iid, f"lease_{kind[:4]}{n:04d}")
        return iid

    def owned(self, kind: str, iid: str, lid: str) -> None:
        """Release the scope's live lease, grant the next generation, admit iid on it."""
        for (old,) in self.rows("SELECT lease_id FROM leases WHERE topic_id = ? AND scope = ? AND released_at IS NULL", TOPIC, self.SCOPE[kind]):
            self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = ?", T, old)
        gen = self.rows("SELECT coalesce(max(generation), 0) + 1 FROM leases WHERE topic_id = ?", TOPIC)[0][0]
        self.x("INSERT INTO leases (lease_id, topic_id, scope, generation, station_id, granted_at, expires_at) VALUES (?, ?, ?, ?, 'st1', ?, ?)", lid, TOPIC, self.SCOPE[kind], gen, T, T)
        self.invocation(iid, kind=kind, lease=lid)

    def columns_for(self, iid: str, state: str) -> str:
        """SET clause giving a row everything the target state's CHECKs need,
        with deterministic values so write-once columns are re-set unchanged."""
        return {
            "admitted": "state = 'admitted'",
            "launching": f"state = 'launching', launch_intent_at = '{T}', job_handle = 'job-{iid}'",
            "running": f"state = 'running', launch_intent_at = '{T}', job_handle = 'job-{iid}', host_id = 'dev', boot_id = 'b1', start_fingerprint = 'st=1'",
            "result_ready": f"state = 'result_ready', launch_intent_at = '{T}', job_handle = 'job-{iid}', result_payload_digest = '{h('d')}', result_staged_at = '{T}'",
            "committed": f"state = 'committed', launch_intent_at = '{T}', job_handle = 'job-{iid}', result_payload_digest = '{h('d')}', result_staged_at = '{T}'",
            "cancelled": f"state = 'cancelled', cancel_requested_at = '{T}', cancel_requested_by = 'router', descendants_confirmed_at = '{T}'",
            "failed": "state = 'failed'",
            "outcome_unknown": f"state = 'outcome_unknown', launch_intent_at = '{T}', job_handle = 'job-{iid}', outcome_unknown_since = '{T}', unknown_episode = unknown_episode + 1",
        }[state]

    PATH = {"admitted": (), "launching": ("launching",), "running": ("launching", "running"),
            "result_ready": ("launching", "running", "result_ready"), "committed": ("launching", "running", "result_ready", "committed"),
            "cancelled": ("cancelled",), "failed": ("launching", "failed"), "outcome_unknown": ("launching", "running", "outcome_unknown")}
    RESOLUTION = {"running": "found_running", "result_ready": "found_result", "committed": "found_committed", "failed": "confirmed_failed", "cancelled": "terminated_group"}

    def test_terminal_states_are_final(self) -> None:
        """D06 rewrite: the full L-1 transition matrix, for all five kinds. Each
        (kind, from, to) pair starts from a fresh invocation driven to `from`
        along an allowed path; the attempt supplies every column the target's
        CHECKs need (and, out of outcome_unknown, the matching reconciliation
        record), so only the transition rule decides."""
        n = 0
        for kind in self.KINDS:
            for src, allowed in self.ALLOWED.items():
                for dst in self.ALLOWED:
                    if dst == src:
                        continue
                    n += 1
                    with self.subTest(kind=kind, src=src, dst=dst):
                        iid = self.fresh(kind, n)
                        for step in self.PATH[src]:
                            self.x(f"UPDATE invocations SET {self.columns_for(iid, step)} WHERE invocation_id = ?", iid)
                        if src == "outcome_unknown" and dst in self.RESOLUTION:
                            if dst == "committed":
                                lease = self.rows("SELECT coalesce(i.lease_id, p.lease_id) FROM invocations i LEFT JOIN invocations p ON p.invocation_id = i.parent_invocation_id WHERE i.invocation_id = ?", iid)[0][0]
                                gen = self.rows("SELECT generation FROM leases WHERE lease_id = ?", lease)[0][0]
                                self.receipt(f"op_{n:08d}", iid, lease=lease, gen=gen, before=n)
                            self.reconcile(iid, self.RESOLUTION[dst], digest=h("d") if dst == "result_ready" else None, rid=f"rec_{n:08d}")
                        attempt = f"UPDATE invocations SET {self.columns_for(iid, dst)} WHERE invocation_id = ?"
                        if dst in allowed:
                            self.x(attempt, iid)
                            self.assertEqual(self.rows("SELECT state FROM invocations WHERE invocation_id = ?", iid), [(dst,)])
                        else:
                            self.rejects("invocation state transition not allowed", attempt, iid)
        self.assertEqual(n, 5 * 8 * 7)

    RECONCILE = ("INSERT INTO invocation_reconciliations (reconciliation_id, invocation_id, unknown_episode, unknown_since, resolution, method, evidence_ref, result_payload_digest, resolved_at, request) "
                 "VALUES (?1, ?2, ?3, ?4, ?5, 'job_handle_lookup', ?6, ?7, ?8, json_object('resolution', ?5, 'method', 'job_handle_lookup', 'evidence_ref', ?6, 'result_payload_digest', ?7))")

    def test_outcome_unknown_is_reconciled_not_skipped(self) -> None:
        """D07 rewrite (A5), extended for RA4. First half: leaving
        outcome_unknown needs the durable reconciliation of this episode, with
        a resolution that supports the target; a timestamp, a bare digest, a
        stale episode's record, a mismatched digest or the wrong resolution
        are refused. Second half, the review's two-episode attack: episode 1
        reconciled found_running and left; episode 2 entered an hour later;
        its direct exit is refused — and so is rewinding its start time to
        episode 1's (then exiting), rewriting its identity to episode 1's,
        or skipping ahead; the row reads back unchanged after each refusal.
        A re-entry must take a fresh identity (not episode 2's again, not
        episode 1's); a re-entry at episode 1's very timestamp is episode 3,
        which neither earlier record reconciles; its own record does."""
        later = "2026-09-25T13:00:00Z"
        self.invocation("inv_pppppppp")
        self.to_running("inv_pppppppp")
        self.rejects("CHECK constraint failed", "UPDATE invocations SET state = 'outcome_unknown', unknown_episode = 1 WHERE invocation_id = 'inv_pppppppp'")  # no start time
        self.to_unknown("inv_pppppppp", T)
        to_ready = "UPDATE invocations SET state = 'result_ready', result_payload_digest = ?, result_staged_at = ? WHERE invocation_id = 'inv_pppppppp'"
        refused = "reconciliation record of this episode"
        self.rejects(refused, to_ready, h("d"), T)  # timestamp + result digest, no reconciliation
        self.reconcile("inv_pppppppp", "found_running", rid="rec_00000001")
        self.rejects(refused, to_ready, h("d"), T)  # a record whose resolution does not support result_ready
        self.x("UPDATE invocations SET state = 'running' WHERE invocation_id = 'inv_pppppppp'")
        self.to_unknown("inv_pppppppp", later)
        self.rejects("current outcome_unknown episode", self.RECONCILE, "rec_00000009", "inv_pppppppp", 1, T, "found_result", h("7"), h("d"), T)  # a record for the earlier episode
        self.rejects(refused, "UPDATE invocations SET state = 'running' WHERE invocation_id = 'inv_pppppppp'")  # the earlier episode's record is stale
        self.rejects("CHECK constraint failed", self.RECONCILE, "rec_00000002", "inv_pppppppp", 2, later, "found_result", h("7"), None, T)  # found_result names its digest
        self.reconcile("inv_pppppppp", "found_result", digest=h("e"), rid="rec_00000002")
        self.rejects(refused, to_ready, h("d"), T)  # the digest found is not the one being staged
        self.assertEqual(self.rows("SELECT state FROM invocations WHERE invocation_id = 'inv_pppppppp'"), [("outcome_unknown",)])
        self.x(to_ready, h("e"), T)

        # RA4 — the review's two-episode attack, on a second invocation
        self.lease("lease_dddddddd", 2, scope="discovery")
        self.invocation("inv_disc0001", kind="discovery", lease="lease_dddddddd")
        self.to_running("inv_disc0001")
        self.to_unknown("inv_disc0001", T)  # episode 1
        self.reconcile("inv_disc0001", "found_running")
        exit_running = "UPDATE invocations SET state = 'running' WHERE invocation_id = 'inv_disc0001'"
        self.x(exit_running)
        self.to_unknown("inv_disc0001", later)  # episode 2
        before = self.snapshot("invocations")
        fresh = "takes a fresh identity on entry"
        self.rejects(refused, exit_running)  # direct exit: episode 2 has no record
        for label, sql, params, reasons in (
                ("the review's rewind of the start time", "UPDATE invocations SET outcome_unknown_since = ? WHERE invocation_id = 'inv_disc0001'", (T,), (fresh,)),
                ("identity rewritten to the reconciled episode", "UPDATE invocations SET unknown_episode = 1 WHERE invocation_id = 'inv_disc0001'", (), (fresh,)),
                ("identity skipped ahead while active", "UPDATE invocations SET unknown_episode = 3 WHERE invocation_id = 'inv_disc0001'", (), (fresh,)),
                # in one statement with the exit, both the exit's gate (it reads the episode being left) and the
                # identity guard refuse; which reports first is SQLite's trigger order, not the invariant
                ("rewind and exit in one statement", "UPDATE invocations SET outcome_unknown_since = ?, state = 'running' WHERE invocation_id = 'inv_disc0001'", (T,), (refused, fresh)),
                ("identity rewritten and exit in one statement", "UPDATE invocations SET unknown_episode = 1, state = 'running' WHERE invocation_id = 'inv_disc0001'", (), (refused, fresh))):
            with self.subTest(attack=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.x(sql, *params)
                self.assertTrue(any(reason in str(ctx.exception) for reason in reasons), str(ctx.exception))
                self.assertEqual(self.snapshot("invocations"), before)
        self.reconcile("inv_disc0001", "found_running")  # episode 2's own record
        self.x(exit_running)
        for label, sql, params in (
                ("re-entry keeping episode 2's identity", "UPDATE invocations SET state = 'outcome_unknown', outcome_unknown_since = ? WHERE invocation_id = 'inv_disc0001'", (T,)),
                ("re-entry reusing episode 1's identity", "UPDATE invocations SET state = 'outcome_unknown', outcome_unknown_since = ?, unknown_episode = 1 WHERE invocation_id = 'inv_disc0001'", (T,)),
                ("identity changed outside an entry", "UPDATE invocations SET unknown_episode = 3 WHERE invocation_id = 'inv_disc0001'", ()),
                ("start time changed outside an entry", "UPDATE invocations SET outcome_unknown_since = ? WHERE invocation_id = 'inv_disc0001'", (T,))):
            with self.subTest(attack=label):
                self.rejects(fresh, sql, *params)
        self.to_unknown("inv_disc0001", T)  # episode 3, at episode 1's timestamp
        self.rejects(refused, exit_running)
        self.rejects("current outcome_unknown episode", self.RECONCILE, "rec_00000019", "inv_disc0001", 1, T, "found_running", h("7"), None, T)
        self.assertEqual(self.rows("SELECT state, unknown_episode, outcome_unknown_since FROM invocations WHERE invocation_id = 'inv_disc0001'"), [("outcome_unknown", 3, T)])
        self.reconcile("inv_disc0001", "found_running")
        self.x(exit_running)
        self.assertEqual(self.rows("SELECT unknown_episode, unknown_since, resolution FROM invocation_reconciliations WHERE invocation_id = 'inv_disc0001' ORDER BY unknown_episode"),
                         [(1, T, "found_running"), (2, later, "found_running"), (3, T, "found_running")])

    def test_every_exit_needs_its_own_episodes_record(self) -> None:
        """RA4 for every permitted reconciliation exit: on a second unknown
        episode, the first episode's record never permits the exit — for
        running and result_ready it even names the resolution the exit needs
        — and the second episode's own record does."""
        later = "2026-09-25T13:00:00Z"
        for n, target in enumerate(("running", "result_ready", "committed", "failed", "cancelled"), start=1):
            with self.subTest(target=target):
                iid = self.fresh("research_pass", 900 + n)
                self.to_running(iid)
                self.to_unknown(iid, T)
                if target == "result_ready":  # episode 1 found the result: its record supports result_ready too
                    self.reconcile(iid, "found_result", digest=h("d"))
                    self.x("UPDATE invocations SET state = 'result_ready', result_payload_digest = ?, result_staged_at = ? WHERE invocation_id = ?", h("d"), T, iid)
                else:
                    self.reconcile(iid, "found_running")
                    self.x("UPDATE invocations SET state = 'running' WHERE invocation_id = ?", iid)
                self.to_unknown(iid, later)
                if target == "committed":
                    lease = self.rows("SELECT lease_id FROM invocations WHERE invocation_id = ?", iid)[0][0]
                    gen = self.rows("SELECT generation FROM leases WHERE lease_id = ?", lease)[0][0]
                    self.receipt(f"op_{900 + n:08d}", iid, lease=lease, gen=gen, before=900 + n)
                attempt = f"UPDATE invocations SET {self.columns_for(iid, target)} WHERE invocation_id = ?"
                self.rejects("reconciliation record of this episode", attempt, iid)
                self.reconcile(iid, self.RESOLUTION[target], digest=h("d") if target == "result_ready" else None)
                self.x(attempt, iid)
                self.assertEqual(self.rows("SELECT state, unknown_episode FROM invocations WHERE invocation_id = ?", iid), [(target, 2)])

    def test_reconciliation_resolutions_and_evidence(self) -> None:
        """A5: terminal resolutions confirm descendant handling; termination is its
        own method; evidence is a retained artifact; records are immutable."""
        self.invocation("inv_pppppppp")
        self.to_running("inv_pppppppp")
        self.to_unknown("inv_pppppppp", T)
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", h("7"), T)
        ins = ("INSERT INTO invocation_reconciliations (reconciliation_id, invocation_id, unknown_episode, unknown_since, resolution, method, evidence_ref, descendants_confirmed_at, resolved_at, request) "
               "VALUES ('rec_00000001', 'inv_pppppppp', 1, ?1, ?2, ?3, ?4, ?5, ?6, json_object('resolution', ?2, 'method', ?3, 'evidence_ref', ?4, 'result_payload_digest', NULL))")
        self.rejects("CHECK constraint failed", ins, T, "confirmed_failed", "job_handle_lookup", h("7"), None, T)  # descendants unconfirmed
        self.rejects("CHECK constraint failed", ins, T, "terminated_group", "job_handle_lookup", h("7"), T, T)  # termination is its own method
        self.rejects("CHECK constraint failed", ins, T, "found_running", "execution_group_termination", h("7"), None, T)
        self.rejects("FOREIGN KEY constraint failed", ins, T, "found_running", "job_handle_lookup", h("0"), None, T)  # evidence must be a retained artifact
        self.rejects("CHECK constraint failed", self.RECONCILE, "rec_00000001", "inv_pppppppp", 1, T, "found_running", h("7"), h("d"), T)  # only found_result names a digest
        refused = "reconciliation record of this episode"
        # episode 1: found running supports only running
        self.reconcile("inv_pppppppp", "found_running", rid="rec_00000001")
        for target in ("failed", "cancelled"):
            with self.subTest(target=target):
                self.rejects(refused, f"UPDATE invocations SET state = '{target}', cancel_requested_at = ?, cancel_requested_by = 'operator', descendants_confirmed_at = ? WHERE invocation_id = 'inv_pppppppp'", T, T)
        self.x("UPDATE invocations SET state = 'running' WHERE invocation_id = 'inv_pppppppp'")
        # episode 2: a confirmed failure supports failed, not cancelled
        later = "2026-09-25T13:00:00Z"
        self.to_unknown("inv_pppppppp", later)
        self.reconcile("inv_pppppppp", "confirmed_failed", rid="rec_00000002")
        self.rejects(refused, "UPDATE invocations SET state = 'cancelled', cancel_requested_at = ?, cancel_requested_by = 'operator', descendants_confirmed_at = ? WHERE invocation_id = 'inv_pppppppp'", T, T)
        self.rejects("immutable", "UPDATE invocation_reconciliations SET resolution = 'terminated_group'")
        self.x("UPDATE invocations SET state = 'failed' WHERE invocation_id = 'inv_pppppppp'")
        # a group termination supports cancelled (and not running)
        self.lease("lease_dddddddd", 2, scope="discovery")
        self.invocation("inv_disc0001", kind="discovery", lease="lease_dddddddd")
        self.to_running("inv_disc0001")
        self.to_unknown("inv_disc0001", T)
        self.x(ins.replace("'rec_00000001', 'inv_pppppppp'", "'rec_00000003', 'inv_disc0001'"), T, "terminated_group", "execution_group_termination", h("7"), T, T)
        self.rejects(refused, "UPDATE invocations SET state = 'running' WHERE invocation_id = 'inv_disc0001'")
        self.x("UPDATE invocations SET state = 'cancelled', cancel_requested_at = ?, cancel_requested_by = 'operator', descendants_confirmed_at = ? WHERE invocation_id = 'inv_disc0001'", T, T)

    def test_found_committed_needs_the_final_receipt(self) -> None:
        self.invocation("inv_pppppppp")
        self.to_running("inv_pppppppp")
        self.to_unknown("inv_pppppppp", T)
        self.reconcile("inv_pppppppp", "found_committed")
        commit = "UPDATE invocations SET state = 'committed', result_payload_digest = ?, result_staged_at = ? WHERE invocation_id = 'inv_pppppppp'"
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition", before=0)
        self.rejects("reconciliation record of this episode", commit, h("d"), T)  # only an interim receipt exists
        self.receipt("op_00000002", "inv_pppppppp", kind="final_outcome", before=1)
        self.x(commit, h("d"), T)

    def test_never_observed_job_recovered_by_handle(self) -> None:
        """Ruling R2.4: a job never observed running (no process identity) is
        recovered through its stable handle and retained result."""
        self.invocation("inv_pppppppp")
        self.to_launching("inv_pppppppp")
        self.to_unknown("inv_pppppppp", T)
        self.reconcile("inv_pppppppp", "found_result", digest=h("d"))
        self.x("UPDATE invocations SET state = 'result_ready', result_payload_digest = ?, result_staged_at = ? WHERE invocation_id = 'inv_pppppppp'", h("d"), T)
        self.assertEqual(self.rows("SELECT job_handle, host_id, boot_id FROM invocations WHERE invocation_id = 'inv_pppppppp'"), [("job-inv_pppppppp", None, None)])

    def test_running_requires_process_identity_not_a_pid(self) -> None:
        self.invocation("inv_pppppppp")
        self.to_launching("inv_pppppppp")
        self.rejects("CHECK constraint failed", "UPDATE invocations SET state = 'running', host_id = 'dev' WHERE invocation_id = 'inv_pppppppp'")
        self.x("UPDATE invocations SET state = 'running', host_id = 'dev', boot_id = 'b1', start_fingerprint = 'st=1' WHERE invocation_id = 'inv_pppppppp'")
        columns = {row[1] for row in self.x("PRAGMA table_info(invocations)")}
        self.assertNotIn("pid", columns)

    def test_launching_requires_launch_intent(self) -> None:
        """Launch intent (before spawn) carries the stable job handle — SQL and
        JSON now agree (A5)."""
        self.invocation("inv_pppppppp")
        self.rejects("CHECK constraint failed", "UPDATE invocations SET state = 'launching' WHERE invocation_id = 'inv_pppppppp'")
        self.rejects("CHECK constraint failed", "UPDATE invocations SET state = 'launching', launch_intent_at = ? WHERE invocation_id = 'inv_pppppppp'", T)
        self.to_launching("inv_pppppppp")

    def test_process_identity_is_write_once(self) -> None:
        """D10 rewrite (A5, ruling R2.4): every identity/config/admission pin is
        write-once; observed process identity (host and container included) is
        write-once once observed and preserved in every later state."""
        self.invocation("inv_pppppppp")
        self.to_running("inv_pppppppp")  # container_id not observed yet
        self.x("UPDATE invocations SET container_id = 'ctr-1' WHERE invocation_id = 'inv_pppppppp'")  # first observation is allowed
        pins = (("kind", "'verification'"), ("topic_id", f"'{OTHER}'"), ("parent_invocation_id", "'inv_pppppppp'"),
                ("requested_by_invocation_id", "'inv_pppppppp'"), ("lease_id", "NULL"), ("capability_id", "'cap_other000'"),
                ("config_bundle_hash", f"'{h('0')}'"), ("admission_context", "'pre-contract/1'"), ("contract_revision", "2"),
                ("brief_ref", "'brief-1'"), ("brief_version", "1"), ("brief_hash", f"'{h('b')}'"), ("brief_confirmation_decision_id", "'opd_x'"),
                ("admitted_at", "'2026-09-26T00:00:00Z'"), ("launch_intent_at", "'2026-09-26T00:00:00Z'"), ("job_handle", "'job-other'"),
                ("host_id", "'other-host'"), ("container_id", "'ctr-2'"), ("container_id", "NULL"), ("host_id", "NULL"),
                ("boot_id", "'b2'"), ("start_fingerprint", "'st=2'"))
        for column, value in pins:
            with self.subTest(column=column, value=value):
                self.rejects("write-once", f"UPDATE invocations SET {column} = {value} WHERE invocation_id = 'inv_pppppppp'")
        self.x("UPDATE invocations SET state = 'result_ready', result_payload_digest = ?, result_staged_at = ? WHERE invocation_id = 'inv_pppppppp'", h("d"), T)
        self.rejects("write-once", "UPDATE invocations SET result_payload_digest = ? WHERE invocation_id = 'inv_pppppppp'", h("e"))
        self.assertEqual(self.rows("SELECT host_id, container_id, boot_id, start_fingerprint FROM invocations WHERE invocation_id = 'inv_pppppppp'"), [("dev", "ctr-1", "b1", "st=1")])

    def test_delegate_names_its_parent(self) -> None:
        self.invocation("inv_pppppppp")
        self.to_running("inv_pppppppp")
        self.rejects("a delegate runs under", *self.raw_invocation(invocation_id="inv_dddddddd", kind="delegate", lease_id=None))
        self.invocation("inv_dddddddd", kind="delegate", lease=None, parent="inv_pppppppp")

    def test_delegate_inherits_a_running_parent_of_its_topic(self) -> None:
        """R2.1/R2.2: a delegate runs under a launching/running non-delegate parent
        of its topic, with the parent's admission pins and no lease of its own."""
        rev = self.approved_revision(TOPIC)
        self.invocation("inv_pppppppp")
        refused = "a delegate runs under"
        self.rejects(refused, *self.raw_invocation(invocation_id="inv_d0000001", kind="delegate", lease_id=None, parent_invocation_id="inv_pppppppp", contract_revision=rev))  # parent not started
        self.to_running("inv_pppppppp")
        self.rejects("CHECK constraint failed", *self.raw_invocation(invocation_id="inv_d0000001", kind="delegate", lease_id="lease_aaaaaaaa", parent_invocation_id="inv_pppppppp", contract_revision=rev))  # own lease
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        self.to_running("inv_oooooooo")
        self.rejects(refused, *self.raw_invocation(invocation_id="inv_d0000001", kind="delegate", lease_id=None, parent_invocation_id="inv_oooooooo", contract_revision=rev))  # other topic's parent
        # different pins: revision 2 is approved by amendment after the parent was admitted under revision 1
        self.contract(TOPIC, 2)
        self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 1", TOPIC)
        self.approve_contract(TOPIC, 2, kind="amendment_approval")
        self.rejects(refused, *self.raw_invocation(invocation_id="inv_d0000001", kind="delegate", lease_id=None, parent_invocation_id="inv_pppppppp", contract_revision=2))
        self.invocation("inv_d0000001", kind="delegate", lease=None, parent="inv_pppppppp")
        self.to_running("inv_d0000001")
        self.rejects(refused, *self.raw_invocation(invocation_id="inv_d0000002", kind="delegate", lease_id=None, parent_invocation_id="inv_d0000001", contract_revision=rev))  # no delegate chains

    def test_capability_is_unique_per_invocation(self) -> None:
        self.invocation("inv_pppppppp")
        self.lease("lease_dddddddd", 2, scope="discovery")
        self.rejects("UNIQUE constraint failed: invocations.capability_id", *self.raw_invocation(invocation_id="inv_vvvvvvvv", kind="discovery", lease_id="lease_dddddddd", capability_id="cap_pppppppp"))


class CommitFencingTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")

    def test_operation_id_reuse_rejected_and_receipts_immutable(self) -> None:
        self.receipt("op_00000001", "inv_pppppppp")
        stored = self.snapshot("operation_receipts")
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000001", "inv_pppppppp", before=1, kind="interim_transition", rid="rcpt_distinct1")
        self.assertIn("UNIQUE constraint failed: operation_receipts.operation_id", str(ctx.exception))
        self.rejects("operation receipts are immutable", "UPDATE operation_receipts SET payload_digest = ? WHERE operation_id = 'op_00000001'", h("0"))
        self.rejects("never deleted", "DELETE FROM operation_receipts WHERE operation_id = 'op_00000001'")
        # REPLACE on the primary key and on the alternate receipt_id key (A1);
        # every key is attacked in test_store_history.py.
        # (the JSON is rewritten alongside, so each attempt is a consistent row and only the conflict decides)
        replace = ("INSERT OR REPLACE INTO operation_receipts SELECT ?, ?, operation_kind, invocation_id, topic_id, ?, ?, lease_id, lease_generation, admission_context, contract_revision, brief_hash, config_bundle_hash, state_revision_before + ?, state_revision_after + ?, validator_version, policy_version, "
                   "json_set(receipt, '$.operation_id', ?, '$.receipt_id', ?, '$.request_fingerprint', ?, '$.payload_digest', ?, '$.state_revision_before', state_revision_before + ?, '$.state_revision_after', state_revision_after + ?), committed_at "
                   "FROM operation_receipts WHERE operation_id = 'op_00000001'")
        for op, rid, shift in (("op_00000001", "rcpt_00000001", 0), ("op_00000002", "rcpt_00000001", 5)):
            with self.subTest(operation=op):
                self.rejects("replay protection depends on them", replace, op, rid, h("9"), h("0"), shift, shift, op, rid, h("9"), h("0"), shift, shift)
        self.assertEqual(self.snapshot("operation_receipts"), stored)

    def test_one_final_outcome_per_invocation(self) -> None:
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition", before=0)
        self.receipt("op_00000002", "inv_pppppppp", kind="interim_transition", before=1)
        self.receipt("op_00000003", "inv_pppppppp", kind="final_outcome", before=2)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000004", "inv_pppppppp", kind="final_outcome", before=3)
        self.assertIn("UNIQUE constraint failed: operation_receipts.invocation_id", str(ctx.exception))

    def test_one_commit_per_state_revision(self) -> None:
        self.lease("lease_dddddddd", 2, scope="discovery")
        self.invocation("inv_qqqqqqqq", kind="discovery", lease="lease_dddddddd")
        self.receipt("op_00000001", "inv_pppppppp", before=4)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000002", "inv_qqqqqqqq", lease="lease_dddddddd", gen=2, before=4)
        self.assertIn("UNIQUE constraint failed: operation_receipts.topic_id, operation_receipts.state_revision_after", str(ctx.exception))

    def test_stale_generation_rejected(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000001", "inv_pppppppp", gen=0)
        self.assertIn("stale generation", str(ctx.exception))
        self.receipt("op_00000001", "inv_pppppppp", gen=1)

    def test_released_lease_cannot_commit(self) -> None:
        self.x("UPDATE leases SET released_at = ?, release_reason = 'expired' WHERE lease_id = 'lease_aaaaaaaa'", T)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000001", "inv_pppppppp")
        self.assertIn("released lease", str(ctx.exception))

    def test_cross_topic_commit_rejected(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000001", "inv_pppppppp", tid=OTHER)
        self.assertIn("cross-topic", str(ctx.exception))

    def test_commit_under_another_invocations_lease_rejected(self) -> None:
        self.lease("lease_vvvvvvvv", 2, scope="verification")
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000001", "inv_pppppppp", lease="lease_vvvvvvvv", gen=2)
        self.assertIn("foreign lease", str(ctx.exception))

    def test_delegate_commits_under_parent_lease(self) -> None:
        self.to_running("inv_pppppppp")
        self.invocation("inv_dddddddd", kind="delegate", lease=None, parent="inv_pppppppp")
        self.receipt("op_00000001", "inv_dddddddd")

    def test_state_revision_advances_by_exactly_one(self) -> None:
        self.x("UPDATE queue_entries SET state_revision = 1 WHERE topic_id = ?", TOPIC)
        self.rejects("advances by exactly one", "UPDATE queue_entries SET state_revision = 3 WHERE topic_id = ?", TOPIC)
        self.rejects("advances by exactly one", "UPDATE queue_entries SET state_revision = 0 WHERE topic_id = ?", TOPIC)


class OrdinalAndTriggerTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.lease("lease_cccccccc", 2, scope="checkpoint")
        self.invocation("inv_kkkkkkkk", kind="checkpoint", lease="lease_cccccccc")

    def test_only_research_pass_final_outcomes_get_ordinals(self) -> None:
        self.receipt("op_00000001", "inv_kkkkkkkk", lease="lease_cccccccc", gen=2, before=0)
        self.rejects("ordinals go only to", "INSERT INTO research_ordinals VALUES (?, 1, 'inv_kkkkkkkk', 'op_00000001')", TOPIC)
        self.receipt("op_00000002", "inv_pppppppp", kind="interim_transition", before=1)
        self.rejects("ordinals go only to", "INSERT INTO research_ordinals VALUES (?, 1, 'inv_pppppppp', 'op_00000002')", TOPIC)
        self.receipt("op_00000003", "inv_pppppppp", before=2)
        self.x("INSERT INTO research_ordinals VALUES (?, 1, 'inv_pppppppp', 'op_00000003')", TOPIC)

    def test_ordinals_dense_and_once_per_invocation(self) -> None:
        self.receipt("op_00000001", "inv_pppppppp", before=0)
        self.rejects("densely", "INSERT INTO research_ordinals VALUES (?, 2, 'inv_pppppppp', 'op_00000001')", TOPIC)
        self.x("INSERT INTO research_ordinals VALUES (?, 1, 'inv_pppppppp', 'op_00000001')", TOPIC)
        self.rejects("UNIQUE constraint failed", "INSERT INTO research_ordinals VALUES (?, 2, 'inv_pppppppp', 'op_00000001')", TOPIC)

    def test_trigger_identity_unique_and_handled_is_final(self) -> None:
        insert = "INSERT INTO review_triggers (trigger_identity, topic_id, reason_code, signal_source, cause_ref, observed_at) VALUES (?, ?, 'persistent_contradiction', 'deterministic', 'CL-3', ?)"
        self.x(insert, h("1"), TOPIC, T)
        self.rejects("UNIQUE constraint failed: review_triggers.trigger_identity", insert, h("1"), TOPIC, T)
        self.receipt("op_00000009", "inv_pppppppp", kind="interim_transition", before=0)
        self.receipt("op_00000010", "inv_pppppppp", kind="interim_transition", before=1)
        self.x("INSERT INTO review_episodes (episode_id, topic_id, kind, opened_at, opened_by_operation_id) VALUES ('ep-1', ?, 'method_fit', ?, 'op_00000009')", TOPIC, T)
        self.x("UPDATE review_triggers SET episode_id = 'ep-1', handled_at = ? WHERE trigger_identity = ?", T, h("1"))
        self.x("UPDATE review_episodes SET closed_at = ?, closed_by_operation_id = 'op_00000010' WHERE episode_id = 'ep-1'", T)
        self.rejects("a handled trigger stays handled", "UPDATE review_triggers SET handled_at = NULL WHERE trigger_identity = ?", h("1"))
        self.rejects("never deleted", "DELETE FROM review_triggers WHERE trigger_identity = ?", h("1"))
        # A1 / RG-1b(e): replaying the trigger unhandled after its episode closed,
        # through REPLACE, cannot reopen it; read back the stored row.
        self.rejects("never deleted", insert.replace("INSERT", "INSERT OR REPLACE"), h("1"), TOPIC, T)
        self.assertEqual(self.rows("SELECT episode_id, handled_at FROM review_triggers WHERE trigger_identity = ?", h("1")), [("ep-1", T)])


class AdmissionAndLeaseTest(StoreTestCase):
    """A4 (typed admission context; pre-contract work can finalize without a
    Contract v2 FK, scientific commits still need the approved protocol) and
    ruling R2.1 (per-scope leases, one owning invocation, kind/scope match)."""

    def discovery(self, iid: str = "inv_scope001", lease: str = "lease_dddddddd", gen: int = 1, **kw) -> None:
        self.lease(lease, gen, scope="discovery")
        self.invocation(iid, kind="discovery", lease=lease, pre_contract=True, **kw)

    def test_pre_contract_discovery_can_finalize(self) -> None:
        """The review's probe: a scoping discovery on a topic with no approved
        contract (drafts exist here — ZeroContractDiscoveryTest runs it with
        none at all) commits its final receipt (it hit an FK failure before)."""
        self.discovery()
        self.receipt("op_00000001", "inv_scope001", lease="lease_dddddddd", kind="final_outcome")
        self.assertEqual(self.rows("SELECT admission_context, contract_revision, brief_hash FROM operation_receipts"), [("pre-contract/1", None, h("b"))])

    def test_pre_contract_admission_needs_the_confirmed_brief(self) -> None:
        """C-12 / G-4 with durable briefs (0b): pre-contract pins name the
        topic's confirmed brief version (id, version, hash) and the decision
        that confirmed it. Near-misses, one dimension each, are refused: a
        rejected confirmation of the same version, a second approved
        confirmation that is not the one recorded, a decision of another kind,
        another hash, this version's hash under another version number or
        brief id, a version that was stored and has an approved
        confirmation but was never confirmed, and another topic's confirmed
        brief. Decisions about briefs that are not stored cannot even be
        recorded (G-13 subject existence). The exact pins are accepted."""
        brief, version, bhash, did = self.confirm_brief(TOPIC)
        self.lease("lease_dddddddd", 1, scope="discovery")
        for case, kw in (("another brief id", dict(ref="brief-2", rev=version, hsh=bhash)), ("an unstored version", dict(ref=brief, rev=2, hsh=bhash)),
                         ("another hash", dict(ref=brief, rev=version, hsh=h("9"))), ("another topic", dict(tid=OTHER, ref=brief, rev=version, hsh=bhash))):
            with self.subTest(unrecordable=case):
                self.rejects("must name an existing subject", "INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at) "
                             "VALUES ('opd_nosubject', ?, 'brief_confirmation', 'approved', 'intake_brief', ?, ?, ?, 'user', ?)", kw.get("tid", TOPIC), kw["ref"], kw["rev"], kw["hsh"], T)
        self.decision("opd_rejected", "brief_confirmation", disposition="rejected", ref=brief, rev=version, hsh=bhash)
        self.decision("opd_second00", "brief_confirmation", ref=brief, rev=version, hsh=bhash)
        self.decision("opd_wrongknd", "publication_approval", ref=brief, rev=version, hsh=bhash)  # task 2a: a kind whose subject has no stored table (a scope approval now needs a stored report)
        v2 = self.brief(TOPIC, brief, 2, parent=1)
        self.decision("opd_v2unconf", "brief_confirmation", ref=brief, rev=2, hsh=v2)
        other = self.confirm_brief(OTHER, "brief-o", 1)
        pins = dict(kind="discovery", lease_id="lease_dddddddd", admission_context="pre-contract/1", contract_revision=None)
        exact = dict(brief_ref=brief, brief_version=version, brief_hash=bhash, brief_confirmation_decision_id=did)
        stored = self.snapshot("invocations")
        for case, over in (("a rejected confirmation", dict(brief_confirmation_decision_id="opd_rejected")),
                           ("an approved confirmation that is not the recorded one", dict(brief_confirmation_decision_id="opd_second00")),
                           ("a decision of another kind", dict(brief_confirmation_decision_id="opd_wrongknd")),
                           ("another hash", dict(brief_hash=h("9"))),
                           ("another version number with this version's hash", dict(brief_version=2)),
                           ("another brief id with this version's hash", dict(brief_ref="brief-9")),
                           ("a stored, never-confirmed version", dict(brief_version=2, brief_hash=v2, brief_confirmation_decision_id="opd_v2unconf")),
                           ("another topic's confirmed brief", dict(zip(("brief_ref", "brief_version", "brief_hash", "brief_confirmation_decision_id"), other)))):
            with self.subTest(pins=case):
                self.rejects("pre-contract work needs a confirmed brief", *self.raw_invocation(invocation_id="inv_scope001", **pins, **dict(exact, **over)))
        self.assertEqual(self.snapshot("invocations"), stored)
        self.x(*self.raw_invocation(invocation_id="inv_scope001", **pins, **exact))

    def test_pre_contract_admission_pins_the_current_confirmed_version(self) -> None:
        """Once the brief re-versions and the new version is confirmed, the
        superseded version admits no new work (as a superseded contract
        admits no new contract/1 work); work already admitted keeps its pins."""
        brief, version, bhash, did = self.confirm_brief(TOPIC)
        self.lease("lease_dddddddd", 1, scope="discovery")
        self.lease("lease_eeeeeeee", 2, scope="research")
        old_pins = dict(admission_context="pre-contract/1", contract_revision=None, brief_ref=brief, brief_version=1, brief_hash=bhash, brief_confirmation_decision_id=did)
        self.x(*self.raw_invocation(invocation_id="inv_scope001", kind="discovery", lease_id="lease_dddddddd", **old_pins))
        v2 = self.brief(TOPIC, brief, 2, parent=1)
        self.decision("opd_confirm2", "brief_confirmation", ref=brief, rev=2, hsh=v2)
        self.x("UPDATE intake_briefs SET status = 'superseded' WHERE topic_id = ? AND brief_id = ? AND version = 1", TOPIC, brief)
        self.x("UPDATE intake_briefs SET status = 'confirmed', confirmed_by_decision_id = 'opd_confirm2' WHERE topic_id = ? AND brief_id = ? AND version = 2", TOPIC, brief)
        self.rejects("pre-contract work needs a confirmed brief", *self.raw_invocation(invocation_id="inv_scope002", kind="research_pass", lease_id="lease_eeeeeeee", **old_pins))
        self.x(*self.raw_invocation(invocation_id="inv_scope002", kind="research_pass", lease_id="lease_eeeeeeee",
                                    **dict(old_pins, brief_version=2, brief_hash=v2, brief_confirmation_decision_id="opd_confirm2")))
        self.assertEqual(self.rows("SELECT invocation_id, brief_version FROM invocations ORDER BY invocation_id"), [("inv_scope001", 1), ("inv_scope002", 2)])

    def test_pre_contract_admission_closes_once_a_contract_is_approved(self) -> None:
        self.approve_contract(TOPIC, 1)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.discovery()
        self.assertIn("no approved contract", str(ctx.exception))
        self.invocation("inv_disc0001", kind="discovery", lease="lease_dddddddd")  # contract-admitted discovery on the same lease is fine

    def test_pre_contract_admission_only_for_scoping_kinds(self) -> None:
        brief, version, bhash, did = self.confirm_brief(TOPIC)
        for kind, scope in (("verification", "verification"), ("checkpoint", "checkpoint")):
            with self.subTest(kind=kind):
                lid = f"lease_{kind[:8]:0<8}"
                self.lease(lid, 1 if kind == "verification" else 2, scope=scope)
                self.rejects("CHECK constraint failed", *self.raw_invocation(invocation_id=f"inv_{kind[:8]:0<8}", kind=kind, lease_id=lid, admission_context="pre-contract/1", contract_revision=None,
                                                                             brief_ref=brief, brief_version=version, brief_hash=bhash, brief_confirmation_decision_id=did))
        self.lease("lease_rrrrrrrr", 3)
        self.invocation("inv_draft001", lease="lease_rrrrrrrr", pre_contract=True)  # the primary drafting the contract (S3)

    def test_contract_admission_needs_an_approved_revision(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.rejects("contract work needs an approved contract revision", *self.raw_invocation(invocation_id="inv_pppppppp", contract_revision=1))
        self.approve_contract(TOPIC, 1)
        self.invocation("inv_pppppppp")

    def test_receipt_carries_the_invocations_admission_and_config(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")  # pinned to approved revision 1
        self.contract(TOPIC, 2)
        self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 1", TOPIC)
        self.approve_contract(TOPIC, 2, kind="amendment_approval")
        pinned = "admission pins or config bundle differ"
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000001", "inv_pppppppp", admission=("contract/1", 2, None))  # the now-current revision is not the invocation's
        self.assertIn(pinned, str(ctx.exception))
        for admission in (("pre-contract/1", None, h("b")), ("pre-contract/1", 1, None)):  # the second differs in context alone
            with self.subTest(admission=admission):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.receipt("op_00000001", "inv_pppppppp", admission=admission)
                self.assertIn(pinned, str(ctx.exception))
        self.rejects(pinned, "INSERT INTO operation_receipts (operation_id, receipt_id, operation_kind, invocation_id, topic_id, request_fingerprint, payload_digest, lease_id, lease_generation, admission_context, contract_revision, config_bundle_hash, state_revision_before, state_revision_after, validator_version, policy_version, receipt, committed_at) "
                     "VALUES ('op_00000001', 'rcpt_00000001', 'final_outcome', 'inv_pppppppp', ?, ?, ?, 'lease_aaaaaaaa', 1, 'contract/1', 1, ?, 0, 1, 'v1', 'p1', ?, ?)",
                     TOPIC, h("f"), h("d"), h("0"), json.dumps(self.receipt_body("op_00000001", "rcpt_00000001", "final_outcome", "inv_pppppppp", TOPIC, 0)), T)  # another config bundle
        self.receipt("op_00000001", "inv_pppppppp")

    RECEIPT_INSERT = ("INSERT INTO operation_receipts (operation_id, receipt_id, operation_kind, invocation_id, topic_id, request_fingerprint, payload_digest, lease_id, lease_generation, "
                      "admission_context, contract_revision, brief_hash, config_bundle_hash, state_revision_before, state_revision_after, validator_version, policy_version, receipt, committed_at) "
                      "VALUES ('op_00000001', 'rcpt_00000001', 'final_outcome', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, 'v1', 'p1', ?, ?)")

    @staticmethod
    def with_field(body: dict, path: str, value) -> str:
        out = json.loads(json.dumps(body))
        *parents, last = path.split(".")
        node = out
        for part in parents:
            node = node[part]
        node[last] = value
        return json.dumps(out)

    def test_receipt_json_admission_matches_its_columns(self) -> None:
        """A10 / RA6: every identity and version field the commit receipt JSON
        duplicates equals its column or pinned reference. The review's probe
        fields first (topic, invocation, revision-before, validator), then
        every other one, then the admission references that need a join
        (contract hash; brief id, version and confirmation of a pre-contract
        receipt). Each probe changes ONE field of an otherwise consistent,
        schema-shaped receipt, so only the JSON/row binding can refuse it; a
        receipt recording the release of its own fencing lease is accepted."""
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        base = self.receipt_body("op_00000001", "rcpt_00000001", "final_outcome", "inv_pppppppp", TOPIC, 0)
        row = ("inv_pppppppp", TOPIC, h("f"), h("d"), "lease_aaaaaaaa", 1, "contract/1", 1, None, h("c"))
        check, reference = "CHECK constraint failed", "admission references must be its pins"
        for path, value, fragment in (
                ("topic_id", "fleet-a:intake-latency", check), ("invocation_id", "inv_01J8ZQ3W2X", check),
                ("state_revision_before", 41, check), ("validation.validator_version", "outcome-validator/1.0.0", check),
                ("operation_id", "op_00000009", check), ("receipt_id", "rcpt_00000009", check), ("operation_kind", "interim_transition", check),
                ("request_fingerprint", h("0"), check), ("payload_digest", h("0"), check), ("state_revision_after", 2, check),
                ("validation.policy_version", "p9", check), ("committed_at", "2026-09-26T00:00:00Z", check),
                ("admission.context", "pre-contract/1", check), ("admission.contract.revision", 2, check),
                ("admission.brief", {"brief_id": None, "version": None, "content_hash": h("b")}, check),  # a brief hash on a contract receipt
                ("effects.lease_release", {"lease_id": "lease_zzzzzzzz", "generation": 1, "rest_state": "idle"}, check),
                ("effects.lease_release", {"lease_id": "lease_aaaaaaaa", "generation": 2, "rest_state": "idle"}, check),
                ("admission.contract.content_hash", h("9"), reference)):
            with self.subTest(field=path, value=value):
                self.rejects(fragment, self.RECEIPT_INSERT, *row, self.with_field(base, path, value), T)
        self.assertEqual(self.rows("SELECT count(*) FROM operation_receipts"), [(0,)])
        self.x(self.RECEIPT_INSERT, *row, self.with_field(base, "effects.lease_release", {"lease_id": "lease_aaaaaaaa", "generation": 1, "rest_state": "idle"}), T)

    def test_pre_contract_receipt_json_names_the_pinned_brief(self) -> None:
        """RA6 / C-12 for the pre-contract admission references: the receipt JSON's
        brief id, version and confirming decision are the invocation's pins."""
        self.discovery()
        base = self.receipt_body("op_00000001", "rcpt_00000001", "final_outcome", "inv_scope001", TOPIC, 0)
        row = ("inv_scope001", TOPIC, h("f"), h("d"), "lease_dddddddd", 1, "pre-contract/1", None, h("b"), h("c"))
        for path, value in (("admission.brief.brief_id", "brief-2"), ("admission.brief.version", 2), ("admission.brief_confirmation_decision_id", "opd_other000")):
            with self.subTest(field=path):
                self.rejects("admission references must be its pins", self.RECEIPT_INSERT, *row, self.with_field(base, path, value), T)
        self.rejects("CHECK constraint failed", self.RECEIPT_INSERT, *row, self.with_field(base, "admission.brief.content_hash", h("9")), T)
        self.x(self.RECEIPT_INSERT, *row, json.dumps(base), T)

    def test_pre_contract_receipt_carries_the_brief_pinned_at_admission(self) -> None:
        self.discovery()
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.receipt("op_00000001", "inv_scope001", lease="lease_dddddddd", admission=("pre-contract/1", None, h("9")))
        self.assertIn("admission pins or config bundle differ", str(ctx.exception))
        self.receipt("op_00000001", "inv_scope001", lease="lease_dddddddd")

    def test_admission_pins_are_exclusive(self) -> None:
        """A contract-admitted row carries no brief pins; a pre-contract row no
        contract revision (probes chosen so the admission trigger passes)."""
        brief, version, bhash, did = self.confirm_brief(TOPIC)
        self.lease("lease_dddddddd", 1, scope="discovery")
        self.rejects("CHECK constraint failed", *self.raw_invocation(invocation_id="inv_scope001", kind="discovery", lease_id="lease_dddddddd", admission_context="pre-contract/1", contract_revision=1,
                                                                     brief_ref=brief, brief_version=version, brief_hash=bhash, brief_confirmation_decision_id=did))
        self.approve_contract(TOPIC, 1)
        self.rejects("CHECK constraint failed", *self.raw_invocation(invocation_id="inv_disc0001", kind="discovery", lease_id="lease_dddddddd", contract_revision=1,
                                                                     brief_ref=brief, brief_version=version, brief_hash=bhash, brief_confirmation_decision_id=did))
        self.x(*self.raw_invocation(invocation_id="inv_disc0001", kind="discovery", lease_id="lease_dddddddd", contract_revision=1))

    def test_pre_contract_research_pass_earns_no_ordinal(self) -> None:
        """C-12 / C-7: a scientific counter needs the approved protocol."""
        self.lease("lease_rrrrrrrr", 1)
        self.invocation("inv_draft001", lease="lease_rrrrrrrr", pre_contract=True)
        self.receipt("op_00000001", "inv_draft001", lease="lease_rrrrrrrr", kind="final_outcome")
        self.rejects("ordinals go only to", "INSERT INTO research_ordinals VALUES (?, 1, 'inv_draft001', 'op_00000001')", TOPIC)

    SCREEN = ("INSERT INTO screening_assessments (assessment_id, topic_id, work_id, contract_revision, eligibility_protocol_version, framing_version, stage, decision, reason_code, criterion_results, actor_kind, invocation_id, recorded_by_operation_id, created_at) "
              "VALUES (?, ?, 'wrk_00000001', ?, ?, ?, 'abstract', 'exclude', 'EC-1', '{}', 'primary', ?, ?, ?)")
    LINK = ("INSERT INTO claim_source_links (claim_id, claim_revision, work_id, source_version, topic_id, contract_revision, obligation_id, spans, contribution, evidence_origin_lineage, created_at) "
            "VALUES (?, 1, 'wrk_00000001', 'v1', ?, ?, 'O-1', '[]', 'answer', 'study-1', ?)")
    DOSSIER = ("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) "
               "VALUES (?, 1, ?, 1, 'eval-1', ?, ?, ?)")

    def evidence_basics(self) -> None:
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000001', 'doi', '10.1/x', ?)", T)
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'text/plain', ?)", h("7"), T)

    def claim(self, cid: str, producer: str, tid: str = TOPIC) -> None:
        self.x("INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES (?, 1, ?, ?, ?, 0, NULL, 'provisional', ?)", cid, tid, h("7"), producer, T)

    def scientific_row_counts(self) -> list[tuple]:
        return self.rows("SELECT (SELECT count(*) FROM screening_assessments), (SELECT count(*) FROM claim_source_links), (SELECT count(*) FROM dossiers)")

    def test_pre_contract_work_records_no_scientific_disposition(self) -> None:
        """RA3, the review's probe first: with only draft contracts, a confirmed
        brief and a pre-contract research pass whose final receipt committed, a
        primary 'exclude' screening assessment naming draft revision 1 is
        refused — as is one naming the draft that carries an obligation, a
        claim-source link to that draft's obligation, and a dossier under a
        draft. RA3-R: a valid contract_approval of that draft cannot be
        recorded on it while it stays a draft, its structural approval fails
        (unrated facet), and the dossier under it is still refused; the
        contract rows are unchanged. Genuine scoping stays open to the same
        pass: its search observation and a provisional claim are recorded."""
        self.contract_with_rows(TOPIC, 2, facets=(facet("F-1"),), obligations=(obligation("O-1", ("F-1",)),))  # a draft with an obligation
        self.lease("lease_rrrrrrrr", 1)
        self.invocation("inv_draft001", lease="lease_rrrrrrrr", pre_contract=True)
        self.receipt("op_00000001", "inv_draft001", lease="lease_rrrrrrrr", kind="final_outcome")
        self.evidence_basics()
        self.x("INSERT INTO search_observations (observation_id, invocation_id, topic_id, request_identity, attempt, lane, request, obligation_ids, started_at, coverage_state, result_count, completeness, policy_version, page_outcome, gateway_call_ref) "
               "VALUES ('o1', 'inv_draft001', ?, ?, 1, 'crossref', ?, '[]', ?, 'searched_ok', 1, 'complete', 'pol1', 'end_unknown', 'gw-call:1')", TOPIC, h("4"), FIND_REQUEST, T)
        self.claim("clm_00000001", "inv_draft001")
        refused = "recorded by contract-admitted work under the approved protocol revision it names"
        for rev in (1, 2):
            with self.subTest(draft_revision=rev):
                self.rejects(refused, self.SCREEN, "sa1", TOPIC, rev, 1, 1, "inv_draft001", "op_00000001", T)
        self.rejects("produced by contract-admitted work", self.LINK, "clm_00000001", TOPIC, 2, T)
        self.rejects("never a draft", self.DOSSIER, TOPIC, 2, h("3"), h("7"), T)
        contracts = self.snapshot("contract_revisions")
        self.decision("opd_appr0002", "contract_approval", rev=2, hsh=self.content_hash_of(TOPIC, 2))
        self.rejects("recorded only by the draft -> approved transition", "UPDATE contract_revisions SET approved_by_decision_id = 'opd_appr0002' WHERE topic_id = ? AND revision = 2", TOPIC)
        self.rejects("approval needs complete obligation/facet rows", "UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = 'opd_appr0002' WHERE topic_id = ? AND revision = 2", TOPIC)
        self.rejects("never a draft", self.DOSSIER, TOPIC, 2, h("3"), h("7"), T)
        self.assertEqual(self.snapshot("contract_revisions"), contracts)
        self.assertEqual(self.scientific_row_counts(), [(0, 0, 0)])
        self.assertEqual(self.rows("SELECT count(*) FROM search_observations"), [(1,)])

    def test_scientific_rows_bind_the_approved_protocol_they_name(self) -> None:
        """RA3 valid control and pin near-misses. Revision 1 is approved and
        work A is admitted under it and commits; then an amendment approves
        revision 3 (draft 2 was rated) and work B is admitted under it and
        commits; draft 4 sits beside it. Under revision 3, B's commit records a
        screening assessment, a link for B's claim and a dossier. Each
        near-miss differs in one pin: naming the draft; recorded by A's commit
        (pinned to revision 1); assessed by A; another framing or
        eligibility-protocol version; a link for A's claim; a link naming this
        topic's obligation for another topic's claim. RA3-R: the dossier
        controls rest on actual approval history, read back — revision 1
        passed approval and was superseded by the amendment, keeping its
        decision, so a dossier under it keeps its pins and is accepted; 3 is
        approved; drafts 2 and 4 never held a decision, and a dossier under 4
        is refused."""
        self.approve_contract(TOPIC, 1)
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_aaaaaaaa", lease="lease_aaaaaaaa", contract_rev=1)
        self.receipt("op_00000001", "inv_aaaaaaaa", kind="interim_transition", before=0)
        rev = self.approved_with_obligation(TOPIC)
        self.assertEqual(rev, 3)
        self.contract(TOPIC, 4, content_hash=self.chash(TOPIC, 4))
        self.lease("lease_bbbbbbbb", 2, scope="discovery")
        self.invocation("inv_bbbbbbbb", kind="discovery", lease="lease_bbbbbbbb", contract_rev=3)
        self.receipt("op_00000002", "inv_bbbbbbbb", lease="lease_bbbbbbbb", gen=2, kind="interim_transition", before=1)
        self.evidence_basics()
        self.claim("clm_0000000a", "inv_aaaaaaaa")
        self.claim("clm_0000000b", "inv_bbbbbbbb")
        self.assertEqual(self.approved_with_obligation(OTHER), 3)
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        self.claim("clm_0000000o", "inv_oooooooo", tid=OTHER)
        refused = "recorded by contract-admitted work under the approved protocol revision it names"
        for label, args in (("names the draft", (4, 1, 1, "inv_bbbbbbbb", "op_00000002")),
                            ("recorded by a commit pinned to revision 1", (3, 1, 1, "inv_bbbbbbbb", "op_00000001")),
                            ("assessed by work pinned to revision 1", (3, 1, 1, "inv_aaaaaaaa", "op_00000002")),
                            ("another framing version", (3, 1, 2, "inv_bbbbbbbb", "op_00000002")),
                            ("another eligibility-protocol version", (3, 2, 1, "inv_bbbbbbbb", "op_00000002"))):
            with self.subTest(screening=label):
                self.rejects(refused, self.SCREEN, "sa1", TOPIC, *args, T)
        linked = "produced by contract-admitted work"
        self.rejects(linked, self.LINK, "clm_0000000a", TOPIC, 3, T)  # A's claim: produced under revision 1
        self.rejects(linked, self.LINK, "clm_0000000o", TOPIC, 3, T)  # another topic's claim (its producer is pinned to that topic's revision 3)
        self.assertEqual(self.scientific_row_counts(), [(0, 0, 0)])
        self.x(self.SCREEN, "sa1", TOPIC, 3, 1, 1, "inv_bbbbbbbb", "op_00000002", T)
        self.x(self.LINK, "clm_0000000b", TOPIC, 3, T)
        self.x(self.DOSSIER, TOPIC, 3, h("3"), h("7"), T)
        self.assertEqual(self.scientific_row_counts(), [(1, 1, 1)])
        self.assertEqual(self.rows("SELECT revision, status, approved_by_decision_id FROM contract_revisions WHERE topic_id = ? ORDER BY revision", TOPIC),
                         [(1, "superseded", "opd_ca01t1xx"), (2, "draft", None), (3, "approved", "opd_ca03t1xx"), (4, "draft", None)])
        second = ("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) "
                  "VALUES (?, 2, ?, 1, 'eval-1', ?, ?, ?)")
        self.rejects("never a draft", second, TOPIC, 4, h("4"), h("7"), T)
        self.x(second, TOPIC, 1, h("4"), h("7"), T)  # the historically approved, now superseded revision 1
        self.assertEqual(self.scientific_row_counts(), [(1, 1, 2)])

    def test_invocation_owns_a_live_lease_of_its_kind_and_topic(self) -> None:
        self.approve_contract(TOPIC, 1)
        self.lease("lease_aaaaaaaa", 1)
        self.lease("lease_vvvvvvvv", 2, scope="verification")
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        refused = "owns a live lease of its topic"
        self.rejects(refused, *self.raw_invocation(invocation_id="inv_pppppppp", lease_id="lease_vvvvvvvv"))  # wrong scope
        self.rejects(refused, *self.raw_invocation(invocation_id="inv_pppppppp", lease_id="lease_zzzzzzzz"))  # other topic's lease
        self.invocation("inv_pppppppp")
        self.rejects("UNIQUE constraint failed: invocations.lease_id", *self.raw_invocation(invocation_id="inv_qqqqqqqq"))  # a second owner
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_aaaaaaaa'", T)
        self.lease("lease_bbbbbbbb", 3)
        self.x("UPDATE leases SET released_at = ?, release_reason = 'expired' WHERE lease_id = 'lease_bbbbbbbb'", T)
        self.rejects(refused, *self.raw_invocation(invocation_id="inv_qqqqqqqq", lease_id="lease_bbbbbbbb"))  # released
        self.lease("lease_cccccccc", 4)
        self.invocation("inv_qqqqqqqq", lease="lease_cccccccc")

    def test_newer_verification_generation_does_not_fence_research(self) -> None:
        """R2.1: a verification lease granted after the research lease has a larger
        generation; the research pass still commits at its own generation."""
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.lease("lease_vvvvvvvv", 2, scope="verification")
        self.invocation("inv_vvvvvvvv", kind="verification", lease="lease_vvvvvvvv")
        self.receipt("op_00000002", "inv_vvvvvvvv", lease="lease_vvvvvvvv", gen=2, before=0, kind="final_outcome")
        self.receipt("op_00000001", "inv_pppppppp", lease="lease_aaaaaaaa", gen=1, before=1, kind="final_outcome")
        self.assertEqual(self.rows("SELECT operation_id FROM operation_receipts ORDER BY state_revision_after"), [("op_00000002",), ("op_00000001",)])


class ZeroContractDiscoveryTest(StoreTestCase):
    """A4/RA3 with a genuinely empty contract table (the review's own probe):
    the base fixture's setUp writes draft contracts, so this class writes the
    two topics only."""

    def setUp(self) -> None:
        self.db = connect(self.APPLY_CONNECTION_CONTRACT)
        self.seed_configuration()
        for tid in (TOPIC, OTHER):
            self.x("INSERT INTO queue_entries (topic_id, fleet_id, priority, status, created_at, updated_at) VALUES (?, 'fleet-a', 1, 'awaiting_brief_confirmation', ?, ?)", tid, T, T)

    def test_pre_contract_discovery_can_finalize(self) -> None:
        """No contract row exists anywhere: a confirmed brief admits a scoping
        discovery, which runs, records its scoping observation, and commits its
        final receipt with a NULL contract pin carrying the brief."""
        self.assertEqual(self.rows("SELECT count(*) FROM contract_revisions"), [(0,)])
        self.lease("lease_dddddddd", 1, scope="discovery")
        self.invocation("inv_scope001", kind="discovery", lease="lease_dddddddd", pre_contract=True)
        self.to_running("inv_scope001")
        self.x("INSERT INTO search_observations (observation_id, invocation_id, topic_id, request_identity, attempt, lane, request, obligation_ids, started_at, coverage_state, result_count, completeness, policy_version, page_outcome, gateway_call_ref) "
               "VALUES ('o1', 'inv_scope001', ?, ?, 1, 'crossref', ?, '[]', ?, 'searched_ok', 2, 'complete', 'pol1', 'end_unknown', 'gw-call:1')", TOPIC, h("4"), FIND_REQUEST, T)
        self.receipt("op_00000001", "inv_scope001", lease="lease_dddddddd", kind="final_outcome")
        self.x("UPDATE invocations SET state = 'result_ready', result_payload_digest = ?, result_staged_at = ? WHERE invocation_id = 'inv_scope001'", h("d"), T)
        self.x("UPDATE invocations SET state = 'committed' WHERE invocation_id = 'inv_scope001'")
        self.assertEqual(self.rows("SELECT admission_context, contract_revision, brief_hash FROM operation_receipts"), [("pre-contract/1", None, h("b"))])
        self.assertEqual(self.rows("SELECT state FROM invocations"), [("committed",)])
        self.assertEqual(self.rows("SELECT count(*) FROM contract_revisions"), [(0,)])


class HashContractTest(StoreTestCase):
    """C-13 / Astra 0a ruling R1, frozen in 0b: every commit receipt records
    the canonicalization and request-fingerprint contracts its hashes were
    computed under; every decision receipt records the canonicalization
    contract of its logical hashes (spec_hash) and no fingerprint contract.
    Only the frozen versions are admitted. Oracle: the frozen strings written
    here by hand; each refusal leaves the table unchanged."""

    FROZEN_COMMIT = {"canonicalization": "jcs-rfc8785/1", "fingerprint": "commit-fingerprint/1"}

    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")

    def test_commit_receipt_records_the_frozen_contracts(self) -> None:
        refused = "CHECK constraint failed: operation_receipts_hash_contract_frozen"
        stored = self.snapshot("operation_receipts")
        for case, value in (("absent", DROP), ("null", None), ("fingerprint contract absent", {"canonicalization": "jcs-rfc8785/1"}),
                            ("canonicalization absent", {"fingerprint": "commit-fingerprint/1"}),
                            ("another fingerprint contract", {**self.FROZEN_COMMIT, "fingerprint": "commit-fingerprint/2"}),
                            ("another canonicalization", {**self.FROZEN_COMMIT, "canonicalization": "json-sort-keys/1"})):
            with self.subTest(case=case):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.receipt("op_00000001", "inv_pppppppp", receipt_overrides={"hash_contract": value})
                self.assertIn(refused, str(ctx.exception))
                self.assertEqual(self.snapshot("operation_receipts"), stored)
        self.receipt("op_00000001", "inv_pppppppp", receipt_overrides={"hash_contract": dict(self.FROZEN_COMMIT)})
        self.assertEqual(self.rows("SELECT json_extract(receipt, '$.hash_contract.fingerprint') FROM operation_receipts"), [("commit-fingerprint/1",)])

    def test_decision_receipt_records_the_frozen_canonicalization_only(self) -> None:
        refused = "CHECK constraint failed: decision_receipts_hash_contract_frozen"
        spec = self.spec()
        stored = self.snapshot("decision_receipts")
        for case, value in (("absent", DROP), ("another canonicalization", {"canonicalization": "json-sort-keys/1"}),
                            ("a fingerprint contract it has no fingerprint for", {"canonicalization": "jcs-rfc8785/1", "fingerprint": "commit-fingerprint/1"})):
            with self.subTest(case=case):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.decision_receipt("dec_00000001", "inv_pppppppp", spec, receipt_overrides={"hash_contract": value})
                self.assertIn(refused, str(ctx.exception))
                self.assertEqual(self.snapshot("decision_receipts"), stored)
        self.decision_receipt("dec_00000001", "inv_pppppppp", spec, receipt_overrides={"hash_contract": {"canonicalization": "jcs-rfc8785/1"}})
        self.assertEqual(len(self.snapshot("decision_receipts")), 1)

    def test_frozen_versions_agree_across_ddl_schema_and_helper(self) -> None:
        """The DDL, the JSON schema and gen2/core/canonical.py name the same
        frozen versions (a bump in one place alone fails here)."""
        from gen2.core import canonical

        common = json.loads((STORE_DIR.parent / "schema" / "common.schema.json").read_text(encoding="utf-8"))["$defs"]
        self.assertEqual((canonical.CANONICALIZATION, canonical.FINGERPRINT_CONTRACT), ("jcs-rfc8785/1", "commit-fingerprint/1"))
        self.assertEqual({k: v["const"] for k, v in common["commit_hash_contract"]["properties"].items()}, self.FROZEN_COMMIT)
        self.assertEqual({k: v["const"] for k, v in common["logical_hash_contract"]["properties"].items()}, {"canonicalization": "jcs-rfc8785/1"})
        ddl = store_fixtures.DDL_TEXT
        self.assertIn("'$.hash_contract.canonicalization'), '') IN ('jcs-rfc8785/1')", ddl)
        self.assertIn("'$.hash_contract.fingerprint'), '') IN ('commit-fingerprint/1')", ddl)


if __name__ == "__main__":
    unittest.main()
