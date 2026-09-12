---
tier: objective
---
# Design the Binary Ninja CLI and in-process bridge

User request: “Let's figure out the CLI/MCP/plugin/API bits.” Prefer a locally maintained CLI borrowing ideas from banteg/bn, rather than depending on its release process. Resolve target identity across stateless commands, whether commands can send Python snippets, discovery of the installed API, and desktop versus private Wayland display modes. Determine whether MCP adds enough value to include. Look for an update-availability API that can inform the model without installing updates.

Accepted context: use requireFile for the paid archive; packaging implementation is discretionary. State may be selected through configuration/environment instead of a mandatory repeated flag. Python runs inside the GUI process. This issue covers interface investigation and a concrete proposal, not full implementation.

Closed: Recorded the CLI/plugin/API proposal and supporting source observations in docs/log.md, including explicit target selection, source execution, docs discovery, two Wayland modes, and update metadata. Commands remain proposed.
