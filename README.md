# Headless Binary Ninja

A locally maintained CLI for Binary Ninja Personal, using a managed GUI on a
private Wayland compositor. Commands run Python inside the GUI against explicit
BinaryViews. The MVP covers static analysis, request recovery, API lookup, and
deliberate database saves.

Start with `binja --help`, then `binja skill` for the packaged workflow guide.
Commands wait for completed analysis unless explicitly told otherwise.

Import the licensed archive, then build the CLI (x86_64 Linux with Nix):

```sh
nix-store --add-fixed sha256 ~/temp/binaryninja_linux_6.0.10601_personal.zip
nix build
./result/bin/binja --help
./result/bin/binja skill
# Optional persistent installation:
nix profile install .
```

The archive is pinned to 6.0.10601. Its vendor tree is immutable; the separate
`binja-runtime` FHS launcher preserves bundled Python and Qt. Supply the license
at runtime. Do not publish the paid runtime closure to public binary caches.

For a first session, put the built CLI on PATH and copy a benign sample into a
workspace. The default runtime license is `~/.binaryninja/license.dat`; override
it with `start --license PATH`.

```sh
export PATH="$PWD/result/bin:$PATH"
mkdir -p temp/try
cd temp/try
cp --dereference /usr/bin/env ./sample
export BINJA_STATE_DIR="$PWD/state"
binja start
binja api show BinaryView.get_functions_containing
binja open ./sample
binja py -c 'result = [(f.name, hex(f.start)) for f in bv.functions][:10]'
binja py -c 'bv.set_comment_at(bv.entry_point, "Reviewed entry point")'
binja save ./analysis.bndb
binja stop
binja start
binja open ./analysis.bndb
binja py -c 'result = bv.get_comment_at(bv.entry_point)'
binja stop
```

Open multiple files and use `--target` with a handle from `binja targets` or an
unambiguous filename/path. Each request keeps its intended view even if GUI focus
or another client changes. `--json` provides structured output.

Long commands print a request ID before submitting. `--no-wait` submits without
waiting; `binja request ID --wait 30` retrieves the same execution. A client timeout
does not cancel or roll back a script. `stop` refuses pending work and unsaved
changes; `stop --force` deliberately discards them. Save databases outside the
managed state directory. The guide explains retention limits and failure behavior.

Run the live checks against an installed CLI and a small benign ELF:

```sh
python3 tests/smoke.py --binja ./result/bin/binja --sample /path/to/sample
```

The checks copy inputs into another workspace and never execute them. They cover
targeting, readiness, request recovery, bounded results, GUI close/reopen, saving,
restart persistence, and shutdown guards. A Personal license is required.

The MVP is ready for the operator's UX check. Subagent reviews and usability trials
are pending that checkpoint. Desktop/VNC, per-view close, decompile/xref convenience
commands, richer API lookup, and update notices remain deferred. Large-binary save
performance and recovery from native crashes have not been characterized.

[The design](docs/design.md) describes the broader interface; `deeds ready` and
`deeds show r2neck --tree` track the remaining review/trial gate and follow-ups.

[The investigation log](docs/log.md) contains the tested behavior of the supplied
6.0.10601 Personal distribution and the reference projects.
