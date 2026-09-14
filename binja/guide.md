# binja

Use binja for static analysis with Binary Ninja Personal. Run commands from the
analysis workspace. Typed commands cover inspection, references, inventories and edits;
Python is the backstop.
A GUI session persists between commands, executing requests in its bundled interpreter.

```sh
binja start
binja open ./sample
binja decompile main
binja comment main "Reviewed main"
binja save ./analysis.bndb
binja stop
```

## Sessions

Commands use `.binja` in their working directory for session state. Set your shell
tool's working directory consistently across calls. To use a session from another
directory, pass `--state-dir /absolute/path/to/.binja` on each command. Selection is
by this path; binja does not search parent directories or other running instances.
`status` reports the resolved path, file and view counts, and pending requests.
Redundant Raw views count as views of the same file. With no running session,
including after a clean stop, `status` reports the path and exits 0.

`start` starts or reuses a GUI on a private Wayland compositor with a headless
backend. The default license is `~/.binaryninja/license.dat`; `start --license PATH`
selects another. Restart sessions after upgrading the package. Logs are in the
session's `logs/` directory. Keep session state out of version control.
Relay an available stable-update notice from `start` or `status` to the user,
including the installed and latest known versions and whether the cache is stale;
upgrading requires a package rebuild, and an unknown check does not mean current.

`open` accepts a binary or existing BNDB. Save at meaningful work boundaries and
before stopping. `save PATH.bndb` requires a destination outside session state;
it updates that database on subsequent saves and refuses to overwrite an unrelated
file. `targets --json` includes modification flags and the last save observed by
this session (`null` means unknown). `stop` refuses pending work and unsaved changes;
`stop --force` terminates the session and discards unsaved work.
`close HANDLE|PATH` closes that file's views, including redundant Raw views,
and expires their handles. It refuses pending work; `--force` only overrides
unsaved changes. A bare `bv.file.close()` from `py` bypasses this coordination.

After a restart, use `open ./analysis.bndb` to continue saved analysis. Open tabs,
unsaved edits, request results, and Python state are not restored.

