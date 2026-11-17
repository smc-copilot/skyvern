#!/usr/bin/env python3
"""Machine-checkable VNC/websockify oracle for PR-00 (GAP-VNC-ORACLE).

本轮澄清决策: Host 16080 maps to container 6080, which is websockify in front
of x11vnc (RFB on localhost:5900). Health requires a WebSocket 101 upgrade and
an RFB banner. Container `running`, TCP-open-only, and Dashboard HTTP 200 are
not VNC PASS.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import sys
from pathlib import Path
from typing import Any

from constants import ENTERPRISE_VNC_PORT_DEFAULT, VNC_ORACLE_TIMEOUT_SECONDS, VNC_RFB_PREFIX
from errors import EnterpriseError

HTTP_200_IS_NOT_VNC = "VNC_HTTP_NOT_WEBSOCKET"


def _read_http_headers(sock: socket.socket) -> tuple[bytes, bytes]:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
        if len(data) > 65536:
            raise EnterpriseError("VNC_HANDSHAKE_FAILED", "HTTP header too large")
    header, leftover = data.split(b"\r\n\r\n", 1)
    return header, leftover


def _recv_exact(sock: socket.socket, buffer: bytearray, size: int) -> bytes:
    while len(buffer) < size:
        chunk = sock.recv(size - len(buffer))
        if not chunk:
            break
        buffer.extend(chunk)
    data = bytes(buffer[:size])
    del buffer[:size]
    return data


def _decode_ws_payloads(sock: socket.socket, leftover: bytes = b"", *, limit: int = 4096) -> bytes:
    buffer = bytearray(leftover)
    payload = b""
    while len(payload) < limit:
        header = _recv_exact(sock, buffer, 2)
        if len(header) < 2:
            return payload
        b0, b1 = header[0], header[1]
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F
        if length == 126:
            ext = _recv_exact(sock, buffer, 2)
            if len(ext) < 2:
                return payload
            length = struct.unpack("!H", ext)[0]
        elif length == 127:
            ext = _recv_exact(sock, buffer, 8)
            if len(ext) < 8:
                return payload
            length = struct.unpack("!Q", ext)[0]
        mask = b""
        if masked:
            mask = _recv_exact(sock, buffer, 4)
            if len(mask) < 4:
                return payload
        body = _recv_exact(sock, buffer, length)
        if len(body) < length:
            payload += body
            return payload
        if masked:
            body = bytes(b ^ mask[i % 4] for i, b in enumerate(body))
        if opcode == 0x8:
            break
        if opcode in {0x1, 0x2, 0x0}:
            payload += body
            if VNC_RFB_PREFIX in payload:
                return payload
    return payload


def probe_vnc(host: str, port: int, timeout_s: float = VNC_ORACLE_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Probe websockify+RFB. Raises EnterpriseError on failure."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    try:
        try:
            sock.connect((host, port))
        except OSError as exc:
            raise EnterpriseError("VNC_PORT_CLOSED", f"{host}:{port} {exc}") from exc
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            "GET / HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Sec-WebSocket-Protocol: binary\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        try:
            header_raw, leftover = _read_http_headers(sock)
        except TimeoutError as exc:
            raise EnterpriseError("VNC_TIMEOUT", f"timed out after {timeout_s}s") from exc
        header_text = header_raw.decode("latin1", errors="replace")
        status_line = header_text.split("\r\n", 1)[0]
        parts = status_line.split()
        code = parts[1] if len(parts) > 1 else "000"
        if code == "200":
            raise EnterpriseError(
                HTTP_200_IS_NOT_VNC,
                "HTTP 200 on the VNC port is not a websockify/RFB handshake",
            )
        if code != "101":
            raise EnterpriseError("VNC_HANDSHAKE_FAILED", f"expected 101, got {status_line!r}")
        try:
            payload = _decode_ws_payloads(sock, leftover)
        except TimeoutError as exc:
            raise EnterpriseError("VNC_TIMEOUT", "timed out waiting for RFB after 101") from exc
        if VNC_RFB_PREFIX not in payload:
            raise EnterpriseError(
                "VNC_RFB_MISSING",
                "WebSocket 101 succeeded but no RFB banner (x11vnc not speaking)",
            )
        return {
            "ok": True,
            "host": host,
            "port": port,
            "http_upgrade": 101,
            "rfb_banner_present": True,
            "timeout_s": timeout_s,
        }
    finally:
        sock.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=ENTERPRISE_VNC_PORT_DEFAULT)
    parser.add_argument("--timeout", type=float, default=VNC_ORACLE_TIMEOUT_SECONDS)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    try:
        report = probe_vnc(args.host, args.port, timeout_s=args.timeout)
        print(json.dumps(report, indent=2, sort_keys=True))
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    except EnterpriseError as exc:
        print(exc.code, file=sys.stderr)
        print(exc.message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
