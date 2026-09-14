# Add guide recipes for decompilation, renaming, and import callers

Every usability subject completed its task through `py` but spent most effort
reconstructing Binary Ninja Python idioms rather than waiting or fighting the
CLI. Recipes they asked for, in the packaged guide (`binja/guide.md`):

- Addressed HLIL listing (`f.hlil.root.lines` with `line.address`) next to the
  matching disassembly (`Function.instructions`); one subject needed both to
  resolve a decompiler stride ambiguity in a checksum loop.
- Rename and function-comment writes (`f.name = ...`, `f.comment = ...`) and a
  save/reopen verification.
- Import callers: the three symbol kinds per import (ImportedFunctionSymbol,
  ImportAddressSymbol, ExternalSymbol), `s.type.name` for readable kinds,
  excluding the stub itself, `call_sites`/`get_callees` versus `get_code_refs`.
- Inventory: entry point, function count, largest functions with `total_bytes`
  semantics stated, imports with library attribution if the API exposes it.

Keep these as guide text unless `zbqnx2` turns one into a command.

Also state plainly: one worker per session, so batch per-function work into a
single script; parallel shells hide client overhead but add no throughput
(closed `8vftez`).
