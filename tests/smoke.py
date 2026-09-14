#!/usr/bin/env python3
"""Live MVP checks through an installed CLI, from a disposable other workspace.

Usage: python3 tests/smoke.py --binja ./result/bin/binja --sample /path/to/small/ELF
The sample is copied and statically analyzed; it is never executed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binja", required=True, type=Path)
    parser.add_argument("--sample", required=True, type=Path)
    parser.add_argument("--license", type=Path, default=Path.home() / ".binaryninja/license.dat")
    options = parser.parse_args()
    binary = str(options.binja.resolve())
    workspace = Path(tempfile.mkdtemp(prefix="binja-smoke-"))
    state = workspace / ".binja"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    sample_a, sample_b = workspace / "a/sample", workspace / "b/sample"
    for sample in (sample_a, sample_b):
        sample.parent.mkdir()
        shutil.copy2(options.sample, sample)
    original_hash = hashlib.sha256(sample_a.read_bytes()).hexdigest()

    def cli(*args, code=0, stdin=None, receipts=None):
        completed = subprocess.run([binary, "--json", *map(str, args)], cwd=workspace,
            env=env, input=stdin, text=True, capture_output=True, timeout=90)
        assert completed.returncode == code, (args, completed.returncode, completed.stdout, completed.stderr)
        if receipts is not None:
            receipts.extend(json.loads(line) for line in completed.stderr.splitlines())
        return json.loads(completed.stdout)

    def py(source, target=None, code=0, **flags):
        args = ["py", "-c", source]
        if target:
            args += ["--target", target]
        for key, value in flags.items():
            args.append("--" + key.replace("_", "-"))
            if value is not True:
                args.append(str(value))
        return cli(*args, code=code)

    def retrieve(record):
        return cli("request", record["id"], "--wait", "20")

    def phase(message):
        print(message, flush=True)

    started = False
    try:
        phase("Offline help and matching API lookup")
        help_output = subprocess.check_output([binary, "--help"], cwd=workspace, env=env, text=True)
        assert "skill" in help_output
        assert "binja api" in subprocess.check_output([binary, "skill"], cwd=workspace, env=env, text=True)
        symbol = cli("api", "show", "BinaryView.get_functions_containing")
        assert symbol["version"] == cli("api", "paths")["version"]
        assert Path(symbol["source"]).is_file()
        assert cli("api", "search", "call site")["total"] > 0
        assert "No static" in cli("api", "show", "does_not_exist", code=1)["error"]
        assert "Ambiguous" in cli("api", "show", "name", code=1)["error"]
        assert not state.exists()

        phase("Private session ownership and target inference")
        session = cli("start", "--license", options.license)
        started = True
        assert session["state_dir"] == str(state)
        assert session["version"].split()[0] == symbol["version"]
        assert cli("--state-dir", state, "status")["generation"] == session["generation"]
        assert py("import os; result = os.getcwd()", no_target=True)["result"] == str(workspace)
        assert cli("start")["generation"] == session["generation"]
        assert cli("targets") == []
        assert "No live target" in py("result = bv", code=1)["error"]
        opened_a = cli("open", sample_a)
        assert opened_a["target_snapshot_stage"] == "open"
        a = opened_a["result"]["handle"]
        assert opened_a["result"]["analysis"] == "IdleState"
        assert py("result = bv.file.filename")["result"] == str(sample_a)
        b = cli("open", sample_b)["result"]["handle"]
        assert "ambiguous" in py("result = 0", code=1)["error"]
        assert "ambiguous" in py("result = 0", "sample", code=1)["error"]
        assert py("result = bv.file.filename", "a/sample")["result"] == str(sample_a)
        raw = next(t["handle"] for t in cli("targets") if t["path"] == str(sample_a) and t["view_type"] == "Raw")
        assert py("result = bv.view_type", raw)["result"] == "Raw"
        focused = py("result = bv.file.filename", "active")
        assert focused["result"] == str(sample_b)
        focus_switch = """import binaryninjaui as ui
def switch():
    context = ui.UIContext.activeContext()
    for tab in context.getTabs():
        frame = context.getViewFrameForTab(tab)
        if frame and frame.getCurrentBinaryView().file.filename == args['path']:
            context.activateTab(tab)
