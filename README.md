# Headless Binary Ninja

A locally maintained CLI for Binary Ninja, using a managed GUI on desktop
Wayland or a private compositor. Commands run Python inside the GUI against
explicit BinaryViews; the initial interface does not use MCP.

The intended agent entry point is `binja --help`, followed by `binja skill` for
an on-demand workflow guide. Static analysis is the initial scope, and commands
will wait for completed analysis unless explicitly told otherwise.

Import the licensed archive, then build the CLI (x86_64 Linux with Nix):

```sh
nix-store --add-fixed sha256 ~/temp/binaryninja_linux_6.0.10601_personal.zip
nix build
./result/bin/binja --help
./result/bin/binja skill
```

The archive is pinned to 6.0.10601. Its vendor tree is immutable; the separate
`binja-runtime` FHS launcher preserves bundled Python and Qt. Supply the license
at runtime. Do not publish the paid runtime closure to public binary caches.

Session commands are under implementation. Read [the design](docs/design.md), then run
`deeds ready`. The MVP graph is available with `deeds show r2neck --tree`: private
session startup, targeted Python, API lookup, save/reopen, and initial agent trials.
Convenience commands and display extras follow those trials; `deeds list` includes
that remaining work.

[The investigation log](docs/log.md) contains the tested behavior of the supplied
6.0.10601 Personal distribution and the reference projects.
