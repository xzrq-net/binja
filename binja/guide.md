# binja

binja drives a persistent Binary Ninja Personal GUI for static analysis. Typed
commands cover inspection, references, inventories and edits; `py` runs Python
in the GUI's bundled interpreter for everything else. `--help` on any command
lists its flags. Text output renders a request's `result`; `--json` returns the
whole record.

```sh
binja start
binja open ./sample
binja decompile main
binja comment main "Reviewed main"
binja save ./analysis.bndb
binja stop
```

## Sessions

Session state lives in `.binja` under the working directory, so keep the
working directory constant across calls, or pass `--state-dir /abs/path/.binja`
on each. binja never searches parent directories or other running instances.

`start` starts or reuses a GUI on a private headless Wayland compositor, with
the license from `~/.binaryninja/license.dat` or `--license PATH`. A human can
watch or drive that GUI by pointing a VNC viewer at the Unix socket `start`
and `status` print (TigerVNC: `vncviewer .binja/runtime/vnc.sock`).
`start --display desktop` instead opens the GUI on the shell's own
`WAYLAND_DISPLAY`; there `screenshot` and `input` are unavailable and the
human dismisses dialogs directly. The display is fixed for the session: stop
before switching. Restart sessions after upgrading the package. If `start` or
`status` reports a newer stable release, tell the user; upgrading needs a
package rebuild.

`open` takes a binary or BNDB. Save at work boundaries and before stopping:
`save PATH.bndb` needs a path outside session state, keeps updating that
database on later saves, and refuses to overwrite an unrelated file. `stop`
refuses pending work and unsaved changes; `stop --force` discards them.
`close HANDLE|PATH` closes one file's views and expires their handles, with the
same guards (`--force` overrides only unsaved changes).

After a restart, `open ./analysis.bndb` continues from the save. Handles, request
results and Python state do not survive.

If the GUI stops responding, `screenshot [PATH]` captures the display and
`input key Escape` or `input click X Y` (screenshot pixels, top-left origin)
drive it, even when GUI RPC is down. `status` reports open modals and unknown
GUI state. Screenshots default to session `artifacts/`, cleared on stop. If a
startup dialog blocks plugin loading, the supervisor kills the session after
60 seconds; check `logs/binaryninja.log` and `logs/supervisor.log` in the state
directory, then `start --no-startup-deadline` to keep it alive for screenshot
and input. `status --json` shows `ready: false` until the plugin loads.

## Targets

With one eligible view, commands infer the target. Otherwise pass `--target`
with a handle from `targets`, a unique filename or path, or `active` (GUI
focus, sampled once):

```sh
binja targets
binja --target ./sample py -c 'result = bv.file.filename'
binja py --target ./sample --file inspect.py --args '{"limit": 10}'
```

Handles stay valid across saves that change a view's path, and expire when the
view closes or the session restarts. Opening a binary also produces a Raw view
of the same file: `status` counts it, inference ignores it, and `close` closes
both.

## Python and API lookup

Look up unfamiliar API before guessing:

```sh
binja api search 'call site'
binja api members Function --match name
binja api show BinaryView.get_functions_containing
binja api paths
```

These read a static index of the installed distribution and need no session or
license. `api search` matches declarations and docstrings, so a hit is not proof
of membership; `api members CLASS` is, and includes inherited members and
annotated fields with their owning class. Native UI classes and C extension
types are outside the index; `api paths` locates the shipped documentation for
those.

`py` takes stdin, `-c CODE`, or `--file PATH`. Each request gets fresh globals
`bn`, `bv`, `args`, `result`, and `on_ui(callable)`. Assign JSON-compatible
values to `result`; addresses stay exact integers, so `hex()` them for reading.
`py --no-target` runs with `bv=None` for session-level work.

Scripts execute in the GUI process: imports come from the bundled interpreter,
the working directory is where the session was launched (use absolute paths),
and imports and database edits persist between requests while variables do not.
Keep analysis work on the worker; use `on_ui` only for GUI calls.

Target-bound commands wait for analysis to complete before running.
`--allow-incomplete` skips the wait. Analysis on hold is an error that prints
the resume command for that target. A script that edits and then reads
dependent results needs `bv.update_analysis_and_wait()` between the two. Raw
views have no analysis.

## Reading code

Default reading order:

1. Decompiled output, knowing that functions can be incomplete, control flow
   broken, and inferred types misleading.
2. When it looks wrong, MLIL: it keeps the analysis results but shows what the
   decompiler folded away. HLIL is a weaker fallback.
3. At the instruction level, LLIL rather than disassembly: fewer tokens,
   normalized operations.
4. Disassembly for encodings, raw bytes and calling conventions, and as the
   backstop when the ILs disagree with each other or with the bytes.

```sh
binja decompile main
binja il main                       # MLIL by default
binja il main --view hlil
binja il main --view llil --ssa
binja disasm main
binja decompile main --offset 64 --limit 64
binja disasm main+10 --count 20
```

