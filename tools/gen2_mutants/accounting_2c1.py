"""2c-1 invariant guards; controls specified by hand, no full-suite trace."""
from .base import Mutation

TARGET = "gen2/accounting/__init__.py"
TEST = "test_accounting.AccountingTest."


def mutant(name, killer, old, new, *also):
    return Mutation("2C1-" + name, "2c-1", name, (TEST + killer,), target=TARGET, old=old, new=new, also=also)


WINDOW = '    if any(not _captured(o, inventory) or o.page_outcome == "failed" for o in observations):'
CHAINS = '    if any(not _complete_chain(chain) for chain in chains.values()):'
MUTATIONS = [
    mutant("unknown-is-zero", "test_partial_pass", 'return None if self.unknown_reason is not None else len(self.known_ids)',
           'return 0 if self.unknown_reason is not None else len(self.known_ids)'),
    mutant("zero-assessed-is-zero-novelty", "test_zero_denominator", 'if assessed.value is None or assessed.value == 0:\n        return None',
           'if assessed.value is None or assessed.value == 0:\n        return Fraction(0)'),
    mutant("overlapping-lanes-multiply", "test_repeated_study_overlapping_lanes", 'works = frozenset(links[r] for r in records if r in links)',
           'works = frozenset(r for r in records if r in links)'),
    mutant("partial-pass-counts", "test_partial_pass", WINDOW,
           '    if any(o.completeness == "unobserved" or o.page_outcome == "failed" for o in observations):', (CHAINS, '    if False:')),
    mutant("failed-pass-counts", "test_failed_missing_and_capped_passes", 'p.kind != "research_pass" or p.state != "committed"',
           'p.kind != "research_pass"'),
    mutant("unexhausted-pass-counts", "test_failed_missing_and_capped_passes", 'return pages[-1].page_outcome == "exhausted" and cursor is None',
           'return True'),
    mutant("repeating-search-counts", "test_repeating_search_earns_no_window", 'if requests - seen:', 'if requests:'),
    mutant("deferred-is-assessed", "test_deferred_remains_unassessed", 'assessed = frozenset(a.work_id for a in inventory.assessments)',
           'assessed = works | frozenset(a.work_id for a in inventory.assessments)'),
    mutant("legacy-history-known", "test_legacy_history", 'if inventory.history == "legacy_unknown":\n        return "legacy historical capture unknown"',
           'if False:\n        return "legacy historical capture unknown"',
           ('historical = "legacy historical capture unknown" if inventory.history == "legacy_unknown" else None', 'historical = None')),
    mutant("unlinked-is-known", "test_unlinked_and_capture_mismatch", 'reason or ("record identity not linked" if records - links.keys() else None)', 'reason'),
    mutant("capture-count-unchecked", "test_unlinked_and_capture_mismatch", 'and observation.result_count == len(events)', ''),
    mutant("judgment-unknown-is-zero", "test_unknown_judgment", 'or any(v is None for v in labels.values())', ''),
]
CONTROLS = {m.mid: {"controls": [TEST + "test_control_complete"], "why":
            "By hand: one committed complete distinct search, linked and assessed work, current accepted claim and explicit novelty judgment; evaluates the changed guard or expression on its accepted path."}
            for m in MUTATIONS}

ROUTER = "test_accounting.WindowTest."


def repair(name, killer, control, old, new):
    m = Mutation("2C1R-" + name, "2c-1-repair-1", name, (killer,), target=TARGET, old=old, new=new)
    MUTATIONS.append(m)
    CONTROLS[m.mid] = {"controls": [control], "why": "Hand-written complete-window control exercises the accepted path of this window guard."}


repair("capture-as-search-identity", ROUTER + "test_equivalent_requests_and_different_search", ROUTER + "test_distinct_search_control",
       'search = replace(o.page.search, lanes=(o.lane,))', 'search = replace(o.page.search, lanes=(o.lane,), query=o.request_identity)')
repair("drop-ancestry", ROUTER + "test_partial_failed_and_missing_delegates", ROUTER + "test_complete_delegated_search",
       'descendants = _descendants(root, inventory)', 'descendants = []')
repair("drop-transitive-ancestry", TEST + "test_transitive_delegate_capture", ROUTER + "test_complete_delegated_search",
       'pending.append(child.invocation_id)', 'pass')
repair("ignore-failed-delegate", ROUTER + "test_partial_failed_and_missing_delegates", ROUTER + "test_complete_delegated_search",
       'p.state != "committed" or p.invocation_id not in observed', 'p.invocation_id not in observed')
repair("ignore-missing-delegate-capture", ROUTER + "test_partial_failed_and_missing_delegates", ROUTER + "test_complete_delegated_search",
       'p.state != "committed" or p.invocation_id not in observed', 'p.state != "committed"')
repair("accept-broken-chain", ROUTER + "test_missing_and_partial_prefix", ROUTER + "test_complete_linked_pages", CHAINS, '    if False:')
repair("infer-start-from-tail", ROUTER + "test_missing_and_partial_prefix", ROUTER + "test_complete_linked_pages",
       'number, cursor = 1, None', 'number, cursor = pages[0].page.number, pages[0].page.cursor')
repair("ignore-cursor-continuity", ROUTER + "test_broken_chains", ROUTER + "test_complete_linked_pages",
       'o.page.number != number or o.page.cursor != cursor', 'o.page.number != number')
repair("ignore-page-continuity", ROUTER + "test_broken_chains", ROUTER + "test_complete_linked_pages",
       'o.page.number != number or o.page.cursor != cursor', 'o.page.cursor != cursor')
repair("accept-capped-prefix", ROUTER + "test_broken_chains", ROUTER + "test_complete_linked_pages",
       'o.page_outcome != "continuation"', 'o.page_outcome not in ("continuation", "limit_reached")')
repair("nonpaging-erases-window", ROUTER + "test_nonpaging_success_preserves_window", TEST + "test_control_complete",
       'continue  # Non-paging success', 'return set()  # Non-paging success')
repair("ignore-nonpaging-failure", ROUTER + "test_nonpaging_partial_and_failed_remain_visible", ROUTER + "test_nonpaging_success_preserves_window",
       WINDOW, '    if any(o.request_type == "find" and (not _captured(o, inventory) or o.page_outcome == "failed") for o in observations):')
