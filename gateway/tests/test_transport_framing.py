"""Task 2b-repair-14 (Astra F1 / R13C-1): a response is a success only when its HTTP message is complete, and every framing the transport reads is one it can tell the end of.

Astra served a three-row DOAJ dump from a loopback socket, kept the full Content-Length and cut the body after the header, or after the first record. `HTTPResponse.read(amt)` returned what had
arrived without raising: the lane was HTTP 200 / `ok`, `index.load` returned a count of 0 or 1 and committed it. A syntactically valid CSV prefix cannot say that it is a prefix, so the
completeness of the message is the transport's to establish (adapters/base.py `_read_body`; RFC 9112 §6.3, §7.1).

Everything below goes over a real loopback socket, through the real Transport, Client, DOAJ loader and `index.load` (against a database that records what it is asked), with the bytes of the
response written by hand so that its framing is exactly what the case says. What it covers, and what it cannot:

  * Content-Length  complete / cut after the headers / cut mid-record / cut at a record boundary / one byte short — only the complete one loads
  * chunked         complete (several chunks, an extension, a trailer) / cut after the headers / cut mid-chunk / cut at a chunk boundary with no terminal chunk — only the complete one loads
  * the bound       a declared length, a chunked body and a close-delimited body past MAX_BODY_BYTES are refused; a body of exactly the bound is read
  * deliberate handling of framing that is invalid or conflicts: Transfer-Encoding with Content-Length, a coding other than `chunked`, a Content-Length that repeats, a list, or is not digits
  * error statuses keep their status; a bodyless status (304) is bodyless whatever its Content-Length says
  * CLOSE-DELIMITED: with neither header, EOF is the end of the message (RFC 9112 §6.3 item 8). EOF cannot tell a deliberately shorter body from an interrupted one, so a close-delimited body cut at
    a record boundary loads as the shorter document it is. That case is a test of the ambiguity, stated, not a defence against it.
"""
from __future__ import annotations

import contextlib
import socket
import threading
import unittest
from unittest import mock

from research_gateway.adapters import base
from research_gateway.adapters.base import Client, Transport
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.harvest import index, registries
from tests.test_openers import Fake, HEAD, THREE


