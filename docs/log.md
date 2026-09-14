# Investigation log

## 2026-09-12 — Binary Ninja 6.0 packaging and agent interfaces

Assessed the supplied Personal distribution,
the built-in MCP over a running GUI, and current Codex activation mechanisms.
No runtime implementation or interface choice has been adopted. The proposed
direction is a Nix-pinned distribution, an explicitly owned GUI session under a
state directory, and a compact CLI/Python interface with optional MCP exposure.

### Inputs and reproducibility

- ZIP: `~/temp/binaryninja_linux_6.0.10601_personal.zip`.
- Flat SHA-256: `sha256-OOuY5Pw6I5iL3CrDDEPDj2UysjD2ZlADAw7L+SGVRMc=`.
- Live version: `6.0.10601 Personal`; bundled Python `3.13.14`; Qt `6.11.1`.
- Matching API tag: `stable/6.0.10601`, commit
  `2ddf304b3275aa184e95570404539cbc4beb64c6`.
- `hugsy/binja-headless`: existing checkout at `e6ab5ad` (2025-02-13).
- `banteg/bn`: inspected checkout at
  `bd910329547303c787a68fcd8309e83ab1be6590`, version 0.15.0 (2026-09-04).
- Codex CLI installed here: `0.154.0`. Local source inspected at `3d2ee51ca2`;
  source behavior is not proof of feature availability in this conversation's host.

The API checkout had existing modifications and an older checkout. The matching
tag was fetched without changing its working tree.

### Live experiment

Extracted the archive under ignored `temp/investigation/`, preserving Unix modes
and symlinks. Reused a cached FHS runner and labwc 0.9.2 with
`WLR_BACKENDS=headless`, `WLR_RENDERER=pixman`, and `QT_QPA_PLATFORM=wayland`.
The old runner needed an additional libcurl search path to launch 6.0. A direct
launch through the ambient nix-ld setup failed on missing libEGL.

Created private Binary Ninja and XDG directories, linked the existing license
at runtime, disabled the welcome wizard and update checks, and loaded
a scratch copy of hugsy's bridge. The bridge was restricted to loopback with a
temporary port; the built-in MCP used a generated bearer token. Inputs were
copies of a small test executable. No test executable was executed.

Verified GUI startup, MCP initialization, open/list/select, decompilation, LLIL,
function metadata, an in-process Python query, and a Qt window screenshot.
The screenshot is `temp/investigation/window.png`. All test GUI and compositor
processes were stopped, and the MCP and RPyC listeners were checked closed.
VNC/input handling was not exercised in this experiment.

Scratch evidence includes `builtin-tools.json`, `mcp-observations.json`, the
archive's extracted Python API and documentation, and the temporary launcher.
These are disposable investigation artifacts, not supported project commands.

### Built-in MCP: useful breadth, shared target state

The live catalog has **75 tools**, approximately **60,227 bytes** under Python's
default JSON serialization. Descriptions are mostly short. Coverage includes
analysis, functions, xrefs, types, variables, symbols, comments, sections, file
management, and mutations. There is no Python execution tool. IL exposes only
text form. Lists and code use Markdown/text with pagination metadata; some
other results include structured content. The tested code output was readable,
and the function tools support architecture disambiguation.

The target model is unsuitable for independent clients sharing a process:

```text
UI opens target                  -> MCP active view is null
client A selects view_1 (ELF)     -> client B also sees view_1
client B selects view_2 (Raw)     -> client A now sees view_2
client B opens another file      -> client A now sees that file's view
MCP selects the first file;
GUI focuses the second file      -> MCP remains on the first file
```

These were separate initialized HTTP MCP sessions with different session IDs.
Selection is process-wide in the tested build. Setting the target immediately
before a tool call does not provide isolation if another client can interleave.
A proxy would need exclusive ownership and serialization of both selection and
operation, including file-open operations. Alternatively, use one backend
process per consumer or resolve explicit views directly through the Python API.

