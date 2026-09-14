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

## 2026-09-13 — Rust client and supervisor with the usability changes

Replaced the Python CLI and supervisor with one Rust binary, including a hidden
supervisor subcommand. The resident plugin and command scripts remain Python;
the static Python API builder runs during packaging. Nix uses
`rustPlatform.buildRustPackage` with `Cargo.lock`, and the devshell includes
cargo/rustc. Installed resources are relative to the binary; development builds
can use the checkout's plugin directory and copied build metadata.

The client uses clap, serde_json with arbitrary integer precision, and blocking
SEQPACKET sockets with read deadlines. It consumes protocol-3 admission and final
replies without a first-poll sleep. The supervisor retains flock authority,
retained child processes, process-group shutdown, and owner-only endpoint cleanup.
Both shutdown calls pin the generation returned by the live owner handshake.

The rewrite includes concise human outcomes, queued-only acceptance receipts,
full verbose/JSON records, artifact paths instead of duplicated stream previews,
successful cancellation exit 0, custom ID construction guidance, stopped-session
status, file/view counts, forensic history/rejection rendering, and API property
writability/enum members. API show keeps a source:line pointer; search states its
shown/total count. Default request listings summarize cap rejections by count;
`--all` prints retained events, while verbose/JSON keep the full envelope.
Artifact files and references survive inline pruning until lifetime cleanup.

The adapted runD 100-call tight loop used the same copied sample (SHA-256
`aaae63bd63899939214f8b362be589a77e1df1de8db48688d9966a9895cba2a4`)
and workload, `result={"i":N,"count":len(bv.functions)}`. Each call launches the
installed CLI in a disposable external workspace. The controlled Rust measurement
ran after builds had finished; an earlier run overlapping a build was excluded.

| Measure | Python baseline | Rust |
| --- | --- | --- |
| 100-call wall time | 24.234950 s | 0.162663 s |
| Median CLI wall time | 243.035 ms | 1.491 ms |
| Median worker time | 0.737 ms | 0.319 ms |

The loop was about 149 times faster overall. The plugin is still Python; the
worker-time difference is not evidence of a language speedup there. Harness and
raw baseline/Rust results are in `temp/phase-a/`; the excluded run and supplementary
evidence are in `temp/phase-b/`.

A separate human-output comparison used the same small query. Combined stdout
and stderr shrank from 456 to 109 bytes. Using `o200k_base` as a tokenizer proxy,
not a claim about the trial model's tokenizer, that was 187 to 55 tokens; API
show Function.name was 128 to 64, open 161 to 57, and save 198 to 57. Stop grew
from 16 to 22 tokens because it now identifies the state path. Raw command
outputs and counts are under `temp/phase-b/`.

Verification: Nix builds and the two Rust transport tests passed, as did nine
Python protocol/execution/index tests. The installed smoke suite passed from
`/tmp/binja-smoke-9gq196p0`; the live bridge suite passed from
`/tmp/binja-protocol-c0xbdb2p`. Development resource lookup, API show, and a live
start/py/stop were also checked through the debug binary with checkout resources.
The requested intermediate code commit was made after the first green smoke run,
before documentation and deed closure.

Smoke assertions changed for the protocol-3 raw disconnect probe, the forensic
listing envelope/counts, cancellation command exit 0 (retrieval remains exit 1),
retained artifact files/references instead of deletion, and lean human strings
without repeated IDs or snapshot metadata. The original targeting, mutation,
readiness, failure, deduplication, persistence, stale-generation, and unchanged-input
checks remain. Added checks cover stopped status, file/view counts, API metadata
and source pointers, search truncation, idle receipt silence including verbose,
full verbose records, integers beyond 64 bits, large file/stdin sources,
artifact-only human stream rendering, and a full history above 4096 rows.

Not verified: a complete replay of runD's stress workload, hours-long contention
or memory growth, supervisor/GUI crash recovery, or forced-kill escalation against
a deliberately unresponsive native child. Guide recipe validation (rcxvky) and
the bounded adversarial implementation review remain phase C work. No review or usability subagents ran in this phase.

## 2026-09-13 — Guide recipes and CLI diagnostics

Validated the four packaged guide recipes with the installed Rust binary from
`/tmp/binja-recipes-pnmzqge5`, outside the checkout. The C++ ELF entry function
printed five addressed HLIL lines and twelve disassembly instructions. Renaming
it to `reviewed_entry` and assigning its function comment survived a database save,
stop/start, and reopen. Its inventory printed entry 0x401080, 29 functions, main
largest at 1613 basic-block bytes, four dependencies, and import type-library
attribution where available. On system Bash, malloc exposed all three import
symbol kinds; the caller recipe printed 47 call sites and 47 code references with
the stub excluded. Recipe transcripts are under `temp/phase-c/`. The guide now
groups recovery behavior without repeating receipt, cancellation, and retry
explanations, and states the one-worker batching constraint.

