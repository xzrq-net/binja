# Show property writability and enum members in api show

All three usability subjects hit this. `api show Function.name` and
`Function.comment` print getter-shaped signatures (`name(self) -> str`) with no
indication that they are writable properties; subjects guessed `f.name = ...`
after a failed lookup for a setter (`Function.set_user_name`). `Function.hlil`
does say read-only, so the contrast misleads. `api show binaryninja.enums.SymbolType`
prints the class line and no members, so the values needed for
`get_symbols_of_type` had to be found through `types.Symbol`. `api search` said
"29 matches" but displayed 15 with no truncation note or way to see the rest.
