"""Own child processes and the state lock; never trust a PID from a file."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid

from .common import Error, PROTOCOL, atomic_json, build_config, receive, rpc, send


def prepare_state(state):
    for relative in ("", "bn", "bn/plugins", "config", "cache", "data", "runtime", "tmp", "logs", "artifacts"):
        directory = state / relative
        if directory.is_symlink():
            raise Error(f"State directory must not be a symlink: {directory}")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.stat().st_uid != os.getuid():
            raise Error(f"State directory has a different owner: {directory}")
        directory.chmod(0o700)


def start(state, license_path):
    prepare_state(state)
    # A held lock means the owner must answer; stale files are never authority.
    with (state / "runtime/lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            status = rpc(state, "status")
            if status["version"].split()[0] != build_config()["version"]:
                raise Error("Running Binary Ninja version differs from this CLI; stop it before upgrading.")
            return dict(status, reused=True)
    license_path = Path(license_path or "~/.binaryninja/license.dat").expanduser().resolve()
    if not license_path.is_file():
        raise Error(f"License not found: {license_path}. Pass start --license PATH.")
    with (state / "logs/supervisor.log").open("a") as log:
        process = subprocess.Popen(
            [sys.executable, "-P", "-m", "binja.session", str(state), str(license_path)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
        )
    deadline = time.monotonic() + 70
    last_error = "receiver has not started"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise Error(f"Session startup exited ({process.returncode}); inspect {state / 'logs'}.")
        try:
            return rpc(state, "status", timeout=1)
        except Error as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise Error(f"Startup wait timed out: {last_error}; use status or stop --force to recover.")


def stop(state, force=False):
    owner = rpc(state, "status", control=True)
    generation = owner["generation"]
    if not force:
        rpc(state, "prepare_stop", generation=generation)
    rpc(state, "stop", generation=generation, control=True)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with (state / "runtime/lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return {"stopped": True, "generation": generation, "discarded": force}
            except BlockingIOError:
                time.sleep(0.1)
    raise Error("Shutdown is still in progress; inspect the supervisor log.")


def terminate(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def retire_artifacts(state):
    """Called only by the lifetime owner with no live GUI children."""
    for old in (state / "artifacts").iterdir():
        if old.is_dir() and not old.is_symlink():
            shutil.rmtree(old)
        else:
            old.unlink()


def serve(state, license_path):
    os.umask(0o077)
    config = build_config()
    with (state / "runtime/lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        generation = uuid.uuid4().hex[:12]
        runtime = state / "runtime"
        # Only the exclusive lock owner may retire endpoints from an old lifetime.
        for name in ("rpc.sock", "control.sock", "wayland-0", "wayland-0.lock"):
            (runtime / name).unlink(missing_ok=True)
        metadata = dict(generation=generation, protocol=PROTOCOL, display="headless", state_dir=str(state))
        atomic_json(runtime / "instance.json", metadata)
        plugins = state / "bn/plugins"
        if any(plugins.iterdir()):
            raise Error(f"Managed plugin directory must be empty: {plugins}")
        license_link = state / "bn/license.dat"
        if license_link.exists() and not license_link.is_symlink():
            raise Error(f"Refusing to replace a license file: {license_link}")
        license_link.unlink(missing_ok=True)
        license_link.symlink_to(license_path)
        source = str(Path(__file__).resolve().parent.parent)
        (state / "bn/startup.py").write_text(
            f"import sys\nsys.path.insert(0, {source!r})\nfrom binja.bridge import start\nstart()\n"
        )
        settings = {"ui.allowWelcome": False, "ui.mcp.enabled": False}
        for name in ("Updates", "UpdateChannelList", "ReleaseNotes", "ExtensionManager", "ExternalResources", "Debuginfod", "WARP", "CollaborationServer"):
            settings["network.enable" + name] = False
        atomic_json(state / "bn/settings.json", settings)
        retire_artifacts(state)
        env = os.environ.copy()
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH", "LD_PRELOAD", "BN_DISABLE_USER_SETTINGS"):
            env.pop(key, None)
        env.update({
            "XDG_RUNTIME_DIR": str(runtime), "XDG_CONFIG_HOME": str(state / "config"),
            "XDG_CACHE_HOME": str(state / "cache"), "XDG_DATA_HOME": str(state / "data"),
            "TMPDIR": str(state / "tmp"), "BN_USER_DIRECTORY": str(state / "bn"),
            "BN_QSETTINGS_POSTFIX": "binja", "BN_DISABLE_CRASH_REPORTING": "1",
            "BN_DISABLE_USER_PLUGINS": "1", "PYTHONNOUSERSITE": "1",
            "BINJA_STATE_DIR": str(state), "BINJA_GENERATION": generation,
            "WLR_BACKENDS": "headless", "WLR_HEADLESS_OUTPUTS": "1", "WLR_RENDERER": "pixman",
            "QT_QPA_PLATFORM": "wayland",
        })
        children = []
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        stopping = False

        def signal_stop(*_):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, signal_stop)
        signal.signal(signal.SIGINT, signal_stop)
        try:
            listener.bind(str(runtime / "control.sock"))
            listener.listen(8)
            listener.settimeout(0.2)
            with (state / "logs/labwc.log").open("w") as log:
                compositor = subprocess.Popen([config["labwc"], "-C", "/dev/null"], env=env,
                    stdout=log, stderr=log, start_new_session=True, stdin=subprocess.DEVNULL)
            children.append(compositor)
            deadline = time.monotonic() + 15
            while not (runtime / "wayland-0").exists():
                if compositor.poll() is not None or time.monotonic() > deadline or stopping:
                    raise Error("Private compositor did not start; inspect labwc.log.")
                time.sleep(0.1)
            env["WAYLAND_DISPLAY"] = "wayland-0"
            with (state / "logs/binaryninja.log").open("w") as log:
                gui = subprocess.Popen([config["runtime"], "-n"], env=env,
                    stdout=log, stderr=log, start_new_session=True, stdin=subprocess.DEVNULL)
            children.append(gui)
            deadline = time.monotonic() + 60
            ready = False
            while not stopping and all(child.poll() is None for child in children):
                if not ready:
                    try:
                        rpc(state, "hello", generation=generation, timeout=0.2)
                        ready = True
                    except Error:
                        if time.monotonic() > deadline:
                            raise Error("GUI receiver did not become ready; inspect binaryninja.log.")
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                with connection:
                    connection.settimeout(2)
                    response = dict(protocol=PROTOCOL, generation=generation)
                    try:
                        request = receive(connection)
                        if request.get("generation") != generation or request.get("protocol") != PROTOCOL:
                            raise Error("Session generation or protocol mismatch.")
                        if request["op"] == "stop":
                            stopping = True
                        elif request["op"] != "status":
                            raise Error("Unknown supervisor operation.")
                        response["data"] = dict(metadata, ready=ready)
                    except (Error, OSError, ValueError, KeyError) as exc:
                        response["error"] = str(exc)
                    try:
                        send(connection, response)
                    except OSError:
                        pass
        finally:
            for child in reversed(children):
                terminate(child)
            listener.close()
            retire_artifacts(state)
            for name in ("rpc.sock", "control.sock", "wayland-0", "wayland-0.lock"):
                (runtime / name).unlink(missing_ok=True)


if __name__ == "__main__":
    serve(Path(sys.argv[1]), Path(sys.argv[2]))
