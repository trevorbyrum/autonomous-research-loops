"""Deterministic time at the OS boundary; HTTP parsing and deadline code stay real.

ScriptedSocketTime emulates blocking calls using their actual socket timeout,
never the client's deadline calculation. It cannot prove kernel/TLS behaviour;
the separate loopback route and certificate tests exercise those real paths.
No client symbol is imported here: the mutation runner replaces that module.
"""
from __future__ import annotations

import contextlib
import socket
import ssl
from types import SimpleNamespace
from unittest import mock

from gen2.tests.virtual_time import VirtualTime


@contextlib.contextmanager
def deadline_clock(gateway, clock, *, wire=False):
    """Control _Deadline's runtime clock lookup without changing Python's global time.

    Real wire witnesses test routing, with no elapsed-time oracle: disable the
    kernel timer there so scheduling cannot consume their virtual budget.
    """
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(gateway, "time", SimpleNamespace(monotonic=clock.monotonic)))
        if wire:
            stack.enter_context(mock.patch.object(gateway._DeadlineSocket, "settimeout", lambda sock, seconds: socket.socket.settimeout(sock, None)))
        yield


class ScriptedSocketTime(VirtualTime):
    """A real connected socket, with scripted stdlib blocking primitives.

    Each (delay, bytes) read chunk costs virtual seconds, once, regardless of
    buffering. A delay exceeding the socket's armed timeout raises TimeoutError
    after spending that timeout. Missing reads block for 30 virtual seconds.
    Connect/handshake/write delays follow the same rule. Scripts and expected
    budgets are supplied by tests, independently of production _Deadline.
    """

    def __init__(self, parts=(), *, connect=0.0, handshake=0.0, write=0.0):
        super().__init__()
        self.parts = list(parts)
        self.connect_delay, self.handshake_delay, self.write_delay = connect, handshake, write
        self.calls = []

    def wait(self, sock, seconds, operation):
        timeout = sock.gettimeout()
        self.calls.append((operation, timeout))
        if timeout is not None and seconds > timeout:
            self.now += timeout
            raise TimeoutError("scripted blocking call timed out")
        self.now += seconds

    def read(self, sock, size):
        if not self.parts:
            self.wait(sock, 30.0, "read")
            return b""
        delay, data = self.parts.pop(0)
        self.wait(sock, delay, "read")
        if len(data) > size:
            self.parts.insert(0, (0.0, data[size:]))
        return data[:size]

    @contextlib.contextmanager
    def installed(self, gateway):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(64)
        self.port = listener.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        real_connect = socket.socket.connect

        def connect(sock, target):
            self.wait(sock, self.connect_delay, "connect")
            armed = sock.gettimeout()
            sock.settimeout(None)   # only virtual time can consume the script's budget
            try:
                return real_connect(sock, target)
            finally:
                sock.settimeout(armed)

        def recv_into(sock, buffer, size=0, flags=0):
            data = self.read(sock, size or len(buffer))
            buffer[:len(data)] = data
            return len(data)

        def tls_read(sock, size=1024, buffer=None):
            return self.read(sock, size) if buffer is None else recv_into(sock, buffer, size)

        def send(sock, data, *args):
            self.wait(sock, self.write_delay, "write")
            return len(data)

        with listener, contextlib.ExitStack() as stack:
            stack.enter_context(deadline_clock(gateway, self))
            stack.enter_context(mock.patch.object(gateway._DeadlineSocket, "settimeout", socket.socket.settimeout))
            for owner, name, replacement in (
                (socket.socket, "connect", connect),
                (socket.socket, "recv", lambda sock, size, *args: self.read(sock, size)),
                (socket.socket, "recv_into", recv_into),
                (socket.socket, "send", send),
                (socket.socket, "sendall", lambda sock, data, *args: (send(sock, data), None)[1]),
                (ssl.SSLSocket, "do_handshake", lambda sock, *args: self.wait(sock, self.handshake_delay, "handshake")),
                (ssl.SSLSocket, "read", tls_read),
                (ssl.SSLSocket, "send", send),
            ):
                stack.enter_context(mock.patch.object(owner, name, replacement))
            yield self
