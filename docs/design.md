# Binary Ninja for agents

## Scope

Provide a locally maintained `binja` CLI that controls a persistent Binary Ninja
GUI process. Support Personal licenses, desktop Wayland, and a private compositor.
Make the installed Python API discoverable and executable without requiring the
model to know its current API surface from memory.

Scope this interface to static analysis. Live debugging belongs to other tools.
For unusual inputs such as a dumped Windows executable from Proton, defer loader
preparation to image formats, preprocessing, the Python API, or manual GUI work
that produces a prepared BNDB. Do not build a specialized loading workflow yet.

This document defines the intended interface. Command examples are not installed
commands yet. Deeds milestone `r2neck` defines a smaller usable MVP and initial
agent trials; its task graph is authoritative for delivery order. The MVP uses
private Wayland, targeted Python, minimal API search/show, and explicit database
save/reopen with request recovery. Help and the packaged guide grow alongside
implementation. Convenience subcommands, richer API lookup, desktop/visual access,
and update notices follow the first trials. The completion criteria below describe
the broader interface, not prerequisites for starting usability tests. Behavioral
evidence and reference revisions are in [the investigation log](log.md).

## Architecture and ownership

| Component | Owns |
| --- | --- |
| Nix package | Distribution, dependencies, CLI, plugin, and reference documentation |
| CLI | Instance discovery, arguments, submitted scripts, and output formatting |
| Resident GUI plugin | RPC, target identity, execution scheduling, and request results |
| Binary Ninja | Live BinaryViews, analysis, edits, and database serialization |
| CLI-distributed guide | Workflow, API lookup, and corrections learned from actual mistakes |

Use Python for the CLI, plugin, and command scripts. Start with a standard-library
JSON protocol over a filesystem Unix socket inside the selected state directory.
The external CLI never imports `binaryninja` or transfers Python object proxies.
Only source text, arguments, and serialized results cross the process boundary;
analysis scripts run in the distribution's bundled interpreter.

Borrow selected ideas and code from banteg/bn, especially target enumeration and
compact output. Maintain the implementation here and retain applicable license
notices. That project's installation/update machinery is not a
runtime dependency. The initial interface has no MCP server. A future adapter
would use this same client/execution boundary if a concrete client requirement
justifies it.

## Distribution and upgrades

Use `requireFile` for the private Personal ZIP, pinned by version and flat hash.
The user supplies the file to the local Nix store; download credentials and license
data never enter derivations. Pin public dependencies normally and keep the paid
runtime closure out of public caches.

Start with `buildFHSEnv`, keeping the vendor directory layout intact and the
installation immutable in the store. An FHS composition already launched the
supplied 6.0 build when libcurl was added to the old reference environment. Use
the bundled Python and Qt libraries and declared runtime dependencies; avoid
global Python installation, user-site package installation, and ambient library
search paths. The CLI's separate Nix Python environment needs no Binja libraries.

Start scripts with the bundled API and standard library. Add third-party Python
dependencies only when a concrete workflow needs them, through the composition
with the GUI interpreter in mind. No general dependency manager is needed now.

Package upgrades are explicit changes to the version/hash and matching API/plugin
inputs. Disable automatic download/installation. Probe the separate update-check
and auto-update controls rather than assuming they are equivalent.

An optional cached metadata check reports installed/latest stable versions, the
check time, and unknown/error status. Expose this through startup/status so the
model can relay an available update. Network failure must not delay or prevent
analysis, and a metadata check must not invoke download/install functions. Do not
equate an update awaiting installation with an available release.

## State and session lifecycle

Resolve the state directory from `--state-dir`, then `BINJA_STATE_DIR`. A workspace
can supply the environment variable through its existing environment setup. If
neither is provided, give an actionable error rather than attaching to an arbitrary
process. Relative paths are resolved by the CLI before contacting the application.

```text
<state>/
  bn/                    settings, managed plugins, runtime license link
  config/ cache/ data/   XDG application state
  runtime/
    rpc.sock             private RPC endpoint
    instance.json        process generation and discovery metadata
    lock                 exclusive session ownership
    ...                  private Wayland/VNC sockets when used
  tmp/ logs/ artifacts/
```

Create the state directory and socket directory with owner-only access. Reject
duplicate ownership and overlong Unix socket paths clearly. Do not unlink a live
socket or terminate a process merely because a stale PID file names it. Identify
each GUI lifetime with a fresh generation ID and verify discovery metadata against
the live endpoint.

