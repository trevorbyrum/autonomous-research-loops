"""Task 2b-repair-14 (Astra F1 / R13C-1): the gateway mutants of the transport's framing completion (adapters/_transport.py `_read_body`).

A response is a success only when its HTTP message is complete (RFC 9112 §6.3, §7.1). The mutants here remove ONE rule of it in a temporary copy and name the tests that must notice
(tests/test_transport_framing.py, over a real loopback socket, through the real Transport, Client, DOAJ loader and `index.load`):

  T-length-*   a body shorter than its Content-Length is a success; a declared length past the bound is read before it is refused;
  T-bound-*    a body past MAX_BODY_BYTES is returned;
  T-framing-*  a message whose framing is invalid or conflicts (Transfer-Encoding with Content-Length, another coding, a Content-Length that repeats or is not digits) is read under
               one of its framings; the library's lenient reading of the headers is not checked against the RFC's;
  T-error-*    an error status loses its status when its body does not arrive whole;
  T-chunked-*  (task 2b-repair-15, Astra F1) the transport's own reading of chunked framing (`_read_chunked`, RFC 9112 §7.1) loses one rule: the size syntax, the CRLF after a chunk's data, EOF inside the
               data / a line / the trailer section, a line's CRLF, the trailer field syntax, the extension syntax, a line's length, the bound on the announced size and on the trailer, or the
               whole reader (the body is handed back to http.client's decoder).

A killer must FAIL in its assertions, not error (tools/gen2_gateway_mutations.py). A control takes the accepted path through the same code.
"""
from __future__ import annotations

TRANSPORT = "research_gateway/adapters/_transport.py"
TF = "tests.test_transport_framing."
CL, CH, BD, IF, ST, CD = TF + "ContentLength.", TF + "Chunked.", TF + "Bound.", TF + "InvalidFraming.", TF + "Statuses.", TF + "CloseDelimited."
CONTROLS = (CL + "test_control_the_complete_body_loads_all_three", CH + "test_control_complete_chunked_bodies_load_all_three", CD + "test_control_a_complete_close_delimited_body_loads")
CH_CONTROLS = (CH + "test_control_complete_chunked_bodies_load_all_three", CH + "test_control_the_syntax_the_grammar_allows_is_read",
               CH + "test_astras_controls_the_complete_counterparts_load_and_a_complete_header_only_csv_is_zero")
ASTRA, SYNTAX, CUT, SHORT = (CH + "test_astras_wire_captures_each_row_of_her_table_is_refused_with_no_count", CH + "test_framing_the_grammar_does_not_allow_is_refused_beside_its_control",
                             CH + "test_a_cut_inside_the_last_chunk_or_the_trailer_section_is_not_a_load", CH + "test_a_chunked_body_with_no_terminal_chunk_is_not_a_load")


