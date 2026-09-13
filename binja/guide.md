# binja

Use binja for static analysis in a persistent Binary Ninja Personal GUI. Scripts
execute in its bundled interpreter; the external CLI does not import Binary Ninja.

Start with a workspace state directory and a binary or existing BNDB:

```sh
export BINJA_STATE_DIR="$PWD/.binja"
binja start                    # default license: ~/.binaryninja/license.dat
binja open ./sample
binja status
binja targets
binja py <<'PY'
result = [(f.name, hex(f.start)) for f in bv.functions][:20]
PY
binja py -c 'bv.set_comment_at(bv.entry_point, "Reviewed entry point")'
binja save ./analysis.bndb
binja stop
binja start
binja open ./analysis.bndb
binja py -c 'result = bv.get_comment_at(bv.entry_point)'
binja stop
```

`--state-dir PATH` overrides BINJA_STATE_DIR. No automatic instance discovery.
`start --license PATH` supplies a runtime license; it never enters the Nix store.
The MVP uses a private Wayland compositor. Desktop/VNC and per-view close are
deferred. `start` reuses the selected owned session. Restart after package upgrades.

Choose the intended view. With one analyzed view, omission is convenient. With
multiple files, pass `--target HANDLE` from `targets`, or a unique filename/path:

```sh
binja open ./second-sample
binja --target ./sample py -c 'result = bv.file.filename'
binja py --target GENERATION:v1 --file inspect.py --args '{"limit": 10}'
```

Handles are specific to a GUI lifetime and expire on close/reopen or restart.
Paths change when saving a binary as a database; the live handle stays the same.
Redundant Raw views do not interfere with inference; select their handles explicitly
when needed. `--target active` deliberately samples GUI focus once. Each accepted
request retains its view, including while queued; other clients and tab changes
cannot redirect it. There is no shared selected target.

Look up unfamiliar API calls before guessing:

```sh
binja api search 'call site'
binja api show BinaryView.get_functions_containing
binja api paths
```

Search/show read the pinned 6.0.10601 Python declarations and docstrings. `api paths`
locates matching Sphinx documentation and source. These commands, `--help`, and
`skill` work without a session or license. Use fully qualified symbols to resolve
ambiguity. Static lookup does not enumerate inherited members or native UI classes;
inspect the packaged documentation directly for those.

Python accepts stdin, `-c CODE`, or `--file PATH`. Each request gets fresh globals:
`bn`, `bv`, `args`, `result`, and `on_ui(callable)`. Assign JSON-compatible values
to `result`; convert API objects into the fields you need. Integer addresses retain
their exact values in JSON; use `hex()` for readable virtual addresses. File offsets
are different quantities. Stdout/stderr from the script and its synchronous on_ui
callbacks are captured. Newly spawned threads and native Binja logs are not captured.
`py --no-target` explicitly runs a session script with bv=None.

Commands require completed analysis when they execute, even after waiting in the
queue. Analysis on hold produces an error. `--allow-incomplete` deliberately skips
this gate and is recorded in the result. To resume a held target:

```sh
binja py --allow-incomplete -c 'bv.set_analysis_hold(False); bv.update_analysis_and_wait()'
```

Raw views have no analysis pipeline. Edits can trigger analysis: if a script edits
and then reads dependent results, call `bv.update_analysis_and_wait()` between them.
Keep analysis work on the worker; use `on_ui` only for GUI calls.

Save deliberately at meaningful work boundaries and before stopping. `save PATH`
writes a BNDB, requires a destination outside the managed state directory, and
updates that database on subsequent saves. An existing unrelated destination is
refused. `targets --json` reports both modification flags and the last save observed
by this session (null means unknown). `stop` refuses pending work and unsaved changes;
`stop --force` explicitly terminates the owned GUI and discards unsaved work.

Recover slow requests instead of repeating mutations:

```sh
binja py --target GENERATION:v1 --file slow_script.py --no-wait --json
binja requests
binja request GENERATION:rREQUEST_ID --wait 30
binja cancel GENERATION:rQUEUED_ID
```

The client prints an ID to stderr before submitting. With `--json`, this receipt is
a JSON object on stderr; stdout holds one JSON result. `--no-wait` returns submission
status immediately. The normal wait is 30 seconds; a wait timeout exits 2 and leaves
execution running. Retrieve its ID with `request`. Errors exit 1. Status and request
inspection remain available during worker execution.

After a disconnect, inspect the printed ID. Unknown does not establish whether a
mutation executed. Duplicate `--request-id` submissions with exactly the same source,
filename, target, and arguments return the original request; conflicting reuse fails.
Never automatically repeat a mutation. Cancel affects queued requests and pre-script
readiness waits only; running Python/native work cannot safely be interrupted.

Results and artifacts last for the newest 64 finished requests in the current GUI
lifetime. Each stream retains up to 1 MiB (with an explicit truncation flag), and JSON
results up to 8 MiB; values over 16 KiB are returned through artifact paths. Copy
artifacts elsewhere if needed. Restart removes managed request artifacts. Deduplication
records remain for up to 4096 IDs; then save and restart before further submissions.
Expired IDs cannot execute again. Earlier-generation outcomes are unknown/interrupted.

Scripts are arbitrary Python with the user's filesystem access. Fresh globals are
not a sandbox or transaction. Python errors, serialization errors, timeouts, and
forced stops do not roll back edits or external writes. Request recovery does not
recover unsaved changes after a GUI crash. Only deliberate successful database saves
provide persistence. Logs are under STATE/logs.
