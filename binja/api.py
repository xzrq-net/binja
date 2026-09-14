"""Offline index of the pinned distribution's declarations and docstrings."""
import ast
import json
from pathlib import Path
import sys


def declarations(root):
    records = []
    imports = {}
    for source in sorted(root.rglob("*.py")):
        relative = source.relative_to(root.parent).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts.pop()
        if any(part.startswith("_") for part in parts):
            continue
        module = ".".join(parts)
        tree = ast.parse(source.read_text())
        package = parts if source.stem == "__init__" else parts[:-1]
        for node in tree.body:
            if isinstance(node, ast.Import):
                for name in node.names:
                    local = name.asname or name.name.split(".")[0]
                    imports[module + "." + local] = name.name if name.asname else local
            elif isinstance(node, ast.ImportFrom):
                origin = package[:len(package) - node.level + 1] if node.level else []
                origin = ".".join([*origin, node.module] if node.module else origin)
                for name in node.names:
                    if name.name != "*":
                        imports[module + "." + (name.asname or name.name)] = origin + "." + name.name

        def collect(body, prefix, public_prefix, class_fields=False):
            setters = {d.value.id for n in body for d in getattr(n, "decorator_list", [])
                if isinstance(d, ast.Attribute) and d.attr == "setter" and isinstance(d.value, ast.Name)}
            for node in body:
                is_field = class_fields and isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                if not is_field and not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                name = node.target.id if is_field else node.name
                if name.startswith("_"):
                    continue
                if any(isinstance(d, ast.Attribute) and d.attr in ("setter", "deleter") for d in getattr(node, "decorator_list", [])):
                    continue
                symbol = prefix + "." + name
                public = public_prefix + "." + name
                metadata = {}
                if is_field:
                    # An annotated declaration need not be a dataclass instance field.
                    # Keep ClassVar annotations and field(...) defaults as source text.
                    metadata["kind"] = "field"
                    metadata["annotation"] = ast.unparse(node.annotation)
                    if node.value is not None:
                        metadata["default"] = ast.unparse(node.value)
                    signature = ast.unparse(node)
                elif isinstance(node, ast.ClassDef):
                    bases = [ast.unparse(b).split(".")[-1] for b in node.bases]
                    metadata["bases"] = [ast.unparse(b.value if isinstance(b, ast.Subscript) else b)
                        for b in node.bases]
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
                    doc="" if is_field else ast.get_docstring(node) or "", source=str(source), line=node.lineno,
                    docs=f"{root.parent.parent}/api-docs/{module}-module.html#{symbol}", **metadata))
                if isinstance(node, ast.ClassDef):
                    collect(node.body, symbol, public, class_fields=metadata["kind"] == "class")

        collect(tree.body, module, "binaryninja")

    classes = {r["symbol"]: r for r in records if r["kind"] in ("class", "enum")}

    def resolve(name):
        # Follow explicit imports, including module aliases and re-exports.
        seen = set()
        while name not in seen:
            seen.add(name)
            parts = name.split(".")
            for end in range(len(parts), 0, -1):
                prefix = ".".join(parts[:end])
                if prefix in imports:
                    name = ".".join([imports[prefix], *parts[end:]])
                    break
            else:
                return name
        return name

    def resolve_base(scope, expression):
        while scope:
            local = scope + "." + expression
            resolved = resolve(local)
            if resolved in classes or resolved != local:
                return resolved
            scope = scope.rpartition(".")[0]
        return "builtins.object" if expression == "object" else expression

    for record in classes.values():
        scope = record["symbol"].rsplit(".", 1)[0]
        record["bases"] = [resolve_base(scope, b) for b in record["bases"]]

    visiting = set()

    def linearize(symbol):
        if symbol not in classes:
            return [symbol] if symbol == "builtins.object" else [symbol, "builtins.object"]
        record = classes[symbol]
        if "mro" in record:
            return record["mro"]
        if symbol in visiting:
            raise ValueError(f"Cyclic static inheritance: {symbol}")
        visiting.add(symbol)
        bases = record["bases"] or ["builtins.object"]
        pending = [list(linearize(b)) for b in bases] + [list(bases)]
        order = [symbol]
        # C3: a head is eligible only when it appears in no other tail.
        while pending := [p for p in pending if p]:
            head = next((p[0] for p in pending if all(p[0] not in q[1:] for q in pending)), None)
            if head is None:
                raise ValueError(f"Inconsistent static inheritance: {symbol}")
            order.append(head)
            for sequence in pending:
                if sequence[0] == head:
                    sequence.pop(0)
        visiting.remove(symbol)
        record["mro"] = order
        record["unresolved_bases"] = [b for b in order[1:] if b not in classes and b != "builtins.object"]
        return order

    for symbol in classes:
        linearize(symbol)
    return records


if __name__ == "__main__":
    Path(sys.argv[2]).write_text(json.dumps(declarations(Path(sys.argv[1]))))
