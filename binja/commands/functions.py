"""Filtered function inventory, ordered before pagination."""
from binja.analysis import print_page
from binja.inventory import inventory_page, text_filter

matches = text_filter(args["match"], args["regex"])
functions = list(bv.functions)
selected = [f for f in functions if matches(f.name)]
if args["sort"] == "size":
    key = lambda f: (-f.total_bytes, f.start, f.name, f.platform.name)
elif args["sort"] == "name":
    key = lambda f: (f.name, f.start, f.platform.name)
else:
    key = lambda f: (f.start, f.name, f.platform.name)
rows = (dict(address=hex(f.start), name=f.name, total_bytes=f.total_bytes) for f in sorted(selected, key=key))
result = inventory_page(request, rows, args["offset"], args["limit"],
    total_available=len(functions), match=args["match"], regex=args["regex"], sort=args["sort"])
print("total_bytes sums basic-block lengths, including overlaps; size order is largest first.")
for row in result["rows"]:
    print(f"{row['address']}  {row['total_bytes']} bytes  {row['name']}")
print_page(result["page"])
