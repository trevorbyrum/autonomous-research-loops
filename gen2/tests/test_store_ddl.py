"""Constraint tests for the gen-2 store DDL draft (gen2/store/schema.sql).

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
from gen2.tests.store_fixtures import DROP, OTHER, STORE_DIR, TOPIC, StoreTestCase, T, connect, facet, h, obligation


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

    RECONCILE = ("INSERT INTO invocation_reconciliations (reconciliation_id, invocation_id, unknown_episode, unknown_since, resolution, method, evidence_ref, result_payload_digest, resolved_at) "
                 "VALUES (?, ?, ?, ?, ?, 'job_handle_lookup', ?, ?, ?)")

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
        ins = ("INSERT INTO invocation_reconciliations (reconciliation_id, invocation_id, unknown_episode, unknown_since, resolution, method, evidence_ref, descendants_confirmed_at, resolved_at) "
               "VALUES ('rec_00000001', 'inv_pppppppp', 1, ?, ?, ?, ?, ?, ?)")
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


class VerificationTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.lease("lease_vvvvvvvv", 2, scope="verification")
        self.invocation("inv_vvvvvvvv", kind="verification", lease="lease_vvvvvvvv")
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'text/plain', ?)", h("7"), T)
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000001', 'doi', '10.1/x', ?)", T)
        self.x("INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES ('clm_00000001', 1, ?, ?, 'inv_pppppppp', 1, 'full_text', 'provisional', ?)", TOPIC, h("7"), T)
        self.quote_check("qc-1")

    def second_research_pass(self) -> None:
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_aaaaaaaa'", T)
        self.lease("lease_bbbbbbbb", 3)
        self.invocation("inv_qqqqqqqq", lease="lease_bbbbbbbb")

    def test_producer_cannot_verify_itself(self) -> None:
        # Realistic case: the research-pass producer names itself as verifier (the role trigger fires first).
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", verifier="inv_pppppppp", extraction="inv_pppppppp")
        self.assertIn("separate verification invocation", str(ctx.exception))
        # Isolate the producer != verifier CHECK: a claim whose producer is itself a
        # verification-kind invocation passes the role trigger, so only the CHECK can refuse it.
        self.x("INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES ('clm_00000001', 2, ?, ?, 'inv_vvvvvvvv', 0, NULL, 'provisional', ?)", TOPIC, h("7"), T)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000002", claim=("clm_00000001", 2), quote=("not_applicable", None), producer="inv_vvvvvvvv", use="sampled")  # not load-bearing: sampled
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.verify("ver_00000001")

    def test_verifier_must_be_separate_verification_invocation(self) -> None:
        """D26 rewrite (ruling R2.2): keep the kind rule; replace blanket parent
        rejection with the control/causal distinction. A verifier can never have
        a controlling parent (so the producer cannot launch or control it); a
        verifier *requested by* the producing pass is legitimate."""
        self.second_research_pass()  # a second research_pass, not a verifier
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", verifier="inv_qqqqqqqq", extraction="inv_qqqqqqqq")
        self.assertIn("separate verification invocation", str(ctx.exception))
        # control parentage: refused when the verification invocation is admitted
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_vvvvvvvv'", T)
        self.lease("lease_wwwwwwww", 4, scope="verification")
        self.rejects("CHECK constraint failed", *self.raw_invocation(invocation_id="inv_childver", kind="verification", lease_id="lease_wwwwwwww", parent_invocation_id="inv_pppppppp"))
        # causal request by the producer: admitted, and its receipt is accepted
        self.invocation("inv_reqdver1", kind="verification", lease="lease_wwwwwwww", requested_by="inv_pppppppp")
        self.verify("ver_00000002", verifier="inv_reqdver1", extraction="inv_reqdver1")

    def test_requested_by_is_same_topic_and_never_self(self) -> None:
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_vvvvvvvv'", T)
        self.lease("lease_wwwwwwww", 4, scope="verification")
        self.rejects("same topic", *self.raw_invocation(invocation_id="inv_reqdver1", kind="verification", lease_id="lease_wwwwwwww", requested_by_invocation_id="inv_oooooooo"))
        self.rejects("same topic", *self.raw_invocation(invocation_id="inv_reqdver1", kind="verification", lease_id="lease_wwwwwwww", requested_by_invocation_id="inv_reqdver1"))
        self.invocation("inv_reqdver1", kind="verification", lease="lease_wwwwwwww", requested_by="inv_pppppppp")

    def test_receipt_must_name_the_claims_real_producer(self) -> None:
        self.second_research_pass()
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", producer="inv_qqqqqqqq")
        self.assertIn("independent of the claim producer", str(ctx.exception))

    def test_producer_unvalidated_extraction_rejected(self) -> None:
        """D28 rewrite (A6/B6): the prohibited thing is the producer's selected or
        unvalidated extraction — not authenticated canonical bytes the producer
        acquired. Negatives: an unvalidated producer extraction (as a
        'validated' one without its validation, or passed off as the verifier's
        own); canonical bytes without an authenticated acquisition or not a
        staged artifact. Positives: canonical-byte reuse of producer-acquired
        bytes; a validated producer extraction."""
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", method="validated_extraction", extraction="inv_pppppppp", validation=None)
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", method="verifier_extraction", extraction="inv_pppppppp")
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", method="canonical_bytes", extraction="inv_pppppppp", gateway=None)
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", method="canonical_bytes", extraction="inv_pppppppp", obtained=h("0"))
        self.assertIn("authenticated canonical bytes", str(ctx.exception))
        self.verify("ver_00000001", method="canonical_bytes", extraction="inv_pppppppp")  # producer-acquired canonical bytes
        self.verify("ver_00000002", method="validated_extraction", extraction="inv_pppppppp", validation="validation-7")

    def test_supports_cannot_exceed_obtained_tier(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", tier="abstract", required="full_text")
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.verify("ver_00000001", tier="abstract", required="full_text", verdict="cannot_assess_at_required_tier")

    ACCEPT = "UPDATE claims SET status = 'accepted_support' WHERE claim_id = 'clm_00000001' AND revision = 1"
    PROMOTION_REFUSED = "needs a supporting load-bearing-use verification receipt"

    def claim_status(self) -> list[tuple]:
        return self.rows("SELECT status FROM claims WHERE claim_id = 'clm_00000001' AND revision = 1")

    def test_accepted_support_needs_receipt_at_required_tier(self) -> None:
        self.rejects(self.PROMOTION_REFUSED, self.ACCEPT)  # no receipt at all
        self.verify("ver_00000001", use="sampled", tier="abstract", required="abstract")  # supports, but a sample, and only at abstract
        self.rejects(self.PROMOTION_REFUSED, self.ACCEPT)
        self.verify("ver_00000002", tier="full_text", required="full_text")
        self.x(self.ACCEPT)

    def test_sampling_never_qualifies_a_load_bearing_claim(self) -> None:
        """RA5. The review's probe: on the load-bearing, full-text claim, a
        full-text 'supports' receipt with use='sampled', all four substantive
        checks not_checked, a matched quote and an adjudication record. It is a
        truthful sampling receipt and is stored as one, but promotion reads the
        claim's own designation and refuses it. So is a *successful* sampling
        receipt (every check performed and passed): sampling is not
        load-bearing qualification. A load-bearing partial support does not
        qualify either. Only a load-bearing-use 'supports' receipt with every
        check performed promotes; the claim reads back provisional after each
        refusal."""
        unperformed = {name: "not_checked" for name in self.CHECKS_OK}
        adjudicated = {"adjudication_ref": "adj-1", "resolved_at": T, "resolution": "sampled; not re-checked"}
        self.verify("ver_sample01", use="sampled", checks=unperformed, adjudication=adjudicated)
        self.rejects(self.PROMOTION_REFUSED, self.ACCEPT)
        self.verify("ver_sample02", use="sampled")  # successful sampling
        self.rejects(self.PROMOTION_REFUSED, self.ACCEPT)
        self.verify("ver_partial1", verdict="partially_supports")  # load-bearing use, checks performed, not support
        self.rejects(self.PROMOTION_REFUSED, self.ACCEPT)
        self.assertEqual(self.claim_status(), [("provisional",)])
        self.verify("ver_lb000001")  # genuine load-bearing qualification
        self.x(self.ACCEPT)
        self.assertEqual(self.claim_status(), [("accepted_support",)])

    def test_load_bearing_receipt_states_its_claims_designation(self) -> None:
        """RA5: a receipt requested for load-bearing use must be about a
        load-bearing claim at that claim's own required tier — it cannot
        re-describe the subject it certifies. A sampled receipt may audit any
        claim at any tier. (clm_00000002 is not load-bearing but does carry a
        full-text tier, so the load-bearing conjunct alone refuses it.)"""
        self.x("INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES ('clm_00000002', 1, ?, ?, 'inv_pppppppp', 0, 'full_text', 'provisional', ?)", TOPIC, h("7"), T)
        self.quote_check("qc-2", claim=("clm_00000002", 1))
        refused = "that claim's own required tier"
        for label, kw in (("a higher required tier than the claim's", dict(tier="reproduced", required="reproduced")),
                          ("a lower required tier than the claim's", dict(tier="abstract", required="abstract")),
                          ("a claim that is not load-bearing", dict(claim=("clm_00000002", 1), quote=("matched", "qc-2")))):
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.verify("ver_00000001", **kw)
                self.assertIn(refused, str(ctx.exception))
        self.assertEqual(self.rows("SELECT count(*) FROM verification_receipts"), [(0,)])
        self.verify("ver_00000001", use="sampled", tier="abstract", required="abstract")
        self.verify("ver_00000002", use="sampled", claim=("clm_00000002", 1), quote=("matched", "qc-2"))
        self.verify("ver_00000003")  # the claim's own designation

    def test_claims_start_provisional(self) -> None:
        self.rejects("claims are captured provisional", "INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES ('clm_00000002', 1, ?, ?, 'inv_pppppppp', 0, NULL, 'accepted_support', ?)", TOPIC, h("7"), T)

    def test_nli_alarm_quarantines_the_quote(self) -> None:
        """D32 + the byte-mismatch test the review found missing: an NLI alarm
        and an exact-byte mismatch each quarantine the quote."""
        insert = "INSERT INTO quote_checks (check_id, claim_id, claim_revision, source_artifact_hash, span_start, span_end, normalization_version, exact_match, nli_checker, nli_checker_version, nli_signal, quote_quarantined, checked_at) VALUES (?, 'clm_00000001', 1, ?, 0, 5, 'n1', ?, 'minicheck', '1', ?, ?, ?)"
        self.rejects("CHECK constraint failed", insert, "qc-2", h("7"), "matched", "alarm", 0, T)
        self.x(insert, "qc-2", h("7"), "matched", "alarm", 1, T)
        self.rejects("CHECK constraint failed", insert, "qc-3", h("7"), "mismatch", "pass", 0, T)
        self.x(insert, "qc-3", h("7"), "mismatch", "pass", 1, T)

    def test_support_needs_successful_checks_or_adjudication(self) -> None:
        """A6: 'supports' with an adverse or unperformed check, or a tier-0 alarm,
        is refused unless an explicit adjudication resolves it; a mismatched
        quote can never support."""
        adjudicated = {"adjudication_ref": "adj-1", "resolved_at": T, "resolution": "operator ruled the qualification immaterial"}
        n = 0
        for name in ("numeric_units", "denominators", "negation", "qualifications"):
            for status in ("checked_problem", "not_checked", "unavailable"):
                with self.subTest(check=name, status=status):
                    n += 1
                    checks = dict(self.CHECKS_OK, **{name: status})
                    with self.assertRaises(sqlite3.IntegrityError) as ctx:
                        self.verify(f"ver_{n:08d}", checks=checks)
                    self.assertIn("CHECK constraint failed", str(ctx.exception))
                    if status == "checked_problem":
                        self.verify(f"ver_{n:08d}", checks=checks, adjudication=adjudicated)
        self.quote_check("qc-alarm", nli="alarm")
        with self.assertRaises(sqlite3.IntegrityError):
            self.verify("ver_alarm001", tier0="alarm")
        self.verify("ver_alarm001", tier0="alarm", adjudication=adjudicated)
        self.quote_check("qc-mism", match="mismatch")
        with self.assertRaises(sqlite3.IntegrityError):  # the quarantine binding refuses it; the CHECK is a second layer
            self.verify("ver_mismatch", quote=("mismatch", "qc-mism"), adjudication=adjudicated)

    def test_absent_keys_are_not_passes(self) -> None:
        """SQLite passes a CHECK that evaluates to NULL, so an absent JSON key must
        fail closed: 'supports' with an adverse check and NO adjudication key, or
        with no exact-quote status, is refused like an explicit null."""
        with self.assertRaises(sqlite3.IntegrityError):
            self.verify("ver_00000001", checks=dict(self.CHECKS_OK, numeric_units="checked_problem"), drop=("adjudication",))
        with self.assertRaises(sqlite3.IntegrityError):
            self.verify("ver_00000002", quote=("not_applicable", None), drop=("checks.exact_quote.status",))
        self.verify("ver_00000001", drop=("adjudication",))  # all checks succeeded: the absent adjudication is not needed

    def test_truthful_unsuccessful_verdicts_may_record_unperformed_checks(self) -> None:
        """A6 (the over-restriction): a load-bearing cannot_assess or
        does_not_support receipt may truthfully report not_checked/unavailable;
        a load-bearing partial-support verdict may not."""
        unperformed = {"numeric_units": "not_checked", "denominators": "unavailable", "negation": "not_checked", "qualifications": "unavailable"}
        self.verify("ver_00000001", tier="abstract", verdict="cannot_assess_at_required_tier", checks=unperformed, quote=("not_applicable", None))
        self.verify("ver_00000002", verdict="does_not_support", checks=unperformed)
        with self.assertRaises(sqlite3.IntegrityError):
            self.verify("ver_00000003", verdict="partially_supports", checks=unperformed)
        self.verify("ver_00000004", verdict="partially_supports", checks=dict(self.CHECKS_OK, numeric_units="checked_problem"))

    def test_quote_check_binding(self) -> None:
        """A6/A10: the receipt's quote check is of this claim revision, against the
        receipt's source artifact, with the receipt's match status; support never
        rests on a quarantined quote without adjudication."""
        self.x("INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES ('clm_00000001', 2, ?, ?, 'inv_pppppppp', 1, 'full_text', 'provisional', ?)", TOPIC, h("7"), T)
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'text/plain', ?)", h("8"), T)
        self.quote_check("qc-rev2", claim=("clm_00000001", 2))
        self.quote_check("qc-src8", source=h("8"))
        self.quote_check("qc-mism", match="mismatch")
        self.quote_check("qc-alarm", nli="alarm")
        refused = "unquarantined quote check of this claim"
        for label, kw in (("other claim revision", dict(quote=("matched", "qc-rev2"))),
                          ("other source artifact", dict(quote=("matched", "qc-src8"))),
                          ("status disagrees", dict(verdict="does_not_support", quote=("matched", "qc-mism"))),
                          ("quarantined by alarm", dict(quote=("matched", "qc-alarm")))):
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.verify("ver_00000001", **kw)
                self.assertIn(refused, str(ctx.exception))
        self.verify("ver_00000001", quote=("matched", "qc-alarm"), adjudication={"adjudication_ref": "adj-1", "resolved_at": T, "resolution": "entailment confirmed on re-read"})
        self.verify("ver_00000002", verdict="does_not_support", quote=("mismatch", "qc-mism"))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000003", quote=("matched", None))  # a matched quote names its check
        self.assertIn("CHECK constraint failed", str(ctx.exception))

    def test_receipt_row_matches_its_json(self) -> None:
        """A10: every normalized column equals its field in the immutable receipt
        JSON. Each probe keeps the columns valid (so the role, quote and
        capability triggers pass) and changes only the JSON field, so only the
        binding CHECK can refuse it — including the review's probe (JSON
        does_not_support while the column says supports)."""
        spans = [{"start": 0, "end": 9, "locator": {"kind": "page", "value": "3"}}]
        acq = {"route": "gateway:other", "retrieved_at": T, "gateway_call_ref": "gw-call-1", "cache_reuse": False}
        ext = {"method": "verifier_extraction", "extractor": "x-1", "produced_by_invocation_id": "inv_other000", "validation_ref": None}
        probes = {
            "verification_receipt_id": "ver_other000", "topic_id": OTHER,
            "claim": {"claim_id": "clm_other000", "claim_revision": 1}, "claim.revision": {"claim_id": "clm_00000001", "claim_revision": 2},
            "source": {"work_id": "wrk_other000", "source_version": "v1"}, "source.version": {"work_id": "wrk_00000001", "source_version": "v2"},
            "cited_spans": spans, "obtained_content_hash": h("0"), "access_tier": "reproduced",
            "requested_for": {"use": "sampled", "required_access_tier": "full_text"}, "requested_for.tier": {"use": "load_bearing", "required_access_tier": "abstract"},
            "acquisition": acq, "extraction": ext, "extraction.method": dict(ext, method="canonical_bytes", produced_by_invocation_id="inv_vvvvvvvv"),
            "extraction.validation_ref": dict(ext, produced_by_invocation_id="inv_vvvvvvvv", validation_ref="v-1"),
            "producer_invocation_id": "inv_other000", "verifier_invocation_id": "inv_other000", "quote_check_id": "qc-other", "verdict": "does_not_support",
        }
        for label, value in probes.items():
            with self.subTest(field=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.verify("ver_00000001", receipt_overrides={label.split(".")[0]: value})
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.verify("ver_00000001")

    def test_receipt_names_the_verifiers_own_capability(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.verify("ver_00000001", capability="cap_pppppppp")
        self.assertIn("verifier capability", str(ctx.exception))
        self.verify("ver_00000001")


class ObservationTest(StoreTestCase):
    INSERT = ("INSERT INTO search_observations (observation_id, invocation_id, topic_id, request_identity, attempt, lane, request, obligation_ids, started_at, coverage_state, result_count, error_class, capability_fact_id, policy_version, completeness) "
              "VALUES (?, 'inv_pppppppp', ?, ?, 1, 'crossref', '{}', '[]', ?, ?, ?, ?, ?, 'pol1', ?)")

    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")

    def obs(self, oid: str, state: str, count, error=None, fact=None, ident: str = "1", completeness: str | None = None) -> None:
        if completeness is None:
            completeness = "complete" if state in ("searched_ok", "searched_empty", "metadata_only") else "unobserved"
        self.x(self.INSERT, oid, TOPIC, h(ident), T, state, count, error, fact, completeness)

    def test_degraded_search_cannot_report_zero(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "provider_unavailable", 0, "provider_outage")
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "provider_unavailable", None, None)  # degraded needs an error class
        self.obs("o1", "provider_unavailable", None, "payload_invalid")
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o2", "unknown", 0, "telemetry_missing", ident="2")
        self.obs("o2", "unknown", None, "telemetry_missing", ident="2")

    def test_searched_empty_is_exactly_zero_and_searched_ok_has_results(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "searched_empty", None)
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "searched_ok", 0)
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "searched_ok", None)
        self.obs("o1", "searched_empty", 0)
        self.obs("o2", "searched_ok", 3, ident="2")

    def test_secrets_failure_is_a_dated_capability_fact(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "auth_failed", None, "secrets_backend_failing")
        self.x("INSERT INTO capability_facts (fact_id, capability, state, detail, since, affected_lanes, recorded_at) VALUES ('cf-1', 'secrets_backend', 'failing', 'vault 403', '2026-09-21T19:47:00Z', '[\"semantic_scholar\"]', ?)", T)
        self.obs("o1", "auth_failed", None, "secrets_backend_failing", "cf-1")

    def test_one_current_capability_fact_supersede_to_transition(self) -> None:
        ins = "INSERT INTO capability_facts (fact_id, capability, state, detail, since, affected_lanes, recorded_at) VALUES (?, ?, ?, 'd', ?, '[]', ?)"
        current = "SELECT fact_id, state FROM capability_facts WHERE capability = 'secrets_backend' AND superseded_by_fact_id IS NULL"
        self.x(ins, "cf-1", "secrets_backend", "failing", T, T)
        self.rejects("UNIQUE constraint failed", ins, "cf-2", "secrets_backend", "healthy", T, T)  # a second current fact
        # A9: the documented supersession transaction, failure -> healthy, same capability
        self.x("BEGIN")
        self.x("UPDATE capability_facts SET superseded_by_fact_id = 'cf-2' WHERE fact_id = 'cf-1'")
        self.x(ins, "cf-2", "secrets_backend", "healthy", T, T)
        self.x("COMMIT")
        self.assertEqual(self.rows(current), [("cf-2", "healthy")])
        self.assertEqual(self.rows("SELECT state, superseded_by_fact_id FROM capability_facts WHERE fact_id = 'cf-1'"), [("failing", "cf-2")])  # retained
        self.rejects("supersede, never edit", "UPDATE capability_facts SET state = 'healthy' WHERE fact_id = 'cf-1'")
        self.rejects("supersede, never edit", "UPDATE capability_facts SET recorded_at = '2026-09-26T00:00:00Z' WHERE fact_id = 'cf-2'")
        # linking a successor that is never inserted fails at COMMIT; rollback leaves cf-2 current
        self.x("BEGIN")
        self.x("UPDATE capability_facts SET superseded_by_fact_id = 'cf-3' WHERE fact_id = 'cf-2'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.x("COMMIT")
        self.x("ROLLBACK")
        self.assertEqual(self.rows(current), [("cf-2", "healthy")])
        # cross-capability successor, in either order
        self.x("BEGIN")
        self.x("UPDATE capability_facts SET superseded_by_fact_id = 'cf-x' WHERE fact_id = 'cf-2'")
        self.rejects("same capability", ins, "cf-x", "gateway_budget", "failing", T, T)
        self.x("ROLLBACK")
        self.x(ins, "cf-y", "gateway_budget", "failing", T, T)
        self.rejects("same capability", "UPDATE capability_facts SET superseded_by_fact_id = 'cf-y' WHERE fact_id = 'cf-2'")
        # self and cyclic supersession; inserting an already-superseded fact
        self.rejects("CHECK constraint failed", "UPDATE capability_facts SET superseded_by_fact_id = 'cf-2' WHERE fact_id = 'cf-2'")
        self.rejects("must be current", "UPDATE capability_facts SET superseded_by_fact_id = 'cf-1' WHERE fact_id = 'cf-2'")
        self.rejects("inserted current", "INSERT INTO capability_facts (fact_id, capability, state, detail, since, affected_lanes, superseded_by_fact_id, recorded_at) VALUES ('cf-9', 'secrets_backend', 'failing', 'd', ?, '[]', 'cf-2', ?)", T, T)
        self.assertEqual(self.rows(current), [("cf-2", "healthy")])

    def test_observation_invocation_is_of_its_topic(self) -> None:
        """A10: search_observations binds its invocation's topic."""
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        self.rejects("invocation of its own topic", self.INSERT.replace("'inv_pppppppp'", "'inv_oooooooo'"), "o1", TOPIC, h("1"), T, "searched_ok", 3, None, None, "complete")
        self.x(self.INSERT.replace("'inv_pppppppp'", "'inv_oooooooo'"), "o1", OTHER, h("1"), T, "searched_ok", 3, None, None, "complete")

    def test_partial_results_are_kept_and_marked_incomplete(self) -> None:
        """A11 / RG-4: a partial result set keeps its observed records (count as a
        lower bound, retrieval events captured) and says why it is partial; it is
        never searched_empty, a degraded search never claims an observed result
        set, and a complete successful search carries no error."""
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "searched_ok", 5, completeness="partial")  # partial must say why
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "searched_empty", 0, "partial_pagination", completeness="partial")  # an empty page is not an empty search
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "provider_unavailable", None, "provider_outage", completeness="complete")
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "searched_ok", 5, completeness="unobserved")
        with self.assertRaises(sqlite3.IntegrityError):
            self.obs("o1", "searched_ok", 5, "timeout", completeness="complete")  # a complete result set has no error
        self.obs("o1", "searched_ok", 5, "partial_pagination", completeness="partial")
        self.x("INSERT INTO retrieval_events (event_id, observation_id, topic_id, provider_record_id, captured_at) VALUES ('e1', 'o1', ?, 'rec-1', ?)", TOPIC, T)
        self.assertEqual(self.rows("SELECT completeness, result_count, error_class FROM search_observations"), [("partial", 5, "partial_pagination")])

    def test_retrieval_events_only_from_successful_searches(self) -> None:
        self.obs("o1", "provider_unavailable", None, "timeout")
        self.obs("o2", "searched_ok", 2, ident="2")
        ins = "INSERT INTO retrieval_events (event_id, observation_id, topic_id, provider_record_id, captured_at) VALUES (?, ?, ?, 'rec-1', ?)"
        self.rejects("successful searches", ins, "e1", "o1", TOPIC, T)
        self.rejects("successful searches", ins, "e1", "o2", OTHER, T)
        self.x(ins, "e1", "o2", TOPIC, T)


