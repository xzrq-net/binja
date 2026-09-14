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
