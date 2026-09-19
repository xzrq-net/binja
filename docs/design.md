# Binary Ninja for agents

## Scope

`binja` provides static analysis through a persistent Binary Ninja Personal GUI.
The CLI provides typed analysis commands with Python as the backstop, plus matching
API documentation for looking up unfamiliar operations. Live debugging and
specialized loader preparation are outside this interface.

[README](../README.md) covers installation; `binja skill` is the installed workflow
reference. This document describes architecture and interface constraints.
Planned extensions and delivery order live in deeds. [The investigation log](log.md)
records experiments and their results.

## Architecture and ownership

| Component | Owns |
| --- | --- |
| Nix package | Runtime distribution, dependencies, CLI, plugin, and API documentation |
| CLI | Session selection, arguments, submitted scripts, and request presentation |
| Python command scripts | Typed analysis, native text rendering, and structured results |
| Session supervisor | Process ownership, private compositor, readiness, and cleanup |
| Resident GUI plugin | RPC, target identity, execution scheduling, and request results |
| Binary Ninja | Live BinaryViews, analysis, edits, and database serialization |
| Packaged guide | Workflow and API lookup instructions |

The client, plugin, and supervisor use JSON protocol version 3 over filesystem
Unix `SOCK_SEQPACKET` sockets.
The CLI and supervisor are one Rust binary; the supervisor runs as a hidden
subcommand. The resident plugin and executed scripts remain Python inside Binary
Ninja. Source text, arguments, and serialized results cross the process boundary. Scripts run in the distribution's bundled
interpreter. There is no transfer of Python object proxies.

Target enumeration and UI dispatch adapt code from banteg/bn, with its license
notice retained in `licenses/`. The CLI requires no MCP server or separate
agent-skill installation.

## Wire protocol

Each connection carries one operation. Each logical message is one UTF-8 JSON
object split into packets: byte `0x01` followed by 1–32768 bytes of JSON, then a
separate one-byte `0x00` end packet. Chunks may split a UTF-8 character; decode
only after reassembly. EOF is an incomplete message, not a terminator. Reject
unknown/empty data packets, packets larger than 32769 bytes (`MSG_TRUNC`), invalid
JSON, and non-object messages. There is no newline delimiter, multiplexing, or
application retransmission. Receivers enforce a deadline for the whole message.

The serialized request envelope is bounded at 4 MiB; each response envelope at
64 MiB. Bounds exclude packet tag bytes. Sources, including `-c`, stdin, and
locally read files, remain inline snapshots. Large execution outputs still use
artifacts; the larger response bound accommodates forensic history. Oversized
submissions are rejected before admission. A response that exceeds its bound
returns an error without changing the execution outcome.

Requests contain `protocol: 3`, `generation`, `op`, and operation parameters.
`submit` carries `spec` with `id`, `kind` (the submitted operation's name, default
`py`), `source`, `filename`, `args`, `target`, `no_target`, and `allow_incomplete`.
`submit` and `request` accept `wait`, default 0, as finite nonnegative seconds
within the server platform's timeout range. The wait budget starts after
admission/lookup; it is not an end-to-end CLI deadline.

GUI replies contain `protocol`, `generation`, `event`, `final`, and either `data`
or `error`. Submission first returns `event: "accepted"`, the admission snapshot
in `data`, and `existing` to distinguish duplicate recovery from new admission.
With `wait: 0`, that reply has `final: true` and ends the operation. With positive
wait, it has `final: false`; the handler then waits on the worker condition and
returns `event: "result", final: true` at termination or deadline. Other GUI
operations return one final result. `request` waits without an admission event.
A deadline response whose request is still unfinished includes
`client_wait_expired: true` in `data`. The client adds a state-path-preserving
recovery command and uses exit 2. Disconnect does not cancel accepted execution.

All terminal transitions notify condition waiters under the scheduling lock.
Waiting releases that lock and runs on a connection thread, never the UI thread.
Client read deadlines must allow the server's deadline reply to arrive; transport
failure is distinct from normal wait expiry. Nonwaiting handlers retain short
I/O timeouts. Supervisor control operations use the same framing and identity
checks, but return a single `{protocol, generation, data|error}` envelope.

