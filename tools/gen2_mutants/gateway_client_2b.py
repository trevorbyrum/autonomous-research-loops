"""Mutants of task 2b: the engine's gateway client (gen2/gateway_client), each guard
removed or weakened alone, and (task 2b-repair A6) the router's record_gateway_facts.
Killers are in gen2/tests/test_gateway_client.py, which replays the gateway's recorded
answers and records the results through a real router.

Task 2b-repair: `2B-metadata-only-kept` enforced the rejected conversion of metadata_only
into an empty search (Astra's test 115); it is replaced by the metadata-only family below,
whose killers require the named state instead. `2B-pages-rounded-up` guarded the merged
multi-page observation, which is gone (each page is its own observation, A2); the page
family below replaces it.

The gateway service's own guards are a separate inventory (tools/gen2_gateway_mutants.py,
run by tools/gen2_gateway_mutations.py on the gateway's suite).
"""
from __future__ import annotations

from .base import Mutation

GC = "test_gateway_client."
RA, UA, TO, RR, OH = GC + "RecordedAnswers.", GC + "UnreadableAnswers.", GC + "TransportOutcomes.", GC + "RecordedByTheRouter.", GC + "OverRealHttp."
GF = GC + "GatewayFactsCommand."
OBS, CLI, CAPS, CANON = "gen2/gateway_client/observe.py", "gen2/gateway_client/client.py", "gen2/router/capabilities.py", "gen2/core/canonical.py"
PAGE_DOC = 'request={"lane": entry["source"], "page": page, "request": sent},'