@contextlib.contextmanager
def serve(message: bytes):
    """The URL of a loopback server that answers its one request with exactly these bytes and closes the connection."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    sock.settimeout(10)

    def answer():
        try:
            conn, _ = sock.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(10)
            seen = b""
            while b"\r\n\r\n" not in seen:   # the request, whole, before the answer: closing on an unread request would reset the connection under the client
                more = conn.recv(65536)
                if not more:
                    break
                seen += more
            conn.sendall(message)
    thread = threading.Thread(target=answer, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{sock.getsockname()[1]}/csv"
    finally:
        sock.close()
        thread.join(5)


def message(framing: bytes, body: bytes, status: bytes = b"200 OK") -> bytes:
    return b"HTTP/1.1 " + status + b"\r\nContent-Type: text/csv\r\n" + framing + b"\r\n" + body


def chunked(*pieces: bytes, end: bytes = b"0\r\n\r\n") -> bytes:
    return b"".join(f"{len(p):X}\r\n".encode() + p + b"\r\n" for p in pieces) + end


FULL = THREE.encode()
RECORDS = FULL.splitlines(keepends=True)   # the header, then one line per journal
CL = lambda n: f"Content-Length: {n}\r\n".encode()   # noqa: E731
CHUNKED = b"Transfer-Encoding: chunked\r\n"


def outcome(raw: bytes) -> dict:
    """What the real stack makes of a response with these bytes: the loader's count (or its error), the database's commits and rollbacks, and the call the client logged."""
    with serve(raw) as url, mock.patch.object(registries, "DOAJ_CSV", url):
        db = Fake()
        client = Client(broker=Broker({"doaj": RatePolicy(per_second=100000)}), transport=Transport(), timeout=5, sleep=lambda _: None)
        try:
            count, error = index.load(db, lambda: registries.doaj_journals(client), "doaj", metadata_license="CC0"), None
        except Exception as e:   # the test judges what comes out
            count, error = None, f"{type(e).__name__}: {e}"
    call = client.log[0]
    return {"count": count, "error": error, "commits": db.commits, "rollbacks": db.rollbacks, "status": call.status, "class": call.failure_class}


def raw_response(raw: bytes) -> base.Response:
    with serve(raw) as url:
        return Transport().request("GET", url, {}, None, 5)


class Loaded(unittest.TestCase):
    """The outcome of a response that was a complete message: the whole dump, committed once, HTTP 200."""

    def assert_loaded(self, got: dict, count: int = 3):
        self.assertEqual((got["count"], got["error"], got["rollbacks"], got["status"], got["class"]), (count, None, 0, 200, "ok"), got)

    def assert_refused(self, got: dict, why: str):
        self.assertIsNone(got["count"], got)
        self.assertIn(why, got["error"], got)
        self.assertEqual(got["rollbacks"], 1, "a load that fails is rolled back, not committed as a shorter one")
        self.assertIsNone(got["status"], "no success status for a message that did not arrive whole")
        self.assertNotEqual(got["class"], "ok")


class ContentLength(Loaded):
    def test_control_the_complete_body_loads_all_three(self):
        self.assert_loaded(outcome(message(CL(len(FULL)), FULL)))

    def test_a_body_cut_after_the_headers_is_not_a_load_of_nothing(self):
        for label, cut in (("after the headers", 0), ("after the column header", len(RECORDS[0])), ("mid-record: inside the first journal", len(RECORDS[0]) + 8),
                           ("at a record boundary: one journal delivered", len(RECORDS[0]) + len(RECORDS[1])), ("at a record boundary: two delivered", len(b"".join(RECORDS[:3]))),
                           ("one byte short", len(FULL) - 1)):
            with self.subTest(label):
                self.assert_refused(outcome(message(CL(len(FULL)), FULL[:cut])), "IncompleteRead")

    def test_control_the_cuts_are_valid_documents_that_a_csv_reader_alone_would_load(self):
        """Why the framing is the transport's: the same bytes, delivered as a message whose Content-Length matches them, are a successful shorter load. Nothing in the CSV says it is a prefix."""
        for label, cut, count in (("column header only", len(RECORDS[0]), 0), ("one journal", len(RECORDS[0]) + len(RECORDS[1]), 1), ("two journals", len(b"".join(RECORDS[:3])), 2)):
            with self.subTest(label):
                self.assert_loaded(outcome(message(CL(cut), FULL[:cut])), count)

    def test_a_body_longer_than_its_length_is_read_to_the_length_only(self):
        """http.client reads the declared length and no more; the rest of the connection is not this message's."""
        self.assert_loaded(outcome(message(CL(len(FULL)), FULL + b"junk after the message")))

    def test_whitespace_around_the_length_is_allowed_and_is_not_a_different_length(self):
        self.assert_loaded(outcome(message(b"Content-Length:   " + str(len(FULL)).encode() + b"   \r\n", FULL)))


class Chunked(Loaded):
    def test_control_complete_chunked_bodies_load_all_three(self):
        cases = {"one chunk": chunked(FULL), "several chunks, cut inside a record": chunked(FULL[:25], FULL[25:60], FULL[60:]),
                 "a chunk extension": b"%X;name=value\r\n" % len(FULL) + FULL + b"\r\n0\r\n\r\n",
                 "a trailer field after the terminal chunk": chunked(FULL, end=b"0\r\nX-Checksum: 1\r\n\r\n")}
        for label, body in cases.items():
            with self.subTest(label):
                self.assert_loaded(outcome(message(CHUNKED, body)))

    def test_a_chunked_body_with_no_terminal_chunk_is_not_a_load(self):
        cases = {"after the headers": b"", "mid-chunk": f"{len(FULL):X}\r\n".encode() + FULL[:40],
                 "at a chunk boundary, one chunk delivered": chunked(FULL[:len(RECORDS[0]) + len(RECORDS[1])], end=b""),
                 "after the last chunk's data, before its line end": f"{len(FULL):X}\r\n".encode() + FULL,
                 "a chunk size that is not hexadecimal": b"zz\r\n" + FULL}
        for label, body in cases.items():
            with self.subTest(label):
                self.assert_refused(outcome(message(CHUNKED, body)), "IncompleteRead")


    def test_a_cut_inside_the_trailer_section_loses_trailer_fields_only(self):
        """The last-chunk (size 0) was read: every octet of the body arrived, and trailer fields are not the body (RFC 9112 §7.1.2). http.client takes the missing blank line at EOF as the end of
        the trailers (its own reading, kept), and the gateway reads no trailer field."""
        self.assert_loaded(outcome(message(CHUNKED, chunked(FULL, end=b"0\r\n"))))
        self.assert_loaded(outcome(message(CHUNKED, chunked(FULL, end=b"0\r\nX-Checksum: 1\r\n"))))


