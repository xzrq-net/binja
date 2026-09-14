#!/usr/bin/env python3
"""Live MVP checks through an installed CLI, from a disposable other workspace.

Usage: python3 tests/smoke.py --binja ./result/bin/binja --sample /path/to/small/ELF
The sample is copied and statically analyzed; it is never executed.
"""
import argparse
import signal
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
    parser.add_argument("--sample", type=Path)
    parser.add_argument("--offline", action="store_true", help="Only help and API lookup; no sample, GUI, or license needed")
    parser.add_argument("--license", type=Path, default=Path.home() / ".binaryninja/license.dat")
    options = parser.parse_args()
    if not options.offline and options.sample is None:
        parser.error("--sample is required unless --offline is used")
    binary = str(options.binja.resolve())
    workspace = Path(tempfile.mkdtemp(prefix="binja-smoke-"))
    state = workspace / ".binja"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    sample_a, sample_b = workspace / "a/sample", workspace / "b/sample"
    if not options.offline:
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

    def payload(record):
        return record["result"] if "result" in record else json.loads(Path(record["result_artifact"]).read_text())

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

        large = cli("api", "members", "BinaryView")
        assert large["total"] == large["total_members"] == len(large["members"]) > 200
        names = [m["name"] for m in large["members"]]
        assert names == sorted(set(names))
        assert "get_functions_containing" in names and "write" in names
        assert all(m["owner"] == large["class"] and "doc" not in m for m in large["members"])
        assert large["unresolved_bases"] == []
        filtered = cli("api", "members", "binaryninja.Function", "--match", "NaMe")
        assert filtered["members"] and all("name" in m["name"].lower() for m in filtered["members"])
        name = next(m for m in filtered["members"] if m["name"] == "name")
        assert name["writable"] is True and name["return_type"] == "str"
        hlil = cli("api", "members", "Function", "--match", "hlil")["members"]
        assert next(m for m in hlil if m["name"] == "hlil")["writable"] is False
        for missing in ("set_user_name", "size", "Function.", "self", "name*"):
            absent = cli("api", "members", "Function", "--match", missing)
            assert absent["total"] == 0 and absent["members"] == [] and absent["unresolved_bases"] == []
        assert "nonempty" in cli("api", "members", "Function", "--match", "  ", code=1)["error"]
        for missing in ("does_not_exist", "binaryninjaui.UIContext", "ctypes.Structure"):
            assert "not in the static index" in cli("api", "members", missing, code=1)["error"]
        ambiguous = cli("api", "members", "CacheImage", code=1)["error"]
        assert "Ambiguous" in ambiguous and "binaryninja.kernelcache.kernelcache.CacheImage" in ambiguous
        assert "binaryninja.sharedcache.sharedcache.CacheImage" in ambiguous
        assert cli("api", "members", "binaryninja.kernelcache.kernelcache.CacheImage")["class"].endswith(".CacheImage")
        assert "not a class" in cli("api", "members", "Function.name", code=1)["error"]

        inherited = cli("api", "members", "HighLevelILBasicBlock")
        member = next(m for m in inherited["members"] if m["name"] == "start")
        assert member["owner"] == "binaryninja.basicblock.BasicBlock" and member["writable"] is False
        assert cli("api", "show", member["symbol"])["signature"] == member["signature"]
        multiple = cli("api", "members", "HighLevelILAdd")
        names = [m["name"] for m in multiple["members"]]
        assert len(names) == len(set(names))
        order = [(multiple["mro"].index(m["owner"]), m["name"]) for m in multiple["members"]]
        assert order == sorted(order)
        assert any(m["owner"] == "binaryninja.commonil.BaseILInstruction" for m in multiple["members"])
        human = subprocess.check_output([binary, "api", "members", "HighLevelILBasicBlock", "--match", "start"],
            cwd=workspace, env=env, text=True)
        assert "[from binaryninja.basicblock.BasicBlock]" in human and "[property, read-only]" in human
        partial = cli("api", "members", "SegmentDescriptorList", "--match", "does_not_exist")
        assert partial["members"] == [] and partial["unresolved_bases"] == ["list"]
        human = subprocess.check_output([binary, "api", "members", "SegmentDescriptorList", "--match", "does_not_exist"],
            cwd=workspace, env=env, text=True)
        assert "No indexed member names match" in human and "Their members are unknown" in human
        enum = cli("api", "members", "binaryninja.enums.SymbolType", "--match", "ImportedFunctionSymbol")["members"]
        assert len(enum) == 1 and enum[0]["value"] == 2
        assert "GENERATION:rUNIQUE_ID" in subprocess.check_output([binary, "py", "--help"], text=True)
        assert cli("status") == {"running": False, "state_dir": str(state)}
        assert not state.exists()
        if options.offline:
            phase(f"PASS — offline API lookup; evidence: {workspace}")
            return

        phase("Failed supervisor returns after the competing-winner grace")
        blocker = state / "bn/plugins/block-start"
        blocker.parent.mkdir(parents=True)
        blocker.write_text("Deliberately prevent supervisor initialization")
        before = time.monotonic()
        failed_start = subprocess.run([binary, "--json", "start", "--license", str(options.license)],
            cwd=workspace, env=env, text=True, capture_output=True, timeout=8)
        latency = time.monotonic() - before
        assert failed_start.returncode == 1, (failed_start.stdout, failed_start.stderr)
        error = json.loads(failed_start.stdout)["error"]
        assert "Session startup exited (exit status: 1)" in error, error
        assert str(state / "logs") in error and "Startup wait timed out" not in error
        assert "Managed plugin directory must be empty" in (state / "logs/supervisor.log").read_text()
        assert latency < 8, latency
        phase(f"Failed supervisor latency: {latency:.3f}s")
        blocker.unlink()
        assert cli("status")["running"] is False

        phase("Private session ownership and target inference")
        phase("Concurrent and late starts share initialization")
        started = True
        starts = [subprocess.Popen([binary, "--json", "start", "--license", str(options.license)],
            cwd=workspace, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(8)]
        deadline = time.monotonic() + 20
        while not (state / "runtime/control.sock").exists():
            assert time.monotonic() < deadline, "Supervisor did not initialize"
            time.sleep(.01)
        assert any(p.poll() is None for p in starts), "Missed initialization window"
        starts += [subprocess.Popen([binary, "--json", "start"], cwd=workspace, env=env,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        sessions = []
        for process in starts:
            stdout, stderr = process.communicate(timeout=90)
            assert process.returncode == 0, (stdout, stderr)
            sessions.append(json.loads(stdout))
        assert len({s["generation"] for s in sessions}) == 1
        assert all(s["running"] for s in sessions)
        assert all(s["reused"] for s in sessions[-2:])
        session = sessions[0]
        assert session["state_dir"] == str(state)
        assert session["version"].split()[0] == symbol["version"]
        assert cli("--state-dir", state, "status")["generation"] == session["generation"]
        assert py("import os; result = os.getcwd()", no_target=True)["result"] == str(workspace)
        assert cli("start")["generation"] == session["generation"]
        assert cli("targets") == []

        phase("Stuck UI status, compositor capture, and modal dismissal")
        ui_blocked, ui_release = workspace / "ui-blocked", workspace / "ui-release"
        blocked_ui = py('''import time
from pathlib import Path
def block():
    Path(args['ready']).touch()
    deadline = time.monotonic() + 15
    while not Path(args['release']).exists() and time.monotonic() < deadline:
        time.sleep(.05)
on_ui(block)
''', no_target=True, no_wait=True, args=json.dumps({"ready": str(ui_blocked), "release": str(ui_release)}))
        try:
            deadline = time.monotonic() + 5
            while not ui_blocked.exists():
                assert time.monotonic() < deadline, "UI did not enter the blocking callback"
                time.sleep(.05)
            before = time.monotonic()
            unknown = cli("status")
            assert time.monotonic() - before < 3
            assert unknown["modal_open"] is None and unknown["targets"] is None
            assert unknown["file_count"] is None and unknown["view_count"] is None
            assert any(r["id"] == blocked_ui["id"] for r in unknown["requests"])
            assert "Modal: unknown" in subprocess.check_output([binary, "status"], cwd=workspace, env=env, text=True, timeout=3)
        finally:
            ui_release.touch()
        assert retrieve(blocked_ui)["status"] == "completed"

        gui_pid = py("import os; result = os.getpid()", no_target=True)["result"]
        modal = py('''from PySide6.QtWidgets import QMessageBox
def modal():
    box = QMessageBox()
    box.setWindowTitle('binja smoke modal')
    box.setText('Dismiss this modal using the CLI.')
    box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
    return box.exec()
result = on_ui(modal)
''', no_target=True, no_wait=True)
        deadline = time.monotonic() + 5
        while cli("status")["modal_open"] is not True:
            assert time.monotonic() < deadline, "Modal did not open"
            time.sleep(.05)
        shot = cli("screenshot")
        png = Path(shot["path"]).read_bytes()
        assert png[:8] == b"\x89PNG\r\n\x1a\n" and png[12:16] == b"IHDR"
        assert shot["width"] == int.from_bytes(png[16:20], "big") > 0
        assert shot["height"] == int.from_bytes(png[20:24], "big") > 0
        assert Path(shot["path"]).parent == state / "artifacts"
        shutil.copy2(shot["path"], workspace / "modal.png")
        assert "outside" in cli("input", "click", shot["width"], shot["height"], code=1)["error"]
        assert "wtype exited" in cli("input", "key", "NotARealKeySym", code=1)["error"]
        assert cli("input", "key", "Tab")["key"] == "Tab"
        # Stop every GUI thread: these commands must depend only on the compositor.
        os.kill(gui_pid, signal.SIGSTOP)
        try:
            before = time.monotonic()
            frozen = cli("status")
            assert time.monotonic() - before < 3
            assert frozen["running"] and frozen["modal_open"] is None and frozen["requests"] is None
            frozen_path = workspace / "frozen modal.png"
            screenshot = subprocess.check_output([binary, "screenshot", frozen_path.name],
                cwd=workspace, env=env, text=True, timeout=5).strip()
            assert screenshot == str(frozen_path)
            assert frozen_path.read_bytes()[:8] == png[:8]
            previous = frozen_path.read_bytes()
            assert "Create screenshot" in cli("screenshot", frozen_path, code=1)["error"]
            assert frozen_path.read_bytes() == previous
            assert cli("input", "key", "Escape")["key"] == "Escape"
        finally:
            os.kill(gui_pid, signal.SIGCONT)
        assert retrieve(modal)["result"] == 4194304  # QMessageBox.Cancel
        assert cli("status")["modal_open"] is False
        assert py("result = 6 * 7", no_target=True)["result"] == 42

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

        phase("Typed listings: native Pseudo C, IL addresses, pagination, and recovery")
        function = py("f = (bv.get_functions_by_name('main') or bv.get_functions_at(bv.entry_point))[0]; "
            "result = dict(name=f.name, start=hex(f.start), arch=f.arch.name)", a)["result"]
        name, start = function["name"], function["start"]
        default = cli("decompile", name, "--target", a)
        assert default["kind"] == "decompile" and payload(default)["page"]["limit"] == 64
        full = payload(cli("decompile", start, "--target", a, "--limit", "10000"))
        assert full["view"] == "pseudo-c" and full["address_kind"] == "anchor"
        assert all(set(row) == {"address", "text"} for row in full["rows"])
        native = payload(py(f"""f = bv.get_function_at({start})
s = bn.DisassemblySettings.default_linear_settings()
s.set_option(bn.DisassemblyOption.ShowAddress, False)
result = [str(line) for line in f.pseudo_c.get_linear_lines(f.hlil.root, s)]
""", a))
        rendered = [row["text"] for row in full["rows"]]
        body_start = rendered.index(native[0])
        assert rendered[body_start:body_start + len(native)] == native
        first = cli("decompile", name, "--target", a, "--limit", "3")
        second = payload(cli("decompile", name, "--target", a, "--offset", "3", "--limit", "3"))
        assert payload(first)["rows"] + second["rows"] == full["rows"][:6]
        assert payload(first)["page"]["next_offset"] == 3 and second["page"]["total"] == len(full["rows"])
        end_page = payload(cli("decompile", start, "--target", a, "--offset", str(len(full["rows"]))))
        assert end_page["rows"] == [] and end_page["page"]["next_offset"] is None
        for identifier in (start, hex(int(start, 16) + 1), name + "+1"):
            assert payload(cli("decompile", identifier, "--target", a))["function"]["start"] == start
        human = subprocess.check_output([binary, "request", first["id"]], cwd=workspace, env=env, text=True)
        assert f"{name} @ {start}  pseudo-c" in human and "continue with --offset 3" in human
        assert '"rows":' not in human and '"function":' not in human
        assert cli("il", start, "--target", a, "--request-id", first["id"]) == cli("request", first["id"])
        recovered = retrieve(cli("il", name, "--target", a, "--no-wait"))
        assert recovered["kind"] == "il" and payload(recovered)["view"] == "mlil"
        for view in ("hlil", "mlil", "llil"):
            for ssa in (False, True):
                flags = ["--ssa"] if ssa else []
                record = payload(cli("il", start, "--target", a, "--view", view, *flags))
                assert record["ssa"] == ssa
                indexes = {row["il_index"]: row["address"] for row in record["rows"] if row["il_index"] is not None}
                assert indexes and all(set(row) == {"address", "text", "il_index"} for row in record["rows"])
                py(f"""f = bv.get_function_at({start})
il = f.{view}{'.ssa_form' if ssa else ''}
for index, address in args.items():
    assert hex(il[int(index)].address) == address, (index, address)
""", a, args=json.dumps(indexes))

        phase("Typed listing spills retain text and JSON")
        py("import binja.execution as execution; execution.INLINE_BYTES = 128", no_target=True)
        try:
            spilled = cli("decompile", name, "--target", a, "--limit", "3")
            assert Path(spilled["stdout"]["artifact"]).read_text().endswith("continue with --offset 3\n")
            assert payload(spilled) == payload(first)
            human = subprocess.check_output([binary, "request", spilled["id"]], cwd=workspace, env=env, text=True)
            assert spilled["stdout"]["artifact"] in human and '"rows":' not in human
        finally:
            py("import binja.execution as execution; execution.INLINE_BYTES = 16384", no_target=True)

        phase("Function and linear disassembly, native hex offsets, and stopping reasons")
        disasm = payload(cli("disasm", start, "--target", a))
        assert all(set(row) == {"address", "text", "bytes"} for row in disasm["rows"])
        instructions = [row for row in disasm["rows"] if row["bytes"]]
        assert instructions
        py("for row in args:\n    raw = bytes.fromhex(row['bytes'])\n    assert bv.read(int(row['address'], 16), len(raw)) == raw",
            a, args=json.dumps(instructions))
        linear = payload(cli("disasm", start, "--target", a, "--count", "5"))
        chunk = payload(cli("disasm", start, "--target", a, "--count", "5", "--limit", "2"))
        rest = payload(cli("disasm", chunk["next_address"], "--target", a, "--count", str(chunk["remaining_count"])))
        assert chunk["rows"] + rest["rows"] == linear["rows"]
        assert linear["remaining_count"] == 0 and linear["stopped_reason"] is None
        by_end = payload(cli("disasm", start, "--target", a, "--end", linear["next_address"]))
        assert by_end["rows"] == linear["rows"] and by_end["next_address"] == linear["next_address"]
        split = next(row for row in instructions if len(bytes.fromhex(row["bytes"])) > 1)
        partial = payload(cli("disasm", split["address"], "--target", a, "--end", hex(int(split["address"], 16) + 1)))
        assert partial["rows"] == [] and partial["stopped_reason"] == "end splits an instruction"
        offset = payload(cli("disasm", name + "+10", "--target", a, "--count", "1"))
        assert offset["start"] == hex(int(start, 16) + 0x10)
        unmapped = payload(cli("disasm", "0xffffffffffff0000", "--target", a, "--count", "1"))
        assert unmapped["stopped_reason"] == "unmapped address"
        assert "Raw" in cli("decompile", start, "--target", raw, code=1)["error"]
        assert "Raw" in cli("il", start, "--target", raw, code=1)["error"]
        raw_offset = py(f"result = bv.get_data_offset_for_address({start})", a)["result"]
        py("bv.arch = bn.Architecture[args]", raw, args=json.dumps(function["arch"]))
        raw_disasm = payload(cli("disasm", hex(raw_offset), "--target", raw, "--count", "5"))
        assert [r["bytes"] for r in raw_disasm["rows"]] == [r["bytes"] for r in linear["rows"]]
        assert "after" in cli("disasm", start, "--target", a, "--end", start, code=1)["error"]

        phase("Ambiguous names/addresses and skipped analysis fail explicitly")
        renamed = py("fs = list(bv.functions)[:2]; result = [(hex(f.start), f.name) for f in fs]; "
            "[setattr(f, 'name', 'binja_ambiguous') for f in fs]", a)["result"]
        for command in ("decompile", "xrefs", "refs", "callers"):
            error = cli(command, "binja_ambiguous", "--target", a, code=1)["error"]
            assert "Ambiguous function" in error and all(address in error for address, _ in renamed)
        error = cli("disasm", "binja_ambiguous+1", "--count", "1", "--target", a, code=1)["error"]
        assert "Ambiguous address" in error and all(address in error for address, _ in renamed)
        py("for address, name in args:\n    bv.get_function_at(int(address, 16)).name = name", a, args=json.dumps(renamed))
        platform = py(f"""f = bv.get_function_at({start})
platform = next(p for p in bn.Platform if p.arch == f.arch and p != f.platform)
bv.create_user_function(f.start, platform)
bv.update_analysis_and_wait()
result = platform.name
""", a)["result"]
        try:
            error = cli("decompile", start, "--target", a, code=1)["error"]
            assert "Ambiguous function" in error and platform in error and function["arch"] in error
        finally:
            py(f"bv.remove_user_function(bv.get_function_at({start}, bn.Platform[args])); bv.update_analysis_and_wait()",
                a, args=json.dumps(platform))
        py(f"bv.get_function_at({start}).analysis_skipped = True; bv.update_analysis_and_wait()", a)
        assert "skipped" in cli("decompile", start, "--target", a, code=1)["error"]
        py(f"bv.get_function_at({start}).analysis_skipped = False; bv.update_analysis_and_wait()", a)
        for arguments in (("il", start, "--view", "invalid"), ("decompile", start, "--limit", "0"),
                ("disasm", start, "--count", "0"), ("disasm", start, "--count", "1", "--end", start),
                ("disasm", start, "--count", "1", "--offset", "1"), ("il", start, "--offset", "-1"),
                ("xrefs", start, "--limit", "0"), ("refs", start, "--offset", "-1"),
                ("callers", start, "--limit", "0")):
            invalid = subprocess.run([binary, *arguments], cwd=workspace, env=env, text=True, capture_output=True)
            assert invalid.returncode == 2 and "Request " not in invalid.stderr

        phase("Reference traversal: native sources, import normalization, and calls versus references")
        data = py("s = next(s for s in bv.get_symbols() if s.type == bn.SymbolType.DataSymbol "
            "and list(bv.get_data_refs(s.address))); result = dict(name=s.full_name, address=hex(s.address))", a)["result"]
        for subject, address in ((name, start), (data["name"], data["address"])):
            inbound = payload(cli("xrefs", subject, "--target", a, "--limit", "10000"))
            native = py("address = int(args, 16); result = dict("
                "code=sorted((hex(r.address), hex(r.function.start)) for r in bv.get_code_refs(address)), "
                "data=sorted(map(hex, bv.get_data_refs(address))))", a, args=json.dumps(address))["result"]
            assert sorted([r["address"], f["start"]] for r in inbound["rows"] if r["kind"] == "code"
                for f in r["functions"]) == native["code"]
            assert sorted(r["address"] for r in inbound["rows"] if r["kind"] == "data") == native["data"]
            assert inbound["counts"] == dict(code_references=len(native["code"]), data_references=len(native["data"]))
            assert inbound["direction"] == "inbound" and inbound["relation"] == "reference"
            assert inbound["addresses"] == [address]

        imports = py("""kinds = {bn.SymbolType.ImportedFunctionSymbol, bn.SymbolType.ImportAddressSymbol, bn.SymbolType.ExternalSymbol}
symbol = next(s for s in bv.get_symbols() if s.type == bn.SymbolType.ImportedFunctionSymbol)
symbols = [s for s in bv.get_symbols_by_name(symbol.full_name) if s.type in kinds]
result = dict(name=symbol.full_name, addresses=sorted({hex(s.address) for s in symbols}),
    stubs=sorted({hex(s.address) for s in symbols if s.type == bn.SymbolType.ImportedFunctionSymbol}))
""", a)["result"]
        recipe = """addresses = {int(a, 16) for a in args['addresses']}
stubs = {int(a, 16) for a in args['stubs']}
calls = set()
for f in bv.functions:
    if f.start in stubs:
        continue
    for site in f.call_sites:
        if addresses.intersection(bv.get_callees(site.address, f, site.arch)):
            calls.add((hex(f.start), f.name, hex(site.address)))
refs = {(r.function.start, r.address) for address in addresses for r in bv.get_code_refs(address)
    if r.function.start not in stubs}
result = dict(calls=sorted(calls), counts=dict(call_sites=len(calls), code_references=len(refs)))
"""
        expected = py(recipe, a, args=json.dumps(imports))["result"]
        baseline = payload(cli("callers", imports["name"], "--target", a, "--limit", "10000"))
        assert baseline["counts"] == expected["counts"]
        assert sorted([r["function"]["start"], r["function"]["name"], r["address"]] for r in baseline["rows"]) == expected["calls"]
        assert baseline["excluded_stubs"] == imports["stubs"]
        assert all(r["function"]["start"] not in imports["stubs"] for r in baseline["rows"])
        for address in imports["addresses"]:
            alias = payload(cli("callers", address, "--target", a, "--limit", "10000"))
            assert alias["addresses"] == baseline["addresses"] and alias["rows"] == baseline["rows"]
            assert alias["counts"] == baseline["counts"]

        # A user reference on a non-call instruction must not become a call site.
        fixture = py("""f = bv.get_function_at(int(args['start'], 16))
destination = int(args['import'], 16)
call_addresses = {site.address for site in f.call_sites}
source = next(address for _, address in f.instructions if address not in call_addresses
    and destination not in bv.get_code_refs_from(address, f))
f.add_user_code_ref(source, destination)
bv.add_user_data_ref(f.start + 1, int(args['data'], 16))
result = dict(source=hex(source), destination=hex(destination), data_source=hex(f.start + 1))
""", a, args=json.dumps({"start": start, "import": imports["stubs"][0], "data": data["address"]}))["result"]
        try:
            changed = payload(cli("callers", imports["name"], "--target", a, "--limit", "10000"))
            assert changed["rows"] == baseline["rows"]
            assert changed["counts"]["code_references"] == baseline["counts"]["code_references"] + 1
            assert changed["counts"]["call_sites"] == baseline["counts"]["call_sites"]
            inbound = payload(cli("xrefs", imports["stubs"][0], "--target", a, "--limit", "10000"))
            assert any(r["kind"] == "code" and r["address"] == fixture["source"] for r in inbound["rows"])
            inbound = payload(cli("xrefs", data["name"], "--target", a, "--limit", "10000"))
            assert any(r["kind"] == "data" and r["address"] == fixture["data_source"]
                and any(f["start"] == start for f in r["functions"]) for r in inbound["rows"])
            # Independently recover outbound edges by range queries and inverse lookup.
            native = py("""f = bv.get_function_at(int(args, 16))
blocks = list(f.basic_blocks)
inside = lambda address: any(b.start <= address < b.end for b in blocks)
code_targets = {dest for b in blocks for dest in bv.get_code_refs_from(b.start, f, b.arch, b.end - b.start)}
data_targets = {dest for b in blocks for dest in bv.get_data_refs_from(b.start, b.end - b.start)}
edges = {('code', hex(r.address), hex(dest)) for dest in code_targets for r in bv.get_code_refs(dest)
    if r.function == f and inside(r.address)}
edges.update(('data', hex(source), hex(dest)) for dest in data_targets for source in bv.get_data_refs(dest) if inside(source))
result = sorted(edges)
""", a, args=json.dumps(start))["result"]
            outbound = payload(cli("refs", name, "--target", a, "--limit", "10000"))
            assert outbound["direction"] == "outbound" and outbound["relation"] == "reference"
            assert sorted([r["kind"], r["address"], r["to"]] for r in outbound["rows"]) == native
            assert ["data", fixture["data_source"], data["address"]] in native
            interior = payload(cli("xrefs", name + "+1", "--target", a))
            assert interior["addresses"] == [fixture["data_source"]]  # Exact address, not function start.
            for command, subject in (("xrefs", data["name"]), ("refs", name), ("callers", imports["name"])):
                whole = payload(cli(command, subject, "--target", a, "--limit", "10000"))
                first = cli(command, subject, "--target", a, "--limit", "1")
                tail = payload(cli(command, subject, "--target", a, "--offset", "1", "--limit", "10000"))
                assert payload(first)["rows"] + tail["rows"] == whole["rows"]
                assert payload(first)["counts"] == whole["counts"] == tail["counts"]
                assert first["kind"] == command and payload(first)["page"]["total"] == len(whole["rows"])
                human = subprocess.check_output([binary, "request", first["id"]], cwd=workspace, env=env, text=True)
                assert command in human and '"rows":' not in human
                assert whole["direction"] in human and "code" in human and "reference" in human
                assert ("call from" if command == "callers" else "data references") in human
        finally:
            py("f = bv.get_function_at(int(args['start'], 16)); "
                "f.remove_user_code_ref(int(args['source'], 16), int(args['destination'], 16)); "
                "bv.remove_user_data_ref(int(args['data_source'], 16), int(args['data'], 16))",
                a, args=json.dumps(fixture | dict(start=start, data=data["address"])))
        for command in ("xrefs", "callers"):
            empty = retrieve(cli(command, "0xffffffffffff0000", "--target", a, "--no-wait"))
            assert empty["kind"] == command and payload(empty)["rows"] == []
            assert payload(empty)["page"]["next_offset"] is None
            assert "Zero references is not proof of no callers" in empty["stdout"]["text"]

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
        phase("Force stop empties owned groups, including SIGTERM-resistant descendants")
        survivor_ready = workspace / "survivor-ready"
        shell = shutil.which("bash")
        survivor = py(f"""import subprocess, os
p = subprocess.Popen([{shell!r}, "-c", "trap '' TERM; echo ready > " + {str(survivor_ready)!r} + "; while :; do sleep 1; done"])
result = dict(pid=p.pid, group=os.getpgid(p.pid))
""", final_view)["result"]
        deadline = time.monotonic() + 5
        while not survivor_ready.exists():
            assert time.monotonic() < deadline
            time.sleep(.01)
        os.kill(survivor["pid"], signal.SIGTERM)
        os.kill(survivor["pid"], 0)  # It really resists TERM before shutdown.
        cli("stop", "--force")
        started = False
        try:
            os.killpg(survivor["group"], 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError(f"Owned group survived stop: {survivor}")
        assert not list((state / "artifacts").iterdir())
        assert not (state / "runtime/rpc.sock").exists()
        phase("Supervisor SIGKILL also kills its compositor and GUI launcher")
        cli("start")
        started = True
        # Test-only discovery through /proc; production never acts on PID metadata.
        supervisors = []
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                argv = (proc / "cmdline").read_bytes().split(b"\0")
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            if b"__supervisor" in argv and str(state).encode() in argv:
                supervisors.append(int(proc.name))
        assert len(supervisors) == 1, supervisors
        supervisor = supervisors[0]
        children = list(map(int, Path(f"/proc/{supervisor}/task/{supervisor}/children").read_text().split()))
        assert len(children) == 2, children
        os.kill(supervisor, signal.SIGKILL)
        deadline = time.monotonic() + 10
        while any(Path(f"/proc/{pid}").exists() for pid in children):
            assert time.monotonic() < deadline, f"Supervisor children survived: {children}"
            time.sleep(.05)
        assert cli("status")["running"] is False
        cli("start")
        cli("stop")
        started = False
        phase(f"PASS — installed MVP workflow and failure checks; evidence: {workspace}")
    finally:
        if started:
            subprocess.run([binary, "stop", "--force"], cwd=workspace, env=env, capture_output=True, timeout=30)


if __name__ == "__main__":
    main()
