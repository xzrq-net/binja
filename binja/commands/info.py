"""View summary with one bounded list of libraries, segments, and sections."""
from binja.analysis import print_page
from binja.inventory import inventory_page

libraries = sorted(bv.libraries)
segments = sorted(bv.segments, key=lambda s: (s.start, s.end, s.data_offset))
sections = sorted(bv.sections.values(), key=lambda s: (s.start, s.name))
rows = [dict(kind="library", name=name) for name in libraries]
for segment in segments:
    permissions = ("r" if segment.readable else "-") + ("w" if segment.writable else "-") + ("x" if segment.executable else "-")
    rows.append(dict(kind="segment", start=hex(segment.start), end=hex(segment.end), permissions=permissions,
        file_offset=hex(segment.data_offset), file_length=segment.data_length))
for section in sections:
    rows.append(dict(kind="section", name=section.name, start=hex(section.start), end=hex(section.end),
        semantics=section.semantics.name))
result = inventory_page(request, rows, args["offset"], args["limit"], path=bv.file.filename, view_type=bv.view_type,
    architecture=bv.arch.name if bv.arch else None, platform=bv.platform.name if bv.platform else None,
    entry_point=hex(bv.entry_point), function_count=len(bv.functions),
    counts=dict(libraries=len(libraries), segments=len(segments), sections=len(sections)))
print(f"{result['path']}  {result['view_type']}  {result['architecture'] or 'unknown architecture'}  {result['platform'] or 'unknown platform'}")
print(f"entry {result['entry_point']}; {result['function_count']} functions")
print(f"{len(libraries)} libraries; {len(segments)} segments; {len(sections)} sections (exclusive ends)")
for row in result["rows"]:
    if row["kind"] == "library":
        print(f"library  {row['name']}")
    elif row["kind"] == "segment":
        print(f"segment  {row['start']}-{row['end']}  {row['permissions']}  file offset {row['file_offset']} + {row['file_length']} bytes")
    else:
        print(f"section  {row['start']}-{row['end']}  {row['name']}  {row['semantics']}")
print_page(result["page"])
