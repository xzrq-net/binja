---
blocked-by: [2nbgtk]
tier: objective
---
# Deliver the first managed Binary Ninja CLI workflow

User goal: “package and wrap Binary Ninja for agentic use.” The accepted interface is a locally maintained CLI, a small Python receiver inside the Personal-edition GUI, and an RPC socket under the state directory. Borrow from banteg/bn without depending on its release process. Support desktop and private Wayland displays, discover the installed API, and omit MCP initially.

[The design](../docs/design.md) is the implementation contract. Use `deeds ready` and `deeds show r2neck --tree`. Parts are intended as local commit boundaries; agents commit and finish completed jj changes with `jj new`.

The final skill/integration task gates this milestone; its dependencies cover all eight implementation parts.

## Done when

A fresh workspace starts the pinned Personal build, discovers its API, opens a copied sample, queries/modifies an explicitly selected view, saves/reopens the database, and shuts down without losing acknowledged work. Independent clients cannot redirect each other's targets. The skill explains the verified workflow and limitations.

All parts below must be completed. Missing desktop-socket access must be recorded as unverified, not treated as a passing desktop test. Investigation scripts are evidence, not an implementation to install wholesale.
