---
tier: objective
---
# Customer feedback: export multiple functions with rendered code and analysis status

Customer: the agent maintaining `~/projects/honglass`, during the HoN Reborn
0.12.8.1 compatibility investigation. The user requested this feedback be
filed; the command design remains a proposal.

The investigation reduced 2,917 live cvars to 11 distinct string getters and
needed to inspect several related functions in k2.dll and shared.dll. A
`binja py` script batched function exports into JSON, collecting HLIL, LLIL,
disassembly and analysis/skip status. This avoided a separate command per
function and preserved evidence outside disposable session state, but required
recreating rendering and metadata plumbing.

Observed friction:

- Flattening HLIL instructions into strings lost indentation and made control
  flow harder to assess than the built-in decompiler rendering.
- Manually converting hexadecimal RVAs into JSON numbers and assembling the
  argument payload introduced transcription/JSON errors. Passing hex strings
  and converting them inside the script worked better.
- The script guessed `.name` on `bv.analysis_info.state`, which was an integer.
  The typed commands already handle this sort of presentation detail.

Consider a batch export interface accepting multiple function selectors, with
hexadecimal addresses and explicit RVA/base handling, reusing existing code
renderers. Useful output would group selected HLIL/MLIL/LLIL/disassembly by
function, retain indentation and instruction addresses, and include resolved
identity plus completed/skipped/unavailable analysis status for each function.
It should support saving evidence to a caller-selected path outside session
state. Preserve existing analysis waits and request-ID recovery behavior.

Assess by reproducing a multi-function export from a real DLL: the result
should be usable for code review without a custom rendering script, and any
missing/skipped function should be explicit. No batch exporter was implemented
as part of this feedback filing.
