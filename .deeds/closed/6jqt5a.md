# Label snapshot fields and client timeouts in request output

Request records carry the target as resolved at submission. After `save`, the
completion line shows the old input path while the next line says
`Saved .../x.bndb`; after a long `open`, the record's `target.analysis` says
`DiscoveryState` while `result.analysis` and `targets` say `IdleState`. Subjects
worked it out but called it contradictory. Name the snapshot (for example
`target_at_submission`) or show current target state.

On a client wait expiry, `--json open` exits 2 with a `running` record and no
field saying the wait expired; the non-JSON path prints a `Retrieve with:` hint
but the JSON path does not. Add an explicit expiry marker and the recovery
command to both. Subjects also asked for elapsed time on running requests and
some progress signal beyond the analysis state name; they could not tell slow
analysis from a stall.

Minor wording: `start` prints `— headless` while the guide describes a GUI on a
private Wayland compositor; every subject flagged the mismatch as making the
documented process model less trustworthy.

Closed: Labeled target snapshots and their capture stage, added elapsed time and explicit human/JSON client wait expiry with recovery commands, and aligned start wording with the private-compositor GUI. Built and passed the external live smoke suite; see docs/log.md.
