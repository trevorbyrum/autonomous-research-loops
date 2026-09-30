"""Mutants of task 2r: the size rules tools/gen2_linecount.py --check enforces
in make gen2-check (the per-file limit, its surface, the generated-file
allowlist and the production growth-review trigger), each guard removed or
weakened alone.
"""
from __future__ import annotations

from .base import LCT, SZ, Mutation

_PREFIXES = ("gen2/", "tools/gen2", "tools/check_", "tools/gen_", "deploy/", ".github/")
_SURFACE = 'SURFACE_PREFIXES = ("gen2/", "tools/gen2", "tools/check_", "tools/gen_", "deploy/", ".github/")'

MUTATIONS: list[Mutation] = [
    Mutation("2R-size-limit-inclusive", "2r", "a file of exactly 1,500 lines fails the per-file limit", (SZ + "test_exactly_the_limit_passes",),
             target=LCT, old="        if n > FILE_LIMIT:", new="        if n >= FILE_LIMIT:"),
    Mutation("2R-size-over-limit-dropped", "2r", "a file over the per-file limit is not collected", (SZ + "test_a_hand_written_file_over_the_limit_fails_named_with_its_count",
             SZ + "test_an_unlisted_generated_looking_file_fails"), target=LCT, old="            over.append((rel, n))", new="            pass"),
    Mutation("2R-size-over-limit-passes", "2r", "a file over the per-file limit is named but the check exits 0",
             (SZ + "test_a_hand_written_file_over_the_limit_fails_named_with_its_count", SZ + "test_an_unlisted_generated_looking_file_fails"),
             target=LCT, old="        if over or bad or production >= GROWTH_REVIEW:", new="        if bad or production >= GROWTH_REVIEW:"),
    Mutation("2R-size-first-offender-only", "2r", "only the first file over the limit is named", (SZ + "test_a_hand_written_file_over_the_limit_fails_named_with_its_count",),
             target=LCT, old="        for rel, n in over:", new="        for rel, n in over[:1]:"),
    Mutation("2R-size-count-unnamed", "2r", "a file over the limit is named without its count", (SZ + "test_a_hand_written_file_over_the_limit_fails_named_with_its_count",),
             target=LCT, old="{rel} has {n:,} lines > {FILE_LIMIT:,}", new="{rel} has more than {FILE_LIMIT:,} lines"),
    # the surface: each place the per-file limit covers, dropped alone
    *(Mutation(f"2R-size-surface-drops-{prefix.strip('./_').replace('/', '-')}", "2r", f"the per-file limit skips {prefix}",
               (SZ + "test_a_hand_written_file_over_the_limit_fails_named_with_its_count",), target=LCT,
               old=_SURFACE, new=f"SURFACE_PREFIXES = {tuple(p for p in _PREFIXES if p != prefix)!r}".replace("'", '"'))
      for prefix in _PREFIXES),
    Mutation("2R-size-surface-drops-makefile", "2r", "the per-file limit skips the Makefile", (SZ + "test_a_hand_written_file_over_the_limit_fails_named_with_its_count",),
             target=LCT, old='SURFACE_FILES = ("Makefile",)', new="SURFACE_FILES = ()"),
    # the allowlist: only a listed path is exempt, and each entry must hold
    Mutation("2R-size-exempt-by-name", "2r", "a file named like an allowlisted one, anywhere, is exempt", (SZ + "test_an_unlisted_generated_looking_file_fails",),
             target=LCT, old="or rel in GENERATED or", new="or Path(rel).name in {Path(g).name for g in GENERATED} or"),
    Mutation("2R-size-exempt-by-header", "2r", "a file that says it is generated is exempt", (SZ + "test_an_unlisted_generated_looking_file_fails",),
             target=LCT, old="or rel in GENERATED or", new="or rel in GENERATED or \"GENERATED\" in (root / rel).read_text(encoding=\"utf-8\", errors=\"replace\") or"),
    Mutation("2R-size-allowlist-file-unchecked", "2r", "an allowlist entry for a file that is not tracked holds",
             (SZ + "test_an_allowlist_entry_whose_tool_does_not_name_it_fails",), target=LCT, old="        if rel not in tracked:", new="        if False:"),
    Mutation("2R-size-allowlist-tool-unchecked", "2r", "an allowlist entry whose tool is not tracked holds",
             (SZ + "test_an_allowlist_entry_whose_tool_does_not_name_it_fails",), target=LCT,
             old="        elif tool not in tracked or not (root / tool).is_file():", new="        elif not (root / tool).is_file():"),
    Mutation("2R-size-allowlist-unnamed", "2r", "an allowlist entry whose tool does not name the file holds",
             (SZ + "test_an_allowlist_entry_whose_tool_does_not_name_it_fails",), target=LCT,
             old='        elif rel not in (root / tool).read_text(encoding="utf-8", errors="replace"):', new="        elif False:"),
    Mutation("2R-size-allowlist-passes", "2r", "an allowlist entry that does not hold is named but the check exits 0",
             (SZ + "test_an_allowlist_entry_whose_tool_does_not_name_it_fails",), target=LCT,
             old="        if over or bad or production >= GROWTH_REVIEW:", new="        if over or production >= GROWTH_REVIEW:"),
    # the production growth-review trigger
    Mutation("2R-growth-trigger-exclusive", "2r", "reaching 15,000 production lines does not trigger the growth review, only passing it does",
             (SZ + "test_reaching_the_growth_review_trigger_fails",), target=LCT, old="        if production >= GROWTH_REVIEW:\n",
             new="        if production > GROWTH_REVIEW:\n",
             also=(("        if over or bad or production >= GROWTH_REVIEW:", "        if over or bad or production > GROWTH_REVIEW:"),)),
    Mutation("2R-growth-trigger-passes", "2r", "the growth review is announced but the check exits 0", (SZ + "test_reaching_the_growth_review_trigger_fails",),
             target=LCT, old="        if over or bad or production >= GROWTH_REVIEW:", new="        if over or bad:"),
    Mutation("2R-growth-trigger-silent", "2r", "the growth review fails the check without saying why", (SZ + "test_reaching_the_growth_review_trigger_fails",),
             target=LCT, old="        if production >= GROWTH_REVIEW:\n            print(", new="        if False:\n            print("),
]
