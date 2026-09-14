"""Native type parsing, variable selection, and compact edit readbacks."""
from .common import Error


def type_text(value):
    return str(value) if value is not None else None


def parse_type(bv, text):
    try:
        value, _ = bv.parse_type_string(text)
    except SyntaxError as exc:
        raise Error(str(exc)) from None
    return value


def variable_info(variable):
    return dict(identifier=hex(variable.identifier), name=variable.name,
        source=variable.source_type.name, index=variable.index, storage=variable.storage)


def resolve_variable(function, selector):
    variables = function.vars
    if selector.startswith("id:"):
        try:
            identifier = int(selector[3:], 0)
        except ValueError:
            raise Error(f"Invalid variable identifier {selector!r}. Use id:0xHEX or id:DECIMAL.") from None
        matches = [v for v in variables if v.identifier == identifier]
    else:
        matches = [v for v in variables if v.name == selector]
    if not matches:
        raise Error(f"No variable {selector!r} in {function.name}. Enumerate function.vars through py; "
            "select a unique name or id:0xHEX.")
    if len(matches) > 1:
        candidates = "; ".join(f"{v.name} id:{v.identifier:#x} ({v.source_type.name}/{v.index}/{v.storage})"
            for v in sorted(matches, key=lambda v: v.identifier))
        raise Error(f"Ambiguous variable {selector!r}: {candidates}. Use a native identifier.")
    return matches[0]


def edit_result(request, changed, **details):
    result = dict(target=request["target_snapshot"]["handle"], changed=changed, **details)
    print(f"{result['target']}  {request['kind']}  {'changed' if changed else 'no-op'}")
    function = result.get("function")
    if function:
        print(f"{function['name']} @ {function['start']}")
    if "before" in result:
        print(f"before: {result['before']!r}")
        print(f"after:  {result['after']!r}")
    return result
