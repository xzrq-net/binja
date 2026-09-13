---
blocked-by: [2nbgtk]
tier: objective
---
# Deliver the first managed Binary Ninja CLI workflow

User goal: “package and wrap Binary Ninja for agentic use.” The accepted interface is a locally maintained CLI, a small Python receiver inside the Personal-edition GUI, and an RPC socket under the state directory. Borrow from banteg/bn without depending on its release process. Support desktop and private Wayland displays, discover the installed API, and omit MCP initially.

[The design](../docs/design.md) is the implementation contract. Use `deeds ready` and `deeds show r2neck --tree`. Parts are intended as local commit boundaries; agents commit and finish completed jj changes with `jj new`.

User refinements: “static analysis only”; “default posture is to only operate once analysis is finished”; “start with binary ninja's natural representations”; and “binja --help” leading to “binja skill”. Specialized loading and extra Python capabilities are deferred. Undo is opportunistic, save cadence remains open because saves can take minutes, and GUI interaction checks should stay inexpensive. Subagent usability trials are authorized once the initial command set works.

The final guide/integration task gates this milestone; its dependencies cover all eight implementation parts.

## Done when

A fresh workspace discovers the guide through `binja --help` and `binja skill`, starts the pinned Personal build, discovers its API, opens a copied sample, queries/modifies an explicitly selected view, saves/reopens the database, and shuts down without silently discarding unsaved work. Independent clients cannot redirect each other's targets. Analysis must be ready unless explicitly overridden. The guide explains the verified workflow and limitations.

All parts below must be completed. Missing desktop-socket access must be recorded as unverified, not treated as a passing desktop test. Investigation scripts are evidence, not an implementation to install wholesale.
