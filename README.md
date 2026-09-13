# Headless Binary Ninja

A locally maintained CLI for Binary Ninja, using a managed GUI on desktop
Wayland or a private compositor. Commands run Python inside the GUI against
explicit BinaryViews; the initial interface does not use MCP.

The intended agent entry point is `binja --help`, followed by `binja skill` for
an on-demand workflow guide. Static analysis is the initial scope, and commands
will wait for completed analysis unless explicitly told otherwise.

Implementation is pending. Read [the design](docs/design.md), then run
`deeds ready`. The MVP graph is available with `deeds show r2neck --tree`: private
session startup, targeted Python, API lookup, save/reopen, and initial agent trials.
Convenience commands and display extras follow those trials; `deeds list` includes
that remaining work.

[The investigation log](docs/log.md) contains the tested behavior of the supplied
6.0.10601 Personal distribution and the reference projects.
