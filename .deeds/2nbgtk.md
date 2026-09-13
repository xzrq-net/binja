---
blocked-by: [zxazzq, 2ggtpn, t7h2fr]
---
# Ship on-demand agent guidance and verify the complete workflow

Finish [Completion criteria](../docs/design.md#completion-criteria).

## Work

- Make `binja --help` prominently advertise `binja skill`, which prints a concise guide shipped with the CLI. Both must work without a state directory, license, or GUI. No separate agent-skill installation or global MCP configuration is required.
- Cover state/targets, lookup before unfamiliar API use, completed-analysis defaults and explicit overrides, Python output, deliberate saves at meaningful boundaries, request recovery, and update notices. Record observed mistakes rather than speculative exhaustive lists.
- Write README installation/first-session instructions using actual commands. Reconcile the design with delivered behavior and remove obsolete scaffold/documentation claims.
- Provide a reproducible integration smoke workflow with copied benign samples and runtime license injection.
- Once the initial command set works, run bounded usability trials with subagents given ordinary requests such as `use binja to open this binary`. Let them discover help, the guide, and API docs without repository design knowledge. Use isolated sample/state directories, observe friction, and revise the small command set and output. The user explicitly authorized this testing; do not expand the whole command surface in advance.

## Verification

From fresh state: start Personal, find matching docs, open two targets, query/mutate the intended one, recover a request after disconnect, save/reopen a BNDB, and stop cleanly. Check independent state directories, stale handles, and placement of writes/sockets.

Verify private Wayland screenshots and VNC viewing/input. Exercise desktop Wayland if a socket is available; otherwise record the exact missing validation. Run CLI examples outside the implementation repository and verify guide references point to installed commands/docs. Confirm a fresh agent can discover and use the workflow starting from `binja --help` without a preinstalled skill.

Close milestone r2neck when all parts meet their criteria, commit locally, and finalize the completed change with `jj new`.
