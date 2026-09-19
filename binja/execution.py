"""Serialized scripts, per-thread output capture, and generation-local recovery."""
from collections import OrderedDict, deque
from contextlib import contextmanager
import json
from pathlib import Path
import re
import shlex
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
REVALIDATE_SECONDS = 1
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
            pending = [r for r in self.records.values() if r["status"] not in TERMINAL
                and self.lane(r) == self.lane(record)]
            position = next(i for i, r in enumerate(pending) if r["id"] == record["id"])
            value["queue_position"] = sum(r["status"] == "queued" for r in pending[:position + 1])
            value["waits_behind"] = pending[position - 1]["id"] if position else None
        return value

    def get(self, request_id):
        self.validate_id(request_id)
        with self.lock:
            if request_id in self.records:
                return self.snapshot(self.records[request_id])
            if any(event["id"] == request_id for event in self.rejections):
                raise Error(f"Request {request_id} was rejected at capacity and never executed. "
                    "Safe to resubmit after capacity is available.")
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

        if spec.get("kind", "py") not in ("py", "open", "save", "close", "decompile", "il", "disasm", "xrefs", "refs",
                "callers", "info", "functions", "imports", "strings", "rename", "comment", "proto", "retype", "declare", "undo"):
            raise Error("Request kind must be py, open, save, close, decompile, il, disasm, xrefs, refs, callers, "
                "info, functions, imports, strings, rename, comment, proto, retype, declare, or undo.")

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
            self.check_close(target, spec.get("kind", "py"))
            record = dict(id=request_id, status="queued", target_snapshot=target, target_snapshot_stage="submission",
                allow_incomplete=bool(spec.get("allow_incomplete", False)), submitted=time.time(),
                kind=spec.get("kind", "py"), filename=spec["filename"],
                _spec=spec, _bv=bv)
            self.records[request_id] = record
            self.changed.notify_all()
            return self.snapshot(record)

    def cancel(self, request_id):
        self.validate_id(request_id)
        with self.lock:
            record = self.records.get(request_id)
            if record is None:
                return self.get(request_id)
            if record["status"] not in ("queued", "waiting_analysis"):
                raise Error("Only queued requests or readiness waits can be cancelled; running Python/native work cannot be interrupted safely.")
            self.finish(record, status="cancelled")
            return self.snapshot(record)

    @staticmethod
    def lane(record):
        return (record.get("target_snapshot") or {}).get("file_id")

    def lane_heads(self):
        # Called under the lock. Derive lanes from submission order so an open
        # can acquire its file identity without moving behind newer requests.
        heads = {}
        for record in self.records.values():
            if record["status"] not in TERMINAL:
                heads.setdefault(self.lane(record), record)
        return list(heads.values())

    def ready(self, record, bv):
        if bv is None:
            return True
        # Poll analysis off the UI thread. Periodically revalidate parked views
        # so a closed view fails without refreshing every target on every poll.
        # Never hold the scheduling lock while waiting on the UI.
        if time.monotonic() >= record.get("_next_revalidation", 0):
            on_ui(lambda: self.bridge.targets.resolve(record["target_snapshot"]["handle"]))
            with self.lock:
                if record["status"] not in TERMINAL:
                    record["_next_revalidation"] = time.monotonic() + REVALIDATE_SECONDS
        if record["allow_incomplete"] or record["kind"] == "close":
            return True
        state = bv.analysis_state
        # Raw has no analysis pipeline and remains InitialState in this API.
        if state == self.bn.AnalysisState.IdleState or (bv.view_type == "Raw" and state == self.bn.AnalysisState.InitialState):
            return True
        if state == self.bn.AnalysisState.HoldState:
            target = record["target_snapshot"]["handle"]
            resume = shlex.join(["binja", "--state-dir", str(self.bridge.state), "py",
                "--target", target, "--allow-incomplete", "-c",
                "bv.set_analysis_hold(False); bv.update_analysis_and_wait()"])
            raise Error(f"Analysis is on hold. Resume this target with:\n{resume}\n"
                "Or pass --allow-incomplete to deliberately use incomplete results.")
        return False

    def select(self):
        with self.lock:
            heads = self.lane_heads()
        for record in heads:
            with self.lock:
                if record["status"] in TERMINAL:
                    continue
                record.setdefault("started", time.time())
                bv = record["_bv"]
            error = None
            try:
                ready = self.ready(record, bv)
            except BaseException as exc:
                # Hold and expired handles run through normal failure capture.
                ready, error = True, exc
            with self.lock:
                if any(head["status"] in TERMINAL for head in heads):
                    return None  # Cancellation may have promoted an older head.
                if ready:
                    record.update(status="running", phase="executing", _readiness_error=error)
                    return record
                record.update(status="waiting_analysis", phase="waiting_analysis")
        return None

    def opened(self, record, bv, target):
        with self.lock:
            record.update(target_snapshot=target, target_snapshot_stage="open",
                _bv=bv, _open_pending=True)

    def check_close(self, target, kind, request_id=None):
        # Called under the admission lock; every view of a file shares its fate.
        if target is None:
            return
        pending = [r for r in self.records.values() if r["status"] not in TERMINAL
            and r["id"] != request_id
            and (r.get("target_snapshot") or {}).get("file_id") == target["file_id"]]
        closing = next((r for r in pending if r.get("kind") == "close"), None)
        if closing:
            raise Error(f"Close pending for {target['handle']}: {closing['id']}. "
                "Wait for it or cancel it before submitting more work; run binja targets afterwards.")
        if kind == "close" and pending:
            ids = ", ".join(r["id"] for r in pending)
            raise Error(f"Outstanding requests for {target['handle']}: {ids}. "
                "Inspect binja requests and wait or cancel queued work before closing; "
                "--force only discards unsaved changes.")

    def close(self, record, force):
        def close_on_ui():
            # Take the lock on the UI thread, never while waiting for it. The
            # worker is paused here; admission cannot race the final check/close.
            with self.lock:
                _, target = self.bridge.targets.resolve(record["target_snapshot"]["handle"])
                self.check_close(target, "close", record["id"])
                return self.bridge.targets.close(target, force)
        return on_ui(close_on_ui)

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
        directory = self.bridge.state / "artifacts" / record["id"]
        completing_open = record.get("_open_pending", False)
        stdout = stderr = None
        if not completing_open:
            directory.mkdir(mode=0o700)
            stdout, stderr = Output(directory / "stdout.txt"), Output(directory / "stderr.txt")
        outcome = {}

        def captured_ui(function):
            def invoke():
                with self.stdout.capture(stdout), self.stderr.capture(stderr):
                    return function()
            return on_ui(invoke)

        try:
            if record["_readiness_error"] is not None:
                raise record["_readiness_error"]
            if bv is not None:
                # The readiness probe may have waited on the UI; validate again
                # immediately before executing or describing the opened view.
                on_ui(lambda: self.bridge.targets.resolve(record["target_snapshot"]["handle"]))
            if completing_open:
                result = on_ui(lambda: self.bridge.targets.describe(bv))
                outcome = dict(self.store_result(result, directory / "result.json"), status="completed")
                return
            spec = record["_spec"]
            scope = dict(bn=self.bn, bv=bv, args=spec.get("args", {}), result=None,
                on_ui=captured_ui, bridge=self.bridge, request=record, __name__="__binja_script__")
            with self.stdout.capture(stdout), self.stderr.capture(stderr):
                undo_id = bv.begin_undo_actions() if bv is not None and record["kind"] not in ("undo", "close") else None
                try:
                    exec(compile(spec["source"], spec["filename"], "exec"), scope, scope)
                finally:
                    # Keep partial edits undoable when a script raises; never roll them back.
                    if undo_id is not None:
                        bv.commit_undo_actions(undo_id)
            if not record.get("_open_pending"):
                value = self.store_result(scope["result"], directory / "result.json")
                outcome = dict(value, status="completed")
        except BaseException as exc:
            with self.lock:
                if record["status"] != "cancelled":
                    outcome = dict(status="failed", error=f"{type(exc).__name__}: {exc}"[-INLINE_BYTES:])
                    if not isinstance(exc, Error):
                        outcome["traceback"] = script_traceback(exc)[-INLINE_BYTES:]
        finally:
            streams = dict(stdout=stdout.finish(), stderr=stderr.finish()) if stdout is not None else {}
            with self.lock:
                record.update(streams)
                if outcome:
                    self.finish(record, **outcome)
                else:
                    # The open script is done. Keep its captured output and
                    # retained view, but release the executor until readiness.
                    record.update(status="queued", phase="preparing")
                    record.pop("_spec", None)
                    self.changed.notify_all()

    def finish(self, record, **outcome):
        # Called under the lock for every terminal transition, including cancel.
        record.update(outcome, finished=time.time())
        for key in ("phase", "_bv", "_spec", "_open_pending", "_readiness_error", "_next_revalidation"):
            record.pop(key, None)
        self.prune()
        self.changed.notify_all()

    def prune(self):
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

    def run(self):
        while True:
            with self.changed:
                self.changed.wait_for(lambda: bool(self.lane_heads()))
            record = self.select()
            if record is None:
                with self.changed:
                    self.changed.wait(timeout=0.1)
                continue
            try:
                self.execute(record)
            except BaseException as exc:
                # Artifact I/O can fail before script execution or during output finalization.
                with self.lock:
                    self.finish(record, status="failed", error=f"Request infrastructure error: {exc}"[-INLINE_BYTES:])