Read timeouts now name the request and recovery command; JSON acceptance events
include the existing flag. Status pluralizes file/view counts. Script tracebacks
omit leading executor frames, preserving downstream frames, exception chains,
and syntax-error locations. Four Rust tests and five Python execution tests pass.
The installed live smoke suite passed from `/tmp/binja-smoke-iepcy6lq`; added
assertions cover singular file output, both acceptance flag values, and the first
script frame. No existing assertion was weakened. Nix builds pass.

The timeout tests use a connected, nonresponding socket peer; a deliberately hung
GUI was not tested. The broader adversarial review (2nbgtk) remains separate.

### Independent review findings and dispositions

The independent reviewer reported four findings; all are fixed in this change:

- **Blocker: owned group members survived shutdown after the leader exited.**
  Termination now sends group SIGTERM, escalates after five seconds to SIGKILL,
  and waits for killpg(group, 0) to return ESRCH. The supervisor is a child
  subreaper and reaps adopted descendants as well as its retained child leaders.
  Shutdown errors retain the lock and defer cleanup instead of releasing
  ownership. A live smoke script spawns a SIGTERM-resistant subprocess from GUI
  Python and checks group disappearance before accepting stop; a Rust test
  separately exercises an already-exited leader.
- **Supervisor SIGKILL left labwc alive.** Both direct children receive
  PR_SET_PDEATHSIG/SIGKILL in pre_exec, with a parent-identity recheck covering
  death between fork and prctl. Spawning stays on the supervisor's main thread,
  which lives as long as the process. The packaged GUI launcher's existing
  bubblewrap die-with-parent behavior is retained. Smoke kills the supervisor,
  checks that both labwc and the GUI launcher disappear, then restarts cleanly.
- **Competing or late starts failed during initialization.** Both paths now
  wait for the winning receiver, validate its version, and reuse its generation.
  Readiness polling uses RPC without taking a transient flock, which could itself
  defeat a spawning supervisor. Smoke launches eight simultaneous starts plus
  two arriving after the control socket appears; all must succeed with the same
  generation, and the late starts must report reuse.
- **Pruning used submission order.** The worker now sorts terminal records by
  finished timestamp before pruning. A Python regression submits the eventual
  newest completion first, follows it with 65 cancelled records, then verifies
  its result survives while the two oldest cancellations are pruned.

Nix build, five Rust tests, six Python execution tests, the installed live smoke
suite (external workspace `/tmp/binja-smoke-l_sdbq2i`), and live bridge checks
passed. Evidence is under `temp/review-fixes/`. Existing smoke assertions remain;
the sequential startup was replaced with the concurrent case, and shutdown
coverage was extended. The guide's split flag was repaired and its JSON envelope
and output paragraphs compressed; the recipes are byte-for-byte unchanged.

This completes the implementation review and MVP milestone (2nbgtk, r2neck).
Convenience commands, desktop access, richer API lookup, and update notices remain
open follow-ups. This check did not exercise uninterruptible kernel waits,
descendants deliberately escaping their owned process group, or the other
long-duration/stress limitations recorded above. Parent-death signaling covers
the direct children; it is not a general descendant containment mechanism.

### Failed-supervisor startup grace

Bound the competing-winner wait to five seconds after observing our own spawned
supervisor's exit, while retaining RPC-only readiness polling. If no receiver
answers, start reports the child's exit status and the session logs path instead
of exhausting the 70-second startup deadline. The new smoke case blocks startup
with a file in bn/plugins and requires failure within eight seconds; measured
latency was 5.203 seconds. Nix build, all five Rust tests, and the full installed
live smoke suite passed, including concurrent/late starts. External workspace:
`/tmp/binja-smoke-4hijreua`; transcript: `temp/start-grace/smoke.txt`.

## 2026-09-13 — CLI surface evaluation against banteg/bn

Compared the installed surface (session lifecycle, `py`, `api`, request
bookkeeping; no typed analysis commands) with banteg/bn `bd91032` (v0.15.0,
about 35 commands: function/decompile/il/disasm/xrefs/refs/callsites/search,
typed data reads, mutations with preview/verify/rollback, bundles, schema). A GPT
review via ception reached the same ranking independently.

Findings. All three trial subjects asked for typed commands after succeeding
through Python (reportA.md:185, reportB.md:84, reportC.md:102); the recorded
effort was reconstructing Binary Ninja idioms, which typed commands remove.
Ranked gaps: code inspection with a shared ambiguity-rejecting resolver;
reference traversal with explicit inbound/outbound, code/data, call/reference
dimensions and import-stub exclusion; offline `api members`; inventories;
per-view close; type and local edits with native undo grouping. Deliberately
not borrowed: bn's preview/verify/rollback framework, bundles, schema, token
counting, `--caller-static`. Function resolution must reject ambiguity, and
lists must page. The user prefers decompilation first, MLIL as the strong
fallback, and LLIL rarely; that preference now sits in the guide.

Re-scoped `zbqnx2` into a milestone with parts 5bkxzv, 2wrz2e, fm4yyw, vmnn2h,
c6z866; filed scpm34 (screenshot and input for stuck GUI states, user
request) and 8ty558 (database search, frozen); staged 32k3q7.

