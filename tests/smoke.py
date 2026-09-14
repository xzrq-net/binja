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


def send_wire(connection, value):
    data = json.dumps(value).encode()
    for offset in range(0, len(data), 32768):
        connection.send(b'\x01' + data[offset:offset+32768])
    connection.send(b'\x00')

def receive_wire(connection):
    data = bytearray()
    while True:
        packet, _, flags, _ = connection.recvmsg(32769)
        assert not flags & socket.MSG_TRUNC and packet
        if packet == b'\x00':
            return json.loads(data)
        assert packet[0] == 1
        data.extend(packet[1:])

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
        assert cli("api", "show", "Function.name")["writable"] is True
        assert cli("api", "show", "Function.hlil")["writable"] is False
        members = cli("api", "show", "binaryninja.enums.SymbolType")["members"]
        assert any(m["name"] == "ImportedFunctionSymbol" and m["value"] == 2 for m in members)
        human_api = subprocess.check_output([binary, "api", "show", "Function.name"], cwd=workspace, env=env, text=True)
        assert "[property, writable]" in human_api and "function.py:" in human_api
        assert "Docs:" not in human_api and "Binary Ninja" not in human_api
        search = subprocess.check_output([binary, "api", "search", "function", "--limit", "1"], cwd=workspace, env=env, text=True)
        assert "1 of " in search and "--limit" in search
        assert "GENERATION:rUNIQUE_ID" in subprocess.check_output([binary, "py", "--help"], text=True)
        assert cli("status") == {"running": False, "state_dir": str(state)}
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
        one_file = cli("status")
        assert one_file["file_count"] == 1 and one_file["view_count"] >= 2
        status_text = subprocess.check_output([binary, "status"], cwd=workspace, env=env, text=True)
        assert f"1 file ({one_file['view_count']} views)" in status_text
        b = cli("open", sample_b)["result"]["handle"]
        assert cli("status")["file_count"] == 2
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
        assert accepted["existing"] is False
        assert accepted["queue_position"] == 1 and accepted["waits_behind"] == slow["id"]
        assert accepted["target_snapshot"]["handle"] == a
        assert queued["client_wait_expired"] and queued["recovery_command"]
        human_id = session["generation"] + ":rhumanqueue"
        human = subprocess.run([binary, "py", "-c", "result = bv.file.filename", "--target", b,
            "--request-id", human_id, "--wait", ".01"], cwd=workspace, env=env,
            text=True, capture_output=True, timeout=10)
        assert human.returncode == 2
        assert "queued #2" in human.stderr and queued["id"] in human.stderr
        assert b in human.stderr and "target snapshot" in human.stderr
        assert "Client wait expired" in human.stdout and "Retrieve with:" in human.stdout
        extras = [py("result = bv.file.filename", a, no_wait=True) for _ in range(4)]
        extras.append(py("bv.set_comment_at(bv.entry_point, 'must not run')", a, no_wait=True))
        pending = [slow, queued, {"id": human_id}, *extras]
        rejected_id = session["generation"] + ":rcaprejected"
        rejection = py("raise AssertionError('must not execute')", a, no_wait=True,
            request_id=rejected_id, code=1)["error"]
        assert "not accepted and will not execute" in rejection
        assert slow["id"] in rejection and "7 queued" in rejection and "Safe to resubmit" in rejection
        duplicate_receipts = []
        duplicate = cli("py", "-c", "raise AssertionError('must not replay')", "--target", a,
            "--no-wait", "--request-id", slow["id"], receipts=duplicate_receipts)
        assert duplicate_receipts[-1]["event"] == "accepted" and duplicate_receipts[-1]["existing"] is True
        assert duplicate["id"] == slow["id"] and duplicate["status"] == "running"
        human_rejection = subprocess.run([binary, "py", "-c", "result = 0", "--target", a, "--no-wait"],
            cwd=workspace, env=env, text=True, capture_output=True, timeout=10)
        assert human_rejection.returncode == 1
        assert "not accepted and will not execute" in human_rejection.stderr
        assert slow["id"] in human_rejection.stderr and "7 queued" in human_rejection.stderr
        envelope = cli("requests")
        listing = envelope["requests"]
        assert envelope["finished_shown"] == 5 and envelope["finished_total"] >= 5
        assert envelope["rejected_total"] == 2
        assert rejected_id in {r["id"] for r in envelope["rejections"]}
        assert [r["id"] for r in listing[:8]] == [r["id"] for r in pending]
        assert len(listing) == 13
        assert all(r["status"] in ("completed", "failed", "cancelled") for r in listing[8:])
        assert [r["finished"] for r in listing[8:]] == sorted((r["finished"] for r in listing[8:]), reverse=True)
        human_listing = subprocess.check_output([binary, "requests"], cwd=workspace, env=env, text=True)
        assert human_listing.splitlines()[0].startswith(slow["id"])
        assert "2 cap-rejected attempts" in human_listing and rejected_id not in human_listing
        human_full = subprocess.check_output([binary, "requests", "--all"], cwd=workspace, env=env, text=True)
        assert rejected_id in human_full and "not accepted" in human_full
        assert "executing " in human_listing and "waiting " in human_listing and a in human_listing
        full_envelope = cli("requests", "--all")
        full = full_envelope["requests"]
        assert full_envelope["finished_shown"] == full_envelope["finished_total"]
        assert len(full) > len(listing) and rejected_id not in {r["id"] for r in full}
        assert all(all(k in r for k in ("phase", "elapsed_seconds", "target_snapshot", "kind", "filename", "output_pruned", "queue_wait_seconds", "execution_seconds")) for r in listing)
        assert "Outstanding" in cli("stop", code=1)["error"]
        assert "Only queued" in cli("cancel", slow["id"], code=1)["error"]
        cancelled = cli("cancel", extras[-1]["id"])
        assert cancelled["status"] == "cancelled" and cancelled["execution_seconds"] is None
        assert cli("request", cancelled["id"], code=1)["status"] == "cancelled"
        retry = py("result = 'accepted after cancellation'", a, no_wait=True, request_id=rejected_id)
        assert retry["queue_position"] == 7 and retry["waits_behind"] == extras[-2]["id"]
        assert cli("status")["requests"]
        release.touch()
        assert retrieve(slow)["result"] == str(sample_a)
        assert retrieve(queued)["result"] == str(sample_a)
        assert cli("request", human_id, "--wait", "20")["result"] == str(sample_b)
        assert retrieve(retry)["result"] == "accepted after cancellation"
        assert len(cli("requests")["requests"]) == 5

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
        assert failed["traceback"].splitlines()[1].startswith(f'  File "{script}", line 2')
        assert "exec(compile(" not in failed["traceback"]
        output = py("import threading; t = threading.Thread(target=lambda: print('unrelated')); t.start(); t.join(); print('owned'); on_ui(lambda: print('ui-owned')); result = 2**64-1", a)
        assert output["stdout"]["text"] == "owned\nui-owned\n"
        assert output["result"] == 2**64 - 1
        assert py("result = 2**100", a)["result"] == 2**100
        human = subprocess.run([binary, "py", "--target", a, "-c", "result=42"], cwd=workspace, env=env, text=True, capture_output=True, check=True)
        assert len(human.stderr.splitlines()) == 1 and human.stderr.startswith("Request ")
        assert "Completed" in human.stdout and "42" in human.stdout
        verbose_submit = subprocess.run([binary, "py", "--target", a, "-c", "result=42", "--verbose"], cwd=workspace, env=env, text=True, capture_output=True, check=True)
        assert len(verbose_submit.stderr.splitlines()) == 1
        assert "Record:" in verbose_submit.stdout
        verbose = subprocess.check_output([binary, "request", output["id"], "--verbose"], cwd=workspace, env=env, text=True)
        full_record = json.loads(verbose.split("Record:\n", 1)[1])
        assert full_record == cli("request", output["id"])
        large = py("print('x' * 1100000); result = list(range(10000))", a)
        assert large["stdout"]["truncated"] and Path(large["stdout"]["artifact"]).stat().st_size == 1024 * 1024
        assert len(json.loads(Path(large["result_artifact"]).read_text())) == 10000
        assert "not JSON serializable" in py("result = bv", a, code=1)["error"]
        large_script = workspace / "large_script.py"
        large_script.write_text("# padding\n" * 100000 + "result=42\n")
        assert cli("py", "--target", a, "--file", large_script)["result"] == 42
        assert cli("py", "--target", a, stdin=large_script.read_text())["result"] == 42
        artifact_human = subprocess.check_output([binary, "request", large["id"]], cwd=workspace, env=env, text=True)
        assert large["stdout"]["artifact"] in artifact_human and "1048576 bytes" in artifact_human
        assert "x" * 100 not in artifact_human and "truncated" in artifact_human

        phase("Disconnect before acknowledgement, recovery, and deduplication")
        request_id = session["generation"] + ":rdisconnect"
        source = "import time; time.sleep(.3); bv.set_comment_at(bv.entry_point, bv.get_comment_at(bv.entry_point) + 'once'); result = bv.get_comment_at(bv.entry_point)"
        spec = dict(id=request_id, source=source, filename="<disconnect probe>", args={}, target=a, no_target=False, allow_incomplete=False)
        wire = dict(protocol=3, generation=session["generation"], op="submit", spec=spec)
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as connection:
            connection.connect(str(state / "runtime/rpc.sock"))
            send_wire(connection, wire)
        time.sleep(.1)
        assert cli("request", request_id, "--wait", "5")["result"] == "once"
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as connection:
            connection.connect(str(state / "runtime/rpc.sock"))
            send_wire(connection, wire)
            assert receive_wire(connection)["data"]["result"] == "once"
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
        assert not list((state / "artifacts").iterdir())
        stopped = cli("status")
        assert stopped == {"running": False, "state_dir": str(state)}
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
            metadata = json.loads(json.dumps(record))
            metadata["output_pruned"] = True
            directory = state / "artifacts" / record["id"]
            if "result" in metadata:
                metadata.pop("result")
                metadata["result_artifact"] = str(directory / "result.json")
            for stream in ("stdout", "stderr"):
                if stream in metadata:
                    metadata[stream].pop("text", None)
                    metadata[stream]["artifact"] = str(directory / (stream + ".txt"))
            assert cli("request", record["id"], "--wait", "5", code=code) == metadata
            assert directory.is_dir()
            for stream in ("stdout", "stderr"):
                assert Path(metadata[stream]["artifact"]).is_file()
            if "result_artifact" in metadata:
                expected = record.get("result")
                retained = json.loads(Path(metadata["result_artifact"]).read_text())
                if "result" in record:
                    assert retained == expected
                else:
                    assert retained == list(range(10000))
            assert py("raise AssertionError('must not replay')", reopened, request_id=record["id"], code=code) == metadata
        for record in recent:
            assert cli("request", record["id"]) == record
        assert {r["id"] for r in (old, old_failed, old_large, *recent)} <= {path.name for path in (state / "artifacts").iterdir()}
        retained_old = cli("request", old["id"])
        for command, path in (("open", sample_a), ("save", database)):
            for record, expected in ((old, "Inline output pruned"), (recent[-1], "789")):
                rendered = subprocess.check_output([binary, command, str(path), "--request-id", record["id"]],
                    cwd=workspace, env=env, text=True, stderr=subprocess.PIPE, timeout=90)
                assert "Completed" in rendered and expected in rendered
                assert "Opened " not in rendered and "Saved " not in rendered

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
        exported = cli("requests", "--all")
        assert len(exported["requests"]) >= 4096
        assert exported["finished_total"] == exported["finished_shown"]

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
