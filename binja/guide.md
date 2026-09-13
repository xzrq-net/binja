# binja

Use binja for static analysis with Binary Ninja Personal. Run commands from the
analysis workspace. A GUI session persists between commands; each Python request
executes in its bundled interpreter.

```sh
binja start
binja open ./sample
binja py <<'PY'
result = [(f.name, hex(f.start)) for f in bv.functions][:20]
PY
binja py -c 'bv.set_comment_at(bv.entry_point, "Reviewed entry point")'
binja save ./analysis.bndb
binja stop
```

## Sessions

Commands use `.binja` in their working directory for session state. Set your shell
tool's working directory consistently across calls. To use a session from another
directory, pass `--state-dir /absolute/path/to/.binja` on each command. Selection is
by this path; binja does not search parent directories or other running instances.
`status` reports the resolved path, live views, and pending requests.

`start` starts or reuses that session on a private Wayland compositor. The default
license is `~/.binaryninja/license.dat`; `start --license PATH` selects another.
Restart sessions after upgrading the package. Logs are in the session's `logs/`
directory. Keep session state out of version control.

`open` accepts a binary or existing BNDB. Save at meaningful work boundaries and
before stopping. `save PATH.bndb` requires a destination outside session state;
it updates that database on subsequent saves and refuses to overwrite an unrelated
file. `targets --json` includes modification flags and the last save observed by
this session (`null` means unknown). `stop` refuses pending work and unsaved changes;
`stop --force` terminates the session and discards unsaved work.

After a restart, use `open ./analysis.bndb` to continue saved analysis. Open tabs,
unsaved edits, request results, and Python state are not restored.

## Targets

With one eligible view, commands infer the target. With multiple files, use
`--target` with a handle from `targets`, or a unique filename/path:

```sh
binja targets
binja --target ./sample py -c 'result = bv.file.filename'
binja py --target ./sample --file inspect.py --args '{"limit": 10}'
```

Use the returned handle to keep addressing a view after saving changes its path.
Handles expire when the view closes or the session restarts. Redundant Raw views
do not affect inference; select their handles explicitly when needed.
`--target active` samples GUI focus once. Each accepted request retains its target
while queued and running; other clients and tab changes cannot redirect it.

## Python and API lookup

Look up unfamiliar API calls before guessing:

```sh
binja api search 'call site'
binja api show BinaryView.get_functions_containing
binja api paths
```

Search/show read the installed distribution's Python declarations and docstrings.
`api paths` locates the matching source and Sphinx documentation. These commands,
`--help`, and `skill` need no running session or license. Use qualified symbols to
resolve ambiguity. Static lookup does not enumerate inherited members or native
UI classes; inspect the packaged documentation for those.

`py` accepts stdin, `-c CODE`, or `--file PATH`. Each request gets fresh globals:
`bn`, `bv`, `args`, `result`, and `on_ui(callable)`. Assign JSON-compatible values to
`result`; convert API objects into the fields you need. Use `hex()` for readable
virtual addresses. Integer addresses remain exact in JSON; file offsets are
different quantities. `py --no-target` runs with `bv=None` for session-level work.

The CLI reads `--file` locally, but executes its contents in the GUI process.
Use absolute paths for file access inside scripts: its working directory starts
as the directory where the session was launched, and its imports use the bundled
interpreter. Variables from earlier requests are unavailable; imports and database
edits persist. Stdout/stderr capture includes synchronous `on_ui` callbacks, but
excludes spawned threads and native Binary Ninja logs.

Target-bound commands wait for completed analysis when they execute.
`--allow-incomplete` skips this check and is recorded in the result. Analysis on
hold produces an error; resume it explicitly:

```sh
binja py --allow-incomplete -c 'bv.set_analysis_hold(False); bv.update_analysis_and_wait()'
```

If a script edits and then reads dependent results, call
`bv.update_analysis_and_wait()` between them. Keep analysis work on the worker;
use `on_ui` only for GUI calls. Raw views have no analysis pipeline.

## Request recovery

Python, open, and save commands print a request ID to stderr before submitting.
They normally wait up to 30 seconds. A timeout exits 2 and leaves execution
running; retrieve the existing request instead of repeating it:

```sh
binja py --file slow_script.py --no-wait
binja requests
binja request REQUEST_ID --wait 30
binja cancel QUEUED_REQUEST_ID
```

Replace the placeholders with returned IDs. `--no-wait` returns submission status
immediately. `--json` puts one JSON result on stdout and a JSON submission receipt
on stderr. Failed, cancelled, or expired requests exit 1. Status and request
inspection remain available during worker execution.

After a disconnect, inspect the printed ID. An unknown ID does not prove the script
never ran. Reusing `--request-id` with exactly the same submission returns the
original request; conflicting reuse fails. Do not automatically repeat mutations.
Cancellation applies to queued requests and pre-script analysis waits; running
Python/native work cannot safely be interrupted.

The newest 64 finished requests retain results and artifacts until the session
ends. Each output stream retains up to 1 MiB, with a truncation flag; JSON results
have an 8 MiB limit. Outputs above 16 KiB are returned as artifact paths. Read those
files to consume the output, and copy them elsewhere to retain them. Deduplication
records survive result expiry. A session accepts at most 4096 distinct execution
requests, including saves; save periodically and restart before reaching that limit.

Scripts have the user's filesystem access. Errors, timeouts, and forced stops do
not roll back edits or external writes. Request recovery works within the running
GUI; recovering analysis after a crash requires a successful database save.
