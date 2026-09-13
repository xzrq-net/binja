---
tier: objective
---
# Verify Binary Ninja threading contracts and operation concurrency

User request: research whether Binary Ninja admits the plugin's execution model,
whether Python APIs are thread-safe, and whether long GUI operations use modal
dialogs to preserve application consistency. Evaluate a simpler interface where
the CLI can reconnect and wait for at most one ongoing operation.

Check official documentation, the matching installed API source, and relevant
GUI/scripting behavior. Distinguish worker-thread support, UI-thread constraints,
and whole-operation isolation. Report findings before changing the protocol.
Subagent reviews and trials remain gated.

Closed: Checked matching installed API source, official threading/UI documentation, and an isolated modal/background-task probe. Recommended one active operation with reconnect/wait; no protocol changes or subagent trials.
