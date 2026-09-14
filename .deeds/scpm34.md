---
tier: objective
---
# Add rudimentary screenshot and input commands for stuck GUI states

User's words: "I don't trust binary ninja UI not to block the agent for some
stupid reason. I'd like rudimentary screenshot + input abilities just to cover
some long-tail condition wasting my time."

Scope is the long tail, not GUI automation: a modal dialog, an update prompt, a
license or crash-report window that leaves the worker idle.

- `screenshot [PATH]`: capture the private compositor's output to a PNG
  artifact (default under the session's artifacts/) and print the path. Check
  whether wlr-screencopy or grim works on headless labwc with the software
  backend; otherwise use Qt's `QScreen.grabWindow` through `on_ui`.
- `input`: minimal keyboard and pointer injection, enough to dismiss a dialog:
  key presses (Escape, Return, Tab) and a click at coordinates. Prefer a
  compositor-level path (wlr virtual keyboard/pointer, wtype, ydotool) over Qt
  test hooks, since a native modal is what we expect to be stuck on.
- `status` should say when the GUI has a modal window open if Qt exposes that
  cheaply (`QApplication.activeModalWidget()` through `on_ui`); unknown state
  stays explicit. No automatic clicking.

Keep it small: no window enumeration, no focus or navigation commands, no
coordinate discovery beyond the screenshot itself. Coordinate with an2dc3
(desktop Wayland and wayvnc) but do not block on it; the headless session is
where the agent gets stuck.

Verify by provoking a modal (an `on_ui` call that opens a message box) and
clearing it from the CLI.
