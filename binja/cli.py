import argparse
import json
from pathlib import Path
import sys

from .common import Error, rpc, state_path


def main():
    parser = argparse.ArgumentParser(prog="binja",
        description="Binary Ninja for agents. Start with `binja skill` for the workflow guide."
    )
    parser.add_argument("--state-dir", help="session directory (or BINJA_STATE_DIR)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
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
        if args.command in ("start", "stop"):
            from . import session
            value = session.start(state, args.license) if args.command == "start" else session.stop(state, args.force)
        else:
            value = rpc(state, args.command)
        print(json.dumps(value, indent=2))
    except (Error, OSError, ValueError) as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"binja: {exc}", file=sys.stderr)
        sys.exit(1)