class CloseDelimited(Loaded):
    def test_control_a_complete_close_delimited_body_loads(self):
        self.assert_loaded(outcome(message(b"", FULL)))

    def test_the_ambiguity_stated_a_close_delimited_body_cut_at_a_record_boundary_is_a_shorter_document(self):
        """RFC 9112 §6.3 item 8: the end of such a message IS the close. A connection cut after the first journal is indistinguishable from a provider that sent one, so it loads as one
        (the CSV opener sees a well-formed document, tests/test_openers.py). A cut inside a record is still refused by the opener, whatever the framing."""
        self.assert_loaded(outcome(message(b"", FULL[:len(RECORDS[0]) + len(RECORDS[1])])), 1)
        got = outcome(message(b"", FULL[:len(RECORDS[0]) + 8]))
        self.assertEqual((got["count"], got["rollbacks"]), (1, 0), "a cut inside the first record is a short row: the same ambiguity, and not what the opener can know")


class Bound(Loaded):
    """The 256 MiB bound, exercised at 64 bytes (the module constant, patched): a body past it is an error Response, whatever frames it."""

    BOUND = 64

    def request(self, raw: bytes) -> base.Response:
        with mock.patch.object(base, "MAX_BODY_BYTES", self.BOUND):
            return raw_response(raw)

    def test_a_body_of_exactly_the_bound_is_read_and_one_byte_more_is_not(self):
        body = b"x" * self.BOUND
        for label, framing, wire in (("Content-Length", CL(self.BOUND), body), ("chunked", CHUNKED, chunked(body)), ("close-delimited", b"", body)):
            with self.subTest(label):
                got = self.request(message(framing, wire))
                self.assertEqual((got.status, got._body, got.error), (200, body, None))
        for label, framing, wire in (("Content-Length", CL(self.BOUND + 1), body + b"y"), ("chunked", CHUNKED, chunked(body + b"y")), ("close-delimited", b"", body + b"y")):
            with self.subTest(label):
                got = self.request(message(framing, wire))
                self.assertEqual((got.status, got._body), (None, b""))
                self.assertIn(f"response exceeds {self.BOUND} bytes", got.error)

    def test_a_declared_length_past_the_bound_is_refused_before_any_of_the_body_is_read(self):
        got = self.request(message(CL(10 ** 12), b"x" * 10))   # a length that cannot be met, and a body that is shorter than the bound: it is the declared size that is refused
        self.assertEqual((got.status, got._body), (None, b""))
        self.assertIn("response exceeds", got.error)

    def test_an_error_status_past_the_bound_keeps_its_status(self):
        got = self.request(message(CL(self.BOUND + 1), b"x" * (self.BOUND + 1), status=b"503 Service Unavailable"))
        self.assertEqual((got.status, got._body), (503, b""))
        self.assertIn("body unusable", got.error)


