"""Annotated function disassembly or a bounded linear instruction window."""
from binja.analysis import emit_listing, function_listing, resolve_address, resolve_function
from binja.common import Error

count, end_expression = args["count"], args["end"]
if count is None and end_expression is None:
    function = resolve_function(bv, args["function"])
    result = function_listing(request, function, "disasm", args["offset"], args["limit"])
else:
    start = address = resolve_address(bv, args["function"])
    end = resolve_address(bv, end_expression) if end_expression is not None else None
    if end is not None and end <= start:
        raise Error("--end must be after the starting address (the end is exclusive).")
    architecture = bv.arch
    if architecture is None:
        raise Error("No view architecture. Select an analyzed view or set bv.arch through py.")
    rows = []
    stopped = None
    limit = args["limit"]
    while len(rows) < limit and (count is None or len(rows) < count) and (end is None or address < end):
        data = bv.read(address, architecture.max_instr_length)
        if not data:
            stopped = "unmapped address"
            break
        decoded = architecture.get_instruction_text(data, address)
        if decoded is None or not decoded[1] or decoded[1] > len(data):
            stopped = "undecodable instruction"
            break
        tokens, length = decoded
        if end is not None and address + length > end:
            stopped = "end splits an instruction"
            break
        rows.append(dict(address=hex(address), text="".join(t.text for t in tokens), bytes=data[:length].hex(" ")))
        address += length
    remaining = count - len(rows) if count is not None else None
    more = remaining > 0 if remaining is not None else address < end
    continuation = None
    if more and not stopped:
        extent = f"--count {remaining}" if remaining is not None else f"--end {end:#x}"
        continuation = f"disasm {address:#x} {extent} --limit {limit} --target {request['target_snapshot']['handle']}"
    result = dict(target=request["target_snapshot"]["handle"], function=None, view="disasm", ssa=False,
        address_kind="instruction", start=hex(start), count=count, end=hex(end) if end is not None else None,
        next_address=hex(address), remaining_count=remaining, stopped_reason=stopped,
        rows=rows, page=dict(limit=limit, returned=len(rows)))
    emit_listing(result, continuation)
