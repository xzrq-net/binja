"""Offline index of the pinned distribution's declarations and docstrings."""
import ast
import json
from pathlib import Path
import sys


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
            setters = {d.value.id for n in body for d in getattr(n, "decorator_list", [])
                if isinstance(d, ast.Attribute) and d.attr == "setter" and isinstance(d.value, ast.Name)}
            for node in body:
                if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name.startswith("_"):
                    continue
                if any(isinstance(d, ast.Attribute) and d.attr in ("setter", "deleter") for d in getattr(node, "decorator_list", [])):
                    continue
                symbol = prefix + "." + node.name
                public = public_prefix + "." + node.name
                metadata = {}
                if isinstance(node, ast.ClassDef):
                    bases = [ast.unparse(b).split(".")[-1] for b in node.bases]
                    metadata["kind"] = "enum" if any(b in ("Enum", "IntEnum", "Flag", "IntFlag", "StrEnum") for b in bases) else "class"
                    if metadata["kind"] == "enum":
                        members = []
                        for statement in node.body:
                            if isinstance(statement, ast.Assign):
                                names, value = statement.targets, statement.value
                            elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
                                names, value = [statement.target], statement.value
                            else:
                                continue
                            for name in names:
                                if isinstance(name, ast.Name) and not name.id.startswith("_"):
                                    member = dict(name=name.id, expression=ast.unparse(value))
                                    try:
                                        literal = ast.literal_eval(value)
                                        if isinstance(literal, (str, int, float, bool)) or literal is None:
                                            member["value"] = literal
                                    except (ValueError, TypeError):
                                        pass
                                    members.append(member)
                        metadata["members"] = members
                    signature = "class " + node.name + "(" + ", ".join(ast.unparse(b) for b in node.bases) + ")"
                else:
                    is_property = any(isinstance(d, ast.Name) and d.id == "property" for d in node.decorator_list)
                    metadata["kind"] = "property" if is_property else "function"
                    if is_property:
                        metadata["writable"] = node.name in setters
                        metadata["return_type"] = ast.unparse(node.returns) if node.returns else None
                    signature = node.name + "(" + ast.unparse(node.args) + ")"
                    if node.returns:
                        signature += " -> " + ast.unparse(node.returns)
                records.append(dict(symbol=symbol, alias=public, signature=signature,
                    doc=ast.get_docstring(node) or "", source=str(source), line=node.lineno,
                    docs=f"{root.parent.parent}/api-docs/{module}-module.html#{symbol}", **metadata))
                if isinstance(node, ast.ClassDef):
                    collect(node.body, symbol, public)

        collect(tree.body, module, "binaryninja")
    return records


if __name__ == "__main__":
    Path(sys.argv[2]).write_text(json.dumps(declarations(Path(sys.argv[1]))))
