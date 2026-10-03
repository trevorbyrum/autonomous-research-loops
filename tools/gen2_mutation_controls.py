#!/usr/bin/env python3
"""Paired positive controls for the gen-2 mutation inventory (task
1c-repair-2 C4; Astra 1c re-review C4; the evidence rule tightened in task
1c-repair-3, Astra 1c re-review 2 BLOCK 2).

A mutant's killers are the tests that must fail under it. Its paired
controls are tests that must pass under it: tests that are not its killers
and that take an accepted path through the code the mutant changes, so that
a kill does not rest on that path being broken (what this does and does not
establish: below).
tools/gen2_mutations.py runs both, per mutant, and reads the controls from
tools/gen2_mutation_controls.json, which this tool writes. It is not part of
the build: it is rerun when the inventory or the tests change (the runner
refuses a mutant with no entry, and a control that is not exactly one test).

  trace    one unmutated run of the whole suite, recording per test what it
           executed (below) and whether it passed -> --trace FILE
  choose   pick each mutant's controls from a trace -> the controls file

What counts as taking a path through the mutated code, per kind of target:
  * Python (requirements()): the lines the mutant changes, found by difflib
    over the whole file (a line of `old` it leaves as it was is not one).
    Inside a function each belongs to the innermost statement whose own
    lines hold it (an if's or while's test, a for's header, an except
    clause; a simple statement whole), and the test must
      - for a changed refusal — a raise (not of FLOW, the exceptions raised to
        return an outcome), or a call to a function of the same file whose
        last statement is such a raise — pass the guard that directly
        governs it: leave that if's or while's test, that loop's header, or
        that try's body (whose handler holds the refusal), within one frame,
        for a line outside the refusal (or return from it); a changed if or
        while whose own branch is a refusal is passed the same way, having
        executed its changed line;
      - for any other changed statement, an if or while included, execute
        its changed line (a line with no instruction of its own, which no
        traced run executes, falls back to its statement's first), or the
        test of the if or while that directly holds it in a branch, or the
        header of the for loop whose body directly holds it (as for a
        refusal; task 1c-repair-4): the guard deciding whether it runs,
        either way — a loop over nothing included;
      - for a changed except clause, or a changed statement directly in its
        handler, also the try completing: its body left for a line outside
        the try (or returning from it), the path on which no handler runs.
    An enclosing if, while or try is never evidence: reaching the branch
    around a guard is not reaching the guard. A refusal that no guard in its
    function governs has no accepted path through it, and no control. A
    changed statement of a module's own program counts as it is, a def line
    (run at import) does not, and a changed module or class constant counts
    where a function reads it. Its own process is traced with
    sys.monitoring, recording each line and each arc (a line and the next
    one run in the same frame, or its return); a child it starts runs a copy
    that carries a tracing prologue (the child tree for gen2/ modules and
    scripts, the path-handed copy for a tool) and its lines and arcs are
    credited to the test running when it recorded them. Line numbers are
    those of the repository file: the prologue shares an existing line.
  * a DDL trigger: a statement that succeeds enters the trigger (its WHEN is
    evaluated), in an instrumented copy of the DDL (the store suite only —
    the DDL mutants reach no other tests).
  * a DDL table or index: a statement that succeeds writes a row of that
    table (an insert, or failing any, an update).
  * a schema file: the test declares a valid fixture of that schema (each
    such test re-checks the whole schema tree with the mutant in place).
  * a DDL trigger that refuses every statement it enters (no WHEN): nothing
    accepted passes through it, so the control writes a row of the table it
    guards, in a statement that succeeds, and says so;
  * otherwise (the connection pragmas, boundaries.toml, common.schema.json)
    by hand, in MANUAL, with the reason.
Where only a killer takes that path, it may hold its own accepted case (the
task's other route: the accepted case inside the killer): credited only
where the case also runs under the mutant — before the assertion the mutant
fails, or beside it in a subTest — as read and recorded in READ_IN_KILLER or
MANUAL; otherwise the accepted case is split out into a test of its own.
Only tests that passed in the trace are candidates, and only tests the
runner points at the mutant: a path-handed tool reaches only the module
holding its path (or, where a fixtures module holds the path, the test
modules that import it: the three documentation and metrics tools of task
2q-a), and a DDL mutant only the store suite. For the
supervisor's own files the canonical accepted-path tests (PREFERRED: a clean
end commits, a regular file is staged as found, ...) are taken first where
they are candidates. Otherwise the tests that took no refusal or error path
in the target at all (no exception raised inside the file — a refusal, or
an error it handles — nor, for the DDL, a statement that failed: every path
they took through it was accepted, as far as a raise shows) come first
(task 1c-repair-3); then candidates in a killer's class, then its module,
then the rest; within those, the fewest such paths, then those whose names
state an accepted behaviour before those whose names state a refusal
(NEGATIVE), then the fastest in the trace — the same for a mutant that
over-restricts: its control too is an accepted path the mutant still
accepts (until task 1c-repair-3 it preferred a refusal that still held). A
control already in the file stays chosen while it still qualifies under the
rule above, unless it took a refusal path and a candidate that took none
exists, so a new trace does not trade verified controls for equal ones. The
mutation run
checks that each control passes under its mutant; `choose --run LOG` reads a
run's log, keeps each control that did not pass as rejected for that mutant
(in the file, so it stays rejected), and takes the next candidate.

What the rule establishes, for a Python mutant with a paired control: in
an unmutated traced run the control executed a line the mutant changes; or
evaluated the guard directly governing a changed statement that is not a
refusal (the if or while holding it in a branch, the for loop holding it in
its body), either way, without necessarily running the statement (Astra 1c
re-review 3: evidence-not-recorded's control evaluates its guard and never
runs the changed line); or passed the guard directly governing a changed
refusal without taking it. The mutation run then shows it passing under the
mutant. What it does not establish: why a killer failed (a control passing
beside it shows that path still works under the mutant, not that the
guard's absence is what the killer caught); that the accepted path is the
one the guard exists for, or that the test's assertions depend on that
evaluation (a control that reaches the
changed line and later fails on something else is not a control — the run
rejects it — but one that reaches it and asserts nothing about it passes);
which operand of a compound condition decided it; that the passing
evaluation is the same one that executed a changed line of a multi-line
guard; a refusal expressed as a returned value rather than a raise, which
is treated as an ordinary statement (executed, not passed); and a line or
arc run by a child that dies before its prologue, or between the tests'
time windows. For the DDL: a statement that enters a trigger whose WHEN is
false for a reason other than the guard's also counts. By-hand entries
(MANUAL, READ_IN_KILLER) are judgments, each with its reason. A mutant with
no candidate is recorded with an empty list and its reason, and the runner
reports it.
"""
from __future__ import annotations

import argparse
import ast
import bisect
import difflib
import importlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "gen2" / "tests"
CONTROLS = ROOT / "tools" / "gen2_mutation_controls.json"
TOOL_ID = 3  # a sys.monitoring tool id no one else in the suite uses
# Exceptions raised to return an outcome from inside a step, not to refuse: the supervisor's Waiting ("launching",
# "waiting_launch", ...). Neither a refusal in the rule nor a refusal path in the ranking. Its subclass Held, the
# router-call chokepoint's refusal, is raised by its own name and stays one.
FLOW = frozenset({"Waiting"})

# Mutants whose code the tracing cannot reach, with their controls and why.
_REAL_GRAPH = "loads the same real gen2/boundaries.toml through the checker and shows what it grants still accepted"
_IMPORTER_GRAPH = ("test_check_boundaries.BoundaryCheckerTest.test_importer_cannot_reach_a_store_under_the_real_graph",
                   _REAL_GRAPH + " (the importer's import of core)")
_ROUTER_GRAPH = ("test_check_boundaries.BoundaryCheckerTest.test_store_writes_are_the_routers_under_the_real_graph",
                 _REAL_GRAPH + " (the router's reach to the store's write primitives)")
