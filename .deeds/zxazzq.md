---
blocked-by: [mpsj67]
---
# Add file lifecycle and common analysis CLI commands

Implement the first useful analysis workflow as readable Python scripts shipped by the CLI. Follow [CLI and documentation surface](../docs/design.md#cli-and-documentation-surface).

## Work

- Add file/database open, save to an explicit database destination, close, and analysis status/wait behavior. Opening a file must not silently change another command's target.
- Add decompile and xrefs as the initial common reads, preserving addresses and bounding/paginating output. Arbitrary Python covers gaps.
- Add deliberate UI focus/navigation and screenshot artifact output.
- Finish graceful session stop, coordinating queued/running operations and unsaved work. Discard/force is explicit; saving analysis never silently overwrites the input executable.
- Provide compact text and JSON output, resolved-target provenance, relevant analysis readiness, and accurate help.

## Verification

Open a copied binary, query it, mutate a name/comment through Python, save a BNDB, close/reopen, and verify persistence and unchanged input bytes. Exercise close/stop with unsaved changes and outstanding work. Compare representative rendered code with Binja.

Borrow selected rendering code from banteg/bn with attribution. Do not expand this into recreating their entire command/tool inventories.
