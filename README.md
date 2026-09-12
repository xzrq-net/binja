# Headless Binary Ninja

A locally maintained CLI for Binary Ninja, using a managed GUI on desktop
Wayland or a private compositor. Commands run Python inside the GUI against
explicit BinaryViews; the initial interface does not use MCP.

The design is complete and implementation is pending. Read
[the design](docs/design.md), then run `deeds ready`. The full implementation
graph is available with `deeds show r2neck --tree`.

[The investigation log](docs/log.md) contains the tested behavior of the supplied
6.0.10601 Personal distribution and the reference projects.
