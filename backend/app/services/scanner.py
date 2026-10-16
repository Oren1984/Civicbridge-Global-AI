"""ClamAV clamd client (INSTREAM over TCP). If the scanner is unreachable the result is 'scan_unavailable',
never 'clean'."""
from __future__ import annotations

import socket
import struct

from app.config import get_settings

CHUNK = 64 * 1024


def _connect() -> socket.socket:
    s = get_settings()
    sock = socket.create_connection((s.clamav_host, s.clamav_port), timeout=s.scanner_timeout_s)
    sock.settimeout(s.scanner_timeout_s)
    return sock


def _read_reply(sock: socket.socket) -> str:
    buf = b""
    while not buf.endswith(b"\0"):
        part = sock.recv(4096)
        if not part:
            break
        buf += part
    return buf.rstrip(b"\0").decode(errors="replace").strip()


def ping() -> tuple[bool, str]:
    try:
        with _connect() as sock:
            sock.sendall(b"zPING\0")
            reply = _read_reply(sock)
            return reply == "PONG", reply or "no reply"
    except OSError as exc:
        return False, type(exc).__name__


def version() -> str:
    try:
        with _connect() as sock:
            sock.sendall(b"zVERSION\0")
            return _read_reply(sock)
    except OSError as exc:
        return f"unavailable ({type(exc).__name__})"


def scan_bytes(data: bytes) -> tuple[str, str]:
    """Return (status, detail) where status is clean | infected | scan_unavailable | error."""
    try:
        with _connect() as sock:
            sock.sendall(b"zINSTREAM\0")
            for i in range(0, len(data), CHUNK):
                chunk = data[i : i + CHUNK]
                sock.sendall(struct.pack("!L", len(chunk)) + chunk)
            sock.sendall(struct.pack("!L", 0))
            reply = _read_reply(sock)
    except OSError as exc:
        return "scan_unavailable", f"scanner unreachable: {type(exc).__name__}"
    if reply.endswith("OK") and "FOUND" not in reply:
        return "clean", "ClamAV: no signature matched"
    if reply.endswith("FOUND"):
        sig = reply.split(":", 1)[-1].replace("FOUND", "").strip()
        return "infected", f"ClamAV signature: {sig}"[:300]
    return "error", f"unexpected scanner reply: {reply[:200]}"
