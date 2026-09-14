#!/usr/bin/env python3
"""Live startup deadlines and recovery through an installed CLI (about 3 minutes).

Usage: python3 tests/startup.py --binja ./result/bin/binja
Requires a Personal license. A copied plugin shows a Qt modal before starting
the receiver; the packaged plugin and runtime are never modified.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time


MODAL = '''
_receiver_start = start

def start():
    def modal():
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox()
        box.setWindowTitle("binja startup test")
        box.setText("Receiver initialization is blocked until this dialog closes.")
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        state = Path(os.environ["BINJA_STATE_DIR"])
        (state / "modal.json").write_text(__import__("json").dumps(dict(pid=os.getpid())))
        box.exec()
    on_ui(modal)
    _receiver_start()
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binja", type=Path, required=True)
    parser.add_argument("--license", type=Path, default=Path.home() / ".binaryninja/license.dat")
    options = parser.parse_args()
    binary = options.binja.resolve()
    workspace = Path(tempfile.mkdtemp(prefix="binja-startup-"))
    state = workspace / ".binja"
    resources = workspace / "fixture/binja"
    shutil.copytree(binary.parent.parent / "lib/binja", resources)
    bridge = resources / "bridge.py"
    bridge.chmod(0o600)
    with bridge.open("a") as plugin:
        plugin.write(MODAL)
    env = dict(os.environ, BINJA_RESOURCE_DIR=str(resources))
    env.pop("PYTHONPATH", None)
    print(f"Evidence: {workspace}", flush=True)

    def cli(*args, code=0):
        result = subprocess.run([str(binary), "--json", *map(str, args)],
            cwd=workspace, env=env, capture_output=True, text=True, timeout=20)
        assert result.returncode == code, (args, result.stdout, result.stderr)
        return json.loads(result.stdout)

    def wait_for(predicate, seconds=15):
        deadline = time.monotonic() + seconds
        while not predicate():
            assert time.monotonic() < deadline, "Condition did not become true"
            time.sleep(.1)

    def launch(*flags):
        (state / "modal.json").unlink(missing_ok=True)
        process = subprocess.Popen([str(binary), "--json", "start", "--license",
            str(options.license.resolve()), *flags], cwd=workspace, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        starts.append(process)
        wait_for(lambda: (state / "modal.json").exists())
        owner = cli("status")
        assert owner["running"] and owner["ready"] is False, owner
        assert owner["targets"] is None and owner["modal_open"] is None, owner
        assert not (state / "runtime/rpc.sock").exists()
        # Test-only process discovery; cleanup assertions cover both owned groups.
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
        assert len(children) == 3, children  # labwc, wayvnc, GUI launcher
        groups = [os.getpgid(pid) for pid in children]
        return process, owner, groups

    def failed(process, label, timeout=80):
        stdout, stderr = process.communicate(timeout=timeout)
        (workspace / f"{label}.json").write_text(stdout)
        assert process.returncode == 1, (stdout, stderr)
        return json.loads(stdout)["error"]

    def cleaned(groups):
        assert cli("status")["running"] is False
        for name in ("rpc.sock", "control.sock", "wayland-0", "wayland-0.lock"):
            assert not (state / "runtime" / name).exists(), name
        assert not list((state / "artifacts").iterdir())
        for group in groups:
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                continue
            raise AssertionError(f"Owned group survived: {group}")

    starts = []
    try:
        print("Default deadline stops a startup modal and cleans up", flush=True)
        before = time.monotonic()
        process, _, groups = launch()
        cli("screenshot", workspace / "default-modal.png")
        error = failed(process, "default-start")
        elapsed = time.monotonic() - before
        assert 60 <= elapsed < 80, elapsed
        assert "Session startup exited" in error, error
        for log in ("binaryninja.log", "supervisor.log"):
            assert str(state / "logs" / log) in error, error
        assert "GUI receiver did not become ready" in (state / "logs/supervisor.log").read_text()
        cleaned(groups)
        print(f"Default failed after {elapsed:.1f}s", flush=True)

        print("Disabled deadline survives the CLI wait, then recovers through input", flush=True)
        before = time.monotonic()
        process, owner, groups = launch("--no-startup-deadline")
        error = failed(process, "disabled-start")
        elapsed = time.monotonic() - before
        assert 70 <= elapsed < 80, elapsed
        assert "Startup wait timed out" in error, error
        stalled = cli("status")
        assert stalled["running"] and stalled["ready"] is False
        assert stalled["generation"] == owner["generation"]
        (workspace / "stalled-status.json").write_text(json.dumps(stalled))
        assert cli("screenshot", workspace / "disabled-modal.png")["ready"] is False
        cli("input", "key", "Return")
        wait_for(lambda: cli("status")["file_count"] == 0)
        reused = cli("start")
        assert reused["reused"] and reused["generation"] == owner["generation"]
        assert cli("py", "--no-target", "-c", "result = 6 * 7")["result"] == 42
        assert cli("screenshot", workspace / "recovered.png")["ready"] is True
        cli("stop")
        cleaned(groups)
        print(f"Recovered the same generation after {elapsed:.1f}s", flush=True)

        for action in ("force-stop", "gui-exit", "compositor-exit"):
            print(f"Disabled deadline still handles {action} before readiness", flush=True)
            process, _, groups = launch("--no-startup-deadline")
            before = time.monotonic()
            if action == "force-stop":
                cli("stop", "--force")
            elif action == "gui-exit":
                pid = json.loads((state / "modal.json").read_text())["pid"]
                os.kill(pid, signal.SIGTERM)
            else:
                os.killpg(groups[0], signal.SIGTERM)
            assert "Session startup exited" in failed(process, action, timeout=15)
            assert time.monotonic() - before < 15
            cleaned(groups)
        print("PASS — startup deadlines, modal recovery, and child cleanup", flush=True)
    finally:
        subprocess.run([str(binary), "stop", "--force"], cwd=workspace, env=env,
            capture_output=True, timeout=30)
        for process in starts:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=10)


if __name__ == "__main__":
    main()
