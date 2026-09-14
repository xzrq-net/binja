"""Resolved calls to a function/address or an import's stub, slot and external symbol."""
from binja.analysis import function_info
from binja.references import call_subject, reference_listing

addresses, stubs, symbols, function = call_subject(bv, args["function"])
calls = set()
for caller in bv.functions:
    if caller.start in stubs:
        continue
    for site in caller.call_sites:
        if addresses.intersection(bv.get_callees(site.address, caller, site.arch)):
            calls.add((caller.start, caller.name, site.address))
code = {(r.function.start, r.address) for address in addresses for r in bv.get_code_refs(address)
    if r.function.start not in stubs}
rows = [dict(address=hex(site), function=dict(start=hex(start), name=name)) for start, name, site in sorted(calls)]
result = dict(query=args["function"], function=function_info(function) if function else None,
    addresses=[hex(a) for a in sorted(addresses)], symbols=symbols, excluded_stubs=[hex(a) for a in sorted(stubs)],
    direction="inbound", relation="call", counts=dict(call_sites=len(calls), code_references=len(code)))
result = reference_listing(request, result, rows, args["offset"], args["limit"])