def build(Mutant) -> list:
    """The mutants (tools/gen2_gateway_mutants.py: `Mutant`)."""
    return [
        Mutant("T-length-a-short-body-is-a-success", "a body that ends before its Content-Length is returned as the response (HTTPResponse.read(amt) does not raise): Astra's zero- and one-journal loads", TRANSPORT,
               "    if resp.length:   # a Content-Length with bytes still to come: the connection ended before the message did\n        raise http.client.IncompleteRead(data, resp.length)\n", "",
               (CL + "test_a_body_cut_after_the_headers_is_not_a_load_of_nothing", ST + "test_an_error_status_with_a_cut_body_keeps_its_status_and_says_the_body_is_not_here"),
               (*CONTROLS, CL + "test_control_the_cuts_are_valid_documents_that_a_csv_reader_alone_would_load", CL + "test_a_body_longer_than_its_length_is_read_to_the_length_only")),
        Mutant("T-length-a-declared-length-past-the-bound-is-read", "a Content-Length past the bound is not refused up front (the body is then read, and refused only when it arrives)", TRANSPORT,
               "        if declared is not None and declared > MAX_BODY_BYTES:\n            raise BodyTooLarge(f\"Content-Length {declared} is past {MAX_BODY_BYTES}\")\n", "",
               (BD + "test_a_declared_length_past_the_bound_is_refused", BD + "test_a_declared_length_past_the_bound_is_refused_before_the_stream_is_read"),
               (BD + "test_a_body_of_exactly_the_bound_is_read_and_one_byte_more_is_not", CL + "test_control_the_complete_body_loads_all_three")),
        Mutant("T-bound-a-body-past-the-bound-is-returned", "a body of more than MAX_BODY_BYTES, delivered chunked or close-delimited, is returned whole", TRANSPORT,
               "    if len(data) > MAX_BODY_BYTES:\n        raise BodyTooLarge(f\"more than {MAX_BODY_BYTES} bytes\")\n", "",
               (BD + "test_a_body_of_exactly_the_bound_is_read_and_one_byte_more_is_not",),
               (BD + "test_a_declared_length_past_the_bound_is_refused", *CONTROLS)),
        Mutant("T-framing-transfer-encoding-with-content-length-is-read", "a response with both Transfer-Encoding and Content-Length is read under one of them", TRANSPORT,
               "        if encodings and lengths:\n", "        if False:\n",
               (IF + "test_each_is_refused_beside_its_control",),
               (CH + "test_control_complete_chunked_bodies_load_all_three", CL + "test_control_the_complete_body_loads_all_three")),
        Mutant("T-framing-another-transfer-coding-is-read", "a Transfer-Encoding other than exactly `chunked` (gzip, or chunked among others) is read as the library reads it (not chunked: the chunk framing becomes the body)", TRANSPORT,
               "        if encodings and [c.strip().lower() for v in encodings for c in v.split(\",\")] != [\"chunked\"]:\n", "        if False:\n",
               (IF + "test_each_is_refused_beside_its_control",), (CH + "test_control_complete_chunked_bodies_load_all_three",)),
        Mutant("T-framing-a-content-length-that-is-not-digits-is-read", "a Content-Length the RFC's grammar refuses (a sign, an underscore, hexadecimal, a list, repeated fields) is read as the library reads it", TRANSPORT,
               "        if lengths and (len(lengths) > 1 or not _DIGITS.fullmatch(lengths[0].strip())):\n", "        if False:\n",
               (IF + "test_each_is_refused_beside_its_control",), (CL + "test_control_the_complete_body_loads_all_three", CL + "test_whitespace_around_the_length_is_allowed_and_is_not_a_different_length")),
        Mutant("T-framing-the-librarys-reading-is-not-checked", "the library's settled framing (chunked or length) is trusted without comparing it to what the headers state", TRANSPORT,
               "        if resp.chunked != bool(encodings) or resp.length != declared:\n", "        if False:\n",
               (IF + "test_each_is_refused_beside_its_control",), (CL + "test_control_the_complete_body_loads_all_three", CH + "test_control_complete_chunked_bodies_load_all_three", ST + "test_a_bodyless_status_is_bodyless_whatever_its_content_length_says")),
        Mutant("T-framing-a-bodyless-status-is-checked-against-its-length", "a 204 or 304 is held to the Content-Length it carries (which describes the representation it did not send)", TRANSPORT,
               "    if resp.status not in (204, 304):\n", "    if True:\n",
               (ST + "test_a_bodyless_status_is_bodyless_whatever_its_content_length_says",), (ST + "test_an_error_status_keeps_its_status_and_a_complete_body_is_read",)),
        Mutant("T-error-a-cut-error-body-loses-the-status", "an error status whose body does not arrive whole becomes a status-less transport failure", TRANSPORT,
               "            return Response(e.code, header_map(e.headers), payload, url, error=why)\n", "            return Response(None, {}, b\"\", url, error=why or f\"HTTP {e.code}\")\n",
               (ST + "test_an_error_status_keeps_its_status_and_a_complete_body_is_read", ST + "test_a_429_keeps_its_retry_after_header_whatever_its_body_did"), (CL + "test_control_the_complete_body_loads_all_three",)),
        # ---- the chunked framing the transport reads itself (task 2b-repair-15; Astra F1)
        Mutant("T-chunked-the-size-is-read-by-int", "a chunk size is whatever `int(line, 16)` reads (`+0`, `0x0`, `-8E`, `8_E`, a space): http.client's own reading", TRANSPORT,
               "        match = _CHUNK_HEAD.fullmatch(head)\n        if match is None:\n            raise FramingError(f\"chunked framing: {head[:40]!r} is no chunk size (1*HEXDIG, then extensions: RFC 9112 §7.1)\")\n        size = int(match.group(1), 16)\n",
               "        size = int(head.split(b\";\")[0], 16)\n",
               (ASTRA, SYNTAX, SHORT), CH_CONTROLS),
        Mutant("T-chunked-the-extension-syntax-is-not-checked", "anything after a valid size is an extension (`8E;`, an unterminated quoted value, a stray character)", TRANSPORT,
               "        match = _CHUNK_HEAD.fullmatch(head)\n", "        match = re.match(rb\"([0-9A-Fa-f]+)\", head)\n",
               (SYNTAX,), CH_CONTROLS),
        Mutant("T-chunked-the-crlf-after-the-data-is-not-checked", "the two bytes after a chunk's data are skipped, whatever they are (`XX`, a bare LF, a size run into the data)", TRANSPORT,
               "        if end != b\"\\r\\n\":\n", "        if False:\n",
               (ASTRA, SYNTAX), CH_CONTROLS),
        Mutant("T-chunked-eof-in-a-line-is-the-end-of-it", "a framing line cut by EOF is taken as it arrived: `0` and EOF is a last chunk, a cut trailer field is a trailer, a missing final CRLF is the final CRLF (http.client's reading)", TRANSPORT,
               "        if not got.endswith(b\"\\n\"):\n            raise http.client.IncompleteRead(b\"\".join(pieces))   # the connection ended inside the line\n",
               "        if not got.endswith(b\"\\n\"):\n            return got.rstrip(b\"\\r\")\n",
               (ASTRA, CUT), CH_CONTROLS),
        Mutant("T-chunked-eof-in-a-chunks-data-is-the-end-of-the-body", "a chunk cut short by EOF ends the body as it is", TRANSPORT,
               "                raise http.client.IncompleteRead(b\"\".join(pieces), left)\n", "                return b\"\".join(pieces)\n",
               (SHORT,), CH_CONTROLS),
        Mutant("T-chunked-a-bare-lf-ends-a-line", "a framing line ended by LF alone is a line (a size, a trailer field)", TRANSPORT,
               "            raise FramingError(f\"chunked framing: {what} ends in a bare LF (RFC 9112 §7.1)\")\n", "            return got[:-1]\n",
               (SYNTAX,), CH_CONTROLS),
        Mutant("T-chunked-a-trailer-line-need-not-be-a-field", "any line before the final CRLF is a trailer field (`not a field`, an obsolete fold)", TRANSPORT,
               "        if _TRAILER_FIELD.fullmatch(field) is None:\n", "        if False:\n",
               (SYNTAX,), CH_CONTROLS),
        Mutant("T-chunked-a-framing-line-has-no-length-bound", "a size line or trailer line past the line bound is not refused for its length", TRANSPORT,
               "        if len(got) > _MAX_LINE:\n            raise FramingError(f\"chunked framing: {what} is longer than {_MAX_LINE} bytes\")\n", "",
               (CH + "test_a_framing_line_past_the_line_bound_is_refused",), CH_CONTROLS),
        Mutant("T-chunked-an-announced-size-past-the-bound-is-read", "the total the chunks announce is not held to the bound before a chunk is read", TRANSPORT,
               "        if total > MAX_BODY_BYTES:\n            raise BodyTooLarge(f\"the chunks announce more than {MAX_BODY_BYTES} bytes\")\n", "",
               (BD + "test_a_chunk_that_announces_more_than_the_bound_is_refused_before_its_data_is_read", BD + "test_chunks_that_together_pass_the_bound_and_a_trailer_section_past_it_are_refused",
                BD + "test_a_body_of_exactly_the_bound_is_read_and_one_byte_more_is_not"), CH_CONTROLS),
        Mutant("T-chunked-the-trailer-section-has-no-bound", "a trailer section of any size is read", TRANSPORT,
               "        if seen > MAX_BODY_BYTES:\n            raise BodyTooLarge(f\"the trailer section is past {MAX_BODY_BYTES} bytes\")\n", "",
               (BD + "test_chunks_that_together_pass_the_bound_and_a_trailer_section_past_it_are_refused",), CH_CONTROLS),
        Mutant("T-chunked-the-body-is-left-to-the-library", "a chunked body is read by http.client's decoder, not by the transport's reader", TRANSPORT,
               "    if resp.chunked:\n        return _read_chunked(resp.fp)\n", "",
               (ASTRA, CUT), CH_CONTROLS),
    ]
