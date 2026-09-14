---
tier: nit
---
# Handle a closed stdout pipe without a panic

`binja skill | head -1` prints the first line, then the Rust runtime panics with
"failed printing to stdout: Broken pipe" and exits 101, because Rust ignores
SIGPIPE and `println!` panics on EPIPE. Agents pipe `skill` and `api search`
into `head` routinely. Either restore the SIGPIPE default disposition at startup
or write through a handle that treats EPIPE as a quiet exit 0. The Python client
raised a BrokenPipeError traceback in the same case, so this is noise rather
than a regression.

Closed: SIGPIPE default disposition restored at CLI startup (not in the supervisor); binja skill | head exits 141 quietly instead of panicking.