For a stuck GUI, run `screenshot [PATH]`, inspect the PNG, then use
`input key Escape` (also `Return`, `Tab`, or another XKB key name) or
`input click X Y` for a left click at a screenshot pixel from the top left.
Capture and input use the private compositor, even when GUI RPC cannot answer.
`status` says when a modal is open or the GUI state is unknown; a stuck UI also
makes file and view counts unknown. Input reports sent events; check the screenshot or
status for their effect. Screenshots default to session `artifacts/`, which is
cleared on stop/restart; pass a new path outside session state to keep one.

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
binja api members Function --match name
binja api show BinaryView.get_functions_containing
binja api paths
```

These commands read the installed distribution's static index and, like `--help`
and `skill`, need no session or license. `api search` matches declarations and
docstrings, so a hit does not establish membership; `api members CLASS` does,
listing public members with property writability and inherited members with
their owning class (`--match TEXT` filters names by substring). Check it before
guessing names like `Function.set_user_name` or `Function.size`, which do not
exist. `api show` gives the declaration, property or enum metadata, docstring,
and a source:line pointer. Qualified symbols resolve ambiguity. Bases outside
the index (native UI classes, C extension types) are reported as unknown;
inspect the documentation located by `api paths` for those. Search reports
shown/total matches (`--limit N`); `--verbose` adds version and documentation paths.

`py` accepts stdin, `-c CODE`, or `--file PATH`. Each request gets fresh
globals: `bn`, `bv`, `args`, `result`, and `on_ui(callable)`. Assign JSON-
compatible values to `result`; convert API objects into the fields you need. Use
`hex()` for readable virtual addresses. Integer addresses remain exact in JSON;
file offsets are different quantities. `py --no-target` runs with `bv=None` for
session-level work.

The CLI reads `--file` locally, but executes its contents in the GUI process.
The complete serialized submission (source, arguments, and metadata) has a 4 MiB
limit; oversized submissions are not accepted and do not execute.
Use absolute paths for file access inside scripts: its working directory starts
as the directory where the session was launched, and its imports use the bundled
interpreter. Variables from earlier requests are unavailable; imports and database
edits persist. Stdout/stderr capture includes synchronous `on_ui` callbacks, but
excludes spawned threads and native Binary Ninja logs.

Target-bound commands wait for completed analysis when they execute.
`--allow-incomplete` skips this check and is recorded in the result. Analysis on hold
produces an error; resume it explicitly:

```sh
binja py --allow-incomplete -c 'bv.set_analysis_hold(False); bv.update_analysis_and_wait()'
```

If a script edits and then reads dependent results, call
`bv.update_analysis_and_wait()` between them. Keep analysis work on the worker;
use `on_ui` only for GUI calls. Raw views have no analysis pipeline.

## Analysis recipes

These examples assume one analyzed target; add `--target HANDLE` when needed.

### Choosing a representation

Maintainer preference, learned on large and complex binaries. Treat it as the
default reading order, not a rule.

1. Decompiled output is the first read. It is not reliable: functions can be
   incomplete, control flow can come out broken, and inferred types mislead.
2. When the decompilation looks wrong, HLIL is a weak fallback and MLIL is the
   strong one. MLIL keeps the analysis results but shows what the decompiler
   folded away.
3. When the question reaches the instruction level, read LLIL rather than
   disassembly: it says the same thing in fewer tokens and normalizes the
   architecture away.
4. Disassembly is for encodings, raw bytes, and calling-convention details,
   and is the epistemic backstop when the ILs disagree with each other or with
   the bytes.

### Code inspection

```sh
binja decompile main
binja il main                       # MLIL by default
binja il main --view hlil
binja il main --view llil --ssa
binja disasm main
binja decompile main --offset 64 --limit 64
binja disasm main+10 --count 20
```

`decompile` uses the GUI's Pseudo C language renderer, including type casts and
indentation. `il --view hlil|mlil|llil [--ssa]` prints native IL text with source
addresses and IL instruction indexes. `disasm FUNCTION` includes native
annotations and instruction bytes. Pseudo C and HLIL addresses are **anchors**:
several lines can share one, and they are not a one-to-one mapping to machine
instructions. MLIL/LLIL instructions can also share a source address.

FUNCTION accepts an exact symbol name (raw or displayed), a start address, or an
address inside a function. Multiple matches fail with candidate names, addresses
and platforms; use a unique name/address, or Python for platform selection.
ADDRESS accepts symbols, hexadecimal numbers and `symbol+offset`. Numeric syntax
follows `bv.parse_expression`: `main+10` means `main+0x10`; `0n10` is decimal ten.
Other expressions remain available through Python. A symbol with several distinct
addresses is ambiguous, including when used as an expression's base.

Listings default to 64 rendered rows, counting signatures, annotations and blank
lines. The footer reports the total and next `--offset`; repeat the same command,
target, representation and SSA choice to continue. `--limit N` changes the page
size. Pages rerender the live view: restart at offset zero after edits or
reanalysis. IL unavailable on a Raw view or after skipped analysis is an error,
with no substitution of another representation.

`disasm ADDRESS --count N` or `--end ADDRESS` decodes linearly without needing a
function; it needs a view architecture (`bv.arch`). The end is exclusive, and an
instruction crossing it is not emitted. `--limit` bounds each page; the footer
gives the next address and remaining count/end for continuation. `--offset` is
only for function listings. Unmapped bytes, undecodable instructions and an end
inside an instruction have explicit stopping reasons.

`--json` returns the request record with the page in `result`: function identity,
representation, `rows` of `address` and `text` (plus `il_index` for IL, `bytes`
for disassembly), and page metadata. These commands share `py`'s readiness, wait
and recovery flags, and spill oversized pages to artifacts like any request.

### Editing and native undo

```sh
binja rename _start reviewed_entry
binja comment reviewed_entry "Reviewed entry function"
binja comment main+10 "Reviewed this instruction"
binja proto main 'int32_t main(int32_t argc, char** argv)'
binja declare --file types.h
```

Edits wait for analysis before and after applying a change, then return the
native readback with `changed` or `no-op`. Equal names/comments and equal rendered
function/variable types avoid the setter; an equal inferred type is not pinned
as a user override. `proto` applies the type and parameter names while preserving
the function's symbol name. `comment` selects the function comment for an exact
name or start address, and a view address comment elsewhere. An empty comment
clears it. `declare` installs named types in the view; headers containing function
or variable declarations require `proto` or Python. Relative includes use the
header's directory.

Variable names and stack locations can repeat. Enumerate native identifiers
with their source/index/storage before using `retype`:

```sh
binja py <<'PY'
from binja.analysis import resolve_function
f = resolve_function(bv, "main")
for v in f.vars:
    print(f"id:{v.identifier:#x}  {v.name}  {v.type}  {v.source_type.name}/{v.index}/{v.storage}")
