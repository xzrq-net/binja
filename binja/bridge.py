"""Resident receiver loaded through the managed startup.py."""
from concurrent.futures import Future, TimeoutError
import math
import os
from pathlib import Path
import socket
import threading
import traceback

import binaryninja as bn
from PySide6.QtWidgets import QApplication

from .common import Error, PROTOCOL, build_config, receive, send
from .targets import Targets, on_ui
from .execution import Execution
from . import updates


class Bridge:
    def __init__(self):
        self.state = Path(os.environ["BINJA_STATE_DIR"])
        self.generation = os.environ["BINJA_GENERATION"]
        self.targets = Targets(self.generation)
        self.execution = Execution(self, bn)
        self.ui_probe = None
        self.ui_probe_lock = threading.Lock()

    def gui_status(self):
        # Reuse one pending probe while the UI is stuck; polling must not
        # accumulate waiting threads or main-thread callbacks.
        with self.ui_probe_lock:
            if self.ui_probe is None or self.ui_probe.done():
                probe = self.ui_probe = Future()

                def inspect():
                    try:
                        probe.set_result(dict(targets=self.targets.refresh(),
                            modal_open=QApplication.activeModalWidget() is not None))
                    except Exception as exc:
                        probe.set_exception(exc)

                try:
                    bn.execute_on_main_thread(inspect)
                except Exception as exc:
                    probe.set_exception(exc)
            probe = self.ui_probe
        try:
            return probe.result(timeout=.25)
        except TimeoutError:
            return dict(targets=None, modal_open=None, gui_error="UI status probe timed out")
        except Exception as exc:
            return dict(targets=None, modal_open=None, gui_error=f"UI status probe: {exc}")

    def dispatch(self, request):
        if request.get("protocol") != PROTOCOL:
            raise Error("CLI/plugin protocol mismatch; restart with the matching package.")
        if request.get("generation") != self.generation:
            raise Error("Old session generation; its execution outcomes are unknown/interrupted.")
        operation = request["op"]
        if operation in ("hello", "status"):
            config = build_config()
            result = dict(generation=self.generation, version=bn.core_version(),
                state_dir=str(self.state), docs=config["vendor"] + "/api-docs", python=__import__("sys").version)
            if operation == "status":
                result.update(self.gui_status())
                result["requests"] = [{k: r[k] for k in ("id", "status", "target_snapshot")} for r in self.execution.list()["requests"] if r["status"] not in ("completed", "failed", "cancelled")]
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
            envelope = dict(protocol=PROTOCOL, generation=self.generation)
            try:
                request = receive(connection)
                operation = request["op"]
                seconds = request.get("wait", 0)
                if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                        or not math.isfinite(seconds) or not 0 <= seconds <= threading.TIMEOUT_MAX - 5):
                    raise Error("wait must be finite, nonnegative seconds within the platform timeout limit.")
                if seconds and operation not in ("submit", "request"):
                    raise Error("wait is only supported for submit and request.")
                data = self.dispatch(request)
                if operation == "submit":
                    existing = data.pop("admission_existing", False)
                    send(connection, dict(envelope, event="accepted", existing=existing,
                        final=seconds == 0, data=data))
                    if seconds == 0:
                        return
                if operation in ("submit", "request"):
                    # Admission has already happened. Waiting never holds the UI thread.
                    connection.settimeout(max(5, seconds + 5))
                    data = self.execution.wait(data["id"], seconds)
                response = dict(envelope, event="result", final=True, data=data)
                send(connection, response)
            except Exception as exc:
                try:
                    send(connection, dict(envelope, event="result", final=True,
                        error=f"{type(exc).__name__}: {exc}"))
                except (OSError, Error):
                    pass

    def serve(self):
        endpoint = self.state / "runtime/rpc.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as listener:
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
        updates.start(bridge.state, bn)
    except Exception:
        bn.log_error(traceback.format_exc())
