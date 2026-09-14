---
blocked-by: [5bkxzv]
---
# Add inventory commands: info, functions, imports, and strings

Plausible rather than essential: Python recipes cover these today, but every
trial subject asked for them and they are the cheapest commands to add once
the 5bkxzv output contract exists.

- `info`: arch, platform, entry point, file and view type, function count,
  libraries, segments, sections.
- `functions [--match SUBSTRING|--regex] [--sort size|address|name] [--limit N]`:
  address, name, total_bytes.
- `imports [--match]`: address, symbol kind, name, type library when known
  (mirror the guide's inventory recipe).
- `strings [--match] [--limit N]`.

Bound lists with `--limit` and report the total so a truncated list is
recoverable. Avoid first-100-or-all pagination.
Retire the guide's "Inventory" recipe when these land.

Evidence: trial C asked for summary/functions/imports with sort-by-size
(temp/trials/reportC.md:102); trial A for listing (reportA.md:185).

Closed: info, functions, imports, and strings delivered on the page contract with totals and filters; verified row-for-row against native queries on sample and bash.
