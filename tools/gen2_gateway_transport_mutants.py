"""Task 2b-repair-14 (Astra F1 / R13C-1): the gateway mutants of the transport's framing completion (adapters/base.py `_read_body`).

A response is a success only when its HTTP message is complete (RFC 9112 §6.3, §7.1). The mutants here remove ONE rule of it in a temporary copy and name the tests that must notice
(tests/test_transport_framing.py, over a real loopback socket, through the real Transport, Client, DOAJ loader and `index.load`):

  T-length-*   a body shorter than its Content-Length is a success; a declared length past the bound is read before it is refused;
  T-bound-*    a body past MAX_BODY_BYTES is returned;
  T-framing-*  a message whose framing is invalid or conflicts (Transfer-Encoding with Content-Length, another coding, a Content-Length that repeats or is not digits) is read under
               one of its framings; the library's lenient reading of the headers is not checked against the RFC's;
  T-error-*    an error status loses its status when its body does not arrive whole.

A killer must FAIL in its assertions, not error (tools/gen2_gateway_mutations.py). A control takes the accepted path through the same code.
"""
from __future__ import annotations

BASE = "research_gateway/adapters/base.py"
TF = "tests.test_transport_framing."
CL, CH, BD, IF, ST, CD = TF + "ContentLength.", TF + "Chunked.", TF + "Bound.", TF + "InvalidFraming.", TF + "Statuses.", TF + "CloseDelimited."
CONTROLS = (CL + "test_control_the_complete_body_loads_all_three", CH + "test_control_complete_chunked_bodies_load_all_three", CD + "test_control_a_complete_close_delimited_body_loads")


def build(Mutant) -> list:
    """The mutants (tools/gen2_gateway_mutants.py: `Mutant`)."""
    return [
        Mutant("T-length-a-short-body-is-a-success", "a body that ends before its Content-Length is returned as the response (HTTPResponse.read(amt) does not raise): Astra's zero- and one-journal loads", BASE,
               "    if resp.length:   # a Content-Length with bytes still to come: the connection ended before the message did\n        raise http.client.IncompleteRead(data, resp.length)\n", "",
               (CL + "test_a_body_cut_after_the_headers_is_not_a_load_of_nothing", ST + "test_an_error_status_with_a_cut_body_keeps_its_status_and_says_the_body_is_not_here"),
               (*CONTROLS, CL + "test_control_the_cuts_are_valid_documents_that_a_csv_reader_alone_would_load", CL + "test_a_body_longer_than_its_length_is_read_to_the_length_only")),
        Mutant("T-length-a-declared-length-past-the-bound-is-read", "a Content-Length past the bound is not refused up front (the body is then read, and refused only when it arrives)", BASE,
               "        if declared is not None and declared > MAX_BODY_BYTES:\n            raise BodyTooLarge(f\"Content-Length {declared} is past {MAX_BODY_BYTES}\")\n", "",
               (BD + "test_a_declared_length_past_the_bound_is_refused_before_any_of_the_body_is_read",),
               (BD + "test_a_body_of_exactly_the_bound_is_read_and_one_byte_more_is_not", CL + "test_control_the_complete_body_loads_all_three")),
        Mutant("T-bound-a-body-past-the-bound-is-returned", "a body of more than MAX_BODY_BYTES, delivered chunked or close-delimited, is returned whole", BASE,
               "    if len(data) > MAX_BODY_BYTES:\n        raise BodyTooLarge(f\"more than {MAX_BODY_BYTES} bytes\")\n", "",
               (BD + "test_a_body_of_exactly_the_bound_is_read_and_one_byte_more_is_not",),
               (BD + "test_a_declared_length_past_the_bound_is_refused_before_any_of_the_body_is_read", *CONTROLS)),
        Mutant("T-framing-transfer-encoding-with-content-length-is-read", "a response with both Transfer-Encoding and Content-Length is read under one of them", BASE,
               "        if encodings and lengths:\n", "        if False:\n",
               (IF + "test_each_is_refused_beside_its_control",),
               (CH + "test_control_complete_chunked_bodies_load_all_three", CL + "test_control_the_complete_body_loads_all_three")),
        Mutant("T-framing-another-transfer-coding-is-read", "a Transfer-Encoding other than exactly `chunked` (gzip, or chunked among others) is read as the library reads it (not chunked: the chunk framing becomes the body)", BASE,
               "        if encodings and [c.strip().lower() for v in encodings for c in v.split(\",\")] != [\"chunked\"]:\n", "        if False:\n",
               (IF + "test_each_is_refused_beside_its_control",), (CH + "test_control_complete_chunked_bodies_load_all_three",)),
        Mutant("T-framing-a-content-length-that-is-not-digits-is-read", "a Content-Length the RFC's grammar refuses (a sign, an underscore, hexadecimal, a list, repeated fields) is read as the library reads it", BASE,
               "        if lengths and (len(lengths) > 1 or not _DIGITS.fullmatch(lengths[0].strip())):\n", "        if False:\n",
               (IF + "test_each_is_refused_beside_its_control",), (CL + "test_control_the_complete_body_loads_all_three", CL + "test_whitespace_around_the_length_is_allowed_and_is_not_a_different_length")),
        Mutant("T-framing-the-librarys-reading-is-not-checked", "the library's settled framing (chunked or length) is trusted without comparing it to what the headers state", BASE,
               "        if resp.chunked != bool(encodings) or resp.length != declared:\n", "        if False:\n",
               (IF + "test_each_is_refused_beside_its_control",), (CL + "test_control_the_complete_body_loads_all_three", CH + "test_control_complete_chunked_bodies_load_all_three", ST + "test_a_bodyless_status_is_bodyless_whatever_its_content_length_says")),
        Mutant("T-framing-a-bodyless-status-is-checked-against-its-length", "a 204 or 304 is held to the Content-Length it carries (which describes the representation it did not send)", BASE,
               "    if resp.status not in (204, 304):\n", "    if True:\n",
               (ST + "test_a_bodyless_status_is_bodyless_whatever_its_content_length_says",), (ST + "test_an_error_status_keeps_its_status_and_a_complete_body_is_read",)),
        Mutant("T-error-a-cut-error-body-loses-the-status", "an error status whose body does not arrive whole becomes a status-less transport failure", BASE,
               "            return Response(e.code, header_map(e.headers), payload, url, error=why)\n", "            return Response(None, {}, b\"\", url, error=why or f\"HTTP {e.code}\")\n",
               (ST + "test_an_error_status_keeps_its_status_and_a_complete_body_is_read", ST + "test_a_429_keeps_its_retry_after_header_whatever_its_body_did"), (CL + "test_control_the_complete_body_loads_all_three",)),
    ]