_ORDER = "the tool's own test; no other test calls compare()"
MANUAL: dict[str, dict] = {
    # task 2a: the signal command's schema is a module constant read when the Router builds its SchemaSet, not by a traced line of
    # the request's path; the accepted request validates against the changed enum
    **{mid: {"controls": ["test_router_workflow.SignalTest.test_a_signal_is_queued_pending_and_opens_its_review"],
             "why": "validates an accepted retraction from code policy against the signal command's schema (gen2/router/scheduling.py "
                    "SCHEDULING_COMMANDS, whose enum the mutant widens) and records it: the widened schema still accepts it"}
       for mid in ("2A-signal-discretionary", "2A-signal-model-source")},
    # task 2b-repair A6: the same shape — record_gateway_facts' schema is a module constant (gen2/router/capabilities.py
    # CAPABILITY_COMMANDS) read when the Router builds its SchemaSet, not by a traced line of the request's path
    # task 2b-repair A1: every traced uncaptured answer also has an empty lane (the killers'); the uncaptured answer with
    # records only was written as a test of its own, added after the trace
    "2B-uncaptured-empty-kept": {"controls": ["test_gateway_client.RecordedAnswers.test_control_an_uncaptured_lane_with_records_keeps_them_as_a_lower_bound"],
                                 "why": "evaluates gen2/gateway_client/observe.py uncaptured's changed guard (searched_empty?) for a searched_ok lane of "
                                        "an uncaptured answer — false, on the accepted path to a partial lower bound — and asserts that bound: the "
                                        "mutant, which skips the guard, leaves it so"},
    "2B-fact-namespace-open": {"controls": ["test_gateway_client.GatewayFactsCommand.test_a_fact_is_recorded_and_replays"],
                               "why": "validates an accepted gateway.secrets.vault fact against gateway_facts' schema, whose capability pattern the "
                                      "mutant widens, and records it: the widened schema still accepts it"},
    # task 2b-repair-13b (Gate D #3): the observation command's page_outcome and continuation schema is a module constant (gen2/router/
    # service.py COMMANDS) read when the Router builds its SchemaSet, not by a traced line of the request's path; the accepted
    # observations, a continuation with a string cursor and a page cap with an integer one, validate against the widened schema
    **{mid: {"controls": ["test_gateway_client.RecordedByTheRouter.test_how_pagination_ended_is_recorded_with_its_cursor"],
             "why": "validates and records accepted observations whose page outcomes include a continuation and a page cap with their cursors "
                    "against the observation command's schema (gen2/router/service.py COMMANDS, which the mutant widens): the widened schema "
                    "still accepts them"}
       for mid in ("2B13-schema-outcome-open", "2B13-schema-cursor-type", "2B13-schema-continuation-extras")},
    # task 2b-repair-13d: `recv` and `send` of the deadline socket are the two calls an HTTP exchange never makes (http.client reads through
    # recv_into and writes with sendall), so only the unit tests that call them directly execute them. Task 2b-repair-15 (Astra's final 2b
    # review) added a timely call of each, written as a test of its own: with time left, the call returns what arrived / sends what it is given
    **{mid: {"controls": [control],
             "why": f"calls gen2/gateway_client/client.py _DeadlineSocket.{call} directly, as no exchange does, with time left on the deadline, and asserts "
                    f"{what}: the mutant, which drops only the arming, leaves that unchanged"}
       for mid, control, call, what in (
           ("2B13D-recv-not-armed", "test_gateway_exchange.EachCallIsGivenWhatIsLeft.test_control_recv_returns_what_arrives_with_time_left", "recv", "that what a peer sent inside the deadline is read whole"),
           ("2B13D-send-not-armed", "test_gateway_exchange.EachCallIsGivenWhatIsLeft.test_control_send_sends_with_time_left", "send", "that a peer reading inside the deadline receives what it is given"))},
    # task 2b-repair-15 (Astra F2): the name-resolution guards. Each control takes the accepted path through the changed code and asserts something the mutant leaves alone:
    # a name looked up beforehand is connected to (and, over TLS, checked as the name); a failed lookup leaves the endpoint stale and every exchange a failure; an address is the client's own
    "2B15-an-exchange-resolves-a-name": {"controls": ["test_gateway_exchange.NoExchangeResolvesAName.test_a_name_that_was_looked_up_beforehand_is_connected_to_and_stays_the_hosts_name",
                                                       "test_gateway_exchange.TlsNamesAreChecked.test_the_certificate_is_checked_against_the_hostname_and_the_server_name_sent_is_the_hostname"],
                                         "why": "executes gen2/gateway_client/client.py _DeadlineHTTPConnection's changed `_create_connection` line on its accepted path: the name was looked up beforehand, so an address is admitted and the "
                                                "alternative the mutant adds (a lookup by the exchange itself, when none is) is never reached, and the exchange connects and reads its reply, over plain HTTP and over TLS"},
    **{mid: {"controls": ["test_gateway_exchange.NoExchangeResolvesAName.test_a_failed_lookup_leaves_the_client_built_and_stale_and_every_exchange_a_failure_at_once"],
             "why": "a client whose lookup failed takes a connection failure through gen2/gateway_client/client.py _exchange's changed line (the withdrawal) and asserts a failure at once and a stale "
                    "endpoint: the mutant, which looks up again there (the resolver is a stand-in that fails, so the endpoint is withdrawn again), or leaves the endpoint as it was (it has no addresses "
                    "to withdraw), keeps both"}
       for mid in ("2B15-an-exchange-re-resolves-after-a-failure", "2B15-a-connection-failure-leaves-the-endpoint-fresh")},
    "2B15-an-ip-literal-is-looked-up": {"controls": ["test_gateway_exchange.NoExchangeResolvesAName.test_a_name_that_was_looked_up_beforehand_is_connected_to_and_stays_the_hosts_name"],
                                        "why": "executes gen2/gateway_client/client.py _literal on a name, where it returns None as the mutant does for every host: the name is connected to through its beforehand lookup"},
    # R15-2 (Astra's 2b-repair-15 review): the pairing must construct a client. This test builds one over a literal address, so it evaluates the constructor's changed guard (`self._real and not self._endpoint.literal`)
    # on its false branch, where no lookup is due; Astra traced it into the constructor on the baseline and the mutant, and the mutant's killers fail by assertion where it passes
    "2B15-construction-does-not-look-the-name-up": {"controls": ["test_gateway_exchange.NoExchangeResolvesAName.test_an_ip_literal_is_never_resolved"],
                                                    "why": "constructs a GatewayClient over an IP literal, so that gen2/gateway_client/client.py's changed guard (`self._real and not self._endpoint.literal`) is evaluated and false: no lookup is due for an "
                                                           "address, which the mutant, that makes none for a name either, leaves as it was; the client then exchanges and reads its reply"},
    # task 2b-repair-17: a mutant that takes the ownership decoration off a method changes a line that runs once, at import, which no traced test executes; the accepted path through the
    # decorated definition is its own call, alone, which the control makes and which passes undecorated (nothing overlaps it). The failover mutant adds a `break` inside the handler of a failed
    # connect; the accepted path is the first address answering, where the handler is never entered and the loop's try completes
    **{mid: {"controls": ["test_gateway_ownership.OneOperationAtATime.test_control_the_same_operations_run_alone_and_a_search_then_a_grant_then_a_resolve_follow_each_other"],
             "why": f"calls {what} alone on a client (a search, a grant, a resolve, each through its exchange) with nothing running beside it: the accepted path through gen2/gateway_client/client.py's "
                    f"definition whose ownership decoration the mutant removes; undecorated it runs the same, nothing being there to refuse"}
       for mid, what in (("2B17-a-search-is-not-an-operation", "`search`"), ("2B17-a-grant-is-not-an-operation", "`grant`"), ("2B17-a-resolve-is-not-an-operation", "`resolve`"),
                         ("2B17-an-exchange-ignores-the-owner", "`_exchange`"))},
    "2B17-failover-stops-at-the-first-address": {"controls": ["test_gateway_ownership.ConnectionLifetimes.test_control_the_first_address_answering_leaves_the_others_untried"],
                                                 "why": "connects to a first address that answers, so gen2/gateway_client/client.py _connect's handler of a failed connect, where the mutant adds its `break`, is never entered "
                                                        "and the loop's try completes: the path on which no handler runs, which the mutant leaves as it was"},
    # task 2b-repair-18 (Astra's R17-1): the controls the brief names, chosen by hand over the traced first choice (a literal grant under a hostile environment, which reaches the changed lines but shows
    # nothing of what the mutant changes): the ordinary name that withdraws and sends nothing, the ordinary literal that still connects, the move to B, and the admitted address connected to whatever
    # host the request names. Each passes under its mutant: the mutants differ from the code only for a request host urllib decodes into an address, which none of these controls has
    "2B18-connect-reads-the-request-host-as-an-address": {
        "controls": ["test_gateway_routes.DirectHttpOnly.test_control_the_admitted_address_is_connected_to_whatever_host_the_request_names",
                     "test_gateway_ownership.TheOriginIsTheOnlyAuthority.test_control_an_ordinary_literal_still_connects_after_the_gateway_at_it_is_replaced"],
        "why": "connects through gen2/gateway_client/client.py _connect's changed loop on its accepted path: an address is admitted, and the request names a name, a literal or an encoded literal, whose "
               "reading as an address (the mutant's `_literal` of the request host) is the admitted address itself or nothing; the connection is made and the reply read. The ordinary literal "
               "endpoint, replaced by another listener at its address, is still connected to, as the contract authorizes"},
    "2B18-the-r17-1-reading-is-restored": {
        "controls": ["test_gateway_ownership.TheOriginIsTheOnlyAuthority.test_control_an_ordinary_name_withdraws_and_sends_nothing_and_the_move_to_b_works",
                     "test_gateway_ownership.TheOriginIsTheOnlyAuthority.test_control_an_ordinary_literal_still_connects_after_the_gateway_at_it_is_replaced"],
        "why": "runs Astra's stop/fail/NXDOMAIN/rebind sequence over an ordinary name, which the mutant treats as the code does (a name is no address, withdrawn it admits none and sends nothing, and the "
               "owner's lookup of it at B is then connected to), and over an ordinary literal, which is its own admitted address: through the changed validation and connect lines, on their accepted path"},
    "2B18-a-percent-encoded-host-is-a-name": {
        "controls": ["test_gateway_routes.TheEndpointForms.test_the_forms_that_are_accepted_are_one_canonical_origin_that_urllib_and_the_owner_read_alike"],
        "why": "constructs a client for each accepted form through the changed host pattern and label rule (names with hyphens, digits and a maximum length, literals of both families), none of which has a "
               "percent sign, which is all the mutant adds: each still comes out as its canonical origin"},
    # task 2b-repair-13b (Astra's 2b-repair-12 timing ruling): the start-grace killer holds the order in which the identity appears; the
    # accepted case, a start whose identity is recorded before recovery, is the normal-start control written beside it
    "1C-sup-no-start-grace": {"controls": ["test_supervisor_lifecycle.ResearchPassLifecycleTest.test_control_a_start_that_has_recorded_its_identity_at_recovery_is_found_running"],
                              "why": "executes gen2/supervisor/supervisor.py _unknown's changed grant of the start grace on its accepted path: the launcher's "
                                     "identity is recorded before the restarted supervisor first looks, so the guard before the grace is false and the "
                                     "supervisor finds it running and never waits; the mutant, which gives the grace nothing, leaves that unchanged"},
    # task 2a's expansion: only the killer takes the accepted rejection in the trace; the accepted rejection alone was written as a test
    # of its own, added after the trace
    "2A-rework-stale": {"controls": ["test_router_workflow.ScopeDecisionTest.test_a_rejection_of_the_current_report_reworks_it"],
                        "why": "executes gen2/router/service.py _rework's changed line (the newest-report check) on its accepted path, a rejection of "
                               "the topic's newest report, and asserts the move back to scoping: the mutant, which drops only that check, keeps it"},
    # the changed statement is the rework's move itself, under no guard of its own: every accepted rejection asserts or relies on it
    "2A-rework-none": {"controls": [],
                       "why": "the changed statement is the rework's queue move itself (gen2/router/service.py _rework's return), reached only by a "
                              "rejection of the topic's newest report, whose one effect is that move: no accepted path through it can pass under a "
                              "mutant that drops it, so there is no alternative to pair"},
    # task 2a: every traced creation is of a topic outside fleet-a, which the mutant (a fixed fleet-a) breaks; the accepted creation of a
    # fleet-a topic was written as a test of its own, added after the trace
    "2A-topic-fleet-fixed": {"controls": ["test_router_workflow.TopicTest.test_each_topic_takes_its_own_ids_fleet"],
                             "why": "executes gen2/router/scheduling.py's queue insert (the changed fleet_id) for fleet-a:t3, whose fleet the mutant "
                                    "also names, and asserts the row: the mutant leaves that creation working"},
    # task 1f-repair: only the killers reach claude_declared in the trace; its accepted case with no expiresAt was split out, added after the trace
    "1F-prb-claude-milliseconds-as-seconds": {
        "controls": ["test_capability_probe.DeclaredExpiryTest.test_a_claude_credential_stating_no_expiry_declares_none"],
        "why": "executes gen2/supervisor/probe.py claude_declared's changed line on its accepted path for a credential stating no expiresAt "
               "(the conditional's else: the changed conversion itself is evaluated only by the killers) and asserts it declares no expiry "
               "and notes the refresh token"},
    # task 1f: only the killer replays a recorded probe in the traced suite; the accepted replay is split out into a test of its own
    "1F-caps-replay-unchecked": {"controls": ["test_capability_probe.ProbeRecordTest.test_a_lost_reply_is_answered_again_from_the_record"],
                                 "why": "the identical observation's replay is the accepted path through the conflict check (capabilities.py): "
                                        "the control replays one and checks nothing was written"},
    # connection.sql: every store connection applies it; the control's accepted writes fire triggers under it
    "A1-recursive-triggers-off": {"controls": ["test_store_ddl_invocations.LeaseFencingTest.test_release_is_write_once"],
                                  "why": "applies the connection contract and makes accepted writes that fire triggers under it"},
    **{mid: {"controls": [_IMPORTER_GRAPH[0]], "why": _IMPORTER_GRAPH[1]}
       for mid in ("RA7-real-graph-posix", "RA7-real-graph-nt", "A8-real-graph-posixsubprocess", "A8-real-graph-imaplib",
                   "1B-real-graph-writers-widened", "1B-real-graph-primitives-dropped")},
    # the importer's test also checks _sqlite3 (it failed under this mutant): the router's instead
    **{mid: {"controls": [_ROUTER_GRAPH[0]], "why": _ROUTER_GRAPH[1]} for mid in ("IMP-graph-store-granted", "IMP-graph-sqlite-granted",
                                                                                "A8-real-graph-sqlite3")},
    # common.schema.json has no fixtures of its own: a schema that takes its connector types from it
    "0D-connector-types-open-to-a-store-name": {
        "controls": ["test_schema_counterfactuals.FixtureCounterfactualTest.test_an_extension_connector_without_its_implementation_is_refused"],
        "why": "re-checks the schema tree with the mutant in place and declares a valid export-manifest fixture, whose connectors take "
               "their type from common.schema.json"},
    # only the killer executes the changed line; its accepted case was split out as its own test (task 1c-repair-2)
    "0CR-checker-errors-collapsed-to-a-set": {
        "controls": ["test_check_ddl_rules.SchemaFixtureRuleTest.test_two_rules_reporting_one_signature_pass_when_both_are_declared"],
        "why": "executes tools/check_gen2_schemas.py line 268 on the accepted path: the two errors declared twice pass"},
    # only the killer executes the changed lines, and it asserts its paired case before the one the mutant fails
    "RA7-walrus-binds-in-comprehension": {
        "controls": [], "in_killer": ["test_check_boundaries.BoundaryCheckerTest.test_scope_resolution_witnesses"],
        "why": "the mutant over-reports (the walrus case, the killer's positive control, becomes a violation); the killer asserts its "
               "paired negatives (the class-body and global cases reported) before that; no other test reaches these lines"},
    # only killers reach the commit budget's guard in the trace; the accepted case its killer holds in a subTest (the pause
    # lifting within budget) was split out as a test of its own, added after the trace (task 1c-repair-3)
    "1C-sup-commit-budget-unbounded": {
        "controls": ["test_supervisor_lifecycle.ResearchPassLifecycleTest.test_a_commit_refused_while_paused_commits_once_the_pause_lifts"],
        "why": "executes gen2/supervisor/supervisor.py's commit-budget guard (if self._spend(job, journal, \"commit\")) on its accepted path: "
               "the commit refused once while paused is resent within budget and commits"},
    # task 1e: every traced status read is of a world with ended work, which the mutant lists (and status then fails for); the
    # accepted case — live work only — was written as a test of its own, added after the trace
    "1E-rstatus-ended-invocations": {
        "controls": ["test_operator_status.LiveWorkTest.test_live_work_alone_is_listed"],
        "why": "evaluates gen2/router/status.py's live-work filter (if i[\"state\"] in LIVE) on a running pass, the case it admits, in a "
               "world with no ended work, and asserts the pass is listed waiting for its end"},
    # task 1e: every traced in-process CLI call but health sends a token; health without one was written as a test of its own
    "1E-cli-token-unsent": {
        "controls": ["test_operator_restart.CliTest.test_health_is_asked_without_a_token"],
        "why": "evaluates gen2/app/cli.py's `if token:` with no token (no header sent, the branch the mutant always takes) and asserts "
               "the unauthenticated health route still answers"},
    # task 1e: only the killer replays a brief closure; its accepted case was split out as a test of its own, added after the trace
    "1E-close-conflict-replayed": {
        "controls": ["test_operator_commands.BriefCommandTest.test_the_identical_closure_replays"],
        "why": "passes gen2/router/amendments.py's closure-conflict guard (if (row[\"status\"], row[\"closed_by\"], row[\"close_reason\"]) != ...) "
               "without taking it: the identical closure by the same operator replays and writes nothing"},
    # task 1c-repair-4 (the C4 re-check): the traced candidates reach the supersession loop's header only through a fixture's
    # first approval; the accepted case it admits was split out of the killer as a test of its own, added after the trace
    "1B-approval-without-supersession": {
        "controls": ["test_router_ops.OperatorDecisionTest.test_a_first_contract_approval_supersedes_nothing"],
        "why": "evaluates gen2/router/service.py's supersession guard (if previous is not None: the approved revision, task 1d) with none "
               "approved, runs none of its body, and asserts the alternative it admits: nothing superseded, exactly this revision approved, "
               "the topic queued"},
    # task 1c-repair-4 (the C4 re-check): every traced candidate (143) needs an approval, which this over-restricting mutant
    # refuses; the one alternative the trigger's own WHEN admits without an approval was written as a test of its own
    "RA3R-approval-refused-too": {
        "controls": ["test_store_ddl_contracts.ContractGovernanceTest.test_an_update_recording_no_approval_pointer_passes_its_guard"],
        "why": "a statement that succeeds enters trigger contract_approval_pointer_set_by_approval with its WHEN false on its own "
               "NEW-pointer conjunct (a draft's pointer written as NULL: nothing recorded), the alternative it admits without the removed "
               "approved-status exemption; no write path makes that statement. The other alternative, restating a pointer already "
               "recorded, needs an approval first, which the mutant refuses: all 143 traced candidates fail under it"},
    # task 1c-repair-4 (the C4 re-check): the changed return is governed by an early return, which the traced rule does not
    # treat as a guard (it credits an if only for what its branch holds); read, it is the guard deciding whether a replay is sent
    "1C-child-router-replay-reads-committed": {
        "controls": ["test_router_commit.FencingTest.test_positive_control"],
        "why": "a first commit passes gen2/router/service.py's replay guard the other way (line 609: no receipt for the operation id, so "
               "line 610 returns and the commit proceeds; line 613 is never reached) and asserts the status the mutant confuses: a new "
               "commit is reported committed. Paired by hand: the guard is an early return rather than a branch holding line 613"},
    # a race, not a removed guard: which test notices it depends on timing
    "1C-jobs-probe-takes-the-lock": {
        "controls": [],
        "why": "the changed line is the probe itself, under no guard of its own, and no execution of it answers as the original does: a "
               "free lock reads as held (F_OFD_SETLK hands back the F_WRLCK it was given), a held one raises EAGAIN, and taking the lock "
               "can make a launcher locking at that moment give up. So there is no accepted alternative through it (re-checked in task "
               "1c-repair-4 against Astra 1c re-review 3, BLOCK 2's standard); a test through it passes only where its answer does not "
               "matter and no launcher is locking just then, which is timing: of 13 candidates run under it, one passed in one run and "
               "failed the next; none passes dependably, so none is paired"},
    # task 1d: each guard's accepted case, which only its killer took in the trace, split out as a test of its own and paired by hand
    **{mid: {"controls": [control], "why": why} for mid, control, why in (
        ("1D-registry-revocation-conflict-replayed", "test_router_registries.QualificationRecordTest.test_the_same_revocation_again_replays",
         "passes gen2/router/registries.py's revocation-conflict guard (line 180) without taking it: the identical revocation replays"),
        ("1D-amend-brief-conflict-replayed", "test_router_amendments.BriefVersionTest.test_the_same_version_again_replays",
         "passes gen2/router/amendments.py's brief-version conflict guard (line 154) without taking it: the identical version replays"),
        ("1D-amend-amendment-conflict-replayed", "test_router_amendments.AmendmentProposalTest.test_the_same_amendment_again_replays",
         "passes gen2/router/amendments.py's amendment-conflict guard (line 196) without taking it: the identical revision replays"),
        ("1D-amend-reservations-left-open", "test_router_scheduling.ReservationTest.test_an_amendment_leaves_a_closed_reservation_as_it_was",
         "executes gen2/router/amendments.py line 285 (the impact's closing guard) for a reservation already closed and passes it over; "
         "asserts only that the closed reservation is kept as it was"),
        ("1D-sched-requeue-conflict-replayed", "test_router_scheduling.RequeueTest.test_the_same_requeue_again_replays",
         "passes gen2/router/scheduling.py's re-queue conflict guard (line 103) without taking it: the identical re-queue replays"),
        ("1D-sched-reservation-conflict-replayed", "test_router_scheduling.ReservationTest.test_the_same_reservation_again_replays",
         "passes gen2/router/scheduling.py's reservation-conflict guard (line 159) without taking it: the identical reservation replays"),
        ("1D-sched-reservation-reopened", "test_router_scheduling.ReservationTest.test_an_exhausted_reservation_is_closed_when_the_next_opens",
         "passes gen2/router/scheduling.py's open-reservation guard (line 172) without taking it: the open one has no units left, so it closes "
         "and the next opens"),
        ("1D-sched-draw-below-threshold", "test_router_scheduling.ReservationTest.test_an_auto_promotion_draw_inside_a_critical_facet",
         "passes gen2/router/scheduling.py's threshold guard (line 193) without taking it: a facet rated critical meets the threshold"),
        ("1D-sched-review-conflict-replayed", "test_router_scheduling.SignalQueueTest.test_the_same_review_again_replays",
         "passes gen2/router/scheduling.py's review-conflict guard (line 201) without taking it: the identical review replays"),
        ("1D-sched-policy-budget-unbounded", "test_router_scheduling.RequeueTest.test_policy_requeues_within_a_larger_budget",
         "passes gen2/router/scheduling.py's budget guard (if policy is None or attempt - 1 > attempts) without taking it, a first retry "
         "within a budget of two, and is re-queued"),
        ("1D-sched-policy-budget-short", "test_router_scheduling.RequeueTest.test_policy_requeues_within_a_larger_budget",
         "passes the same guard clear of its boundary (one retry spent of two), where > and >= agree"),
        ("1D-sched-exhaustion-without-hold", "test_router_scheduling.RequeueTest.test_policy_past_its_budget_requeues_nothing",
         "executes the exhausted branch, the changed hold insert included, and asserts what the branch does besides the hold: the "
         "answer is exhausted and nothing is re-queued"),
        ("1D-sched-lane-gate-never", "test_router_scheduling.ReservationTest.test_a_reservation_is_sized_by_the_bundle_and_drawn_within_its_units",
         "passes gen2/router/scheduling.py's lane guard with each lane's last work absent or live, for claims naming no retry"),
    )},
    # task 1d: no accepted path exists through these changed statements
    "1D-registry-revocation-not-recorded": {
        "controls": [],
        "why": "the changed statement is the revocation's write itself (gen2/router/registries.py, the qualifications update), under no guard "
               "of its own: its only effect is the write, so every test through it asserts or relies on the recorded revocation (a replay, "
               "the refusal it causes, the restart that keeps it) and none can pass under a mutant that drops it"},
    "1D-amend-amendment-without-facets": {
        "controls": [],
        "why": "the changed loop writes an amendment's facet rows; contract-v2 requires facets and the DDL admits an obligation row only when "
               "the facets it tags are rows of its revision, so no amendment is recorded without them: every proposal through the loop "
               "fails under the mutant (probed: 0 of 12 candidates pass), and the loop has no accepted alternative to pair"},
    "TO-differences-ignored": {
        "controls": [], "in_killer": ["test_trigger_order_tool.TriggerOrderToolTest.test_outcomes_must_be_green_and_identical"],
        "why": "the killer asserts the accepted case (identical green outcomes: no problem) before the refusals; " + _ORDER},
    "TO-original-failures-ignored": {
        "controls": [], "in_killer": ["test_trigger_order_tool.TriggerOrderToolTest.test_outcomes_must_be_green_and_identical"],
        "why": "the killer asserts the accepted case (identical green outcomes: no problem) before the refusals; " + _ORDER},
    # task 1e-repair: recover_incident's COMMANDS entry; no recovery request passes through it the same way under both versions
    "1E-svc-recover-requester-from-request": {
        "controls": ["test_operator_mcp.McpTest.test_mcp_needs_a_token_and_lists_only_the_roles_tools"],
        "why": "reads the COMMANDS entry the mutant changes on its accepted path — tools/list's role filter lists recover_incident for an "
               "operator — and asserts the operator's tools; the mutant changes only the field supplied from the principal, and no recovery "
               "request can be a control: the surface refuses a body naming requested_by, and without it the mutant's request is refused "
               "(probed: 0 of 9 candidates pass)"},
    # task 2q-a: five branches that, in the traced run, only a mutant's own killer entered; each got a test of its own, added after the
    # trace, that takes the accepted path through the changed line (the mutant leaves it passing)
    "2Q-collab-module-attribute-base": {
        "controls": ["test_metrics_measure.CollaborationTest.test_an_attribute_base_that_is_not_a_project_class_is_no_family"],
        "why": "evaluates tools/gen2_metrics.py project_bases' changed elif for a base named through a module attribute (abc.ABC) that is "
               "no project class: false, on the accepted path to no family; the mutant's `False and ...` leaves it so"},
    "2Q-exempt-continuation-lost": {
        "controls": ["test_metrics_ratchet.ExemptionTest.test_a_wrapped_reason_is_one_value_too"],
        "why": "runs tools/gen2_metrics.py parse_entries' changed continuation branch on a reason wrapped over two lines, accepted either "
               "way: the first line alone is a reason, so the exemption still holds under the mutant"},
    "2Q-ratchet-selfcall-growth-ignored": {
        "controls": ["test_metrics_ratchet.CollaborationTest.test_unchanged_self_calls_are_no_regression"],
        "why": "evaluates tools/gen2_metrics.py compare's changed guard (count > was) for a baselined pair whose count is unchanged: false, on "
               "the accepted path; the mutant's `if False` leaves it so"},
    "2Q-ratchet-cross-service-ignored": {
        "controls": ["test_metrics_ratchet.BaselinedCrossServiceTest.test_a_baselined_import_between_the_services_stays_allowed"],
        "why": "evaluates tools/gen2_metrics.py compare's changed guard (edge not in the baseline) for an import between the services that "
               "the baseline already holds: false, on the accepted path; the mutant's `if False` leaves it so"},
    "2Q-debt-continuation-lost": {
        "controls": ["test_debt_register.EntryTest.test_a_wrapped_what_continues_too"],
        "why": "runs tools/check_gen2_debt.py parse_register's changed continuation branch on a `what` wrapped over two lines, accepted "
               "either way: the first line alone is a description, so the entry still passes under the mutant"},
    "2Q-loc-word-is-substring": {
        "controls": ["test_locators.SymbolLocatorTest.test_a_name_in_a_markdown_file_is_found_as_a_word"],
        "why": "runs tools/check_gen2_locators.py defines' changed word search on a markdown file for a whole word it contains: found "
               "under the mutant's substring test too"},
    # task 2q-a-repair: every traced candidate resolves a base through a submodule (a package's attribute), which this mutant breaks; the control
    # written for it takes the line's other branch alone
    "2QR-collab-submodule-not-an-attribute": {
        "controls": ["test_metrics_collaboration.UnresolvedBaseTest.test_control_a_name_a_measured_module_does_not_define_is_unresolved_with_that_reason"],
        "why": "evaluates tools/gen2_metrics.py Classes.member's changed return for a name a measured module defines nowhere, so no submodule is looked up "
               "either: unresolved with the reason `defines no`, which the mutant's constant return gives too"},
    "2Q-rebaseline-crossing-offenders-dropped": {
        "controls": ["test_metrics_ratchet.ExemptedRegressionsAreNeverRecordedTest.test_a_new_function_over_the_threshold"],
        "why": "evaluates tools/gen2_metrics.py tighten's changed elif for a new offender that an exemption covers (and so was an offender "
               "under the old thresholds too): false, so it is not recorded, and the mutant's `elif False` records it no more"},
    # task 1e-repair: the server's handle_error override runs only for a failed connection
    "1E-engine-connection-fault-traceback": {
        "controls": [],
        "why": "the mutant renames the server's handle_error override (gen2/app/engine.py _Server), which socketserver calls only when a "
               "connection has failed outside the service: no answered request passes through it, every call is a fault, and its one line "
               "and empty stderr are what its killer asserts. There is no accepted alternative through it to pair"},
    # task 1e-repair: the startup leak runs in the engine's own process, which only the replacement tests start (both its killers)
    "1E-engine-startup-leak": {
        "controls": [], "in_killer": ["test_operator_restart.ReplacementTest.test_a_replacement_process_serves_the_same_principals_permissions_and_state"],
        "why": "the changed line (the credentials read at the engine's start, gen2/app/engine.py main) runs only in the engine processes the "
               "replacement tests start; the killer's accepted case — three engine processes start under the mounted secrets, serve health, "
               "status and commands, keep principals, pins and the confirmed brief, refuse the rotated token — runs under the mutant and is "
               "asserted before the secrecy check it fails, every engine's output collected first"},
    # task 1e-repair-2: the review's startup-stdout mutant, in the refusal handler of the engine's start
    "1E-engine-startup-stdout-leak": {
        "controls": [], "in_killer": ["test_operator_restart.ReplacementTest.test_an_engine_without_usable_secrets_does_not_start"],
        "why": "the changed line (the refusal handler of gen2/app/engine.py main) runs only in engine processes that refuse to start, which "
               "only this test starts; its accepted case — each of the three refused starts exits 1 printing no address (in subTests), and "
               "all three outputs are collected, none empty, each with the engine's fixed refusal diagnostic — runs under the mutant and is "
               "asserted before the secrecy check it fails, the stdout line read at each start collected with the rest (Astra 1e-repair "
               "re-review finding 3)"},
}
# A killer the trace shows entering its trigger in a statement that succeeds, where no other test does, is credited
# with its own accepted case only once read: that statement runs before the refusal the mutant fails (or the
# refusals sit in subTests, which go on), so it also runs under the mutant.
READ_IN_KILLER = {
    "test_store_ddl_export.ExportOutboxTest.test_connector_watermark_never_regresses":
        "the idempotent retry UPDATE runs before the refusals, which sit in subTests; an advancing UPDATE ends the test",
    "test_store_ddl_evidence.ObservationTest.test_one_current_capability_fact_supersede_to_transition":
        "the documented supersession UPDATE (cf-1 -> cf-2) runs before the refusals",
    "test_store_ddl_evidence.ObservationTest.test_supersession_goes_on_past_a_late_snapshot":
        "the accepted late insert (cf-2 behind cf-3) and the documented supersession (cf-3 -> cf-5) run before the refusals",
    "test_store_ddl_invocations.OrdinalAndTriggerTest.test_trigger_identity_unique_and_handled_is_final":
        "the UPDATE marking the trigger handled runs before the refusals",
    "test_store_history.RecordIdentityTest.test_work_identity_is_immutable":
        "the refusals sit in subTests, which go on; the accepted study_group_id UPDATE then runs",
}
# For the supervisor's own files (task 1c, the review's examples): the canonical accepted-path tests, taken first
# where they qualify (they take the mutated path, passed in the trace, are not the mutant's killers).
_CLEAN_END = "test_supervisor_lifecycle.ResearchPassLifecycleTest.test_a_clean_end_commits_the_result_with_its_execution_record"
PREFERRED = {
    "gen2/supervisor/spool.py": ("test_supervisor_spool.CollectTest.test_a_regular_file_is_staged_as_found",
                                 "test_supervisor_spool.StageTest.test_bytes_are_staged_once_under_their_hash_read_only_for_one_topic", _CLEAN_END),
    "gen2/supervisor/supervisor.py": (_CLEAN_END, "test_supervisor_delegates.ResearchPassParentTest.test_a_parent_that_completes",
                                      "test_supervisor_crash.DiscoveryCrashTest.test_crash_after_launch_intent_before_any_start",
                                      "test_supervisor_crash.DiscoveryCrashTest.test_crash_after_the_identity_is_recorded"),
    "gen2/supervisor/jobs.py": ("test_supervisor_jobs.TerminateTest.test_the_whole_group_is_ended_and_confirmed_gone", _CLEAN_END),
    "gen2/supervisor/jobshim.py": ("test_supervisor_jobs.LookupTest.test_the_launcher_records_how_its_executor_ended", _CLEAN_END),
}
# A test whose name says it checks a refusal: ranked after the others, which state what is accepted.
NEGATIVE = re.compile(r"refuse|reject|_not_|_never_|cannot|_no_|fail|invalid|wrong|conflict|missing|without|stale|lost|violat|denied|unknown|"
                      r"escape|bypass|forged|foreign|ignored|outlive|exceed|_only_")