on_ui(switch)
result = bv.file.filename
"""
        assert py(focus_switch, b, args=json.dumps({"path": str(sample_a)}))["result"] == str(sample_b)
        assert py("result = bv.file.filename", "active")["result"] == str(sample_a)

        phase("Queue receipts, pending cap, cancellation, expiry, and listing")
        release = workspace / "release-worker"
        slow = py("import time\nfrom pathlib import Path\ndeadline = time.monotonic() + 60\nwhile not Path(args['release']).exists() and time.monotonic() < deadline: time.sleep(.05)\nresult = bv.file.filename",
            a, no_wait=True, args=json.dumps({"release": str(release)}))
        expired = cli("request", slow["id"], "--wait", ".2", code=2)
        assert expired["status"] == "running" and expired["elapsed_seconds"] > 0
        assert expired["client_wait_expired"] is True
        assert str(state) in expired["recovery_command"] and slow["id"] in expired["recovery_command"]
        receipts = []
        queued = cli("py", "-c", "result = bv.file.filename", "--target", a, "--wait", ".01", code=2, receipts=receipts)
        accepted = receipts[-1]
        assert accepted["event"] == "accepted" and accepted["status"] == "queued"
        assert accepted["queue_position"] == 1 and accepted["waits_behind"] == slow["id"]
        assert accepted["target_snapshot"]["handle"] == a
        assert queued["client_wait_expired"] and queued["recovery_command"]
        human_id = session["generation"] + ":rhumanqueue"
        human = subprocess.run([binary, "py", "-c", "result = bv.file.filename", "--target", b,
            "--request-id", human_id, "--wait", ".01"], cwd=workspace, env=env,
            text=True, capture_output=True, timeout=10)
        assert human.returncode == 2
        assert "queue position: 2" in human.stderr and queued["id"] in human.stderr
        assert b in human.stderr and "target snapshot (submission)" in human.stderr
        assert "Client wait expired" in human.stdout and "Retrieve with:" in human.stdout
        extras = [py("result = bv.file.filename", a, no_wait=True) for _ in range(4)]
        extras.append(py("bv.set_comment_at(bv.entry_point, 'must not run')", a, no_wait=True))
        pending = [slow, queued, {"id": human_id}, *extras]
        rejected_id = session["generation"] + ":rcaprejected"
        rejection = py("raise AssertionError('must not execute')", a, no_wait=True,
            request_id=rejected_id, code=1)["error"]
        assert "not accepted and will not execute" in rejection
        assert slow["id"] in rejection and "7 queued" in rejection and "Safe to resubmit" in rejection
        duplicate = py("raise AssertionError('must not replay')", a, no_wait=True, request_id=slow["id"])
        assert duplicate["id"] == slow["id"] and duplicate["status"] == "running"
        human_rejection = subprocess.run([binary, "py", "-c", "result = 0", "--target", a, "--no-wait"],
            cwd=workspace, env=env, text=True, capture_output=True, timeout=10)
        assert human_rejection.returncode == 1
        assert "not accepted and will not execute" in human_rejection.stderr
        assert slow["id"] in human_rejection.stderr and "7 queued" in human_rejection.stderr
        listing = cli("requests")
        assert [r["id"] for r in listing[:8]] == [r["id"] for r in pending]
        assert len(listing) == 13
        assert all(r["status"] in ("completed", "failed", "cancelled") for r in listing[8:])
        assert [r["finished"] for r in listing[8:]] == sorted((r["finished"] for r in listing[8:]), reverse=True)
        human_listing = subprocess.check_output([binary, "requests"], cwd=workspace, env=env, text=True)
        assert human_listing.splitlines()[0].startswith(slow["id"])
        assert "phase: executing" in human_listing and "elapsed:" in human_listing and a in human_listing
        full = cli("requests", "--all")
        assert len(full) > len(listing) and rejected_id not in {r["id"] for r in full}
        assert all("phase" in r and "elapsed_seconds" in r and "target_snapshot" in r for r in listing)
        assert "Outstanding" in cli("stop", code=1)["error"]
        assert "Only queued" in cli("cancel", slow["id"], code=1)["error"]
        assert cli("cancel", extras[-1]["id"], code=1)["status"] == "cancelled"
        retry = py("result = 'accepted after cancellation'", a, no_wait=True, request_id=rejected_id)
        assert retry["queue_position"] == 7 and retry["waits_behind"] == extras[-2]["id"]
        assert cli("status")["requests"]
        release.touch()
        assert retrieve(slow)["result"] == str(sample_a)
        assert retrieve(queued)["result"] == str(sample_a)
        assert cli("request", human_id, "--wait", "20")["result"] == str(sample_b)
        assert retrieve(retry)["result"] == "accepted after cancellation"
        assert len(cli("requests")) == 5

        phase("Analysis readiness at execution time and explicit override")
        hold = py("import time; time.sleep(.5); bv.set_analysis_hold(True)", a, no_wait=True)
        gated = py("bv.set_comment_at(bv.entry_point, 'must not run')", a, no_wait=True)
        retrieve(hold)
        refused = cli("request", gated["id"], "--wait", "5", code=1)
        assert "hold" in refused["error"]
        assert py("result = bv.get_comment_at(bv.entry_point)", a, allow_incomplete=True)["result"] == ""
        py("bv.set_analysis_hold(False); bv.update_analysis_and_wait()", a, allow_incomplete=True)

        phase("Fresh scopes, Python errors, output isolation, and bounded artifacts")
        py("temporary_variable = 1", a)
        assert "NameError" in py("result = temporary_variable", a, code=1)["error"]
        script = workspace / "trace_probe.py"
        script.write_text("print('before error')\nraise ValueError('trace marker')\n")
        failed = cli("py", "--target", a, "--file", script, code=1)
        assert str(script) in failed["traceback"] and "line 2" in failed["traceback"]
        assert failed["stdout"]["text"] == "before error\n"
        output = py("import threading; t = threading.Thread(target=lambda: print('unrelated')); t.start(); t.join(); print('owned'); on_ui(lambda: print('ui-owned')); result = 2**64-1", a)
        assert output["stdout"]["text"] == "owned\nui-owned\n"
        assert output["result"] == 2**64 - 1
        large = py("print('x' * 1100000); result = list(range(10000))", a)
        assert large["stdout"]["truncated"] and Path(large["stdout"]["artifact"]).stat().st_size == 1024 * 1024
        assert len(json.loads(Path(large["result_artifact"]).read_text())) == 10000
        assert "not JSON serializable" in py("result = bv", a, code=1)["error"]

        phase("Disconnect before acknowledgement, recovery, and deduplication")
        request_id = session["generation"] + ":rdisconnect"
        source = "import time; time.sleep(.3); bv.set_comment_at(bv.entry_point, bv.get_comment_at(bv.entry_point) + 'once'); result = bv.get_comment_at(bv.entry_point)"
        spec = dict(id=request_id, source=source, filename="<disconnect probe>", args={}, target=a, no_target=False, allow_incomplete=False)
        wire = dict(protocol=2, generation=session["generation"], op="submit", spec=spec)
        with socket.socket(socket.AF_UNIX) as connection:
            connection.connect(str(state / "runtime/rpc.sock"))
            connection.sendall(json.dumps(wire).encode() + b"\n")
        time.sleep(.1)
        assert cli("request", request_id, "--wait", "5")["result"] == "once"
        with socket.socket(socket.AF_UNIX) as connection:
            connection.connect(str(state / "runtime/rpc.sock"))
            connection.sendall(json.dumps(wire).encode() + b"\n")
            assert json.loads(connection.makefile("rb").readline())["data"]["result"] == "once"
        assert py("result = bv.get_comment_at(bv.entry_point)", a)["result"] == "once"
        assert py("result = 0", a, request_id=request_id) == cli("request", request_id)

        phase("Database save failures, orderly shutdown guard, and restart persistence")
        assert "Unsaved" in cli("stop", code=1)["error"]
        failed_save = cli("save", workspace / "missing/failed.bndb", "--target", a, code=1)
        assert failed_save["status"] == "failed"
        assert "Unsaved" in cli("stop", code=1)["error"]
        database = workspace / "analysis.bndb"
        saved = retrieve(cli("save", database, "--target", a, "--no-wait"))
        assert saved["target_snapshot"]["path"] == str(sample_a)
        assert saved["target_snapshot_stage"] == "submission"
        assert saved["result"]["saved"]["path"] == str(database)
        assert database.is_file()
        py("bv.set_comment_at(bv.entry_point, 'persisted annotation')", a)
        cli("save", database, "--target", a)
        cli("stop")
        started = False
        assert not (state / "runtime/rpc.sock").exists()
        restarted = cli("start", "--license", options.license)
        started = True
        assert restarted["generation"] != session["generation"]
        reopened = cli("open", database)["result"]["handle"]
        assert py("result = bv.get_comment_at(bv.entry_point)", reopened)["result"] == "persisted annotation"
        assert "No live target" in py("result = 0", a, code=1)["error"]
        assert "old generation" in cli("request", request_id, code=1)["error"]
        for sample in (sample_a, sample_b):
            assert hashlib.sha256(sample.read_bytes()).hexdigest() == original_hash
        assert (state.stat().st_mode & 0o777) == 0o700
        assert ((state / "runtime/rpc.sock").stat().st_mode & 0o777) == 0o600

        phase("GUI close/reopen invalidation and output pruning without replay")
        py("import binaryninjaui as ui\ndef close():\n    for context in ui.UIContext.allContexts():\n        for tab in list(context.getTabs()):\n            context.closeTab(tab)\non_ui(close)", no_target=True)
        assert cli("targets") == []
        reopened_again = cli("open", database)["result"]["handle"]
        assert reopened_again != reopened
        assert "No live target" in py("result = 0", reopened, code=1)["error"]
        runtime = py("import os; result = {'updates': bn.update.are_auto_updates_enabled(), 'qt': os.environ['QT_QPA_PLATFORM'], 'user_site': __import__('site').ENABLE_USER_SITE}", reopened_again)["result"]
        assert runtime == {"updates": False, "qt": "wayland", "user_site": False}
        # Use a smaller result limit to exercise pruning quickly.
        py("import binja.execution as execution; execution.KEEP_RESULTS = 2", no_target=True)
        old = py("import sys; print('old output'); print('old error output', file=sys.stderr); result = 123", reopened_again)
        old_failed = py("raise ValueError('retained error')", reopened_again, code=1)
        old_large = py("print('x' * 20000); result = list(range(10000))", reopened_again)
        recent = [py("result = 456", reopened_again), py("result = 789", reopened_again)]
        for record, code in ((old, 0), (old_failed, 1), (old_large, 0)):
            metadata = {k: v for k, v in record.items()
                if k not in ("stdout", "stderr", "result", "result_artifact", "result_bytes")}
            metadata["output_pruned"] = True
            assert cli("request", record["id"], "--wait", "5", code=code) == metadata
            assert not (state / "artifacts" / record["id"]).exists()
            assert py("raise AssertionError('must not replay')", reopened, request_id=record["id"], code=code) == metadata
        for record in recent:
            assert cli("request", record["id"]) == record
        assert {path.name for path in (state / "artifacts").iterdir()} == {r["id"] for r in recent}
        retained_old = cli("request", old["id"])
        for command, path in (("open", sample_a), ("save", database)):
            for record, expected in ((old, "Output pruned."), (recent[-1], "789")):
                rendered = subprocess.check_output([binary, command, str(path), "--request-id", record["id"]],
                    cwd=workspace, env=env, text=True, stderr=subprocess.PIPE, timeout=90)
                assert record["id"] + " completed" in rendered and expected in rendered

        phase("Saving after a long request history")
        py("bv.set_comment_at(bv.entry_point, 'saved after long request history')", reopened_again)
        # Seed old metadata instead of issuing thousands of RPC calls.
        py("""history = {}
