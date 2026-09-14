"""Shared wire format. This module never imports Binary Ninja."""
import json
import os
from pathlib import Path
import socket

PROTOCOL = 2
MAX_MESSAGE = 4 * 1024 * 1024


class Error(Exception):
    pass


def build_config():
    return json.loads(Path(__file__).with_name("build.json").read_text())


def state_path(value):
    state = Path(value or ".binja").expanduser().resolve()
    if len(os.fsencode(state / "runtime/control.sock")) > 107:
        raise Error("State path is too long for Unix sockets; choose a shorter --state-dir.")
    return state


def receive(connection):
    with connection.makefile("rb") as stream:
        line = stream.readline(MAX_MESSAGE + 1)
    if not line.endswith(b"\n") or len(line) > MAX_MESSAGE:
        raise Error("Invalid or oversized RPC message (limit 4 MiB).")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise Error("RPC message must be a JSON object.")
    return value


def send(connection, value):
    data = json.dumps(value, allow_nan=False).encode() + b"\n"
    if len(data) > MAX_MESSAGE:
        raise Error("RPC message exceeds 4 MiB.")
    connection.sendall(data)


def rpc(state, operation, *, generation=None, control=False, timeout=5, **params):
    if generation is None:
        try:
            generation = json.loads((state / "runtime/instance.json").read_text())["generation"]
        except (OSError, ValueError, KeyError) as exc:
            raise Error(f"No session metadata in {state}; run binja start.") from exc
    request = dict(protocol=PROTOCOL, generation=generation, op=operation, **params)
    endpoint = state / "runtime" / ("control.sock" if control else "rpc.sock")
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(timeout)
            connection.connect(str(endpoint))
            send(connection, request)
            response = receive(connection)
    except (OSError, ValueError) as exc:
        raise Error(f"Session endpoint unavailable: {exc}. Inspect {state / 'logs'}.") from exc
    if response.get("protocol") != PROTOCOL or response.get("generation") != generation:
        raise Error("Session identity or protocol mismatch; run status and check the installed CLI.")
    if "error" in response:
        raise Error(response["error"])
    return response["data"]


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)
