"""Native analyzed strings, preserving decoded values and byte lengths."""
import json

from binja.analysis import print_page
from binja.inventory import inventory_page, text_filter

matches = text_filter(args["match"])
strings = sorted(bv.strings, key=lambda s: (s.start, s.type.name, s.length))

def rows():
    for string in strings:
        value = string.value
        if matches(value):
            yield dict(address=hex(string.start), type=string.type.name, length=string.length, value=value)

result = inventory_page(request, rows(), args["offset"], args["limit"],
    total_available=len(strings), match=args["match"])
for row in result["rows"]:
    value = json.dumps(row["value"], ensure_ascii=False)
    print(f"{row['address']}  {row['type']}  {row['length']} bytes  {value}")
print_page(result["page"])
