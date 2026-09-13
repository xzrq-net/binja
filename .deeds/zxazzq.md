---
blocked-by: [mpsj67]
---
# Add file lifecycle and common analysis CLI commands

Implement the first useful analysis workflow as readable Python scripts shipped by the CLI. Follow [CLI and documentation surface](../docs/design.md#cli-and-documentation-surface).

## Work

- Add file/database open, save to an explicit database destination, close, and analysis status/wait behavior. Default open and analysis commands to completed analysis; require an explicit option for partial work. Opening a file must not silently change another command's target. Static analysis only; specialized loaders can be handled through Python or a manually prepared BNDB.
- Make slow saves inspectable/retrievable through the request mechanism and surface dirty state and the last successful save observed by the session where available. Do not fabricate earlier save history. Keep automatic cadence undecided; teach deliberate saves at meaningful boundaries instead of adding an autosaver.
- Add decompile and xrefs as the initial common reads, preserving Binary Ninja's natural address representations and bounding/paginating output. Clarify view/address-versus-offset/symbol ambiguity as needed, without building a universal schema. Arbitrary Python covers gaps.
- Add deliberate UI focus/navigation and screenshot artifact output.
- Add inexpensive API-backed checks for dialogs or required interaction where available; do not build general dialog automation. Report the limitation when state cannot be determined reliably.
- Use native undo support where easy in editing commands; avoid a generalized undo framework.
- Finish graceful session stop, coordinating queued/running operations and unsaved work. Discard/force is explicit; saving analysis never silently overwrites the input executable.
- Provide compact text and JSON output, resolved-target provenance, relevant analysis readiness, and accurate help.

## Verification

Open a copied binary, query it, mutate a name/comment through Python, save a BNDB, close/reopen, and verify persistence and unchanged input bytes. Exercise close/stop with unsaved changes and outstanding work. Compare representative rendered code with Binja.

Check default analysis readiness and the explicit incomplete-analysis path. Verify save status distinguishes running, successful, and failed saves, including client disconnect recovery. Exercise a detectable GUI interaction requirement if the API supports it.

Borrow selected rendering code from banteg/bn with attribution. Do not expand this into recreating their entire command/tool inventories.