## 2026-09-13 — Offline class member lookup (32k3q7, stage 1)

Implemented `api members CLASS [--match TEXT]` against the packaged static index.
The index now resolves explicit imports and records bases, C3 method resolution
order, and unresolved bases. Listings select overrides once, show direct members
first and inherited owners in MRO order, and sort names within each owner.
Filtering uses a case-insensitive literal substring of the member name, trimming
outer whitespace. Lists are untruncated; empty matches succeed, while absent,
ambiguous, and non-class symbols fail. Unindexed bases remain explicit coverage
gaps. No runtime introspection was added.

Verification: all four Python index tests and six Rust tests passed. The
regenerated development index was exercised through `cargo run`; BinaryView
lists 413 members. The installed offline smoke suite passed after `nix build`
(`/tmp/binja-smoke-hfl0brpk`), covering inherited ownership and property metadata,
multiple inheritance, both nonexistent Function members, ambiguous CacheImage,
native/unindexed symbols, and enum values. The builder fixtures also cover
relative imports, re-exports, nested classes, diamonds, and invalid inheritance.
Static review found no assignments masking indexed inherited members or borrowed
property accessors in the pinned distribution. No GUI or license was used.

The guide's API lookup paragraph now addresses the Function guesses without
duplicating API documentation. Runtime lookup stays deferred until a concrete
failure needs it.

## 2026-09-13 — Typed code inspection and GUI verification

Implemented 5bkxzv's `decompile`, `il` and `disasm` after design approval. They
submit packaged Python scripts with distinct kinds through the existing worker.
The final design uses no new envelope fields or structured error taxonomy:
Python prints the header/listing/continuation and returns lean structured rows;
Rust only suppresses duplicate result printing for these kinds. Function and
symbol ambiguity fails with inline candidates. MLIL is the default IL view.
Pagination rerenders the live function, without cursors. Linear disassembly uses
the view architecture, exclusive ends and explicit decode stopping reasons.

Started Binary Ninja 6.0.10601 Personal successfully in the checkout's `.binja`.
Opened `temp/samples/a/sample` and copied the requested bash 5.3p9 executable
from `/nix/store/v8llyqw71lygr2llhmcc8ya5bdlzq45v-bash-5.3p9/bin/bash` into
`temp/typed/bash` before opening it. Neither executable was run. Compared the
CLI with captured GUI linear views for sample's `main` at `0x40122e` and bash's
`can_optimize_cat_file` at `0x496890`: Pseudo C, HLIL, MLIL, LLIL and disassembly.
Screenshots and corresponding CLI records are `temp/typed/{sample,bash}-*.{png,json}`.

The first comparison exposed that a bare `DisassemblySettings()` omits casts
shown by the GUI. Switched to `default_linear_settings()`, disabling the native
address/opcode columns and collapse indicators and enabling WaitForIL. Pseudo C
now retains, for example, sample's `*(uint64_t*)((char*)fsbase + 0x28)` and
`(uint8_t)var_198 = 3;`. Native code, branch targets, IL indexes and instruction
bytes matched the inspected GUI content. GUI-only call-argument inlays such as
`dest:` are not native text and are omitted. Native HLIL/Pseudo C line anchors
are retained: the synthetic `fsbase` declaration has API anchor `0x401242`, while
the Pseudo C GUI gutter associates it with `0x40122e`. This is why addresses are
labeled anchors. The standalone renderer always expands the function body.

Bash had 2,046 functions. Chose `can_optimize_cat_file` as the median by
`total_bytes` (83 bytes), and `read_token.constprop.0` at `0x42b8c0` as the largest
(17,199 bytes). Measured UTF-8 stdout and the JSON encoder's actual result size,
including header/footer and result metadata, for every page of all eight
representations. The default is **64 rows**: all those pages stayed below the
16,384-byte inline threshold in both streams. At 100 rows, largest-function SSA
pages reached 17,818/21,570 bytes (stdout/result); at 80 rows, 16,687/19,705 bytes.

Largest-function measurements at 64 rows (bytes; maxima cover every page):

| Representation | Total rows | First stdout/result | Maximum stdout/result |
| --- | ---: | ---: | ---: |
| Pseudo C | 4,410 | 2,682 / 4,521 | 5,959 / 7,983 |
| HLIL | 3,569 | 3,689 / 5,998 | 6,511 / 9,389 |
| HLIL SSA | 18,629 | 5,059 / 7,337 | 7,472 / 9,878 |
| MLIL | 3,912 | 2,729 / 5,148 | 3,450 / 5,950 |
| MLIL SSA | 8,590 | 4,343 / 6,827 | 12,904 / 15,330 |
| LLIL | 4,166 | 2,423 / 4,810 | 2,933 / 5,464 |
| LLIL SSA | 9,105 | 3,530 / 5,923 | 10,813 / 13,294 |
| Disassembly | 4,730 | 3,443 / 5,318 | 4,029 / 5,867 |

