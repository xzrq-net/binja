"""Offline index of the pinned distribution's declarations and docstrings."""
import ast
import json
from pathlib import Path
import sys

from .common import Error, build_config


def declarations(root):
    records = []
    for source in sorted(root.rglob("*.py")):
        relative = source.relative_to(root.parent).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts.pop()
        if any(part.startswith("_") for part in parts):
            continue
        module = ".".join(parts)
        tree = ast.parse(source.read_text())

        def collect(body, prefix, public_prefix):
            for node in body:
                if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name.startswith("_"):
                    continue
                if any(isinstance(d, ast.Attribute) and d.attr in ("setter", "deleter") for d in getattr(node, "decorator_list", [])):
                    continue
                symbol = prefix + "." + node.name
                public = public_prefix + "." + node.name
                if isinstance(node, ast.ClassDef):
                    signature = "class " + node.name + "(" + ", ".join(ast.unparse(b) for b in node.bases) + ")"
                else:
                    signature = node.name + "(" + ast.unparse(node.args) + ")"
                    if node.returns:
                        signature += " -> " + ast.unparse(node.returns)
                records.append(dict(symbol=symbol, alias=public, signature=signature,
                    doc=ast.get_docstring(node) or "", source=str(source), line=node.lineno,
                    docs=f"{root.parent.parent}/api-docs/{module}-module.html#{symbol}"))
                if isinstance(node, ast.ClassDef):
                    collect(node.body, symbol, public)

        collect(tree.body, module, "binaryninja")
    return records


def query(operation, value=None, limit=15):
    config = build_config()
    base = dict(version=config["version"], source=config["vendor"] + "/python/binaryninja",
                docs=config["vendor"] + "/api-docs")
    if operation == "paths":
        return base
    records = json.loads(Path(__file__).with_name("api-index.json").read_text())
    if operation == "show":
        matches = [r for r in records if value in (r["symbol"], r["alias"], r["alias"].removeprefix("binaryninja."))]
        if not matches:
            matches = [r for r in records if r["symbol"].endswith("." + value)]
        if len(matches) != 1:
            if not matches:
                raise Error(f"No static declaration for {value!r}; try api search. Inherited and native UI members may need direct documentation inspection (api paths).")
            raise Error("Ambiguous symbol; use a qualified name: " + ", ".join(r["symbol"] for r in matches))
        return dict(base, **{k: v for k, v in matches[0].items() if k != "alias"})
    terms = value.casefold().split()
    if not terms:
        raise Error("Supply a nonempty API search query.")
    matches = [r for r in records if all(t in (r["symbol"] + " " + r["doc"]).casefold() for t in terms)]
    matches.sort(key=lambda r: (-sum(t in r["symbol"].casefold() for t in terms), len(r["symbol"]), r["symbol"]))
    return dict(base, total=len(matches), matches=[dict(symbol=r["symbol"], signature=r["signature"],
        summary=r["doc"].split("\n")[0], source=r["source"], line=r["line"]) for r in matches[:limit]])


if __name__ == "__main__":
    Path(sys.argv[2]).write_text(json.dumps(declarations(Path(sys.argv[1]))))