FUNCTION is an exact symbol name (raw or displayed), a start address, or an
address inside the function. Ambiguity fails with the candidates; pick a unique
name or address, or use Python for platform selection. ADDRESS follows
`bv.parse_expression`: symbols, hex numbers, `symbol+offset` where the offset is
hex (`main+10` is `main+0x10`; `0n10` is decimal ten). A symbol with several
addresses is ambiguous, including as an expression base.

`disasm ADDRESS --count N` or `--end ADDRESS` (exclusive) decodes bytes
linearly with no function context: no symbols, comments or variable
annotations. It pages by address, not `--offset`.

**Pagination, for every listing and inventory command:** `--offset/--limit`
count rendered rows, including signatures, annotations and blank lines, 64 per
page by default. Pages rerender the live view, so restart from offset zero
after edits or reanalysis. Oversized pages spill to artifact files. IL that is
unavailable (Raw view, skipped analysis) is an error.

## Editing and native undo

```sh
binja rename _start reviewed_entry
binja comment reviewed_entry "Reviewed entry function"
binja comment main+10 "Reviewed this instruction"
binja proto main 'int32_t main(int32_t argc, char** argv)'
binja declare --file types.h
```

Edits wait for analysis before and after the change and return the native
readback as `changed` or `no-op`. Setting a value equal to the current one skips
the setter, so an equal inferred type is not pinned as a user override. `proto`
applies the type and parameter names and keeps the function's symbol name.
`comment` on an exact function name or start address sets the function comment;
elsewhere it sets an address comment. An empty comment clears. `declare`
installs the named types Binary Ninja's parser returns for the header. Includes
resolve against the header's directory but may serve only as parsing context,
so declare a defining header directly; a parse that yields no types is an
error. Function and variable declarations in headers need `proto` or Python.

Variable names and stack locations can repeat, so enumerate native identifiers
before `retype`:

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

`retype` accepts a unique exact name or `id:0xHEX` and reports the type the
variable ended up with. Read fresh HLIL after a prototype or variable edit; IL
objects held across an edit are stale. In Python:
`bv.parse_type_string`, `f.set_user_type` or `v.set_type_async`, then
`bv.update_analysis_and_wait` and reacquire the variable.

`undo` reverts the latest native undo entry and prints Binary Ninja's own
action summaries, which can read oddly. Each
target-bound request, including `py`, is one undo entry (empty ones are
dropped); a failed script keeps its already-applied edits as one entry. Undo
history belongs to the file and interleaves with GUI edits; it is not a
per-client rollback.

## References

```sh
binja xrefs g_entities              # Inbound references to this exact address
binja xrefs main
binja refs main                     # Outbound references from the function
binja callers malloc                # Resolved call sites, import stubs excluded
```

`xrefs ADDRESS|FUNCTION` lists inbound references. An exact function name
means its start; an address or `symbol+offset` means that exact address.
`refs FUNCTION` lists outbound references within the function's analyzed basic
blocks. Both include non-call uses; `callers` is for resolved calls.

`callers NAME|ADDRESS` treats an import's stub, address slot and external symbol
as one thing, selected by name or any of those addresses, and excludes the
import's own stubs.

## Inventory

```sh
binja info
binja functions --sort size --limit 10
binja functions --match parse --sort name
binja functions --regex '^(parse|read)_' --offset 64
binja imports --match malloc
binja strings --match error
```

`info` summarizes the view and pages libraries, segments and sections in one
window. `functions --match` is a case-insensitive substring; `--regex` is a
case-sensitive Python search over displayed names. `imports` lists each stub,
address slot and external symbol as its own row. `strings --match` searches
decoded values. Filters and sorting apply before pagination.

## Requests and recovery

`open`, `save`, `py` and the typed analysis commands are requests. Each prints
its request ID to stderr before submitting, then waits up to `--wait` seconds
(default 30) after admission. If the wait expires the command exits 2 and prints
a recovery command; the request keeps queueing or running. Retrieve it instead
of resubmitting:

```sh
binja py --file slow_script.py --no-wait
binja requests
binja request REQUEST_ID --wait 30
binja cancel QUEUED_REQUEST_ID
```

One worker per session executes requests in order, so batch per-function work
into one script; parallel shells only hide client overhead. At most 8 requests
can be unfinished at once; a rejected submission never executes, and `request`
on its ID says so until the rejection ages out of the newest 64. `cancel`
works on queued requests and on pre-script analysis waits; running Python or
native work cannot be interrupted.

After a read timeout or disconnect, inspect the printed ID. An unknown ID does
not prove the script never ran. Recover with `request ID` or by resubmitting
with the same `--request-id`, which returns the original record without
executing again; do not blindly repeat mutations.

Output over 16 KiB comes back as an artifact path, and older records drop
their inline output in favor of the files. Artifacts and request records live
until the session stops, so copy anything you need first. Errors, timeouts and
forced stops do not roll back edits; a GUI crash loses everything since the
last save.
