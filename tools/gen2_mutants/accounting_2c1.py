"""2c-1 invariant guards; controls specified by hand, no full-suite trace."""
from .base import Mutation

TARGET = "gen2/accounting/__init__.py"
TEST = "test_accounting.AccountingTest."


def mutant(name, killer, old, new, *also):
    return Mutation("2C1-" + name, "2c-1", name, (TEST + killer,), target=TARGET, old=old, new=new, also=also)


WINDOW = '        if any(not _captured(o, inventory) or o.request_type != "find" or o.page_outcome != "exhausted" for o in observations):'
MUTATIONS = [
    mutant("unknown-is-zero", "test_partial_pass", 'return None if self.unknown_reason is not None else len(self.known_ids)',
           'return 0 if self.unknown_reason is not None else len(self.known_ids)'),
    mutant("zero-assessed-is-zero-novelty", "test_zero_denominator", 'if assessed.value is None or assessed.value == 0:\n        return None',
           'if assessed.value is None or assessed.value == 0:\n        return Fraction(0)'),
    mutant("overlapping-lanes-multiply", "test_repeated_study_overlapping_lanes", 'works = frozenset(links[r] for r in records if r in links)',
           'works = frozenset(r for r in records if r in links)'),
    mutant("partial-pass-counts", "test_partial_pass", WINDOW,
           '        if any(o.completeness == "unobserved" or o.request_type != "find" for o in observations):'),
    mutant("failed-pass-counts", "test_failed_missing_and_capped_passes", 'p.kind != "research_pass" or p.state != "committed" or not observations',
           'p.kind != "research_pass" or not observations'),
    mutant("unexhausted-pass-counts", "test_failed_missing_and_capped_passes", 'or o.page_outcome != "exhausted"', ''),
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