Protocol upgrades require session restart. The Rust client uses blocking sockets
with receive deadlines; after admission it blocks on the result read without a
first-poll sleep. Startup readiness polling is separate from execution waits.
There is no Python client or supervisor entry point.

## Distribution and upgrades

The Nix package uses `requireFile` for the Personal ZIP, pinned by version and flat
hash. The user imports the archive into the local store. Credentials and license
data stay out of derivations; the paid runtime stays out of public caches.

An FHS launcher preserves the immutable vendor tree, bundled Python, and Qt.
Dependencies are declared in the package; the launcher removes ambient Python and
library search paths and disables Python user-site loading. The CLI is built with
`rustPlatform.buildRustPackage` and `Cargo.lock`. Python is needed at build time
for static API indexing and at runtime inside Binary Ninja; the CLI and supervisor
do not require a separate Python environment. Additional script dependencies
belong in the package when a concrete workflow needs them.

The binary resolves plugin resources and build metadata from `../lib/binja`
relative to its executable. Development builds fall back to the checkout's
`binja/` directory; `BINJA_RESOURCE_DIR` explicitly overrides the resource path.
Build metadata names the immutable vendor, FHS launcher, labwc, wayvnc, and
compositor helper paths. The
supervisor injects the selected plugin directory into the GUI's bundled Python.

Upgrades change the archive pin and rebuild the CLI/plugin and matching API index
together. Automatic update downloads and installation are disabled. Running
sessions must be restarted after package upgrades. Start and running-session status
include a stable-release notice from `cache/updates.json`: installed version,
channel, latest stable version, available/current/unknown status, check and expiry
times (Unix seconds), error, and a derived stale flag. Successful checks are reused
for 24 hours; errors for one hour. A session attempts at most one check on startup
when its cache is missing, expired, or for a different installed version. Status
only reads the cache, including when GUI RPC is unavailable.

The receiver queries native `UpdateChannel["release-personal"].latest_version_num`
on a separate daemon thread with automatic updates disabled; the `network.enable*`
settings remain disabled independently. The notice becomes unknown after five
seconds. The native API has no cancellation argument: its outstanding call may
finish later, but cannot publish a late result or trigger another check in that
session. No download/install API is used, and pending installation is not treated
as release availability.

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
    wayland-0            private compositor socket (headless mode)
    vnc.sock, wayvncctl  wayvnc viewer and control sockets (headless mode)
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
child process objects for shutdown and cleanup. Shutdown pins both RPC operations
to the generation returned by the live supervisor handshake. A held flock is the
ownership authority; no PID read from discovery metadata is used for termination.
Shutdown sends SIGTERM to owned groups, escalates after five seconds to SIGKILL,
and confirms group disappearance with killpg(0)/ESRCH before retiring artifacts
or endpoints and releasing the lock. The supervisor is a child subreaper so it
can reap orphan descendants even after their group leader exits. Its main thread
spawns every child with PR_SET_PDEATHSIG/SIGKILL and a parent-identity recheck;
the packaged GUI launcher also uses bubblewrap's die-with-parent behavior.
Concurrent starts, including callers arriving during initialization, wait for
the winning lock owner's receiver and reuse its generation.
The supervisor requires a GUI receiver handshake within 60 seconds unless the
session was launched with `start --no-startup-deadline`. With that flag, it keeps
polling readiness and serving compositor controls until the receiver loads, a
child exits, or shutdown is requested. The CLI's 70-second startup wait remains
bounded; its timeout leaves the session alive with supervisor `ready: false`.
`status` reports no running session with exit 0 when the lock is unheld, without
creating missing state. If a lock is held but the endpoint cannot answer, it
reports a fault. Live status counts files by file ID, separately from views.

This isolates application state, not filesystem access. Arbitrary Python runs
with the user's access and can change process state. Its working directory is
initially inherited from session startup; scripts should use absolute file paths.

Normal stop refuses outstanding requests and unsaved changes. Forced stop
explicitly discards work. BNDB files are saved to explicit destinations outside
managed state. A restart retires request artifacts and does not restore views or
unsaved analysis.

