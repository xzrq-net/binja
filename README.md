# Headless Binary Ninja

`binja` is a CLI for agent-driven static analysis with Binary Ninja Personal.
It manages a persistent GUI on a private Wayland compositor, viewable over VNC
or optionally shown on your desktop, and provides typed
analysis commands with Python as the backstop. It includes API lookup, recoverable requests,
and explicit database saves. The client and session supervisor are one Rust
binary; scripts and the resident plugin run in Binary Ninja's bundled Python.

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
binja decompile main
binja il main
binja disasm main
binja comment main "Reviewed entry point"
binja py -c 'result = [f.name for f in bv.functions if f.comment]'
binja save ./analysis.bndb
binja stop
```

Commands use `.binja` in their working directory for session state. Keep the same
working directory across calls, or pass `--state-dir PATH` on each command.
Reopen `analysis.bndb` after starting a new session to continue saved work.
`binja skill` prints the full workflow, including multiple targets, API lookup,
and recovery after a client timeout. It works without a session or license.
Human output is concise; `--verbose` includes the full record and `--json` returns
it directly. Artifact files survive until session shutdown or a new lifetime starts.
Copy results you need to keep before stopping.

`decompile`, `il`, and `disasm` render the GUI's own listings in bounded pages;
functions resolve by exact name or address, and ambiguity is an error rather
than a guess.

To watch or drive the private GUI yourself, connect a VNC viewer to the Unix
socket printed by `binja start` and `binja status`, with no password (the state
directory is owner-only):

```sh
vncviewer .binja/runtime/vnc.sock   # TigerVNC
```

`binja start --display desktop` shows the GUI on your own Wayland display
instead. That mode has no `screenshot` or `input` commands; the display is
fixed until `binja stop`.

## Development

Build and run the live checks from the checkout:

```sh
nix build
python3 tests/smoke.py --binja ./result/bin/binja --sample /path/to/small/ELF
python3 tests/bridge.py --package "$(readlink -f result)" --sample /path/to/small/ELF
python3 tests/startup.py --binja ./result/bin/binja
```

The checks require a Personal license (`smoke.py --offline` runs only the help
and API lookup phases and needs neither license nor sample). They copy the sample into a temporary
workspace, analyze it without executing it, and verify targeting, request recovery,
save/reopen, and shutdown behavior.
`startup.py` takes about three minutes to check startup-modal deadlines, recovery
through compositor input, and cleanup when children exit before readiness.

`nix develop` provides cargo, rustc, Python for checks, and the packaged CLI.
Dependencies are locked in `Cargo.lock`; Nix consumes it directly. To run the
Rust client with the checkout's plugin and guide during development:

```sh
nix build
cp result/lib/binja/{build.json,api-index.json} binja/
cargo run -- --help
cargo run -- api show Function.name
```

Those generated files are ignored by version control. Refresh them after package
changes. Installed binaries locate resources relative to themselves; development
builds use `binja/` in the source checkout. `BINJA_RESOURCE_DIR` can select another
resource directory explicitly. Restart sessions after changing the plugin.
`cargo test` checks the Rust client; the other `tests/*.py` scripts check Python
helpers without a GUI.

See [the design](docs/design.md) for architecture and interface constraints.
`deeds ready` lists pending work; [the investigation log](docs/log.md) records
runtime observations and verification history.
