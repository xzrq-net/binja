---
blocked-by: [cmgxfc]
---
# Provide minimal installed API search and symbol lookup

Make unfamiliar Python API use practical before agent trials. Use bundled Sphinx documentation and Python source matching the packaged distribution.

## Work

- Provide `api search` and `api show` for documented/declared symbols. Return version, qualified symbol, signature/docstring where available, and source location. Expose documentation paths for direct inspection.
- Work without a GUI, license injection, or importing `binaryninja` into the CLI. Never depend on investigation scratch paths or a stale public documentation version.
- Report missing/ambiguous symbols and static-lookup limitations explicitly. Keep indexing simple; inherited-member enumeration and runtime extension introspection belong to `32k3q7`.
- Add working lookup examples to the packaged guide as commands land.

## Verification

Retrieve `BinaryView.get_functions_containing`, search for a relevant API, and test missing/ambiguous lookups. Verify no GUI starts, reported version matches the package, and installed paths work outside this repository. Test lookup behavior, not snapshots of an entire release.
