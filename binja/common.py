"""Shared wire format. This module never imports Binary Ninja."""
import json
from pathlib import Path
import socket
import time

PROTOCOL = 3
CHUNK_BYTES = 32 * 1024
MAX_REQUEST = 4 * 1024 * 1024
MAX_RESPONSE = 64 * 1024 * 1024
DATA_PACKET = b"\x01"
END_PACKET = b"\x00"


class Error(Exception):
    pass


def build_config():
    return json.loads(Path(__file__).with_name("build.json").read_text())


def receive(connection, limit=MAX_REQUEST):
    """Read one framed JSON object; EOF is never a message terminator."""
    data = bytearray()
    timeout = connection.gettimeout()
    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        while True:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("RPC message receive timed out.")
                connection.settimeout(remaining)
            packet, _, flags, _ = connection.recvmsg(CHUNK_BYTES + 1)
            if flags & socket.MSG_TRUNC:
                raise Error("Oversized RPC packet.")
            if packet == END_PACKET:
                break
            if not packet:
                raise Error("Incomplete RPC message: disconnected before end packet.")
            if packet[:1] != DATA_PACKET or len(packet) == 1:
                raise Error("Invalid RPC data packet.")
            if len(data) + len(packet) - 1 > limit:
                raise Error(f"RPC message exceeds {limit} bytes.")
            data.extend(packet[1:])
    finally:
        connection.settimeout(timeout)
    value = json.loads(data)
    if not isinstance(value, dict):
        raise Error("RPC message must be a JSON object.")
    return value


def send(connection, value, limit=MAX_RESPONSE):
    data = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
    if len(data) > limit:
        raise Error(f"RPC message exceeds {limit} bytes.")
    for offset in range(0, len(data), CHUNK_BYTES):
        packet = DATA_PACKET + data[offset:offset + CHUNK_BYTES]
        if connection.send(packet) != len(packet):
            raise Error("Incomplete RPC packet send.")
    if connection.send(END_PACKET) != len(END_PACKET):
        raise Error("Incomplete RPC end packet send.")