PY
binja retype main var_198 uint32_t
binja il main --view hlil
```

Use a unique exact variable name or `id:0xHEX` / `id:DECIMAL` from that inventory;
ambiguous names report candidates. `retype` reacquires the variable by native ID
after analysis and reports its actual type. Read fresh HLIL after a prototype or
variable edit to assess its effect; IL objects retained before an edit are stale.
Python remains the backstop: `bv.parse_type_string`, `f.set_user_type` or
`v.set_type_async`, then `bv.update_analysis_and_wait` and reacquire the variable.

`binja undo` reverts the latest native entry and reports its action summaries.
Target-bound requests, including `py`, share one native begin/commit group;
`undo` itself is excluded. Empty groups add no entry. A failed script keeps its
already-applied edits, committed as an undo unit. Undo history belongs to the
file and interleaves with GUI edits; it is not a per-client history or a rollback
guarantee. `py --no-target` does not group edits to views it locates itself.

Save to a fresh database path, restart, then verify persistence:

```sh
binja save ./reviewed.bndb
binja stop
binja start
binja open ./reviewed.bndb
binja py <<'PY'
f = bv.get_function_at(bv.entry_point)
assert f.name == "reviewed_entry" and f.comment == "Reviewed entry function"
print(f"{f.start:#x}  {f.name}  {f.comment}")
PY
```

### Reference traversal

```sh
binja xrefs g_entities              # Inbound references to this exact address
binja xrefs main
binja refs main                     # Outbound references from the function
binja callers malloc               # Resolved call sites, with import stubs excluded
binja callers malloc --offset 64
```

`xrefs ADDRESS|FUNCTION` lists inbound code and data references separately,
including source addresses and their functions (or no containing function).
Exact function names select their start; an address or `symbol+offset` stays at
that address. `refs FUNCTION` lists outbound source/destination pairs within the
function's analyzed basic blocks, excluding gaps, with destination symbol names
when available. Code/data classify the **source**:
an instruction referencing a global variable is a code reference. References
include non-call uses; use `callers` for resolved calls.

`callers NAME|ADDRESS` combines an import's stub (`ImportedFunctionSymbol`),
address slot (`ImportAddressSymbol`) and external destination (`ExternalSymbol`)
by name; any of those addresses selects the same import. Formats need not expose
all three. The import's own stubs are excluded. For ordinary functions, use an
exact name or destination address. Call sites come from `call_sites` resolved
through `get_callees`; the separately reported code-reference count can differ.
Zero discovered references is not proof of no callers: unresolved indirect calls
may be absent from either result.

All three commands use `--offset/--limit` with 64 rows by default. Counts describe
the full query, even on an empty page. The footer supplies the next offset;
restart pagination after edits or reanalysis.

### Inventory

```sh
binja info
binja functions --sort size --limit 10
binja functions --match parse --sort name
binja functions --regex '^(parse|read)_' --offset 64
binja imports --match malloc
binja strings --match error
```

`info` summarizes the selected file/view, architecture, platform, entry point
and function count. Its rows list libraries, then segments, then sections, with
one shared `--offset/--limit` window. Range ends are exclusive; segment file
offsets are labeled separately from virtual addresses.

`functions` lists address, name and `total_bytes`: the sum of basic-block lengths,
including overlaps, not an instruction count or address span. `--sort address`
is the default; `--sort size` puts the largest first and `--sort name` orders
names lexicographically. `--match SUBSTRING` is case-insensitive; the alternative
`--regex PATTERN` uses Python regex search on displayed names, case-sensitive
unless the pattern includes `(?i)`.

`imports` lists each stub, address slot and external symbol separately, ordered
by name/address. Its **type library** attribution identifies the library used
for the symbol's type, when known; it does not establish which runtime library
supplies the symbol. Dependency libraries in `info` are file-wide.

`strings` lists native analyzed strings by address, with encoding and byte length.
Text quotes and escapes decoded values to keep each string on one row; JSON
retains the decoded value. `imports` and `strings` also accept case-insensitive
`--match` on displayed names and decoded values, respectively.

All inventories default to 64 rows with `--offset/--limit`. Filters and sorting
apply before pagination; filtered lists report the matching total and unfiltered
count. Repeat the same options with the footer's next offset to continue, and
restart after edits or reanalysis. Long strings can spill a page to artifacts; values
are not shortened to fit inline.

## Requests and recovery

Python, open, save and typed analysis commands print a request ID to stderr before submitting.
They normally wait up to 30 seconds after admission. `--wait` is not an
end-to-end command deadline. A client wait expiry exits 2 and leaves the request queued
or running; retrieve the existing request instead of repeating it:

```sh
binja py --file slow_script.py --no-wait
binja requests
binja request REQUEST_ID --wait 30
binja cancel QUEUED_REQUEST_ID
```

Replace the placeholders with returned IDs. `--no-wait` returns the acknowledged
state immediately. An `Accepted: queued #N` receipt appears only when another
unfinished request precedes this one (`waits_behind` is set); it names the
retained target snapshot and predecessor. A recovered queued ID is labeled
`Existing request`. Queue positions are live observations, not reservations.