The median function fits in one page in every representation; its maximum sizes
were 2,150 stdout bytes and 3,911 result bytes. Rechecked actual default CLI
requests for both functions in all representations: all remained inline.
Measurements, native renderings and probe scripts are under `temp/typed/`.
These measurements choose a useful default, not a guarantee for unusually long
rows; existing artifacts remain the fallback. No extra envelope metadata was
needed. The inspected bn implementation informed the comparison;
no new peer code was borrowed.

`cargo test` passed all five checks; Python execution/protocol/API-index suites
passed 6/5/1. `nix build` succeeded, then
`python3 tests/smoke.py --binja ./result/bin/binja --sample temp/samples/a/sample`
passed from its disposable external workspace, `/tmp/binja-smoke-jp6lw_4o`.
New smoke coverage compares Pseudo C with the independent language-function API,
checks native IL indexes/addresses for all six IL variants, paging and recovery,
artifact text/JSON, disassembly bytes and linear continuation, Raw decoding,
ambiguous names and same-address platforms, skipped analysis and invalid flags.
A separate one-byte `0x0f` input confirmed the undecodable-instruction stop.
Existing queue, save/reopen, retention and shutdown checks still pass. Verification
was on x86-64; other architecture decoders were not exercised.

Updated the packaged guide, README and design contract, retiring the addressed
HLIL/disassembly Python recipe. Saved scratch databases and stopped the checkout
GUI cleanly.

## 2026-09-13 — Private display recovery (scpm34)

Verified packaged labwc 0.20.0 with `WLR_BACKENDS=headless`, one output, and
`WLR_RENDERER=pixman` before implementing the interface. It advertised
wlr-screencopy v3, virtual keyboard v1, and virtual pointer v2. Grim captured a
1280×720 PNG; wtype and wlrctl connected successfully. Protocol evidence and
probe scripts are under `temp/gui-probe/`.

Added `screenshot [PATH]`, `input key KEY`, and `input click X Y` through the
generation-checked supervisor endpoint. Helpers use only its private compositor
socket and run with bounded lifetimes. Screenshots default to session artifacts;
explicit destinations refuse overwrite. Click coordinates use the scale-1 PNG.
The guide and Display modes reference document the recovery interface.

Live verification caught a keyboard delivery bug that protocol success alone
missed: Qt received wtype's first press as an already-held key in
`wl_keyboard.enter`, followed only by its release. An empty modifier event
before the requested press establishes the keyboard first. Escape then closed
a QMessageBox on a fresh session. A separate screenshot-guided click at
(637, 389) closed its OK button and returned 1024; ordinary Python subsequently
returned 42. No widget coordinates were queried. Screenshots `modal.png` and
`after-click.png`, plus `click-result.json`, retain that manual evidence.

With every GUI thread stopped by SIGSTOP, screenshot and input still returned;
status reported unknown modal, target, and request state in 1.011 seconds.
After SIGCONT, Escape closed the modal (QMessageBox.Cancel, 4194304), and Python
again returned 42. Evidence: `frozen-fixed.png` and `frozen-result.json` in the
same probe directory. Status now shares one asynchronous UI probe across polls,
waits at most 250 ms for it, and falls back to supervisor information if GUI RPC
cannot answer within one second.

The full installed smoke suite passed from `/tmp/binja-smoke-msnpgb4k`, including
the deterministic modal/capture/Escape recovery sequence, an explicitly blocked
UI thread, SIGSTOP/SIGCONT, invalid input, and screenshot overwrite refusal.
Transcript: `temp/gui-probe/smoke.txt`. Two GUI-probe unit tests, six execution
tests, six Rust tests, and `nix build` passed. All probe sessions were stopped.

Filed 685369 for the existing 60-second GUI startup-readiness deadline: it kills
a session whose plugin never starts, limiting the time available to inspect
startup dialogs. The present commands work while its compositor is alive;
changing that lifecycle policy is separate work.

## 2026-09-13 — Reference traversal and import caller verification

Implemented 2wrz2e's `xrefs`, `refs` and `callers` as Python command scripts with
separate request kinds on the existing worker. Shared exact-name resolution and
page helpers stay in `analysis.py`; `references.py` handles import normalization
and reference text. Python prints direction, code/data source kind, call/reference
semantics, counts and continuation. Rows remain lean; no envelope fields or error
taxonomy were added. Retired the guide's Import callers Python recipe in favor
of the commands and documented the reference contract in design.md.

The address decision is exact: `xrefs main+1` queries that byte, while `refs`
resolves the containing function. Outbound references are scoped to analyzed
basic-block ranges, excluding gaps. Byte-wise queries preserve user data
references inside instructions. Code/data classify the source: instructions
referencing globals are code references. `callers` normalizes an import name or
any of its stub/slot/external addresses to the same import group, excludes its
own stubs, and independently counts resolved call sites and code references.
Inbound output states that zero references is not proof of no callers.

Started Binary Ninja 6.0.10601 Personal in the checkout's `.binja`, opened
`temp/samples/a/sample` and reused `temp/typed/bash`, the scratch copy of the
requested bash 5.3p9 executable. Neither binary was executed. Captured the guide
recipe before replacing it, then compared each command's complete call-site set
and both counts against it. All matched:

| Bash import | Resolved call sites | Code references, stubs excluded |
| --- | ---: | ---: |
| malloc | 47 | 47 |
| free | 1,045 | 1,045 |
| strlen | 563 | 563 |
| memcpy | 41 | 41 |

Each import's three representation addresses also returned the same counts and
normalized address set. Sample `xrefs` matched native `get_code_refs` and
`get_data_refs`: `main` at `0x40122e` had 1/0 code/data references;
`__dso_handle` at `0x404008` had 1/1, `g_entities` at `0x404120` had 7/0, and
`_typeinfo_for_Entity` at `0x403ca8` had 0/2. Sources outside functions are
explicitly reported without a containing function. Sample `refs main` found
108 code references. Bash's largest function, `read_token.constprop.0`, had
2,502 outbound code references; a full query took about 60 ms including the CLI.

Retained the 64-row default. Measured every page for `callers free`,
`callers strlen`, `xrefs free`, and `refs read_token.constprop.0`. Maximum
stdout/result bytes were respectively 3,992/6,697, 3,759/6,464, 3,551/7,724,
and 1,590/4,200, all below the 16,384-byte inline threshold. Scratch recipe,
command records, comparisons and measurements are under `temp/references/`.
No new peer code was borrowed.

`cargo test` passed all six checks; Python execution/protocol/API-index suites
passed 6/5/4. `nix build` succeeded, then the installed smoke command
`python3 tests/smoke.py --binja ./result/bin/binja --sample temp/samples/a/sample`
passed in `/tmp/binja-smoke-pw81vxh8`. New coverage compares inbound references
with native queries and outbound edges with range queries plus inverse lookup;
checks import aliases and stub exclusion against the recipe; adds a user
reference on a non-call instruction and proves only the code-reference count
increases; and checks data sources inside functions, exact interior addresses,
ambiguity, pagination, text recovery, no-wait requests and empty-result warnings.
Existing inspection, transport, save/reopen and shutdown checks still pass.
Verification covered x86-64 ELF binaries. Stopped the checkout GUI cleanly.

## 2026-09-13 — Inventory commands and reference output polish

Implemented fm4yyw's `info`, `functions`, `imports` and `strings` with distinct
request kinds on the existing worker. They reuse the resolver module's page
helpers and the 64-row default. `inventory.py` shares only text filtering and
page headers; command scripts retain their native API queries and rendering.
No envelope changes, cursor state, new dependencies or peer code were added.
The guide's Inventory Python recipe was replaced with command usage and the
typed contract was extended in design.md.

First applied the two live-review fixes: `refs` now includes nullable `to_symbol`
from the native exact-address symbol lookup, and text places its name beside
the destination address. Sample's first edge now reads
`0x40125b -> __builtin_memset @ 0x4043f8`. Empty totals print `0 rows`; requests
past the end of a nonempty list retain the offset/total wording.

The inventory decisions are explicit: functions default to address order;
size is descending and name is lexicographic, with deterministic ties.
`--match` is a case-insensitive substring over displayed names or decoded string
values. Functions alternatively accept `--regex PATTERN`, using Python regex
search and its native case rules. Filtered results carry both `page.total` and
`total_available`. Info's scalar summary repeats on each page, while libraries,
segments and sections share one tagged row sequence and one offset. Segment
file offsets are distinguished from virtual addresses and all ends are exclusive.
Import rows preserve the recipe's separate stub/slot/external representations
and `lookup_imported_object_library` attribution, with an explicit warning that
the type library does not identify the runtime provider. Strings retain full
native decoded values and byte lengths, quoting control characters in text.

Started Binary Ninja 6.0.10601 Personal successfully in the checkout's `.binja`.
Opened `temp/samples/a/sample` and the existing scratch copy `temp/typed/bash`;
neither executable was run. Compared every inventory row with independent
native queries, including the retired import recipe's type-library lookup.
Reconstructed all inventories through default-sized pages and compared all
three function sort orders against the full native function set:

| Binary | Functions | Import symbols | Strings | Libraries / segments / sections |
| --- | ---: | ---: | ---: | --- |
| sample | 29 | 22 | 52 | 4 / 7 / 27 |
| bash | 2,046 | 650 | 5,785 | 2 / 7 / 27 |

Bash's largest function is `read_token.constprop.0`, 17,199 `total_bytes`.
`functions --regex '^read_'` found 11; `imports --match MALLOC` found three;
`strings --match ERROR` found 81, all matching native values. The malloc slot
at `0x4f2c38` reports type library `libc_x86_64.so.6`, while its stub and external
symbol report unknown, as in the recipe.

Measured every 64-row page. Bash's maximum stdout/result sizes were
2,497/4,754 bytes for info, 2,876/5,109 for functions, 4,806/7,089 for imports,
and 45,810/48,372 for strings. Two string pages spill beyond the 16,384-byte
inline threshold; retrieval preserves their full values. Retained 64 rows and
the existing artifact behavior. All sample pages stayed inline (maximum JSON
4,943 bytes). Native inventories, page reconstruction and size/filter evidence
are under `temp/inventory/`.