class ScreeningAndDecisionTest(StoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition")
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000001', 'doi', '10.1/x', ?)", T)
        self.jev = self.spec()

    SCREEN = ("INSERT INTO screening_assessments (assessment_id, topic_id, work_id, contract_revision, eligibility_protocol_version, framing_version, stage, decision, reason_code, criterion_results, actor_kind, invocation_id, decision_receipt_id, recorded_by_operation_id, created_at) "
              "VALUES (?, ?, 'wrk_00000001', 1, 1, 1, 'abstract', ?, ?, '{}', ?, 'inv_pppppppp', ?, 'op_00000001', ?)")

    def test_exclusion_requires_reason_code(self) -> None:
        self.rejects("CHECK constraint failed", self.SCREEN, "sa1", TOPIC, "exclude", None, "primary", None, T)
        self.x(self.SCREEN, "sa1", TOPIC, "exclude", "EC-outcome-not-met", "primary", None, T)
        self.rejects("never deleted", "DELETE FROM screening_assessments WHERE assessment_id = 'sa1'")

    def test_shadow_decision_provider_cannot_write_authoritative_screening(self) -> None:
        # The A10 binding (the receipt's committed action must be this assessment)
        # now refuses a shadow receipt first; the qualified-authority trigger is
        # its second layer (tools/gen2_mutations.py SECOND_LAYER).
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev)  # shadow
        with self.assertRaises(sqlite3.IntegrityError):
            self.x(self.SCREEN, "sa1", TOPIC, "include", None, "decision_provider", "dec_00000001", T)
        self.decision_receipt("dec_00000002", "inv_pppppppp", self.jev, authority="qualified", qualification="qual-screen-1", action="commit_reversible_action", commit_op="op_00000001")
        self.x(self.SCREEN, "sa1", TOPIC, "include", None, "decision_provider", "dec_00000002", T)

    def test_provider_assessment_is_exactly_its_receipts_committed_action(self) -> None:
        """A10: class, topic, invocation, action, commit and subject of the
        qualified receipt all bind to the assessment; each probe is a qualified
        receipt differing in one of them."""
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000002', 'doi', '10.1/y', ?)", T)
        self.receipt("op_00000002", "inv_pppppppp", kind="interim_transition", before=1)
        pre = self.spec("dspec_prefil01", cls="relevance_prefilter")
        q = dict(authority="qualified", qualification="qual-screen-1")
        self.decision_receipt("dec_otherwrk", "inv_pppppppp", self.jev, action="commit_reversible_action", commit_op="op_00000001", subject=("work", "wrk_00000002"), **q)
        self.decision_receipt("dec_othercls", "inv_pppppppp", pre, action="commit_reversible_action", commit_op="op_00000001", cls="relevance_prefilter", **q)
        self.decision_receipt("dec_othercom", "inv_pppppppp", self.jev, action="commit_reversible_action", commit_op="op_00000002", **q)
        self.decision_receipt("dec_proposal", "inv_pppppppp", self.jev, action="attach_proposal", proposal="prop-1", **q)
        self.decision_receipt("dec_othersub", "inv_pppppppp", self.jev, action="commit_reversible_action", commit_op="op_00000001", subject=("claim", "wrk_00000001"), **q)
        for did in ("dec_otherwrk", "dec_othercls", "dec_othercom", "dec_proposal", "dec_othersub"):
            with self.subTest(receipt=did):
                self.rejects("screening assessment bindings", self.SCREEN, "sa1", TOPIC, "include", None, "decision_provider", did, T)
        # another invocation's receipt (a discovery pass of the same topic)
        self.lease("lease_dddddddd", 2, scope="discovery")
        self.invocation("inv_disc0001", kind="discovery", lease="lease_dddddddd")
        self.decision_receipt("dec_otherinv", "inv_disc0001", self.jev, action="commit_reversible_action", commit_op="op_00000001", **q)
        self.rejects("screening assessment bindings", self.SCREEN, "sa1", TOPIC, "include", None, "decision_provider", "dec_otherinv", T)
        self.decision_receipt("dec_00000002", "inv_pppppppp", self.jev, action="commit_reversible_action", commit_op="op_00000001", **q)
        self.x(self.SCREEN, "sa1", TOPIC, "include", None, "decision_provider", "dec_00000002", T)

    def test_assessment_operation_invocation_and_reversal_are_of_its_topic(self) -> None:
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        self.receipt("op_other001", "inv_oooooooo", lease="lease_zzzzzzzz", tid=OTHER, kind="interim_transition")
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000002', 'doi', '10.1/y', ?)", T)
        refused = "screening assessment bindings"
        self.rejects(refused, self.SCREEN.replace("'op_00000001'", "'op_other001'"), "sa1", TOPIC, "include", None, "primary", None, T)
        self.rejects(refused, self.SCREEN.replace("'inv_pppppppp'", "'inv_oooooooo'"), "sa1", TOPIC, "include", None, "primary", None, T)
        self.x(self.SCREEN, "sa1", TOPIC, "exclude", "EC-1", "primary", None, T)
        reverse = ("INSERT INTO screening_assessments (assessment_id, topic_id, work_id, contract_revision, eligibility_protocol_version, framing_version, stage, decision, reason_code, criterion_results, actor_kind, invocation_id, supersedes_assessment_id, recorded_by_operation_id, created_at) "
                   "VALUES (?, ?, ?, 1, 1, 1, 'abstract', 'include', NULL, '{}', 'primary', 'inv_pppppppp', 'sa1', 'op_00000001', ?)")
        self.rejects(refused, reverse, "sa2", TOPIC, "wrk_00000002", T)  # a reversal of another work's exclusion
        # a reversal of another topic's exclusion of the same work
        self.x("INSERT INTO screening_assessments (assessment_id, topic_id, work_id, contract_revision, eligibility_protocol_version, framing_version, stage, decision, reason_code, criterion_results, actor_kind, invocation_id, recorded_by_operation_id, created_at) "
               "VALUES ('sa-other', ?, 'wrk_00000001', 1, 1, 1, 'abstract', 'exclude', 'EC-1', '{}', 'primary', 'inv_oooooooo', 'op_other001', ?)", OTHER, T)
        self.rejects(refused, reverse.replace("'sa1'", "'sa-other'"), "sa2", TOPIC, "wrk_00000001", T)
        self.x(reverse, "sa2", TOPIC, "wrk_00000001", T)

    def test_fallback_label_cannot_carry_probability(self) -> None:
        fb = self.spec("dspec_screen02", provider="llm_fallback")
        label = {"primitive": "label", "selected_option_id": "include", "evidence_refs": ["r1"]}
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", fb, provider="llm_fallback", answer=dict(label, probability=0.9))
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", fb, provider="llm_fallback", answer=dict(label, primitive="choice", confidence=0.9))
        self.decision_receipt("dec_00000001", "inv_pppppppp", fb, provider="llm_fallback", answer=label)

    def test_missing_confidence_or_primitive_is_rejected_not_defaulted(self) -> None:
        """D41 (MODIFY per review): the Noul positive now runs under a Noul spec."""
        noul = self.spec("dspec_noul0001", primitive="noul", options=("yes", "no"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, answer={"primitive": "choice", "selected_option_id": "include", "distribution": {"include": 0.8, "exclude": 0.2}})
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, answer={"selected_option_id": "include", "confidence": 0.7})
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", noul, answer={"primitive": "noul", "probability": 0.8, "confidence": 0.9})
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", noul, answer={"primitive": "noul"})
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev)
        self.decision_receipt("dec_00000002", "inv_pppppppp", noul, answer={"primitive": "noul", "probability": 0.8})

    def test_unqualified_authority_is_capped(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, authority="qualified", action="attach_proposal", proposal="prop-1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, authority="advisory", action="commit_reversible_action", commit_op="op_00000001")
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, authority="shadow", action="attach_proposal", proposal="prop-1")
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, authority="advisory", action="attach_proposal", proposal="prop-1")

    def test_receipt_provider_must_match_spec(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, provider="llm_fallback", answer={"primitive": "label", "selected_option_id": "x", "evidence_refs": ["r"]})
        self.assertIn("must match its spec", str(ctx.exception))


