"""Task 2b-repair-13c: the gateway mutants of the byte openers (core/wire.py and its consumers).

2b-repair-13a closed the decoder's contract over the VALUES a lexer hands it; Astra's R13A-1 then showed the layer beneath it: a library's default reading resolves malformed bytes
(an unterminated CSV quote, a name twice, `NaN`, an invalid byte) before any schema sees them. 2b-repair-13c gives each opener a contract of its own (core/wire.py's docstring is the
ruling for each, against RFC 8259, XML 1.0 and RFC 4180). The mutants here remove ONE rule of one opener in a temporary copy and name the tests that must notice:

  O-json-*      RFC 8259: UTF-8 only, no NaN/Infinity, finite numbers, each name once;
  O-bytes-*     strict UTF-8 for every format (an invalid byte is a refusal, not U+FFFD);
  O-xml-*       a 1.x declaration, the declared encoding is the bytes', no DOCTYPE, bounded nesting;
  O-csv-*       RFC 4180: a quoted field is closed, nothing follows a closing quote, no quote inside an unquoted field, no bare carriage return, a bounded cell,
                and a column the schema reads is not named twice;
  O-snapshot-*  a line of the OpenAlex snapshot that is not JSON fails the load;
  O-count-*     the call log's count is read by the same opener as the decoder's;
  O-retry-after-*  a Retry-After header is `delay-seconds` or an HTTP-date, not whatever `float()` reads;
  O-a-parser-*  a parse call outside core/wire.py fails the inventory.

A killer must FAIL in its assertions, not error (tools/gen2_gateway_mutations.py). A control takes the accepted path through the same code.
"""
from __future__ import annotations

WIRE = "research_gateway/core/wire.py"
SCHEMA = "research_gateway/core/schema.py"
BASE = "research_gateway/adapters/base.py"
SNAPSHOT = "research_gateway/harvest/openalex_snapshot.py"
OP = "tests.test_openers."
JR, XR, CR, BC, AG, AS, INV = (OP + "JsonRulings.", OP + "XmlRulings.", OP + "CsvRulings.", OP + "ByteCorruption.", OP + "AgainstTheCsvModule.", "tests.test_astra_13a.R13A1.", OP + "Inventory.")
JSON_FAMILY = BC + "test_json_every_corruption_is_a_payload_error_from_the_decoder_and_has_no_count"
XML_FAMILY = BC + "test_xml_every_corruption_is_a_payload_error_from_parse_xml"
CSV_FAMILY = BC + "test_csv_every_corruption_of_the_dump_is_a_payload_error_and_never_a_load"
SNAPSHOT_FAMILY = BC + "test_the_snapshot_reader_every_corruption_of_a_line_fails_the_load_naming_it"


