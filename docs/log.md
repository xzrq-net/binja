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
