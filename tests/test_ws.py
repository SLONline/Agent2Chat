"""Frame-level tests for the minimal WebSocket client (no network)."""
import struct

from agent2chat.connectors.ws import OP_TEXT, WebSocket


class FakeSocket:
    """Feeds queued inbound bytes to recv() and records what was sent."""

    def __init__(self, inbound: bytes = b""):
        self._in = inbound
        self.sent = b""

    def recv(self, n):
        chunk, self._in = self._in[:n], self._in[n:]
        return chunk

    def sendall(self, data):
        self.sent += data

    def settimeout(self, t):
        pass

    def close(self):
        pass


def _server_text_frame(payload: bytes) -> bytes:
    """A server->client (unmasked) text frame."""
    header = bytearray([0x80 | OP_TEXT])
    if len(payload) < 126:
        header.append(len(payload))
    else:
        header.append(126)
        header += struct.pack(">H", len(payload))
    return bytes(header) + payload


def test_recv_decodes_text_frame():
    ws = WebSocket(FakeSocket(_server_text_frame(b"hello")))
    assert ws.recv(timeout=1) == "hello"


def test_recv_reassembles_fragments():
    # FIN=0 continuation: first text frame, then a continuation frame with FIN=1.
    frag1 = bytes([OP_TEXT, 3]) + b"foo"            # FIN=0, opcode=text
    frag2 = bytes([0x80 | 0x0, 3]) + b"bar"         # FIN=1, opcode=continuation
    ws = WebSocket(FakeSocket(frag1 + frag2))
    assert ws.recv(timeout=1) == "foobar"


def test_send_text_is_masked():
    fake = FakeSocket()
    ws = WebSocket(fake)
    ws.send_text("hi")
    sent = fake.sent
    assert sent[0] == 0x80 | OP_TEXT          # FIN + text opcode
    assert sent[1] & 0x80                      # mask bit set (client frames must be masked)
    length = sent[1] & 0x7F
    assert length == 2
    mask = sent[2:6]
    masked_payload = sent[6:8]
    unmasked = bytes(b ^ mask[i % 4] for i, b in enumerate(masked_payload))
    assert unmasked == b"hi"


def test_recv_handles_large_payload():
    payload = b"z" * 500                        # forces the 16-bit length path
    ws = WebSocket(FakeSocket(_server_text_frame(payload)))
    assert ws.recv(timeout=1) == "z" * 500