`close HANDLE|PATH [--force]` retires the selected view and all other views of
its file. It retains the selection at admission, refuses queued, running, or parked requests
for any sibling view, and prevents new target requests while close is pending.
`--force` permits discarding unsaved changes; it never overrides pending work.
The packaged close script runs on the existing worker and closes GUI tabs on the
UI thread with the worker paused. The final pending-work check and close share
the admission lock, acquired on the UI thread. No supervisor operation is needed.
Close does not wait for analysis and stays outside the request undo group.

The native tab API has no force argument. During a forced close, a scoped Qt
handler selects Discard on its modified-file prompts; an existing modal prevents
close. A view is live only while its file has an attached GUI tab, even if Qt's
deferred deletion or retained requests keep the file context alive. Removing the
tabs expires all sibling handles immediately; execution revalidation rejects
queued requests whose handles expired after admission. Later handle lookups also
report expiry with guidance to list targets or reopen. Bare `bv.file.close()` in
Python bypasses the managed checks and GUI retirement.

## Display modes

`start --display headless` (the default) runs a private labwc compositor with a
headless backend and software rendering, plus wayvnc listening on the Unix
socket `runtime/vnc.sock` with no VNC authentication: the owner-only runtime
directory is the access control. wayvnc renders the cursor into the stream and
keeps its control socket at `runtime/wayvncctl`. Both helpers are owned children
started in order, each awaited by its socket; a wayvnc exit is logged, reported
as a null `vnc_socket`, and does not end the session, while any other child exit
does. `start --display desktop` connects the GUI to the caller's compositor
instead: the CLI resolves `WAYLAND_DISPLAY` against `XDG_RUNTIME_DIR` to an
absolute socket path, checks it is a socket, and the supervisor passes that path
as `WAYLAND_DISPLAY` while still redirecting XDG runtime state. Absolute paths
also serve containers that bind-mount a host socket. Both modes force native Qt
Wayland with `DISPLAY` removed; there is no X11 fallback. Display choice is a
startup property recorded in session metadata; reusing a session with the other
mode is an error. Attaching to an unmanaged GUI or moving a live process between
compositors is outside scope.

`screenshot` and `input` drive only the private compositor and fail explicitly
in desktop mode, where the human is already at the display. `screenshot [PATH]`
captures that output as a PNG through grim's wlr-screencopy
support. It returns the path and dimensions; the default is a unique file under
session `artifacts/`. Explicit paths are resolved by the CLI and must not exist.
`input key KEY` sends one XKB key press/release through wtype's virtual keyboard;
`input click X Y` sends a left click through wlrctl's virtual pointer. Coordinates
are scale-1 screenshot pixels from the top left of the single headless output.
The pointer is clamped to that corner before relative movement to the requested
pixel; bounds come from a capture, with no window or pointer enumeration.