class InvalidFraming(Loaded):
    """Framing that is invalid or conflicts is refused, not guessed at: no reading of such a message is defined (RFC 9112 §6.3 items 3 and 5; RFC 9110 §8.6)."""

    def test_each_is_refused_beside_its_control(self):
        cases = {
            "Transfer-Encoding and Content-Length together": (CHUNKED + CL(len(FULL)), chunked(FULL), "both Transfer-Encoding and Content-Length"),
            "a Transfer-Encoding that is not chunked": (b"Transfer-Encoding: gzip\r\n", FULL, "only `chunked` is read"),
            "chunked after another coding": (b"Transfer-Encoding: gzip, chunked\r\n", chunked(FULL), "only `chunked` is read"),
            "chunked before another coding": (b"Transfer-Encoding: chunked, gzip\r\n", chunked(FULL), "only `chunked` is read"),
            "two Content-Length fields that differ": (CL(len(FULL)) + CL(len(FULL) - 1), FULL, "not one number of digits"),
            "two Content-Length fields that agree": (CL(len(FULL)) * 2, FULL, "not one number of digits"),
            "a Content-Length list": (f"Content-Length: {len(FULL)}, {len(FULL)}\r\n".encode(), FULL, "not one number of digits"),
            "a signed Content-Length": (f"Content-Length: +{len(FULL)}\r\n".encode(), FULL, "not one number of digits"),
            "a negative Content-Length": (b"Content-Length: -1\r\n", FULL, "not one number of digits"),
            "a Content-Length with an underscore (Python's int() reads it)": (b"Content-Length: 1_0\r\n", FULL[:10], "not one number of digits"),
            "a hexadecimal Content-Length": (b"Content-Length: 0x10\r\n", FULL[:16], "not one number of digits"),
            "a fractional Content-Length": (b"Content-Length: 5.0\r\n", FULL[:5], "not one number of digits"),
            "an empty Content-Length": (b"Content-Length:\r\n", FULL, "not one number of digits"),
            "chunked with trailing whitespace, which the library does not read as chunked (its chunk framing would become the body)": (b"Transfer-Encoding: chunked \r\n", chunked(FULL),
                                                                                                                                   "read this response's framing"),
        }
        for label, (framing, body, why) in cases.items():
            with self.subTest(label):
                self.assert_refused(outcome(message(framing, body)), why)
        self.assert_loaded(outcome(message(CL(len(FULL)), FULL)))   # the controls: one valid length, and chunked alone
        self.assert_loaded(outcome(message(CHUNKED, chunked(FULL))))
        self.assert_loaded(outcome(message(b"Transfer-Encoding: Chunked\r\n", chunked(FULL))), 3)   # the coding's name is case-insensitive

    def test_the_refusal_is_an_error_response_with_no_status_and_no_body(self):
        got = raw_response(message(CHUNKED + CL(5), chunked(b"hello")))
        self.assertEqual((got.status, got._body), (None, b""))
        self.assertTrue(got.error.startswith("FramingError"), got.error)


class Statuses(unittest.TestCase):
    def test_an_error_status_keeps_its_status_and_a_complete_body_is_read(self):
        got = raw_response(message(CL(5), b"hello", status=b"500 Internal Server Error"))
        self.assertEqual((got.status, got._body, got.error), (500, b"hello", None))

    def test_an_error_status_with_a_cut_body_keeps_its_status_and_says_the_body_is_not_here(self):
        got = raw_response(message(CL(50), b"hello", status=b"500 Internal Server Error"))
        self.assertEqual((got.status, got._body), (500, b""))
        self.assertIn("IncompleteRead", got.error)
        self.assertIn("HTTP 500", got.error)

    def test_a_429_keeps_its_retry_after_header_whatever_its_body_did(self):
        got = raw_response(message(CL(50) + b"Retry-After: 30\r\n", b"cut", status=b"429 Too Many Requests"))
        self.assertEqual((got.status, got.retry_after_seconds()), (429, 30.0))

    def test_a_bodyless_status_is_bodyless_whatever_its_content_length_says(self):
        """RFC 9112 §6.3 item 2: a 304 has no content; the Content-Length it may carry describes the representation it did not send."""
        got = raw_response(message(CL(1234), b"", status=b"304 Not Modified"))
        self.assertEqual((got.status, got._body, got.error), (304, b"", None))


class FakeTransportIsNotTheRealOne(unittest.TestCase):
    def test_a_fake_transports_bodies_are_taken_as_they_are(self):
        """The framing check belongs to the real Transport; the test transport hands back the canned body whole (a Response has no framing)."""
        t = base.FakeTransport()
        t.add("GET", "https://example.org/", 200, HEAD)
        self.assertEqual(t.request("GET", "https://example.org/x", {}, None, 1)._body, HEAD.encode())


if __name__ == "__main__":
    unittest.main()
