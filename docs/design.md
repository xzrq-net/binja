# Binary Ninja for agents

## Scope

`binja` provides static analysis through a persistent Binary Ninja Personal GUI.
The CLI submits Python to that process and exposes the matching API documentation,
so an agent can look up and execute unfamiliar operations. Live debugging and
specialized loader preparation are outside this interface.

[README](../README.md) covers installation; `binja skill` is the installed workflow
reference. This document describes architecture and interface constraints.
Planned extensions and delivery order live in deeds. [The investigation log](log.md)
records experiments and their results.

## Architecture and ownership

| Component | Owns |
| --- | --- |
| Nix package | Runtime distribution, dependencies, CLI, plugin, and API documentation |
| CLI | Session selection, arguments, submitted scripts, and output formatting |
| Session supervisor | Process ownership, private compositor, readiness, and cleanup |
| Resident GUI plugin | RPC, target identity, execution scheduling, and request results |
| Binary Ninja | Live BinaryViews, analysis, edits, and database serialization |
| Packaged guide | Workflow and API lookup instructions |

The CLI and plugin use a versioned JSON protocol over a filesystem Unix socket.
The external CLI never imports `binaryninja`: source text, arguments, and serialized
results cross the process boundary. Scripts run in the distribution's bundled
interpreter. There is no transfer of Python object proxies.

Target enumeration and UI dispatch adapt code from banteg/bn, with its license
notice retained in `licenses/`. The CLI requires no MCP server or separate
agent-skill installation.

## Distribution and upgrades

The Nix package uses `requireFile` for the Personal ZIP, pinned by version and flat
hash. The user imports the archive into the local store. Credentials and license
data stay out of derivations; the paid runtime stays out of public caches.

An FHS launcher preserves the immutable vendor tree, bundled Python, and Qt.
Dependencies are declared in the package; the launcher removes ambient Python and
library search paths and disables Python user-site loading. The CLI uses a separate
Nix Python environment. Additional script dependencies belong in the package when
a concrete workflow needs them.

Upgrades change the archive pin and rebuild the CLI/plugin and matching API index
together. Automatic update downloads and installation are disabled. Running
sessions must be restarted after package upgrades. Optional update notices are
tracked in deeds.

## State and session lifecycle

Commands resolve `--state-dir PATH`, defaulting to `.binja` in the command's current
working directory. Selection needs no shell environment setup and never searches
parent directories or arbitrary processes. Commands from another directory must
name the same state path to use that session. Relative CLI paths are resolved
before contacting the application.

```text
<state>/
  bn/                    settings, managed startup plugin, runtime license link
  config/ cache/ data/    XDG application state
  runtime/
    rpc.sock             GUI endpoint
    control.sock         supervisor endpoint
    instance.json        generation and discovery metadata
    lock                 exclusive session ownership
    wayland-0            private compositor socket
  tmp/ logs/ artifacts/
```

State directories and sockets have owner-only access. An exclusive lock owns the
session; discovery files alone are never authority to terminate a process or unlink
a live socket. Each GUI lifetime gets a new generation ID, verified by both RPC
endpoints. Overlong Unix socket paths produce an error requiring a shorter state
path. `start` reuses an owned session after checking its live identity and version.

The supervisor sets `BN_USER_DIRECTORY`, XDG config/cache/data/runtime paths, and
`TMPDIR` for children. It links a runtime license, loads the managed startup plugin,
disables the welcome wizard and unrelated network startup work, and forces a fresh
GUI process rather than forwarding to another instance. The supervisor retains
child process objects for shutdown and cleanup.

This isolates application state, not filesystem access. Arbitrary Python runs
with the user's access and can change process state. Its working directory is
initially inherited from session startup; scripts should use absolute file paths.

Normal stop refuses outstanding requests and unsaved changes. Forced stop
explicitly discards work. BNDB files are saved to explicit destinations outside
managed state. A restart retires request artifacts and does not restore views or
unsaved analysis.

## Display modes

Sessions use a private labwc compositor with a headless backend and software
rendering. Qt selects native Wayland. Desktop Wayland and optional wayvnc access
are planned in deeds; display choice remains a startup property. Attaching to an
unmanaged GUI or moving a live process between compositors is outside scope.

## Targets and readiness

Targets expose a generation-scoped handle, path, view type, focus, analysis state,
modification flags, and the last successful save observed by this session. Handles
are not reused after a view closes and expire on restart. Saving may change a
view's path while retaining its live handle.

Each accepted target-bound request resolves and retains one BinaryView. Commands
infer a target only when exactly one eligible view exists, ignoring redundant Raw
views for an analyzed file. Otherwise they require a handle or unambiguous
filename/path. `--target active` samples focus once. There is no shared selected
target, and subsequent focus changes cannot redirect queued or running work.

Retaining a view does not freeze analysis or prevent GUI edits. Commands wait for
completed analysis at execution time and check that the target remains live.
Analysis on hold fails with instructions to resume it. `--allow-incomplete`
explicitly skips readiness and appears in the result. A script that triggers
analysis must wait again before reading dependent results. Raw views have no
analysis pipeline.

Use native virtual addresses in Python and preserve integer precision in output.
Readable addresses can use hexadecimal strings; file offsets must be identified
separately. A universal address schema is unnecessary.

## Execution and recovery

The plugin serializes scripts on one worker. UI calls run on the main thread via
`on_ui`; analysis waits stay on the worker. Status and request inspection remain
available during execution, subject to the GUI being responsive.

Each script receives fresh globals with `bn`, `bv`, `args`, `result`, and `on_ui`.
Session-level scripts explicitly omit a target. The CLI preserves source filenames
for tracebacks and sends arguments separately from source. Database edits and
imported modules persist, but variables defined by earlier requests do not.

Scripts return JSON-compatible values. Output capture is bounded and isolates
script execution and its synchronous UI callbacks. Large output is returned through
artifact paths. Serialization failures are explicit errors; they do not roll back
the script. The guide documents size and retention limits.

Request IDs belong to a GUI lifetime. The client emits IDs before submission
for recovery after a disconnect or timeout. Duplicate IDs return the original
record without replay. Metadata stays for the session; only the newest 64
finished requests retain outputs and artifacts. Older records have
`output_pruned: true`. A restart cannot establish an earlier outcome.

Cancellation can stop queued work or a pre-script analysis wait. It cannot safely
interrupt running Python or native calls. Scripts are neither sandboxed nor
transactional; exceptions and forced stops can leave edits and external writes.

## Database persistence

Saving is an inspectable request that completes only after Binary Ninja reports
success. A save writes a BNDB, never silently overwrites the input executable,
refuses unrelated existing destinations, and keeps the GUI filename in sync.
Unknown save history remains unknown. Both byte modifications and analysis
changes contribute to the shutdown guard.

Save at meaningful work boundaries and before stopping. There is no automatic
save cadence. Request recovery survives a client disconnect; recovering analysis
after a GUI crash requires a successful database save.

## API discovery and documentation

`api search` and `api show` use an index built from the installed distribution's
Python declarations and docstrings. Results include version and source locations;
`api paths` locates bundled source and Sphinx documentation. Static lookup requires
no GUI, license, or Binary Ninja imports in the CLI. Inherited members and native
UI classes may require direct documentation inspection.

`--help` points to `binja skill`, which prints a single packaged guide. The guide
teaches working commands, target selection, API lookup, readiness, saving, and
failure recovery. Extend it from observed usage friction; avoid duplicating API
documentation or including development status in the installed instructions.
