---
blocked-by: [2nbgtk]
---
# Add analysis and UI convenience commands after usability trials

Extend the working Python-first interface in small increments guided by recorded trial friction. These commands are follow-up work, not prerequisites for the initial review/tests. Split a command into its own deed when it becomes a separate implementation handoff; do not prebuild an API-sized inventory.

- Add per-view `close`, coordinating queued/running requests, unsaved changes, and handle invalidation.
- Add `decompile` and `xrefs` with compact text/JSON, target provenance, and bounded or paginated output. Preserve native address conventions and reject ambiguous symbols/offsets. Compare representative output with Binary Ninja.
- Add deliberate UI focus/navigation and screenshot artifact output. Coordinate visual verification with `an2dc3`.
- Add inexpensive dialog/interaction checks only where the API supports them. Unknown interaction state must remain explicit; no automatic clicking.
- Use native undo where easy for editing commands; no generalized undo framework.

Keep help and the one packaged guide current with each addition. Run focused verification and bounded usability follow-ups for changes to the user workflow. Preserve applicable notices when borrowing rendering code from banteg/bn.
