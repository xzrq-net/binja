"""Outbound native references whose sources lie in the function's analyzed blocks."""
from binja.analysis import function_info, resolve_function
from binja.references import reference_listing

function = resolve_function(bv, args["function"])
edges = set()
for block in function.basic_blocks:
    for source in range(block.start, block.end):
        for destination in bv.get_code_refs_from(source, function, block.arch):
            edges.add(("code", source, destination))
        for destination in bv.get_data_refs_from(source):
            edges.add(("data", source, destination))
rows = [dict(kind=kind, address=hex(source), to=hex(destination)) for kind, source, destination in sorted(edges)]
result = dict(query=args["function"], function=function_info(function), addresses=[hex(function.start)],
    direction="outbound", relation="reference",
    counts=dict(code_references=sum(kind == "code" for kind, _, _ in edges),
        data_references=sum(kind == "data" for kind, _, _ in edges)))
result = reference_listing(request, result, rows, args["offset"], args["limit"])
