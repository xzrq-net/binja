---
blocked-by: [cmgxfc]
---
# Expose documentation for the installed Binary Ninja API

Implement API lookup against the selected distribution, following [CLI and documentation surface](../docs/design.md#cli-and-documentation-surface).

## Work

- Provide `api search`, `api members`, and `api show` using bundled Sphinx docs and Python source.
- Return version, qualified symbol, signature/docstring where available, and source location. Treat missing/ambiguous symbols and inherited members accurately.
- Static lookup must work without a GUI, license injection, or importing `binaryninja` into the CLI. Use shipped documentation instead of another hand-maintained API manual.
- Expose documentation paths for direct inspection. State static-lookup limitations for extension classes; the execution layer can supplement with explicit runtime introspection.
- Do not evaluate every property when enumerating live members.

## Verification

Retrieve a known member/docstring, list/search a class with many fields, and test missing/ambiguous symbols. Verify no GUI starts and the reported version matches the package. Test extraction/lookup behavior, not snapshots of an entire release.

The public API page fetched during investigation was labeled v5.3 while the ZIP is 6.0. Use packaged `binaryview.py`, `update.py`, and `api-docs/`; never depend on investigation scratch paths.