def build(Mutant) -> list:
    """The mutants (tools/gen2_gateway_mutants.py: `Mutant`)."""
    return [
        Mutant("O-json-a-name-twice-is-the-last", "an object that names a field twice is read as its last value, as `json.loads` does", WIRE,
               "object_pairs_hook=_names_once, ", "",
               (JR + "test_the_refused", JSON_FAMILY, SNAPSHOT_FAMILY), (JR + "test_the_accepted",)),
        Mutant("O-json-nan-and-infinity-are-numbers", "`NaN`, `Infinity` and `-Infinity` are read as numbers (both layers that refuse them removed: the token, and the pass over what was parsed that refuses any non-finite float)", WIRE,
               (", parse_constant=_refuse_constant)", "            elif kind is float and not finite(child):\n"), (")", "            elif False:\n"),
               (JR + "test_the_refused", JSON_FAMILY), (JR + "test_the_accepted",)),
        Mutant("O-json-an-overflowing-number-is-infinity", "`1e999` is read as infinity: the pass over what was parsed does not look at numbers", WIRE,
               "            elif kind is float and not finite(child):\n", "            elif False:\n",
               (JR + "test_the_refused", JSON_FAMILY, SNAPSHOT_FAMILY), (JR + "test_the_accepted",)),
        Mutant("O-bytes-are-read-with-replacement", "bytes that are not UTF-8 are read with U+FFFD in their place, for JSON, XML and CSV alike", WIRE,
               '            text = bytes(body).decode("utf-8")\n', '            text = bytes(body).decode("utf-8", "replace")\n',
               (JR + "test_the_refused", XR + "test_the_refused", CR + "test_the_refused", JSON_FAMILY, XML_FAMILY, CSV_FAMILY),
               (JR + "test_the_accepted", XR + "test_the_accepted", CR + "test_the_accepted")),
        Mutant("O-xml-any-declared-version-is-read", "an XML declaration's version is not checked: `2.0`, `1` and `abc` are read", WIRE,
               "    _check_declaration(text)\n", "",
               (XR + "test_the_refused", XR + "test_text_is_read_as_text_but_still_checked", XML_FAMILY), (XR + "test_the_accepted",)),
        Mutant("O-xml-a-declared-encoding-is-ignored", "a declaration of another encoding over UTF-8 bytes is read as UTF-8", WIRE,
               '    if encoding is not None and encoding.lower() != "utf-8":\n', "    if False:\n",
               (XR + "test_the_refused", XML_FAMILY), (XR + "test_the_accepted",)),
        Mutant("O-xml-a-doctype-is-read", "a document type declaration is read: an internal subset's entities expand and an external subset is skipped without a word", WIRE,
               "    parser = ET.XMLParser(target=_NoDoctype())\n", "    parser = ET.XMLParser(target=ET.TreeBuilder())\n",
               (XR + "test_the_refused", XML_FAMILY), (XR + "test_the_accepted",)),
        Mutant("O-xml-nesting-is-unbounded", "an XML document nested past the gateway's limit is read", WIRE,
               "        if depth > MAX_DEPTH:\n", "        if False:\n",
               (XR + "test_the_refused", XML_FAMILY, "tests.test_decoder_total.TheDecoderOnlyEverRaisesPayloadError.test_nesting_past_the_gateways_operational_limit_is_refused_at_its_edge_and_nesting_within_it_is_read"),
               (XR + "test_the_accepted",)),
        Mutant("O-csv-an-unterminated-quote-is-data", "a quoted field that is never closed ends at the end of the data (the csv module's default): Astra's zero-journal load", WIRE,
               """_QUOTED = re.compile(r'"([^"]*(?:""[^"]*)*)"')""", """_QUOTED = re.compile(r'"([^"]*(?:""[^"]*)*)(?:"|\\Z)')""",
               (CR + "test_the_refused", CSV_FAMILY, AS + "test_each_probe", AS + "test_the_index_load_that_returned_zero_now_fails_and_rolls_back",
                BC + "test_csv_every_single_quote_removed_from_an_all_quoted_dump_is_refused",
                "tests.test_schema_corruption.CsvCorruptions.test_a_dump_whose_serialized_framing_is_broken_is_unreadable_not_shorter_or_empty"),
               (CR + "test_the_accepted", AS + "test_the_valid_dump_still_loads_through_index_load")),
        Mutant("O-csv-text-after-a-closing-quote-is-read", "text after a closing quote starts the next cell (the csv module's default)", WIRE,
               '            raise Malformed(f"line {line}: " + ("text after a closing quote',
               '            if quoted:\n                continue\n            raise Malformed(f"line {line}: " + ("text after a closing quote',
               (CR + "test_the_refused", CSV_FAMILY, AS + "test_each_probe"), (CR + "test_the_accepted", AS + "test_the_valid_dump_still_loads_through_index_load")),
        Mutant("O-csv-a-quote-inside-an-unquoted-field-is-text", "a quote inside an unquoted field is part of it (RFC 4180 §2.5 forbids it; the csv module reads it)", WIRE,
               """_UNQUOTED = re.compile(r'[^",\\r\\n]*')""", """_UNQUOTED = re.compile(r'[^,\\r\\n]*')""",
               (CR + "test_the_refused", CSV_FAMILY, AG + "test_on_thousands_of_texts_it_reads_what_strict_reads_and_refuses_more_only_where_the_rfc_does"),
               (CR + "test_the_accepted", AG + "test_it_reads_the_documents_a_csv_writer_writes")),
        Mutant("O-csv-a-bare-carriage-return-is-skipped", "a carriage return that is not half of CRLF is dropped, joining the cells around it", WIRE,
               '            if char == "\\r":\n                raise Malformed(f"line {line}: a carriage return that does not end the line (RFC 4180 §2.1)")\n',
               '            if char == "\\r":\n                i += 1\n                continue\n',
               (CR + "test_the_refused", CSV_FAMILY), (CR + "test_the_accepted",)),
        Mutant("O-csv-a-cell-has-no-limit", "a cell of any size is read", WIRE,
               "            if len(cell) > CELL_LIMIT:\n", "            if False:\n",
               (CR + "test_the_refused", "tests.test_schema_corruption.CsvCorruptions.test_a_cell_past_the_field_limit_and_a_file_with_no_usable_header_are_unreadable_not_empty"),
               (CR + "test_the_accepted",)),
        Mutant("O-csv-a-column-the-schema-reads-may-be-named-twice", "the last of two columns of the same name is the one read", SCHEMA,
               "    if twice:\n        raise PayloadError(", "    if False:\n        raise PayloadError(",
               (CSV_FAMILY, AS + "test_each_probe", "tests.test_schema_corruption.CsvCorruptions.test_a_dump_whose_serialized_framing_is_broken_is_unreadable_not_shorter_or_empty"),
               (BC + "test_csv_a_column_the_schema_does_not_read_may_be_named_twice", AS + "test_the_valid_dump_still_loads_through_index_load")),
        Mutant("O-snapshot-a-line-that-is-not-json-is-skipped", "a snapshot line that is not JSON is skipped and the load comes out shorter", SNAPSHOT,
               '                    raise PayloadError(f"{path.name} line {number}: {e}") from None\n', "                    continue\n",
               (SNAPSHOT_FAMILY, "tests.test_harvest.Shapes.test_openalex_records_and_snapshot_reader"), ()),
        Mutant("O-count-is-read-by-a-lenient-parser", "the call log's count of results is read by `json.loads`, whatever the decoder would refuse", BASE,
               "        j = _open_json(resp._body) if resp.ok and resp._body else None\n    except Malformed:\n",
               '        j = __import__("json").loads(resp._body) if resp.ok and resp._body else None\n    except ValueError:\n',
               (JSON_FAMILY,), (BC + "test_json_every_proper_prefix_of_a_document_is_refused",)),
        Mutant("O-retry-after-is-read-by-float", "a Retry-After of `inf`, `nan`, `-5`, `1e3` or `1_0` is a delay (the header was read with `float()`)", BASE,
               "        if v.isascii() and v.isdigit():\n            try:\n                return float(int(v))\n            except (ValueError, OverflowError):   # more digits than int() converts, or more seconds than a double holds\n                return None\n",
               "        try:\n            return float(v)\n        except ValueError:\n            pass\n",
               (OP + "HeaderOpeners.test_retry_after_is_delay_seconds_or_an_http_date_and_nothing_else", OP + "HeaderOpeners.test_a_retry_after_that_is_not_a_delay_opens_no_breaker_of_its_own"),
               ("tests.test_broker.FromRows.test_retry_after_http_date_and_no_shortening", "tests.test_core_foundations.MeteredClient.test_retry_after_is_honoured")),
        Mutant("O-a-parser-outside-wire", "the decoder parses JSON with the library itself again", SCHEMA,
               ("from . import wire\n", "        return wire.open_json(body)\n"), ("import json\nfrom . import wire\n", "        return json.loads(body)\n"),
               (INV + "test_every_parse_call_in_the_gateway_is_listed_with_its_class", JSON_FAMILY), (INV + "test_control_the_scan_finds_a_parser_however_it_is_imported",)),
    ]