All six Rust tests and Python execution/protocol/API-index checks (6/5/4) passed.
`nix build` succeeded, followed by
`python3 tests/smoke.py --binja ./result/bin/binja --sample temp/samples/a/sample`
in `/tmp/binja-smoke-uy536b1g`. Added checks for destination symbols and empty
footers; native inventory contents and type libraries; all function sort orders;
substring/regex filtering, invalid patterns and flag conflicts; pagination,
no-wait recovery and human output. Existing screenshot/input, reference,
inspection, transport and save/reopen checks passed. Verification covered
x86-64 ELF binaries. Stopped the checkout GUI cleanly. No follow-ups were needed.

## 2026-09-13 — Cached stable update notices (t7h2fr)

Probed the pinned Personal 6.0.10601 distribution through its managed GUI with
`set_auto_updates_enabled(False)` and both `network.enableUpdates` and
`network.enableUpdateChannelList` still false. Those settings suppress automatic
checks; explicit native channel queries nevertheless contact the network.
Scratch scripts, syscall traces, and the final smoke transcript are under
`temp/update-probe/`; disposable probe states used `/tmp/binja-update-*`.

| API | Observed behavior |
| --- | --- |
| `UpdateChannel[...]` / enumeration | Cold metadata lookup made DNS and HTTPS requests in about 1.03 s. Repeated enumeration used the process cache in under 0.1 ms. The stable channel is `release-personal`, not `Stable`. |
| `latest_version_num` | Reads the channel object's Python field; no additional native/network call. |
| `latest_version` / `versions` | Native channel-version lookup; warm reads took about 0.1 ms. A cold lookup attempted the network and failed after 10.003 s against a proxy that never replied. |
| `updates_available` | Repeated calls made HTTPS requests even with channel metadata cached, took 1.6–3.2 s, and rewrote the updater preference manifest under `bn/update/`. Kept out of the implementation. |
| `get_time_since_last_update_check` | Local preference read, returning elapsed seconds since `last_check`; with `last_check=0`, returned roughly the current Unix time. Explicit metadata and availability calls did not advance that field. It is not the notice's check timestamp. |
| `is_update_installation_pending` | Local preference read; false throughout. Describes a downloaded installation, not a release notice. Kept out of availability decisions. |

The real stable metadata was `6.0.10601 personal`, matching the installation.
The same native response included historical `5.3.9757 personal`; tests model
that older installation for the available case. No future release was invented
and no download/install API was called. A trace of the production startup query
showed no file writes by its query thread and zero write opens in the immutable
vendor directory. Startup's existing auto-update disable call writes a 74-byte
preference manifest (`auto=false`, `last_check=0`, `pending=false`); the metadata
query left it unchanged. `nix-store --verify-path` confirmed the vendor contents.

Implemented a notice in `cache/updates.json`, read by the supervisor so it also
survives unavailable GUI RPC. Start and running-session status expose the installed
and latest stable versions, channel, available/current/unknown result, check and
expiry times, error, and derived stale flag. Successful results last 24 hours;
errors last one hour. A new session checks once if that cache is absent, expired,
or belongs to a different installation. Status and reused starts never initiate
a network query. Version comparison uses numeric components of the stable
version; unsupported version text remains unknown.

Checks run outside the UI and serialized analysis worker. A five-second notice
deadline records unknown and discards any eventual result. This bounds reporting,
not native cancellation: the API exposes no cancellation argument, so its single
daemon query can remain outstanding until the native transport returns (10 s in
the stalled-proxy experiment) or the GUI exits. It cannot spawn retries or publish
a late result. No extra runtime process, dependency, or substitute updater was
introduced. A real two-byte x86 function completed analysis in 0.197 s while a
native metadata query was stalled; the smoke suite now exercises that sequence.

Unit tests cover cached available/current/unknown, expiry, changed installation,
malformed data, the auto-update guard, unrecognized versions, and late-result
rejection. `nix build` and the full installed smoke suite passed, including the
stalled-proxy timeout, concurrent native analysis, reused start, stale/corrupt
caches, cache persistence across restart, and the notice with every GUI thread
stopped by SIGSTOP.

The first full smoke run exposed a typed-IL inconsistency on the NixOS coreutils
multicall ELF (`/run/current-system/sw/bin/true`): a blank HLIL separator row
carried the IL index of a neighboring instruction while its address was null, so
the smoke test's index-to-address map lost a real address. Blank rows now carry
neither address nor IL index, and the smoke test asserts that pairing.

## 2026-09-13 — Editing prerequisite: native undo in the GUI process

Before implementing c6z866, started Binary Ninja 6.0.10601 Personal and ran
`temp/editing/undo-experiment.py` on sample's main through the existing
`binja-worker`. Ungrouped name/comment writes each created an undo entry;
`bv.undo()` reverted only the latter. Explicit `begin_undo_actions()` and
`commit_undo_actions(id)` grouped both writes into one entry. Worker-side commit
took about 30 microseconds; undo and redo restored both values after analysis.
An empty group after undo preserved both stacks. A UI-thread rename invoked
through `on_ui` and a worker-side comment also shared one group and undid
together. No UI-thread grouping or workaround was needed, so the request
wrapper is viable. Evidence: `temp/editing/undo-experiment.json`.

