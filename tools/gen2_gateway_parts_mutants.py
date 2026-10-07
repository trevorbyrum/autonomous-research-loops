"""Task 2q-b5: the gateway mutants of the split of adapters/base.py into the client and its parts (`_response.py`, `_transport.py`, `_links.py`).

The split puts four modules in the directory the adapter loader, the registry's orphan check and the inventory read: each of them has to tell a part of the client from an adapter, and an
adapter may import from a part only what the part's `__all__` offers. The mutants break one of those, and the Link reader's value step, in a temporary copy:

  B5-the-orphan-check-takes-a-client-part-for-an-adapter   registry/load.py `check_adapters` lists `_links`, `_response` and `_transport` as adapters without a seed row;
  B5-the-inventory-reads-a-client-part-as-an-adapter        tests/inventory.py `provider_modules` scans the parts as provider-data modules;
  B5-a-client-part-offers-an-adapter-any-name               `import_findings` admits any name an adapter imports from a part (only base.py's `__all__` decides);
  B5-the-stream-read-scan-looks-in-the-old-module           `netread_sites` looks for the transport's stream reads in base.py;
  B5-a-link-parameter-value-is-always-a-token               `_param` no longer reads a quoted-string value (the step `parse_links` was split into).

A killer fails in its assertion; the control passes under the mutant (it takes the accepted path through the same code). The two scanner mutants' controls (task 2q-e1, Astra 2q-b5 C3) are
fixtures that CALL `provider_modules` and `netread_sites` and assert what they list: they fail on an always-empty or broken scanner, which the first pairing's source test did not.
"""
from __future__ import annotations

LOAD, INVENTORY, LINKS = "research_gateway/registry/load.py", "tests/inventory.py", "research_gateway/adapters/_links.py"
REG, INV, TF = "tests.test_registry.AdapterConsistency.", "tests.test_inventory.", "tests.test_member_isolation.Imports."
LH = "tests.test_link_header."


def build(Mutant) -> list:
    """The mutants (tools/gen2_gateway_mutants.py: `Mutant`)."""
    return [
        Mutant("B5-the-orphan-check-takes-a-client-part-for-an-adapter", "the registry's orphan check lists the parts of the client as adapters", LOAD,
               'if p.stem != "base" and not p.stem.startswith("_")}', 'if p.stem not in {"__init__", "base"}}',
               (REG + "test_no_orphan_adapters",), (REG + "test_every_seeded_source_has_an_adapter",)),
        Mutant("B5-the-inventory-reads-a-client-part-as-an-adapter", "the inventory scans the parts of the client as provider-data modules", INVENTORY,
               'if not client_part(p.name) and p.name != "__init__.py")', 'if p.name not in ("base.py", "__init__.py"))',
               (INV + "Inventory.test_the_provider_data_modules_include_five_named_ones_and_not_the_transport_module",), (INV + "Scans.test_control_the_provider_module_list_names_the_adapters_and_data_modules",)),
        Mutant("B5-a-client-part-offers-an-adapter-any-name", "an adapter may import any name of a part of the client, not only what its `__all__` offers", INVENTORY,
               '                        if a.name not in (api if module.name == "base.py" else parts.get(module.name, set())):\n',
               '                        if module.name == "base.py" and a.name not in api:\n',
               (TF + "test_every_other_form_an_import_can_take_is_refused_or_analysed",), (TF + "test_a_parser_re_exported_by_the_client_is_refused_and_so_is_the_reviewers_mutant",)),
        Mutant("B5-the-stream-read-scan-looks-in-the-old-module", "the scan of stream reads looks in base.py, where the transport no longer is", INVENTORY,
               'if rel != "adapters/_transport.py":', 'if rel != "adapters/base.py":',
               (INV + "TheProviderTransport.test_the_only_reads_of_a_connections_stream_in_the_transport_module_are_read_body_and_its_chunked_reader",),
               (INV + "Scans.test_control_the_netread_scan_names_each_stream_read_of_the_module_it_is_given",)),
        Mutant("B5-a-link-parameter-value-is-always-a-token", "a link parameter's value is read as a token, never as a quoted-string", LINKS,
               "        at, value = _quoted(header, at) if at < len(header) and header[at] == '\"' else _token(header, at)\n", "        at, value = _token(header, at)\n",
               (LH + "Reading.test_a_next_link_is_found_however_the_header_is_written",), (LH + "Reading.test_control_a_parameter_whose_value_is_a_token_is_read_beside_one_with_no_value",)),
    ]