MUTATIONS: list[Mutation] = [
    *(Mutation(f"2B-{key}", "2b", desc, tuple(killers), target=target, old=old, new=new)
      for key, desc, killers, target, old, new in (
          ("count-without-identities", "a lane's count need not match the identities it names", (UA + "test_a_count_without_its_identities_is_not_a_count",), OBS,
           "    if not isinstance(retrieved, list) or len(retrieved) != count or", "    if not isinstance(retrieved, list) or"),
          ("unobserved-counted", "an unobserved lane may carry a count", (UA + "test_a_count_without_its_identities_is_not_a_count",), OBS,
           '        if count is not None or entry.get("retrieved") is not None:', "        if False:"),
          ("vocabulary-unchecked", "a coverage or completeness outside the vocabulary is accepted", (UA + "test_a_count_without_its_identities_is_not_a_count",), OBS,
           '    if cov not in COVERAGE or comp not in ("complete", "partial", "unobserved"):', "    if False:"),
          ("partial-unexplained", "a partial set without its reason is accepted", (UA + "test_a_count_without_its_identities_is_not_a_count",), OBS,
           '    if comp == "partial" and err is None:', "    if False:"),
          ("repeat-counted-twice", "a record the provider repeated is two candidates", (UA + "test_a_repeated_identity_is_one_candidate",), OBS,
           "        if identity not in seen:", "        if True:"),
          # 2b-repair A1: metadata_only is its own state, naming its record
          ("metadata-only-unnamed", "metadata_only naming no record is kept as it stands (the store refuses it)",
           (UA + "test_metadata_only_names_the_held_record", UA + "test_metadata_only_naming_nothing_is_unreadable_never_an_empty_query",
            RR + "test_metadata_only_is_admissible_as_its_own_state"), OBS,
           '    if entry.get("coverage") != "metadata_only" or entry.get("retrieved"):\n        return entry', "    if True:\n        return entry"),
          ("metadata-only-held-ignored", "an enrich's held identity is not the record its metadata_only lane names",
           (UA + "test_metadata_only_names_the_held_record", RR + "test_metadata_only_is_admissible_as_its_own_state"), OBS,
           "    if not (isinstance(held, str) and held):", "    if True:"),
          ("metadata-only-empty", "metadata_only naming nothing becomes an empty search (the conversion test 115 enforced)",
           (UA + "test_metadata_only_naming_nothing_is_unreadable_never_an_empty_query",), OBS,
           '        return unobserved(entry["source"], "unknown", "payload_invalid")\n    return {**entry, "count": 1',
           '        return {**entry, "coverage": "searched_empty"}\n    return {**entry, "count": 1'),
          # 2b-repair A1: an uncaptured answer is a lower bound, never complete negative evidence
          ("uncaptured-empty-kept", "an uncaptured empty lane stays an empty search (made partial, which the store refuses)",
           (RA + "test_an_uncaptured_answer_is_a_lower_bound_never_negative_evidence", RR + "test_an_uncaptured_answer_is_recorded_as_a_lower_bound",
            TO + "test_a_poll_not_attributed_to_this_caller_or_not_captured_degrades"), OBS,
           '    if entry["coverage"] == "searched_empty":\n        return unobserved(entry["source"], "unknown", "telemetry_missing")',
           '    if False:\n        return unobserved(entry["source"], "unknown", "telemetry_missing")'),
          ("uncaptured-complete", "the lanes of an answer the gateway did not capture stay complete",
           (RA + "test_an_uncaptured_answer_is_a_lower_bound_never_negative_evidence", RR + "test_an_uncaptured_answer_is_recorded_as_a_lower_bound",
            TO + "test_a_poll_not_attributed_to_this_caller_or_not_captured_degrades"), CLI,
           '            result["lanes"].append(entry if captured else observe.uncaptured(entry))', '            result["lanes"].append(entry)'),
          ("uncaptured-silent", "a request the gateway did not capture durably raises no telemetry loss",
           (RA + "test_an_uncaptured_answer_is_a_lower_bound_never_negative_evidence",), CLI,
           '            lost(str(obs.get("capture_loss") or "the gateway did not acknowledge a durable request row"))', "            pass"),
          ("poll-capture-ignored", "a poll the gateway did not record durably leaves the answer captured",
           (TO + "test_a_poll_not_attributed_to_this_caller_or_not_captured_degrades",), CLI,
           "            if not _captured(poll):\n                captured = False", "            if False:\n                captured = False"),
          # 2b-repair A1: the whole answer variant
          ("records-unchecked", "a dispatched answer without its records list is read as one with none",
           (UA + "test_a_success_that_is_not_a_gateway_answer_is_unreadable",), CLI,
           "        if not isinstance(lanes, list) or not isinstance(records, list):",
           "        records = records if isinstance(records, list) else []\n        if not isinstance(lanes, list):"),
          ("lane-less-empty", "an answer without lanes that is not a record-cache hit is an empty search",
           (UA + "test_an_answer_without_lanes_is_only_a_record_cache_hit_that_says_so",), CLI,
           "            lanes = _record_cache_lanes(doc, sent)\n",
           '            lanes = _record_cache_lanes(doc, sent) or [{"source": observe.GATEWAY_LANE, "coverage": "searched_empty", '
           '"completeness": "complete", "count": 0, "retrieved": []}]\n'),
          ("cache-hit-unmarked", "an answer without lanes is read as a record-cache hit without saying it is one",
           (UA + "test_an_answer_without_lanes_is_only_a_record_cache_hit_that_says_so",), CLI,
           '    if sent.get("request_type") != "resolve" or doc.get("cache_hit") is not True or doc.get("served_from") != "record_cache" \\',
           '    if sent.get("request_type") != "resolve" \\'),
          ("named-lane-dropped", "a named lane the answer leaves out is not observed as unknown",
           (UA + "test_a_named_lane_the_answer_leaves_out_is_unobserved",), CLI,
           '        result["lanes"] += [observe.unobserved(sid, "unknown", "payload_invalid") for sid in sent.get("lanes") or [] if sid not in answered]',
           '        result["lanes"] += []'),
          # identity (H-1, H-5; 2b-repair A2)
          ("fact-unlinked", "a secrets-failing observation does not name its fact",
           (RA + "test_a_failing_secrets_read_carries_its_fact_and_no_count", RR + "test_a_secrets_failure_is_recorded_through_the_routers_own_commands"), OBS,
           '"capability_fact_id": fact_id if entry.get("error_class") == "secrets_backend_failing" else None,', '"capability_fact_id": None,'),
          ("id-not-deterministic", "an observation's id depends on the run, not on its identity",
           (RA + "test_the_same_answer_twice_is_the_same_observation",), OBS,
           '    oid = "obs_" + _digest("observation", invocation_id, attempt, rid)', '    oid = "obs_" + _digest("observation", invocation_id, attempt, rid, id(entry))'),
          ("id-includes-links", "an observation's id changes with the obligations it is linked to",
           (RA + "test_the_same_answer_twice_is_the_same_observation",), OBS,
           '    oid = "obs_" + _digest("observation", invocation_id, attempt, rid)', '    oid = "obs_" + _digest("observation", invocation_id, attempt, rid, obligation_ids)'),
          ("delivery-in-identity", "how an answer was delivered is part of the request's identity",
           (RR + "test_a_delivery_change_is_never_a_second_observation",), CLI,
           PAGE_DOC, 'request={"lane": entry["source"], "page": page, "request": sent, "delivery": answer["delivery"]},'),
          ("echo-is-identity", "the request's identity is the gateway's echo (a failure has none: different requests merge)",
           (RR + "test_different_failed_requests_are_different_observations",), CLI,
           PAGE_DOC, 'request={"lane": entry["source"], "page": page, "request": answer["effective"]},'),
          ("page-request-first", "every page's observation names the first page's request (the failed cursor is lost)",
           (RA + "test_each_page_is_its_own_observation_and_a_failed_one_keeps_its_cursor",
            RR + "test_a_failed_continuation_is_its_own_observation_with_its_cursor"), CLI,
           PAGE_DOC, 'request={"lane": entry["source"], "page": page, "request": request},'),
          ("echo-unchecked", "an answer for another invocation or attempt is attributed to this one",
           (UA + "test_an_answer_for_another_invocation_is_not_attributed",), CLI,
           "        if not _echoes(obs, ctx):\n            # an answer", "        if False:\n            # an answer"),
          ("echo-bool-attempt", "an attempt echoed as true is read as attempt 1",
           (UA + "test_an_answer_for_another_invocation_is_not_attributed",), CLI,
           'type(obs.get("attempt")) is int and obs["attempt"] == ctx["attempt"]', 'obs.get("attempt") == ctx["attempt"]'),
          ("envelope-unchecked", "a success that is not a gateway answer is read as one",
           (UA + "test_a_success_that_is_not_a_gateway_answer_is_unreadable",), CLI,
           '        if resp_headers.get("x-research-gateway") != "result" or "json" not in resp_headers.get("content-type", ""):', "        if False:"),
          ("transport-failure-empty", "nothing answering is recorded as an empty search", (TO + "test_nothing_answered_is_unknown_never_empty",
                                                                                          TO + "test_named_lanes_each_get_their_unknown"), CLI,
           '            return failed("unknown", error)', '            return failed("searched_empty", None)'),
          ("policy-refusal-empty", "a request the policy refused is recorded as an empty search", (RA + "test_a_grant_and_the_policy_it_binds",), CLI,
           '           403: ("not_searched", None),', '           403: ("searched_empty", None),'),
          ("queued-unpolled", "a queued answer is read as it stands, without polling", (TO + "test_a_queued_answer_is_polled_to_its_result_under_this_invocation",
                                                                                        TO + "test_a_queued_answer_is_polled_and_a_job_that_never_ends_is_a_timeout"), CLI,
           '        if doc.get("status") in ("queued", "running"):', "        if False:"),
          ("failed-job-read", "a failed job's result is read like a done one's", (TO + "test_a_queued_answer_is_polled_and_a_job_that_never_ends_is_a_timeout",), CLI,
           '            if job.get("status") != "done" or not isinstance(job.get("result"), dict):', '            if not isinstance(job.get("result"), dict):'),
          # 2b-repair A5: every poll is this caller's
          ("poll-uncorrelated", "a poll carries no invocation or attempt", (TO + "test_a_queued_answer_is_polled_to_its_result_under_this_invocation",), CLI,
           '            status, job, _ = self._exchange("GET", f"/v1/jobs/{job_id}", None, ctx["token"], _headers(ctx))',
           '            status, job, _ = self._exchange("GET", f"/v1/jobs/{job_id}", None, ctx["token"])'),
          ("poll-echo-unchecked", "a poll's answer for another caller is attributed to this one",
           (TO + "test_a_poll_not_attributed_to_this_caller_or_not_captured_degrades",), CLI,
           "                return job, (obs if _echoes(obs, ctx) else None)", "                return job, obs"),
          ("redirects-followed", "the default transport follows a redirect (the bearer token goes elsewhere)", (OH + "test_a_redirect_is_never_followed",), CLI,
           "_OPENER = urllib.request.build_opener(_NoRedirect)", "_OPENER = urllib.request.build_opener()"),
          # 2b-repair A6: the gateway's facts through the router's own command, before the observations naming them
          ("facts-not-recorded", "the facts a search reported are not among the router's requests",
           (RR + "test_a_secrets_failure_is_recorded_through_the_routers_own_commands",), OBS,
           '    return [("record_gateway_facts", {**who, "facts": batch}) for batch in batches] + [', "    return [] + ["),
          ("fact-id-unchecked", "a gateway fact's id need not be its content's", (GF + "test_what_is_not_a_gateway_fact_is_refused",), CAPS,
           '                if fact["fact_id"] != canonical.gateway_fact_id(fact):', "                if False:"),
          ("fact-namespace-open", "a gateway fact may name any capability, not only gateway.*", (GF + "test_what_is_not_a_gateway_fact_is_refused",), CAPS,
           '"^gateway\\\\.[a-z0-9][a-z0-9_.-]{0,62}$"', '"^[a-z].*$"'),
          # 2b-repair-2 R2: an episode's snapshots (the id is the snapshot's; another state is another episode)
          ("fact-id-episode-only", "a gateway fact's id is its episode's alone: a later snapshot of an ongoing outage replays as the stale one",
           (RR + "test_an_outage_that_widens_is_recorded_snapshot_by_snapshot", GF + "test_a_later_snapshot_of_the_episode_supersedes_it_and_keeps_its_onset"),
           CANON, '["capability", fact["capability"], fact["since"], fact["state"], fact["revision"], fact["detail"], fact["last_success_at"],\n'
           '         sorted(fact["affected_lanes"])]', '["capability", fact["capability"], fact["since"]]'),
          ("fact-lanes-ordered", "a snapshot's affected lanes are a list: the same lanes in another order are another snapshot",
           (GF + "test_a_later_snapshot_of_the_episode_supersedes_it_and_keeps_its_onset",), CANON,
           '         sorted(fact["affected_lanes"])]', '         list(fact["affected_lanes"])]'),
          ("fact-state-changes-in-episode", "another state since the current episode's instant supersedes it", (GF + "test_what_is_not_a_gateway_fact_is_refused",), CAPS,
           '            if current is not None and instant(current["since"]) == instant(fact["since"]) and current["state"] != fact["state"]:',
           "            if False:"),
          ("facts-one-command", "two snapshots of one capability from one search's pages share a command (the router refuses it)",
           (RR + "test_pages_answered_under_two_snapshots_record_each_in_page_order",), OBS,
           '        if not batches or any(f["capability"] == fact["capability"] for f in batches[-1]):', "        if not batches:"),
          ("fact-older-recorded", "an older episode is recorded behind the current fact", (GF + "test_a_later_episode_supersedes_and_an_earlier_one_is_refused",), CAPS,
           '            if current is not None and instant(current["since"]) > instant(fact["since"]):', "            if False:"),
          ("fact-not-superseding", "a new fact leaves its capability's current fact current (the one-current index refuses it)",
           (GF + "test_a_later_episode_supersedes_and_an_earlier_one_is_refused",), CAPS,
           '            if current is not None and not behind:\n                self._store.update("capability_facts", {"fact_id": current["fact_id"]}, '
           '{"superseded_by_fact_id": fact["fact_id"], **_successor(fact)})',
           '            if False:\n                self._store.update("capability_facts", {"fact_id": current["fact_id"]}, '
           '{"superseded_by_fact_id": fact["fact_id"], **_successor(fact)})'),
          # 2b-repair-3 R2: an episode's snapshots ordered by their revision, whenever the router hears of them
          ("fact-id-without-revision", "a snapshot's id leaves out its revision: a return to earlier contents replays as the earlier snapshot",
           (RR + "test_an_outage_that_says_again_what_it_said_before_is_current_as_said_last",
            GF + "test_an_earlier_revision_recorded_late_is_kept_behind_the_current_fact"), CANON,
           'fact["state"], fact["revision"], fact["detail"]', 'fact["state"], fact["detail"]'),
          ("fact-order-by-arrival", "an earlier revision recorded late displaces the current fact (the last recorded is current)",
           (GF + "test_an_earlier_revision_recorded_late_is_kept_behind_the_current_fact",), CAPS,
           '            behind = current is not None and instant(current["since"]) == instant(fact["since"]) and current["revision"] > fact["revision"]',
           "            behind = False"),
          ("fact-revision-twin", "one revision of an episode may be recorded with other contents", (GF + "test_what_is_not_a_gateway_fact_is_refused",), CAPS,
           "            if twin is not None:", "            if False:"),
          ("fact-revision-any", "a reported fact's revision need only be present", (RA + "test_a_fact_without_its_revision_is_no_fact",), OBS,
           '            or type(fact.get("revision")) is not int or not 1 <= fact["revision"] <= canonical.INT_BOUND:',
           '            or fact.get("revision") is None:'),
          ("fact-unfenced", "a gateway fact is recorded without a current lease", (GF + "test_only_a_running_invocation_records_but_a_lost_reply_replays",), CAPS,
           '        self._require_current_lease(inv, now)\n        if self._one("queue_entries", {"topic_id": inv["topic_id"]})["paused_at"] is not None:\n'
           '            raise Refusal("topic_paused", f"{inv[\'topic_id\']} is paused")',
           '        if self._one("queue_entries", {"topic_id": inv["topic_id"]})["paused_at"] is not None:\n'
           '            raise Refusal("topic_paused", f"{inv[\'topic_id\']} is paused")'),
      )),
    # 2b-repair-3 R2, Astra's reproduction 1: two recorder processes over one durable store (the kill rests on the children)
    Mutation("2B-fact-order-by-arrival-two-processes", "2b", "a delayed write from another process displaces the newer snapshot it arrived after",
             (RR + "test_a_report_recorded_after_a_newer_one_never_displaces_it",), target=CAPS, via_child=True,
             old='            behind = current is not None and instant(current["since"]) == instant(fact["since"]) and current["revision"] > fact["revision"]',
             new="            behind = False"),
]
