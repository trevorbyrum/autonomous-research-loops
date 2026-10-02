"""The task-2b gateway mutant inventory run by tools/gen2_gateway_mutations.py.

Each mutant removes or weakens exactly ONE guard of the gateway repairs (the edit `old`
→ `new` must occur exactly once in `target`, a path under gateway/). `killers` must fail
under it; `controls` must pass under it — tests that take the accepted path through the
same code, so a kill does not rest on that path being broken. `db` marks a mutant whose
killers need the scratch database. Test ids are unittest names from gateway/.

2b-repair-12 (schema-first decoding): every operation declares its payload and one decoder reads it (core/schema.py), so the per-adapter guards of 2b-repair-7..11 moved into the
decoder and the schemas. The mutants that restated them in the adapters (`need`, `optional`, `preferred`, the views, the lazy-choice scan) are replaced by
tools/gen2_gateway_schema_mutants.py, which keeps the earlier names where a guard kept its meaning. A mutant there may carry several edits (a tuple of `old`/`new`), for a guard that
had two layers (the decoder and the adapter's own eager read): both are removed.

Not in the inventory, and why: the schema's immutability trigger (DDL applied to a shared
scratch database — tested directly by DurableCorrelation.test_correlation_is_immutable_
once_written, not mutated); the front door's admit() before submit()/handle() (both bind
again: removing one layer is an equivalent mutant); Grants.mint's `grantor.bound` clause
(a grant's principal is never a grantor: equivalent); crossref._record's own refusal of a work
with neither DOI nor URL (2b-repair A4: members() and the router both drop the `url:None` it
would build — a second and third layer that make removing the first equivalent); the
migration's `restriction_inputs = true` (2b-repair-4 F2: a migration that marks nothing fails its
own completion check in every test that converts a row, so no accepted path is left to pair a
control with); each of its two `NOT restriction_inputs` (the pass's list of rows, and the batch's
re-check under lock of a row a current writer converted meanwhile: each backs the other, so
removing one is equivalent without concurrency; that a rerun converts nothing and a current
writer's row is never rewritten is test_the_migration_runs_once_and_says_when_it_is_done's); the
serving gate's own view, gateway.servable_records (2b-repair-5 F2: DDL applied to the shared
scratch database, like the immutability trigger — the tests that re-apply the schema would leave a
mutant view there for every later run; it is exercised directly by test_record_gate.AssembledGateway,
which fails on all four doors with a reader that goes around it); the local index's last tie-breaker,
`r.identity` (2b-repair-6 F3: it makes offset pages cut one total order — without it, rows tied on
rank, works and year have no defined order, but a small fixture's ties keep their physical order,
so no test can reliably see it removed); the local index's separate count around the gate
(F2-index-counts-around-gate, retired in 2b-repair-7: the page, the counts and the population digest are
now one statement over ONE join to gateway.servable_records, so reading and counting around the gate is
the single edit F2-index-reads-around-gate makes, and its killers include the count's); R8-record-keeps-views (retired in 2b-repair-13c: its guard — a record holds plain
data, a view of the provider's answer never ends up inside one — moved from `make_record`'s return to the serialization boundary, where Q-router-does-not-materialize-the-answer and
Q-record-materializes-its-provenance (tools/gen2_gateway_opaque_mutants.py) hold both sides of it).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mutant:
    mid: str
    description: str
    target: str
    old: str | tuple[str, ...]   # one edit; or a tuple of edits, each applied once, for a guard that has two layers (both are removed)
    new: str | tuple[str, ...]
    killers: tuple[str, ...]
    controls: tuple[str, ...]
    db: bool = False


SC = "tests.test_secrets_contract."
PS, LO = "tests.test_payload_shapes.AdapterBoundary.", "tests.test_lane_outcomes."
CO, SP, PV = "tests.test_correlation.", "tests.test_server_policy.", "tests.test_provenance."
SCHEMA = "research_gateway/core/schema.py"
SECRETS, ROUTER, BASE, APP = "research_gateway/core/secrets.py", "research_gateway/core/router.py", "research_gateway/adapters/base.py", "research_gateway/app.py"
PRINC, HTTP, MCP, STDIO = "research_gateway/core/principals.py", "research_gateway/api/http.py", "research_gateway/mcp/homelab_adapter.py", "research_gateway/clients/mcp_stdio.py"
LIC = "research_gateway/core/licenses.py"
CACHE, MIGRATE = "research_gateway/core/cache.py", "research_gateway/registry/migrate.py"
INDEX, RG = "research_gateway/adapters/openalex_snapshot.py", "tests.test_record_gate."
LOCAL_INDEX = "tests.test_adapters_platforms.OpenAlexLocalIndex.test_find_hits_local_index_without_network"
EX = "tests.test_exhaustion."
PP = "tests.test_provider_pagination."
MD = "tests.test_member_decoding."
LH = "tests.test_link_header."
MI = "tests.test_member_isolation."
DOORS = "tests.test_inventory.Inventory.test_every_site_the_scans_find_is_listed_and_every_listed_site_is_there"
HX = "tests.test_invariants."
TP = "tests.test_present_means_typed."
TF = "tests.test_typed_fields."
ST = "tests.test_station_contract."
OR, AL, FB = "tests.test_oracle.", "tests.test_alternatives.", "tests.test_flow_binding."


def harness(letter: str, op: str) -> str:
    """The invariant harness's test for invariant `letter` (a: an end or continuation only from fields it read; b: an unreadable container is
    never an empty one; c: readable members beside an unreadable one survive; d: nothing escapes unhandled) over the operation named `op`."""
    why = {"a": "ends_or_continues_only_on_what_it_read", "b": "an_unreadable_container_is_never_empty", "c": "readable_peers_survive",
           "d": "nothing_escapes_unhandled"}[letter]
    return f"{HX}Corruptions.test_{letter}_{why}__" + "".join(ch if ch.isalnum() else "_" for ch in op).strip("_")


# a raw provider list taken out through the one door, inline, so a mutant needs no import of its own: what the repair removed
# was an adapter holding the plain list; a mutant that restores it must reach for the door, and the source check lists every one
_P = '__import__("research_gateway.core.payload", fromlist=["plain"]).plain'

MUTANTS: list[Mutant] = [
    # ---- item 6: secrets outcomes (DEPLOYMENT-CONTRACT §3.4) ---------------------------------------------
    Mutant("S-home-fallback", "an unset token-file variable falls back to ~/.vault-token", SECRETS,
           'self.token_file = token_file or env.get(TOKEN_FILE_VAR) or ""',
           'self.token_file = token_file or env.get(TOKEN_FILE_VAR) or os.path.expanduser("~/.vault-token")',
           (SC + "F1NoHomeFallback.test_refuses_to_start_and_never_opens_the_home_token",),
           (SC + "F1NoHomeFallback.test_control_an_explicit_token_file_starts_the_service",)),
    Mutant("S-no-address", "a vault backend without an address is accepted", SECRETS,
           "        if not self.addr:\n            raise SecretsConfigError", "        if False:\n            raise SecretsConfigError",
           ("tests.test_core_foundations.Secrets.test_vault_backend_without_address_refuses",),
           (SC + "F4GenuinelyAbsent.test_absent_is_absent_and_does_not_alarm",)),
    Mutant("S-unreadable-token-starts", "an unreadable token file at startup is accepted", SECRETS,
           "        if problem:\n            raise SecretsConfigError", "        if False:\n            raise SecretsConfigError",
           (SC + "F2ExplicitFileUnreadable.test_a_missing_path_at_startup_is_refused",),
           (SC + "F1NoHomeFallback.test_control_an_explicit_token_file_starts_the_service",)),
    Mutant("S-failing-reads-absent", "a failed read is returned as absent", SECRETS,
           '        if kind == "failing":\n            return payload\n        if kind == "absent":',
           '        if kind == "failing":\n            return SecretRead(ABSENT)\n        if kind == "absent":',
           (SC + "F3TransportAndStatus.test_each_failure_is_failing_and_never_absent", SC + "F8OutageReplay.test_the_outage_reads_as_an_outage",
            SC + "F5OutcomeSurvivesTheHttpBoundary.test_per_lane_outcome_over_http"),
           (SC + "F4GenuinelyAbsent.test_absent_is_absent_and_does_not_alarm", SC + "F5OutcomeSurvivesTheHttpBoundary.test_control_a_readable_secret_answers")),
    Mutant("S-missing-mount-absent", "a 404 for a mount that does not exist reads as absent", SECRETS,
           "        if errors == []:\n            return \"absent\", None", "        if True:\n            return \"absent\", None",
           (SC + "F4GenuinelyAbsent.test_control_the_same_path_under_a_missing_mount_is_failing",
            SC + "F3TransportAndStatus.test_each_failure_is_failing_and_never_absent"),
           (SC + "F4GenuinelyAbsent.test_absent_is_absent_and_does_not_alarm",)),
    Mutant("S-success-status-unchecked", "a success status other than 200 is read as the secret (A7)", SECRETS,
           "        if status != 200:", "        if False:",
           (SC + "F3TransportAndStatus.test_a_valid_body_under_another_success_status_is_failing",),
           (SC + "F3TransportAndStatus.test_control_the_same_body_under_200_is_the_secret",)),
    Mutant("S-follows-redirects", "the vault opener follows redirects (the token goes elsewhere)", SECRETS,
           "    _opener = urllib.request.build_opener(_Opener)", "    _opener = urllib.request.build_opener()",
           (SC + "F7RedirectsRefused.test_no_redirect_is_followed",),
           (SC + "F4GenuinelyAbsent.test_absent_is_absent_and_does_not_alarm",)),
    Mutant("S-cache-launders", "a cached failure replays as absent", SECRETS,
           "            self._cache[vault_name] = (self._clock() + ttl, kind, payload)",
           '            self._cache[vault_name] = (self._clock() + ttl, "absent" if kind == "failing" else kind, payload)',
           (SC + "F6CacheDoesNotLaunderAFailure.test_failure_replay_expiry_and_recovery",),
           (SC + "F4GenuinelyAbsent.test_absent_is_absent_and_does_not_alarm",)),
    Mutant("S-stale-success", "a cached success outlives its TTL (a failed re-read is papered over)", SECRETS,
           "        if hit and hit[0] > now:", '        if hit and (hit[0] > now or hit[1] != "failing"):',
           (SC + "F6CacheDoesNotLaunderAFailure.test_failure_replay_expiry_and_recovery", SC + "F8OutageReplay.test_the_outage_reads_as_an_outage",
            SC + "F4GenuinelyAbsent.test_absent_is_absent_and_does_not_alarm"),   # a removed secret, re-read after its TTL, is absent
           (SC + "F5OutcomeSurvivesTheHttpBoundary.test_control_a_readable_secret_answers",)),
    Mutant("S-no-transition-alert", "a transition into failing does not alert", SECRETS,
           "            alert = self._settle(before)\n        self._notify(alert)\n\n    def _settle",
           "            alert = self._settle(before)\n        self._notify(False)\n\n    def _settle",
           (SC + "F3TransportAndStatus.test_the_capability_fact_is_dated_names_its_lanes_and_alerts_on_transition",),
           (SC + "F4GenuinelyAbsent.test_absent_is_absent_and_does_not_alarm",)),
    Mutant("S-no-status-line", "operator status carries no failing line", SECRETS,
           '        if f["state"] != "failing":\n            return None', '        if True:\n            return None',
           (SC + "F8OutageReplay.test_the_outage_reads_as_an_outage",),
           (SC + "F3TransportAndStatus.test_the_capability_fact_is_dated_names_its_lanes_and_alerts_on_transition",)),
    # ---- 2b-repair-3 R2: each change of the fact is its next revision; an answer carries the latest ------------
    Mutant("S-revision-uncounted", "a change of the capability fact is not a new revision", SECRETS,
           "        if self._content() != before:\n            self.revision += 1", "        if False:\n            self.revision += 1",
           (SC + "FactRevisions.test_each_change_is_the_next_revision_and_a_repeat_is_not",
            "tests.test_engine_fixtures.EngineFixtures.test_data_secrets_outage_recurs"),
           (SC + "F3TransportAndStatus.test_the_capability_fact_is_dated_names_its_lanes_and_alerts_on_transition",)),
    Mutant("S-revision-every-read", "a fresh read that changes nothing is a new revision", SECRETS,
           "        if self._content() != before:\n            self.revision += 1", "        if True:\n            self.revision += 1",
           (SC + "FactRevisions.test_each_change_is_the_next_revision_and_a_repeat_is_not",
            "tests.test_engine_fixtures.EngineFixtures.test_data_secrets_outage_two_invocations"),
           (SC + "F3TransportAndStatus.test_the_capability_fact_is_dated_names_its_lanes_and_alerts_on_transition",)),
    Mutant("R-fact-last-lane-wins", "an answer carries the fact of the lane collected last, not the latest revision", ROUTER,
           '        if held is None or fact.get("revision", 0) >= held.get("revision", 0):', "        if True:",
           (SC + "FactRevisions.test_an_answer_keeps_the_latest_snapshot_it_met",),
           ("tests.test_engine_fixtures.EngineFixtures.test_data_secrets_failing",)),
    Mutant("S-lane-generic", "a lane whose secret read failed is a generic unreadable lane", ROUTER,
           "    if isinstance(e, SecretsBackendFailing):\n        _secrets_failing(entry, facts, sid, e)\n        return e.fact\n",
           "",
           (SC + "F5OutcomeSurvivesTheHttpBoundary.test_per_lane_outcome_over_http",),
           (LO + "LaneOutcomes.test_each_refusal_names_its_error_class",)),
    Mutant("S-startup-token-read", "a failed token read at startup is taken for 'no tokens'", APP,
           "        if read.state == FAILING:\n            raise SecretsConfigError", "        if False:\n            raise SecretsConfigError",
           (SC + "F2ExplicitFileUnreadable.test_a_token_read_that_fails_at_startup_is_refused_as_failing",),
           (SC + "F1NoHomeFallback.test_control_an_explicit_token_file_starts_the_service",)),
    # ---- item 3: response shape at the adapter boundary --------------------------------------------------
    Mutant("P-json-lenient", "unparseable JSON reads as an empty object", SCHEMA,
           '''        raise PayloadError(f"unparseable JSON (HTTP {getattr(answer, 'status', None)}, {len(body)} bytes)" + ("" if e.syntax else f": {e}")) from None''',
           "        return {}",
           (PS + "test_the_json_reader_refuses_what_it_cannot_read",),
           (PS + "test_control_the_apis_own_empty_answer_stays_empty",)),
    Mutant("P-empty-lenient", "an empty body reads as an empty object", SCHEMA,
           '''        raise PayloadError(f"empty body (HTTP {getattr(answer, 'status', None)})")''', "        return {}",
           (PS + "test_the_json_reader_refuses_what_it_cannot_read",), (PS + "test_control_the_apis_own_empty_answer_stays_empty",)),
    Mutant("P-search-404-empty", "crossref's search 404 reads as no results", "research_gateway/adapters/crossref.py",
           '    resp = client.get(SOURCE_ID, "find", f"{BASE}/works", params=params, query=query)\n    check(SOURCE_ID, resp, allow_404=False)',
           '    resp = client.get(SOURCE_ID, "find", f"{BASE}/works", params=params, query=query)\n    if not check(SOURCE_ID, resp):\n        return {"records": []}',
           (PS + "test_a_search_endpoints_404_is_an_outage_not_no_results",), (PS + "test_control_the_apis_own_empty_answer_stays_empty",)),
    Mutant("P-partial-complete", "a set that lost records is called complete", ROUTER,
           '    entry["completeness"] = "partial" if dropped else "complete"', '    entry["completeness"] = "complete"',
           (LO + "LaneOutcomes.test_dropped_records_make_a_partial_lower_bound",),
           (LO + "LaneOutcomes.test_control_all_readable_records_are_complete",)),
    Mutant("P-unreadable-records-empty", "a lane whose every record was unreadable is searched_empty", ROUTER,
           "    if dropped and not count:", "    if False:",
           (LO + "LaneOutcomes.test_only_unreadable_records_observe_nothing",), (LO + "LaneOutcomes.test_control_a_readable_empty_answer_is_searched_empty",)),
    Mutant("P-fact-counted", "a fact-only answer gets a count of 0", ROUTER,
           '        entry["error_class"] = ERR_UNCONFIGURED if entry["coverage"] == COVERAGE_AUTH else ERR_OUTAGE\n        return\n',
           '        entry["error_class"] = ERR_UNCONFIGURED if entry["coverage"] == COVERAGE_AUTH else ERR_OUTAGE\n',
           (LO + "LaneOutcomes.test_a_fact_only_answer_is_degraded_not_empty",), (LO + "LaneOutcomes.test_control_a_readable_empty_answer_is_searched_empty",)),
    Mutant("P-partial-exhausted", "a partial lane is marked exhausted", ROUTER,
           '    elif ended and entry["coverage"] in (COVERAGE_OK, COVERAGE_EMPTY) and entry["completeness"] == "complete":',
           '    elif ended and entry["coverage"] in (COVERAGE_OK, COVERAGE_EMPTY):',
           (LO + "LaneOutcomes.test_a_partial_lane_is_never_exhausted",), (LO + "LaneOutcomes.test_control_a_readable_empty_answer_is_searched_empty",)),
    Mutant("P-cursor-lost", "a lane does not echo the cursor it was asked with", ROUTER,
           '                   "cursor": (payload.get("cursors") or {}).get(lane.source_id)}', '                   "cursor": None}',
           (LO + "LaneOutcomes.test_a_failed_continuation_page_keeps_its_cursor",), (LO + "LaneOutcomes.test_control_all_readable_records_are_complete",)),
    Mutant("P-degraded-cached", "an answer with a degraded lane is cached", ROUTER,
           '            if rt == "find" and all(lane.get("completeness") == "complete"', '            if rt == "find" and True or all(lane.get("completeness") == "complete"',
           (LO + "DegradedAnswersAreNotReplayed.test_a_degraded_answer_is_asked_again", LO + "DegradedAnswersAreNotReplayed.test_a_partial_answer_is_asked_again"),
           (LO + "DegradedAnswersAreNotReplayed.test_control_a_complete_answer_is_served_from_cache",)),
    Mutant("P-resolve-fact-not-found", "a keyless resolve's fact is read as a record", ROUTER,
           '            if isinstance(rec, dict) and rec.get("capability_fact") and not rec.get("identity"):', "            if False:",
           (LO + "LaneOutcomes.test_a_resolve_capability_fact_is_not_not_found",), (LO + "LaneOutcomes.test_control_a_readable_empty_answer_is_searched_empty",)),
    Mutant("P-retrieved-missing", "a counted lane does not name what it counted", ROUTER,
           '                          else [str(r["identity"]) for r in got])', "                          else [])",
           (LO + "LaneOutcomes.test_dropped_records_make_a_partial_lower_bound", LO + "LaneOutcomes.test_control_all_readable_records_are_complete"),
           (LO + "LaneOutcomes.test_control_a_readable_empty_answer_is_searched_empty",)),
    # 2b-repair A4: provider members, each decoded alone, and every candidate names something
    Mutant("P-members-not-isolated", "one unreadable member discards the members read beside it", "research_gateway/core/payload.py",
           "            except MEMBER_ERRORS:\n                rec = None", "            except ZeroDivisionError:\n                rec = None",
           (LO + "RealAdapterMembers.test_a_later_bad_member_keeps_the_earlier_as_a_partial_lower_bound", LO + "RealAdapterMembers.test_each_member_is_decoded_alone"),
           (LO + "RealAdapterMembers.test_control_readable_members_are_complete_and_cached",)),
    Mutant("P-member-identity-unchecked", "a decoded member naming nothing (url:None) is kept by the adapter helper", BASE,
           '    return [rec if isinstance(rec, dict) and meaningful(rec.get("identity")) else None for rec in items.each(build)]',
           '    return [rec if isinstance(rec, dict) and rec.get("identity") else None for rec in items.each(build)]',
           (LO + "RealAdapterMembers.test_each_member_is_decoded_alone",), (LO + "RealAdapterMembers.test_control_readable_members_are_complete_and_cached",)),
    Mutant("P-router-identity-unchecked", "the router counts a record whose identity names nothing", ROUTER,
           '    good = [r for r in (items or []) if isinstance(r, dict) and ident.meaningful(r.get("identity")) and r.get("kind")]',
           '    good = [r for r in (items or []) if isinstance(r, dict) and r.get("identity") and r.get("kind")]',
           (LO + "LaneOutcomes.test_a_fabricated_identity_is_a_dropped_record",), (LO + "LaneOutcomes.test_control_all_readable_records_are_complete",)),
    # ---- items 1-2: invocation/attempt and complete request identity -------------------------------------
    Mutant("C-v1-drops-invocation", "the /v1 door drops the invocation headers", HTTP,
           '                 "topic": (self.headers.get("X-Research-Topic") or "")[:64] or None, **correlation}',
           '                 "topic": (self.headers.get("X-Research-Topic") or "")[:64] or None}',
           (CO + "BothDoorsCarryTheInvocation.test_the_v1_door_echoes_the_callers_invocation_and_attempt",),
           (CO + "BothDoorsCarryTheInvocation.test_control_what_is_not_research_needs_no_correlation",)),
    Mutant("C-malformed-accepted", "a malformed invocation id is accepted", APP,
           "    if not INVOCATION_RE.fullmatch(inv):", "    if False:",
           (CO + "BothDoorsCarryTheInvocation.test_malformed_or_half_given_correlation_is_refused",),
           (CO + "BothDoorsCarryTheInvocation.test_the_v1_door_echoes_the_callers_invocation_and_attempt",)),
    Mutant("C-mcp-drops-invocation", "the MCP door drops the invocation", MCP,
           '        tr = {**trace, **({"batch_entry": entry} if entry is not None else {})}',
           '        tr = {"batch_entry": entry} if entry is not None else {}',
           (CO + "BothDoorsCarryTheInvocation.test_the_mcp_door_carries_it_into_every_tool_call_and_batch_entry",),
           (CO + "BothDoorsCarryTheInvocation.test_the_v1_door_echoes_the_callers_invocation_and_attempt",)),
    Mutant("C-batch-entry-lost", "MCP batch entries lose their index", MCP,
           '                    results.append({"tool": tool, "result": call(tool, (entry or {}).get("arguments") or {}, index)})',
           '                    results.append({"tool": tool, "result": call(tool, (entry or {}).get("arguments") or {}, None)})',
           (CO + "BothDoorsCarryTheInvocation.test_the_mcp_door_carries_it_into_every_tool_call_and_batch_entry",),
           (CO + "BothDoorsCarryTheInvocation.test_the_v1_door_echoes_the_callers_invocation_and_attempt",)),
    Mutant("C-no-db-captured", "an answer without a database claims a durable row", APP,
           '            obs["capture_loss"] = "no durable call log: this gateway runs without a database"\n            return obs',
           '            obs["captured"] = True\n            return obs',
           (CO + "BothDoorsCarryTheInvocation.test_the_v1_door_echoes_the_callers_invocation_and_attempt",),
           (CO + "BothDoorsCarryTheInvocation.test_the_mcp_door_carries_it_into_every_tool_call_and_batch_entry",)),
    # 2b-repair A5: the pair is required on every research request, polls bound and recorded under their caller
    Mutant("C-v1-correlation-optional", "a /v1 research request without correlation runs unattributed", HTTP,
           "        if not problem and research and not correlation:", "        if False:",
           (CO + "BothDoorsCarryTheInvocation.test_a_research_request_without_correlation_is_refused_on_every_door",
            SP + "Grants_.test_the_grant_carries_its_invocation"),
           (CO + "BothDoorsCarryTheInvocation.test_the_v1_door_echoes_the_callers_invocation_and_attempt",)),
    Mutant("C-mcp-correlation-optional", "an MCP research tool call without correlation runs unattributed", MCP,
           '        if not tr.get("invocation_id"):   # every research tool call is attributed (2b-repair A5)', "        if False:",
           (CO + "BothDoorsCarryTheInvocation.test_a_research_request_without_correlation_is_refused_on_every_door",),
           (CO + "BothDoorsCarryTheInvocation.test_the_mcp_door_carries_it_into_every_tool_call_and_batch_entry",)),
    Mutant("C-poll-uncorrelated", "a job poll without correlation is answered", HTTP,
           "            trace = self._trace(research=True)   # a poll is research: bound and recorded under its caller (A5)",
           "            trace = self._trace()",
           (CO + "BothDoorsCarryTheInvocation.test_a_research_request_without_correlation_is_refused_on_every_door",),
           ("tests.test_http_api.InlineGateway.test_bad_requests",)),
    Mutant("C-poll-unbound", "a grant's poll may name another invocation", APP,
           "        trace = bind_correlation(dict(trace or {}), principal)", "        trace = dict(trace or {})",
           (SP + "JobsAreTheirTopicsAlone.test_a_poll_naming_another_invocation_or_none_is_refused",),
           (SP + "JobsAreTheirTopicsAlone.test_control_its_own_topic_reads_its_job",), db=True),
    Mutant("C-poll-as-creator", "a poll's observation names the job's creator, not its caller", APP,
           '        obs = {"invocation_id": trace.get("invocation_id"), "attempt": trace.get("attempt"),\n'
           '               "request_identity": j.get("request_identity"), "served": "polled",',
           '        obs = {"invocation_id": j.get("invocation_id"), "attempt": j.get("attempt"),\n'
           '               "request_identity": j.get("request_identity"), "served": "polled",',
           (SP + "JobsAreTheirTopicsAlone.test_a_poll_is_bound_and_recorded_under_its_own_caller",),
           (SP + "JobsAreTheirTopicsAlone.test_control_its_own_topic_reads_its_job",), db=True),
    Mutant("C-poll-row-as-creator", "a poll's durable row is written under the job's creator", APP,
           '                    invocation_id=obs["invocation_id"], attempt=obs["attempt"], request_identity=j.get("request_identity")))',
           '                    invocation_id=j.get("invocation_id"), attempt=j.get("attempt"), request_identity=j.get("request_identity")))',
           (SP + "JobsAreTheirTopicsAlone.test_a_poll_is_bound_and_recorded_under_its_own_caller",),
           (SP + "JobsAreTheirTopicsAlone.test_control_its_own_topic_reads_its_job",), db=True),
    Mutant("C-download-observation-dropped", "the station client drops a download's observation header",
           "research_gateway/clients/http_client.py",
           '        return {"content": raw, "content_type": ctype, **raw_observation(observed)}', '        return {"content": raw, "content_type": ctype}',
           ("tests.test_http_api.InlineGateway.test_the_station_client_keeps_a_downloads_observation",
            "tests.test_http_api.InlineGateway.test_bytes_without_their_observation_say_so"),
           ("tests.test_http_api.InlineGateway.test_control_a_download_through_the_station_client_is_its_bytes",)),
    Mutant("C-subject-collapses", "a request key keeps only its query (kind and cursor collide)", STDIO,
           '    if not extra and base_key != "source":', '    if base_key != "source":',
           (CO + "RequestIdentity.test_the_design_reviews_probe_kind_and_cursor_no_longer_collide",),
           (CO + "RequestIdentity.test_control_spellings_of_one_request_share_its_identity",)),
    Mutant("C-identity-no-cursor", "the effective request drops its cursors", "research_gateway/core/request_identity.py",
           "                   cursors=dict(payload.get(\"cursors\") or {}),", "                   cursors={},",
           (CO + "RequestIdentity.test_the_design_reviews_probe_kind_and_cursor_no_longer_collide",),
           (CO + "RequestIdentity.test_control_spellings_of_one_request_share_its_identity",)),
    Mutant("C-identity-no-default", "the effective request leaves the default page size unapplied", "research_gateway/core/request_identity.py",
           '        out.update(query=payload.get("query") or "", kind=payload.get("kind"), limit=payload.get("limit") or DEFAULT_LIMIT,',
           '        out.update(query=payload.get("query") or "", kind=payload.get("kind"), limit=payload.get("limit"),',
           (CO + "RequestIdentity.test_control_spellings_of_one_request_share_its_identity",),
           (CO + "RequestIdentity.test_the_design_reviews_probe_kind_and_cursor_no_longer_collide",)),
    Mutant("C-activity-loss-silent", "a failed activity write is acknowledged as captured", STDIO,
           '        return {"captured": False, "loss": f"activity file not written ({why}); "',
           '        return {"captured": True, "loss": f"activity file not written ({why}); "',
           (CO + "StdioClient.test_a_failed_activity_write_is_acknowledged_and_announced_later", CO + "StdioClient.test_the_tool_result_carries_the_loss"),
           (CO + "StdioClient.test_the_gateway_line_is_the_transport_and_a_pending_answer_clears_nothing",)),
    Mutant("C-pending-clears", "a pending answer writes the clearing gateway line", STDIO,
           "    if not gateway_trouble and result is not None and not pending:", "    if not gateway_trouble and result is not None:",
           (CO + "StdioClient.test_the_gateway_line_is_the_transport_and_a_pending_answer_clears_nothing",),
           (CO + "StdioClient.test_a_failed_activity_write_is_acknowledged_and_announced_later",)),
    Mutant("C-attempt-constant", "every repeat of a request is attempt 1", STDIO,
           "        _ATTEMPTS[identity] = _ATTEMPTS.get(identity, 0) + 1", "        _ATTEMPTS[identity] = 1",
           (CO + "StdioClient.test_attempts_number_repeats_of_one_request",),
           (CO + "StdioClient.test_the_gateway_line_is_the_transport_and_a_pending_answer_clears_nothing",)),
    Mutant("C-job-unattributed", "a queued job does not keep its creator's invocation", "research_gateway/core/queue.py",
           "                     invocation_id, attempt, request_identity),", "                     None, None, request_identity),",
           (CO + "DurableCorrelation.test_a_queued_job_and_its_lane_calls_carry_the_creators_invocation",),
           (CO + "DurableCorrelation.test_a_lost_request_row_is_reported_not_implied",), db=True),
    Mutant("C-lane-rows-unattributed", "lane call rows do not carry the invocation", BASE,
           '        return {"invocation_id": self.invocation_id, "attempt": self.attempt, "request_identity": self.request_identity}',
           '        return {"invocation_id": None, "attempt": None, "request_identity": self.request_identity}',
           (CO + "DurableCorrelation.test_a_queued_job_and_its_lane_calls_carry_the_creators_invocation",),
           (CO + "DurableCorrelation.test_a_lost_request_row_is_reported_not_implied",), db=True),
    Mutant("C-waiter-unattributed", "a coalesced caller's row carries no invocation", APP,
           "                        invocation_id=invocation_id, attempt=attempt, request_identity=rid))",
           "                        invocation_id=None, attempt=None, request_identity=rid))",
           (CO + "DurableCorrelation.test_a_coalesced_caller_keeps_its_own_invocation",),
           (CO + "DurableCorrelation.test_a_queued_job_and_its_lane_calls_carry_the_creators_invocation",), db=True),
    Mutant("C-coalesced-as-dispatched", "a coalesced caller is told it dispatched", APP,
           '                  else "coalesced" if out.get("created") is False\n', "",
           (CO + "DurableCorrelation.test_a_coalesced_caller_keeps_its_own_invocation",),
           (CO + "DurableCorrelation.test_a_queued_job_and_its_lane_calls_carry_the_creators_invocation",), db=True),
    Mutant("C-row-loss-silent", "a lost request row is not reported", APP,
           '            obs["capture_loss"] = f"request row not written: {type(e).__name__}"[:200]', "            pass",
           (CO + "DurableCorrelation.test_a_lost_request_row_is_reported_not_implied",),
           (CO + "DurableCorrelation.test_a_queued_job_and_its_lane_calls_carry_the_creators_invocation",), db=True),
    # ---- item 4: server-side policy ------------------------------------------------------------------------
    Mutant("G-bind-noop", "a grant's policy is not applied", PRINC,
           "    if not principal.bound:\n        return payload\n    out = dict(payload)", "    return payload\n    out = dict(payload)",
           (SP + "Grants_.test_the_v1_door_binds_the_topic_policy", SP + "Grants_.test_the_mcp_door_binds_it_too"),
           (SP + "Grants_.test_control_an_unbound_client_is_unchanged",)),
    Mutant("G-conflict-overridden", "a conflicting argument is silently overridden", PRINC,
           '            raise PolicyError(f"policy-bound: {key} is set by the topic, not the caller")', "            pass",
           (SP + "Grants_.test_the_v1_door_binds_the_topic_policy",), (SP + "Grants_.test_control_an_unbound_client_is_unchanged",)),
    Mutant("G-invocation-free", "a grant-bearer may name another invocation", PRINC,
           '        raise PolicyError("policy-bound: the invocation is set by the grant, and the request must carry it")', "        pass",
           (SP + "Grants_.test_the_grant_carries_its_invocation",), (SP + "Grants_.test_control_an_unbound_client_is_unchanged",)),
    Mutant("G-invocation-optional", "a grant's request naming no invocation runs (2b-repair A5)", PRINC,
           '    if trace.get("invocation_id") != principal.invocation_id:',
           '    if trace.get("invocation_id") not in (None, principal.invocation_id):',
           (SP + "Grants_.test_in_process_a_grant_request_carries_the_pair_too",),
           (SP + "Grants_.test_control_the_grants_invocation_with_the_callers_attempt_runs",)),
    Mutant("G-attempt-defaulted", "a grant's request without an attempt runs (2b-repair A5)", PRINC,
           '    if not isinstance(trace.get("attempt"), int) or isinstance(trace.get("attempt"), bool) or trace["attempt"] < 1:',
           "    if False:",
           (SP + "Grants_.test_in_process_a_grant_request_carries_the_pair_too",),
           (SP + "Grants_.test_control_the_grants_invocation_with_the_callers_attempt_runs",)),
    Mutant("G-unsigned", "a grant's signature is not checked", PRINC,
           "        if not body or not sig or not hmac.compare_digest(sig, self._sign(body)):", "        if not body or not sig:",
           (SP + "Grants_.test_a_forged_altered_expired_or_foreign_grant_is_refused",), (SP + "Grants_.test_only_a_grantor_mints_and_a_grant_never_does",)),
    Mutant("G-never-expires", "an expired grant is accepted", PRINC,
           ' or claims["exp"] <= self._clock():', ":",
           (SP + "Grants_.test_a_forged_altered_expired_or_foreign_grant_is_refused",), (SP + "Grants_.test_only_a_grantor_mints_and_a_grant_never_does",)),
    Mutant("G-everyone-grantor", "every configured client may mint grants", APP,
           "                return Principal(name=name, grantor=name in self.settings.grantors)",
           "                return Principal(name=name, grantor=True)",
           (SP + "Grants_.test_only_a_grantor_mints_and_a_grant_never_does",), (SP + "Grants_.test_a_grant_request_states_its_posture",)),
    Mutant("G-mcp-unbound", "the MCP door runs under the grantor's bare name, unbound", HTTP,
           "            reply = homelab_adapter.rpc(self.server.gateway, client, body, trace=trace)",
           "            reply = homelab_adapter.rpc(self.server.gateway, client.name, body, trace=trace)",
           (SP + "Grants_.test_the_mcp_door_binds_it_too",), (SP + "Grants_.test_the_v1_door_binds_the_topic_policy",)),
    Mutant("G-posture-unchecked", "a job is readable under a looser posture of its topic", PRINC,
           '    return all(bool(payload.get(k)) == principal.policy[k] for k in ("commercial", "accept_per_item") if k in principal.policy)',
           "    return True",
           (SP + "JobsAreTheirTopicsAlone.test_polling_never_crosses_topics_or_postures",),
           (SP + "JobsAreTheirTopicsAlone.test_control_its_own_topic_reads_its_job",), db=True),
    # ---- item 5: licence, freshness, provenance -----------------------------------------------------------
    # 2b-repair A3: restrictions survive persistence; metadata licence is not content licence; availability is what was delivered
    Mutant("L-summary-drops-restrictions", "a stored member summary forgets the source's restrictions", "research_gateway/core/canonical.py",
           "    out.update({k: member[k] for k in MEMBER_RESTRICTIONS + INFERRED_RESTRICTIONS if isinstance(member.get(k), bool)})\n", "",
           (PV + "RestrictionsSurviveReload.test_a_prohibition_survives_a_fresh_process_reload",
            PV + "RestrictionsSurviveReload.test_third_party_terms_survive_a_fresh_process_reload"),
           (PV + "RestrictionsSurviveReload.test_control_an_unrestricted_cc0_record_reloads_permitted",), db=True),
    Mutant("L-legacy-prohibition-lost", "a row kept in record_sources loses its stored prohibition on reload", "research_gateway/core/cache.py",
           '             **({"redistributable": False} if redistribution == "prohibited" else {})}',
           "             }",
           (PV + "RestrictionsSurviveReload.test_a_legacy_row_keeps_its_stored_prohibition",),
           (PV + "RestrictionsSurviveReload.test_control_a_legacy_permitted_row_reloads_permitted",), db=True),
    Mutant("L-inputs-marker-unwritten", "the current writer's new row is not marked as carrying its inputs", "research_gateway/core/cache.py",
           "now(), true) ", "now(), false) ",
           (PV + "RestrictionsSurviveReload.test_control_a_row_written_with_its_inputs_is_derived_from_them_alone",),
           (PV + "RestrictionsSurviveReload.test_a_pre_repair_row_written_again_is_the_current_writers",), db=True),
    Mutant("L-rewritten-row-keeps-old-marker", "a row an earlier writer left, written again by the current writer, keeps its old marker",
           "research_gateway/core/cache.py", '"restriction_inputs = true",', '"restriction_inputs = gateway.records.restriction_inputs",',
           (PV + "RestrictionsSurviveReload.test_a_pre_repair_row_written_again_is_the_current_writers",),
           (PV + "RestrictionsSurviveReload.test_a_prohibition_survives_a_fresh_process_reload",), db=True),
    # 2b-repair-4 F2: earlier writers' rows are converted once (registry/migrate.py); nothing reads them unconverted
    Mutant("F2-opens-over-unconverted-rows", "a cache (and so a gateway) opens a database still holding an unconverted row", CACHE,
           "            if left:\n", "            if False:\n",
           (PV + "RestrictionsSurviveReload.test_no_gateway_opens_a_database_holding_an_unconverted_row",),
           (PV + "RestrictionsSurviveReload.test_a_prohibition_survives_a_fresh_process_reload",), db=True),
    # 2b-repair-5 F2: every serving read goes through gateway.servable_records, which withholds a row not yet converted
    Mutant("F2-cache-reads-around-gate", "the record cache reads stored rows around the serving gate", CACHE,
           '"SELECT canonical FROM gateway.servable_records WHERE identity = %s "', '"SELECT canonical FROM gateway.records WHERE identity = %s "',
           (PV + "RestrictionsSurviveReload.test_a_row_an_older_gateway_writes_later_is_never_served",
            RG + "OneServingRead.test_no_production_code_reads_stored_records_around_the_gate"),
           (PV + "RestrictionsSurviveReload.test_a_prohibition_survives_a_fresh_process_reload",), db=True),
    Mutant("F2-index-reads-around-gate", "the local index serves stored rows read around the serving gate", INDEX,
           '"FROM gateway.index_docs d JOIN gateway.servable_records r ON r.identity = d.identity "',
           '"FROM gateway.index_docs d JOIN gateway.records r ON r.identity = d.identity "',
           (RG + "AssembledGateway.test_a_row_written_after_startup_is_withheld_on_every_door",
            RG + "AssembledGateway.test_a_search_only_withheld_rows_match_observes_nothing",
            RG + "OneServingRead.test_no_production_code_reads_stored_records_around_the_gate"),
           (LOCAL_INDEX,), db=True),
    Mutant("F2-withheld-complete", "a lane whose stored matches were withheld reports what was served as complete", ROUTER,
           "    return got, (str(fact) if fact else None), dropped + withheld\n", "    return got, (str(fact) if fact else None), dropped\n",
           (LO + "LaneOutcomes.test_withheld_stored_records_make_a_partial_lower_bound",),
           (LO + "LaneOutcomes.test_dropped_records_make_a_partial_lower_bound",)),
    # 2b-repair-6 F3: a lane is exhausted only on its adapter's report that nothing remains
    Mutant("F3-missing-cursor-is-exhaustion", "the router reads a missing continuation as exhaustion (the defect)", ROUTER,
           '    elif ended and entry["coverage"] in (COVERAGE_OK, COVERAGE_EMPTY) and entry["completeness"] == "complete":',
           '    elif entry["coverage"] in (COVERAGE_OK, COVERAGE_EMPTY) and entry["completeness"] == "complete":',
           (EX + "ReportedEnd.test_records_with_no_continuation_and_no_reported_end_are_a_lower_bound",
            EX + "ReportedEnd.test_an_empty_answer_is_exhausted_only_when_reported"),
           (EX + "ReportedEnd.test_control_a_reported_end_is_exhausted", EX + "ReportedEnd.test_control_a_continuation_is_followed_not_exhausted")),
    Mutant("F3-truncation-complete", "records with neither a continuation nor a reported end stay a complete answer", ROUTER,
           '            entry.update(completeness="partial", error_class=ERR_PAGINATION)', "            pass",
           (EX + "ReportedEnd.test_records_with_no_continuation_and_no_reported_end_are_a_lower_bound",),
           (EX + "ReportedEnd.test_control_a_reported_end_is_exhausted",)),
    Mutant("F3-end-outranks-continuation", "a reported end wins over the continuation the same answer gave", ROUTER,
           '    if nxt is not None and entry["completeness"] != "unobserved":\n        entry["next"] = nxt',
           '    if nxt is not None and entry["completeness"] != "unobserved" and not ended:\n        entry["next"] = nxt',
           (EX + "ReportedEnd.test_a_continuation_outranks_a_reported_end",),
           (EX + "ReportedEnd.test_control_a_continuation_is_followed_not_exhausted",)),
    Mutant("F3-crossref-no-first-cursor", "Crossref's first page is asked without a cursor (it then sends no continuation)",
           "research_gateway/adapters/crossref.py", '"cursor": cursor or "*"}', '"cursor": cursor}',
           (PP + "Crossref.test_the_first_page_asks_for_a_cursor",), (PP + "Crossref.test_continues",)),
    Mutant("F3-kaggle-cut-page-continues", "a Kaggle page cut to the limit continues at page + 1 (skipping the cut rows) or ends",
           "research_gateway/adapters/kaggle.py", "    cut = len(items) > limit", "    cut = False",
           (PP + "KaggleDatasets.test_a_page_cut_to_the_limit_neither_continues_nor_ends",),
           (PP + "KaggleDatasets.test_continues",)),
    Mutant("F3-index-claims-end", "the local index reports its end on every page (a bounded answer called whole)", INDEX,
           '            "next_offset": f"{start + size}:{population}" if more else None, "exhausted": not more}',
           '            "next_offset": None, "exhausted": True}',
           (EX + "AssembledPaging.test_more_converted_matches_than_the_limit_continue_on_every_door",
            EX + "AssembledPaging.test_the_engine_client_pages_to_the_end",
            EX + "LocalIndexPages.test_more_matches_than_the_limit_page_to_the_end"),
           (EX + "LocalIndexPages.test_control_everything_fitting_on_the_final_page_is_exhausted",
            EX + "AssembledPaging.test_control_everything_fitting_is_exhausted_and_its_sentinel_skips_the_lane", LOCAL_INDEX), db=True),
    Mutant("F3-index-no-lookahead", "the local index reads only the page, so it never knows whether anything remains", INDEX,
           "                cur.execute(sql, [query, *args, start, start + size + 1])", "                cur.execute(sql, [query, *args, start, start + size])",
           (EX + "LocalIndexPages.test_more_matches_than_the_limit_page_to_the_end",),
           (EX + "LocalIndexPages.test_control_everything_fitting_on_the_final_page_is_exhausted",), db=True),
    # 2b-repair-7 F3-R1: a continuation is read only in the population it was counted in
    Mutant("F3R1-index-population-unchecked", "a continuation is read in whatever population the index now holds (the defect)", INDEX,
           "    if counted_in is not None and population != counted_in:\n", "    if False:\n",
           (EX + "LocalIndexPages.test_a_match_removed_after_page_one_never_hides_the_one_after_it",
            EX + "LocalIndexPages.test_a_match_inserted_ahead_of_the_offset_is_never_passed_over",
            EX + "LocalIndexPages.test_a_match_reordered_ahead_of_the_offset_is_never_passed_over",
            EX + "LocalIndexPages.test_cached_pages_never_splice_two_populations",
            EX + "AssembledPaging.test_a_changed_index_ends_no_doors_search"),
           (EX + "LocalIndexPages.test_more_matches_than_the_limit_page_to_the_end",
            EX + "AssembledPaging.test_more_converted_matches_than_the_limit_continue_on_every_door"), db=True),
    Mutant("F3R1-index-digest-unordered", "the population digest names the matches but not their order", INDEX,
           "' ' ORDER BY pos)", "' ' ORDER BY identity)",
           (EX + "LocalIndexPages.test_a_match_reordered_ahead_of_the_offset_is_never_passed_over",),
           (EX + "LocalIndexPages.test_more_matches_than_the_limit_page_to_the_end",
            EX + "LocalIndexPages.test_a_match_removed_after_page_one_never_hides_the_one_after_it"), db=True),
    Mutant("F3R1-stale-continuation-is-unreadable", "a continuation the index can no longer honour reads as an unreadable answer", ROUTER,
           "        entry[\"coverage\"], entry[\"error_class\"] = COVERAGE_DOWN, ERR_PAGINATION\n",
           "        entry[\"coverage\"], entry[\"error_class\"] = COVERAGE_DOWN, ERR_PAYLOAD\n",
           (EX + "LocalIndexPages.test_a_match_removed_after_page_one_never_hides_the_one_after_it",),
           (EX + "LocalIndexPages.test_a_negative_offset_is_no_page",), db=True),
    # 2b-repair-7: each find adapter's end rule as its provider's evidence states it (docs/PROVIDER-PAGINATION.md)
    Mutant("P7-crossref-total-ends", "Crossref ends on an empty page or a first page holding total-results, not on a short page",
           "research_gateway/adapters/crossref.py", "    end = len(items) < rows\n",
           '    end = not items or (cursor in (None, "*") and len(items) >= (total(msg.get("total-results")) or 10 ** 9))\n',
           (PP + "Crossref.test_ends", PP + "Crossref.test_neither"), (PP + "Crossref.test_continues",)),
    Mutant("P7-datacite-past-the-cap", "DataCite offers page-number continuations past the first 10,000 records",
           "research_gateway/adapters/datacite.py", " and (page + 1) * size <= MAX_PAGED_RECORDS else None", " else None",
           (PP + "DataCiteDois.test_neither",), (PP + "DataCiteDois.test_continues", PP + "DataCiteDois.test_ends")),
    Mutant("P7-doaj-cap-by-page-end", "DOAJ refuses a page that starts below record 1,000 but ends past it",
           "research_gateway/adapters/doaj.py", "    if (page - 1) * page_size >= MAX_RECORDS_PER_QUERY:",
           "    if page * page_size > MAX_RECORDS_PER_QUERY:",
           (PP + "DoajArticles.test_control_a_page_starting_below_the_cap_is_asked",),
           (PP + "DoajArticles.test_a_page_starting_past_the_cap_is_never_asked",)),
    Mutant("P7-doaj-continues-into-the-cap", "DOAJ offers a next page that would start at the 1,000-record cap",
           "research_gateway/adapters/doaj.py", " and page * page_size < MAX_RECORDS_PER_QUERY else None", " else None",
           (PP + "DoajArticles.test_neither",), (PP + "DoajArticles.test_continues", PP + "DoajArticles.test_ends")),
    Mutant("P7-europepmc-unchanged-cursor-ends", "Europe PMC treats an unchanged cursor as the end (undocumented)",
           "research_gateway/adapters/europepmc.py", '            "exhausted": False}',
           '            "exhausted": j.get("nextCursorMark") == (cursor or "*")}',
           (PP + "EuropePmcSearch.test_neither",), (PP + "EuropePmcSearch.test_continues",)),
    Mutant("P7-govinfo-count-ends", "GovInfo treats a first page holding `count` as the end (undocumented)",
           "research_gateway/adapters/govinfo.py", '            "exhausted": False}',
           '            "exhausted": bool(results) and offset_mark == "*" and j.get("count") == len(results)}',
           (PP + "GovInfoSearch.test_continues",), (PP + "GovInfoSearch.test_neither",)),
    Mutant("P7-dataverse-empty-page-ends", "Dataverse ends on an empty page short of total_count",
           "research_gateway/adapters/harvard_dataverse.py", "    reached = count is not None and page * per_page >= count\n",
           "    reached = not items or (count is not None and page * per_page >= count)\n",
           (PP + "DataverseSearch.test_continues",), (PP + "DataverseSearch.test_ends", PP + "DataverseSearch.test_neither")),
    Mutant("P7-openaire-missing-cursor-ends", "OpenAIRE treats a missing nextCursor as the end (undocumented)",
           "research_gateway/adapters/openaire.py", '    end = mark == sent or',
           '    end = mark in (sent, None) or',
           (PP + "OpenAireProducts.test_neither",), (PP + "OpenAireProducts.test_continues", PP + "OpenAireProducts.test_ends")),
    Mutant("P7-openaire-unchanged-cursor-continues", "OpenAIRE's documented end (the cursor handed back unchanged) is not read",
           "research_gateway/adapters/openaire.py", '    end = mark == sent or',
           '    end = False or',
           (PP + "OpenAireProducts.test_ends",), (PP + "OpenAireProducts.test_continues",)),
    Mutant("P7-kaggle-short-page-ends", "Kaggle ends on a page shorter than an assumed size of twenty (undocumented)",
           "research_gateway/adapters/kaggle.py", '"next_page": page + 1 if items and not cut else None, "exhausted": False}',
           '"next_page": page + 1 if len(items) >= 20 and not cut else None, "exhausted": len(items) < 20 and not cut}',
           (PP + "KaggleDatasets.test_continues",), (PP + "KaggleDatasets.test_a_page_cut_to_the_limit_neither_continues_nor_ends",)),
    Mutant("P7-openml-full-page-ends", "OpenML ends on a full page (its client continues one)",
           "research_gateway/adapters/openml.py", '            "exhausted": len(items) < min(limit, 100)}', '            "exhausted": True}',
           (PP + "OpenMLDatasets.test_continues",), (PP + "OpenMLDatasets.test_ends",)),
    Mutant("P7-socrata-past-the-window", "Socrata offers a next page whose offset + limit the 10,000 window refuses",
           "research_gateway/adapters/socrata.py", " and following + size <= SEARCH_WINDOW else None", " else None",
           (PP + "SocrataCatalog.test_neither",), (PP + "SocrataCatalog.test_continues", PP + "SocrataCatalog.test_ends")),
    Mutant("P7-socrata-empty-page-ends", "Socrata ends on an empty page short of resultSetSize (undocumented)",
           "research_gateway/adapters/socrata.py", "    reached = count is not None and following >= count\n",
           "    reached = not results or (count is not None and following >= count)\n",
           (PP + "SocrataCatalog.test_neither",), (PP + "SocrataCatalog.test_ends", PP + "SocrataCatalog.test_continues")),
    # 2b-repair-7 F3-R2: Hugging Face pages by its own Link rel="next", inside the gateway's URL and credential boundary
    Mutant("F3R2-hf-short-page-ends", "Hugging Face ends on a short page and continues a full one, whatever its Link header says",
           "research_gateway/adapters/huggingface.py", '"exhausted": link.url is None and link.known}',
           '"exhausted": len(items) < min(limit, 100)}',
           (PP + "HuggingFaceDatasets.test_continues", PP + "HuggingFaceDatasets.test_ends"),
           (PP + "HuggingFaceDatasets.test_the_next_page_is_asked_at_the_providers_own_url",)),
    Mutant("F3R2-hf-any-link-followed", "a next link that leaves this search on the Hub is handed back as the continuation",
           "research_gateway/adapters/huggingface.py", '"next_cursor": own_link(link.url, listing, search=query),', '"next_cursor": link.url,',
           (PP + "HuggingFaceDatasets.test_a_next_link_that_leaves_this_search_is_not_a_continuation",),
           (PP + "HuggingFaceDatasets.test_continues",)),
    Mutant("F3R2-hf-any-continuation-asked", "a continuation handed back is asked wherever it points",
           "research_gateway/adapters/huggingface.py", "        url, params = own_link(cursor, listing, search=query), None\n",
           "        url, params = cursor, None\n",
           (PP + "HuggingFaceDatasets.test_a_continuation_that_leaves_this_search_is_never_asked",),
           (PP + "HuggingFaceDatasets.test_the_next_page_is_asked_at_the_providers_own_url",)),
    Mutant("F3R2-link-user-info-kept", "a provider link carrying user info (credentials of its own) is followable", BASE,
           "    if u.username is not None or u.password is not None or u.fragment:\n", "    if u.fragment:\n",
           (PP + "HuggingFaceDatasets.test_a_next_link_that_leaves_this_search_is_not_a_continuation",
            PP + "HuggingFaceDatasets.test_a_continuation_that_leaves_this_search_is_never_asked"),
           (PP + "HuggingFaceDatasets.test_continues",)),
    # 2b-repair-8 R7-1: a Link header that cannot be read is never an end (RFC 8288 reading, three outcomes)
    Mutant("R8-link-unreadable-is-absence", "a Link header that cannot be read is taken for one that names no next link", BASE,
           "        return NextLink(None, False)\n    return NextLink(targets.pop()", "        return NextLink(None, True)\n    return NextLink(targets.pop()",
           (LH + "Reading.test_a_header_that_cannot_be_read_is_neither_a_next_link_nor_the_end",
            LH + "HuggingFace.test_a_header_that_cannot_be_read_never_ends_the_lane"),
           (LH + "Reading.test_a_header_read_whole_that_names_no_next_link_is_an_established_end",
            LH + "HuggingFace.test_control_a_header_read_whole_with_no_next_link_is_the_end")),
    Mutant("R8-link-two-next-pages-pick-one", "two different next pages: the last one is taken, as if the header were certain", BASE,
           "    return NextLink(targets.pop() if len(targets) == 1 and not unusable else None, len(targets) <= 1 and not unusable)",
           "    return NextLink(targets.pop() if targets else None, True)",
           (LH + "Reading.test_a_header_that_cannot_be_read_is_neither_a_next_link_nor_the_end",),
           (LH + "Reading.test_a_next_link_is_found_however_the_header_is_written",)),
    Mutant("R8-hf-ignores-known", "Hugging Face reads no next URL as the end whether or not the header was read", "research_gateway/adapters/huggingface.py",
           '"exhausted": link.url is None and link.known}', '"exhausted": link.url is None}',
           (LH + "HuggingFace.test_a_header_that_cannot_be_read_never_ends_the_lane",),
           (LH + "HuggingFace.test_control_a_header_read_whole_with_no_next_link_is_the_end",
            LH + "HuggingFace.test_a_next_link_with_a_quoted_comma_continues_through_the_router")),
    Mutant("R8-link-comma-ends-a-quoted-string", "a comma ends a quoted parameter (the reader that lost the reported relation)", BASE,
           "                    while i < n and header[i] != '\"':\n", "                    while i < n and header[i] not in '\",':\n",
           (LH + "Reading.test_a_next_link_is_found_however_the_header_is_written",
            LH + "HuggingFace.test_a_next_link_with_a_quoted_comma_continues_through_the_router"),
           (LH + "Reading.test_a_relative_target_is_resolved_against_the_url_asked",
            LH + "HuggingFace.test_control_a_header_read_whole_with_no_next_link_is_the_end")),
    Mutant("R8-transport-keeps-the-last-link-line", "a repeated header line replaces the earlier ones instead of joining them", BASE,
           '        out[name] = f"{out[name]}, {value}" if name in out else value\n', "        out[name] = value\n",
           (LH + "RepeatedFieldLines.test_repeated_lines_are_joined_in_order",
            LH + "RepeatedFieldLines.test_the_real_transport_keeps_every_link_line"),
           ("tests.test_core_foundations.MeteredClient.test_real_transport_never_raises",)),
    # 2b-repair-8 R7-1, everywhere an end or a continuation is read from the provider's own metadata
    # 2b-repair-7: Socrata's portal cache is learnt only from members read whole (A4)
    Mutant('A4-socrata-domains-from-raw-members', 'Socrata learns portal domains from the raw members before decoding each alone', 'research_gateway/adapters/socrata.py',
           '    _KNOWN_DOMAINS.update(r["venue"].lower() for r in records if r and isinstance(r.get("venue"), str) and r["venue"])\n',
           '    _KNOWN_DOMAINS.update((__import__("research_gateway.core.payload", fromlist=["plain"]).plain(r.raw).get("metadata") or {}).get("domain", "").lower() for r in results.each(lambda member: member) if __import__("research_gateway.core.payload", fromlist=["plain"]).plain(r.raw).get("metadata"))\n',
           ('tests.test_lane_outcomes.RealAdapterMembers.test_a_socrata_member_that_is_not_an_object_keeps_the_readable_ones',),
           ('tests.test_lane_outcomes.RealAdapterMembers.test_control_a_whole_socrata_page_is_complete',)),
    # 2b-repair-7b / 2b-repair-8: every provider member is decoded alone, and a provider's list is a Members that cannot be
    # iterated (core/payload.py). A mutant that restores the old defect must take the plain list out through the one door,
    # `plain`, so the behavioural killers fail on the malformed member and the source check (DOORS) fails on the unlisted use.
    Mutant("A4-crossref-references-raw", "Crossref builds its reference records by iterating the raw references",
           "research_gateway/adapters/crossref.py",
           '"items": members(SOURCE_ID, refs, _reference)}', '"items": [r for r in map(_reference, refs.each(lambda member: member)) if r is not OMIT]}',
           (MD + "EveryMemberAlone.test_a_member_that_is_not_an_object_costs_that_member_only", DOORS), (MD + "EveryMemberAlone.test_control_a_readable_member_alone_is_kept_whole",)),
    Mutant("A4-unpaywall-raw", "Unpaywall builds its location records by iterating the raw locations",
           "research_gateway/adapters/unpaywall.py",
           'items = members(SOURCE_ID, locations, location)', 'items = [r for r in (location(loc) for loc in locations.each(lambda member: member)) if r is not OMIT]',
           (MD + "EveryMemberAlone.test_a_member_that_is_not_an_object_costs_that_member_only", DOORS), (MD + "EveryMemberAlone.test_control_a_readable_member_alone_is_kept_whole",)),
    Mutant("A4-dataverse-unreadable-file-called-foreign", "a download whose file may be an unreadable member is refused as 'does not belong'",
           "research_gateway/adapters/harvard_dataverse.py", "            if None in files:", "            if False:",
           (MD + "DataverseDownloadMembership.test_a_file_that_may_be_the_unreadable_member_is_not_called_foreign",),
           (MD + "DataverseDownloadMembership.test_a_file_that_is_not_in_the_dataset_is_refused_as_such",)),
    Mutant("A4-ecb-series-raw", "ECB builds its series records by iterating the raw series",
           "research_gateway/adapters/ecb.py", "    records = members(SOURCE_ID, sdmx.series_members(j), record)",
           "    records = [record(m) for m in sdmx.series_members(j).each(lambda member: member)]",
           (MD + "EveryMemberAlone.test_a_member_that_is_not_an_object_costs_that_member_only", DOORS), (MD + "EveryMemberAlone.test_control_a_readable_member_alone_is_kept_whole",)),
    Mutant("A4-first-result-unreadable-is-not-found", "a lookup whose first result cannot be read answers 'not found'", "research_gateway/core/payload.py",
           "        if got and got[0] is None:\n", "        if False:\n",
           (MD + "FirstResult.test_an_unreadable_first_result_is_an_unreadable_answer", MI + "Views.test_the_first_member_is_read_like_any_other_and_never_replaced_by_the_next"),
           (MD + "FirstResult.test_control_a_readable_first_result_is_the_record_and_none_is_not_found",)),
    Mutant("A4-omitted-member-counted-as-lost", "a member that names nothing to report (a reference with no DOI) is counted as a dropped one",
           "research_gateway/core/payload.py", "            if rec is not OMIT:\n                out.append(rec)\n", "            out.append(None if rec is OMIT else rec)\n",
           (MD + "EveryMemberAlone.test_control_a_member_naming_nothing_is_omitted_not_dropped",),
           (MD + "EveryMemberAlone.test_a_member_that_is_not_an_object_costs_that_member_only",)),
    Mutant("F2-harvest-rows-unmarked", "the harvest's new row is not marked current", "research_gateway/harvest/index.py",
           "now(), true) ", "now(), false) ",
           (PV + "RestrictionsSurviveReload.test_the_harvests_rows_are_current_and_read_from_record_sources",),
           ("tests.test_harvest.IndexRoundTrip.test_a_metadata_licence_never_becomes_the_content_licence",), db=True),
    Mutant("F2-marked-unconverted", "the migration marks a row without converting it", MIGRATE,
           "(json.dumps(converted(canonical, stored), default=str), identity)", "(json.dumps(canonical, default=str), identity)",
           (PV + "RestrictionsSurviveReload.test_a_pre_repair_rows_prohibition_survives_the_migration",
            PV + "RestrictionsSurviveReload.test_the_live_gateways_rows_keep_their_leads_statements"),
           (PV + "RestrictionsSurviveReload.test_control_a_legacy_permitted_row_reloads_permitted",), db=True),
    Mutant("F2-legacy-members-unread", "a row with no members of its own is converted without its record_sources rows", MIGRATE,
           '                stored = [] if canonical.get("provenance") else stored_members(cur, identity)\n', "                stored = []\n",
           (PV + "RestrictionsSurviveReload.test_a_legacy_rows_lead_statement_survives_the_migration",),
           (PV + "RestrictionsSurviveReload.test_a_legacy_row_keeps_its_stored_prohibition",), db=True),
    Mutant("F2-lead-statements-dropped", "the lead's own statements, among the record's fields, are not its member's", MIGRATE,
           "    members[at] = {**lead, **members[at]}\n", "",
           (PV + "RestrictionsSurviveReload.test_the_live_gateways_rows_keep_their_leads_statements",
            PV + "RestrictionsSurviveReload.test_a_legacy_rows_lead_statement_survives_the_migration"),
           (PV + "RestrictionsSurviveReload.test_control_a_pre_repair_unrestricted_row_reloads_permitted",), db=True),
    Mutant("F2-lead-statements-spread", "a lead with no member of its own puts its statements on the first member", MIGRATE,
           'm.get("source_id") == canonical.get("source_id")), None)', 'm.get("source_id") == canonical.get("source_id")), 0)',
           (PV + "RestrictionsSurviveReload.test_a_legacy_rows_lead_statement_survives_the_migration",),
           (PV + "RestrictionsSurviveReload.test_the_live_gateways_rows_keep_their_leads_statements",), db=True),
    Mutant("F2-prohibition-not-converted", "task 2b's stored prohibition is not converted into its member's statement", MIGRATE,
           '    derived = {"redistributable": False} if facts.get("redistribution") == "prohibited" else {}\n', "    derived = {}\n",
           (PV + "RestrictionsSurviveReload.test_a_pre_repair_rows_prohibition_survives_the_migration",),
           (PV + "RestrictionsSurviveReload.test_control_a_pre_repair_unrestricted_row_reloads_permitted",), db=True),
    Mutant("F2-personal-use-not-converted", "task 2b's stored personal use is dropped by the migration", MIGRATE,
           '        if facts.get("access") == "personal_use" and m.get("third_party_restricted") is not True:\n', "        if False:\n",
           (PV + "RestrictionsSurviveReload.test_a_pre_repair_rows_personal_use_survives_the_migration_as_inferred",),
           (PV + "RestrictionsSurviveReload.test_control_a_pre_repair_unrestricted_row_reloads_permitted",), db=True),
    Mutant("F2-inferred-as-stated", "a personal use inferred from legacy data is recorded as the source's third-party terms", MIGRATE,
           '            derived["inferred_personal_use"] = True\n', '            derived["third_party_restricted"] = True\n',
           (PV + "RestrictionsSurviveReload.test_a_pre_repair_rows_personal_use_survives_the_migration_as_inferred",
            PV + "RestrictionsSurviveReload.test_a_pre_repair_rows_prohibition_survives_the_migration"),
           (PV + "RestrictionsSurviveReload.test_the_migration_runs_once_and_says_when_it_is_done",), db=True),
    Mutant("F2-stated-also-inferred", "a personal use its kept third-party statement explains is also recorded as inferred", MIGRATE,
           ' and m.get("third_party_restricted") is not True:\n', ":\n",
           (PV + "RestrictionsSurviveReload.test_a_pre_repair_rows_personal_use_survives_the_migration_as_inferred",),
           (PV + "RestrictionsSurviveReload.test_control_a_pre_repair_unrestricted_row_reloads_permitted",), db=True),
    Mutant("F2-inferred-not-kept", "a stored member summary forgets its inferred restriction", "research_gateway/core/canonical.py",
           "MEMBER_RESTRICTIONS + INFERRED_RESTRICTIONS if", "MEMBER_RESTRICTIONS if",
           (PV + "RestrictionsSurviveReload.test_a_pre_repair_rows_personal_use_survives_the_migration_as_inferred",),
           (PV + "RestrictionsSurviveReload.test_a_prohibition_survives_a_fresh_process_reload",), db=True),
    Mutant("F2-inferred-ignored", "an inferred personal use does not restrict access", LIC,
           ' and not member.get("inferred_personal_use")\n', "\n",
           (PV + "RestrictionsSurviveReload.test_a_pre_repair_rows_personal_use_survives_the_migration_as_inferred",),
           (PV + "PermissionFacts.test_each_fact_follows_its_own_rule",), db=True),
    Mutant("L-metadata-licence-as-content", "a harvest loader's metadata licence stands in for the content licence",
           "research_gateway/harvest/index.py", '    content_license = record.get("license")\n',
           '    content_license = metadata_license or record.get("license")\n',
           ("tests.test_harvest.IndexRoundTrip.test_a_metadata_licence_never_becomes_the_content_licence",
            "tests.test_harvest.IndexRoundTrip.test_the_real_loaders_pass_their_licence_as_metadata"),
           ("tests.test_harvest.IndexRoundTrip.test_control_a_content_licence_decides_with_or_without_a_metadata_licence",), db=True),
    Mutant("L-availability-by-kind", "a file or full-text record is content by its kind, links only or not", LIC,
           '    return {"availability": "content" if has_content else "metadata",',
           '    return {"availability": "content" if has_content or kind in ("full_text", "file") else "metadata",',
           (PV + "ReturnedRecords.test_a_link_only_listing_is_metadata_not_content", PV + "PermissionFacts.test_each_fact_follows_its_own_rule"),
           (PV + "ReturnedRecords.test_a_download_carries_its_own_facts",)),
    Mutant("L-loader-subset", "the DB loader drops licence and freshness", APP,
           '                  "auth", "secret_ref", "key_instructions", "license", "use_commercial", "use_evidence", "freshness_lag",',
           '                  "auth", "secret_ref", "key_instructions", "use_commercial", "use_evidence",',
           (PV + "DatabaseBackedSources.test_the_loader_returns_every_registry_field_of_every_source",
            PV + "DatabaseBackedSources.test_a_db_backed_gateway_answers_with_licence_and_freshness"),
           (PV + "DatabaseBackedSources.test_control_the_database_is_what_is_read",), db=True),
    Mutant("L-conditional-permitted", "a conditional licence permits redistribution", LIC,
           '    return "permitted" if KNOWN.get(cid) else "conditional"', '    return "permitted"',
           (PV + "PermissionFacts.test_each_fact_follows_its_own_rule",), (PV + "PermissionFacts.test_unknown_is_never_permitted",)),
    Mutant("L-unknown-permitted", "an unidentified licence permits redistribution", LIC,
           '    if cid is None:\n        return "unknown"', '    if cid is None:\n        return "permitted"',
           (PV + "PermissionFacts.test_unknown_is_never_permitted", PV + "PermissionFacts.test_each_fact_follows_its_own_rule"),
           (PV + "PermissionFacts.test_a_merged_record_takes_the_most_restrictive_of_its_members",)),
    Mutant("L-storage-is-redistribution", "redistribution is read off the storage verdict (the old one flag)", LIC,
           '            "redistribution": content_redistribution(member.get("license"), member.get("redistributable"))}',
           '            "redistribution": "permitted" if storable(source, record) else "prohibited"}',
           (PV + "PermissionFacts.test_each_fact_follows_its_own_rule", PV + "PermissionFacts.test_no_fact_is_a_function_of_another"),
           (PV + "PermissionFacts.test_unknown_is_never_permitted",)),
    Mutant("L-adapter-prohibition-ignored", "a source's no-redistribution statement is ignored", LIC,
           "    if adapter_flag is False:\n        return \"prohibited\"", "    if False:\n        return \"prohibited\"",
           (PV + "PermissionFacts.test_each_fact_follows_its_own_rule",), (PV + "PermissionFacts.test_unknown_is_never_permitted",)),
    Mutant("L-merge-least-restrictive", "a merged record takes its least restricted member", LIC,
           "    return {fact: min((p[fact] for p in per_member), key=values.index) for fact, values in order.items()}",
           "    return {fact: max((p[fact] for p in per_member), key=values.index) for fact, values in order.items()}",
           (PV + "PermissionFacts.test_a_merged_record_takes_the_most_restrictive_of_its_members",
            PV + "ReturnedRecords.test_a_merged_find_record_carries_each_members_provenance_and_facts"),
           (PV + "PermissionFacts.test_each_fact_follows_its_own_rule",)),
    Mutant("L-stored-drops-facts", "a stored job result loses the four facts", "research_gateway/core/canonical.py",
           '        out["permissions"] = {k: perms[k] for k in PERMISSION_FACTS}', "        pass",
           (PV + "ReturnedRecords.test_a_merged_find_record_carries_each_members_provenance_and_facts",),
           (PV + "ReturnedRecords.test_a_resolved_record_and_its_cached_copy_carry_the_facts",)),
    Mutant("L-persisted-redistributable", "every persisted row is written redistributable (the old meaning)", "research_gateway/core/cache.py",
           '                     redistribution == "permitted", redistribution, prov.get("metadata_license")),',
           '                     True, redistribution, prov.get("metadata_license")),',
           ("tests.test_cache_dedup.PersistentCache.test_only_storable_members_reach_the_database_and_storage_is_not_redistribution",),
           ("tests.test_cache_dedup.PersistentCache.test_reload_keeps_member_stamps_links_and_attribution_verbatim",), db=True),
    # ---- 2b-repair-9: R8-1, R8-2, R8-3, and the four invariants of the harness (tests/test_invariants.py)
    # R8-1: a `rel` that is no relation-type list is unknown, not an absence
    Mutant("R9-rel-value-unchecked", "a rel value is searched for `next` without being read as a list of relation types", BASE,
           '            if rel is None or "next" not in relation_types(rel[0]):\n', '            if rel is None or "next" not in (rel[0] or "").lower().split():\n',
           (LH + "Reading.test_a_header_that_cannot_be_read_is_neither_a_next_link_nor_the_end",
            LH + "HuggingFace.test_a_header_that_cannot_be_read_never_ends_the_lane", HX + "LinkHeaders.test_generated_headers_are_read_alike"),
           (LH + "Reading.test_a_next_link_is_found_however_the_header_is_written",
            LH + "Reading.test_a_header_read_whole_that_names_no_next_link_is_an_established_end",
            LH + "HuggingFace.test_control_a_header_read_whole_with_no_next_link_is_the_end")),
    Mutant("R9-quoted-string-holds-anything", "a quoted string may hold a control character", BASE,
           "                        elif header[i] not in _QDTEXT:\n", "                        elif False:\n",
           (LH + "Reading.test_a_header_that_cannot_be_read_is_neither_a_next_link_nor_the_end", HX + "LinkHeaders.test_generated_headers_are_read_alike"),
           (LH + "Reading.test_a_next_link_is_found_however_the_header_is_written",)),
    Mutant("R9-target-is-anything", "a link target may hold any character", BASE,
           "        if not uri.is_uri_reference(target):\n", "        if False:\n",
           (LH + "Reading.test_a_header_that_cannot_be_read_is_neither_a_next_link_nor_the_end", HX + "LinkHeaders.test_generated_headers_are_read_alike"),
           (LH + "Reading.test_a_comma_inside_the_target_belongs_to_the_target",)),
    Mutant("R9-continuation-may-drop-the-search", "a continuation that leaves the search parameter out is followed", BASE,
           "    return url if all(named.get(k) == [v] for k, v in same.items()) else None", "    return url if all(named.get(k, [v]) == [v] for k, v in same.items()) else None",
           (LH + "HuggingFace.test_a_next_link_that_names_no_search_is_not_the_continuation", HX + "LinkHeaders.test_generated_headers_are_read_alike"),
           (LH + "HuggingFace.test_a_next_link_with_a_quoted_comma_continues_through_the_router",)),
    # R8-2 and (b): an unreadable container is never an empty one
    Mutant('R9-identifier-not-text-is-none', 'the DOI normaliser reads a number, `false` or a list as no DOI', 'research_gateway/core/identity.py',
           '    if not isinstance(value, str):\n        raise PayloadError(f"{type(value).__name__} where an identifier belongs")\n    return value',
           '    return value if isinstance(value, str) else ""',
           ('tests.test_present_means_typed.Records.test_the_normalisers_take_an_identifier_that_is_not_text_for_unreadable_not_for_none',),
           ('tests.test_present_means_typed.Records.test_a_date_is_text_that_names_a_year_or_nothing',)),
    # (a): a lane ends, or continues, only on what it read
    Mutant("R9-total-below-what-was-read-ends", "a total smaller than the results already read is taken as the count, and the page reaches it", BASE,
           "    return value if isinstance(value, int) and not isinstance(value, bool) and value >= seen else None",
           "    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None",
           (TP + "Readers.test_an_offset_is_a_whole_number_past_where_the_page_started_and_a_total_a_whole_number_no_smaller_than_what_was_read",
            harness("a", "datacite.find (a full page)"), harness("a", "socrata.find (a full page)"), harness("a", "doaj.find (a full page)")),
           (PP + "DataCiteDois.test_ends", PP + "DataCiteDois.test_continues")),
    Mutant("R9-next-offset-need-not-advance", "a next offset that does not advance past the page is a continuation", BASE,
           "    return value if isinstance(value, int) and not isinstance(value, bool) and value > offset else None",
           "    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None",
           (harness("a", "semanticscholar.find (a next offset)"),), (PP + "SemanticScholarSearch.test_continues",)),
    Mutant("R9-loader-ends-on-a-cursor-it-cannot-read", "the Crossref journals loader finishes on a full page whose cursor it cannot read",
           "research_gateway/harvest/registries.py", "            if cursor is None:   # a full page whose continuation", "            if False:   # a full page whose continuation",
           (TP + "Loaders.test_crossref_journals_a_full_page_whose_next_cursor_cannot_be_read_fails_the_load", HX + "RegistryLoaders.test_a_loader_that_cannot_read_where_to_go_on_fails_and_never_finishes_early"),
           (TP + "Loaders.test_datacite_repositories_control_pages_are_read_to_the_last",)),
    # (c): readable members beside an unreadable one survive
    Mutant('R9-first-unreadable-member-ends-the-page', 'the member decoder stops at the first member it cannot read', 'research_gateway/core/payload.py',
           '            except MEMBER_ERRORS:\n                rec = None\n',
           '            except MEMBER_ERRORS:\n                break\n',
           ('tests.test_invariants.Corruptions.test_c_readable_peers_survive__crossref_find__a_full_page',),
           ('tests.test_member_decoding.EveryMemberAlone.test_control_a_readable_member_alone_is_kept_whole', 'tests.test_member_decoding.ThroughTheRouter.test_control_readable_rows_are_complete')),
    Mutant("R9-file-listing-needs-the-whole-dataset", "a Hugging Face file listing builds the whole dataset record first, so a field no file needs can cost the files",
           "research_gateway/adapters/huggingface.py", '    rec = _context(d)\n    # the files are the envelope\'s', '    rec = {"license": _record(d)["license"], "gated": d.get("gated", False)}\n    # the files are the envelope\'s',
           (TP + "DatasetFiles.test_a_garbled_author_or_tags_or_title_does_not_cost_the_files_of_a_hugging_face_repository", harness("c", "huggingface.fetch (a dataset's files)")),
           (TP + "DatasetFiles.test_a_licence_that_cannot_be_read_costs_every_file_because_every_file_carries_it",)),
    # (d): nothing escapes unhandled
    Mutant('R9-record-fields-unchecked', 'make_record carries a field of any kind, so a title that is a number reaches the merge and raises out of the router', 'research_gateway/core/canonical.py',
           '    raise PayloadError(f"a record\'s {name} is {type(value).__name__}, not {belongs}")',
           '    return value',
           ('tests.test_present_means_typed.Records.test_a_field_of_the_wrong_kind_is_unreadable_whatever_its_truth',),
           ('tests.test_present_means_typed.Records.test_control_the_fields_that_are_right_are_kept_and_nothing_is_nothing',)),
    # R8-3: the closed import inventory
    Mutant("R9-parser-re-exported-by-the-client", "the client binds a JSON parser at module level, which an adapter can import from it", BASE,
           "import email.utils\nimport http.client\nimport ipaddress\nimport re\n", "import email.utils\nimport http.client\nimport ipaddress\nimport json\nimport re\n",
           (MI + "Imports.test_the_client_has_no_parser_to_re_export_and_exports_no_module",),
           (MI + "Imports.test_every_other_form_an_import_can_take_is_refused_or_analysed",)),
    Mutant("R9-adapter-imports-by-__import__", "an adapter imports a module by __import__, which no import check can read", "research_gateway/adapters/openaire.py",
           "_TOKEN_LOCK = threading.Lock()", '_TOKEN_LOCK = __import__("threading").Lock()',
           (MI + "Imports.test_every_provider_data_module_imports_only_what_the_inventory_admits",),
           (MI + "Imports.test_every_other_form_an_import_can_take_is_refused_or_analysed",)),
    Mutant("R9-module-attribute-not-analysed", "the import check does not look at what an adapter reaches through a package module it imports as a module",
           "tests/inventory.py", "                    if use.attr not in defined_names(imported[node.id]):", "                    if False:",
           (MI + "Imports.test_a_parser_an_admitted_module_imports_is_refused_and_so_is_the_reviewers_complete_mutant",
            MI + "Imports.test_every_other_form_an_import_can_take_is_refused_or_analysed"),
           (MI + "Imports.test_control_a_module_used_for_what_it_defines_is_not_refused", MI + "Imports.test_every_provider_data_module_imports_only_what_the_inventory_admits")),
    Mutant("R9-module-used-as-a-value-not-refused", "the import check admits a package module passed on, aliased or given to getattr",
           "tests/inventory.py", '                    out.append((rel, f"{node.id} (a module, used as a value: what it reaches cannot be bounded)"))', "                    pass",
           (MI + "Imports.test_every_other_form_an_import_can_take_is_refused_or_analysed",),
           (MI + "Imports.test_control_a_module_used_for_what_it_defines_is_not_refused", MI + "Imports.test_a_parser_an_admitted_module_imports_is_refused_and_so_is_the_reviewers_complete_mutant")),
    Mutant("R9-assigned-alias-is-a-definition", "a name a module assigns from what it imports is offered as one it defines (`loads = json.loads`)",
           "tests/inventory.py", "                ast.literal_eval(node.value)", "                ast.literal_eval('0')",
           (MI + "Imports.test_every_other_form_an_import_can_take_is_refused_or_analysed",),
           (MI + "Imports.test_control_the_permitted_imports_are_not_refused", MI + "Imports.test_every_provider_data_module_imports_only_what_the_inventory_admits")),
    # R9-1: a URI is what RFC 3986 says
    Mutant("R9-target-is-a-list-of-characters", "a link target is checked against a list of allowed characters, not the URI-reference grammar", BASE,
           "        if not uri.is_uri_reference(target):\n", "        if re.fullmatch(r\"[A-Za-z0-9\\-._~:/?#\\[\\]@!$&'()*+,;=%]*\", target) is None:\n",
           (LH + "Uris.test_a_target_that_is_not_a_uri_reference_is_unreadable_wherever_it_stands",),
           (LH + "Uris.test_control_the_relation_types_and_targets_that_are_uris_are_read", LH + "Reading.test_a_comma_inside_the_target_belongs_to_the_target")),
    Mutant("R9-relation-type-is-a-list-of-characters", "an extension relation type is checked against a forbidden-character rule, not the URI grammar", BASE,
           "_REGISTERED_REL.fullmatch(p) or uri.is_uri(p)", "_REGISTERED_REL.fullmatch(p) or re.fullmatch(r\"[A-Za-z][A-Za-z0-9+.\\-]*:[^\\s\\\"<>\\\\^`{|}\\x00-\\x1f\\x7f]*\", p)",
           (LH + "Uris.test_a_relation_type_that_is_not_a_uri_is_unreadable_not_another_relation",),
           (LH + "Uris.test_control_the_relation_types_and_targets_that_are_uris_are_read", LH + "Reading.test_a_next_link_is_found_however_the_header_is_written")),
    Mutant("R9-relative-target-is-not-resolved", "a relative next target is taken as written, not resolved against the URL asked (RFC 8288 §3.1)", BASE,
           "            url = uri.resolve(resp.url, target)\n", "            url = target\n",
           (LH + "Context.test_a_relative_target_is_resolved_the_way_the_rfc_says", LH + "Reading.test_a_relative_target_is_resolved_against_the_url_asked"),
           (LH + "Reading.test_a_comma_inside_the_target_belongs_to_the_target", LH + "Uris.test_control_the_relation_types_and_targets_that_are_uris_are_read")),
    Mutant("R9-next-link-to-itself-is-followed", "a next link that is the request itself is a continuation", BASE,
           "or uri.same_resource(url, resp.url):\n", ":\n",
           (LH + "Context.test_a_next_link_that_is_the_request_itself_is_neither_followed_nor_an_end", LH + "Context.test_a_next_link_to_itself_is_a_lower_bound_through_the_router"),
           (LH + "Context.test_a_relative_target_is_resolved_the_way_the_rfc_says", LH + "Reading.test_a_next_link_is_found_however_the_header_is_written")),
    Mutant("R9-anchor-is-ignored", "a next link whose anchor puts its context at another resource is this listing's next page", BASE,
           "            if (anchor is not None and not uri.same_resource(uri.resolve(resp.url, anchor[0]), resp.url, fragment=True)) or uri.same_resource(url, resp.url):\n",
           "            if uri.same_resource(url, resp.url):\n",
           (LH + "Context.test_a_next_link_whose_context_is_another_resource_is_neither_followed_nor_an_end",),
           (LH + "Context.test_an_anchor_that_is_the_request_changes_nothing_and_one_that_is_not_a_uri_makes_the_header_unreadable",
            LH + "Context.test_a_next_link_that_is_the_request_itself_is_neither_followed_nor_an_end")),
    Mutant("R9-anchor-fragment-is-the-same-context", "an anchor that is a fragment of the request is the request's own context", BASE,
           "uri.resolve(resp.url, anchor[0]), resp.url, fragment=True)", "uri.resolve(resp.url, anchor[0]), resp.url)",
           (LH + "Context.test_a_next_link_whose_context_is_another_resource_is_neither_followed_nor_an_end",),
           (LH + "Context.test_an_anchor_that_is_the_request_changes_nothing_and_one_that_is_not_a_uri_makes_the_header_unreadable",)),
    Mutant("R9-anchor-syntax-unchecked", "an anchor that is no URI-reference is resolved as if it were one", BASE,
           "            if anchor is not None and (anchor[0] is None or not uri.is_uri_reference(anchor[0])):\n", "            if anchor is not None and anchor[0] is None:\n",
           (LH + "Context.test_an_anchor_that_is_the_request_changes_nothing_and_one_that_is_not_a_uri_makes_the_header_unreadable",),
           (LH + "Context.test_a_next_link_whose_context_is_another_resource_is_neither_followed_nor_an_end", LH + "Reading.test_a_next_link_is_found_however_the_header_is_written")),
    # R9-2: a present value is read as what it is before a fallback chooses
    Mutant("R9-publisher-not-mapped", "the DataCite record leaves out the publisher the provider states", "research_gateway/adapters/datacite.py",
           'extra={"publisher": publisher, "resource_type": rtype,', 'extra={"resource_type": rtype,',
           (TF + "Publisher.test_the_record_carries_what_the_provider_states", "tests.test_oracle.ExpectedCanonicalFields.test_the_valid_answer_of_every_operation_says_what_the_fixture_says"),
           (TF + "Publisher.test_a_publisher_that_is_not_text_costs_its_member",)),
    Mutant("R9-agency-unreadable-is-remembered", "an agency answer that cannot be read is remembered as the prefix's unknown", "research_gateway/core/identity.py",
           '            return "unknown"\n        agency = agency or "unknown"\n', '            agency = None\n        agency = agency or "unknown"\n',
           (TF + "RegistrationAgency.test_an_agency_that_is_not_text_is_neither_one_nor_remembered",),
           (TF + "RegistrationAgency.test_control_text_is_the_agency_and_no_agency_is_unknown",)),
    # R9-5: a dimension browse is the flow's own structure's
    Mutant('R9-browse-merges-the-structures-of-a-message', 'a dimension browse reads the dimensions of every data structure in the message', 'research_gateway/core/sdmx.py',
           '    answers = {tuple(_dimension_ids(el)) for el in found}\n',
           '    answers = {tuple(d for e in decoded["**DataStructure"] for d in _dimension_ids(e)) for el in found}\n',
           ('tests.test_station_contract.CatalogDiscovery.test_a_browse_names_the_dimensions_of_the_flows_own_structure_and_never_merges_the_structures_of_a_message', 'tests.test_oracle.Catalogues.test_a_browse_names_the_dimensions_of_the_flows_own_data_structure_in_key_order'),
           ('tests.test_station_contract.CatalogDiscovery.test_ecb_dataflows_then_dimensions_in_key_order',)),
    # openml.fetch url members (2b-repair-10b): the harness's mixed-member draw takes what its own classifier calls a bad member
    Mutant("R9-mixed-members-draw-a-link-the-provider-leaves-out", "the harness draws null and empty text as an unreadable member of a url-member operation", "tests/test_invariants.py",
           "                        bad = [v for v in BAD_MEMBERS if classify(m, m.path, v, optional, keyed, op.leaf, op.bare_row) == BAD]\n",
           "                        bad = list(BAD_MEMBERS)\n",
           ("tests.test_oracle.MixedMembersOtherSeeds.test_the_mixed_members_hold_at_other_seeds",),
           (HX + "MixedMembers.test_the_members_that_are_readable_are_exactly_the_ones_kept",)),
    # R10-1 (2b-repair-11b): every alternative is read before one is chosen. Each mutant puts back the lazy `a or b` (or the early return) at ONE site; the oracle's
    # cases (tests.test_oracle.FallbackAlternatives) and tests/test_alternatives.py are the killers, and a control reads the same site with valid values.
    Mutant("R10-unpaywall-unreadable-best-location-is-ignored", "a best location that cannot be read is ignored beside listed locations, and the lane stays complete", "research_gateway/adapters/unpaywall.py",
           '    if best_unreadable:\n        items.append(None)',
           '    if False:\n        items.append(None)',
           (AL + "OtherFormsOfTheSameShape.test_unpaywall_a_best_location_that_cannot_be_read_costs_completeness_and_not_the_listed_locations",),
           (AL + "OtherFormsOfTheSameShape.test_unpaywall_control_the_best_location_stands_in_for_none_listed_and_is_otherwise_left_alone",)),
    # (R10-sdmx datasets()'s `_wrapper(j)`-first read has no mutant: ecb.data reads sdmx.structure(j), which reads the same wrapper first, on every path that reads data sets, so removing it is equivalent)
    # R10-2: the browse is the requested flow's own
    Mutant("R10-bis-structure-is-guessed-from-the-flow-id", "a BIS flow that names no structure is given the structure of its own id", "research_gateway/adapters/bis.py",
           '    ref = flow["structure"]\n    if not ref.get("id"):\n        return {"entries": [], "capability_fact": f"dataflow {within!r}: names no data structure — refusing to invent a series template"}\n',
           '    ref = {**flow["structure"], "id": flow["structure"].get("id") or within}\n',
           (FB + "BrowseOfTheFlowAskedFor.test_a_flow_that_names_no_structure_yields_no_template_and_is_not_guessed_from_its_own_id",),
           (ST + "CatalogDiscovery.test_ecb_dataflows_then_dimensions_in_key_order",)),
    Mutant("R10-ecb-structure-is-guessed-from-the-flow-id", "an ECB flow that names no structure is given the structure of its own id", "research_gateway/adapters/ecb.py",
           '    ref = flow["structure"]\n    if not ref.get("id"):\n        return {"entries": [], "capability_fact": f"dataflow {within!r}: names no data structure — refusing to invent a series template"}\n',
           '    ref = {**flow["structure"], "id": flow["structure"].get("id") or within}\n',
           (FB + "BrowseOfTheFlowAskedFor.test_a_flow_that_names_no_structure_yields_no_template_and_is_not_guessed_from_its_own_id",),
           (ST + "CatalogDiscovery.test_ecb_dataflows_then_dimensions_in_key_order",)),
    Mutant("R10-ambiguous-flow-is-read-as-the-first", "a message that defines the requested flow twice, differently, is read as its first definition", "research_gateway/core/sdmx.py",
           '    if len(distinct) > 1:\n        raise PayloadError(f"an SDMX answer that defines the dataflow {wanted!r} {len(distinct)} times, differently: nothing says which one is meant")\n',
           '',
           (OR + "FlowBinding.test_a_flow_that_cannot_be_bound_yields_no_entry_and_no_template", FB + "SelectionOfTheFlow.test_the_same_definition_twice_is_one_flow_and_a_different_one_is_ambiguous"),
           (FB + "SelectionOfTheFlow.test_the_flow_asked_for_is_the_one_found_by_its_id", FB + "BrowseOfTheFlowAskedFor.test_control_the_same_message_without_the_second_definition_is_read")),
    # R10-3: a listing whose every flow is unnamed is not a catalogue (Astra's mutant: the `identified(...)` validation deleted from the listing)
    Mutant("R10-bis-listing-of-unnamed-flows-is-a-catalogue", "the BIS dataflow listing no longer refuses a listing in which no flow names itself", "research_gateway/adapters/bis.py",
           '        flows = identified(SOURCE_ID, flows, [f for f in flows if f["id"]])   # a flow that names nothing is skipped; none that does is not a catalogue\n', '',
           (OR + "UnnamedFlows.test_a_listing_that_names_no_flow_is_unobserved_with_no_count",),
           (OR + "UnnamedFlows.test_the_readable_control_is_read", ST + "CatalogDiscovery.test_bis_dataflow_listing")),
    Mutant("R10-ecb-listing-of-unnamed-flows-is-a-catalogue", "the ECB dataflow listing no longer refuses a listing in which no flow names itself", "research_gateway/adapters/ecb.py",
           '        flows = identified(SOURCE_ID, flows, [f for f in flows if f["id"]])   # a flow that names nothing is skipped; none that does is not a catalogue\n', '',
           (OR + "UnnamedFlows.test_a_listing_that_names_no_flow_is_unobserved_with_no_count",),
           (OR + "UnnamedFlows.test_the_readable_control_is_read", ST + "CatalogDiscovery.test_ecb_dataflows_then_dimensions_in_key_order")),
]


# 2b-repair-12: the guards that moved into the schema-first decoder (tools/gen2_gateway_schema_mutants.py)
from gen2_gateway_schema_mutants import build as _schema_mutants  # noqa: E402

MUTANTS.extend(_schema_mutants(Mutant))

# 2b-repair-13a: since a field declared `any_()` is handed over Passive (core/payload.py), the mutants that restore an old lazy or loose read by declaring a field `any_()` and reading it
# as before would only make the first read raise PassiveRead — the Passive rule, which tests/test_declarations.py's own mutants kill, standing in for the guard each of them is about. They
# restore the defect they name by ALSO making `any_()` readable again: the same three edits to the decoder (each `any_()` field a bare value, as before), then the loosened declaration
# and its read as the mutant always had them. A mutant carrying them has a target per edit.
SCHEMA_FILE = "research_gateway/core/schema.py"
LEGACY_ANY = ((SCHEMA_FILE, '    if k == "any":\n        return Passive(v)\n', '    if k == "any":\n        return v\n'),
              (SCHEMA_FILE, '        return Passive(fs.default if missing else None)\n', '        return fs.default if missing else None\n'),
              (SCHEMA_FILE, '    if k == "any":\n        return Passive(None)\n', '    if k == "any":\n        return None\n'))


def _with_readable_any(m):
    from dataclasses import replace
    olds = m.old if isinstance(m.old, tuple) else (m.old,)
    news = m.new if isinstance(m.new, tuple) else (m.new,)
    targets = m.target if isinstance(m.target, tuple) else (m.target,) * len(olds)
    return replace(m, target=(*targets, *(t for t, _, _ in LEGACY_ANY)), old=(*olds, *(o for _, o, _ in LEGACY_ANY)), new=(*news, *(n for _, _, n in LEGACY_ANY)))


MUTANTS[:] = [_with_readable_any(m) if ("S.any_(" in (m.new if isinstance(m.new, str) else " ".join(m.new))
                                        or m.mid == "D-a-field-is-read-as-the-same-kind-whatever-its-sibling-says") else m for m in MUTANTS]

# 2b-repair-13a: the decoder's completed contract (tools/gen2_gateway_contract_mutants.py)
from gen2_gateway_contract_mutants import build as _contract_mutants  # noqa: E402

MUTANTS.extend(_contract_mutants(Mutant))

# 2b-repair-13c: the byte openers (tools/gen2_gateway_opener_mutants.py)
from gen2_gateway_opener_mutants import build as _opener_mutants  # noqa: E402

MUTANTS.extend(_opener_mutants(Mutant))

# 2b-repair-13c: opaque provenance (tools/gen2_gateway_opaque_mutants.py)
from gen2_gateway_opaque_mutants import build as _opaque_mutants  # noqa: E402

MUTANTS.extend(_opaque_mutants(Mutant))

# 2b-repair-14: the transport's framing completion (tools/gen2_gateway_transport_mutants.py)
from gen2_gateway_transport_mutants import build as _transport_mutants  # noqa: E402

MUTANTS.extend(_transport_mutants(Mutant))

# 2b-repair-14: XML interpretation (tools/gen2_gateway_xml_mutants.py)
from gen2_gateway_xml_mutants import build as _xml_mutants  # noqa: E402

MUTANTS.extend(_xml_mutants(Mutant))

# 2b-repair-14: the snapshot loader's failure scope (tools/gen2_gateway_snapshot_mutants.py)
from gen2_gateway_snapshot_mutants import build as _snapshot_mutants  # noqa: E402

MUTANTS.extend(_snapshot_mutants(Mutant))

# 2b-repair-14: the one owned inventory (tools/gen2_gateway_inventory_mutants.py)
from gen2_gateway_inventory_mutants import build as _inventory_mutants  # noqa: E402

MUTANTS.extend(_inventory_mutants(Mutant))