Set `BN_USER_DIRECTORY`, XDG config/cache/data/runtime paths, and `TMPDIR` for child
processes. `BN_USER_DIRECTORY` alone does not isolate Qt configuration. Inject the
license at runtime from an explicit path, optionally defaulting to the user's
existing license dotfile. Load only the managed plugin set from the selected
application state. Disable the welcome wizard and unrelated network startup work.

The launcher owns startup, readiness, logs, and cleanup. Force a new GUI process
instead of Binary Ninja's normal forwarding to another running instance. Reusing
an already-running owned session must verify its identity and requested mode.
Normal stop must not silently discard unsaved analysis; forced termination is an
explicit recovery action. Save databases to explicit paths outside process scratch.

This is reproducible dependency and application-state management. The FHS wrapper
does not restrict filesystem access by the application or submitted Python.

## Display modes

```sh
binja start --state-dir temp/binja --display desktop
binja start --state-dir temp/binja --display headless
```

Desktop mode connects to the supplied desktop Wayland socket. Capture its resolved
path before redirecting `XDG_RUNTIME_DIR`; account for container socket access.
Private mode starts labwc with a headless backend and software rendering as needed.
Both select Qt's native Wayland platform explicitly.

Private sessions can expose wayvnc over a Unix socket under the same state directory
for human viewing/input. Screenshot capture is a secondary inspection path. A
deliberate UI navigation command can focus a particular target/address for the
human. Display choice is made at startup; moving a live process between compositors
is outside the initial scope. Connecting to an arbitrary pre-existing unmanaged
GUI is also outside this first lifecycle implementation.

Where the API makes it straightforward, report modal dialogs or other interaction
requirements through status and command errors. Do not automatically click through
them. Keep this to inexpensive checks; screenshot/VNC access remains the fallback,
and the absence of a detected dialog is not proof that the GUI is unblocked.

## Targets

`binja targets` returns live view handles, full paths, view types, and GUI focus.
Handles include or are checked against the process generation and are not reused
after a view is closed. A handle becomes invalid after restart or close/reopen.

For analysis commands:

- Resolve and retain one BinaryView at the start of the request.
- Infer the target when exactly one eligible view exists. Ignore a redundant Raw
  view for this inference when an analyzed view for the same file is open.
- Require `--target` when several eligible views exist. Accept a handle or an
  unambiguous filename/path; ambiguous names fail instead of choosing a match.
- Allow `--target active` as an explicit request to sample GUI focus once.
- Do not maintain a process-wide selected target or implement a shared `use` command.

Keep target provenance visible in results. Switching tabs never redirects an
in-flight request. Retaining a view does not freeze ongoing analysis or a human's
edits; expose analysis state when relevant. Closing through the CLI must coordinate
with queued/running operations, and already-closed targets must fail cleanly.

## Analysis readiness and addresses

Default to operating only once analysis is finished. Opening a file waits for
analysis; target-bound commands, including custom Python, check readiness when
they execute. An explicit per-request option such as `--allow-incomplete` permits
partial analysis and makes that choice visible in results. Do not silently fall
back to partial results when analysis is paused or a client wait expires. Status,
request inspection, and recovery operations remain available while analysis runs.

This is a readiness gate, not a frozen database snapshot. Edits can trigger new
analysis; subsequent requests pass through the same gate. A script that mixes
edits and dependent reads must wait at the relevant points using the API. Keep
waits off the UI thread and expose the waiting request through status.

Start with Binary Ninja's native address and symbol conventions. Preserve familiar
representations and add distinctions where ambiguity appears: identify the view,
distinguish virtual addresses from file offsets, and reject ambiguous symbols.
Keep integer addresses natural inside Python. CLI output must preserve their exact
value and meaning, but a universal address schema is unnecessary for the first
implementation. Refine rendering and input syntax through actual use.

## RPC and Python execution

Keep resident operations small: instance/target discovery, execution submission,
and request status/result retrieval. Version the wire protocol and report a clear
CLI/plugin mismatch. Command-specific analysis logic belongs in scripts shipped
with the CLI, submitted as source plus separate JSON arguments.

Execute each script with fresh locals containing `bn`, `bv`, `args`, and `result`,
and a helper to run UI work on the main thread. Preserve a meaningful source
filename for tracebacks. File/session commands can explicitly execute without a
target; ordinary analysis commands must resolve one.

