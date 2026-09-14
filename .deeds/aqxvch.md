# Report skipped included types in declare instead of a bare no-op

Observed 2026-09-13 by a cold trial subject (Fable) during the guide
compression review, Binary Ninja 6.0.10601. `declare --file types.h` where
`types.h` only `#include`s another header (defining `struct variable` /
`SHELL_VAR`) and declares an unrelated struct installs only the unrelated
struct. That matches `parse_types_from_string` semantics (included types are
parsed as context, installed only when the header's own declarations use
them), and the guide now says so. But an include-only header prints
`declare  no-op` with no rows, indistinguishable from "already present", and
the output never mentions the included types it parsed and skipped.

Options: list parsed-but-skipped type names in the readback, or make the no-op
line say "no declarations in HEADER" when the parse yielded nothing. Update the
guide's `declare` sentence if the installation rule changes.
