"""A loopback TCP server whose every connection runs a script (not collected as tests).

What the whole-exchange deadline is tested against (test_gateway_exchange.py): a real socket that is slow in a way
a fake transport, which already honours the timeout it is handed, cannot be. A script is a function of the open
connection and what the client sent; every wait in it is `server.pause(seconds)`, which returns True at once when the
server is being stopped, so stop() ends every connection and joins every thread it started: no thread is left running
behind a test, and a test checks that (`ThreadsJoined`).
"""
from __future__ import annotations

import socket
import ssl
import threading
import unittest
from typing import Callable


def read_request(conn: socket.socket) -> tuple[bytes, bytes]:
    """(the request line and headers, the body) of one HTTP request, as far as it was sent."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(65536)
        if not chunk:
            return data, b""
        data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    length = 0
    for line in head.split(b"\r\n")[1:]:
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            length = int(value)
    while len(body) < length:
        chunk = conn.recv(65536)
        if not chunk:
            break
        body += chunk
    return head, body


class Loopback:
    """`script(server, conn, head, body)` runs once per accepted connection, in its own thread, after the request was
    read (`read=False`: not read at all). `tls`: a (certificate, key) path pair the connection is wrapped with first, after
    `handshake_after` seconds."""

    def __init__(self, script: Callable, *, read: bool = True, tls: tuple[str, str] | None = None, backlog: int = 16,
                 handshake_after: float = 0.0) -> None:
        self.script, self.read, self.released, self._handshake_after = script, read, threading.Event(), handshake_after
        self._tls = None
        if tls:
            self._tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self._tls.load_cert_chain(*tls)
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(backlog)
        self._listener.settimeout(0.05)
        self.port = self._listener.getsockname()[1]
        self._conns: list[socket.socket] = []
        self._threads = [threading.Thread(target=self._accept_loop, daemon=True)]
        self._lock = threading.Lock()
        self._threads[0].start()

    @property
    def url(self) -> str:
        return f"{'https' if self._tls else 'http'}://127.0.0.1:{self.port}"

    def pause(self, seconds: float) -> bool:
        """Wait `seconds`; True when the server is being stopped (the script should end)."""
        return self.released.wait(seconds)

    def send(self, conn: socket.socket, parts: list[tuple[float, bytes]]) -> None:
        """Send each part after its own wait, ending at once when the client has gone or the server is stopping."""
        for wait, data in parts:
            if self.pause(wait):
                return
            try:
                conn.sendall(data)
            except OSError:
                return

    def _accept_loop(self) -> None:
        while not self.released.is_set():
            try:
                conn, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            conn.settimeout(None)
            with self._lock:
                self._conns.append(conn)
                thread = threading.Thread(target=self._serve, args=(conn,), daemon=True)
                self._threads.append(thread)
            thread.start()

    def _serve(self, raw: socket.socket) -> None:
        conn = raw
        try:
            if self._tls:
                if self.pause(self._handshake_after):
                    return
                conn = self._tls.wrap_socket(raw, server_side=True)
                with self._lock:
                    self._conns.append(conn)
            head, body = read_request(conn) if self.read else (b"", b"")
            self.script(self, conn, head, body)
        except (OSError, ssl.SSLError):
            pass   # the client gave up, which is what most scripts are for
        finally:
            for sock in (conn, raw):
                try:
                    sock.close()
                except OSError:
                    pass

    def stop(self) -> None:
        self.released.set()
        self._listener.close()
        self._threads[0].join(10)   # the accepting thread first: no connection is taken, and no thread started, after the snapshot below
        with self._lock:
            conns, threads = list(self._conns), list(self._threads)
        for conn in conns:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()
        for thread in threads[1:]:
            thread.join(10)


class ThreadsJoined(unittest.TestCase):
    """A test that starts servers: when it has ended and its cleanups have run, every thread it started has ended."""

    def setUp(self) -> None:
        super().setUp()
        before = set(threading.enumerate())
        self.addCleanup(lambda: self.assertEqual(sorted(t.name for t in set(threading.enumerate()) - before), [],
                                                 "a thread was left running"))

    def serve(self, script: Callable, **kw) -> Loopback:
        server = Loopback(script, **kw)
        self.addCleanup(server.stop)
        return server
