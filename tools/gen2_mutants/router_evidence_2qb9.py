"""Mutants of task 2q-b9: Router._write_evidence split into five private helpers by extract-method. The rules the split added are the helper boundaries: what each returns, the order and
the arguments of its call, that each is called, and that its refusals still reach `_guarded`. Each is broken alone at the call or the return; the tests that kill them are the existing
evidence and workflow tests and gen2/tests/test_router_evidence_wiring.py, and the tests that do not reach the changed line are their controls (by hand: nothing here was traced).

  2QB9-claims-result-dropped                     `_write_claims` returns no claims, so the commit's audit event lists none;
  2QB9-promotions-and-links-swapped              the call takes the pair `_promote_and_link_claims` returns in the other order;
  2QB9-links-result-dropped                      `_promote_and_link_claims` returns no links, so the audit event lists none;
  2QB9-claims-helper-not-called                  `_write_evidence` does not call `_write_claims`;
  2QB9-reports-helper-not-called                 ... `_write_scoping_reports`;
  2QB9-proposals-helper-not-called               ... `_write_source_proposals`;
  2QB9-closures-helper-not-called                ... `_close_review_episodes`;
  2QB9-reports-operation-and-instant-swapped     `_write_scoping_reports` is given the instant where it expects the operation, and the operation where it expects the instant;
  2QB9-closures-operation-and-instant-swapped    the same for `_close_review_episodes`;
  2QB9-claims-written-after-the-promotions       `_write_claims` runs after `_promote_and_link_claims`, so a promotion of a claim recorded in the same commit finds none;
  2QB9-reports-refusal-swallowed                 the call of `_write_scoping_reports` drops the refusal it raises, so a defective report is skipped and the commit goes on.
"""
from __future__ import annotations

from .base import RE, SVC, Mutation

WF, WIRING = "test_router_workflow.", "test_router_evidence_wiring."
ADOPT = RE + "ProductionAndAdoptionTest.test_a_scoping_claim_is_adopted_by_a_revision_the_admitted_commit_produces"
REPORT, PROPOSAL = WF + "ScopingReportTest.test_the_report_hands_the_topic_to_the_operator", WF + "SourceProposalTest.test_a_proposal_is_retained_and_authorizes_nothing"
CLOSURE, DEFECT = WF + "ReviewClosureTest.test_the_checkpoint_closes_its_episode_and_handles_its_triggers", WF + "ScopingReportTest.test_each_defect_is_refused_alone"
LINK = WIRING + "ClaimLinkTest.test_a_link_is_written_whichever_write_is_refused"
CLAIMS, SPLIT = "        claims = self._write_claims(payload, topic_id, inv, now)\n", "        promotions, links = self._promote_and_link_claims(payload, topic_id, inv, now)\n"
REPORTS, PROPOSALS, CLOSURES = (f"        self.{name}(payload, topic_id, inv, op_id, now)\n" for name in ("_write_scoping_reports", "_write_source_proposals", "_close_review_episodes"))
SWAPPED = lambda call: call.replace("op_id, now", "now, op_id")  # noqa: E731


def mutant(name: str, description: str, killer: str, old: str, new: str, *also: tuple[str, str]) -> Mutation:
    return Mutation(f"2QB9-{name}", "2q-b9", description, (killer,), target=SVC, old=old, new=new, also=also)


MUTATIONS: list[Mutation] = [
    mutant("claims-result-dropped", "`_write_claims` returns no claims", ADOPT, '"revision"]])\n        return claims\n', '"revision"]])\n        return []\n'),
    mutant("promotions-and-links-swapped", "the call takes the pair of `_promote_and_link_claims` in the other order", ADOPT, SPLIT, SPLIT.replace("promotions, links", "links, promotions")),
    mutant("links-result-dropped", "`_promote_and_link_claims` returns no links", LINK, "        return promotions, links\n", "        return promotions, []\n"),
    mutant("claims-helper-not-called", "`_write_evidence` does not call `_write_claims`", ADOPT, CLAIMS, "        claims = []\n"),
    mutant("reports-helper-not-called", "`_write_evidence` does not call `_write_scoping_reports`", REPORT, REPORTS, ""),
    mutant("proposals-helper-not-called", "`_write_evidence` does not call `_write_source_proposals`", PROPOSAL, PROPOSALS, ""),
    mutant("closures-helper-not-called", "`_write_evidence` does not call `_close_review_episodes`", CLOSURE, CLOSURES, ""),
    mutant("reports-operation-and-instant-swapped", "`_write_scoping_reports` is given the instant for the operation and the operation for the instant", REPORT, REPORTS, SWAPPED(REPORTS)),
    mutant("closures-operation-and-instant-swapped", "`_close_review_episodes` is given the instant for the operation and the operation for the instant", CLOSURE, CLOSURES, SWAPPED(CLOSURES)),
    mutant("claims-written-after-the-promotions", "`_write_claims` runs after `_promote_and_link_claims`", ADOPT, CLAIMS, "        claims = []\n", (SPLIT, SPLIT + CLAIMS)),
    mutant("reports-refusal-swallowed", "the call of `_write_scoping_reports` drops the refusal it raises", DEFECT, REPORTS,
           "        try:\n    " + REPORTS + "        except Refusal:\n            pass\n"),
]