HELPER = r'''
import json, os, sys, time
def _watch(path, rel, out, at, shift):
    mon = sys.monitoring
    state = getattr(sys, "_gen2_controls_trace", None)
    if state is None:
        state = sys._gen2_controls_trace = {"files": {}, "fd": os.open(out, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600), "last": {}, "seen": set()}
        def emit(key, record):
            if key not in state["seen"]:  # each line and each arc once per process: its time places it in a test's window
                state["seen"].add(key)
                os.write(state["fd"], (json.dumps({"t": time.time_ns(), **record}) + "\n").encode())
        def on_line(code, line):
            known = state["files"].get(code.co_filename)
            if known is None:
                return mon.DISABLE
            rel, at, shift = known
            line = line - shift if line > at else line
            frame = id(sys._getframe(1))
            prev, state["last"][frame] = state["last"].get(frame), line
            emit((rel, line), {"rel": rel, "line": line})
            if prev is not None:
                emit((rel, prev, line), {"rel": rel, "arc": [prev, line]})
        def on_start(code, offset):
            if code.co_filename not in state["files"]:
                return mon.DISABLE
            state["last"].pop(id(sys._getframe(1)), None)
        def on_return(code, offset, value):
            known = state["files"].get(code.co_filename)
            if known is None:
                return mon.DISABLE
            prev = state["last"].pop(id(sys._getframe(1)), None)
            if prev is not None:
                emit((known[0], prev, -1), {"rel": known[0], "arc": [prev, -1]})
        try:
            mon.use_tool_id(4, "gen2-controls-child")
        except ValueError:
            pass
        def on_raise(code, offset, exc):
            known = state["files"].get(code.co_filename)
            if known is not None and type(exc).__name__ not in FLOW:
                os.write(state["fd"], (json.dumps({"t": time.time_ns(), "rel": known[0], "raise": 1}) + "\n").encode())
        events = mon.events
        mon.register_callback(4, events.LINE, on_line)
        mon.register_callback(4, events.RAISE, on_raise)
        mon.register_callback(4, events.PY_START, on_start)
        mon.register_callback(4, events.PY_RETURN, on_return)
        mon.set_events(4, events.LINE | events.RAISE | events.PY_START | events.PY_RETURN)
    state["files"][path] = (rel, at, shift)
_watch(*WATCH)
'''


