"""Install named C type declarations from a submitted header."""
from pathlib import Path

from binja.common import Error
from binja.editing import edit_result, type_text

try:
    parsed = bv.parse_types_from_string(args["declarations"], include_dirs=[str(Path(args["path"]).parent)])
except SyntaxError as exc:
    raise Error(str(exc)) from None
unsupported = sorted(str(name) for name in [*parsed.functions, *parsed.variables])
if unsupported:
    raise Error("declare accepts named types; function/variable declarations need proto or py: " + ", ".join(unsupported))
if not parsed.types:
    raise Error(f"No named types to install from {args['path']}. "
        "Add named type declarations or declare the defining header directly; "
        "includes may supply only parsing context.")
before = {name: bv.get_type_by_name(name) for name in parsed.types}
for name, value in parsed.types.items():
    if before[name] != value:
        bv.define_user_type(name, value)
bv.update_analysis_and_wait()
types = []
for name in sorted(parsed.types, key=str):
    value = bv.get_type_by_name(name)
    types.append(dict(name=str(name), type=type_text(value), width=value.width,
        changed=before[name] != value))
result = edit_result(request, any(t["changed"] for t in types), path=args["path"], types=types)
for value in types:
    print(f"{value['name']}  {value['type']}  {value['width']} bytes  {'changed' if value['changed'] else 'no-op'}")
