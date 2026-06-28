"""A minimal RFC 6455 WebSocket *client*, standard library only.

Slack's Socket Mode needs a WebSocket and the stdlib ships no client, so we implement
the slice we need: TLS connect + HTTP Upgrade handshake, masked client frames, and
reassembly of (possibly fragmented) text frames with automatic ping/pong. This avoids a
third-party dependency and keeps the project installable anywhere.

Not a general-purpose library: it handles text/close/ping/pong, which is all Socket Mode
sends. Binary frames are ignored.
"""
from __future__ import annotations

import base64
import os
import socket
import ssl
import struct
import urllib.parse

OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


class WebSocketError(Exception):
    pass


class WebSocket:
    """A connected client. Use :meth:`connect` to build one."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = b""

    @classmethod
    def connect(cls, url: str, *, timeout: float = 30) -> "WebSocket":
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("ws", "wss"):
            raise WebSocketError(f"not a websocket url: {url}")
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "wss" else 80)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query

        raw = socket.create_connection((host, port), timeout=timeout)
        if parts.scheme == "wss":
            ctx = ssl.create_default_context()
            raw = ctx.wrap_socket(raw, server_hostname=host)

        key = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        raw.sendall(handshake.encode())

        ws = cls(raw)
        status_line = ws._read_http_response()
        if "101" not in status_line:
            raise WebSocketError(f"handshake failed: {status_line}")
        return ws

    # ---- handshake ---------------------------------------------------------
    def _read_http_response(self) -> str:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise WebSocketError("connection closed during handshake")
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        self._buf = rest                     # any framed bytes that arrived early
        return head.split(b"\r\n", 1)[0].decode("latin-1", "replace")

    # ---- frame I/O ---------------------------------------------------------
    def recv(self, *, timeout: float | None = None) -> str | None:
        """Return the next text message, or ``None`` on timeout / clean close.

        Control frames (ping/close) are handled transparently. Fragmented text messages
        are reassembled before returning.
        """
        self._sock.settimeout(timeout)
        message = b""
        try:
            while True:
                fin, opcode, payload = self._read_frame()
                if opcode == OP_PING:
                    self._send_frame(OP_PONG, payload)
                    continue
                if opcode == OP_PONG:
                    continue
                if opcode == OP_CLOSE:
                    try:
                        self._send_frame(OP_CLOSE, payload[:2])
                    except OSError:
                        pass
                    return None
                if opcode in (OP_TEXT, OP_CONT):
                    message += payload
                    if fin:
                        return message.decode("utf-8", "replace")
                # ignore binary frames
        except socket.timeout:
            return None

    def send_text(self, text: str) -> None:
        self._send_frame(OP_TEXT, text.encode("utf-8"))

    def close(self) -> None:
        try:
            self._send_frame(OP_CLOSE, b"")
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass

    # ---- low level ---------------------------------------------------------
    def _read_frame(self) -> tuple[bool, int, bytes]:
        b0, b1 = self._recv_exact(2)
        fin = bool(b0 & 0x80)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode])      # FIN + opcode
        length = len(payload)
        mask_bit = 0x80                          # client frames MUST be masked
        if length < 126:
            header.append(mask_bit | length)
        elif length < (1 << 16):
            header.append(mask_bit | 126)
            header += struct.pack(">H", length)
        else:
            header.append(mask_bit | 127)
            header += struct.pack(">Q", length)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._sock.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise WebSocketError("connection closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out
