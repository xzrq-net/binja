"""Reference subjects, import normalization, and paged reference text."""
import binaryninja as bn

from .analysis import named_function, named_symbols, page_rows, print_page, resolve_address
from .common import Error

IMPORT_KINDS = {bn.SymbolType.ImportedFunctionSymbol, bn.SymbolType.ImportAddressSymbol,
    bn.SymbolType.ExternalSymbol}


def brief_function(function):
    return dict(name=function.name, start=hex(function.start))


def reference_subject(bv, identifier):
    function = named_function(bv, identifier)
    address = function.start if function is not None else resolve_address(bv, identifier)
    return address, function


def call_subject(bv, identifier):
    symbols = [s for s in named_symbols(bv, identifier) if s.type in IMPORT_KINDS]
    function = None
    if not symbols:
        address, function = reference_subject(bv, identifier)
        symbols = [s for s in bv.get_symbols(address, 1) if s.type in IMPORT_KINDS]
        if not symbols:
            return {address}, set(), [], function
    names = {s.raw_name for s in symbols}
    if len(names) != 1:
        candidates = "; ".join(sorted({f"{s.raw_name} @ {s.address:#x}" for s in symbols}))
        raise Error(f"Ambiguous import {identifier!r}: {candidates}. Use an exact import name.")
    # An address at any representation selects the same import as its raw name.
    name = names.pop()
    symbols = [s for s in named_symbols(bv, name) if s.type in IMPORT_KINDS and s.raw_name == name]
    addresses = {s.address for s in symbols}
    stubs = {s.address for s in symbols if s.type == bn.SymbolType.ImportedFunctionSymbol}
    representations = sorted({(s.address, s.type.name, s.full_name) for s in symbols})
    rows = [dict(address=hex(address), kind=kind, name=name) for address, kind, name in representations]
    return addresses, stubs, rows, None


def reference_listing(request, result, rows, offset, limit):
    result["target"] = request["target_snapshot"]["handle"]
    result["rows"], result["page"] = page_rows(rows, offset, limit)
    function = result["function"]
    name = function["name"] if function else result["query"]
    addresses = ", ".join(result["addresses"])
    direction = result["direction"]
    print(f"{result['target']}  {name} @ {addresses}  {request['kind']} ({direction})")
    counts = result["counts"]
    if result["relation"] == "call":
        for symbol in result["symbols"]:
            print(f"import {symbol['kind']}  {symbol['name']} @ {symbol['address']}")
        if result["excluded_stubs"]:
            print("Excluded import stubs: " + ", ".join(result["excluded_stubs"]))
        print(f"inbound code: {counts['call_sites']} resolved call sites; {counts['code_references']} code references")
        for row in result["rows"]:
            function = row["function"]
            print(f"{row['address']}  call from {function['name']} @ {function['start']}")
        print("Zero references is not proof of no callers; unresolved indirect calls may be absent.")
    else:
        print("Code/data classify the reference source; references are not calls.")
        for kind in ("code", "data"):
            print(f"{direction} {kind} references: {counts[kind + '_references']}")
            for row in result["rows"]:
                if row["kind"] != kind:
                    continue
                if direction == "inbound":
                    functions = ", ".join(f"{f['name']} @ {f['start']}" for f in row["functions"])
                    print(f"{row['address']}  from {functions or '(no containing function)'}")
                else:
                    destination = f"{row['to_symbol']} @ {row['to']}" if row["to_symbol"] else row["to"]
                    print(f"{row['address']} -> {destination}")
        if direction == "inbound":
            print("Zero references is not proof of no callers; unresolved indirect calls may be absent.")
    print_page(result["page"])
    return result