# -- trace ---------------------------------------------------------------------------------------
def _inventory():
    sys.path[:0] = [str(ROOT / "tools"), str(TESTS), str(ROOT)]
    import gen2_mutations  # noqa: E402
    return gen2_mutations


def _traced_copy(text: str, path: Path, rel: str, helper: Path, out: Path) -> str:
    """The file with a prologue on its last docstring/__future__ line (so no
    line moves) that runs the tracing helper for this file."""
    body, line = ast.parse(text).body, 0
    for node in body:
        docstring = node is body[0] and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        if docstring or (isinstance(node, ast.ImportFrom) and node.module == "__future__"):
            line = node.end_lineno
        else:
            break
    call = (f'__import__("runpy").run_path({str(helper)!r}, init_globals={{"WATCH": ({str(path)!r}, {rel!r}, {str(out)!r}, '
            f'{line if line else 0}, {0 if line else 1}), "FLOW": {sorted(FLOW)!r}}})')
    lines = text.splitlines(keepends=True)
    if not line:
        return call + "\n" + text
    end = lines[line - 1].rstrip("\n")
    lines[line - 1] = end + "; " + call + "\n"
    return "".join(lines)


class _Recorder(unittest.TestResult):
    def __init__(self, windows: dict, outcomes: dict, current: dict) -> None:
        super().__init__()
        self.windows, self.outcomes, self.current = windows, outcomes, current

    def startTest(self, test) -> None:  # noqa: N802
        self.current["test"] = test.id()
        self.windows[test.id()] = [time.time_ns(), None]
        self.outcomes[test.id()] = "pass"
        sys.monitoring.restart_events()
        super().startTest(test)

    def stopTest(self, test) -> None:  # noqa: N802
        self.windows[test.id()][1] = time.time_ns()
        self.current["test"] = None
        super().stopTest(test)

    def addFailure(self, test, err) -> None:  # noqa: N802
        self.outcomes[test.id()] = "fail"

    def addError(self, test, err) -> None:  # noqa: N802
        self.outcomes[test.id()] = "error"

    def addSkip(self, test, reason) -> None:  # noqa: N802
        self.outcomes[test.id()] = "skip"

    def addSubTest(self, test, subtest, err) -> None:  # noqa: N802
        if err is not None:
            self.outcomes[test.id()] = "fail"


