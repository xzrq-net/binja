"""Function/address resolution and bounded native listings for typed commands."""
import re

import binaryninja as bn

from .common import Error


def function_info(function):
    return dict(name=function.name, start=hex(function.start),
        architecture=function.arch.name, platform=function.platform.name)


def one_function(functions, identifier):
    candidates = sorted(set(functions), key=lambda f: (f.start, f.platform.name))
    if len(candidates) > 1:
        names = "; ".join(f"{f.name} @ {f.start:#x} ({f.platform.name}/{f.arch.name})" for f in candidates)
        raise Error(f"Ambiguous function {identifier!r}: {names}. Use a unique name or address; "
            "same-address platform selection is available through py.")
    return candidates[0] if candidates else None


def named_symbols(bv, name):
    return bv.get_symbols_by_name(name) + bv.get_symbols_by_raw_name(name)


def resolve_address(bv, identifier):
    """Check the named base before asking Binary Ninja to evaluate its offset."""
    identifier = identifier.strip()
    symbols = named_symbols(bv, identifier)
    if symbols:
        addresses = {s.address for s in symbols}
        if len(addresses) > 1:
            candidates = sorted({f"{s.full_name} @ {s.address:#x} ({s.type.name})" for s in symbols})
            raise Error(f"Ambiguous address {identifier!r}: {'; '.join(candidates)}. Use an explicit address.")
        return bv.parse_expression(hex(addresses.pop()))
    offset = re.fullmatch(r"(.+)\+\s*(0[xX][0-9a-fA-F]+|0n[0-9]+|[0-9a-fA-F]+)", identifier)
    if offset:
        base = resolve_address(bv, offset[1].strip())
        return bv.parse_expression(f"{base:#x}+{offset[2]}")
    if re.fullmatch(r"0[xX][0-9a-fA-F]+|0n[0-9]+|[0-9a-fA-F]+", identifier):
        return bv.parse_expression(identifier)
    raise Error(f"Cannot resolve address {identifier!r}. Use a symbol, hex address, or symbol+offset; "
        "other expressions are available through py with bv.parse_expression.")


def resolve_function(bv, identifier):
    named = bv.get_functions_by_name(identifier)
    for symbol in bv.get_symbols_by_raw_name(identifier):
        named.extend(bv.get_functions_at(symbol.address))
    function = one_function(named, identifier)
    if function is not None:
        return function
    try:
        address = resolve_address(bv, identifier)
    except Error as exc:
        raise Error(f"No function named {identifier!r}. {exc}") from None
    candidates = bv.get_functions_at(address) + bv.get_functions_containing(address)
    function = one_function(candidates, identifier)
    if function is None:
        raise Error(f"No function at or containing {address:#x}. For linear disassembly use --count N or --end ADDRESS.")
    return function


def require_il_view(bv):
    if bv.view_type == "Raw":
        raise Error("IL unavailable: Raw views have no analysis pipeline. Select an analyzed target from binja targets.")


def rendered_rows(function, view, ssa=False):
    if view != "disasm":
        if function.analysis_skipped:
            raise Error(f"IL unavailable for {function.name} @ {function.start:#x}: analysis was skipped. "
                "Inspect function.analysis_skip_reason through py, or read disasm.")
        il = getattr(function, "hlil" if view == "pseudo-c" else view)
        if il is None or (ssa and il.ssa_form is None):
            raise Error(f"{view} {'SSA ' if ssa else ''}unavailable for {function.name} @ {function.start:#x}. "
                "Inspect analysis through py, or read disasm.")
    settings = bn.DisassemblySettings.default_linear_settings()
    # Addresses and bytes have their own columns; the body is always expanded.
    for option in (bn.DisassemblyOption.ShowAddress, bn.DisassemblyOption.ShowOpcode,
            bn.DisassemblyOption.ShowFunctionAddress, bn.DisassemblyOption.ShowCollapseIndicators):
        settings.set_option(option, False)
    settings.set_option(bn.DisassemblyOption.WaitForIL)
    if view == "pseudo-c":
        root = bn.LinearViewObject.single_function_language_representation(function, settings, "Pseudo C")
    else:
        representation = "disassembly" if view == "disasm" else view + ("_ssa_form" if ssa else "")
        root = getattr(bn.LinearViewObject, "single_function_" + representation)(function, settings)
    cursor = bn.LinearViewCursor(root)
    cursor.seek_to_begin()
    while cursor.valid:
        for line in cursor.lines:
            contents = line.contents
            text = str(contents)
            row = dict(address=hex(contents.address) if text.strip() else None, text=text)
            if view in ("hlil", "mlil", "llil"):
                instruction = contents.il_instruction
                row["il_index"] = instruction.instr_index if instruction is not None else None
            if view == "disasm":
                is_instruction = any(t.type == bn.InstructionTextTokenType.InstructionToken for t in contents.tokens)
                length = function.view.get_instruction_length(contents.address, function.arch) if is_instruction else 0
                row["bytes"] = function.view.read(contents.address, length).hex(" ") if length else None
            yield row
        if not cursor.next():
            break


def emit_listing(result, continuation=None):
    function = result["function"]
    name = f"{function['name']} @ {function['start']}" if function else f"linear @ {result['start']}"
    print(f"{result['target']}  {name}  {result['view']}{' SSA' if result['ssa'] else ''}")
    if result["address_kind"] == "anchor":
        print("Addresses are HLIL anchors, not machine instruction addresses.")
    for row in result["rows"]:
        address = row["address"] or ""
        detail = ""
        if "il_index" in row:
            index = row["il_index"]
            detail = f"{index if index is not None else '':>5}  "
        if "bytes" in row:
            detail = f"{row['bytes'] or '':<23}  "
        print(f"{address:12}  {detail}{row['text']}".rstrip())
    page = result["page"]
    if function:
        end = page["offset"] + page["returned"]
        span = f"{page['offset']}-{end - 1}" if page["returned"] else f"none at offset {page['offset']}"
        footer = f"rows {span} of {page['total']}"
        if page["next_offset"] is not None:
            footer += f"; continue with --offset {page['next_offset']}"
    else:
        footer = f"{page['returned']} instructions; next address {result['next_address']}"
        if result["stopped_reason"]:
            footer += f"; stopped: {result['stopped_reason']}"
        elif continuation:
            footer += f"; continue with {continuation}"
        else:
            footer += "; requested extent complete"
    print(footer)


def function_listing(request, function, view, offset, limit, ssa=False):
    rows = []
    total = 0
    for row in rendered_rows(function, view, ssa):
        if offset <= total < offset + limit:
            rows.append(row)
        total += 1
    if not total:
        raise Error(f"No {view} rendering available for {function.name} @ {function.start:#x}.")
    next_offset = offset + len(rows) if offset + len(rows) < total else None
    result = dict(target=request["target_snapshot"]["handle"], function=function_info(function),
        view=view, ssa=ssa, address_kind="anchor" if view in ("pseudo-c", "hlil") else "instruction",
        rows=rows, page=dict(offset=offset, limit=limit, returned=len(rows), total=total, next_offset=next_offset))
    emit_listing(result)
    return result
