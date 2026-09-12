---
blocked-by: [zxazzq, 2ggtpn, t7h2fr]
---
# Ship the agent skill and verify the complete workflow

Finish [Completion criteria](../docs/design.md#completion-criteria).

## Work

- Create a concise agent skill using the available skill-creation workflow. Cover state/targets, lookup before unfamiliar API use, Python output, persistence, request recovery, and update notices.
- Keep invocation explicit and installation workspace-scoped. Do not configure global MCP. Record observed mistakes rather than speculative exhaustive lists.
- Write README installation/first-session instructions using actual commands. Reconcile the design with delivered behavior and remove obsolete scaffold/documentation claims.
- Provide a reproducible integration smoke workflow with copied benign samples and runtime license injection.

## Verification

From fresh state: start Personal, find matching docs, open two targets, query/mutate the intended one, recover a request after disconnect, save/reopen a BNDB, and stop cleanly. Check independent state directories, stale handles, and placement of writes/sockets.

Verify private Wayland screenshots and VNC viewing/input. Exercise desktop Wayland if a socket is available; otherwise record the exact missing validation. Run CLI examples outside the implementation repository and verify skill links point to installed commands/docs.

Close milestone r2neck when all parts meet their criteria, commit locally, and finalize the completed change with `jj new`.