class DecisionReceiptConsistencyTest(StoreTestCase):
    """A7 (and A10 for the receipt JSON): action/outcome shapes, raw response
    retention, spec binding by primitive/policy/options/protocol, spec shape."""

    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition")
        self.x("INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, deadline_at, clears_when, created_at) "
               "VALUES ('hold_00000001', ?, 'wrk_00000001', 'judgment', 'low confidence', 'needs_decision', 'primary', 'primary', ?, 'primary decides', ?)", TOPIC, T, T)
        self.jev = self.spec()

    def test_action_fixes_the_outcome_shape(self) -> None:
        q = dict(authority="qualified", qualification="qual-1")
        bad = {
            "shadow with a committed operation (the review's probe)": dict(commit_op="op_00000001"),
            "shadow with a hold": dict(hold="hold_00000001"),
            "shadow with a proposal": dict(proposal="prop-1"),
            "proposal without its ref": dict(action="attach_proposal", authority="advisory"),
            "proposal that also commits": dict(action="attach_proposal", proposal="prop-1", commit_op="op_00000001", **q),
            "commit that also proposes": dict(action="commit_reversible_action", commit_op="op_00000001", proposal="prop-1", **q),
            "commit that also holds": dict(action="commit_reversible_action", commit_op="op_00000001", hold="hold_00000001", **q),
            "escalation that commits": dict(action="escalate", commit_op="op_00000001", authority="advisory"),
            "escalation that proposes": dict(action="escalate", proposal="prop-1", authority="advisory"),
            "abstain-hold without its hold": dict(action="abstain_hold", authority="advisory"),
        }
        for label, kw in bad.items():
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, **kw)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.decision_receipt("dec_shadow01", "inv_pppppppp", self.jev)
        self.decision_receipt("dec_propos01", "inv_pppppppp", self.jev, action="attach_proposal", proposal="prop-1", authority="advisory")
        self.decision_receipt("dec_commit01", "inv_pppppppp", self.jev, action="commit_reversible_action", commit_op="op_00000001", **q)
        self.decision_receipt("dec_escal001", "inv_pppppppp", self.jev, action="escalate", hold="hold_00000001", authority="advisory")
        self.decision_receipt("dec_abstn001", "inv_pppppppp", self.jev, action="abstain_hold", hold="hold_00000001", authority="advisory", status="abstained", answer=None)

    def test_abstention_retains_the_raw_response(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, status="abstained", answer=None, raw=None, action="escalate", authority="advisory")
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError):
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, raw=None)  # an answer without its raw bytes
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, status="abstained", answer=None, action="escalate", authority="advisory", raw="0", stage_raw=False)
        self.assertIn("FOREIGN KEY constraint failed", str(ctx.exception))  # the digest must be a retained artifact
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, status="abstained", answer=None, action="escalate", authority="advisory")
        self.decision_receipt("dec_00000002", "inv_pppppppp", self.jev, status="timeout", answer=None, raw=None, action="escalate", authority="advisory")

    def test_receipt_matches_its_spec(self) -> None:
        refused = "must match its spec"
        noul = {"primitive": "noul", "probability": 0.6}
        cases = {
            "a Noul answer under a Choice spec (the review's D41 probe)": dict(answer=noul),
            "another action-policy id": dict(policy=("P2", 1)),
            "another action-policy version": dict(policy=("P1", 2)),
            "a selected option the spec does not offer": dict(answer={"primitive": "choice", "selected_option_id": "maybe", "distribution": {"include": 0.5, "exclude": 0.5}, "confidence": 0.5}),
            "a distribution over an option the spec does not offer": dict(answer={"primitive": "choice", "selected_option_id": "include", "distribution": {"include": 0.5, "maybe": 0.5}, "confidence": 0.5}),
        }
        for label, kw in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, **kw)
                self.assertIn(refused, str(ctx.exception))
        other = self.spec("dspec_otherpr1", protocol_topic=OTHER)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.decision_receipt("dec_00000001", "inv_pppppppp", other)  # a spec bound to another topic's protocol
        self.assertIn(refused, str(ctx.exception))
        # RA6: the spec id the receipt names must be the id of the spec its hash
        # selects — an unknown id, and the id of another stored spec, each with
        # the correct hash
        self.spec("dspec_screen02")
        for spec_id in ("dspec_wrong001", "dspec_screen02"):
            with self.subTest(spec_id=spec_id):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, receipt_overrides={"spec": {"spec_id": spec_id, "spec_hash": self.jev}})
                self.assertIn(refused, str(ctx.exception))
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev)

    def test_spec_shape_by_class_and_provider(self) -> None:
        cases = {
            "screening without an eligibility protocol (the review's probe)": dict(spec_id="dspec_bad00001", no_protocol=True),
            "method_selection without its contract protocol": dict(spec_id="dspec_bad00002", cls="method_selection", no_protocol=True),
            "a fallback that answers Choice": dict(spec_id="dspec_bad00003", provider="llm_fallback", primitive="choice"),
            "a Noul with three options": dict(spec_id="dspec_bad00004", primitive="noul", options=("yes", "no", "maybe")),
            "a single option": dict(spec_id="dspec_bad00005", options=("include",)),
            "options as a list (ids not unique by construction)": dict(spec_id="dspec_bad00006", document_overrides={"options": [{"option_id": "a"}, {"option_id": "a"}]}),
            "no options key at all (absent, not null)": dict(spec_id="dspec_bad00007", drop=("options",)),
            "screening whose protocol key is absent": dict(spec_id="dspec_bad00008", no_protocol=True, drop=("protocol",)),
        }
        for label, kw in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.spec(**kw)
                self.assertTrue("CHECK constraint failed" in str(ctx.exception) or "at least two options" in str(ctx.exception), str(ctx.exception))
        other_protocol = {"topic_id": OTHER, "contract": {"revision": 1, "content_hash": h("a")}, "eligibility_protocol_version": 1}
        for label, overrides in (("primitive", {"primitive": "score"}), ("policy id", {"action_policy": {"policy_id": "P2", "version": 1}}),
                                 ("policy version", {"action_policy": {"policy_id": "P1", "version": 2}}), ("protocol topic", {"protocol": other_protocol})):
            with self.subTest(json_field=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.spec("dspec_bad00009", document_overrides=overrides)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.spec("dspec_noul0001", primitive="noul", options=("yes", "no"))
        self.spec("dspec_meth0001", cls="method_selection", options=("design-a", "design-b", "design-c"))
        self.spec("dspec_fall0001", provider="llm_fallback", cls="intake_triage")

    def test_receipt_row_matches_its_json(self) -> None:
        """A10: each probe keeps the columns valid and changes only the JSON field."""
        doc_probes = {
            "decision_receipt_id": "dec_other000", "invocation_id": "inv_other000", "topic_id": OTHER, "spec": {"spec_id": "dspec_screen01", "spec_hash": h("0")},
            "decided_at": "2026-09-26T00:00:00Z",
            "decision_class": "method_selection", "provider": "llm_fallback", "subject": {"kind": "work", "ref": "wrk_other000"},
            "subject.kind": {"kind": "claim", "ref": "wrk_00000001"},
            "input_manifest": {"snapshot_digest": h("6"), "input_record_ids": [], "input_status": "stale"},
            "policy": {"policy_id": "P9", "version": 1}, "policy.version": {"policy_id": "P1", "version": 9},
            "authorization": {"authority_level": "advisory", "qualification_ref": None}, "authorization.qualification_ref": {"authority_level": "shadow", "qualification_ref": "q-x"},
            "action": "escalate", "outcome": {"commit_operation_id": "op_00000001", "proposal_ref": None, "hold_id": None},
            "outcome.proposal_ref": {"commit_operation_id": None, "proposal_ref": "p-x", "hold_id": None}, "outcome.hold_id": {"commit_operation_id": None, "proposal_ref": None, "hold_id": "hold_00000001"},
            "blind_sample": {"selected": True, "initial_disposition_ref": None},
        }
        base_response = {"status": "answered", "raw_response_digest": h("5"), "raw_response_artifact": {"content_hash": h("5"), "size_bytes": 10, "media_type": "application/json"},
                         "answer": {"primitive": "choice", "selected_option_id": "include", "distribution": {"include": 0.8, "exclude": 0.2}, "confidence": 0.7}}
        for key, value in (("status", "abstained"), ("raw_response_digest", h("4")), ("raw_response_artifact", {"content_hash": h("4"), "size_bytes": 10, "media_type": "application/json"}),
                           ("answer", {"primitive": "choice", "selected_option_id": "exclude", "distribution": {"include": 0.2, "exclude": 0.8}, "confidence": 0.7})):
            doc_probes[f"provider_response.{key}"] = dict(base_response, **{key: value})
        for label, value in doc_probes.items():
            with self.subTest(field=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev, receipt_overrides={label.split(".")[0]: value})
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.jev)


