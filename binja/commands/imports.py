"""Import symbol representations and their native type-library attribution."""
from binja.analysis import print_page
from binja.inventory import inventory_page, text_filter
from binja.references import IMPORT_KINDS

matches = text_filter(args["match"])
symbols = [s for s in bv.get_symbols() if s.type in IMPORT_KINDS]
selected = sorted((s for s in symbols if matches(s.full_name)), key=lambda s: (s.full_name, s.address, s.type.name))
rows = []
for symbol in selected:
    origin = bv.lookup_imported_object_library(symbol.address)
    rows.append(dict(address=hex(symbol.address), kind=symbol.type.name, name=symbol.full_name,
        type_library=origin[0].name if origin else None))
result = inventory_page(request, rows, args["offset"], args["limit"],
    total_available=len(symbols), match=args["match"])
print("Type library is type provenance; it does not identify the runtime library supplying the symbol.")
for row in result["rows"]:
    print(f"{row['address']}  {row['kind']}  {row['name']}  type library: {row['type_library'] or 'unknown'}")
print_page(result["page"])
