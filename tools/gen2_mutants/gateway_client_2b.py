"""Mutants of task 2b: the engine's gateway client (gen2/gateway_client), each guard
removed or weakened alone. Killers are in gen2/tests/test_gateway_client.py, which
replays the gateway's recorded answers and records the results through a real router.

The gateway service's own guards are a separate inventory (tools/gen2_gateway_mutants.py,
run by tools/gen2_gateway_mutations.py on the gateway's suite).
"""
from __future__ import annotations

from .base import Mutation

GC = "test_gateway_client."
RA, UA, TO, RR, OH = GC + "RecordedAnswers.", GC + "UnreadableAnswers.", GC + "TransportOutcomes.", GC + "RecordedByTheRouter.", GC + "OverRealHttp."
OBS, CLI = "gen2/gateway_client/observe.py", "gen2/gateway_client/client.py"

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
          ("metadata-only-kept", "metadata_only with nothing returned stays metadata_only (the store refuses it)",
           (UA + "test_metadata_only_with_nothing_returned_is_an_empty_query",), OBS,
           '    if coverage == "metadata_only" and not count:', "    if False:"),
          ("fact-unlinked", "a secrets-failing observation does not name its fact",
           (RA + "test_a_failing_secrets_read_carries_its_fact_and_no_count", RR + "test_a_secrets_failure_is_recorded_against_its_fact"), OBS,
           '"capability_fact_id": fact_id if entry.get("error_class") == "secrets_backend_failing" else None,', '"capability_fact_id": None,'),
          ("id-not-deterministic", "an observation's id depends on the run, not on its identity",
           (RA + "test_the_same_answer_twice_is_the_same_observation",), OBS,
           '    oid = "obs_" + _digest("observation", invocation_id, attempt, rid)', '    oid = "obs_" + _digest("observation", invocation_id, attempt, rid, id(entry))'),
          ("id-includes-links", "an observation's id changes with the obligations it is linked to",
           (RA + "test_the_same_answer_twice_is_the_same_observation",), OBS,
           '    oid = "obs_" + _digest("observation", invocation_id, attempt, rid)', '    oid = "obs_" + _digest("observation", invocation_id, attempt, rid, obligation_ids)'),
          ("echo-unchecked", "an answer for another invocation or attempt is attributed to this one",
           (UA + "test_an_answer_for_another_invocation_is_not_attributed",), CLI,
           '        if (obs.get("invocation_id"), obs.get("attempt")) != (ctx["invocation_id"], ctx["attempt"]):', "        if False:"),
          ("envelope-unchecked", "a success that is not a gateway answer is read as one",
           (UA + "test_a_success_that_is_not_a_gateway_answer_is_unreadable",), CLI,
           '        if resp_headers.get("x-research-gateway") != "result" or "json" not in resp_headers.get("content-type", ""):', "        if False:"),
          ("transport-failure-empty", "nothing answering is recorded as an empty search", (TO + "test_nothing_answered_is_unknown_never_empty",
                                                                                          TO + "test_named_lanes_each_get_their_unknown"), CLI,
           '            return failed("unknown", error)', '            return failed("searched_empty", None)'),
          ("policy-refusal-empty", "a request the policy refused is recorded as an empty search", (RA + "test_a_grant_and_the_policy_it_binds",), CLI,
           '           403: ("not_searched", None),', '           403: ("searched_empty", None),'),
          ("queued-unpolled", "a queued answer is read as it stands, without polling", (TO + "test_a_queued_answer_is_polled_to_its_result",
                                                                                        TO + "test_a_queued_answer_is_polled_and_a_job_that_never_ends_is_a_timeout"), CLI,
           '        if doc.get("status") in ("queued", "running"):', "        if False:"),
          ("failed-job-read", "a failed job's result is read like a done one's", (TO + "test_a_queued_answer_is_polled_and_a_job_that_never_ends_is_a_timeout",), CLI,
           '            if job.get("status") != "done" or not isinstance(job.get("result"), dict):', '            if not isinstance(job.get("result"), dict):'),
          ("uncaptured-silent", "a request the gateway did not capture durably raises no telemetry loss",
           (RA + "test_an_uncaptured_request_is_an_explicit_telemetry_loss",), CLI,
           '            result["losses"].append({"reason": str(obs.get("capture_loss") or "the gateway did not acknowledge a durable request row"),',
           '            (lambda *a: None)({"reason": str(obs.get("capture_loss") or "the gateway did not acknowledge a durable request row"),'),
          ("pages-rounded-up", "a lane whose later page failed is called complete", (RA + "test_a_failed_continuation_page_leaves_a_lower_bound",
                                                                                      RR + "test_a_failed_continuation_is_admissible_as_a_lower_bound"), CLI,
           '             "count": len(retrieved), "retrieved": retrieved, "completeness": "partial" if partial else "complete"}',
           '             "count": len(retrieved), "retrieved": retrieved, "completeness": "complete"}'),
          ("redirects-followed", "the default transport follows a redirect (the bearer token goes elsewhere)", (OH + "test_a_redirect_is_never_followed",), CLI,
           "_OPENER = urllib.request.build_opener(_NoRedirect)", "_OPENER = urllib.request.build_opener()"),
      )),
]
