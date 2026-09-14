"""Serialized scripts, per-thread output capture, and generation-local recovery."""
from collections import OrderedDict, deque
from contextlib import contextmanager
import json
from pathlib import Path
import queue
import re
import sys
import threading
import time
import traceback

from .common import Error
from .targets import on_ui

KEEP_RESULTS = 64
MAX_PENDING = 8
KEEP_REJECTIONS = 64
OUTPUT_BYTES = 1024 * 1024
RESULT_BYTES = 8 * 1024 * 1024
INLINE_BYTES = 16 * 1024
TERMINAL = {"completed", "failed", "cancelled"}


def script_traceback(exc):
    """Hide execution wrappers, retaining script and downstream API frames."""
    trace = traceback.TracebackException.from_exception(exc)
    def trim(item):
        while item.stack and item.stack[0].filename == __file__:
            del item.stack[0]
        for nested in (item.__cause__, item.__context__):
            if nested is not None:
                trim(nested)
        for nested in getattr(item, "exceptions", None) or ():
            trim(nested)
    trim(trace)
    return "".join(trace.format())


class ThreadOutput:
    """Delegate unrelated threads to the GUI's original stream."""
    def __init__(self, original):
        self.original = original
        self.local = threading.local()

    def write(self, value):
        sink = getattr(self.local, "sink", None)
        return (sink or self.original).write(value)

    def flush(self):
        sink = getattr(self.local, "sink", None)
        return (sink or self.original).flush()

    def __getattr__(self, name):
        return getattr(self.original, name)

    @contextmanager
    def capture(self, sink):
        previous = getattr(self.local, "sink", None)
        self.local.sink = sink
        try:
            yield
        finally:
            self.local.sink = previous


class Output:
    def __init__(self, path):
        self.path = path
        self.stream = path.open("wb")
        self.size = 0
        self.truncated = False

    def write(self, text):
        data = text.encode("utf-8", errors="replace")
        room = OUTPUT_BYTES - self.size
        self.stream.write(data[:room])
        self.size += min(len(data), room)
        self.truncated |= len(data) > room
        return len(text)

    def flush(self):
        self.stream.flush()

    def finish(self):
        self.stream.close()
        value = {"text": self.path.read_bytes()[:INLINE_BYTES].decode("utf-8", errors="replace"),
                 "bytes": self.size}
        if self.size > INLINE_BYTES:
            value["artifact"] = str(self.path)
        value["truncated"] = self.truncated
        return value


