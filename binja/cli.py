import argparse
import json
from pathlib import Path
import sys
import time
import uuid

from .common import Error, rpc, state_path


def globals_for(parser):
    parser.add_argument("--state-dir", default=argparse.SUPPRESS, help="session directory (or BINJA_STATE_DIR)")
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")
    parser.add_argument("--target", default=argparse.SUPPRESS, help="view handle, unique filename/path, or active")


def execution_options(parser):
    parser.add_argument("--allow-incomplete", action="store_true", help="deliberately skip the analysis readiness gate")
    parser.add_argument("--no-wait", action="store_true", help="submit and return the recoverable request ID")
    parser.add_argument("--wait", type=float, default=30, metavar="SECONDS", help="client wait limit; execution continues after timeout (default 30)")
    parser.add_argument("--request-id", help="reuse an exact submission ID for deduplication, never for a new mutation")


def wait_for(state, record, seconds):
    deadline = time.monotonic() + seconds
    while record["status"] not in ("completed", "failed", "cancelled", "expired") and time.monotonic() < deadline:
        time.sleep(min(0.2, max(0, deadline - time.monotonic())))
        record = rpc(state, "request", id=record["id"])
    return record


def submit(state, args, source, filename, parameters, no_target=False):
    session = rpc(state, "hello")
    request_id = args.request_id or f"{session['generation']}:r{uuid.uuid4().hex[:16]}"
    # Emit the ID before network submission, including if acknowledgement is lost.
    receipt = json.dumps({"event": "submitting", "id": request_id}) if args.json else f"Request {request_id}"
    print(receipt, file=sys.stderr, flush=True)
    spec = dict(id=request_id, source=source, filename=filename, args=parameters,
        target=args.target, no_target=no_target, allow_incomplete=args.allow_incomplete)
    record = rpc(state, "submit", spec=spec)
    if not args.no_wait:
        record = wait_for(state, record, args.wait)
    return record


def render(value, command, as_json):
    if as_json:
        print(json.dumps(value, indent=2))
        return
    if isinstance(value, dict) and "id" in value:
        target = value.get("target")
        print(f"{value['id']} {value['status']}" + (f" — {target['handle']} ({target['view_type']}) {target['path']}" if target else ""))
        if value.get("allow_incomplete"):
            print("Analysis: incomplete results explicitly allowed")
        for stream in ("stdout", "stderr"):
            output = value.get(stream, {})
            if output.get("text"):
                print(output["text"], end="" if output["text"].endswith("\n") else "\n")
            if output.get("artifact"):
                print(f"{stream}: {output['artifact']}")
            if output.get("truncated"):
                print(f"{stream}: truncated at 1 MiB")
        if command == "open" and value.get("status") == "completed":
            opened = value["result"]
            print(f"Opened {opened['path']}\nAnalysis: {opened['analysis']}")
        elif command == "save" and value.get("status") == "completed":
            print(f"Saved {value['result']['saved']['path']}")
        elif value.get("result") is not None:
            print(json.dumps(value["result"], indent=2))
        if value.get("result_artifact"):
            print(f"Result: {value['result_artifact']} ({value['result_bytes']} bytes)")
        if value.get("error"):
            print(value.get("traceback") or value["error"])
        if value["status"] in ("queued", "running", "waiting_analysis"):
            print(f"Retrieve with: binja request {value['id']} --wait 30")
    elif command == "targets":
        for target in value:
            dirty = "unsaved" if target["modified"] or target["analysis_changed"] else "clean"
            print(f"{target['handle']}  {target['view_type']}  {target['analysis']}  {dirty}" + ("  [active]" if target["active"] else ""))
            print(f"  {target['path']}")
        if not value:
            print("No open targets. Use binja open PATH.")
    elif command == "requests":
        for record in value:
            print(f"{record['id']}  {record['status']}")
        if not value:
            print("No requests in this session.")
    elif command in ("start", "status"):
        print(f"Binary Ninja {value['version']} — {value['display']}" + (" (reused)" if value.get("reused") else ""))
        print(f"State: {value['state_dir']}\nGeneration: {value['generation']}")
        print(f"{len(value['targets'])} views; {len(value['requests'])} pending requests")
        for record in value["requests"]:
            print(f"  {record['id']} {record['status']}")
    elif command == "stop":
        print(f"Stopped {value['generation']}" + ("; unsaved work discarded" if value["discarded"] else ""))
    else:
        print(json.dumps(value, indent=2))