Both commands use the generation-checked supervisor endpoint and connect helpers
only to the private compositor socket. They need no GUI RPC or `on_ui` callback.
Helpers time out after two seconds and are killed after one further second;
input success reports sent events, not application handling. The GUI's `status`
probe samples targets and `QApplication.activeModalWidget()` asynchronously,
waiting at most 250 ms and sharing one pending probe across polls. A timeout
reports `modal_open`, targets, and file/view counts as null with `gui_error`.
If GUI RPC itself cannot answer within one second, status reports the live
supervisor with those fields and requests unknown. Human output says `unknown`.

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
Analysis on hold fails with a shell-quoted resume command carrying the session's
`--state-dir`, the request's resolved `--target` handle, and `py
--allow-incomplete -c 'bv.set_analysis_hold(False); bv.update_analysis_and_wait()'`,
so the command works from any cwd and cannot be redirected by target inference.
`--allow-incomplete`
explicitly skips readiness and appears in the result. A script that triggers
analysis must wait again before reading dependent results. Raw views have no
analysis pipeline.

Use native virtual addresses in Python and preserve integer precision in output.
Readable addresses can use hexadecimal strings; file offsets must be identified
separately. A universal address schema is unnecessary.

## Typed analysis commands

- The CLI submits packaged Python scripts as operation-specific request kinds
  through the `py`/`open`/`save` worker; no separate analysis RPC/dispatcher. Target
  retention, readiness, recovery and artifact limits are shared. Python owns stdout
  headers (target/function/representation), content and continuation footers; JSON
  lives in `result`. Rust suppresses duplicate human-mode results, including
  recovery. The envelope and spill boundary are unchanged; text/JSON artifacts
  remain independently readable.
- `binja/analysis.py` owns resolution/listing output. FUNCTION tries exact native
  names, then all starting/containing functions at ADDRESS. ADDRESS accepts symbols,
  native numeric syntax and `symbol+offset`; symbol ambiguity is checked before
  `bv.parse_expression`. Ambiguities list candidates (including platforms for same-
  address functions) in error strings; no fuzzy or first-match selection.
- Listings return `rows` and `page: {offset, limit, returned, total, next_offset}`.
  `--offset`/`--limit` paginate, with 64 rows by default. Empty totals print `0
  rows`; offsets past a nonempty list report position/total. Pagination rerenders
  the current view without cursors; restart after edits/reanalysis. Spilling does
  not replace semantic bounds.
- Inspection results identify target/function/representation/extent. Linear-view
  defaults use expanded bodies, separate address/byte columns and no GUI inlays.
  Addresses are hexadecimal, IL indexes nullable; both are null on blank rows.
  Pseudo C/HLIL addresses are anchors, not machine instruction addresses.
  Raw/skipped/unavailable IL fails explicitly.
- `references.py` owns import normalization/text, sharing resolver/page helpers.
  Results include query, target/function identity, resolved addresses, direction
  (`inbound`/`outbound`), relation (`reference`/`call`) and full-query counts.
  Xrefs/refs preserve native auto/user references; `kind` is source `code`/`data`,
  independent of destination and call status. Sort code before data, then
  source/destination. Inbound text warns: zero references is not proof of no
  callers; unresolved indirect calls may be absent.
- `inventory.py` shares filters/headers and page helpers. Functions/imports/strings
  filter before paging, retaining query options, unfiltered `total_available` and
  matching `page.total`. Substrings match case-insensitively; no inventory arrays
  bypass paging.
- Edits return small, unpaged readbacks with target identity and `changed` after
  analysis. Rename/comment/proto/retype add `before` and `after`; proto/retype use
  native rendered types for no-op checks. Worker `execute()` uses native
  begin/commit undo groups for retained-target requests, including `py`, except
  `undo`/`close`. Commit on exceptions keeps partial edits undoable; empty groups
  add no entries. History is shared with GUI edits to the file. No preview, snapshot
  diffing or automatic rollback.

| Command | Row / record fields beyond shared metadata | Specifics |
| --- | --- | --- |
| `decompile FUNCTION` | `{address, text, il_index}` | Single-function Pseudo C language representation. |
| `il FUNCTION` | `{address, text, il_index}` | Native HLIL/MLIL/LLIL; MLIL default. |
| `disasm FUNCTION` | `{address, text, bytes}` | Native function annotations and bytes. |
| `disasm ADDRESS --count/--end` | `{address, text, bytes}`; `start, count, end, next_address, remaining_count, stopped_reason`; page `{limit, returned}` | View-architecture decoding needs no function analysis. Exclusive end; continue by address and remaining count/end. |
| `xrefs FUNCTION/ADDRESS` | `{kind, address, functions: [{name, start}]}` | Inbound references at the exact address; function names select starts, interior addresses stay interior. Data sources may have no containing function. |
| `refs FUNCTION` | `{kind, address, to, to_symbol}` | Outbound sources in analyzed basic blocks, excluding gaps. Destination native symbol name or null; text shows it beside the address. |
| `callers FUNCTION/ADDRESS` | `{address, function: {name, start}}`; `symbols, excluded_stubs` | Inbound calls: resolved `call_sites` through `get_callees`, ordered by function start/name then site. Import names or stub/slot/external addresses select the whole import; exclude its own stubs from independent call-site and code-reference counts. |
| `info` | Path, view type, architecture/platform, entry point, function/category counts; rows tagged by `kind`: library `{name}`, segment `{start, end, permissions, file_offset, file_length}`, section `{name, start, end, semantics}` | One page in library/segment/section order; segments/sections by address. Exclusive range ends, native section semantics. |
| `functions` | `{address, name, total_bytes}` | Sort by address (default), name or descending size, with deterministic ties. Python regex filtering is mutually exclusive with substring matching. |
| `imports` | `{address, kind, name, type_library}` | One per native stub/slot/external symbol, ordered by name/address/kind. `lookup_imported_object_library` attribution does not identify the runtime provider. |
| `strings` | `{address, type, length, value}` | Address/type/length order; length in bytes, full native decoded value, escaped in text. |
| `rename` | `function` | Changes the function name. |
| `comment` | `address, scope, function` | Names/exact starts select function comments; other addresses select view comments. |
| `proto` | `function` | Preserves the function name. |
| `retype` | `function, variable: {identifier, name, source, index, storage}` | Unique exact variable name or native `id:0xHEX` / `id:DECIMAL`; ambiguity errors. Reacquire by ID after analysis. |
| `declare --file` | `path, types: [{name, type, width, changed}]` | Submits local header text with its directory as an include path; installs every named type the native parser returns, using structural equality, reading back each type and change status. An empty parse is an error: on 6.0.10601, includes found through `include_dirs` contribute only types the header's own declarations use, while includes found in the session cwd contribute all their types. |
| `undo` | `summary, remaining` | Captures the last native entry's action summaries before reverting; waits for analysis afterward. |

## Execution and recovery

The plugin executes submitted scripts one at a time on one executor thread.
Requests sharing a file (`target_snapshot.file_id`, Binary Ninja's
`bv.file.session_id`) run in submission order, including requests targeting
different views of that file. Untargeted requests share a session lane; they
are not a barrier for file lanes. The executor chooses the earliest-submitted
lane head whose readiness is satisfied. A head on analysis hold runs and fails
with the resume error. `--allow-incomplete` does not bypass an earlier request
in the same lane.

Readiness waits park with status `waiting_analysis`, releasing the executor for
other lanes. The executor polls readiness every 100 ms when no head can run;
UI calls use `on_ui` without holding the scheduling lock. Handles are revalidated
while parked and immediately before execution. Submitted Python and its native
calls still occupy the executor until they return, including any waits the
script performs itself. Status and request inspection remain available during
execution, subject to the GUI being responsive.

`open` first loads and attaches a view, starts analysis, and records its `open`
target snapshot. It then joins that file's lane in original submission order.
The request completes with a fresh readiness-time target description, preserving
the normal `analysis: IdleState` result. A cancelled parked open leaves the file
open, with its handle available in the retained snapshot.

Admission is capped at 8 unfinished requests, including parked requests.
Rejection occurs before recording the ID and explicitly guarantees no execution,
so that rejected submission can be retried. Duplicate accepted IDs still return
their existing record even at capacity. Receipts expose lane-relative queue
position (counting queued requests), the immediate unfinished predecessor in
that lane, and the retained target snapshot. Queue observations are captured
under the scheduling lock.

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
record without replay. The acknowledgement follows the pre-submission ID receipt,
so clients can distinguish acceptance and queue placement. Human acceptance
receipts are useful only when `waits_behind` is non-null; queued status alone
also describes an idle worker awaiting pickup. Client wait expiry is
explicit in human and JSON output, with a recovery command; it does not cancel work.
Elapsed seconds run from becoming a lane head (including readiness) or, for unstarted
requests, submission. Listings lead with active and queued work and the newest five
finished records by completion time; `--all` includes all finished metadata.

Request target descriptions are labeled `target_snapshot`, with stage `submission`
or `open` (captured after load/attachment). They are not current target state.
Metadata and artifact files stay for the session. Only the newest 64 finished
records retain inline output; older records have `output_pruned: true` and retain
artifact references, byte counts, and stream truncation flags. Small outputs
initially contain inline text/result; pruning exposes their existing backing
files as artifact references. Large streams retain a 16 KiB preview in the full
record as well as an artifact path and byte count. A new lifetime and completed
shutdown retire artifacts after owned children have stopped; reusing a live
session does not. A restart cannot establish an earlier outcome.

The `requests` response is an object with `requests` rows, `finished_total`,
`finished_shown`, `rejected_total`, and `rejections`. Rows retain kind, filename,
truncated error, output-pruned flag, target snapshot, phase, and timestamps.
`started` is set when a request first becomes a lane head.
`queue_wait_seconds` measures submission to that point, or to now/termination
for unstarted work. `execution_seconds` measures lane-head time to now/termination,
including readiness and waiting for another lane's executing script; it is null
for requests cancelled before reaching a lane head and other unstarted work.
`elapsed_seconds` uses
execution time when started, otherwise queue time.

Cap-rejected attempts are separate from accepted records. A lifetime total counts
all cap rejections; a ring retains the newest 64 events, oldest first. Each event
has `id`, `time`, `reason: "pending_cap"`, `kind`, `filename`, `running` (ID or
`"none"`), `queued`, and `pending_cap`. Default human listings summarize the
rejection count; `--all`, verbose, and JSON expose the retained events.
`request`, request waits, and `cancel` check accepted records first, then the
ring: a retained rejection fails with an explicit never-executed, safe-to-resubmit
error, and an ID with neither gets the generic unknown-outcome warning. Duplicate
recovery at capacity neither executes again nor counts as rejection. Invalid
input is not a cap event.

Cancellation can stop queued work or a parked readiness wait, including an
open after load/attachment. It cannot safely interrupt running Python or native
calls. Scripts are neither sandboxed nor
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

`api search`, `api show`, and `api members` use an index built from the installed
distribution's Python declarations and docstrings. Results include version and
source locations; `api paths` locates bundled source and Sphinx documentation.
The index labels declaration `kind`, properties' `writable` status and
`return_type`, and enum `members`. Enum members contain a name and source
expression, plus `value` when statically literal; unresolved expressions are not
evaluated. Public annotated assignments directly in a class body produce `field`
records with `annotation` and optional `default` as source text. Dataclass
fields and `ClassVar` declarations both qualify; instance storage and
writability are not inferred.
Setter declarations are folded into their property rather than indexed as a
second symbol. Class and enum records also carry `bases`, a C3 `mro`, and
`unresolved_bases`. The builder resolves local classes and explicit imports,
including relative imports, module aliases, and re-exports. Unindexed bases
retain their import path or source name and are treated as opaque roots in the
static MRO; `object` contributes no public members. Their unknown ancestry can
limit the order's accuracy. No source expressions are executed.

`api members CLASS [--match TEXT]` lists every matching public indexed member:
methods, properties, annotated fields, nested classes, and enum values. Direct members come first,
then inherited members grouped by owning class in MRO order, alphabetically
within each class. Overrides appear once, selected by MRO before filtering.
`--match` is a case-insensitive literal substring of the member name, with outer
whitespace stripped; it does not search signatures, owners, or docstrings.
Rows retain declaration metadata and add `name` and `owner`; JSON also reports
`class`, `mro`, `unresolved_bases`, the requested `match`, matching `total`, and
unfiltered `total_members`. Empty matches succeed with an empty list; absent,
ambiguous, or non-class symbols fail. An unindexed base is an explicit coverage
gap, including when a filter returns no rows. Unannotated assignments, fields
declared only in method bodies, generated members, and private declarations are
outside the index. `api show CLASS` renders a class declaration with its
effective fields, selected and ordered as in `api members` and tagged with
inherited owners; a field row is `name: annotation = default [field]`, and
defaults over 160 characters are abbreviated in text while JSON keeps the full
source. Static
lookup requires no GUI, license, or Binary Ninja imports; native UI classes and
other gaps may require direct source or documentation inspection via `api paths`.

Default human output keeps outcomes, retained handles, payloads, failures, and
recovery commands. Full paths appear for open/save outcomes and target listings;
historical target snapshots do not masquerade as current state. Artifact-backed
streams show paths and byte counts instead of inline previews. `--verbose`
appends the full available record; `--json` returns that record directly and
preserves flat submitting/accepted stderr events. Human admission receipts appear
only with an unfinished predecessor. Successful cancellation exits 0; retrieving
that cancelled request still exits 1. API show retains a source:line pointer,
while version and docs paths are in verbose/JSON; search states shown/total counts
and the limit needed to retrieve the rest.

`--help` points to `binja skill`, which prints a single packaged guide. The guide
teaches working commands, target selection, API lookup, readiness, saving, and
failure recovery. Extend it from observed usage friction; avoid duplicating API
documentation, `--help` text, notices the tool prints on every call, or
development status in the installed instructions. Sentences that only make
sense against a previous version belong in the log, not the guide.
