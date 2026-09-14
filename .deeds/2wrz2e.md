---
blocked-by: [5bkxzv]
---
# Add reference traversal commands: xrefs and callers

- `xrefs ADDRESS|FUNCTION`: inbound references, code and data listed
  separately, each with the referencing function and address. References are
  not calls.
- `refs FUNCTION`: outbound code and data references from a function.
- `callers NAME|ADDRESS`: resolved call sites. For imports, collect the stub,
  the address slot, and the external symbol by name, exclude the stub's own
  reference, and resolve through `get_callees`. Report call-site count and
  code-reference count separately, as the guide's import-callers recipe does.
  Zero discovered references is not proof of no callers (unresolved indirect
  calls); say so in the output.

Reuse resolution and the output contract from 5bkxzv. Dimensions must be
explicit in output: inbound vs outbound, code vs data, call vs reference.

Evidence: trial B would have overcounted callers by including the import stub
and asked for a caller-counting command (temp/trials/reportB.md:84). The
guide's "Import callers" recipe is the semantics to encode; shorten or retire
it once the command exists. bn separates `xrefs`, `refs`, and `callsites`; its
`--caller-static` return-address workflow stays deferred until requested.

Verify counts against the recipe on `bash` imports (malloc, free, strlen,
memcpy were the trial's set).
