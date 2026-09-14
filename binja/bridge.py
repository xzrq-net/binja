"""Resident receiver loaded through the managed startup.py."""
import os
from pathlib import Path
import socket
import threading
import traceback

import binaryninja as bn

from .common import Error, PROTOCOL, build_config, receive, send
from .targets import Targets, on_ui
from .execution import Execution


class Bridge:
    def __init__(self):
        self.state = Path(os.environ["BINJA_STATE_DIR"])
        self.generation = os.environ["BINJA_GENERATION"]
        self.targets = Targets(self.generation)
        self.execution = Execution(self, bn)

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
                result["requests"] = [{k: r[k] for k in ("id", "status", "target_snapshot")} for r in self.execution.list() if r["status"] not in ("completed", "failed", "cancelled")]
            return result
        if operation == "targets":
            return on_ui(self.targets.refresh)
        if operation == "prepare_stop":
            return self.execution.prepare_stop()
        if operation == "submit":
            return self.execution.submit(request["spec"])
        if operation == "request":
            return self.execution.get(request["id"])
        if operation == "requests":
            return self.execution.list(all_history=request.get("all", False))
        if operation == "cancel":
            return self.execution.cancel(request["id"])
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