def _ddl_instrumented(ddl: str) -> str:
    """Every trigger records that it was entered; every table records each
    row written. Both through functions _connect registers."""
    def enter(match):
        name, header = match.group(1), match.group(2)
        if "\nWHEN " in header:
            header = header.replace("\nWHEN ", f"\nWHEN _gen2_entered('{name}') AND (", 1) + "\n)"  # its own line: the WHEN may end in a comment
        else:
            header += f"\nWHEN _gen2_entered('{name}')"
        return f"CREATE TRIGGER {name}{header}\nBEGIN"
    out = re.sub(r"CREATE TRIGGER (\w+)(.*?)\nBEGIN", enter, ddl, flags=re.DOTALL)
    tables = re.findall(r"^CREATE TABLE (\w+) \(", ddl, flags=re.MULTILINE)
    for table in tables:
        out += (f"\nCREATE TRIGGER _gen2_i_{table} AFTER INSERT ON {table} BEGIN SELECT _gen2_wrote('{table}', 'insert'); END;"
                f"\nCREATE TRIGGER _gen2_u_{table} AFTER UPDATE ON {table} BEGIN SELECT _gen2_wrote('{table}', 'update'); END;\n")
    return out


def _sqlite_recording(current: dict, found: dict):
    """sqlite3.connect, recording (per test) what statements that succeed
    enter and write; a failing statement's records are dropped."""
    real = sqlite3.connect

    class Cursor(sqlite3.Cursor):
        def _run(self, method, *args, **kwargs):
            conn = self.connection
            conn._pending = []
            try:
                result = getattr(super(), method)(*args, **kwargs)
            except BaseException:
                conn._pending = []
                if current["test"] is not None:
                    found[current["test"]].add(("failed", str(len([k for k in found[current["test"]] if k[0] == "failed"]))))
                raise
            conn._flush()
            return result

        def execute(self, *a, **k):
            return self._run("execute", *a, **k)

        def executemany(self, *a, **k):
            return self._run("executemany", *a, **k)

        def executescript(self, *a, **k):
            return self._run("executescript", *a, **k)

    class Connection(sqlite3.Connection):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._pending = []
            self.create_function("_gen2_entered", 1, lambda name: self._pending.append(("trigger", name)) or 1)
            self.create_function("_gen2_wrote", 2, lambda table, op: self._pending.append((op, table)) or 1)

        def _flush(self) -> None:
            test = current["test"]
            for kind, name in self._pending:
                if test is not None:
                    found[test].add((kind, name))
            self._pending = []

        def cursor(self, factory=Cursor):
            return super().cursor(factory)

        def execute(self, *a, **k):
            return self.cursor().execute(*a, **k)

        def executemany(self, *a, **k):
            return self.cursor().executemany(*a, **k)

        def executescript(self, *a, **k):
            return self.cursor().executescript(*a, **k)

    def connect(*args, **kwargs):
        kwargs.setdefault("factory", Connection)
        return real(*args, **kwargs)
    return connect