for i in range(4096):
    request_id = f"{bridge.generation}:rhistory{i}"
    history[request_id] = dict(id=request_id, status="completed", target_snapshot=None, target_snapshot_stage="submission",
        submitted=0, started=0, finished=0, output_pruned=True)
with bridge.execution.lock:
    bridge.execution.records.update(history)
""", no_target=True)
        cli("save", database, "--target", reopened_again)
        assert py("result = 0", reopened_again, request_id=old["id"]) == retained_old
        assert cli("request", restarted["generation"] + ":rhistory4095")["status"] == "completed"

        phase("Live ownership verification rejects stale metadata")
        metadata_path = state / "runtime/instance.json"
        metadata = metadata_path.read_text()
        changed = json.loads(metadata)
        changed["generation"] = "000000000000"
        metadata_path.write_text(json.dumps(changed))
        try:
            assert "mismatch" in cli("stop", "--force", code=1)["error"]
        finally:
            metadata_path.write_text(metadata)
        assert cli("status")["generation"] == restarted["generation"]
        cli("stop")
        started = False

        cli("start", "--license", options.license)
        started = True
        final_view = cli("open", database)["result"]["handle"]
        assert py("result = bv.get_comment_at(bv.entry_point)", final_view)["result"] == "saved after long request history"
        cli("stop")
        started = False
        phase(f"PASS — installed MVP workflow and failure checks; evidence: {workspace}")
    finally:
        if started:
            subprocess.run([binary, "stop", "--force"], cwd=workspace, env=env, capture_output=True, timeout=30)


if __name__ == "__main__":
    main()
