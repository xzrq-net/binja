# Add code inspection commands: decompile, il, and disasm

First typed analysis commands, and the home of the shared pieces every later
command reuses: function resolution and the output contract.

Commands:

- `decompile FUNCTION`: the decompiler's rendered pseudo-C (the GUI's language
  representation), not `str()` of HLIL instructions.
- `il FUNCTION --view hlil|mlil|llil [--ssa]`: IL listing with per-instruction
  addresses. Default view follows the guide's representation-choice section.
- `disasm FUNCTION|ADDRESS [--count N | --end ADDR]`: native disassembly,
  function-scoped by default; the linear window works without function
  analysis.

Shared resolution: FUNCTION is a symbol name, a start address, or an address
inside a function. ADDRESS accepts symbols, hex, and `symbol+offset` through
`bv.parse_expression`. Reject ambiguity (several functions by name, address in
several functions) and list the candidates; never pick the first match.
Avoid `get_functions_by_name(x)[0]` and stringifying IL instead of rendering
it; both shortcuts lose information.

Output contract, reused by every typed read command: text by default, `--json`
for the full record; a header naming the target handle, function name, and
start; bounded output with a stated way to fetch the remainder (windowing or a
follow-up command), never a silent cap; an explicit outcome when IL is
unavailable (Raw view, analysis skipped) instead of empty output. Artifact
spilling already handles size; it does not replace scoping. Preserve native
address conventions and say that HLIL line addresses are anchors, not
instruction addresses.

Evidence: all three usability-trial subjects asked for first-class listing and
decompile commands (temp/trials/reportA.md:185, reportB.md:84, reportC.md:102);
trial A needed disassembly to correct a misleading HLIL pointer type. banteg/bn exposes these; keep notices under licenses/ if code is
borrowed.

Verify against the GUI rendering for a representative function in `sample` and
`bash`. Update binja/guide.md (recipes the commands replace) and tests/smoke.py.

This is the first command that is not Python submission, so it also changes
the interface description: README.md:4 and the Scope paragraph of
docs/design.md describe the CLI as running Python and exposing API docs.
Reword them to "typed analysis commands with Python as the backstop" in the
same change, and give design.md a short section on the shared resolver and
output contract so later parts cite it instead of restating it.

## Delivery notes

The delivered contract keeps the existing request envelope: Python scripts print headers,
listings and continuation footers and return structured pages; Rust suppresses
duplicate result printing in human mode. Errors remain strings with inline
candidates. Rows contain address/text, plus il_index for IL or bytes for disasm.

Shared resolution and native listing helpers are in `binja/analysis.py`; the
output/resolution contract is documented in `docs/design.md` under "Typed
analysis commands". The default is 64 rendered rows, selected by measuring every
page of all representations of bash's largest function, including SSA. Verification
and page-size measurements are in the 2026-09-13 code inspection entry in
`docs/log.md`. The installed-package smoke suite passes. No peer implementation
code was added, and no new license notice was needed.

Closed: decompile, il (MLIL default), and disasm delivered through the open/save command-script pattern; shared resolver and 64-row page contract in binja/analysis.py and docs/design.md; verified against GUI rendering on sample and bash.