def trace(out: Path) -> int:
    g = _inventory()
    tmp = Path(tempfile.mkdtemp(prefix="gen2-controls-"))
    helper, records = tmp / "helper.py", tmp / "lines.jsonl"
    helper.write_text(HELPER, encoding="utf-8")
    py_targets = sorted(t for t in g.FILE_TARGETS if t.endswith(".py"))
    # children: the child tree (gen2/ modules and scripts) and the path-handed tool copies carry the prologue
    tree = tmp / "tree"
    shutil.copytree(ROOT / "gen2", tree / "gen2", ignore=shutil.ignore_patterns("__pycache__"))
    copies: dict[str, str] = {}
    for rel in py_targets:
        how = g.FILE_TARGETS[rel]
        dest = tree / rel if how[0] in ("module", "disk") else tmp / "attr" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_traced_copy((ROOT / rel).read_text(encoding="utf-8"), dest, rel, helper, records), encoding="utf-8")
        copies[str(dest)] = rel
    os.environ["GEN2_CHILD_ROOT"] = str(tree)
    os.environ["GEN2_TEST_EVIDENCE"] = "off"
    sys.path[:0] = [str(TESTS), str(ROOT)]
    for rel in py_targets:
        how = g.FILE_TARGETS[rel]
        if how[0] == "attr":
            setattr(importlib.import_module(how[1]), how[2], tmp / "attr" / rel)
    # this process: the repository's files (and a path-handed copy run in here), by sys.monitoring
    files = {str(ROOT / rel): rel for rel in py_targets}
    files.update(copies)
    current: dict = {"test": None}
    lines: dict[str, set] = defaultdict(set)
    arcs: dict[str, set] = defaultdict(set)  # per test, (file, line, next line) within one frame; next -1: it returned from that line
    last: dict[int, int] = {}  # a target frame's last line, by frame id (dropped when a frame starts or returns)
    mon = sys.monitoring

    def on_line(code, line):
        rel = files.get(code.co_filename)
        if rel is None:
            return mon.DISABLE
        frame = id(sys._getframe(1))  # the monitored frame: the callback runs on top of it
        prev, last[frame] = last.get(frame), line
        if current["test"] is not None:
            lines[current["test"]].add((rel, line))
            if prev is not None:
                arcs[current["test"]].add((rel, prev, line))

    def on_start(code, offset):
        if code.co_filename not in files:
            return mon.DISABLE
        last.pop(id(sys._getframe(1)), None)

    def on_return(code, offset, value):
        rel = files.get(code.co_filename)
        if rel is None:
            return mon.DISABLE
        prev = last.pop(id(sys._getframe(1)), None)
        if prev is not None and current["test"] is not None:
            arcs[current["test"]].add((rel, prev, -1))
    raises: dict[str, dict] = defaultdict(lambda: defaultdict(int))  # per test, exceptions raised inside each target file

    def on_raise(code, offset, exc):
        rel = files.get(code.co_filename)
        if rel is not None and current["test"] is not None and type(exc).__name__ not in FLOW:
            raises[current["test"]][rel] += 1
    mon.use_tool_id(TOOL_ID, "gen2-controls")
    events = mon.events
    mon.register_callback(TOOL_ID, events.LINE, on_line)
    mon.register_callback(TOOL_ID, events.RAISE, on_raise)
    mon.register_callback(TOOL_ID, events.PY_START, on_start)
    mon.register_callback(TOOL_ID, events.PY_RETURN, on_return)
    mon.set_events(TOOL_ID, events.LINE | events.RAISE | events.PY_START | events.PY_RETURN)
    windows, outcomes = {}, {}
    suite = unittest.defaultTestLoader.discover(str(TESTS), pattern="test_*.py")
    started = time.monotonic()
    result = _Recorder(windows, outcomes, current)
    suite.run(result)
    mon.set_events(TOOL_ID, 0)
    print(f"traced run: {len(outcomes)} tests, {time.monotonic() - started:.0f}s; not passing: "
          f"{sorted(t for t, o in outcomes.items() if o != 'pass')}", flush=True)
    # a child's lines, to the test whose window holds them
    spans = sorted((w[0], w[1], t) for t, w in windows.items() if w[1] is not None)
    starts = [span[0] for span in spans]
    if records.exists():
        for raw in records.read_text(encoding="utf-8").splitlines():
            rec = json.loads(raw)
            at = bisect.bisect_right(starts, rec["t"]) - 1
            if at < 0 or rec["t"] > spans[at][1]:
                continue  # between tests
            test = spans[at][2]
            if "raise" in rec:
                raises[test][rec["rel"]] += 1
            elif "arc" in rec:
                arcs[test].add((rec["rel"], *rec["arc"]))
            else:
                lines[test].add((rec["rel"], rec["line"]))
    # the store suite again over the instrumented DDL: triggers entered and rows written by statements that succeed
    fx = importlib.import_module("gen2.tests.store_fixtures")
    ddl0 = fx.DDL_TEXT
    fx.DDL_TEXT = _ddl_instrumented(ddl0)
    found: dict[str, set] = defaultdict(set)
    sqlite3.connect = _sqlite_recording(current, found)
    store_outcomes: dict = {}
    g.load_suite().run(_Recorder({}, store_outcomes, current))
    fx.DDL_TEXT = ddl0
    print(f"store run (instrumented DDL): {len(store_outcomes)} tests; not passing: "
          f"{sorted(t for t, o in store_outcomes.items() if o != 'pass')}", flush=True)
    durations = {t: (w[1] - w[0]) / 1e9 for t, w in windows.items() if w[1] is not None}
    doc = {"outcomes": outcomes, "durations": durations, "store_outcomes": store_outcomes,
           "lines": {t: sorted([r, n] for r, n in s) for t, s in lines.items()},
           "arcs": {t: sorted([r, a, b] for r, a, b in s) for t, s in arcs.items()},
           "raises": {t: dict(d) for t, d in raises.items()},
           "sql": {t: sorted([k, n] for k, n in s) for t, s in found.items()}}
    out.write_text(json.dumps(doc), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"trace written: {out}")
    return 0


# -- choose --------------------------------------------------------------------------------------
def holder_users(holder: str) -> set[str]:
    """The test modules (names as the runner knows them) that import `holder`, a fixtures module that holds a path-handed tool's
    path: they read it at call time, so a mutant's path set there reaches them too. A test module that is itself the holder is
    not asked: its candidates are its own tests (the rule for a holder that is a test module)."""
    package, _, leaf = holder.rpartition(".")
    pattern = re.compile(rf"^\s*(?:from {re.escape(package)} import [^\n]*\b{re.escape(leaf)}\b|from {re.escape(holder)} import\b|import {re.escape(holder)}\b)",
                         re.MULTILINE)
    return {path.stem for path in sorted(TESTS.glob("test_*.py")) if pattern.search(path.read_text(encoding="utf-8"))}



def changed_lines(text: str, mutated: str) -> set[int]:
    """The lines of the repository file a mutant changes, by difflib over
    the whole file: each line it replaces or deletes, and for an insertion
    the line the inserted code runs before (the previous one at a blank).
    A line inside `old` that the mutant leaves as it was is not counted."""
    before, after = text.splitlines(), mutated.splitlines()
    out: set[int] = set()
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            out.update(range(i1 + 1, i2 + 1))
        elif tag == "insert":
            out.add(i1 + 1 if i1 < len(before) and before[i1].strip() else i1)
    return out


def _span(nodes) -> set[int]:
    return set().union(*(set(range(n.lineno, n.end_lineno + 1)) for n in nodes)) if nodes else set()


