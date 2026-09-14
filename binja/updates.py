"""A cached stable-release notice; no updater download or installation calls."""
from concurrent.futures import Future, TimeoutError
import json
import re
import threading
import time

CHANNEL = "release-personal"
CHECK_SECONDS = 5
CACHE_SECONDS = 24 * 60 * 60
ERROR_SECONDS = 60 * 60


def version_number(version):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?: [A-Za-z]+)?", version)
    if match is None:
        raise ValueError(f"Unrecognized stable version: {version}")
    return tuple(map(int, match.groups()))


def query(bn):
    if bn.update.are_auto_updates_enabled():
        raise RuntimeError("Automatic updates are enabled; metadata check skipped")
    # Enumeration fetches channel metadata, then latest_version_num is a Python
    # field read. updates_available also fetches/writes an updater manifest.
    return bn.update.UpdateChannel[CHANNEL].latest_version_num


def cached(path, installed):
    try:
        value = json.loads(path.read_text())
        if (value["installed"] == installed and value["channel"] == CHANNEL
                and value["status"] in ("available", "current", "unknown")
                and value["checked_at"] is not None
                and value["checked_at"] <= time.time() < value["expires_at"]):
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def check(state, bn):
    path = state / "cache/updates.json"
    installed = bn.core_version().split()[0]
    if cached(path, installed) is not None:
        return
    value = dict(installed=installed, channel=CHANNEL, latest_stable=None,
        status="unknown", checked_at=None, expires_at=None,
        error="Stable release metadata check in progress")
    save(path, value)
    result = Future()

    def fetch():
        try:
            result.set_result(query(bn))
        except Exception as exc:
            result.set_exception(exc)

    # The native API has no cancellation argument. Keep at most one call per
    # session, never join it on the worker/UI, and never publish a late result.
    threading.Thread(target=fetch, name="binja-update-query", daemon=True).start()
    try:
        latest = result.result(timeout=CHECK_SECONDS)
        available = version_number(latest) > version_number(installed)
        value.update(latest_stable=latest, status="available" if available else "current", error=None)
    except TimeoutError:
        value["error"] = f"Stable release metadata timed out after {CHECK_SECONDS}s"
    except Exception as exc:
        value["error"] = f"Stable release metadata: {type(exc).__name__}: {exc}"
    checked_at = int(time.time())
    lifetime = ERROR_SECONDS if value["status"] == "unknown" else CACHE_SECONDS
    value.update(checked_at=checked_at, expires_at=checked_at + lifetime)
    save(path, value)


def start(state, bn):
    def run():
        try:
            check(state, bn)
        except Exception as exc:
            # Notices must not prevent the receiver or analysis from starting.
            bn.log_warn(f"Update notice cache: {exc}")

    threading.Thread(target=run, name="binja-update-notice", daemon=True).start()