class HoldTest(StoreTestCase):
    INSERT = ("INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, deadline_at, clears_when, capability_fact_id, created_at) "
              "VALUES (?, ?, 'clm_00000001', ?, 'verifier disagreement', 'needs_decision', ?, ?, ?, ?, ?, ?)")

    def test_hold_needs_owner_deadline_and_clearing_condition(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.x(self.INSERT, "hold_00000001", TOPIC, "judgment", "primary", None, T, "adjudicated", None, T)
        with self.assertRaises(sqlite3.IntegrityError):
            self.x(self.INSERT, "hold_00000001", TOPIC, "judgment", "primary", "primary", None, "adjudicated", None, T)
        with self.assertRaises(sqlite3.IntegrityError):
            self.x(self.INSERT, "hold_00000001", TOPIC, "judgment", "primary", "primary", T, "", None, T)
        with self.assertRaises(sqlite3.IntegrityError):
            self.x(self.INSERT, "hold_00000001", TOPIC, "capability", "router", "router", T, "vault healthy", None, T)
        self.x(self.INSERT, "hold_00000001", TOPIC, "judgment", "primary", "primary", T, "adjudicated", None, T)

    def test_operator_hold_cleared_only_by_operator_decision(self) -> None:
        """D45 rewrite (A2): only an approved hold_clearance about THIS hold clears
        it. Each near-miss differs from the valid decision in one dimension:
        disposition, subject (another hold of the same topic), or kind (a
        publication approval whose free-text subject ref names this hold). A
        decision's topic is fixed by its hold subject when it is recorded
        (test_decision_subject_must_exist_with_its_topic)."""
        self.x(self.INSERT, "hold_00000001", TOPIC, "scope", "operator", "operator", T, "operator rules on reframe", None, T)
        self.x(self.INSERT, "hold_00000002", TOPIC, "scope", "operator", "operator", T, "another hold", None, T)
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition")
        clear = "UPDATE holds SET cleared_at = ?, cleared_by_decision_id = ? WHERE hold_id = 'hold_00000001'"
        self.rejects("CHECK constraint failed", "UPDATE holds SET cleared_at = ?, cleared_by_operation_id = 'op_00000001' WHERE hold_id = 'hold_00000001'", T)
        self.decision("opd_rejected", "hold_clearance", disposition="rejected", ref="hold_00000001")
        self.decision("opd_otherhld", "hold_clearance", ref="hold_00000002")
        self.decision("opd_wrongknd", "publication_approval", ref="hold_00000001", rev=1, hsh=h("5"))
        for did in ("opd_rejected", "opd_otherhld", "opd_wrongknd"):
            with self.subTest(decision=did):
                self.rejects("hold_clearance decision about this hold", clear, T, did)
        self.assertEqual(self.rows("SELECT cleared_at FROM holds WHERE hold_id = 'hold_00000001'"), [(None,)])
        self.decision("opd_00000001", "hold_clearance", ref="hold_00000001")
        self.rejects("hold_clearance decision about this hold", clear, T, "opd_rejected")  # a valid clearance exists, but is not the one named
        self.x(clear, T, "opd_00000001")
        self.rejects("a cleared hold is final", "UPDATE holds SET cleared_at = NULL, cleared_by_decision_id = NULL WHERE hold_id = 'hold_00000001'")

    def test_holds_are_created_open(self) -> None:
        self.rejects("created open", "INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, deadline_at, clears_when, created_at, cleared_at, cleared_by_operation_id) "
                     "VALUES ('hold_00000001', ?, 'x', 'judgment', 'c', 'needs_decision', 'primary', 'primary', ?, 'adjudicated', ?, ?, 'op_00000001')", TOPIC, T, T, T)

    def test_decision_subject_must_exist_with_its_topic(self) -> None:
        self.x(self.INSERT, "hold_00000001", TOPIC, "scope", "operator", "operator", T, "c", None, T)
        ins = "INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'trevor', ?)"
        self.rejects("existing subject", ins, "opd_x", TOPIC, "hold_clearance", "approved", "hold", "hold_nothere", None, None, T)
        self.rejects("existing subject", ins, "opd_x", OTHER, "hold_clearance", "approved", "hold", "hold_00000001", None, None, T)  # another topic's decision about this hold
        self.rejects("existing subject", ins, "opd_x", TOPIC, "blind_initial_disposition", "recorded", "decision_receipt", "dec_nothere", None, None, T)
        self.x(ins, "opd_x", TOPIC, "hold_clearance", "approved", "hold", "hold_00000001", None, None, T)
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.decision_receipt("dec_00000001", "inv_pppppppp", self.spec())
        self.x(ins, "opd_y", TOPIC, "blind_initial_disposition", "recorded", "decision_receipt", "dec_00000001", None, None, T)

    def test_decision_subject_shape(self) -> None:
        """A2: each decision kind admits one subject kind with its identifying fields."""
        ins = "INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at) VALUES ('opd_x', ?, ?, ?, ?, ?, ?, ?, 'trevor', ?)"
        ch = self.content_hash_of(TOPIC, 1)
        self.x(self.INSERT, "hold_00000001", TOPIC, "scope", "operator", "operator", T, "c", None, T)
        # (rows chosen so the subject-existence trigger, which fires first, passes)
        bad = (
            (TOPIC, "hold_clearance", "approved", "topic", TOPIC, 0, None),                 # kind admits only a hold subject
            (TOPIC, "retirement", "approved", "hold", "hold_00000001", None, None),         # and the reverse
            (TOPIC, "scope_approval", "approved", "scoping_report", "scope-1", None, ch),   # a versioned subject needs its revision
            (TOPIC, "contract_approval", "approved", "contract_revision", OTHER, 1, ch),     # contract subject is referenced by its own topic
            (TOPIC, "retirement", "approved", "topic", TOPIC, None, None),                  # topic subject needs the state revision decided against
            (None, "scope_approval", "approved", "scoping_report", "scope-1", 1, ch),       # only hold decisions may be topic-less
            (TOPIC, "retirement", "recorded", "topic", TOPIC, 0, None),                     # 'recorded' is only for blind/advised records
            (TOPIC, "publication_approval", "approved", "publication_source", "src-1", 1, None),  # a publication source needs its hash
        )
        for row in bad:
            with self.subTest(row=row):
                self.rejects("CHECK constraint failed", ins, *row, T)
        self.x(ins, TOPIC, "contract_approval", "approved", "contract_revision", TOPIC, 1, ch, T)


class ExportOutboxTest(StoreTestCase):
    """The one outbound path (task 0d, operator ruling 2026-09-26). An outbox
    event's manifest is the export manifest; receipts and watermarks are per
    connector, and no database product is named anywhere in the store. Each
    test says which publication-table rule it carries, or that it is new with
    the connector contract (docs/gen2/EXPORT-API.md). Oracle: hand-written
    near-misses, each differing from an accepted row in one dimension, beside
    the accepted row itself."""

    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.receipt("op_00000001", "inv_pppppppp", kind="interim_transition")

    def capability_fact(self) -> None:
        self.x("INSERT INTO capability_facts (fact_id, capability, state, detail, since, affected_lanes, recorded_at) "
               "VALUES ('cf-1', 'export.connector.warehouse', 'failing', 'connection refused', ?, '[]', ?)", T, T)

    def delivery(self, **row) -> None:
        """One export_delivery_receipts row: a delivered attempt of connector
        `warehouse` (sql) for man_00000001 unless `row` says otherwise."""
        full = {"export_receipt_id": "exr_00000001", "manifest_id": "man_00000001", "connector_id": "warehouse", "connector_type": "sql",
                "attempt": 1, "status": "delivered", "tombstones_acknowledged": 1, "reconciliation_required": 0, "error_class": None,
                "unknown_cause": None, "capability_fact_id": None, "attempted_at": T, "acked_at": T}
        full.update(row)
        self.x(f"INSERT INTO export_delivery_receipts ({', '.join(full)}) VALUES ({', '.join('?' * len(full))})", *full.values())

    def test_only_approved_work_is_exported(self) -> None:
        """D46 rewrite (A2), carried from the publication outbox unchanged: the
        approval must be an approved publication_approval of this topic about
        exactly the exported source revision and hash. Each near-miss matches
        the exported source in every dimension but one; the wrong-kind probe is
        the review's (an approved rating decision) with its subject
        revision/hash made to coincide with the source's."""
        src = h("5")
        rated = self.content_hash_of(TOPIC, 1)
        probes = (
            ("opd_rejected", dict(disposition="rejected", rev=3, hsh=src), 3, src),
            ("opd_wronghsh", dict(rev=3, hsh=h("4")), 3, src),
            ("opd_stalerev", dict(rev=2, hsh=src), 3, src),
            ("opd_othertop", dict(tid=OTHER, rev=3, hsh=src), 3, src),
        )
        for did, kwargs, rev, hsh in probes:
            self.decision(did, "publication_approval", **kwargs)
        self.decision("opd_rating01", "rating_approval", rev=1, hsh=rated)
        for did, rev, hsh in [(d, r, x) for d, _, r, x in probes] + [("opd_rating01", 1, rated)]:
            with self.subTest(decision=did):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000001", "man_00000001", 1, None, did, h("1"), source_rev=rev, source_hash=hsh)
                self.assertIn("unapproved work is never exported", str(ctx.exception))
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=src)
        with self.assertRaises(sqlite3.IntegrityError):  # a valid approval exists, but is not the one named
            self.outbox("obx_00000001", "man_00000001", 1, None, "opd_rejected", h("1"), source_rev=3, source_hash=src)
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), source_rev=3, source_hash=src)

    def test_manifest_json_matches_its_columns(self) -> None:
        """Carried, and extended to what export-manifest/2 adds: the ordering
        pair, the bundle identity, the connectors and the superseded pair are
        each bound to the stored manifest, one probe per column."""
        src = h("5")
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=src)
        for override in ({"source": {"revision": 3, "content_hash": h("4")}}, {"source": {"revision": 2, "content_hash": src}},
                         {"approval": {"operator_decision_id": "opd_other", "approved_revision": 3}},
                         {"approval": {"operator_decision_id": "opd_00000002", "approved_revision": 2}}, {"artifact_kind": "evidence_correction"},
                         {"generation": 2}, {"options_revision": 2},
                         {"bundle": {"bundle_id": "exb_00000001", "bundle_version": "export-bundle/1", "content_hash": h("0")}},
                         {"expected_connectors": {"warehouse": {"connector_type": "sql"}}},
                         {"supersedes": {"manifest_id": "man_x", "generation": 1, "options_revision": None}},
                         {"supersedes": {"manifest_id": "man_x", "generation": None, "options_revision": 1}}):
            with self.subTest(override=override):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), source_rev=3, source_hash=src, manifest_overrides=override)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), source_rev=3, source_hash=src)

    def test_ordering_pairs_strictly_increase(self) -> None:
        """Carries test_generations_strictly_increase to the pair
        (generation, options_revision): a lower generation is refused however
        high its options revision, and so is a lower options revision of the
        same generation that is not a duplicate; a higher generation needs no
        higher options revision."""
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=h("5"))
        self.outbox("obx_00000001", "man_00000001", 2, 1, "opd_00000002", h("1"))
        self.outbox("obx_00000002", "man_00000002", 2, 2, "opd_00000002", h("2"), options=3, sup_options=1)
        for name, gen, opt, sup in (("a lower generation with a higher options revision", 1, 5, None),
                                    ("a lower options revision of the same generation", 2, 2, 1)):
            with self.subTest(probe=name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000003", "man_00000003", gen, sup, "opd_00000002", h("3"), options=opt)
                self.assertIn("strictly increase", str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError):  # the same pair again
            self.outbox("obx_00000003", "man_00000003", 2, 2, "opd_00000002", h("3"), options=3, sup_options=1)
        self.outbox("obx_00000003", "man_00000003", 3, 2, "opd_00000002", h("3"), options=1, sup_options=3)

    def test_one_generation_is_one_approved_revision(self) -> None:
        """New with the ordering pair: a re-export of generation 2 under a
        later options revision keeps the generation's approval and kind. The
        source revision/hash differ only together with the approval (an
        approval names exactly one revision and hash), so they are one probe;
        a second approval of the same revision and a different kind are each
        their own."""
        src = h("5")
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=src)
        self.decision("opd_reapprov", "publication_approval", rev=3, hsh=src)
        self.decision("opd_rev4appr", "publication_approval", rev=4, hsh=h("4"))
        self.outbox("obx_00000001", "man_00000001", 2, None, "opd_00000002", h("1"), source_rev=3, source_hash=src)
        for name, decision, rev, hsh, kind in (("another approved revision", "opd_rev4appr", 4, h("4"), "completion_publication"),
                                               ("another approval of the same revision", "opd_reapprov", 3, src, "completion_publication"),
                                               ("another artifact kind", "opd_00000002", 3, src, "evidence_correction")):
            with self.subTest(probe=name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000002", "man_00000002", 2, 2, decision, h("2"), options=2, source_rev=rev, source_hash=hsh, kind=kind)
                self.assertIn("one generation is one approved revision", str(ctx.exception))
        self.outbox("obx_00000002", "man_00000002", 2, 2, "opd_00000002", h("2"), options=2, source_rev=3, source_hash=src)
        self.outbox("obx_00000003", "man_00000003", 3, 2, "opd_rev4appr", h("3"), options=1, sup_options=2, source_rev=4, source_hash=h("4"))

    def test_supersession_names_a_lower_pair(self) -> None:
        """Carries the publication CHECKs (a superseded generation is lower;
        generation 1 supersedes no earlier generation) to pairs: the superseded
        pair is complete, at least (1, 1), and strictly lower. Generation 1 may
        supersede its own lower options revision."""
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=h("5"))
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"))
        for name, gen, opt, sgen, sopt in (("a later generation", 2, 1, 3, 1), ("the same pair", 2, 2, 2, 2),
                                           ("a higher options revision of the same generation", 2, 2, 2, 3),
                                           ("generation 0", 2, 1, 0, 1), ("options revision 0", 2, 1, 1, 0),
                                           ("a generation without its options revision", 2, 1, 1, None)):
            with self.subTest(probe=name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000002", "man_00000002", gen, sgen, "opd_00000002", h("2"), options=opt, sup_options=sopt)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.outbox("obx_00000002", "man_00000002", 1, 1, "opd_00000002", h("2"), options=2, sup_options=1)
        self.outbox("obx_00000003", "man_00000003", 2, 1, "opd_00000002", h("3"), options=1, sup_options=5)

    def test_manifest_names_only_declared_connector_types(self) -> None:
        """New (the store's side of the undeclared-connector-type negative that
        replaces the named-store-as-sink negative): every connector a manifest names is an
        object of a declared type, and the connectors are a non-empty object —
        the retired publication shape, an array of names, is refused even when
        its elements look like connectors."""
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=h("5"))
        for text in ('{"warehouse": {"connector_type": "graph_store"}}', '{"warehouse": "sql"}', '{"warehouse": {}}',
                     '{"warehouse": {"connector_type": "sql"}, "index": {"connector_type": "vector_store"}}'):
            with self.subTest(connectors=text):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), connectors_json=text)
                self.assertIn("declared type", str(ctx.exception))
        for text in ('[{"connector_type": "sql"}]', '{}'):
            with self.subTest(connectors=text):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), connectors_json=text)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"),
                    connectors_json='{"a": {"connector_type": "sql"}, "b": {"connector_type": "jsonl_file"}, "c": {"connector_type": "webhook"}, '
                                    '"d": {"connector_type": "extension", "implementation": {"module": "research_export_d.connector", "review_ref": "r"}}}')

    def test_delivery_receipt_only_for_named_connectors(self) -> None:
        """D48 rewrite, carried: membership, not vocabulary. The manifest names
        only `warehouse` (sql). A receipt for `archive` — a well-formed id of a
        declared type — is refused, and so is `warehouse` under another type;
        `warehouse` as sql is accepted."""
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=h("5"))
        self.capability_fact()
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), connectors={"warehouse": "sql"})
        for name, row in (("another connector", {"connector_id": "archive"}), ("the named connector as another type", {"connector_type": "jsonl_file"})):
            with self.subTest(probe=name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.delivery(**row)
                self.assertIn("does not name", str(ctx.exception))
        self.delivery(status="failed", tombstones_acknowledged=0, error_class="timeout", capability_fact_id="cf-1", acked_at=None)
        self.delivery(export_receipt_id="exr_00000002", attempt=2)

    def test_receipt_status_rules(self) -> None:
        """Carries the two publication CHECKs (a failure names its class; a
        delivery is acknowledged with its tombstones) and adds the receipt
        schema's other status rules, so the store cannot hold a receipt the
        contract refuses (P-7, H-2, A2). Each probe changes one field of a
        valid receipt of that status; the four valid receipts are accepted
        after them."""
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=h("5"))
        self.capability_fact()
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), connectors={"warehouse": "sql"})
        valid = {
            "delivered": {},
            "failed": {"status": "failed", "tombstones_acknowledged": 0, "error_class": "timeout", "capability_fact_id": "cf-1", "acked_at": None},
            "outcome_unknown": {"status": "outcome_unknown", "tombstones_acknowledged": 0, "reconciliation_required": 1,
                                "unknown_cause": "no_response_after_send", "capability_fact_id": "cf-1", "acked_at": None},
            "skipped_superseded": {"status": "skipped_superseded", "tombstones_acknowledged": 0, "acked_at": None},
        }
        probes = (
            ("a status the contract does not have (a queued request is not delivered)", "skipped_superseded", {"status": "queued"}),
            ("a failure without its class", "failed", {"error_class": None}),
            ("an error class on a delivery", "delivered", {"error_class": "timeout"}),
            ("an unreadable response as a failure class", "failed", {"error_class": "unreadable_response"}),
            ("a delivery without an acknowledgement time", "delivered", {"acked_at": None}),
            ("a delivery that did not acknowledge its tombstones", "delivered", {"tombstones_acknowledged": 0}),
            ("an acknowledgement time on a failure", "failed", {"acked_at": T}),
            ("tombstones acknowledged by a skipped delivery", "skipped_superseded", {"tombstones_acknowledged": 1}),
            ("an unknown outcome without its cause", "outcome_unknown", {"unknown_cause": None}),
            ("an unknown cause on a settled failure", "failed", {"unknown_cause": "unreadable_response"}),
            ("an unknown cause outside the vocabulary", "outcome_unknown", {"unknown_cause": "timeout"}),
            ("an unknown outcome not reconciled", "outcome_unknown", {"reconciliation_required": 0}),
            ("reconciliation left open on a settled result", "skipped_superseded", {"reconciliation_required": 1}),
            ("a failure without its capability fact", "failed", {"capability_fact_id": None}),
            ("an unknown outcome without its capability fact", "outcome_unknown", {"capability_fact_id": None}),
            ("a capability fact on a delivery", "delivered", {"capability_fact_id": "cf-1"}),
        )
        for name, status, change in probes:
            with self.subTest(probe=name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.delivery(**{**valid[status], **change})
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        for attempt, row in enumerate(valid.values(), start=1):
            self.delivery(export_receipt_id=f"exr_0000000{attempt}", attempt=attempt, **row)
        self.assertEqual(self.rows("SELECT count(*) FROM export_delivery_receipts"), [(4,)])

    def test_connector_watermark_never_regresses(self) -> None:
        """Carries test_sink_generation_never_regresses to the pair: an idempotent
        retry is accepted; a lower generation (whatever its options revision)
        and a lower options revision of the same generation are refused, and so
        are the regression paths that bypass an UPDATE guard (A1)."""
        self.x("INSERT INTO connector_watermarks VALUES (?, 'archive', 2, 3, ?)", TOPIC, T)
        self.x("UPDATE connector_watermarks SET generation = 2, options_revision = 3, delivered_at = ? WHERE topic_id = ? AND connector_id = 'archive'", T, TOPIC)
        for name, gen, opt in (("a lower generation with a higher options revision", 1, 9), ("a lower options revision of the same generation", 2, 2)):
            with self.subTest(probe=name):
                self.rejects("never regresses", "UPDATE connector_watermarks SET generation = ?, options_revision = ? WHERE topic_id = ? AND connector_id = 'archive'", gen, opt, TOPIC)
        for column, value in (("topic_id", OTHER), ("connector_id", "warehouse")):
            with self.subTest(identity=column):
                self.rejects("never regresses", f"UPDATE connector_watermarks SET {column} = ? WHERE topic_id = ? AND connector_id = 'archive'", value, TOPIC)
        self.rejects("connector watermark is never deleted", "DELETE FROM connector_watermarks WHERE topic_id = ? AND connector_id = 'archive'", TOPIC)
        self.rejects("connector watermark is never deleted", "INSERT OR REPLACE INTO connector_watermarks VALUES (?, 'archive', 1, 1, ?)", TOPIC, T)
        self.assertEqual(self.rows("SELECT generation, options_revision FROM connector_watermarks WHERE topic_id = ? AND connector_id = 'archive'", TOPIC), [(2, 3)])
        self.x("UPDATE connector_watermarks SET generation = 3, options_revision = 1 WHERE topic_id = ? AND connector_id = 'archive'", TOPIC)

    def test_connector_ids_are_well_formed(self) -> None:
        """Replaces the publication tables' closed product vocabulary: connector
        ids are open names, so the store holds them to the id shape instead
        (the schema's connector_id pattern) — in the watermark directly, and in
        a receipt even when its manifest names the malformed id."""
        bad = ("Warehouse", "cold_archive", "hook-", "a" * 65, "9warehouse")
        for cid in bad:
            with self.subTest(watermark=cid):
                self.rejects("CHECK constraint failed", "INSERT INTO connector_watermarks VALUES (?, ?, 1, 1, ?)", TOPIC, cid, T)
        self.decision("opd_00000002", "publication_approval", rev=3, hsh=h("5"))
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_00000002", h("1"), connectors={cid: "sql" for cid in bad})
        for attempt, cid in enumerate(bad, start=1):
            with self.subTest(receipt=cid):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.delivery(export_receipt_id=f"exr_bad0000{attempt}", connector_id=cid)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        for cid in ("s", "a" + "b" * 63, "cold-archive"):
            self.x("INSERT INTO connector_watermarks VALUES (?, ?, 1, 1, ?)", TOPIC, cid, T)


class ContractGovernanceTest(StoreTestCase):
    def test_contract_content_immutable_never_deleted(self) -> None:
        """D50 rewrite (A1/A2): every pin, REPLACE, creation as draft, and the
        approval subject. Approval near-misses differ in one dimension: kind (an
        approved rating decision about this very revision), disposition, or
        subject (another revision; a contract's revision, hash and topic are
        mutually determined because content hashes are unique and the decision's
        subject must exist when recorded)."""
        stored = self.snapshot("contract_revisions")
        for pin, value in (("protocol_revision", 2), ("framing_version", 2), ("content_hash", h("9")), ("parent_revision", 1),
                           ("document", '{"topic_id":"fleet-a:t1"}'), ("created_at", "2026-09-26T00:00:00Z"), ("revision", 7)):
            with self.subTest(pin=pin):
                self.rejects("contract revisions are immutable", f"UPDATE contract_revisions SET {pin} = ? WHERE topic_id = ? AND revision = 1", value, TOPIC)
        self.rejects("never deleted", "DELETE FROM contract_revisions WHERE topic_id = ? AND revision = 1", TOPIC)
        self.rejects("never deleted", "INSERT OR REPLACE INTO contract_revisions SELECT topic_id, revision, parent_revision, 2, framing_version, content_hash, json_set(document, '$.protocol_revision', 2), status, approved_by_decision_id, created_at FROM contract_revisions WHERE topic_id = ? AND revision = 1", TOPIC)
        self.assertEqual(self.snapshot("contract_revisions"), stored)
        approve = "UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = ? WHERE topic_id = ? AND revision = 1"
        self.contract(TOPIC, 2)
        self.decision("opd_ratingxx", "rating_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        self.decision("opd_rejected", "contract_approval", disposition="rejected", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        self.decision("opd_otherrev", "contract_approval", rev=2, hsh=self.content_hash_of(TOPIC, 2))
        self.decision("opd_othertop", "contract_approval", tid=OTHER, rev=1, hsh=self.content_hash_of(OTHER, 1))
        for did in ("opd_ratingxx", "opd_rejected", "opd_otherrev", "opd_othertop"):
            with self.subTest(decision=did):
                self.rejects("exact topic, revision and content hash", approve, did, TOPIC)
        self.rejects("existing subject", "INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at) VALUES ('opd_wronghsh', ?, 'contract_approval', 'approved', 'contract_revision', ?, 1, ?, 'trevor', ?)", TOPIC, TOPIC, h("0"), T)
        self.decision("opd_00000001", "contract_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        self.rejects("exact topic, revision and content hash", approve, "opd_rejected", TOPIC)  # a valid approval exists, but is not the one named
        self.x(approve, "opd_00000001", TOPIC)
        self.rejects("draft -> approved -> superseded", "UPDATE contract_revisions SET status = 'draft' WHERE topic_id = ? AND revision = 1", TOPIC)
        self.rejects("written as a draft", "INSERT INTO contract_revisions (topic_id, revision, parent_revision, protocol_revision, framing_version, content_hash, document, status, approved_by_decision_id, created_at) "
                     "SELECT topic_id, 3, 2, protocol_revision, framing_version, ?, json_set(json_set(document, '$.revision', 3), '$.content_hash', ?), 'approved', 'opd_00000001', created_at FROM contract_revisions WHERE topic_id = ? AND revision = 1", h("8"), h("8"), TOPIC)

    def test_hash_lock_binds_document_to_row(self) -> None:
        """G-1 / RA6: every identity field the contract document duplicates —
        topic, revision, parent (the lineage RA2 reads), created_at, content
        hash, protocol revision, framing version — equals its column."""
        base = {"topic_id": TOPIC, "revision": 2, "parent_revision": 1, "created_at": T, "content_hash": h("9"), "protocol_revision": 1, "facet_map": {"framing_version": 1}}
        ins = "INSERT INTO contract_revisions (topic_id, revision, parent_revision, protocol_revision, framing_version, content_hash, document, status, created_at) VALUES (?, 2, 1, 1, 1, ?, ?, 'draft', ?)"
        for key, value in (("topic_id", OTHER), ("revision", 3), ("parent_revision", None), ("created_at", "2026-09-26T00:00:00Z"), ("content_hash", h("0")),
                           ("protocol_revision", 2), ("facet_map", {"framing_version": 2})):
            with self.subTest(field=key):
                self.rejects("CHECK constraint failed", ins, TOPIC, h("9"), json.dumps(dict(base, **{key: value})), T)
        self.x(ins, TOPIC, h("9"), json.dumps(base), T)

    def test_parent_is_a_strictly_earlier_revision(self) -> None:
        """RA2-R: the stored parent relation is proper ancestry. Refused, each
        with its document agreeing with its row (so only the ancestry CHECK can
        refuse) and nothing written: a revision naming itself as parent (the
        review's probe shape), a two-revision cycle written by one multi-row
        INSERT (its foreign key is checked at statement end, when both rows
        exist), and a parent that exists but is a later revision. Accepted: a
        direct parent, an earlier non-adjacent one (a sibling draft's shape),
        and the first revision's NULL parent (setUp)."""
        refused = "CHECK constraint failed: contract_parent_is_earlier"
        stored = self.snapshot("contract_revisions")
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.contract(TOPIC, 2, parent=2)
        self.assertIn(refused, str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.contract_cycle(TOPIC, 2, 3)
        self.assertIn(refused, str(ctx.exception))
        self.assertEqual(self.snapshot("contract_revisions"), stored)
        self.contract(TOPIC, 2)  # direct parent 1
        self.contract(TOPIC, 5, parent=1)  # earlier, not adjacent
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.contract(TOPIC, 3, parent=5)  # an existing, later revision
        self.assertIn(refused, str(ctx.exception))
        self.contract(TOPIC, 3, parent=2)
        self.assertEqual(self.rows("SELECT revision, parent_revision FROM contract_revisions WHERE topic_id = ? ORDER BY revision", TOPIC),
                         [(1, None), (2, 1), (3, 2), (5, 1)])

    def test_one_approved_revision_per_topic(self) -> None:
        self.approve_contract(TOPIC, 1, "opd_00000001")
        self.contract(TOPIC, 2)
        self.decision("opd_00000002", "amendment_approval", rev=2, hsh=self.content_hash_of(TOPIC, 2))
        self.rejects("UNIQUE constraint failed", "UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = 'opd_00000002' WHERE topic_id = ? AND revision = 2", TOPIC)
        self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 1", TOPIC)
        self.x("UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = 'opd_00000002' WHERE topic_id = ? AND revision = 2", TOPIC)

    def test_approval_pointer_is_set_only_by_the_approval_transition(self) -> None:
        """RA3-R: a retained approving decision is evidence that its revision
        passed the draft -> approved transition, whose gate checks rows,
        ratings and coverage — so a dossier can rely on it. Draft 2 was rated;
        revision 3 carries the ratings with its rows (approvable); revision 4
        carries the same entries with its rows deliberately missing (the
        review's probe shape). Each has a valid contract_approval about its
        exact revision and hash. Refused, leaving every contract and dossier
        row unchanged: recording the decision while the revision stays a draft
        (the review's probe; on 3 and 4; also spelled as an upsert); the
        structural approval of 4; draft -> superseded with the decision (it
        would skip the approval gate) and without it — not an edge at all
        since ruling 1, so the status guard refuses it; approving 3 without
        naming its decision (the status CHECK); and a dossier under 3 or 4
        after each. Accepted: approving 3 with its
        decision in one update, then a dossier under it; after an amendment
        (revision 5) supersedes 3, revision 3 keeps its decision and a dossier
        under it is still accepted (historical pins)."""
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", h("7"), T)
        rated = dict(band="critical", score=8, decision="opd_rate0001")
        entries = dict(facets=(facet("F-1", **rated),), obligations=(obligation("O-1", ("F-1",), **rated),))
        draft = self.rate("opd_rate0001", **entries)
        self.contract_with_rows(TOPIC, draft + 1, **entries, content_hash=self.chash(TOPIC, draft + 1))
        self.contract(TOPIC, draft + 2, **entries, parent=draft, content_hash=self.chash(TOPIC, draft + 2))
        self.assertEqual((draft, draft + 1, draft + 2), (2, 3, 4))
        for rev in (3, 4):
            self.decision(f"opd_appr{rev:04d}", "contract_approval", rev=rev, hsh=self.chash(TOPIC, rev))
        pointer = "UPDATE contract_revisions SET approved_by_decision_id = ? WHERE topic_id = ? AND revision = ?"
        upsert = ("INSERT INTO contract_revisions SELECT topic_id, revision, parent_revision, protocol_revision, framing_version, content_hash, document, status, NULL, created_at "
                  "FROM contract_revisions WHERE topic_id = ? AND revision = ? ON CONFLICT (topic_id, revision) DO UPDATE SET approved_by_decision_id = ?")
        approve = "UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = ? WHERE topic_id = ? AND revision = ?"
        supersede = "UPDATE contract_revisions SET status = 'superseded', approved_by_decision_id = ? WHERE topic_id = ? AND revision = ?"
        only = "recorded only by the draft -> approved transition"
        no_dossier = "never a draft"

        def dossier_refused(rev: int) -> None:
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                self.dossier(9, rev, h("9"))
            self.assertIn(no_dossier, str(ctx.exception))

        stored = (self.snapshot("contract_revisions"), self.snapshot("dossiers"))
        for rev in (3, 4):
            with self.subTest(case="the decision recorded on a draft", revision=rev):
                self.rejects(only, pointer, f"opd_appr{rev:04d}", TOPIC, rev)
                self.rejects(only, upsert, TOPIC, rev, f"opd_appr{rev:04d}")
                dossier_refused(rev)
        with self.subTest(case="a failed structural approval"):
            self.rejects("approval needs complete obligation/facet rows", approve, "opd_appr0004", TOPIC, 4)
            dossier_refused(4)
        with self.subTest(case="draft -> superseded"):
            # Not an edge (ruling 1): the status guard refuses it. With a
            # decision named, the pointer guard refuses the same update too,
            # and which of the two SQLite fires first is trigger order, not
            # the invariant, so either is accepted. With none named, only the
            # status guard applies (triggers run before the CHECK).
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                self.x(supersede, "opd_appr0004", TOPIC, 4)
            self.assertTrue(any(f in str(ctx.exception) for f in (only, "draft -> approved -> superseded only")), str(ctx.exception))
            self.rejects("contract status moves draft -> approved -> superseded only",
                         "UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 4", TOPIC)
            dossier_refused(4)
        with self.subTest(case="approved without naming its decision"):
            # Revision 3 passes the approval gate (complete, rated, covered
            # rows), so the status CHECK is what refuses an approval that
            # records no decision.
            self.rejects("CHECK constraint failed: status = 'draft' OR approved_by_decision_id IS NOT NULL",
                         "UPDATE contract_revisions SET status = 'approved' WHERE topic_id = ? AND revision = 3", TOPIC)
            dossier_refused(3)
        self.assertEqual((self.snapshot("contract_revisions"), self.snapshot("dossiers")), stored)
        self.x(approve, "opd_appr0003", TOPIC, 3)
        self.dossier(1, 3, h("1"))
        self.contract_with_rows(TOPIC, 5, **entries, parent=3, content_hash=self.chash(TOPIC, 5))
        self.decision("opd_amend005", "amendment_approval", rev=5, hsh=self.chash(TOPIC, 5))
        self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 3", TOPIC)
        self.x(approve, "opd_amend005", TOPIC, 5)
        self.dossier(2, 3, h("2"))  # under the historically approved, now superseded revision
        self.dossier(3, 5, h("3"))
        self.assertEqual(self.rows("SELECT revision, status, approved_by_decision_id FROM contract_revisions WHERE topic_id = ? ORDER BY revision", TOPIC),
                         [(1, "draft", None), (2, "draft", None), (3, "superseded", "opd_appr0003"), (4, "draft", None), (5, "approved", "opd_amend005")])
        self.assertEqual(self.rows("SELECT dossier_revision, contract_revision FROM dossiers ORDER BY dossier_revision"), [(1, 3), (2, 3), (3, 5)])

    def test_operator_rating_band_and_score_consistent(self) -> None:
        """Each probe's document entry carries the same values as its row, so the
        rejection is the band/score CHECK, not the document binding."""
        bad = (obligation("O-bad1", band="critical", score=5, decision="opd_00000001"),  # rated so by the payload too: only the CHECK refuses
               obligation("O-bad2", band="critical", score=8),
               obligation("O-bad3", score=8))  # a score without a band
        good = (obligation("O-1", band="critical", score=8, decision="opd_00000001"),
                obligation("O-2", band="important", decision="opd_00000001"),
                obligation("O-3"))
        draft = self.rate("opd_00000001", facets=(facet("F-1"),), obligations=bad + good)
        self.contract(TOPIC, draft + 1, facets=(facet("F-1"),), obligations=bad + good)
        self.insert_facet(TOPIC, draft + 1, facet("F-1"))
        for entry in bad:
            with self.subTest(obligation=entry["obligation_id"]):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_obligation(TOPIC, draft + 1, entry)
                self.assertIn("CHECK constraint failed", str(ctx.exception))
        for entry in good:
            self.insert_obligation(TOPIC, draft + 1, entry)
        self.rejects("obligations are immutable", "UPDATE obligations SET operator_importance_band = 'limited' WHERE obligation_id = 'O-2'")

    def next_revision(self, tid: str = TOPIC) -> int:
        return self.rows("SELECT coalesce(max(revision), 0) + 1 FROM contract_revisions WHERE topic_id = ?", tid)[0][0]

    def rated_revision(self, parent: int, *, obligations: tuple = (), facets: tuple = (facet("F-1"), facet("F-2")), facet_rows: bool = True) -> int:
        """A revision of TOPIC, child of `parent`, whose document carries these
        entries (and, by default, its facet rows); the caller writes the row
        under test."""
        rev = self.next_revision()
        self.contract(TOPIC, rev, facets=facets, obligations=obligations, parent=parent, content_hash=self.chash(TOPIC, rev))
        for entry in facets if facet_rows else ():
            self.insert_facet(TOPIC, rev, entry)
        return rev

    RATED = dict(band="critical", score=8)
    PAYLOAD_O1 = {"facets": {}, "obligations": {"O-1": {"band": "critical", "score": 8}}}

    def test_operator_rating_bound_to_a_rating_decision(self) -> None:
        """A2 / RA2 for obligation ratings. The operator rated draft 2
        (obligations O-1, O-2, O-3; the decision's retained payload rates O-1
        critical/8 and O-3 important with no score, and leaves O-2 unrated). A rated row must cite an approved
        rating decision of this topic about an ANCESTOR draft defining the
        obligation exactly as here, whose payload gives exactly this band and
        score. Each probe revision descends from draft 2 (unless lineage is the
        probe) and its document entry names the probe's decision, so only the
        rating binding can refuse: disposition, kind, topic (another topic's
        identical draft 2), a decision about the revision carrying it (a
        self-hash cycle), the review's probe (a decision about the EMPTY draft 1
        invoked for an invented obligation, and for O-1), an obligation the
        operator did not rate, a changed band (with and without a score) or
        score, the same id redefined, an unrelated sibling draft. RA2-R on top:
        no stored history makes a revision its own ancestor — a revision naming
        itself as parent, or two revisions naming each other in one INSERT, with
        the entry citing an approved decision (payload matching) about that very
        revision — so the rated row never lands; the ancestry CHECK refuses the
        history, and were it stored the rating binding would have to (either
        reason is accepted). No row is written by any of
        them; then an unchanged rating carries forward over two revisions."""
        o1 = obligation("O-1", ("F-1",), **self.RATED, decision="opd_00000001")
        o2 = obligation("O-2", ("F-2",))
        o3 = obligation("O-3", ("F-2",), band="important", decision="opd_00000001")  # rated without a score
        draft = self.rate("opd_00000001", facets=(facet("F-1"), facet("F-2")), obligations=(o1, o2, o3))
        self.assertEqual(draft, 2)
        self.decision("opd_rejected", "rating_approval", disposition="rejected", rev=draft, hsh=self.chash(TOPIC, draft), payload=self.PAYLOAD_O1)
        self.decision("opd_approval", "contract_approval", rev=draft, hsh=self.chash(TOPIC, draft))
        self.assertEqual(self.rate("opd_othertop", OTHER, facets=(facet("F-1"), facet("F-2")), obligations=(o1, o2, o3), payload=self.PAYLOAD_O1), draft)
        self.decision("opd_emptydft", "rating_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))  # draft 1 carries no obligation
        refused = "an obligation rating is exactly what the operator rated"

        def probe(label: str, entry: dict, parent: int = draft) -> None:
            with self.subTest(case=label):
                rev = self.rated_revision(parent, obligations=(entry,))
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_obligation(TOPIC, rev, entry)
                self.assertIn(refused, str(ctx.exception))

        for did in ("opd_rejected", "opd_approval", "opd_othertop"):
            probe(did, obligation("O-1", ("F-1",), **self.RATED, decision=did))
        samerev = obligation("O-1", ("F-1",), **self.RATED, decision="opd_samerev")
        rev = self.rated_revision(draft, obligations=(samerev,))
        self.decision("opd_samerev", "rating_approval", rev=rev, hsh=self.chash(TOPIC, rev), payload=self.PAYLOAD_O1)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.insert_obligation(TOPIC, rev, samerev)
        self.assertIn(refused, str(ctx.exception))
        probe("the review's probe: an invented obligation under the empty draft's decision", obligation("O-new", ("F-1",), **self.RATED, decision="opd_emptydft"))
        probe("O-1 under the empty draft's decision", obligation("O-1", ("F-1",), **self.RATED, decision="opd_emptydft"))
        probe("an obligation the operator did not rate", obligation("O-2", ("F-2",), **self.RATED, decision="opd_00000001"))
        probe("a changed band and score", obligation("O-1", ("F-1",), band="important", decision="opd_00000001"))
        probe("a changed band alone (no score either way)", obligation("O-3", ("F-2",), band="limited", decision="opd_00000001"))
        probe("a changed score alone", obligation("O-1", ("F-1",), band="critical", score=9, decision="opd_00000001"))
        probe("the same id redefined", obligation("O-1", ("F-2",), **self.RATED, decision="opd_00000001"))
        probe("an unrelated (sibling) draft", o1, parent=1)
        for label, cyclic in (("a self-parent revision", False), ("a two-revision cycle", True)):
            with self.subTest(case=label):
                rev, did = self.next_revision(), f"opd_selfanc{int(cyclic)}"
                entry = obligation("O-1", ("F-1",), **self.RATED, decision=did)
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    if cyclic:
                        self.contract_cycle(TOPIC, rev, rev + 1, facets=(facet("F-1"), facet("F-2")), obligations=(entry,))
                    else:
                        self.contract(TOPIC, rev, facets=(facet("F-1"), facet("F-2")), obligations=(entry,), parent=rev, content_hash=self.chash(TOPIC, rev))
                    self.decision(did, "rating_approval", rev=rev, hsh=self.chash(TOPIC, rev), payload=self.PAYLOAD_O1)
                    for unrated in (facet("F-1"), facet("F-2")):
                        self.insert_facet(TOPIC, rev, unrated)
                    self.insert_obligation(TOPIC, rev, entry)
                self.assertTrue(any(f in str(ctx.exception) for f in ("contract_parent_is_earlier", refused)), str(ctx.exception))
                self.assertEqual(self.rows("SELECT count(*) FROM contract_revisions WHERE topic_id = ? AND revision >= ?", TOPIC, rev), [(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM obligations"), [(0,)])
        first = self.rated_revision(draft, obligations=(o1,))
        self.insert_obligation(TOPIC, first, o1)
        second = self.rated_revision(first, obligations=(o1,))
        self.insert_obligation(TOPIC, second, o1)
        self.assertEqual(self.rows("SELECT contract_revision, operator_importance_band, operator_importance_score FROM obligations ORDER BY contract_revision"),
                         [(first, "critical", 8), (second, "critical", 8)])

    def test_only_a_rating_decision_carries_a_rating_payload(self) -> None:
        """RA2: the retained payload is part of a rating decision (required), of
        no other kind, and rates only entries of the draft it is about, each
        with a band from the vocabulary."""
        ins = ("INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at, payload) "
               "VALUES ('opd_x', ?, ?, 'approved', 'contract_revision', ?, ?, ?, 'trevor', ?, ?)")
        draft = self.rate("opd_00000001", facets=(facet("F-1"),), obligations=(obligation("O-1", ("F-1",)),))
        ch = self.chash(TOPIC, draft)
        ok = json.dumps({"facets": {"F-1": {"band": "limited"}}, "obligations": {"O-1": {"band": "important", "score": 5}}})
        self.rejects("CHECK constraint failed", ins, TOPIC, "rating_approval", TOPIC, draft, ch, T, None)  # a rating without its payload
        self.rejects("CHECK constraint failed", ins, TOPIC, "contract_approval", TOPIC, draft, ch, T, ok)  # a payload on another kind
        self.rejects("CHECK constraint failed", ins, TOPIC, "rating_approval", TOPIC, draft, ch, T, json.dumps({"facets": {}}))  # malformed
        refused = "rates only entries of the draft the decision is about"
        for label, payload in (("a facet absent from the draft", {"facets": {"F-9": {"band": "limited"}}, "obligations": {}}),
                               ("an obligation absent from the draft", {"facets": {}, "obligations": {"O-9": {"band": "limited"}}}),
                               ("an obligation id given as a facet", {"facets": {"O-1": {"band": "limited"}}, "obligations": {}}),
                               ("a band outside the vocabulary", {"facets": {"F-1": {"band": "essential"}}, "obligations": {}}),
                               ("an obligation without a band", {"facets": {}, "obligations": {"O-1": {"score": 5}}})):
            with self.subTest(case=label):
                self.rejects(refused, ins, TOPIC, "rating_approval", TOPIC, draft, ch, T, json.dumps(payload))
        self.x(ins, TOPIC, "rating_approval", TOPIC, draft, ch, T, ok)

    def test_proposed_importance_cites_an_importance_receipt(self) -> None:
        """A2: a Jev-score proposal cites an importance_score decision receipt of
        the same topic; a receipt of another class or topic is refused."""
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        imp = self.spec("dspec_import01", cls="importance_score")
        self.decision_receipt("dec_screen01", "inv_pppppppp", self.spec())
        self.decision_receipt("dec_import01", "inv_pppppppp", imp, cls="importance_score")
        self.decision_receipt("dec_otherimp", "inv_oooooooo", imp, cls="importance_score", tid=OTHER)
        entries = {rid: obligation("O-" + rid, psource="jev_score", pscore=8, preceipt=rid) for rid in ("dec_screen01", "dec_otherimp", "dec_import01")}
        self.contract(TOPIC, 2, facets=(facet("F-1"),), obligations=tuple(entries.values()))
        self.insert_facet(TOPIC, 2, facet("F-1"))
        for rid in ("dec_screen01", "dec_otherimp"):
            with self.subTest(receipt=rid):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_obligation(TOPIC, 2, entries[rid])
                self.assertIn("importance_score receipt", str(ctx.exception))
        self.insert_obligation(TOPIC, 2, entries["dec_import01"])

    def dossier(self, rev: int, contract_rev: int, ch: str) -> None:
        self.x("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, ?, ?, 1, 'eval-1', ?, ?, ?)", TOPIC, rev, contract_rev, ch, h("7"), T)

    def test_completion_needs_approval_of_current_dossier(self) -> None:
        """D54 rewrite (A2): the transition names an approved completion approval
        of the current dossier (revision + hash) evaluated under the active,
        approved contract. Each near-miss differs from a valid decision in one
        dimension: currency (stale dossier), disposition, kind (a rating
        decision whose subject revision/hash deliberately coincide with the
        current dossier's), naming (a valid approval exists but the transition
        names another), protocol (dossier under an approved but non-active
        contract; under the active contract after an amendment superseded it
        — a dossier under a draft cannot even be written, RA3)."""
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", h("7"), T)
        self.approve_contract(TOPIC, 1)
        self.walk_to(TOPIC, "active")
        self.x("UPDATE queue_entries SET active_contract_revision = 1 WHERE topic_id = ?", TOPIC)
        complete = "UPDATE queue_entries SET status = 'completed_with_qualified_conclusions', status_decision_id = ?, state_revision = state_revision + 1 WHERE topic_id = ?"
        refused = "completion requires operator approval"
        self.dossier(1, 1, h("3"))
        self.decision("opd_stale001", "completion_approval", rev=1, hsh=h("3"))
        self.dossier(2, 1, h("4"))  # material change after that approval
        self.rejects(refused, complete, "opd_stale001", TOPIC)
        self.decision("opd_rejected", "completion_approval", disposition="rejected", rev=2, hsh=h("4"))
        self.rejects(refused, complete, "opd_rejected", TOPIC)
        self.rejects("existing subject", "INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at) VALUES ('opd_wronghsh', ?, 'completion_approval', 'approved', 'dossier', ?, 2, ?, 'trevor', ?)", TOPIC, TOPIC, h("3"), T)
        for rev in (2, 3, 4, 5):
            self.contract(TOPIC, rev)
        self.dossier(5, 1, self.content_hash_of(TOPIC, 5))  # current dossier carrying contract 5's hash
        self.decision("opd_wrongknd", "rating_approval", rev=5, hsh=self.content_hash_of(TOPIC, 5))
        self.rejects(refused, complete, "opd_wrongknd", TOPIC)
        self.approve_contract(OTHER, 1)
        self.x("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, 5, 1, 1, 'eval-1', ?, ?, ?)", OTHER, h("9"), h("7"), T)
        self.decision("opd_othertop", "completion_approval", tid=OTHER, rev=5, hsh=h("9"))
        self.rejects(refused, complete, "opd_othertop", TOPIC)  # another topic's approval of its own dossier 5
        self.decision("opd_valid005", "completion_approval", rev=5, hsh=self.content_hash_of(TOPIC, 5))
        self.rejects(refused, complete, "opd_wrongknd", TOPIC)  # a valid approval exists, but is not the one named
        self.x("UPDATE queue_entries SET active_contract_revision = 2 WHERE topic_id = ?", TOPIC)
        self.rejects(refused, complete, "opd_valid005", TOPIC)  # dossier's contract (approved) is not the active one
        # RA3: no dossier is ever evaluated against a draft (revision 2 is one)
        self.rejects("never a draft", "INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, 6, 2, 1, 'eval-1', ?, ?, ?)", TOPIC, h("6"), h("7"), T)
        # protocol currency: the dossier's (active) contract was approved, then superseded by an amendment
        self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 1", TOPIC)
        self.approve_contract(TOPIC, 2, kind="amendment_approval")
        self.dossier(6, 2, h("6"))
        self.decision("opd_supersed", "completion_approval", rev=6, hsh=h("6"))
        self.x("UPDATE contract_revisions SET status = 'superseded' WHERE topic_id = ? AND revision = 2", TOPIC)
        self.approve_contract(TOPIC, 3, kind="amendment_approval")
        self.rejects(refused, complete, "opd_supersed", TOPIC)  # dossier under the active contract, which is no longer approved
        self.x("UPDATE queue_entries SET active_contract_revision = 3 WHERE topic_id = ?", TOPIC)
        self.dossier(7, 3, h("8"))
        self.decision("opd_00000001", "completion_approval", rev=7, hsh=h("8"))
        self.x(complete, "opd_00000001", TOPIC)
        self.assertEqual(self.rows("SELECT status, status_decision_id FROM queue_entries WHERE topic_id = ?", TOPIC), [("completed_with_qualified_conclusions", "opd_00000001")])
        self.assert_terminal_authority_kept(TOPIC, "completed_with_qualified_conclusions", "opd_00000001",
                                            also_valid=self.decision("opd_second01", "completion_approval", rev=7, hsh=h("8")))
        # the pointer does move with an authorized transition: completed -> retired
        self.decision("opd_retire01", "retirement", rev=self.state_revision())
        self.x("UPDATE queue_entries SET status = 'retired', status_decision_id = 'opd_retire01', state_revision = state_revision + 1 WHERE topic_id = ?", TOPIC)
        self.assertEqual(self.rows("SELECT status, status_decision_id FROM queue_entries WHERE topic_id = ?", TOPIC), [("retired", "opd_retire01")])

    def assert_terminal_authority_kept(self, tid: str, status: str, used: str, also_valid: str) -> None:
        """RA1: after a terminal transition the authorizing-decision pointer keeps
        the decision actually used. The review's probe first — a rejected
        retirement decision about ANOTHER topic written over it with status and
        revision unchanged — then the same with the revision advanced, clearing
        it, another valid approval of the same subject, and simultaneous
        status+decision writes (same status re-asserted; a gated transition
        naming the rejected decision). Each is refused and the row reads back
        unchanged."""
        if not self.rows("SELECT 1 FROM operator_decisions WHERE decision_id = 'opd_unrelatd'"):
            self.decision("opd_unrelatd", "retirement", OTHER, disposition="rejected", rev=0)
        before = self.snapshot("queue_entries")
        moved = "changes only with the status transition it authorizes"
        for label, sql, fragment in (
                ("rejected other-topic decision, nothing else changed (the review's probe)", "UPDATE queue_entries SET status_decision_id = 'opd_unrelatd' WHERE topic_id = ?", moved),
                ("same, revision advanced", "UPDATE queue_entries SET status_decision_id = 'opd_unrelatd', state_revision = state_revision + 1 WHERE topic_id = ?", moved),
                ("cleared", "UPDATE queue_entries SET status_decision_id = NULL WHERE topic_id = ?", moved),
                ("another valid approval of the same subject", f"UPDATE queue_entries SET status_decision_id = '{also_valid}' WHERE topic_id = ?", moved),
                ("same status re-asserted with the rejected decision", f"UPDATE queue_entries SET status = '{status}', status_decision_id = 'opd_unrelatd', state_revision = state_revision + 1 WHERE topic_id = ?", moved),
                ("a gated transition naming the rejected decision", "UPDATE queue_entries SET status = 'retired', status_decision_id = 'opd_unrelatd', state_revision = state_revision + 1 WHERE topic_id = ?", None)):
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.x(sql, tid)
                if fragment:
                    self.assertIn(fragment, str(ctx.exception))
                self.assertEqual(self.snapshot("queue_entries"), before)
        self.assertEqual(self.rows("SELECT status, status_decision_id FROM queue_entries WHERE topic_id = ?", tid), [(status, used)])

    def test_retirement_needs_operator_decision(self) -> None:
        """D55 rewrite (A2): the transition names an approved retirement decision
        about this topic at the state revision being left. Near-misses, one
        dimension each: no decision, stale revision, disposition, topic (same
        revision number), kind (a completion approval whose subject revision
        equals the current state revision), naming (a valid decision exists but
        another is named); and retired is final (draft vocabulary, R2.5), so a
        used decision has no transition left to authorize."""
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", h("7"), T)
        self.approve_contract(TOPIC, 1)  # the wrong-kind probe below needs a dossier, and dossiers need an approved protocol (RA3)
        retire = "UPDATE queue_entries SET status = 'retired', status_decision_id = ?, state_revision = state_revision + 1 WHERE topic_id = ?"
        refused = "retirement requires"
        with self.assertRaises(sqlite3.IntegrityError):
            self.x(retire, None, TOPIC)  # no decision named at all
        self.decision("opd_stale000", "retirement", rev=self.state_revision())
        self.confirm_brief(TOPIC)
        self.set_status(TOPIC, "scoping")  # a commit after the decision makes it stale
        now = self.state_revision()
        self.rejects(refused, retire, "opd_stale000", TOPIC)
        self.decision("opd_rejected", "retirement", disposition="rejected", rev=now)
        self.decision("opd_othertop", "retirement", tid=OTHER, rev=now)
        self.x("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, ?, 1, 1, 'eval-1', ?, ?, ?)", TOPIC, now, h("3"), h("7"), T)
        self.decision("opd_wrongknd", "completion_approval", rev=now, hsh=h("3"))
        for did in ("opd_rejected", "opd_othertop", "opd_wrongknd"):
            with self.subTest(decision=did):
                self.rejects(refused, retire, did, TOPIC)
        self.decision("opd_00000001", "retirement", rev=now)
        self.rejects(refused, retire, "opd_stale000", TOPIC)  # a valid decision exists, but is not the one named
        self.x(retire, "opd_00000001", TOPIC)
        self.rejects("queue status transition not allowed", "UPDATE queue_entries SET status = 'queued', status_decision_id = NULL, state_revision = state_revision + 1 WHERE topic_id = ?", TOPIC)
        # RA1: the used decision stays on the retired row (the rejected same-topic
        # decision, an approved other-topic one, and the review's other-topic
        # rejected decision are all refused)
        for did in ("opd_rejected", "opd_othertop"):
            with self.subTest(substitute=did):
                self.rejects("changes only with the status transition it authorizes", "UPDATE queue_entries SET status_decision_id = ? WHERE topic_id = ?", did, TOPIC)
        self.assert_terminal_authority_kept(TOPIC, "retired", "opd_00000001", also_valid=self.decision("opd_second01", "retirement", rev=now))

    def test_terminal_statuses_cannot_be_inserted(self) -> None:
        """A2: creation is constrained to the initial intake status."""
        ins = "INSERT INTO queue_entries (topic_id, fleet_id, priority, status, status_decision_id, state_revision, created_at, updated_at) VALUES ('fleet-a:t3', 'fleet-a', 1, ?, ?, ?, ?, ?)"
        self.decision("opd_00000001", "retirement", rev=self.state_revision())
        for status, did in (("retired", "opd_00000001"), ("completed_with_qualified_conclusions", "opd_00000001"), ("active", None)):
            with self.subTest(status=status):
                self.rejects("created awaiting brief confirmation", ins, status, did, 0, T, T)
        self.rejects("created awaiting brief confirmation", ins, "awaiting_brief_confirmation", None, 5, T, T)
        self.x(ins, "awaiting_brief_confirmation", None, 0, T, T)

    def test_status_change_is_a_commit(self) -> None:
        self.confirm_brief(TOPIC)  # leaving intake needs a confirmed brief (G-4); here only the revision rule may refuse
        self.rejects("advances state_revision by one", "UPDATE queue_entries SET status = 'scoping' WHERE topic_id = ?", TOPIC)
        self.set_status(TOPIC, "scoping")
        self.assertEqual(self.state_revision(), 1)
        # the authorizing decision is recorded only with a decision-gated status
        self.decision("opd_00000001", "retirement", rev=self.state_revision())
        self.rejects("CHECK constraint failed", "UPDATE queue_entries SET status = 'awaiting_scope_approval', status_decision_id = 'opd_00000001', state_revision = state_revision + 1 WHERE topic_id = ?", TOPIC)
        self.set_status(TOPIC, "retired", "opd_00000001")


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
                             "VALUES ('opd_nosubject', ?, 'brief_confirmation', 'approved', 'intake_brief', ?, ?, ?, 'trevor', ?)", kw.get("tid", TOPIC), kw["ref"], kw["rev"], kw["hsh"], T)
        self.decision("opd_rejected", "brief_confirmation", disposition="rejected", ref=brief, rev=version, hsh=bhash)
        self.decision("opd_second00", "brief_confirmation", ref=brief, rev=version, hsh=bhash)
        self.decision("opd_wrongknd", "scope_approval", ref=brief, rev=version, hsh=bhash)
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
        self.x("INSERT INTO search_observations (observation_id, invocation_id, topic_id, request_identity, attempt, lane, request, obligation_ids, started_at, coverage_state, result_count, completeness, policy_version) "
               "VALUES ('o1', 'inv_draft001', ?, ?, 1, 'crossref', '{}', '[]', ?, 'searched_ok', 1, 'complete', 'pol1')", TOPIC, h("4"), T)
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
        self.x("INSERT INTO search_observations (observation_id, invocation_id, topic_id, request_identity, attempt, lane, request, obligation_ids, started_at, coverage_state, result_count, completeness, policy_version) "
               "VALUES ('o1', 'inv_scope001', ?, ?, 1, 'crossref', '{}', '[]', ?, 'searched_ok', 2, 'complete', 'pol1')", TOPIC, h("4"), T)
        self.receipt("op_00000001", "inv_scope001", lease="lease_dddddddd", kind="final_outcome")
        self.x("UPDATE invocations SET state = 'result_ready', result_payload_digest = ?, result_staged_at = ? WHERE invocation_id = 'inv_scope001'", h("d"), T)
        self.x("UPDATE invocations SET state = 'committed' WHERE invocation_id = 'inv_scope001'")
        self.assertEqual(self.rows("SELECT admission_context, contract_revision, brief_hash FROM operation_receipts"), [("pre-contract/1", None, h("b"))])
        self.assertEqual(self.rows("SELECT state FROM invocations"), [("committed",)])
        self.assertEqual(self.rows("SELECT count(*) FROM contract_revisions"), [(0,)])


class DraftVocabularyTransitionTest(StoreTestCase):
    """Ruling R2.5: the draft queue and claim vocabularies carry explicit,
    tested transition semantics. Oracles are hand-written from the README's
    "Draft vocabularies" section, not read from the DDL."""

    QUEUE = {
        "awaiting_brief_confirmation": {"scoping", "retired"},
        "scoping": {"awaiting_scope_approval", "held", "capability_blocked", "retired"},
        "awaiting_scope_approval": {"awaiting_contract_approval", "scoping", "retired"},
        "awaiting_contract_approval": {"queued", "scoping", "retired"},
        "queued": {"active", "held", "capability_blocked", "retired"},
        "active": {"resting", "queued", "held", "awaiting_judgment", "completed_with_qualified_conclusions", "capability_blocked", "stopped_for_resources", "retired"},
        "resting": {"active", "queued", "held", "retired"},
        "held": {"scoping", "awaiting_scope_approval", "awaiting_contract_approval", "queued", "retired"},
        "capability_blocked": {"scoping", "queued", "held", "retired"},
        "stopped_for_resources": {"queued", "awaiting_judgment", "retired"},
        "awaiting_judgment": {"active", "queued", "completed_with_qualified_conclusions", "stopped_for_resources", "retired"},
        "completed_with_qualified_conclusions": {"queued", "retired"},
        "retired": set(),
    }
    CLAIMS = {
        "provisional": {"accepted_support", "contested", "rejected", "quarantined", "superseded"},
        "accepted_support": {"contested", "quarantined", "superseded"},
        "contested": {"accepted_support", "rejected", "quarantined", "superseded"},
        "quarantined": {"provisional", "rejected", "superseded"},
        "rejected": {"superseded"},
        "superseded": set(),
    }
    CLAIM_PATH = {"provisional": (), "accepted_support": ("accepted_support",), "contested": ("contested",), "quarantined": ("quarantined",),
                  "rejected": ("rejected",), "superseded": ("superseded",)}

    def fresh_topic(self, n: int) -> str:
        """A new topic with a confirmed intake brief, whose revision-1 contract
        is approved and active, with a current dossier and a valid completion
        approval of it, so leaving intake, completion and retirement attempts
        are decided by the transition rule alone."""
        tid = f"fleet-a:m{n:04d}"
        self.x("INSERT INTO queue_entries (topic_id, fleet_id, priority, status, created_at, updated_at) VALUES (?, 'fleet-a', 1, 'awaiting_brief_confirmation', ?, ?)", tid, T, T)
        self.confirm_brief(tid)
        self.contract(tid, 1, content_hash="sha256:" + f"{n:060x}c0c0")
        self.approve_contract(tid, 1, did=f"opd_ca{n:06d}")
        self.x("UPDATE queue_entries SET active_contract_revision = 1 WHERE topic_id = ?", tid)
        dossier_hash = "sha256:" + f"{n:060x}d0d0"
        self.x("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, 1, 1, 1, 'eval-1', ?, ?, ?)", tid, dossier_hash, h("7"), T)
        self.decision(f"opd_co{n:06d}", "completion_approval", tid, rev=1, hsh=dossier_hash)
        return tid

    def reach(self, tid: str, n: int, status: str) -> None:
        if status == "completed_with_qualified_conclusions":
            self.walk_to(tid, "active")
            self.set_status(tid, status, f"opd_co{n:06d}")
        elif status == "retired":
            self.decision(f"opd_rt{n:06d}", "retirement", tid, rev=self.state_revision(tid))
            self.set_status(tid, status, f"opd_rt{n:06d}")
        else:
            self.walk_to(tid, status)

    def test_queue_status_transitions(self) -> None:
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'application/json', ?)", h("7"), T)
        n = 0
        for src, allowed in self.QUEUE.items():
            for dst in self.QUEUE:
                if dst == src:
                    continue
                n += 1
                with self.subTest(src=src, dst=dst):
                    tid = self.fresh_topic(n)
                    self.reach(tid, n, src)
                    decision = None
                    if dst == "completed_with_qualified_conclusions":
                        decision = f"opd_co{n:06d}"
                    elif dst == "retired":
                        decision = f"opd_rx{n:06d}"
                        self.decision(decision, "retirement", tid, rev=self.state_revision(tid))
                    attempt = "UPDATE queue_entries SET status = ?, status_decision_id = ?, state_revision = state_revision + 1 WHERE topic_id = ?"
                    if dst in allowed:
                        self.x(attempt, dst, decision, tid)
                        self.assertEqual(self.rows("SELECT status FROM queue_entries WHERE topic_id = ?", tid), [(dst,)])
                    else:
                        self.rejects("queue status transition not allowed", attempt, dst, decision, tid)
        self.assertEqual(n, 13 * 12)

    def test_claim_status_transitions(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.lease("lease_vvvvvvvv", 2, scope="verification")
        self.invocation("inv_vvvvvvvv", kind="verification", lease="lease_vvvvvvvv")
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, staged_at) VALUES (?, 10, 'text/plain', ?)", h("7"), T)
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000001', 'doi', '10.1/x', ?)", T)
        n = 0
        for src, allowed in self.CLAIMS.items():
            for dst in self.CLAIMS:
                if dst == src:
                    continue
                n += 1
                with self.subTest(src=src, dst=dst):
                    cid = f"clm_{n:08d}"
                    # non-load-bearing, so accepted_support is decided by the transition rule alone
                    self.x("INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES (?, 1, ?, ?, 'inv_pppppppp', 0, NULL, 'provisional', ?)", cid, TOPIC, h("7"), T)
                    for step in self.CLAIM_PATH[src]:
                        self.x("UPDATE claims SET status = ? WHERE claim_id = ?", step, cid)
                    attempt = "UPDATE claims SET status = ? WHERE claim_id = ?"
                    if dst in allowed:
                        self.x(attempt, dst, cid)
                    else:
                        self.rejects("claim status transition not allowed", attempt, dst, cid)
        self.assertEqual(n, 6 * 5)

    def test_mandatory_signals_are_code_or_operator_raised(self) -> None:
        """G-12 / R2.5: retraction and decision-record-change triggers are never a
        model observation (a model may rank discretionary alerts only)."""
        ins = "INSERT INTO review_triggers (trigger_identity, topic_id, reason_code, signal_source, cause_ref, observed_at) VALUES (?, ?, ?, ?, 'SRC-9', ?)"
        for n, reason in enumerate(("retraction", "decision_record_change")):
            with self.subTest(reason=reason):
                self.rejects("CHECK constraint failed", ins, h(str(n)), TOPIC, reason, "primary_observation", T)
                self.x(ins, h(str(n)), TOPIC, reason, "deterministic", T)
        self.x(ins, h("9"), TOPIC, "persistent_contradiction", "primary_observation", T)  # discretionary signals may be observations


class FacetImportanceTest(StoreTestCase):
    """A3: facet importance is its own record, bound to the hash-locked
    document and the operator's rating decision — never inferred from
    obligations — and G-3's uncovered-critical-facet rule gates approval."""

    def approve(self, rev: int) -> None:
        self.decision(f"opd_appr{rev:04d}", "contract_approval", rev=rev, hsh=self.content_hash_of(TOPIC, rev))
        self.x("UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = ? WHERE topic_id = ? AND revision = ?", f"opd_appr{rev:04d}", TOPIC, rev)

    def uncovered(self, rev: int) -> list[tuple]:
        return self.rows("SELECT facet_id FROM uncovered_critical_facets WHERE topic_id = ? AND contract_revision = ? ORDER BY facet_id", TOPIC, rev)

    def test_critical_facet_with_zero_obligations_is_representable_and_blocks_approval(self) -> None:
        # F-omitted is rated critical by the operator (who rated draft 2) and no obligation tags it
        f_omitted = facet("F-omitted", band="critical", score=8, decision="opd_rate0001")
        f2 = facet("F-2", band="important", decision="opd_rate0001")
        o1 = obligation("O-1", ("F-2",), band="important", decision="opd_rate0001")
        draft = self.rate("opd_rate0001", facets=(f_omitted, f2), obligations=(o1,))
        self.contract_with_rows(TOPIC, draft + 1, facets=(f_omitted, f2), obligations=(o1,))
        self.assertEqual(self.rows("SELECT operator_importance_band FROM facets WHERE facet_id = 'F-omitted'"), [("critical",)])
        self.assertEqual(self.uncovered(draft + 1), [("F-omitted",)])
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.approve(draft + 1)
        self.assertIn("no uncovered critical facet", str(ctx.exception))
        # a revision whose obligation tags the critical facet is approvable
        self.contract_with_rows(TOPIC, draft + 2, facets=(f_omitted,), obligations=(obligation("O-2", ("F-omitted",)),))
        self.assertEqual(self.uncovered(draft + 2), [])
        self.approve(draft + 2)

    def test_approval_needs_complete_rows_and_every_facet_rated(self) -> None:
        both = (facet("F-1", band="limited", decision="opd_rate0001"), facet("F-2", band="limited", decision="opd_rate0001"))
        d = self.rate("opd_rate0001", facets=both)
        # a document facet without its row
        self.contract(TOPIC, d + 1, facets=both, obligations=(obligation("O-1", ("F-1",)),))
        self.insert_facet(TOPIC, d + 1, both[0])
        self.insert_obligation(TOPIC, d + 1, obligation("O-1", ("F-1",)))
        with self.assertRaises(sqlite3.IntegrityError):
            self.approve(d + 1)
        # a document obligation without its row
        self.contract(TOPIC, d + 2, facets=both, obligations=(obligation("O-1", ("F-1",)), obligation("O-2", ("F-2",))))
        for entry in both:
            self.insert_facet(TOPIC, d + 2, entry)
        self.insert_obligation(TOPIC, d + 2, obligation("O-1", ("F-1",)))
        with self.assertRaises(sqlite3.IntegrityError):
            self.approve(d + 2)
        # an unrated facet (its importance could not be known critical)
        self.contract_with_rows(TOPIC, d + 3, facets=(both[0], facet("F-2")), obligations=(obligation("O-1", ("F-1",)),))
        with self.assertRaises(sqlite3.IntegrityError):
            self.approve(d + 3)
        self.contract_with_rows(TOPIC, d + 4, facets=both, obligations=(obligation("O-1", ("F-1",)),))
        self.approve(d + 4)

    def test_facet_row_must_equal_its_document_entry(self) -> None:
        doc_entry = facet("F-1", band="critical", score=8, decision="opd_rate0001")
        d = self.rate("opd_rate0001", facets=(doc_entry,))
        self.contract(TOPIC, d + 1, facets=(doc_entry,))
        # a rated probe that differs from what the operator rated is refused by the
        # rating binding too; which of the two reports first is SQLite's trigger
        # order, not the invariant, so either reason is accepted there
        document, rating = "equal its document entry", "exactly what the operator rated"
        for field, row, reasons in (("band", facet("F-1", band="important", decision="opd_rate0001"), (document, rating)),
                                    ("score", facet("F-1", band="critical", score=9, decision="opd_rate0001"), (document, rating)),
                                    ("unrated", facet("F-1"), (document,)),
                                    ("absent", facet("F-9", band="critical", score=8, decision="opd_rate0001"), (document, rating))):
            with self.subTest(field=field):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_facet(TOPIC, d + 1, row)
                self.assertTrue(any(reason in str(ctx.exception) for reason in reasons), str(ctx.exception))
        self.insert_facet(TOPIC, d + 1, doc_entry)

    def test_facet_rating_bound_to_a_rating_decision(self) -> None:
        """A3 / RA2 for facet ratings, mirroring the obligation test: the operator
        rated draft 2 (F-1 critical/8, F-3 important with no score; F-2
        present but unrated). Near-misses,
        one dimension each, with the probe's own decision named in its
        document entry: disposition, kind, topic (another topic's identical
        draft), a decision about the revision carrying it, the review's probe
        (the empty draft 1's decision invoked for an invented facet), a facet
        the operator did not rate, a changed band (with and without a score)
        or score, the same id redefined (another label), an unrelated sibling
        draft; and RA2-R, as for obligations: a self-parent revision and a
        two-revision cycle, the entry citing an approved decision (payload
        matching) about that very revision, never yield a rated row (the
        ancestry CHECK or the rating binding refuses). Then the
        out-of-band CHECK (the payload rates it so, so only the CHECK refuses),
        immutability, and an unchanged carry-forward over two revisions."""
        f1 = facet("F-1", band="critical", score=8, decision="opd_rate0001")
        f3 = facet("F-3", band="important", decision="opd_rate0001")  # rated without a score
        out_of_band = facet("F-x", band="critical", score=5, decision="opd_rate0001")
        draft = self.rate("opd_rate0001", facets=(f1, facet("F-2"), f3, out_of_band))
        payload = {"facets": {"F-1": {"band": "critical", "score": 8}}, "obligations": {}}
        self.decision("opd_rejected", "rating_approval", disposition="rejected", rev=draft, hsh=self.chash(TOPIC, draft), payload=payload)
        self.decision("opd_approval", "contract_approval", rev=draft, hsh=self.chash(TOPIC, draft))
        self.rate("opd_othertop", OTHER, facets=(f1, facet("F-2"), f3, out_of_band), payload=payload)
        self.decision("opd_emptydft", "rating_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        refused = "a facet rating is exactly what the operator rated"

        def revision(entry: dict, parent: int = draft) -> int:
            rev = self.rows("SELECT max(revision) + 1 FROM contract_revisions WHERE topic_id = ?", TOPIC)[0][0]
            self.contract(TOPIC, rev, facets=(entry,), parent=parent, content_hash=self.chash(TOPIC, rev))
            return rev

        def probe(label: str, entry: dict, parent: int = draft) -> None:
            with self.subTest(case=label):
                rev = revision(entry, parent)
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_facet(TOPIC, rev, entry)
                self.assertIn(refused, str(ctx.exception))

        for did in ("opd_rejected", "opd_approval", "opd_othertop"):
            probe(did, facet("F-1", band="critical", score=8, decision=did))
        samerev = facet("F-1", band="critical", score=8, decision="opd_samerev")
        rev = revision(samerev)
        self.decision("opd_samerev", "rating_approval", rev=rev, hsh=self.chash(TOPIC, rev), payload=payload)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.insert_facet(TOPIC, rev, samerev)
        self.assertIn(refused, str(ctx.exception))
        probe("the review's probe: an invented facet under the empty draft's decision", facet("F-new", band="critical", score=9, decision="opd_emptydft"))
        probe("a facet the operator did not rate", facet("F-2", band="critical", score=8, decision="opd_rate0001"))
        probe("a changed band and score", facet("F-1", band="limited", score=1, decision="opd_rate0001"))
        probe("a changed band alone (no score either way)", facet("F-3", band="limited", decision="opd_rate0001"))
        probe("a changed score alone", facet("F-1", band="critical", score=9, decision="opd_rate0001"))
        probe("the same id redefined", dict(f1, label="another subject"))
        probe("an unrelated (sibling) draft", f1, parent=1)
        for label, cyclic in (("a self-parent revision", False), ("a two-revision cycle", True)):
            with self.subTest(case=label):
                rev = self.rows("SELECT max(revision) + 1 FROM contract_revisions WHERE topic_id = ?", TOPIC)[0][0]
                did = f"opd_selfanc{int(cyclic)}"
                entry = facet("F-1", band="critical", score=8, decision=did)
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    if cyclic:
                        self.contract_cycle(TOPIC, rev, rev + 1, facets=(entry,))
                    else:
                        self.contract(TOPIC, rev, facets=(entry,), parent=rev, content_hash=self.chash(TOPIC, rev))
                    self.decision(did, "rating_approval", rev=rev, hsh=self.chash(TOPIC, rev), payload=payload)
                    self.insert_facet(TOPIC, rev, entry)
                self.assertTrue(any(f in str(ctx.exception) for f in ("contract_parent_is_earlier", refused)), str(ctx.exception))
                self.assertEqual(self.rows("SELECT count(*) FROM contract_revisions WHERE topic_id = ? AND revision >= ?", TOPIC, rev), [(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM facets"), [(0,)])
        rev = revision(out_of_band)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.insert_facet(TOPIC, rev, out_of_band)
        self.assertIn("CHECK constraint failed", str(ctx.exception))
        first = revision(f1)
        self.insert_facet(TOPIC, first, f1)
        self.rejects("facets are immutable", "UPDATE facets SET operator_importance_band = 'limited'")
        second = revision(f1, parent=first)
        self.insert_facet(TOPIC, second, f1)
        self.assertEqual(self.rows("SELECT contract_revision, operator_importance_band, operator_importance_score FROM facets ORDER BY contract_revision"),
                         [(first, "critical", 8), (second, "critical", 8)])

    def test_facet_proposal_cites_an_importance_receipt(self) -> None:
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.lease("lease_zzzzzzzz", 1, tid=OTHER)
        self.invocation("inv_oooooooo", tid=OTHER, lease="lease_zzzzzzzz")
        imp = self.spec("dspec_import01", cls="importance_score")
        self.decision_receipt("dec_screen01", "inv_pppppppp", self.spec())
        self.decision_receipt("dec_import01", "inv_pppppppp", imp, cls="importance_score")
        self.decision_receipt("dec_otherimp", "inv_oooooooo", imp, cls="importance_score", tid=OTHER)
        entries = {rid: facet("F-" + rid, psource="jev_score", pscore=8, preceipt=rid) for rid in ("dec_screen01", "dec_otherimp", "dec_import01")}
        self.contract(TOPIC, 2, facets=tuple(entries.values()))
        for rid in ("dec_screen01", "dec_otherimp"):
            with self.subTest(receipt=rid):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.insert_facet(TOPIC, 2, entries[rid])
        self.insert_facet(TOPIC, 2, entries["dec_import01"])

    def test_obligation_row_equals_its_entry_and_tags_only_its_facets(self) -> None:
        """A3 / RA6: an obligation row equals its document entry in every field
        it duplicates — facet tags, importance, template id/version/claim
        type, stopping profile, exploratory flag — and tags only facets of
        its revision."""
        entry = obligation("O-1", ("F-1",), band="important", decision="opd_rate0001")
        d = self.rate("opd_rate0001", facets=(facet("F-1"),), obligations=(entry,))
        self.contract(TOPIC, d + 1, facets=(facet("F-1"), facet("F-1b")), obligations=(entry, obligation("O-2", ("F-9",))))
        self.insert_facet(TOPIC, d + 1, facet("F-1"))
        self.insert_facet(TOPIC, d + 1, facet("F-1b"))
        # each row differs from its entry in one field. The rating binding reads
        # the documents, so it passes the tag probe and has nothing to check on
        # the unrated one; the band probe also differs from what the operator
        # rated, so the rating binding refuses it too (either reason is accepted:
        # which reports first is SQLite's trigger order, not the invariant)
        document, rating = "equal its document entry", "exactly what the operator rated"
        for name, row, reasons in (("facet tags (another facet of the revision)", obligation("O-1", ("F-1", "F-1b"), band="important", decision="opd_rate0001"), (document,)),
                                   ("band", obligation("O-1", ("F-1",), band="critical", decision="opd_rate0001"), (document, rating)),
                                   ("unrated row for a rated entry", obligation("O-1", ("F-1",)), (document,))):
            with self.subTest(field=name):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_obligation(TOPIC, d + 1, row)
                self.assertTrue(any(reason in str(ctx.exception) for reason in reasons), str(ctx.exception))
        # RA6: the protocol fields accounting reads (the review's probe values)
        for column, value in (("template_id", "T-approved"), ("template_version", 3), ("claim_type", "mechanism"),
                              ("stopping_profile_id", "SP-approved"), ("exploratory", 1)):
            with self.subTest(column=column):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_obligation(TOPIC, d + 1, entry, **{column: value})
                self.assertIn("equal its document entry", str(ctx.exception))
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.insert_obligation(TOPIC, d + 1, obligation("O-2", ("F-9",)))  # matches its entry, but F-9 is no facet of the revision
        self.assertIn("tag only facets of its revision", str(ctx.exception))
        self.insert_obligation(TOPIC, d + 1, entry)


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