def _own(node) -> set[int]:
    """A statement's own lines: an if's or while's test, a for's target and
    iterable, a with's items, an except clause; a simple statement whole. A
    compound statement's body is its children's."""
    if isinstance(node, (ast.If, ast.While)):
        return set(range(node.test.lineno, node.test.end_lineno + 1))
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return set(range(node.lineno, node.iter.end_lineno + 1))
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return set(range(node.lineno, node.items[-1].context_expr.end_lineno + 1))
    if isinstance(node, ast.ExceptHandler):
        return set(range(node.lineno, (node.type.end_lineno if node.type else node.lineno) + 1))
    if isinstance(node, (ast.Try, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.lineno}
    return set(range(node.lineno, node.end_lineno + 1))


def requirements(text: str, changed: set[int]) -> list[tuple]:
    """What a traced run must show to take an accepted path through the
    code a mutant changes (module docstring, "What counts"); a control
    meets any one of them.
      ("line", lines, fallback)          it executed one of `lines`, the
                                         changed ones or a direct guard's
                                         test (or, where no traced run
                                         executes any of them — a line with
                                         no instruction of its own — one of
                                         `fallback`, the statement's first)
      ("pass", from_lines, lines, need)  it left one of from_lines, within
                                         one frame, for a line not among
                                         `lines` (or returned from it), and
                                         executed a changed line of the guard
                                         (`need`, where a traced run does)
    Inside a function each changed line belongs to the innermost statement
    whose own lines hold it. A changed refusal — a raise, or a call to a
    function of the file that ends by raising — is passed: the guard that
    directly governs it (the if or while whose branch holds it, the loop
    whose body does, or the try whose handler does) must be left without
    taking it; a changed if or while whose branch is a refusal likewise; any
    other changed statement, an if or while included, must be executed, or
    the guard directly holding it (the if or while whose branch holds it,
    the for loop whose body does) evaluated either way.
    Nothing encloses a guard in this: an outer branch reached is never
    evidence. Outside functions: a changed module or class assignment, the
    lines inside functions that read the names it binds; a changed statement
    of a module's own program, as it is."""
    tree = ast.parse(text)
    parent: dict = {}
    for node in ast.walk(tree):
        for field, value in ast.iter_fields(node):
            for child in value if isinstance(value, list) else ():
                if isinstance(child, ast.AST):
                    parent[child] = (node, field)
    bodies = []  # (first, last) line of each function body
    raising: set[str] = set()  # functions of the file whose last statement raises (a refusal: not FLOW)

    def refusal(stmt) -> bool:
        if isinstance(stmt, ast.Raise):
            raised = stmt.exc.func if isinstance(stmt.exc, ast.Call) else stmt.exc
            return getattr(raised, "id", getattr(raised, "attr", None)) not in FLOW
        call = stmt.value if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) else None
        name = call and (call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", None))
        return name in raising
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            body = node.body if isinstance(node.body, list) else [node.body]
            bodies.append((body[0].lineno, max(getattr(n, "end_lineno", n.lineno) for n in body)))
            if not isinstance(node, ast.Lambda) and isinstance(node.body[-1], ast.Raise) and refusal(node.body[-1]):
                raising.add(node.name)
    inside = lambda n: any(a <= n <= b for a, b in bodies)

    def refused(block) -> bool:
        return bool(block) and refusal(block[-1])

    owners = [n for n in ast.walk(tree) if isinstance(n, (ast.stmt, ast.ExceptHandler)) and inside(n.lineno)]

    def owner(line: int):
        holding = [n for n in owners if line in _own(n)]
        return max(holding, key=lambda n: (n.lineno, -n.end_lineno)) if holding else None

    def passed(stmt):
        """The guard directly governing a changed refusal, and what taking
        it means; None for a refusal no guard in its function governs."""
        node = stmt
        while node in parent:
            above, field = parent[node]
            if isinstance(above, (ast.If, ast.While)) and field in ("body", "orelse"):
                own = _own(above)
                return ("pass", frozenset(own), frozenset(own | _span(getattr(above, field))), frozenset())
            if isinstance(above, (ast.For, ast.AsyncFor)) and field == "body":
                own = _own(above)
                return ("pass", frozenset(own), frozenset(own | _span(above.body)), frozenset())
            if isinstance(above, ast.ExceptHandler):
                attempt = parent[above][0]
                return ("pass", frozenset(_span(attempt.body)), frozenset(range(attempt.lineno, attempt.end_lineno + 1)), frozenset())
            if isinstance(above, (ast.Try, ast.With, ast.AsyncWith)):  # no branch: the guard is further out
                node = above
                continue
            return None
        return None

    def governing(stmt):
        """The if or while that directly holds a statement in a branch, or the
        for loop whose body does (a with or a try body between them decides
        nothing); None for any other."""
        node = stmt
        while node in parent:
            above, field = parent[node]
            if isinstance(above, (ast.If, ast.While)) and field in ("body", "orelse"):
                return above
            if isinstance(above, (ast.For, ast.AsyncFor)) and field == "body":
                return above
            if not (isinstance(above, (ast.With, ast.AsyncWith)) or (isinstance(above, ast.Try) and field == "body")):
                return None
            node = above
        return None

    reqs: list[tuple] = []
    for stmt in sorted({o for o in map(owner, sorted(n for n in changed if inside(n))) if o is not None}, key=lambda n: n.lineno):
        mine = frozenset(_own(stmt) & changed)
        if isinstance(stmt, (ast.If, ast.While)):
            branch = stmt.body if refused(stmt.body) else stmt.orelse if refused(stmt.orelse) else None
            reqs.append(("pass", frozenset(_own(stmt)), frozenset(_own(stmt) | _span(branch)), mine) if branch else
                        ("line", mine or frozenset({stmt.lineno}), frozenset({stmt.lineno})))
        elif refusal(stmt):
            guard = passed(stmt)
            if guard is not None:
                reqs.append(guard)
        else:
            reqs.append(("line", mine or frozenset({stmt.lineno}), frozenset({stmt.lineno})))
        guard = None if refusal(stmt) or isinstance(stmt, (ast.If, ast.While)) else governing(stmt)  # a changed guard is its own
        if guard is not None:  # the guard deciding whether a changed statement runs, evaluated either way
            reqs.append(("line", frozenset(_own(guard)), frozenset({guard.lineno})))
        handler = stmt if isinstance(stmt, ast.ExceptHandler) else parent.get(stmt, (None,))[0]
        if isinstance(handler, ast.ExceptHandler):  # a changed handler, or its clause: the try completing needs none
            attempt = parent[handler][0]
            reqs.append(("pass", frozenset(_span(attempt.body)), frozenset(range(attempt.lineno, attempt.end_lineno + 1)), frozenset()))
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)):
            if changed & _span([node]):
                reqs.append(("line", frozenset(changed & _span([node])), frozenset({node.lineno})))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and not inside(node.lineno) and changed & set(range(node.lineno, node.end_lineno + 1)):
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
    reading = {node.lineno for node in ast.walk(tree) if ((isinstance(node, ast.Name) and node.id in names) or (isinstance(node, ast.Attribute) and node.attr in names))
               and inside(node.lineno)}
    if reading:
        reqs.append(("line", frozenset(reading), frozenset(reading)))
    return list(dict.fromkeys(reqs))


def describe(target: str, reqs: list[tuple]) -> str:
    """A requirement list in words, for the controls file."""
    def lines(found) -> str:
        found = sorted(found)
        runs, start = [], found[0]
        for a, b in zip(found, found[1:] + [None]):
            if b != a + 1:
                runs.append(f"{start}" if start == a else f"{start}-{a}")
                start = b
        return ", ".join(runs)
    parts = []
    for req in reqs:
        if req[0] == "line":
            parts.append(f"executes line {lines(req[1])}" + (f" (else {lines(req[2])})" if req[2] != req[1] else ""))
        else:
            parts.append(f"leaves line {lines(req[1])} for a line outside {lines(req[2])} (or returns)"
                         + (f", having executed line {lines(req[3])}" if req[3] and req[3] != req[1] else ""))
    return f"{target}: " + "; or ".join(parts)


def _ddl_guard(ddl: str, m) -> tuple[str, str] | None:
    """("trigger", name) or ("table", name) the mutant changes."""
    if m.drop_trigger:
        return ("trigger", m.drop_trigger)
    blocks = [(k, n, mt.start(), mt.end()) for mt in re.finditer(r"CREATE (TRIGGER|TABLE|UNIQUE INDEX|INDEX) (\w+)\b.*?(?:\nEND;\n|\) STRICT;\n|;\n)", ddl, re.DOTALL)
              for k, n in [(mt.group(1), mt.group(2))]]
    if m.scope:
        found = [b for b in blocks if b[1] == m.scope]
    else:
        at = ddl.find(m.old)
        found = [b for b in blocks if b[2] <= at < b[3]]
    if not found:
        return None
    kind, name, start, end = found[0]
    if kind == "TRIGGER":
        return ("trigger", name)
    if kind == "TABLE":
        return ("table", name)
    table = re.search(r"\bON (\w+)", ddl[start:end])
    return ("table", table.group(1)) if table else None


VERDICT = re.compile(r"^INVALID +(\S+): paired control\(s\) did not pass under the mutant: (\[.*\])$")


def _probe_one(job: tuple[str, list[str]]) -> tuple[str, dict, str | None]:
    """In a forked worker: run a mutant's killers and these candidate
    controls under it, through the runner's own mutation machinery; which
    candidates passed (a disk target's needing a child that met the mutant)."""
    mid, cands = job
    g = sys.modules["gen2_mutations"]
    m = next(x for x in g.MUTATIONS if x.mid == mid)
    g._CONTROLS = {mid: {"controls": cands}}
    fx = g._FX
    try:
        if m.target in g.FILE_TARGETS:
            res = g._run_file_mutation(m)
        else:
            ddl = g.mutate(fx.DDL_TEXT, m) if m.target == "ddl" else fx.DDL_TEXT
            conn = g.mutate(fx.CONNECTION_TEXT, m) if m.target == "connection" else fx.CONNECTION_TEXT
            res = g.run(fx, ddl, conn, (*m.killers, *cands))
    except ValueError as exc:
        return mid, {}, str(exc)
    named = g._named
    passed = {c: any(named(t, c) for t in res.ran) and not any(named(t, c) for t in (*res.failed, *res.errored, *res.skipped)) for c in cands}
    if res.tree is not None and g.FILE_TARGETS[m.target][0] == "disk":
        met = [a for a in res.attestations if a["pid"] != os.getpid() and a["test"]]
        passed = {c: ok and any(named(a["test"], c) for a in met) for c, ok in passed.items()}
    return mid, passed, None