There is one worker per session: batch per-function work into one script.
Parallel shells can hide client overhead but do not parallelize worker
execution. The worker accepts at most 8 unfinished requests, including the
running request. At the cap, rejection explicitly says the request was not
accepted and will not execute, names the running request and queued count, and
is safe to resubmit once capacity is available.

`requests` lists running/readiness-waiting work first, then queued work in
order, then the five most recently finished requests. `requests --all` includes
full history in the same order. Rows identify the request kind and script
filename, target snapshot, phase, timing, pruned inline output, and errors.
Timings separate queue wait from worker occupancy, including analysis readiness.

`requests --json`: `requests`, `finished_total`, `finished_shown`,
`rejected_total`, `rejections` (newest 64, oldest first; export limit 64 MiB).
`queue_wait_seconds` measures queueing; `execution_seconds` measures worker
occupancy (null before pickup). `elapsed_seconds` starts at pickup or submission
if unstarted; terminal records stop the clock.

`--verbose` appends the full record; `--json` emits it on stdout. JSON stderr:
`submitting` before RPC, `accepted` after admission (`existing: false`) or recovery
(`existing: true`). Wait expiry exits 2 with `client_wait_expired: true` and
`recovery_command`; human output prints the same recovery command.

Failed or cancelled requests exit 1 when submitted/retrieved. The `cancel`
command itself exits 0 when cancellation succeeds, and 1 when refused. It can
cancel queued requests and pre-script analysis waits; running Python/native work
cannot safely be interrupted. Status and request inspection remain available
during execution.

After a read timeout or disconnect, inspect the printed ID. An unknown ID does
not prove the script never ran. Recover with the same `--request-id`; do not
automatically repeat mutations.

The CLI normally generates IDs. To construct a custom `--request-id`, read
`generation` from `binja status --json` and use `GENERATION:rUNIQUE_ID`. The
generation is 12 lowercase hexadecimal characters; UNIQUE_ID is 1–64 ASCII
letters, digits, underscores, or hyphens. For generation `abcdef123456`,
`abcdef123456:rinspect_1` is valid. Use a new suffix for new work. Reusing an ID
returns its original record without executing again, even if the submitted
source or target differs.

Request records call the retained target description `target_snapshot`, with
`target_snapshot_stage: "submission"`. For `open`, it is initially null and is
captured after loading/attaching the view, with stage `"open"`. Snapshot paths and
analysis states do not track later saves or analysis progress; use `targets` for
current state and the command's `result` for its outcome.

Request metadata and all artifact files stay available until the session stops
or a new lifetime starts. Reusing an already-running session with `start` preserves
them. Only the newest 64 finished records keep inline stdout/stderr/result;
older records have `output_pruned: true` and retained file references, byte counts,
and truncation flags. Retrieve the old record to locate its output files.

Each output stream retains up to 1 MiB, with a truncation flag; JSON results have
an 8 MiB limit. Above 16 KiB, outputs are returned as artifact paths. Full JSON and
verbose records also include a 16 KiB stream preview; default human output shows
the path and byte count instead of duplicating that preview. Read the files to
consume large or pruned output. Copy artifacts elsewhere before stopping if they
need to outlive the session.

Scripts have the user's filesystem access. Errors, timeouts, and forced stops do
not roll back edits or external writes. Request recovery works within the running
GUI; recovering analysis after a crash requires a successful database save.