class Execution:
    def __init__(self, bridge, bn):
        self.bridge = bridge
        self.bn = bn
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.rejected_total = 0
        self.rejections = deque(maxlen=KEEP_REJECTIONS)
        self.records = OrderedDict()
        self.work = queue.Queue()
        self.stopping = False
        self.stdout = ThreadOutput(sys.stdout)
        self.stderr = ThreadOutput(sys.stderr)
        sys.stdout = self.stdout
        sys.stderr = self.stderr
        threading.Thread(target=self.run, name="binja-worker", daemon=True).start()

    def validate_id(self, request_id):
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{12}:r[a-zA-Z0-9_-]{1,64}", request_id):
            raise Error("Request IDs must have the form GENERATION:rUNIQUE_ID.")
        if not request_id.startswith(self.bridge.generation + ":"):
            raise Error("Request belongs to an old generation; outcome is unknown/interrupted, with no rollback guarantee.")

    def snapshot(self, record):
        value = {k: v for k, v in record.items() if not k.startswith("_")}
        end = value.get("finished", time.time())
        started = value.get("started")
        value["queue_wait_seconds"] = max(0, (started if started is not None else end) - value["submitted"])
        value["execution_seconds"] = None if started is None else max(0, end - started)
        value["output_pruned"] = value.get("output_pruned", False)
        value["elapsed_seconds"] = value["execution_seconds"] if started is not None else value["queue_wait_seconds"]
        value["phase"] = value["status"] if value["status"] in TERMINAL else value.get("phase", value["status"])
        if record["status"] == "queued":
            pending = [r for r in self.records.values() if r["status"] not in TERMINAL]
            position = next(i for i, r in enumerate(pending) if r["id"] == record["id"])
            value["queue_position"] = sum(r["status"] == "queued" for r in pending[:position + 1])
            value["waits_behind"] = pending[position - 1]["id"] if position else None
        return value

    def get(self, request_id):
        self.validate_id(request_id)
        with self.lock:
            if request_id in self.records:
                return self.snapshot(self.records[request_id])
        raise Error("Unknown request ID; this is not proof that a submitted mutation ran or did not run. Do not blindly resubmit.")

    def wait(self, request_id, seconds):
        self.validate_id(request_id)
        with self.changed:
            if request_id not in self.records:
                return self.get(request_id)
            self.changed.wait_for(lambda: self.records[request_id]["status"] in TERMINAL, timeout=seconds)
            value = self.snapshot(self.records[request_id])
            if seconds > 0 and value["status"] not in TERMINAL:
                value["client_wait_expired"] = True
            return value

    def list(self, all_history=False):
        with self.lock:
            active = [r for r in self.records.values() if r["status"] not in TERMINAL]
            active.sort(key=lambda r: r["status"] == "queued")
            finished = sorted((r for r in self.records.values() if r["status"] in TERMINAL),
                key=lambda r: r["finished"], reverse=True)
            fields = ("id", "status", "target_snapshot", "target_snapshot_stage", "phase",
                "allow_incomplete", "submitted", "started", "finished", "elapsed_seconds",
                "queue_position", "waits_behind", "kind", "filename", "error", "output_pruned",
                "queue_wait_seconds", "execution_seconds")
            rows = [{k: v for k, v in self.snapshot(r).items() if k in fields}
                for r in active + (finished if all_history else finished[:5])]
            return dict(requests=rows, finished_total=len(finished),
                finished_shown=len(finished) if all_history else min(5, len(finished)),
                rejected_total=self.rejected_total, rejections=list(self.rejections))

    def submit(self, spec):
        request_id = spec.get("id")
        self.validate_id(request_id)
        if not isinstance(spec.get("source"), str) or not isinstance(spec.get("filename"), str):
            raise Error("Execution requires source text and a filename.")

        if spec.get("kind", "py") not in ("py", "open", "save"):
            raise Error("Request kind must be py, open, or save.")

        def check_duplicate():
            record = self.records.get(request_id)
            if record is not None:
                return dict(self.snapshot(record), admission_existing=True)
            if self.stopping:
                raise Error("Session is shutting down; no more submissions accepted.")
            pending = [r for r in self.records.values() if r["status"] not in TERMINAL]
            if len(pending) >= MAX_PENDING:
                running = next((r["id"] for r in pending if r["status"] != "queued"), "none")
                queued = sum(r["status"] == "queued" for r in pending)
                self.rejected_total += 1
                self.rejections.append(dict(id=request_id, time=time.time(), reason="pending_cap",
                    kind=spec.get("kind", "py"), filename=spec["filename"], running=running,
                    queued=queued, pending_cap=MAX_PENDING))
                raise Error(f"Request {request_id} was not accepted and will not execute: "
                    f"pending cap {MAX_PENDING}; running request: {running}; {queued} queued. "
                    "Safe to resubmit after capacity is available.")
            return None

        with self.lock:
            duplicate = check_duplicate()
            if duplicate:
                return duplicate
        bv, target = (None, None) if spec.get("no_target", False) else on_ui(lambda: self.bridge.targets.resolve(spec.get("target")))
        with self.lock:
            duplicate = check_duplicate()
            if duplicate:
                return duplicate
            record = dict(id=request_id, status="queued", target_snapshot=target, target_snapshot_stage="submission",
                allow_incomplete=bool(spec.get("allow_incomplete", False)), submitted=time.time(),
                kind=spec.get("kind", "py"), filename=spec["filename"],
                _spec=spec, _bv=bv)
            self.records[request_id] = record
            self.work.put(record)
            return self.snapshot(record)

    def cancel(self, request_id):
        self.validate_id(request_id)
        with self.lock:
            record = self.records.get(request_id)
            if record is None:
                return self.get(request_id)
            if record["status"] not in ("queued", "waiting_analysis"):
                raise Error("Only queued requests or readiness waits can be cancelled; running Python/native work cannot be interrupted safely.")
            record["status"] = "cancelled"
            record["finished"] = time.time()
            self.changed.notify_all()
            return self.snapshot(record)

    def wait_ready(self, bv, record, before_execution=True):
        if record["allow_incomplete"]:
            return
        with self.lock:
            if record["status"] == "cancelled":
                raise Error("Request cancelled before execution.")
            if before_execution:
                record["status"] = "waiting_analysis"
            record["phase"] = "waiting_analysis"
        while True:
            if record["status"] == "cancelled":
                raise Error("Request cancelled before execution.")
            state = bv.analysis_state
            # Raw has no analysis pipeline and remains InitialState in this API.
            if state == self.bn.AnalysisState.IdleState or (bv.view_type == "Raw" and state == self.bn.AnalysisState.InitialState):
                return
            if state == self.bn.AnalysisState.HoldState:
                raise Error("Analysis is on hold. Resume it explicitly with py --allow-incomplete, or deliberately allow incomplete results.")
            time.sleep(0.1)

    def prepare_stop(self):
        with self.lock:
            if any(r["status"] not in TERMINAL for r in self.records.values()):
                raise Error("Outstanding requests; inspect binja requests and wait or cancel queued work before stopping.")
            self.stopping = True
        try:
            targets = on_ui(self.bridge.targets.refresh)
            dirty = [t for t in targets if t["modified"] or t["analysis_changed"]]
            if dirty:
                paths = ", ".join(sorted({t["path"] for t in dirty}))
                raise Error(f"Unsaved analysis: {paths}. Save each file to a BNDB, or use stop --force to explicitly discard it.")
            return {"ready_to_stop": True}
        except BaseException:
            with self.lock:
                self.stopping = False
            raise

    def store_result(self, result, path):
        size = 0
        try:
            with path.open("w") as stream:
                for chunk in json.JSONEncoder(allow_nan=False).iterencode(result):
                    size += len(chunk.encode())
                    if size > RESULT_BYTES:
                        raise Error("JSON result exceeds 8 MiB. Write large data to an explicit artifact path in your script.")
                    stream.write(chunk)
        except (TypeError, ValueError) as exc:
            raise Error(f"result is not JSON serializable: {exc}. Return JSON values, not Binary Ninja objects; script edits remain applied.") from exc
        if size <= INLINE_BYTES:
            return {"result": json.loads(path.read_text()), "result_bytes": size}
        return {"result_artifact": str(path), "result_bytes": size}

    def execute(self, record):
        bv = record["_bv"]
        spec = record["_spec"]
        directory = self.bridge.state / "artifacts" / record["id"]
        directory.mkdir(mode=0o700)
        stdout, stderr = Output(directory / "stdout.txt"), Output(directory / "stderr.txt")
        outcome = {}

        def captured_ui(function):
            def invoke():
                with self.stdout.capture(stdout), self.stderr.capture(stderr):
                    return function()
            return on_ui(invoke)

        try:
            if bv is not None:
                on_ui(lambda: self.bridge.targets.resolve(record["target_snapshot"]["handle"]))
                self.wait_ready(bv, record)
                on_ui(lambda: self.bridge.targets.resolve(record["target_snapshot"]["handle"]))
            with self.lock:
                if record["status"] == "cancelled":
                    return
                record["status"] = "running"
                record["phase"] = "executing"
            scope = dict(bn=self.bn, bv=bv, args=spec.get("args", {}), result=None,
                on_ui=captured_ui, bridge=self.bridge, request=record, __name__="__binja_script__")
            with self.stdout.capture(stdout), self.stderr.capture(stderr):
                exec(compile(spec["source"], spec["filename"], "exec"), scope, scope)
            value = self.store_result(scope["result"], directory / "result.json")
            outcome = dict(value, status="completed")
        except BaseException as exc:
            with self.lock:
                if record["status"] != "cancelled":
                    outcome = dict(status="failed", error=f"{type(exc).__name__}: {exc}"[-INLINE_BYTES:])
                    if not isinstance(exc, Error):
                        outcome["traceback"] = script_traceback(exc)[-INLINE_BYTES:]
        finally:
            output, errors = stdout.finish(), stderr.finish()
            with self.lock:
                record.update(outcome, stdout=output, stderr=errors)
                record.setdefault("finished", time.time())
                self.changed.notify_all()
                record.pop("phase", None)
                record.pop("_bv", None)
                record.pop("_spec", None)

    def run(self):
        while True:
            record = self.work.get()
            try:
                with self.lock:
                    execute = record["status"] != "cancelled"
                    if execute:
                        record.update(status="running", phase="preparing", started=time.time())
                if execute:
                    self.execute(record)
            except BaseException as exc:
                # Artifact I/O can fail before script execution or during output finalization.
                with self.lock:
                    record.update(status="failed", error=f"Request infrastructure error: {exc}"[-INLINE_BYTES:], finished=time.time())
                    self.changed.notify_all()
            finally:
                with self.lock:
                    record.pop("_bv", None)
                    record.pop("_spec", None)
            with self.lock:
                finished = sorted((key for key, item in self.records.items()
                    if item["status"] in TERMINAL and not item.get("output_pruned")),
                    key=lambda key: self.records[key]["finished"])
                for key in finished[:-KEEP_RESULTS]:
                    item = self.records[key]
                    directory = self.bridge.state / "artifacts" / key
                    if "result" in item:
                        item["result_artifact"] = str(directory / "result.json")
                        item.pop("result")
                    for stream in ("stdout", "stderr"):
                        if stream in item:
                            item[stream] = {k: v for k, v in item[stream].items() if k != "text"}
                            item[stream]["artifact"] = str(directory / (stream + ".txt"))
                    item["output_pruned"] = True
