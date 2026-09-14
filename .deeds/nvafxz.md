# Show property writability and enum members in api show

All three usability subjects hit this. `api show Function.name` and
`Function.comment` print getter-shaped signatures (`name(self) -> str`) with no
indication that they are writable properties; subjects guessed `f.name = ...`
after a failed lookup for a setter (`Function.set_user_name`). `Function.hlil`
does say read-only, so the contrast misleads. `api show binaryninja.enums.SymbolType`
prints the class line and no members, so the values needed for
`get_symbols_of_type` had to be found through `types.Symbol`. `api search` said
"29 matches" but displayed 15 with no truncation note or way to see the rest.

## Implementation handoff

Phase A: the static index builder labels properties and writability, return
types, and enum members with literal values or unresolved source expressions.
Verified the packaged Function.name/comment/hlil and SymbolType entries. Rust
show/search rendering remains in B: default show retains one source:line
pointer; docs URL and version move to verbose.
