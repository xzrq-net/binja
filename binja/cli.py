import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Binary Ninja for agents. Start with `binja skill` for the workflow guide."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("skill", help="print the packaged workflow guide (no session required)")
    parser.parse_args()
    print(Path(__file__).with_name("guide.md").read_text())
