---
tier: objective
blocked-by: [5bkxzv, 2wrz2e, fm4yyw, vmnn2h, c6z866]
---
# Add typed analysis commands beside Python

Milestone. User guidance: the choice of commands and the task chunking are the
agents' call; "cover the essentials and the plausibles, without trying for
exhaustiveness (python is the backstop there)". The user will not call these
commands directly; the customer is the agent.

Parts, in delivery order:

1. 5bkxzv code inspection (decompile, il, disasm) plus the shared resolver and
   output contract. Essential.
2. 2wrz2e xrefs, refs, callers. Essential.
3. fm4yyw inventories. Plausible, cheap.
4. vmnn2h per-view close. Lifecycle gap, independent of the others.
5. c6z866 editing with undo grouping. Plausible.

Outside this milestone: scpm34 (screenshot and input, a separate user request),
8ty558 (search, frozen), 32k3q7 (API member listing, staged separately).

Evidence and the peer comparison against banteg/bn are in
docs/log.md under the 2026-09-13 CLI surface evaluation. Keep help and the one
packaged guide current with each part; retire guide recipes a command
replaces. Preserve applicable notices when borrowing rendering code from
banteg/bn.

Closed: All parts landed: decompile/il/disasm, xrefs/refs/callers, info/functions/imports/strings, close, rename/comment/proto/retype/declare/undo. Full installed smoke passed on the merged tip.