def main():
    parser = argparse.ArgumentParser(prog="binja",
        description="Binary Ninja for agents. Start with `binja skill` for the workflow guide."
    )
    globals_for(parser)
    parser.set_defaults(state_dir=None, json=False, target=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("skill", help="print the packaged workflow guide (no session required)")
    api = sub.add_parser("api", help="search/show matching API documentation without a GUI")
    api_sub = api.add_subparsers(dest="api_command", required=True)
    api_sub.add_parser("paths", help="show bundled documentation and Python source paths")
    search = api_sub.add_parser("search", help="search declared symbols and docstrings")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=15)
    show = api_sub.add_parser("show", help="show a qualified symbol's signature and docstring")
    show.add_argument("symbol")
    start = sub.add_parser("start", help="start or reuse a private Wayland session")
    start.add_argument("--license", help="runtime license file (default ~/.binaryninja/license.dat)")
    start.add_argument("--display", choices=["headless"], default="headless")
    sub.add_parser("status", help="show session identity and live views")
    sub.add_parser("targets", help="list explicit view handles and paths")
    stop = sub.add_parser("stop", help="stop the owned session")
    stop.add_argument("--force", action="store_true", help="terminate and discard unsaved work")
    py = sub.add_parser("py", help="execute Python against a retained target (file, -c, or stdin)")
    inputs = py.add_mutually_exclusive_group()
    inputs.add_argument("--file", help="read Python source from a file")
    inputs.add_argument("-c", dest="code", help="inline Python source")
    py.add_argument("--args", default="{}", help="JSON value exposed as args; separate from source")
    py.add_argument("--no-target", action="store_true", help="explicit session script with bv=None")
    execution_options(py)
    open_file = sub.add_parser("open", help="open a binary or BNDB and wait for analysis")
    open_file.add_argument("path")
    execution_options(open_file)
    save = sub.add_parser("save", help="save the intended target to an explicit .bndb path")
    save.add_argument("path")
    execution_options(save)
    sub.add_parser("requests", help="list retained request states")
    request = sub.add_parser("request", help="retrieve an existing request; never re-execute it")
    request.add_argument("id")
    request.add_argument("--wait", type=float, default=0, metavar="SECONDS")
    cancel = sub.add_parser("cancel", help="cancel queued work or a readiness wait")
    cancel.add_argument("id")
    for child in sub.choices.values():
        globals_for(child)
    for child in api_sub.choices.values():
        globals_for(child)
    args = parser.parse_args()
    try:
        if args.command == "skill":
            print(Path(__file__).with_name("guide.md").read_text())
            return
        if args.command == "api":
            from .api import query
            value = query(args.api_command, getattr(args, "query", None) or getattr(args, "symbol", None), getattr(args, "limit", 15))
            if args.json:
                print(json.dumps(value, indent=2))
            elif args.api_command == "show":
                print(f"Binary Ninja {value['version']} — {value['symbol']}\n{value['signature']}\n{value['source']}:{value['line']}\n\n{value['doc']}\n\nDocs: {value['docs']}")
            elif args.api_command == "search":
                print(f"Binary Ninja {value['version']} — {value['total']} matches")
                for match in value["matches"]:
                    print(f"{match['symbol']}\n  {match['signature']}\n  {match['summary']}")
            else:
                print(json.dumps(value, indent=2))
            return
        state = state_path(args.state_dir)
        if args.target and "/" in args.target:
            args.target = str(Path(args.target).expanduser().resolve())
        if args.command in ("open", "save"):
            if args.command == "open" and args.target:
                raise Error("open selects a file by path; omit --target.")
            path = Path(args.path).expanduser().resolve()
            if args.command == "open" and not path.is_file():
                raise Error(f"Input file does not exist: {path}")
            command_file = Path(__file__).with_name("commands") / (args.command + ".py")
            value = submit(state, args, command_file.read_text(), str(command_file), {"path": str(path)}, args.command == "open")
        elif args.command == "py":
            if args.no_target and args.target:
                raise Error("--no-target and --target cannot be combined.")
            if args.file:
                filename = str(Path(args.file).expanduser().resolve())
                source = Path(filename).read_text()
            elif args.code is not None:
                filename, source = "<binja -c>", args.code
            else:
                if sys.stdin.isatty():
                    raise Error("Supply py --file SCRIPT, py -c CODE, or Python on stdin.")
                filename, source = "<binja stdin>", sys.stdin.read()
            value = submit(state, args, source, filename, json.loads(args.args), args.no_target)
        elif args.command == "request":
            value = wait_for(state, rpc(state, "request", id=args.id), args.wait)
        elif args.command == "cancel":
            value = rpc(state, "cancel", id=args.id)
        elif args.command in ("start", "stop"):
            from . import session
            value = session.start(state, args.license) if args.command == "start" else session.stop(state, args.force)
        else:
            value = rpc(state, args.command)
        render(value, args.command, args.json)
        if isinstance(value, dict) and value.get("status") in ("failed", "cancelled", "expired"):
            sys.exit(1)
        if isinstance(value, dict) and value.get("status") in ("running", "waiting_analysis", "queued") and not getattr(args, "no_wait", False):
            sys.exit(2)
    except (Error, OSError, ValueError) as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"binja: {exc}", file=sys.stderr)
        sys.exit(1)
