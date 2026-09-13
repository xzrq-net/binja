# Headless Binary Ninja

`binja` is a CLI for agent-driven static analysis with Binary Ninja Personal.
It manages a persistent GUI on a private Wayland compositor and runs Python
against its open BinaryViews. It includes API lookup, recoverable requests,
and explicit database saves.

## Install

Requires x86_64 Linux, Nix with flakes enabled, and a Binary Ninja Personal license.
From this checkout, import the licensed archive and install the CLI:

```sh
nix-store --add-fixed sha256 /path/to/binaryninja_linux_6.0.10601_personal.zip
nix profile install .
binja --help
```

The package pins the archive and bundles its matching Python API documentation.
The license is supplied at runtime, defaulting to `~/.binaryninja/license.dat`;
use `binja start --license PATH` to select another file. Keep the paid runtime
out of public binary caches.

## Use

Run commands from your analysis workspace, with a binary named `sample`:

```sh
binja start
binja open ./sample
binja py -c 'result = [(f.name, hex(f.start)) for f in bv.functions][:10]'
binja py -c 'bv.set_comment_at(bv.entry_point, "Reviewed entry point")'
binja save ./analysis.bndb
binja stop
```

Commands use `.binja` in their working directory for session state. Keep the same
working directory across calls, or pass `--state-dir PATH` on each command.
Reopen `analysis.bndb` after starting a new session to continue saved work.
`binja skill` prints the full workflow, including multiple targets, API lookup,
and recovery after a client timeout. It works without a session or license.

## Development

Build and run the live checks from the checkout:

```sh
nix build
python3 tests/smoke.py --binja ./result/bin/binja --sample /path/to/small/ELF
```

The checks require a Personal license. They copy the sample into a temporary
workspace, analyze it without executing it, and verify targeting, request recovery,
save/reopen, and shutdown behavior.

See [the design](docs/design.md) for architecture and interface constraints.
`deeds ready` lists pending work; [the investigation log](docs/log.md) records
runtime observations and verification history.
