---
blocked-by: [2nbgtk]
tier: objective
---
# Deliver a usable Binary Ninja MVP and run initial agent trials

User goal: “package and wrap Binary Ninja for agentic use.” Immediate priority: “redo the deeds to have a usability test MVP sooner”; subcommands can be implemented incrementally at the tail.

Use a locally maintained Python CLI and a small receiver in the pinned Personal GUI, with RPC under a workspace state directory. Borrow from banteg/bn with attribution; no MCP. Start with private Wayland, explicit BinaryViews, completed-analysis defaults, arbitrary Python, matching API lookup, and deliberate database saving.

[The design](../docs/design.md) describes architecture and interface constraints. This graph defines delivery order and the MVP boundary. Use `deeds ready` and `deeds show r2neck --tree`. Parts are local commit boundaries; commit completed work and finish with `jj new`.

## Done when

The installed CLI works from a separate workspace: discover `skill` through `--help`, start a managed private session, find matching API docs, open two copied samples, inspect and modify the intended view through Python, save a BNDB, stop/restart, reopen, and observe the saved change. Targets cannot be redirected by another client or GUI focus. Analysis readiness, stale/ambiguous target errors, recoverable requests, and refusal to silently discard unsaved work are verified.

Run bounded adversarial subagent review and usability trials at this checkpoint, fix blockers to this workflow, and record observed friction and unverified behavior. Investigation scripts are evidence, not an implementation to install wholesale.

## After the MVP

These remain intended work but do not gate this milestone: convenience commands (`zbqnx2`), desktop and visual access (`an2dc3`), richer API lookup (`32k3q7`), and optional update notices (`t7h2fr`). They depend on the initial trials so observations can guide implementation. Static analysis only; specialized loaders, extra Python dependencies, generalized undo, and automatic save cadence remain outside this implementation.