Native entries are ordered oldest to newest; their actions expose
`summary_text`. Some summaries use the function's current name, so the undo
command should capture them before reverting. Even writing an unchanged comment
records an action; typed commands should avoid setters when the requested value
already matches. These are native undo semantics, not a rollback guarantee.

The second prerequisite was completed before command implementation. Added a
native proto/retype guide recipe and exercised its operations through
`temp/editing/types-recipe.py`. Setting `_Z11find_entityj` to
`void* find_entity(uint32_t entity_id)` with `set_user_type`, followed by
`update_analysis_and_wait`, preserved its symbol name and changed the fresh HLIL
comparison from `arg1` to `entity_id`. Retyped main's real stack local `var_198`
(native ID `0x7ffffffe6800023`, StackVariableSourceType/index 35/storage -408)
from `int32_t` to `uint32_t`. Reacquiring it by ID after analysis showed the new
type and `uint32_t var_198 = 0` in fresh HLIL. Both edits were undone after the
probe. The recipe and before/after evidence are retained in `temp/editing/`.

A parsed function type and its applied native type can compare unequal despite
identical rendered text. No-op detection should compare native rendered types,
not Type object equality; it should not turn equal inferred types into user
overrides. A type name shown by analysis need not be a declared parser type:
`struct Entity` was not parseable in this view. The recipe uses declared types
and the command will return parser diagnostics rather than guess a declaration.

## 2026-09-13 — Typed edits, undo grouping, and persistence verification

Implemented `rename`, `comment`, `proto`, `retype`, `declare --file` and `undo`
after the two prerequisite experiments above. They use the existing command
scripts, worker, target resolver, readiness gate and text/JSON split. Results
are small readback records with `changed`, field values and native identity;
they are not paged listings. No preview, state snapshot/diff, automatic rollback,
new dependency or borrowed peer implementation was added.

The undo decision is to wrap retained-target execution in begin/commit, on the
worker, with `undo` excluded. The wrapper is localized to `execute()` and commits
in `finally`, before result serialization, so failed scripts retain undoable
partial edits. No changes touch targets.py or the stop path. No-op typed edits
avoid setters; native empty groups leave undo/redo stacks intact. `undo` captures
the last entry's action summaries before reverting and reports the remaining
entry count after analysis. History belongs to the file and includes GUI edits.

Prototype edits preserve the function's symbol name, even if the C declarator
uses another name. Function/variable type no-ops compare rendered native types,
so an equal inferred type is not promoted to a user override. Variable selection
accepts a unique exact name or native `id:0xHEX` / `id:DECIMAL`; errors list
ambiguous candidates with source/index/storage. Retype reacquires the variable
by native ID after analysis. Function names and exact starts select function
comments; other addresses select view comments. Declaration files install named
types, rejecting function/variable declarations; relative includes use the
header's directory. Declarations use native structural equality, which detects
a changed struct member even if the displayed name and total width stay equal.

Exercised all commands in the GUI process on sample. Repeated rename, comment,
prototype, local-type and declaration requests returned no-op without adding
undo entries. One undo reverted a grouped Python rename/comment; declaration
undo reverted both types in a header. Main's native local `var_198`, ID
`0x7ffffffe6800023`, was retyped to `uint32_t`; fresh HLIL showed
`uint32_t var_198 = 0`. Saved `temp/editing/verified.bndb`, stopped and restarted
the session, then compared readbacks: function name `editing_main`, function
and interior-address comments, `void*(uint32_t entity_id)` prototype on
`_Z11find_entityj`, the native local ID/type and its affected HLIL, and the
`EditingPair`/`EditingWord` declarations all persisted unchanged. Evidence is
under `temp/editing/`, including before-save, after-reopen and persistence JSON.

`nix build` and the full installed smoke suite passed after correcting a stale
accessor in the new test (`StructureType.members` is direct). New coverage
includes readback and no-op history counts, request-ID deduplication, human
rendering, empty undo, both comment scopes, prototype name preservation, a real
local's updated HLIL, ambiguous/invalid variable selectors, structural declaration
changes and undo, header rejection, a failed two-edit Python request undone as one
entry, and rename/comment persistence through save/reopen. Verification covered
x86-64 ELF on Binary Ninja 6.0.10601 Personal.

Promoted the tested recipe to typed-command usage, retaining native variable
inventory and the post-analysis HLIL workflow in the guide, and updated the
small-record/undo contract in design.md. The native recipe remains as disposable
evidence in `temp/editing/tested-guide-recipe.md`.

## 2026-09-13 — Managed per-file close (vmnn2h)

Implemented `close HANDLE|PATH [--force]` as a packaged command on the existing
worker. Admission refuses queued, running, or readiness-waiting work for any
view of the file; an admitted close prevents new work for those views. Force
only permits discarding unsaved changes. The worker pauses for the UI callback,
which takes the admission lock and repeats the target and pending-work checks
before closing. No supervisor cooperation is needed. Close skips analysis
readiness and must remain outside an editing command's undo action.

