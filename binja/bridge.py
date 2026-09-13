"""Resident receiver loaded through the managed startup.py."""
import os
from pathlib import Path
import socket
import threading
import traceback

import binaryninja as bn

from .common import Error, PROTOCOL, build_config, receive, send
from .targets import Targets, on_ui


class Bridge:
    def __init__(self):
        self.state = Path(os.environ["BINJA_STATE_DIR"])
        self.generation = os.environ["BINJA_GENERATION"]
        self.targets = Targets(self.generation)

    def dispatch(self, request):
        if request.get("protocol") != PROTOCOL:
            raise Error("CLI/plugin protocol mismatch; restart with the matching package.")
        if request.get("generation") != self.generation:
            raise Error("Old session generation; its execution outcomes are unknown/interrupted.")
        operation = request["op"]
        if operation in ("hello", "status"):
            config = build_config()
            result = dict(generation=self.generation, version=bn.core_version(), display="headless",
                state_dir=str(self.state), docs=config["vendor"] + "/api-docs", python=__import__("sys").version)
            if operation == "status":
                result["targets"] = on_ui(self.targets.refresh)
            return result
        if operation == "targets":
            return on_ui(self.targets.refresh)
        if operation == "prepare_stop":
            raise Error("Orderly stop is not implemented yet; use stop --force to explicitly discard this session.")
        raise Error(f"Unknown operation: {operation}")

    def handle(self, connection):
        with connection:
            connection.settimeout(5)
            response = dict(protocol=PROTOCOL, generation=self.generation)
            try:
                response["data"] = self.dispatch(receive(connection))
            except Exception as exc:
                response["error"] = f"{type(exc).__name__}: {exc}"
            try:
                send(connection, response)
            except OSError:
                pass

    def serve(self):
        endpoint = self.state / "runtime/rpc.sock"
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(str(endpoint))
            endpoint.chmod(0o600)
            listener.listen(16)
            while True:
                connection, _ = listener.accept()
                threading.Thread(target=self.handle, args=(connection,), daemon=True).start()


def start():
    global bridge
    try:
        bn.update.set_auto_updates_enabled(False)
        bridge = Bridge()
        threading.Thread(target=bridge.serve, name="binja-rpc", daemon=True).start()
    except Exception:
        bn.log_error(traceback.format_exc())
