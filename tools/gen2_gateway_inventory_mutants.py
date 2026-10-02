"""Task 2b-repair-14 (Gate D #2, checklist 6): the gateway mutants of the one owned inventory (tests/inventory.py, held by tests/test_inventory.py).

The inventory is only worth what it notices. Each mutant adds, in a temporary copy, ONE site to the package the inventory exists to see — or blinds one of its scans — and the tests that must
notice are named:

  I-site-*   a parser object made outside core/wire.py (the spelling the 13c review found the old scan missed), `plain` called by canonical construction, `.empty` or `.same_as` asked in
             a provider module the ruling does not name;
  I-scan-*   the parse scan stops finding parser objects, or stops finding a name imported from a library.

A killer must FAIL in its assertions, not error (tools/gen2_gateway_mutations.py). A control takes the accepted path through the same code.
"""
from __future__ import annotations

CANON = "research_gateway/core/canonical.py"
OC = "research_gateway/adapters/opencitations.py"
URI = "research_gateway/core/uri.py"
INV = "tests/inventory.py"
TI = "tests.test_inventory."
EVERY = TI + "Inventory.test_every_site_the_scans_find_is_listed_and_every_listed_site_is_there"
SANCTIONED = TI + "Inventory.test_the_sanctioned_predicates_stand_exactly_where_the_ruling_puts_them"
SINKS = TI + "Inventory.test_plain_the_one_materialization_is_called_at_the_reviewed_sinks_alone"
CONTROLS = (TI + "Inventory.test_each_entry_has_a_known_role_that_may_stand_there_and_a_reason", TI + "Scans.test_control_the_parse_scan_finds_a_parser_however_it_is_imported",
            "tests.test_astra_13a.R13A2.test_the_unmodified_adapter_keeps_all_three_citations")
ROW = '    doi = next((part[4:] for part in (row[key] or "").split(" ") if part.startswith("doi:")), None)\n'


def build(Mutant) -> list:
    """The mutants (tools/gen2_gateway_mutants.py: `Mutant`)."""
    return [
        Mutant("I-site-a-parser-object-is-made-in-a-core-module", "`json.JSONDecoder().decode(data)` in a core module that is no opener: the spelling the 13c review found the old scan missed", URI,
               "import re\nfrom typing import NamedTuple\n", "import json\nimport re\nfrom typing import NamedTuple\n\n\ndef _probe(data):\n    return json.JSONDecoder().decode(data)\n\n\n",
               (EVERY,), CONTROLS),
        Mutant("I-site-canonical-construction-materializes-the-raw", "`make_record` seals `plain(raw)`: canonical construction materializes the raw it is given", CANON,
               ("Sealed(detach(raw))", "from .payload import PayloadError, Sealed, detach, refuse_opaque"), ("Sealed(plain(raw))", "from .payload import PayloadError, Sealed, detach, plain, refuse_opaque"),
               (SINKS, EVERY), CONTROLS),
        Mutant("I-site-an-adapter-asks-whether-an-object-is-empty", "an adapter the ruling does not name asks `row.empty` before it selects a candidate", OC, ROW, "    row.empty\n" + ROW,
               (SANCTIONED, EVERY), CONTROLS),
        Mutant("I-site-an-adapter-compares-two-decoded-objects", "an adapter the ruling does not name compares decoded objects with `same_as`", OC, ROW, "    row.same_as(row)\n" + ROW,
               (SANCTIONED, EVERY), CONTROLS),
        Mutant("I-scan-the-parse-scan-forgets-parser-objects", "the parse scan no longer lists `JSONDecoder` among the parser entry points", INV,
               'PARSERS = {"json": {"loads", "load", "JSONDecoder"}, "json.decoder": {"JSONDecoder"},', 'PARSERS = {"json": {"loads", "load"}, "json.decoder": {"JSONDecoder"},',
               (TI + "Scans.test_control_the_parse_scan_finds_a_parser_object_and_a_parser_that_is_not_called",), CONTROLS[:1]),
        Mutant("I-scan-the-parse-scan-forgets-a-name-imported-from-a-library", "the reference scan reads attribute chains only: `from json import loads; loads(x)` is not a parse site", INV,
               "        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in aliases:\n            yield node, aliases[node.id]\n",
               "        elif False:\n            yield node, aliases[node.id]\n",
               (TI + "Scans.test_control_the_parse_scan_finds_a_parser_however_it_is_imported", TI + "Scans.test_control_the_parse_scan_finds_a_parser_object_and_a_parser_that_is_not_called"),
               (TI + "Inventory.test_each_entry_has_a_known_role_that_may_stand_there_and_a_reason",)),
    ]