Native probes on Personal 6.0.10601 found that `FileContext.close()` leaves GUI
tabs behind, while `UIContext.closeTab()` retires them and presents Analysis
Modified or File Modified prompts for unsaved work. The latter has no force
argument. A timer scoped to forced close selects Discard on those native
prompts; an existing modal causes refusal before the timer starts. A forced
close with byte edits and held analysis completed in 0.247 seconds.

File contexts can survive tab removal through Qt deferred deletion or retained
view references. Registry refresh now requires an attached GUI tab before
including a file's data views, so analyzed and Raw handles expire together
immediately. Queued requests retained across an external GUI close fail with
"handle expired" during execution revalidation. Reopening assigns new handles.

`cargo test`, the Python unit checks, and the live bridge checks passed.
`nix build` and
`python3 tests/smoke.py --binja ./result/bin/binja --sample temp/samples/a/sample`
passed. The smoke additions exercise running and queued work refusal with and
without force, sibling-view coordination, cancellation before close, refusal
with an existing modal, unsaved byte and analysis edits, forced discard without
changing the input file, close receipt recovery without replay, later and
already-queued expired handles, missing and ambiguous selectors, relative-path
and clean BNDB close, analysis on hold, human output, consistent target/status
counts, and clean stop. Probe scripts and transcripts are under
`temp/close-probe/`.

## 2026-09-13 — Optional GUI startup deadline

Added `start --no-startup-deadline` for new sessions. It bypasses the supervisor's
60-second GUI handshake deadline while preserving readiness polling, compositor
controls, and child-exit cleanup. The CLI still waits at most 70 seconds. Startup
exit errors now name both `logs/binaryninja.log` and `logs/supervisor.log`; the
packaged guide describes the flag and recovery sequence.

`tests/startup.py` copies the installed plugin and inserts a Qt modal before its
receiver starts. Without the flag, the CLI failed after 65.4 seconds, including
its exit grace; both child groups and all four session endpoints were gone.
With the flag, the CLI timed out at 70.0 seconds while status still reported
`running: true`, `ready: false`, and unknown GUI state. The captured modal matched
the earlier screenshot byte for byte. Compositor Return dismissed it, the same
generation became usable, and Python returned 42. Separate pre-readiness checks
verified force-stop, GUI exit, and compositor exit, including group and endpoint
cleanup. Screenshots and receipts: `/tmp/binja-startup-i1n5m37w`.

`nix build`, all seven Rust tests, and the full installed smoke suite passed
(`/tmp/binja-smoke-4wkfy379`). Transcripts are under `temp/startup-deadline/`.
The modal is a deterministic test fixture; no real license or update dialog was
triggered.

## 2026-09-13 — Guide compression with cold subagents (dxp6mv)

Five fresh subagents (GPT, Fable, GPT, Fable, GPT) each read the current guide
cold from an external workspace, ran a live exercise against `samples/target`
or a bash binary, and reported leaks, cuttable prose, rules they needed, and
false claims. Each round's report fed a rewrite before the next reviewer.
Exercises covered rename/prototype/save/reload, reference traversal and queue
timeout recovery, multi-target retype/undo/close and queue saturation,
declare/proto/comment/linear disasm/analysis hold, and a final verification
of the rewritten claims.

Results with the `o200k_base` proxy: 4792 tokens, 415 lines, before; 2621
tokens, 258 lines, after. What went: three copies of the pagination rules,
JSON field inventories for request and page records, the custom `--request-id`
grammar (now only in `--help`), receipt and exit-code narration, the
`target_snapshot` paragraph, the persistence recipe, "remains"/"still"
wording, and every sentence that restated a notice the tool prints on each
call (HLIL anchors, code/data source, `total_bytes`, type-library column,
exclusive ends, zero-references caveat). Two claims were corrected on
evidence: `declare` installs an included type only when a top-level
declaration uses it, and linear `disasm` carries no symbols, comments or
variable annotations. "No architecture specifics" for LLIL was softened to
"normalized operations" after a reviewer showed `rbp`/`fsbase` in the output.

Rules every trial subject cited as necessary and kept verbatim in meaning:
hex offsets in `symbol+offset`, the analysis-hold resume one-liner, no
parent-directory search for `.binja`, the Raw view explanation, `py` per-request
globals, exit 2 recovery, one undo entry per request, and `callers` folding
import symbols. Follow-ups filed from tool observations: jxc5gg (cap-rejected
IDs get the generic unknown-ID warning), 33qaa7 (dataclass fields missing from
`api members`), sq389d (hold error lacks the resume command), aqxvch (`declare`
no-op on include-only headers).

Verification: `nix build`, installed `binja skill` matches `binja/guide.md`,
and the installed smoke suite passed from `/tmp/binja-smoke-2uoov4wm`. Reports,
task briefs, and guide versions v0 through v4 are under
`temp/guide-compression/`.
