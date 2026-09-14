"""Inbound native code/data references to the exact resolved address."""
from binja.analysis import function_info
from binja.references import brief_function, reference_listing, reference_subject

address, function = reference_subject(bv, args["function"])
code = {(r.address, r.function) for r in bv.get_code_refs(address)}
code = sorted(code, key=lambda r: (r[0], r[1].start, r[1].platform.name))
rows = [dict(kind="code", address=hex(source), functions=[brief_function(f)]) for source, f in code]
data = sorted(set(bv.get_data_refs(address)))
for source in data:
    functions = sorted(bv.get_functions_containing(source), key=lambda f: (f.start, f.platform.name))
    rows.append(dict(kind="data", address=hex(source), functions=[brief_function(f) for f in functions]))
result = dict(query=args["function"], function=function_info(function) if function else None,
    addresses=[hex(address)], direction="inbound", relation="reference",
    counts=dict(code_references=len(code), data_references=len(data)))
result = reference_listing(request, result, rows, args["offset"], args["limit"])