```sh
binja --target <view-handle> py --file inspect_calls.py
binja --target <view-handle> py <<'PY'
result = [(f.name, hex(f.start)) for f in bv.functions]
PY
```

Fresh locals remove dependence on earlier REPL variables; database edits and
imported module state still persist in the GUI process. There is no general Python
sandbox or automatic transaction around arbitrary scripts.

Use ordinary undo support where easy for editing commands; do not build a general
undo framework or promise rollback for arbitrary Python.

Run scripts on a worker and serialize submitted execution initially. Keep status
requests responsive. Marshal UI access to the main thread and keep long analysis
waits off that thread. Avoid capturing unrelated GUI/plugin output when capturing
script stdout/stderr.

Use request IDs scoped to the GUI lifetime. Retain enough status/result information
to recover after a client disconnect without submitting the script again. Return
the original request for a duplicate ID, or reject conflicting content; never
automatically rerun a submitted mutation after a timeout. Restarted sessions cannot
claim an interrupted script completed or was rolled back.

Cancellation must distinguish queued work from running work and native analysis.
Do not kill a Python thread executing arbitrary native API calls. Use bounded
output capture and artifact files for large results, with a clear retention policy.
Define serialization failures explicitly rather than quietly treating an opaque
Binary Ninja object as a normal structured result.

## CLI and documentation surface

Start with lifecycle (`start`, `status`, `stop`), targets, file/database operations
(`open`, `save`, `close`), Python execution, request inspection, and API lookup.
Add a few frequent reads such as decompilation and xrefs and deliberate UI focus.
Do not reproduce the whole Binary Ninja API as named CLI operations.

Default to compact text for inspection. Offer JSON for composition and explicit
artifact output for large data. Document whether errors or Python exceptions leave
changes behind. Saving means an explicit analysis database destination, not silently
overwriting the input executable. Keep source/target ambiguity and data persistence
legible to both human and model.

Saving can take minutes. Treat a save as an inspectable request whose result can
be retrieved after a client disconnect, and report completion only when saving
succeeds. Expose dirty state and the last successful save observed by this session
where the API permits; an unknown save history must stay unknown. The initial
guide should have agents save at meaningful work boundaries and before orderly
shutdown. Automatic save cadence remains undecided pending real save costs; do
not introduce an interval autosaver or save after every mutation. Request recovery
does not recover unsaved changes after a GUI crash.

```sh
binja api search "call site"
binja api members binaryninja.Function
binja api show binaryninja.BinaryView.get_functions_containing
```

Use the selected installation's bundled Sphinx documentation and Python source.
Return version, signatures/docstrings, and source locations. Ordinary search/show
must work without importing Binary Ninja into the CLI or starting the GUI.
Supplement static documentation with explicit runtime introspection when needed
for extension classes. Do not evaluate every property while listing members.

The agent entry point is an ordinary instruction such as `use binja to open this
binary`. Make `binja --help` point prominently to `binja skill`, which prints a
concise, skill-level guide shipped with the CLI. Both commands must work without
a state directory, license, or running GUI. No separate agent-skill installation
or global MCP configuration is required.

The guide teaches the smallest useful workflow, routes unfamiliar API questions
to these commands, explains readiness and saving, and accumulates observed
mistakes. Keep one packaged source for it, rather than another hand-maintained
API manual. After the initial command set works, use subagents for bounded
usability trials starting from the ordinary instruction and CLI help; refine the
guide, command inventory, and output from observed friction.

## Completion criteria

A fresh workspace can import the paid archive, start a managed Personal GUI, find
the matching API documentation, open a sample, inspect and modify it with Python,
save a database, stop, reopen it, and observe the saved change. Two clients cannot
redirect each other's targets by changing GUI focus or opening another file.
Long work remains inspectable after a client disconnect. Runtime state and RPC
sockets stay under the selected directory, with the license supplied at runtime.

As soon as the first RPC works, verify the installed CLI from a separate agent
workspace can reach the selected socket and locate the packaged API docs. Do not
defer this foundational check to final integration.

Exercise the same analysis interface in private and desktop Wayland modes and
verify optional screenshot/VNC access. If the current environment cannot expose
a desktop socket, record the unverified portion rather than claiming it passed.
The initial release reports update-check uncertainty honestly, documents its
limitations, and includes an on-demand guide and reproducible verification commands.
