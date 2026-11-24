"""A fake Neo4j server that speaks enough Bolt 5.4 for the real driver to log in.

It accepts one password. A LOGON with any other password gets the
``Neo.ClientError.Security.Unauthorized`` failure, and the connection closes,
as Neo4j does. Every query succeeds and returns no rows. Tests use it to run
the real driver's connection and retry code, which a mocked driver skips.
"""

from __future__ import annotations

import socket
import struct
import threading
from types import TracebackType
from typing import Any, Self

from neo4j._codec.packstream._common import PackableBuffer, UnpackableBuffer
from neo4j._codec.packstream.v1 import Packer, Unpacker

_BOLT_5_4 = b"\x00\x00\x04\x05"
_SUCCESS, _FAILURE = b"\x70", b"\x7f"
_UNAUTHORIZED = "Neo.ClientError.Security.Unauthorized"


def _frame(signature: bytes, metadata: dict[str, Any]) -> bytes:
    buffer = PackableBuffer()
    Packer(buffer).pack_struct(signature, [metadata])
    body = bytes(buffer.data)
    return struct.pack(">H", len(body)) + body + b"\x00\x00"


def _read_message(conn: socket.socket) -> bytes | None:
    """Read one chunked message, or return None when the client hangs up."""
    data = b""
    while True:
        head = conn.recv(2, socket.MSG_WAITALL)
        if len(head) < 2:
            return None
        (size,) = struct.unpack(">H", head)
        if size == 0:
            if data:
                return data
            continue
        data += conn.recv(size, socket.MSG_WAITALL)


def _logon_password(message: bytes) -> str:
    unpacker = Unpacker(UnpackableBuffer(message))
    unpacker.unpack_structure_header()
    return unpacker.unpack()["credentials"]


class FakeNeo4j:
    """Serve Bolt on a free local port until closed.

    ``password`` is the one the server accepts, and a test can change it.
    ``logins`` lists the password of every LOGON, in order.
    """

    def __init__(self, password: str) -> None:
        self.password = password
        self.logins: list[str] = []
        self._server = socket.create_server(("127.0.0.1", 0))
        self.uri = f"bolt://127.0.0.1:{self._server.getsockname()[1]}"
        threading.Thread(target=self._accept, daemon=True).start()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._server.close()

    def _accept(self) -> None:
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return  # closed
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        with conn:
            conn.recv(20, socket.MSG_WAITALL)  # the magic preamble and version offers
            conn.sendall(_BOLT_5_4)
            while (message := _read_message(conn)) is not None:
                reply, keep_open = self._reply(message)
                if reply:
                    conn.sendall(reply)
                if not keep_open:
                    return

    def _reply(self, message: bytes) -> tuple[bytes, bool]:
        """Answer one message, and say whether the connection stays open."""
        match message[1:2]:
            case b"\x01":  # HELLO
                return _frame(_SUCCESS, {"server": "Neo4j/5.26.0", "connection_id": "bolt-1"}), True
            case b"\x6a":  # LOGON
                password = _logon_password(message)
                self.logins.append(password)
                if password != self.password:
                    # Neo4j sends the failure and then closes the connection.
                    return _frame(_FAILURE, {"code": _UNAUTHORIZED, "message": "rejected"}), False
                return _frame(_SUCCESS, {}), True
            case b"\x02":  # GOODBYE
                return b"", False
            case b"\x10":  # RUN
                return _frame(_SUCCESS, {"fields": [], "t_first": 0}), True
            case b"\x3f":  # PULL
                return _frame(_SUCCESS, {"has_more": False, "t_last": 0, "db": "neo4j"}), True
            case b"\x12":  # COMMIT
                return _frame(_SUCCESS, {"bookmark": "bm:1"}), True
            case _:  # BEGIN, RESET, TELEMETRY, and ROUTE
                return _frame(_SUCCESS, {}), True