def choose(trace_file: Path, runs: list[Path], probe_width: int = 0, jobs: int = 5, reprobe: tuple[str, ...] = ()) -> int:
    """Each mutant's controls from the trace. A control a mutation run found
    not passing under its mutant (INVALID ... paired control(s) did not pass,
    in the runs' logs) is kept in the file as rejected and never chosen for
    that mutant again. With probe_width, each mutant with a control rejected
    by those runs first has its next candidates (that many at a time, a few
    rounds) run under it, and the ones that do not pass are rejected too."""
    g = _inventory()
    tr = json.loads(trace_file.read_text(encoding="utf-8"))
    previous = json.loads(CONTROLS.read_text(encoding="utf-8")) if CONTROLS.exists() else {}
    rejected = {mid: set(e.get("rejected", ())) for mid, e in previous.items()}
    for log in runs:
        for line in log.read_text(encoding="utf-8").splitlines():
            found = VERDICT.match(line)
            if found:
                rejected.setdefault(found.group(1), set()).update(ast.literal_eval(found.group(2)))
    import gen2.tests.store_fixtures as fx
    ddl = fx.DDL_TEXT
    passing = {t for t, o in tr["outcomes"].items() if o == "pass"}
    store_passing = {t for t, o in tr["store_outcomes"].items() if o == "pass"}
    by_line: dict[tuple[str, int], set] = defaultdict(set)
    for test, pairs in tr["lines"].items():
        for rel, n in pairs:
            by_line[(rel, n)].add(test)
    by_from: dict[tuple[str, int], dict[int, set]] = defaultdict(lambda: defaultdict(set))  # (file, line) -> next line -> tests
    for test, found in tr["arcs"].items():
        for rel, a, b in found:
            by_from[(rel, a)][b].add(test)
    by_sql: dict[tuple[str, str], set] = defaultdict(set)
    for test, pairs in tr["sql"].items():
        for kind, name in pairs:
            by_sql[(kind, name)].add(test)
    failed_sql = {t: sum(1 for k, _ in pairs if k == "failed") for t, pairs in tr["sql"].items()}

    def refusals(test: str, target: str) -> int:
        """How often the test took a refusal or error path in the target: an
        exception raised inside that file, or for the DDL a statement that
        failed. Fewer first: the accepted path is what a control is for."""
        if target in ("ddl", "connection"):
            return failed_sql.get(test, 0)
        return tr["raises"].get(test, {}).get(target, 0)
    sources: dict[str, str] = {}
    fixed, plans = {}, {}  # an entry decided without ranking; else (ranked candidates, why)
    for m in g.MUTATIONS:
        if m.mid in MANUAL:
            fixed[m.mid] = {"by_hand": True, **MANUAL[m.mid]}
            continue
        how = g.FILE_TARGETS.get(m.target)
        if m.target in ("ddl", "connection"):
            guard = _ddl_guard(ddl, m) if m.target == "ddl" else None
            if guard is None:
                cands, why = set(), "no DDL object found for this mutation"
            elif guard[0] == "trigger":
                cands, why = by_sql[guard] & store_passing, f"a statement that succeeds enters trigger {guard[1]}"
                if not cands - set(m.killers):
                    holding = sorted(set(m.killers) & by_sql[guard] & store_passing)
                    header = re.search(r"CREATE TRIGGER " + guard[1] + r"\b(.*?)\nBEGIN", ddl, re.DOTALL).group(1)
                    table = re.search(r"\bON (\w+)", header).group(1)
                    if holding and all(k in READ_IN_KILLER for k in holding):  # the killer itself holds the accepted case (read)
                        fixed[m.mid] = {"controls": [], "in_killer": holding,
                                        "why": f"no other test enters trigger {guard[1]} in a statement that succeeds; the killer does, and "
                                               f"under the mutant too: {'; '.join(READ_IN_KILLER[k] for k in holding)}"}
                        continue
                    if "\nWHEN " not in header:  # it refuses every statement it enters: nothing accepted passes through it
                        cands = by_sql[("insert", table)] & store_passing
                        why = (f"trigger {guard[1]} refuses every statement it enters (no WHEN), so no accepted path passes through it; "
                               f"the control inserts a row into {table}, the table it guards, in a statement that succeeds")
            else:
                cands, why = by_sql[("insert", guard[1])] & store_passing, f"a statement that succeeds inserts a row into {guard[1]}"
                if not cands - set(m.killers):
                    cands, why = by_sql[("update", guard[1])] & store_passing, f"a statement that succeeds updates a row of {guard[1]}"
        elif m.target.endswith(".py"):
            text = (ROOT / m.target).read_text(encoding="utf-8")
            reqs = requirements(text, changed_lines(text, g.mutate(text, m)))
            ran = lambda found: set().union(*(by_line[(m.target, n)] for n in found))  # the tests that executed one of these lines
            cands = set()
            for req in reqs:
                if req[0] == "line":
                    cands |= ran(req[1]) or ran(req[2])
                else:
                    passers = {t for n in req[1] for nxt, tests in by_from[(m.target, n)].items() if nxt not in req[2] for t in tests}
                    cands |= passers & ran(req[3]) if ran(req[3]) else passers
            cands &= passing
            why = (describe(m.target, reqs) if reqs else
                   f"{m.target}: the changed code is a refusal that no guard in its function governs, so no accepted path passes through it")
            if how[0] == "attr":
                if how[1].rsplit(".", 1)[-1].startswith("test_"):
                    cands = {t for t in cands if t.split(".")[0] == how[1]}  # only that module is handed the mutant's path
                else:  # a fixtures module holds the path (task 2q-a): every test module that imports it is handed the path through it
                    users = holder_users(how[1])
                    cands = {t for t in cands if t.split(".")[0] in users}
        elif m.target.startswith("gen2/schema/") and m.target.endswith(".schema.json"):
            schema = Path(m.target).name[: -len(".schema.json")]
            module = how[1]
            if module not in sources:
                sources[module] = (TESTS / f"{module}.py").read_text(encoding="utf-8")
            declared = set(re.findall(r"def (test_\w+)\(self\) -> None:\n(?:\s*\"\"\"[\s\S]*?\"\"\"\n)?\s*self\.assertBehaveAsDeclared\(\"" + re.escape(schema) + r"\",\s*\"valid-",
                                      sources[module]))
            cands = {t for t in passing if t.split(".")[0] == module and t.rsplit(".", 1)[1] in declared}
            why = f"re-checks the schema tree and declares a valid {schema} fixture"
        else:
            cands, why = set(), f"no tracing for {m.target}"
        cands -= set(m.killers)
        classes = {k.rsplit(".", 1)[0] for k in m.killers}
        modules = {k.split(".")[0] for k in m.killers}
        preferred = PREFERRED.get(m.target, ())
        rank = lambda t: (preferred.index(t) if t in preferred else len(preferred), refusals(t, m.target) > 0,
                          0 if t.rsplit(".", 1)[0] in classes else 1 if t.split(".")[0] in modules else 2, refusals(t, m.target),
                          bool(NEGATIVE.search(t.rsplit(".", 1)[1])), tr["durations"].get(t, 99.0), t)
        plans[m.mid] = (sorted(cands, key=rank), why)
    to_probe = {mid for mid in rejected if mid in plans and rejected[mid] - set(previous.get(mid, {}).get("rejected", ()))} if probe_width else set()
    to_probe |= set(reprobe)
    exhausted = {mid for mid, e in previous.items() if e.get("exhausted") and mid not in to_probe}  # probed before: none passed
    if to_probe:
        import multiprocessing
        os.environ["GEN2_TEST_EVIDENCE"] = "off"
        g._FX = importlib.import_module("gen2.tests.store_fixtures")
        for round_ in range(3):
            batch = [(mid, [c for c in plans[mid][0] if c not in rejected[mid]][:probe_width]) for mid in sorted(to_probe)]
            batch = [(mid, cands) for mid, cands in batch if cands]
            if not batch:
                break
            by_mid = {m.mid: m for m in g.MUTATIONS}
            g.unresolved_tests(t for mid, cands in batch for t in (*by_mid[mid].killers, *cands))  # imported before the fork, as the runner does
            with multiprocessing.get_context("fork").Pool(jobs, maxtasksperchild=1) as pool:
                for mid, passed, error in pool.imap_unordered(_probe_one, batch, chunksize=1):
                    rejected[mid].update(c for c, ok in passed.items() if not ok)
                    print(f"probe round {round_ + 1}: {mid}: {sum(passed.values())}/{len(passed)} candidate(s) pass under the mutant"
                          + (f" ({error})" if error else ""), flush=True)
                    if any(passed.values()):
                        to_probe.discard(mid)
        exhausted |= to_probe  # every candidate probed failed: none is chosen unverified
    out, unpaired = {}, []
    for m in g.MUTATIONS:
        if m.mid in fixed:
            out[m.mid] = fixed[m.mid]
            if set(fixed[m.mid]["controls"]) & rejected.get(m.mid, set()) or not (fixed[m.mid]["controls"] or fixed[m.mid].get("in_killer")):
                unpaired.append(m.mid)
        else:
            ranked, why = plans[m.mid]
            fresh = [c for c in ranked if c not in rejected.get(m.mid, set())]
            kept = [c for c in previous.get(m.mid, {}).get("controls", ()) if c in fresh][:1]
            if kept and fresh and refusals(kept[0], m.target) and not refusals(fresh[0], m.target):
                kept = []  # a kept control that took a refusal path yields to one that took none
            picked = [] if m.mid in exhausted else kept or fresh[:1]
            tried = len(rejected.get(m.mid, ()))
            effect = ("an over-restricting mutant refuses the accepted path, which every test tried needs (in its case or its fixture)"
                      if "over-restrict" in m.description else "the mutant changes what the accepted path does rather than removing a refusal")
            out[m.mid] = {"controls": picked, "why": why if picked else
                          (f"all {tried} candidates run under the mutant fail ({len(ranked) - tried} of the {len(ranked)} that take the path "
                           f"were not run): {effect}" if ranked else f"no candidate: {why}")}
            if not picked and ranked:
                out[m.mid]["exhausted"] = tried
            if not picked:
                unpaired.append(m.mid)
        if rejected.get(m.mid):
            out[m.mid]["rejected"] = sorted(rejected[m.mid])
    CONTROLS.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    held = sorted(mid for mid, e in out.items() if e.get("in_killer"))
    table = sorted(mid for mid, e in out.items() if "refuses every statement" in e["why"])
    print(f"{len(out)} mutants: {len(out) - len(held) - len(unpaired)} with a paired control ({len(table)} of them a write to the table of a "
          f"trigger that refuses every statement it enters; {sum(1 for e in out.values() if e.get('by_hand') and e['controls'])} by hand), "
          f"{len(held)} whose killer holds its accepted case, {len(unpaired)} with neither: {unpaired}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=("trace", "choose"))
    parser.add_argument("--trace", type=Path, required=True, help="the trace file (written by trace, read by choose)")
    parser.add_argument("--run", type=Path, action="append", default=[], help="choose: a mutation run's log, whose failing controls are rejected")
    parser.add_argument("--probe", type=int, default=0, metavar="N", help="choose: run each newly rejected mutant's next N candidates under it first")
    parser.add_argument("--reprobe", action="append", default=[], metavar="MID", help="choose, with --probe: probe this mutant's candidates again")
    args = parser.parse_args(argv)
    return trace(args.trace) if args.step == "trace" else choose(args.trace, args.run, args.probe, reprobe=tuple(args.reprobe))


if __name__ == "__main__":
    sys.exit(main())