The [MCP guide](https://docs.binary.ninja/guide/mcp.html) says the active view
follows the GUI unless explicitly changed. The live initialize instructions say
UI-opened files are not automatically active for MCP. The latter matched the
initial test. The guide also understates mutation coverage. Prefer live schemas
and behavioral tests over assuming the guide describes every detail.

This was a targeted behavioral review, not an audit of the native implementation
or all 75 handlers. Mutation correctness, database saving, cancellation, and
large-binary performance remain untested.

### Alternative bridges

[hugsy/binja-headless](https://github.com/hugsy/binja-headless) is the faux-headless
bridge tested successfully in the 6.0 experiment. Its default
`0.0.0.0:18812` listener exposes unrestricted Python without authentication;
do not carry those defaults into the composition. A socket inside the private
state directory is a better fit.

[banteg/bn](https://github.com/banteg/bn) is a particularly relevant alternative:
CLI, companion GUI plugin, explicit target selectors, offline command schemas,
in-process Python with `bv` and `bn`, result/stdout capture, and a packaged Codex
skill. It has no mandatory Python dependencies. Inspected code confirms
`BN_CACHE_DIR` controls both bridge socket and registry, `TMPDIR` can contain
CLI spill files, request dispatch is serialized, and GUI target discovery is
marshaled to the main thread. Bridge startup unconditionally unlinks an existing
socket, so the owning launcher should prevent duplicate use of a state directory.
This is a candidate to evaluate before implementing another bridge; it was not
installed or live-tested, and its broader mutation machinery was not reviewed.

[mrphrazer/binary-ninja-headless-mcp](https://github.com/mrphrazer/binary-ninja-headless-mcp)
requires a headless-capable license for real analysis. It does not remove the
Personal-edition display requirement.

### Proposed distribution and runtime ownership

Use [`requireFile`](https://github.com/NixOS/nixpkgs/blob/master/doc/build-helpers/fetchers.chapter.md#requirefile)
for the paid ZIP. It is a fixed-output dependency satisfied by a manually imported
file, with a reproducible hash and actionable missing-file error. A signed private
download URL should not become a public flake input. Pin public plugin/API source
normally. Import the ZIP with `nix-store --add-fixed sha256 <archive>` using the
filename expected by the derivation. Keep the license and authentication data
outside derivations and the store; do not publish the paid runtime closure.

The current local nixpkgs checkout already has a Free-edition 6.0.10601 package
at `pkgs/by-name/bi/binaryninja-free/package.nix`, using `autoPatchelfHook`.
It is a packaging reference, not proof that the Personal Python bundle patches
identically. The experiment establishes that an updated FHS runner
is also a viable starting point.

Require a state directory for each session. Suggested ownership:

```text
<state>/
  bn/                  settings, managed plugins, runtime license link
  config/, cache/, data/
  runtime/             Wayland and bridge sockets, process lock
  tmp/, logs/, artifacts/
```

Set `BN_USER_DIRECTORY`, the XDG directories, and `TMPDIR` for child processes.
`BN_USER_DIRECTORY` alone does not cover Qt state: the experiment produced
`config/Vector 35/Binary Ninja.binja-investigation.conf` under the private
`XDG_CONFIG_HOME`. `BN_QSETTINGS_POSTFIX` can further distinguish installations.
Use an explicit license-path input, with the ambient dotfile as an optional
default. Keep analysis databases as explicit durable outputs, separate from
process scratch. Own startup, readiness, process cleanup, state locking, and
plugin versions in the wrapper. Avoid global sockets and port assumptions.

This isolates writable application state; the FHS environment itself does not
restrict filesystem access. Strong filesystem hermeticity would require an
additional namespace/container boundary and a controlled environment.

Keep packaged binaries immutable and upgrades explicit. Disable update checking
with `network.enableUpdates=false`; treat the separate
`binaryninja.update.set_auto_updates_enabled(False)` control deliberately too.
In the test, the updater API still reported true while network update checks were
disabled, so those are not interchangeable switches. The persistence behavior of
the updater flag in an immutable package was not tested. Do not make the runtime
writable merely to accommodate self-update. Pin the archive/API/plugins together
and validate new versions against copies of databases before changing a workspace.

### Python and activation

Run whole scripts inside the GUI's Python VM against an explicit BinaryView.
Return bounded stdout, a JSON result or artifact path, and tracebacks. Avoid
driving analysis through interactive console text. Marshal UI work to the main
thread; do not put long analysis waits there. Serve API discovery from the
distribution's matching Python source/docstrings and local API docs. The old
API checkout was stale enough that silently using its current checkout would
have been a poor reference.

[Official OpenAI MCP documentation](https://developers.openai.com/codex/mcp/)
supports project-scoped configuration, `enabled=false`, and tool allow/deny
lists. CLI `-c` overrides are available in the installed 0.154.0 CLI, so a
dedicated launcher can enable a configured server only for the requested session.
The inspected Codex source defers regular MCP tools when the model supports tool
search and the provider supports tool namespaces (`core/src/mcp_tool_exposure.rs`
and `core/src/tools/spec_plan.rs`). There is no verified guarantee here that
every Codex host exposes those capabilities or can activate a disabled server
mid-conversation. Deferral also does not mean the backend stays unstarted.

[Skills support progressive disclosure and explicit invocation](https://developers.openai.com/codex/skills/):
`policy.allow_implicit_invocation: false` in `agents/openai.yaml` prevents implicit
skill invocation. This controls the skill, not an independently configured MCP
server. A CLI plus an explicitly invoked skill is the simplest route with no
Binary Ninja MCP schemas in unrelated sessions. A small skill listing may still
be present where the skill is installed. Scope installation/activation to the
workspaces that need it if even that is unwanted.

The next useful implementation experiment would package the runtime, exercise
`banteg/bn` against it, and demonstrate explicit target selection, Python API
discovery/execution, database save/reopen, and optional visual access. Evaluate
that result before choosing the default agent interface. These are
recommendations for discussion, not newly authorized implementation tasks.

## 2026-09-12 — CLI, plugin, and API boundary

The user accepted `requireFile` and delegated the packaging method. They prefer
to borrow from banteg/bn and maintain the resulting interface locally rather than
depend on its release process. Both desktop Wayland and a private compositor are
wanted. State selection may be ambient through configuration or environment.
The immediate task remains interface design, with particular attention to target
selection, arbitrary Python, API discovery, and whether MCP earns its place.

### Proposed boundary

Use a short-lived Python CLI, a small resident Python plugin inside the GUI, and
JSON requests over a Unix socket under the chosen state directory. The CLI's
interpreter never imports Binary Ninja or exchanges Python object proxies with
it. Executed analysis code runs in the distribution's bundled interpreter.

The resident plugin owns target resolution, execution scheduling, response
capture, and the small amount of process state those require. CLI command bodies
can be ordinary Python scripts sent as source with separate JSON arguments.
This avoids maintaining an RPC operation for every Binary Ninja API call and
allows most command code to change without reloading the resident plugin.
Compile submitted source with a meaningful filename for tracebacks. Retain
upstream notices for any code copied from MIT-licensed banteg/bn or other sources.

There still needs to be a receiver in the running GUI. The built-in MCP catalog
has no Python executor. The shipped user guide documents forwarding files and
URLs to an existing GUI process, not general Python execution. `startup.py` can
bootstrap a receiver but is not itself a per-command transport. The existing
interactive console adds GUI-controlled magic variables and analysis updates;
using it as the execution protocol would unnecessarily import those semantics.

### State and target selection

Separate application state from command selection. Open BinaryViews, analysis,
and unsaved edits live in the GUI process; saved analysis lives in databases.
Each request specifies its target, resolved once and retained for the operation.

- A state directory selects the GUI instance. Allow a CLI override, a project
  configuration value, or an environment variable; fail clearly if none resolves.
  Do not search the whole machine and choose the first process found.
- `targets` returns process-scoped view handles, full filenames/database paths,
  view types, and the GUI-focused view as descriptive information.
- With exactly one eligible analysis view, omitted target selection is convenient.
  With several, omission is an error. Ignore a redundant Raw view for this default
  when its corresponding analyzed view is open.
- Accept an explicit handle or unambiguous filename/path selector. Ambiguous
  selectors fail, and stale handles fail after closing/reopening or restarting.
  A process generation identifier prevents handle reuse from selecting new data.
- Do not introduce a shared `use` command. GUI focus is accessed deliberately,
  e.g. an explicit `--target active` or a UI-context query, resolved once per call.

Changing GUI tabs must not redirect a request. Response provenance should make
the resolved target visible without adding a large metadata envelope to every
small output. Target identity does not freeze ongoing analysis or stop a human
editing the same database.

### Execution and output

Supply `bn`, `bv`, and `args` in a fresh execution namespace, plus a small helper
for invoking UI work on the main thread. Return explicit `result` data, stdout,
and tracebacks. Fresh namespaces avoid depending on a previous command's local
variables; they are not fresh interpreters, and imports and database edits persist.
Long analysis waits run on a worker. Serialize submitted scripts initially, while
keeping status inspection responsive. This does not serialize unrelated GUI work.

Preserve a request identifier for long-running work. A client timeout/disconnect
is not proof execution stopped; do not automatically replay a submitted mutation.
Inspection/retrieval of an existing request is preferable to running it twice.
Cancellation must describe what it can actually interrupt: arbitrary native API
calls cannot be safely killed by terminating a Python thread. Avoid promising
automatic rollback of arbitrary Python, which can also write external files.

Default to compact text for inspection, JSON on request, and explicit artifact
paths for large results. Python can submit a source file or stdin. Start with
session/file lifecycle, targets, API lookup, Python, and a few common reads such
as decompile/xrefs rather than mirroring the entire API as CLI verbs.

### API discovery

Expose symbol lookup, member listing, and search over the documentation and Python
sources shipped with the selected distribution. Each lookup identifies the Binja
version and source location. Use runtime introspection where static documentation
is insufficient, especially for UI extension classes; enumerate descriptors
without evaluating every property just to list members.

The shipped `BinaryView` source contains 483 declared methods/properties (including
setter definitions), illustrating why a hand-maintained tool catalog cannot be
the API reference. A scratch AST lookup retrieved
`BinaryView.get_functions_containing` and its docstring without importing Binja.
The fetched public update API page was labeled v5.3, reinforcing the need to prefer
the archive's matching docs. Do not require a running GUI for ordinary static
documentation search. The future skill should direct the model to these commands
and collect observed API mistakes, rather than duplicate the API manual.

### Display and update information

Use the same managed GUI/plugin in both modes. Desktop mode connects to a supplied
Wayland socket; private mode starts labwc and optionally wayvnc. Both force the
native Wayland Qt platform. The previous live run used native Wayland. Desktop
socket forwarding from this container has not been tested. Display choice is made
when starting the process; moving an existing GUI between compositors is not part
of the proposed interface. A deliberate UI navigation command can focus a target
and address for the human without changing analysis-command defaults.

The supplied `binaryninja/update.py` exposes `UpdateChannel.updates_available`,
`latest_version`, `latest_version_num`, `get_time_since_last_update_check`, and
`is_update_installation_pending`. The pending-install flag describes an already
downloaded update, not merely an available release. The Python wrapper alone does
not establish whether querying availability reads cached GUI state or initiates
network traffic. Implement this as a cached, bounded metadata check, with installed
version, latest stable version, check time, and explicit unknown/error status.
Surface it through session status/startup and teach the skill to relay an available
update. It must not block analysis commands or call installation functions.

### MCP decision

Propose no MCP in the first interface. Persistent analysis state belongs to the
GUI process and does not depend on a persistent CLI client or MCP connection.
MCP's potential benefit here is standard client integration: schema discovery,
rich results/resources, authorization, and task handling. Shell/file access already
covers the immediate workflow; no unique requirement currently calls for MCP.
An adapter can be added over the same CLI/client interface if a concrete need appears.

The [MCP 2026-07-28 release](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
removed protocol-level sessions and recommends explicit application handles.
Binja's tested built-in server negotiated the older 2025-11-25 protocol. Neither
version makes shared implicit target selection desirable for this composition.

These are concrete interface recommendations, not implemented commands. The
remaining implementation probes are target lifecycle under close/reopen, worker/UI
scheduling, update-check behavior, and desktop display forwarding.

## 2026-09-12 — Implementation handoff

The user accepted the CLI/plugin design, confirmed the RPC socket belongs under
the state directory, and requested a design document and task graph for the next
session. They designated this a vibe-coded project where agents make commits.

[docs/design.md](design.md) is now the implementation reference. Deeds milestone
`r2neck` contains eight implementation parts: packaging, session/display lifecycle,
RPC/targets, Python execution, workflow commands, installed API documentation,
update notices, and the agent skill with integration verification. `cmgxfc`
(packaging) is the first ready task. API documentation can proceed independently
once packaging is available.

AGENTS.md records the commit policy and links the handoff. The initial packaging
choice is an immutable vendor tree with an FHS runtime, retaining bundled Python
and Qt. No production launcher, CLI, plugin, or skill has been implemented yet.

## 2026-09-12 — Scope and entry-point refinements

The user confirmed static analysis only. Complex image loading can be prepared
through preprocessing, the API, or manual GUI work and saved as a BNDB. Commands
should require completed analysis by default, including custom Python; incomplete
work needs an explicit override. Address handling should begin with Binja's own
conventions and remove concrete ambiguities as they arise.

The entry point is now `binja --help` leading to `binja skill`, a guide printed by
the installed CLI without requiring separate skill installation. The user
authorized subagent usability trials after the first command set works. The
initial RPC task now includes an installed-CLI check from another agent workspace.

Undo and GUI interaction checks remain opportunistic. Extra Python capabilities
are deferred until needed. Save cadence is unresolved because saves can take
minutes; the first implementation will expose dirty/save status, make slow saves
inspectable, and guide deliberate saves at meaningful work boundaries. It will not
introduce an automatic save policy at this stage.

Updated the design and existing task bodies without adding implementation phases.
Also corrected a truncated archive hash in the packaging task after recomputing
it from the supplied ZIP; the original investigation log already had the full hash.

## 2026-09-12 — Usability-first implementation order

The user requested an earlier usability-test MVP, with subcommands added
incrementally afterward. Milestone `r2neck` now ends at a verified private-session
Python/save workflow and bounded subagent implementation review and usability
trials. Help and the packaged guide begin in the CLI skeleton and evolve with
implemented commands. API lookup initially provides search/show; execution keeps
explicit targets, readiness, and recoverable request IDs. The first live execution
also probes save/reopen before convenience wrappers expand.

The trials no longer depend on update notices, desktop/VNC, UI commands, common
analysis wrappers, per-view close, or richer API lookup. Follow-up deeds `zbqnx2`,
`an2dc3`, `32k3q7`, and `t7h2fr` retain those features and depend on the trials.
The design describes the broader intended interface; deeds define delivery order.
No runtime implementation was added in this planning change.

## 2026-09-12 — Installed MVP, before the operator UX check

Implemented the pinned Personal Nix package, separate Python CLI, supervised
private Wayland session, resident Unix RPC receiver, explicit view registry,
serialized Python execution, offline API search/show, and open/save/stop workflow.
`README.md` and the single packaged `binja/guide.md` are the usage references.
Target enumeration/UI dispatch borrow from banteg/bn with its MIT notice retained
under `licenses/`. The vendor tree and its Python/Sphinx references come directly
from the supplied archive; there is no dependency on investigation paths or `~/src`.

The installed CLI was exercised from `/tmp` and disposable external workspaces.
Live version remained 6.0.10601 Personal, with bundled Python 3.13.14 and native
Wayland. Separate state directories launched independently; repeated start reused
the verified owner. Missing-license startup failed before GUI launch. License
injection is a runtime link, Qt writes landed under the selected XDG config, and
the RPC socket/state permissions were 0600/0700. The live updater flag was false
and Python user-site loading was disabled. Startup and forced cleanup use retained
child process objects and a locked supervisor socket, never a PID-file kill.

`tests/smoke.py` provides the repeatable installed-interface verification using
copied benign inputs, without executing them. The final expanded run passed in
`/tmp/binja-smoke-mu2x8d2i`. It covered matching offline lookup; two views with the
same basename; explicit Raw handles; focus changes; queued target retention;
readiness at execution time; held-analysis refusal/override; queued cancellation;
pending-work shutdown refusal; fresh scopes; file/line tracebacks; output isolation
including UI callbacks; output truncation/artifacts; non-JSON result rejection;
disconnect before acknowledgement; recovery without repeating a mutation; failed
saves; repeated BNDB saves; stop/restart/reopen; persistent comments; unchanged
input hashes; GUI close/reopen invalidation; and stale-generation rejection.

The same live suite used reduced retention limits to verify result expiry still
refuses replay and the finite ID ledger refuses further submissions. It also
changed discovery metadata to a stale generation and verified that forced stop
failed without killing the owner. Record/artifact retention is 64 finished
requests per GUI lifetime, with 4096 deduplication IDs and 64 pending requests.
Streams retain 1 MiB each; JSON results retain 8 MiB, with artifacts above 16 KiB.

Two runtime observations shaped the implementation: comment edits set
`analysis_changed` without setting `modified`, so orderly shutdown checks both;
Raw views remain in InitialState because they have no analysis pipeline. An early
API-only comment/save/restart/reopen probe passed before the command wrappers were
added. Self-review also fixed a cancellation race at entry to the readiness gate
and kept request results nonterminal until captured output was finalized.

No subagents were used. The user requested a working MVP for a personal UX check
before subagent reviews/trials. Implementation deeds are closed; `2nbgtk` and
`r2neck` remain open for that checkpoint and the later trials. Desktop/VNC,
per-view close as a CLI command, convenience analysis commands, richer API lookup,
and update notices remain deferred. Large-binary analysis/save performance,
native crashes, modal dialogs, disk-full behavior, and hostile filesystem changes
have not been comprehensively tested. Recovery is scoped to a live GUI and does
not make interrupted arbitrary Python transactional.

## 2026-09-13 — Preliminary documentation and session ergonomics review

Reviewed README, the packaged guide, design, maintainer instructions, and the
implementation behind documented commands. Removed repeated upstream versions,
investigation workspace paths, milestone status, and unimplemented examples from
reference docs. README retains the exact archive filename needed for installation.
The design now describes architecture; future command work remains in deeds.

An export in one shell tool invocation was absent in the next. Commands now select
`.binja` in their current working directory by default, with `--state-dir` for an
explicit location. The CLI no longer reads `BINJA_STATE_DIR`; the supervisor still
sets it internally for the GUI plugin. This is a change to the initial interface:
existing sessions at other paths require `--state-dir`. Recovery hints include
the resolved session path, quoted for the shell. The guide also explains that
script file access occurs in the GUI process, with its startup working directory
and bundled interpreter.

`nix build`, Python compilation, documentation link checks, and `deeds check`
passed. Focused checks verified selection across independent CLI processes,
changed working directories, explicit paths, ignored ambient state configuration,
socket path limits, and recovery hints containing spaces. The updated live suite
passed in `/tmp/binja-smoke-drw4nb58`, including workspace defaults, explicit access
to the same session, runtime/API version agreement, script working directory, and
the existing target, recovery, save/reopen, and shutdown checks.

Found a separate recovery bug: exhausting the request-ID ledger also rejects
`save`, despite an error directing the user to save and restart. Filed `2ajrs7`;
the guide now says to save and restart before reaching the limit. Broader review
of concurrency, crash recovery, and persistence failure modes remains pending.
No subagents were used. The user explicitly kept review/usability trials gated
while this preliminary pass is under review; `2nbgtk` and `r2neck` remain open.

## 2026-09-13 — Remove the lifetime request cap

Removed `MAX_IDS` instead of increasing it to a nominal integer maximum. It
bounded the deduplication dictionary, not an ID counter. A lifetime request cap
could prevent saving a dirty database. Fingerprints now grow with accepted
requests until restart, while pending requests and retained full results remain
bounded at 64 each. Expired IDs still cannot replay. The guide reflects the memory
tradeoff without prescribing periodic restarts.

The smoke check seeds more than 4096 historical IDs, saves a dirty target, checks
that an expired request still cannot replay, and verifies the saved annotation
after normal shutdown and restart.

`nix build`, Python compilation, and the live smoke suite passed; live evidence
is in `/tmp/binja-smoke-jemuwrj_`. No subagents were used.

## 2026-09-13 — Threading and operation ownership research

The user questioned whether the execution model matches Binary Ninja's threading
and GUI consistency constraints, proposing reconnect/wait for at most one ongoing
operation. This investigation changes no runtime code or protocol.

Inspected official documentation and the installed Python API. The local API
checkout's working tree is older and has unrelated changes, so source inspection
used tag `stable/6.0.10601` (`2ddf304b3275aa184e95570404539cbc4beb64c6`) without
changing the checkout. Its `mainthread.py`, `plugin.py`, and `scriptingprovider.py`
match the installed files byte for byte.

Findings:

- Binary Ninja explicitly supports off-main-thread execution. The
  [mainthread reference](https://api.binary.ninja/binaryninja.mainthread-module.html)
  distinguishes the GUI thread from native worker queues and dedicated Python
  threads. [BackgroundTaskThread](https://api.binary.ninja/binaryninja.plugin-module.html#binaryninja.plugin.BackgroundTaskThread)
  wraps a Python thread and reports progress in the status bar, without requiring
  a modal dialog.
- The [native scripting provider](https://github.com/Vector35/binaryninja-api/blob/2ddf304b3275aa184e95570404539cbc4beb64c6/python/scriptingprovider.py)
  owns an `InterpreterThread`. `perform_execute_script_input` rejects new script
  input while that interpreter is busy. This is a per-interpreter rule, not a
  global application lock shared with our executor or other plugins.
- [run_progress_dialog](https://api.binary.ninja/binaryninja.interaction-module.html#binaryninja.interaction.run_progress_dialog)
  executes its callback on a background thread. The matching
  [ProgressTask header](https://github.com/Vector35/binaryninja-api/blob/2ddf304b3275aa184e95570404539cbc4beb64c6/ui/progresstask.h)
  documents that the dialog blocks other UI interaction.
  [Qt modality](https://doc.qt.io/qt-6/qdialog.html#modal-dialogs) governs input to
  other windows; it is not itself a lock on the analysis database or on other
  API callers.
- Thread rules are API- and context-specific. Native UI calls belong on the UI
  thread. [update_analysis_and_wait](https://api.binary.ninja/binaryninja.binaryview-module.html#binaryninja.binaryview.BinaryView.update_analysis_and_wait)
  forbids UI and worker contexts; the native worker-pool restriction must not be
  confused with a dedicated Python interpreter thread. The
  [notification contract](https://api.binary.ninja/binaryninja.binaryview-module.html#binaryninja.binaryview.BinaryDataNotification)
  warns that callbacks hold a global lock and can deadlock if they wait for another
  thread that needs it. `create_database` separately warns against holding a view
  lock across its main-thread work. There is no basis here for treating an arbitrary
  multi-call script as an isolated transaction.

A bounded live probe in `/tmp/binja-threading-49xd0kqv` used an in-memory two-byte
view in a separate managed GUI. `BackgroundTaskThread` ran off the main thread,
read the view, and observed no modal widget. `run_progress_dialog` also ran its
callback off the main thread and exposed a window-modal `ProgressDialog`. While
that dialog remained open, a separate Python thread successfully set and read a
comment on the same disposable view. UI callbacks continued to run on the main
thread. The dialog closed and the owned GUI was stopped. This demonstrates the
absence of automatic exclusion for that API access; it does not certify all
concurrent mutations, serialization, or native database internals as safe.

The current plugin has one execution thread, so its queued CLI scripts already
run serially. It admits a backlog of 64 and retains 64 finished results plus the
fingerprint dictionary. Its locks protect its own records, not whole-script access
against native console commands, GUI actions, other plugins, or threads spawned
by a submitted script. The previous recommendation to eliminate reconnect/wait
was too broad: attachment to an already-running operation is useful independently
of queues and resubmission semantics.

Recommended direction for discussion: one active operation per managed instance,
no backlog, an explicit busy response naming that operation, and reconnect/wait
against its ID. Retain its completion across a disconnect so a completion/reconnect
race is recoverable. Remove resubmission fingerprints and arbitrary job-history
management. Keep operation ownership distinct from thread placement; plugin-level
serialization alone cannot promise exclusive access against independent GUI/plugin
writers. Interactive GUI coordination needs an explicit policy before desktop
support. No implementation changes or subagent trials were performed.

## 2026-09-13 — Simplify request bookkeeping

The user asked for a second opinion on the request system and its former
4096-entry ID ledger. Assessment: Binary Ninja locks per API call and offers no
isolation above that (no transactions, interleaved undo actions, `create_database`
lock warnings), so a script is the unit of intent and one serial worker per
session is the right scale. Parallel work belongs in separate state directories.
Script-level concurrency inside a session would buy little (shared GIL, analysis
already parallel in the native worker pool) and cost nondeterministic
interleaving of mutations.

Under that model the content fingerprints, the "expired" status, and the separate
ID dictionary carried no guarantee a plain record dictionary does not. GPT
(Codex, xhigh effort, via ception) removed them per `vtw63f`: terminal records now
keep id, status, target, timestamps, and truncated error text for the GUI
lifetime, and only the newest 64 finished requests keep outputs and artifact
directories. Pruned records carry `output_pruned: true`. Duplicate IDs return the
existing record before target resolution, so reuse against a dead handle still
returns the original outcome. The `open`/`save` renderers no longer assume a
reused ID belongs to the same command. Queue depth and the pending cap are
unchanged; `t87ez9` defers that choice until agent usage is observed.

`nix build`, Python compilation, and the live smoke suite passed in GPT's run
(`/tmp/binja-smoke-4knpkb0g`) and in an independent rerun after review. The
suite now checks retained metadata for completed, failed, and large-output
requests, artifact deletion, reuse without replay, save after 4096 historical
records, and rendering of pruned records. Review found no divergence from
intent; one instruction was followed literally (a startup error message was
reworded to make a grep clean), which is harmless.

## 2026-09-13 — First usability trials with GPT

Three GPT subjects (Codex, `gpt-6-astra`, default effort, via ception) each ran
one task in its own directory under `/tmp/binja-trials/`, with no repository
`AGENTS.md`, no design context, and the installed CLI reached through a neutral
`bin/` symlink. Subjects were told they were trial participants whose opinion
of the tooling was the deliverable, asked to treat binja as a black box, and
asked to write a friction report. Briefs, reports, and request snapshots are in
`temp/trials/`. Two setup notes: the direnv devshell had a stale nix-direnv
cache and served a pre-`osummwtp` build that demanded `--state-dir`, so the
trials used an explicit fresh build; and the brief called `sample` a C program
when it is C++, which every subject noticed and none was derailed by.

| Trial | Input | Task | Result | Wall time |
| --- | --- | --- | --- | --- |
| A | `sample` (17 KiB C++) | explain `main`, rename, comment, save, restart, verify | success, 9 renames and 19 comments verified after restart | 4m 01s |
| B | `bash` (1.1 MiB) | per-import caller counts for four libc imports, rename top five, save, verify | success, counts cross-checked against `get_code_refs` | 3m 21s |
| C | `rg` (6.4 MiB) plus `sample` | inventory both, save both, report analysis time | success, `rg` analysis 41.9 s crossed the 30 s client wait and was recovered with `request --wait` | 3m 27s |

No task needed a workaround, a forced stop, a repeated mutation, or a look at
the source. The only failing CLI invocations were guessed API lookups
(`Function.set_user_name`, `Function.size`) and `status` after a clean stop.
Subjects rated the transport, targets, request IDs, and save/reopen as working
on the first attempt, and located the effort in reconstructing Binary Ninja
Python idioms. Consolidated friction, filed as `r23mma` (status after stop and
view-versus-file counts), `nvafxz` (property writability, enum members, search
truncation in `api show`/`search`), `6jqt5a` (target snapshot labeling, JSON
timeout marker, elapsed/progress, "headless" wording), and `rcxvky` (guide
recipes: addressed HLIL with disassembly, rename/comment, import callers,
inventory). The subjects' own first-fix picks were `status` after stop (A),
property writability (B), and request observability (C).

Queueing observations for `t87ez9`, from the 15 s request snapshots and the
command trails. Across 18 session-bound requests in three sessions, no request
was submitted while another was running or queued; the smallest gap after the
previous completion was 70 ms, from sequential commands in one shell. All three
subjects did run session-less `api` lookups in a second shell while `start;
open` ran in the first, and subject C ran `status`, `targets`, and `requests`
during the 42 s analysis. Asked afterwards, all three said they serialized
target-bound work because later steps depended on earlier results, not because
of anything the tool said; C expected a `py` submitted during analysis to be
queued behind the readiness gate. All three prefer queueing over a busy error,
on the condition that the receipt says "queued", names the retained target and
what it waits behind, and supports cancel. All three would accept a busy error
only if it states unambiguously that the request was not accepted and will not
execute, because otherwise mutation retries become ambiguous. None used
`requests` for recovery in a crowded session; all three want it to lead with
running and queued requests (ID, target, phase, elapsed) and to filter or limit
the completed history.

Assessment: the observation window supports a small queue with an explicit
queued receipt over a no-backlog busy response; the decision stays with the
user in `t87ez9`. Not covered by these trials: contention between two clients
on one session, cancellation, multi-file sessions beyond C's two targets, and
the bounded implementation review that `2nbgtk` also lists.

## 2026-09-13 — Small, observable serial queue

Implemented the user's decision to retain queueing and the serial worker. Chose
8 unfinished requests including the active request, preserving the existing cap's
counting rule (normally one running plus seven queued), and five newest finished
records after active/queued work in the default listing. `requests --all` retains
full history access. Cap rejection guarantees non-acceptance/no execution and
names the running request and queued count; the rejected ID remains reusable.
Accepted receipts in both formats expose queue position, immediate predecessor,
retained target snapshot, phase, and elapsed seconds. Queued cancellation still
frees capacity. Elapsed time begins at worker pickup, including readiness waits,
or submission for unstarted work. Client wait expiry now has an explicit marker
and recovery command in both formats.

Renamed request `target` to `target_snapshot`, with a capture stage (`submission`,
or `open` after loading/attachment) rather than refreshing historical descriptions.
Protocol version 2 rejects mismatched packages; sessions need restarting after
upgrade. The start line now describes the GUI on its private Wayland compositor.
Updated the packaged guide and design reference; no worker concurrency or new
analysis commands were introduced.

`nix build`, Python compilation, diff whitespace checks, and the live smoke suite
passed. External-workspace evidence: `/tmp/binja-smoke-v0rketc6`, using the default
license. Added deterministic blocked-worker checks for human/JSON queued receipts,
expiry, cap rejection, duplicate recovery at capacity, cancellation, safe reuse of
a rejected ID, and default/full listing order. Existing persistence and recovery
checks also passed. No evidence argues against the decision, but the original
trials had no overlapping submissions and this suite does not measure sustained
multi-client contention or establish an optimal cap. No subagents or commits.

## 2026-09-13 — Stress trial against the small queue

One GPT subject (same setup as the first trials, fresh build of the queue
change) was asked to design its own stress workload on `rg` around a real
deliverable: a map of the 40 largest functions with callers, callees, strings,
and a purpose guess. The brief asked for at least one per-function phase, one
multi-shell phase, and a push past what the task needs. Report, map, scripts,
and the request history are in `temp/trials/runD/`.

Outcome: the map was produced and the session survived 249 accepted requests
in 297 s (243 completed, 5 deliberate failures, 1 cancelled) with no crash,
stuck worker, or forced stop. Of the 249, 104 were submitted while another
request was unfinished, up to the cap; queue wait was under 10 ms at p90 and
23.6 s at the maximum behind a deliberate sleeper. `SystemExit` and
`KeyboardInterrupt` in scripts did not kill the worker. Twelve concurrent
submissions of one request ID appended once. The cap, the wait expiry marker,
the recovery command, and the queued receipts all behaved as documented, and
the subject called the rejection text clear enough that it did not blindly
retry.

Where the tool limited the analysis, in the subject's ranking and ours:

- Small-request latency. 100 sequential trivial calls took 25.2 s, median
  245 ms wall against 1 ms worker time. Confirmed cause: `wait_for` in the CLI
  sleeps 200 ms before its first poll. This pushed the subject away from
  per-function querying toward batching and six-to-eight parallel shells
  (24 to 33 calls/s). Filed `vf2ttr`.
- Result retention. At 33 calls/s the 64-result window covers two seconds;
  earlier analysis results were pruned before the subject reread them, so it
  copied everything to disk immediately. Filed `9353hf`.
- History export. `requests --all --json` has no error text, pruned flag,
  request kind, or trace of rejected submissions, so the dump could not explain
  the run; `elapsed_seconds` changes meaning by phase. Filed `ev7w2f`.
- Head-of-line blocking and the cap. A `--no-target` read waited behind a 6 s
  CPU loop, and a 32-shell burst behind a sleeper got 7 accepted and 25
  rejected. Explicit and recoverable; policy question filed as `8vftez`.
- Smaller: `cancel` exits 1 on success; the `GENERATION:rUNIQUE` request-ID
  format is only revealed by the error (`9wkssd`); `status` after stop still
  reads as a fault (`r23mma`); stream truncation keeps a 16 KiB inline preview
  plus the artifact, which the guide does not say.

Not covered: multi-client contention over hours, memory growth, GUI crash
recovery, and a second session on the same binary.
